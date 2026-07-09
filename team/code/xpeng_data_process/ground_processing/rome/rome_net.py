import math
import os
import cv2
import numpy as np
import torch
from .models.loss import CELossWithMask, L1MaskedLoss
from .models.pose_model import ExtrinsicModel
from pytorch3d.loss import mesh_laplacian_smoothing
from .utility.nvdiff_renderer import NvdiffRenderer as Renderer
from torch.optim.lr_scheduler import MultiStepLR, ExponentialLR
from torch.utils.data import DataLoader
from .utility.pack_gta_input import pack_recon_result
from .utility.image import render_semantic
from .utility.eval_helper import *
from .utility.visualizer import (
    Visualizer,
    draw_trajectory,
    save_cut_label_mesh,
    save_cut_mesh,
    draw_input_pose,
)
from .utility import misc
from .datasets.xnet import XNetDataset
from pytorch_lightning import LightningModule
from xpilot_lightning import const
_TORCH_GREATER_EQUAL_2_0 = torch.__version__ >= const.PYTORCH_UPGRADE_VERSION


def cal_apt_batch_size(num_vertex):
    """
    Calculate the adaptive batch size according to the number of vertices.
    """
    batchsize = int(9.0 * 1e7 / num_vertex)
    return batchsize


class RomeNet(LightningModule):
    def __init__(self, configs):
        super().__init__()

        exp_dir = self.exp_dir = configs["exp_dir"]
        self.rome_output_dir = configs['rome_output_dir']
        os.makedirs(self.rome_output_dir, exist_ok=True)

        self.automatic_optimization = False
        self.save_rendered_image = configs.get("save_rendered_image", False)
        self.grid_guassian_smoothing = configs.get("grid_guassian_smoothing", True)
        self.draw_cam_traj_on_bev_image = configs.get('draw_cam_traj_on_bev_image', False)

        dataset = XNetDataset(configs)
        dataset.enable_all_data()
        pose_xy = np.array(dataset.ego_pose_xyz)[:, :2, 3]
        self.offset_pose_xy = pose_xy - np.asarray([configs["center_point"]["x"], configs["center_point"]["y"]])
        self.dataset = dataset
        draw_input_pose(configs, dataset)

        self.build_bev_camera(configs)

        self.only_save_final_epoch_result = configs.get("only_save_final_epoch_result", True)
        self.log_every_n_steps = configs.get('log_every_n_steps', 10)
        self.mesh_verts_dir = os.path.join(self.rome_output_dir, "mesh_verts")
        os.makedirs(self.mesh_verts_dir, exist_ok=True)

        self.renderer = Renderer()
        self.configs = configs
        self.blend_image_list = defaultdict(list)
        self.all_frame_kpi = {}
        self._build_model()

    def current_rank(self):
        if torch.distributed.is_initialized():
            return torch.distributed.get_rank()
        return 0

    def build_grid(self, configs):
        # Load grid and optimization toggles
        optim_dict = dict()
        for optim_option in ["vertices_rgb", "vertices_label", "vertices_z", "rotations", "translations"]:
            if configs["lr"].get(optim_option, 0) != 0:
                optim_dict[optim_option] = True
                print("{} optimization is ON".format(optim_option))
            else:
                optim_dict[optim_option] = False
                print("{} optimization is OFF".format(optim_option))

        # Choose Different grid generator according to configs
        if optim_dict["vertices_rgb"] and optim_dict["vertices_label"] and (not optim_dict["vertices_z"]):
            from .models.voxel import SquareFlatGridRGBLabel as SquareFlatGrid
        elif optim_dict["vertices_rgb"] and (not optim_dict["vertices_label"]) and optim_dict["vertices_z"]:
            from .models.voxel import SquareFlatGridRGBZ as SquareFlatGrid
        elif optim_dict["vertices_rgb"] and (not optim_dict["vertices_label"]) and (not optim_dict["vertices_z"]):
            from .models.voxel import SquareFlatGridRGB as SquareFlatGrid
        elif (not optim_dict["vertices_rgb"]) and optim_dict["vertices_label"] and (not optim_dict["vertices_z"]):
            from .models.voxel import SquareFlatGridLabel as SquareFlatGrid
        elif (not optim_dict["vertices_rgb"]) and optim_dict["vertices_label"] and optim_dict["vertices_z"]:
            from .models.voxel import SquareFlatGridLabelZ as SquareFlatGrid
        elif optim_dict["vertices_rgb"] and optim_dict["vertices_label"] and optim_dict["vertices_z"]:
            from .models.voxel import SquareFlatGridRGBLabelZ as SquareFlatGrid
        else:
            raise NotImplementedError("No such grid generator, please check your config[\"lr\"]")

        mesh_z_scale = configs.get("mesh_z_scale", 1.0)
        if optim_dict["vertices_z"]:
            grid = SquareFlatGrid(configs, self.offset_pose_xy, self.dataset.num_class, configs["pos_enc"])
        else:
            grid = SquareFlatGrid(configs, self.offset_pose_xy, self.dataset.num_class, z_scale=mesh_z_scale)

        self.optim_dict = optim_dict
        self.grid = grid

        mesh_prior_z_npy = os.path.join(configs["rome_output_dir"], "mesh_prior_z.npy")
        reuse_mesh_prior_z = configs.get("reuse_mesh_prior_z", True)
        mesh_prior_z_initialized = False
        if reuse_mesh_prior_z and os.path.exists(mesh_prior_z_npy):
            mesh_prior_z = np.load(mesh_prior_z_npy)
            if mesh_prior_z.shape[0] == self.grid.vertices_xy.shape[0]:
                self.grid.init_prior_vertices_z(torch.from_numpy(mesh_prior_z))
                mesh_prior_z_initialized = True

        if not mesh_prior_z_initialized:
            self.grid.init_vertices_z(self.dataset.ego_pose_xyz[:, :3, 3], self.grid_guassian_smoothing)
            if self.current_rank() == 0:
                print(f"Save mesh_prior_z: {mesh_prior_z_npy}")
                np.save(mesh_prior_z_npy, self.grid.prior_vertices_z)

    def build_extrinsic_models(self, configs):
        print(f'recon cam num: {len(self.dataset.cam_name_to_cam_index_map)}')
        self.extrinsics = ExtrinsicModel(configs, self.optim_dict["rotations"], self.optim_dict["translations"], num_camera=(len(self.dataset.cam_name_to_cam_index_map)))

    def _build_model(self):
        self.build_grid(self.configs)
        self.build_extrinsic_models(self.configs)
        self.configure_optimizers()

    def build_bev_camera(self, configs):
        cx = configs["bev_x_length"] / 2
        cy = configs["bev_y_length"] / 2
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        world2camera = torch.eye(4, dtype=torch.float64, device=device)
        world2camera[:3, 3] = torch.Tensor([-cx, cy, 0.0])
        world2camera[1, 1] = -1.0
        self.bev_render_params = {
            "world2camera": world2camera[None],
            "focal_length": (1.0 / torch.tensor([cx, cy], dtype=torch.float64, device=device))[None],
            "principal_point": torch.zeros(1, 2, dtype=world2camera.dtype, device=device),
            "image_shape": torch.Tensor([configs["bev_y_pixel"], configs["bev_x_pixel"]])[None],
            "camera_model": "orthographic",
        }


    def configure_optimizers(self):
        configs = self.configs
        parameters = []
        z_parameters = []
        pose_parameters = []
        lr_option = configs.get("lr_option", "multi_step")

        for param_key, param in self.grid.named_parameters():
            if "vertices_rgb" in param_key or "vertices_label" in param_key:
                parameters.append({"params": param, "lr": float(configs["lr"][param_key.split('.')[-1]])})
            else:
                z_parameters.append({"params": param, "lr": float(configs["lr"]["vertices_z"])})

        for param_key, param in self.extrinsics.named_parameters():
            pose_parameters.append({"params": param, "lr": float(configs["lr"][param_key])})

        self.optimizer = torch.optim.Adam(parameters)
        if lr_option == "multi_step":
            self.scheduler = MultiStepLR(self.optimizer, milestones=configs["lr_milestones"], gamma=configs["lr_gamma"])
        elif lr_option == "exponential":
            self.scheduler = ExponentialLR(self.optimizer, gamma=configs["lr_gamma"])
        else:
            raise NotImplementedError
        if self.optim_dict["vertices_z"]:
            self.z_optimizer = torch.optim.Adam(z_parameters)
        if self.optim_dict["translations"] or self.optim_dict["rotations"]:
            self.pose_optimizer = torch.optim.Adam(pose_parameters)

        self.loss_fuction = L1MaskedLoss()
        self.depth_loss_fuction = L1MaskedLoss()
        self.CE_loss_with_mask = CELossWithMask()

    def train_dataloader(self):
        train_dataloader = DataLoader(self.dataset, batch_size=self.configs["batch_size"],
                                    num_workers=self.configs["num_workers"],
                                    shuffle=True,
                                    pin_memory=True,
                                    drop_last=True)

        return train_dataloader

    def val_dataloader(self):
        val_dataloader = DataLoader(self.dataset, batch_size=self.configs["batch_size"],
                                    num_workers=self.configs["num_workers"],
                                    shuffle=False,
                                    pin_memory=True,
                                    drop_last=True)

        return val_dataloader

    def training_epoch_start(self):
        pass

    def training_step(self, batch, batch_idx):
        loss_dict = dict()
        if self.optim_dict["vertices_rgb"]:
            loss_dict["render_loss"] = 0
        if self.optim_dict["vertices_label"]:
            loss_dict["seg_loss"] = 0
        if self.optim_dict["vertices_z"]:
            loss_dict["laplacian_loss"] = 0
            if self.configs["use_mvs_supervise"]:
                loss_dict["depth_loss"] = 0
        loss_dict["total_loss"] = 0

        sample = batch
        configs = self.configs
        epoch = self.current_epoch

        ### Forward
        for key, ipt in sample.items():
            if hasattr(ipt, "clone"):
                sample[key] = ipt.clone().detach()

        mesh = self.grid(batch_size=configs["batch_size"])
        world2camera = sample["world2camera"]
        if epoch >= configs["extrinsic"]["start_epoch"]:
            world2camera = self.extrinsics(sample["camera_idx"]) @ world2camera

        render_params = {
            "mesh": mesh,
            "world2camera": world2camera,
            "focal_length": sample["focal_length"],
            "principal_point": sample["principal_point"],
            "image_shape": sample["image_shape"],
        }

        images_feature, depth = self.renderer(render_params)
        silhouette = images_feature[:, :, :, -1]
        silhouette[silhouette > 0] = 1
        silhouette = torch.unsqueeze(silhouette, -1)
        mask = silhouette
        mask_c = mask.clone()
        if "static_mask" in sample:
            static_mask = torch.unsqueeze(sample["static_mask"], -1)
            mask *= static_mask
        if "static_mask2" in sample:
            static_mask2 = torch.unsqueeze(sample["static_mask2"], -1)
            mask_c *= static_mask2

        total_loss = 0
        gt_depth = sample["depth"]
        mask_depth = gt_depth > 0
        try:
            gt_depth_max = (gt_depth*mask)[mask_depth].max()
        except:
            gt_depth_max = 10
        gt_depth_mask = depth < gt_depth_max # torch.where(gt_depth > 0, depth < gt_depth + 10, torch.tensor(False, device=gt_depth.device))
        if self.optim_dict["vertices_rgb"]:
            gt_image = sample["image"]
            images = images_feature[..., :3]
            render_loss = self.loss_fuction(images, gt_image, mask * gt_depth_mask)
            total_loss += render_loss.mean()

            if self.save_rendered_image:
                output_dir = os.path.join(self.rome_output_dir, "rendered_image", f"epoch_{self.current_epoch}")
                os.makedirs(output_dir, exist_ok=True)
                for i in range(images.shape[0]):
                    render_image = np.clip(images[i].detach().cpu().numpy(), 0.0, 1.0) * 255
                    gt_image = np.clip(sample["image"][i].detach().cpu().numpy(), 0.0, 1.0) * 255
                    concat_image = cv2.vconcat([render_image, gt_image])
                    image_path = "_".join(sample["image_path"][i].split("/")[-4:])
                    concat_image = concat_image[..., ::-1]
                    cv2.imwrite(os.path.join(output_dir, image_path), concat_image)

        if self.optim_dict["vertices_label"]:
            gt_seg = sample["static_label"]
            label_class = self.dataset.num_class
            images_seg = images_feature[..., (-1 - label_class):-1]
            seg_loss = self.CE_loss_with_mask(images_seg.reshape(-1, images_seg.shape[-1]),
                                              gt_seg.reshape(-1), (gt_depth_mask * mask_c).reshape(-1)) * configs["seg_loss_weight"]
            total_loss += seg_loss
        if self.optim_dict["vertices_z"]:
            if self.configs["use_mvs_supervise"]:
                depth_loss = self.depth_loss_fuction(depth.squeeze(), gt_depth.squeeze(), gt_depth_mask.squeeze() * mask.squeeze() * mask_depth.squeeze()) * configs["depth_loss_weight"]
                total_loss += depth_loss.mean()
            laplacian_loss = mesh_laplacian_smoothing(mesh[0]) * self.configs["laplacian_loss_weight"]
            total_loss += laplacian_loss

        self.manual_backward(total_loss)

        self.optimizer.step()
        if self.optim_dict["vertices_z"]:
            self.z_optimizer.step()
        if self.optim_dict["translations"] or self.optim_dict["rotations"]:
            self.pose_optimizer.step()

        self.optimizer.zero_grad()
        if self.optim_dict["vertices_z"]:
            self.z_optimizer.zero_grad()
        if self.optim_dict["translations"] or self.optim_dict["rotations"]:
            self.pose_optimizer.zero_grad()

        rank = self.current_rank()
        if rank == 0 and self.global_step % self.log_every_n_steps == 0:
            if self.optim_dict["vertices_rgb"]:
                loss_dict["render_loss"] += render_loss.mean().detach().cpu().numpy()
            if self.optim_dict["vertices_label"]:
                loss_dict["seg_loss"] += seg_loss.detach().cpu().numpy()
            if self.optim_dict["vertices_z"]:
                loss_dict["laplacian_loss"] += laplacian_loss.detach().cpu().numpy()
                if self.configs["use_mvs_supervise"]:
                    loss_dict["depth_loss"] += depth_loss.mean().detach().cpu().numpy()
            loss_dict["total_loss"] += total_loss.detach().cpu().numpy()

            for key, value in loss_dict.items():
                self.log(key, value)

    def on_train_start(self):
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.visualizer = Visualizer(device, self.configs)
        self.save_mesh_verts_features(epoch=0)

    def training_epoch_end(self, outputs):
        self.scheduler.step()
        rank = self.current_rank()
        epoch = self.current_epoch + 1
        if rank != 0 or (self.only_save_final_epoch_result and epoch != self.configs["epochs"]):
            return

        self.save_mesh_verts_features(epoch)

        with torch.no_grad():
            mesh = self.grid()

        bev_render_params = self.bev_render_params
        z_shift = torch.min(mesh.verts_padded()[..., -1]).cpu() - 0.1
        bev_render_params["world2camera"][..., 2, 3] = -z_shift
        bev_render_params["mesh"] = mesh
        bev_features, bev_depth = self.renderer(bev_render_params)
        bev_depth[..., -1] = bev_depth[..., -1] + z_shift


        # save bev depth
        bev_depth = bev_depth.detach().squeeze().cpu().numpy()
        np.save(os.path.join(self.rome_output_dir, f"bev_depth_epoch_{epoch}.npy"), bev_depth)
        if epoch == self.configs["epochs"]:
            np.save(os.path.join(self.rome_output_dir, "bev_depth.npy"), bev_depth)

        # vis bev rgb
        bev_rgb = bev_features[0, :, :, :3].detach().cpu().numpy()
        bev_rgb = np.clip(bev_rgb, 0, 1)
        if self.draw_cam_traj_on_bev_image:
            bev_rgb = draw_trajectory(bev_rgb, self.dataset, self.configs, epoch)
        cv2.imwrite(os.path.join(self.rome_output_dir, "bev_rgb_epoch_{}.png".format(epoch)), bev_rgb[:, :, ::-1] * 255)

        # vis bev semantic
        bev_seg = bev_features[0, :, :, 3:-1].detach().cpu().numpy()
        bev_seg = np.argmax(bev_seg, axis=-1)
        bev_seg = render_semantic(bev_seg)  # RGB fomat
        if self.draw_cam_traj_on_bev_image:
            bev_seg = draw_trajectory(bev_seg, self.dataset, self.configs, epoch)
        cv2.imwrite(os.path.join(self.rome_output_dir, "bev_seg_epoch_{}.png".format(epoch)), bev_seg[:, :, ::-1])
        if epoch == self.configs["epochs"]:
            cv2.imwrite(os.path.join(self.rome_output_dir, "bev_seg.png"), bev_seg[:, :, ::-1])


    def dump_optimized_cam_extrinsics(self):
        cam_name_id_dict = self.dataset.cam_name_to_cam_index_map
        cam_ids = list(cam_name_id_dict.values())
        with torch.no_grad():
            opt_extrinsics = self.extrinsics(cam_ids).detach().cpu().numpy()
        misc.dump_optimized_cam_extrinsics(opt_extrinsics, cam_name_id_dict, self.rome_output_dir)

    def on_train_end(self):
        rank = self.current_rank()
        if rank != 0:
            return

        # not save first rome result for parking
        if self.configs.get("scene", "driving") == "parking" and "bev_seg_path" not in self.configs:
            return

        self.dump_optimized_cam_extrinsics()
        print(f"Saving mesh to {self.rome_output_dir}")
        with torch.no_grad():
            mesh = self.grid()
        save_cut_mesh(mesh[0], os.path.join(self.rome_output_dir, "bev_mesh.obj"))
        save_cut_label_mesh(mesh[0], os.path.join(self.rome_output_dir, "bev_label_mesh.obj"), self.dataset.filted_color_map)

        # TODO: Please remove this later
        print(f"Saving model to {self.rome_output_dir}")
        self.grid.eval()
        self.extrinsics.eval()
        torch.save(self.grid.state_dict(), os.path.join(self.rome_output_dir, "grid_baseline.pt"))
        torch.save(self.extrinsics.state_dict(), os.path.join(self.rome_output_dir, "pose_baseline.pt"))

        ### Pack results as GTA input
        pack_recon_result(self.configs)




    def validation_step(self, batch, batch_idx):
        sample = batch
        configs = self.configs
        cam_name_to_cam_index_map = self.dataset.cam_name_to_cam_index_map
        cam_index_to_cam_name_map = {v: k for k, v in cam_name_to_cam_index_map.items()}

        for key, ipt in sample.items():
            if hasattr(ipt, "clone"):
                sample[key] = ipt.clone().detach()

        mesh = self.grid(None, configs["batch_size"])
        world2camera = sample["world2camera"]
        if configs["mode"] != "reloc":
            world2camera = self.extrinsics(sample["camera_idx"]) @ sample["world2camera"]
        render_params = {
            "mesh": mesh,
            "world2camera": world2camera,
            "focal_length": sample["focal_length"],
            "principal_point": sample["principal_point"],
            "image_shape": sample["image_shape"],
        }

        ### Inference
        images_feature, _ = self.renderer(render_params)

        ### Get static mask
        silhouette = images_feature[:, :, :, -1]
        silhouette[silhouette > 0] = 1
        silhouette = torch.unsqueeze(silhouette, -1)
        mask = silhouette
        if "static_mask" in sample:
            static_mask = torch.unsqueeze(sample["static_mask"], -1)
            mask *= static_mask
        mask = mask.detach().cpu().numpy().squeeze(3).astype(np.uint8)

        ### Get predicted RGB image
        pred_img = images_feature[:, :, :, :3]
        pred_img = pred_img.detach().cpu().numpy().squeeze()
        pred_img = (pred_img * 255).astype(np.uint8)[:, :, :, ::-1]

        ### Get predicted segmentation
        if self.optim_dict["vertices_rgb"]:
            pred_seg = images_feature[:, :, :, 3:-1]
        else:
            pred_seg = images_feature[:, :, :, :-1]
        pred_seg = pred_seg.detach().cpu().numpy()
        pred_seg = np.argmax(pred_seg, axis=-1)

        ### Get ground truth RGB image
        gt_img = sample["image"]
        gt_img = gt_img.detach().cpu().numpy().squeeze()
        gt_img = (gt_img * 255).astype(np.uint8)[:, :, :, ::-1]

        ### Get ground truth segmentation
        gt_seg = sample["static_label"]
        gt_seg = gt_seg.detach().cpu().numpy()
        gt_seg *= mask

        for b in range(images_feature.shape[0]):
            ### Calculate KPI
            frame_kpi = calculate_frame_kpi(pred_img[b], gt_img[b], pred_seg[b], gt_seg[b], mask[b])
            self.all_frame_kpi[sample["image_path"][b]] = frame_kpi

            ### Blend GT image and predicted segmentation
            vis_pred_seg = render_semantic(pred_seg[b])[:, :, ::-1]
            blend_image = cv2.addWeighted(gt_img[b], 0.5, vis_pred_seg, 0.5, 0)
            img_path = sample["image_path"][b].split("/")[-1]
            camera_idx = int(sample["camera_idx"][b].cpu().numpy())
            camera_full_name = cam_index_to_cam_name_map[camera_idx]
            slice_idx = img_path.split(".")[0].strip("slice")
            cv2.putText(blend_image, f"{camera_full_name}_{slice_idx}", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (0, 0, 255), 2)
            self.blend_image_list[camera_full_name].append((slice_idx, blend_image))

    def on_validation_epoch_end(self):
        world_size = torch.distributed.get_world_size()
        all_blend_image_list = ["" for _ in range(world_size)]
        torch.distributed.all_gather_object(all_blend_image_list,  self.blend_image_list)
        all_frame_kpi_ddp = ["" for _ in range(world_size)]
        torch.distributed.all_gather_object(all_frame_kpi_ddp,  self.all_frame_kpi)

        rank = self.current_rank()
        if rank == 0:
            blend_image_list = defaultdict(list)
            for cam_image_list in all_blend_image_list:
                for cam, cam_image_list in cam_image_list.items():
                    blend_image_list[cam].extend(cam_image_list)

            all_frame_kpi = {}
            for frame_kpi in all_frame_kpi_ddp:
                all_frame_kpi.update(frame_kpi)

            ### Write KPI
            eval_kpi = aggregate_kpi(all_frame_kpi)
            kpi_table_str = generate_kpi_tables(eval_kpi)
            with open(os.path.join(self.rome_output_dir, "kpi.txt"), 'w') as writer:
                writer.write(kpi_table_str)
            logging.info(f"Eval KPI saved at: {os.path.join(self.rome_output_dir, 'kpi.txt')}")

            ### Write video
            video_path = os.path.join(self.rome_output_dir, "pred_seg_projection.mp4")
            write_video(blend_image_list, video_path)
            logging.info(f"Eval video saved at: {video_path}")

    @torch.no_grad()
    def save_mesh_verts_features(self, epoch):
        if self.current_rank() != 0:
            return
        verts_features = self.grid.get_verts_features()
        np.save(os.path.join(self.mesh_verts_dir, f"mesh_verts_{epoch}.npy"), verts_features.cpu().numpy())
