import logging
from typing import Dict

import torch
import os
from xpeng_raster import rasterization as xpeng_raster_rasterization

from ..datasets.base.data_proto import CameraInfo, ImageInfo
from ..datasets.driving_dataset import DrivingDataset
# from ..trainers.base import BasicTrainer, GSModelType
from ..utils.geometry import uniform_sample_sphere
from ..utils.misc import import_str
from ..utils.camera import render_camera_downwards
from ..utils.sky_panorama import sample_panorama_full_from_camera
from ..models.gaussians.basics import dataclass_camera, dataclass_gs

from torchvision.transforms.functional import to_pil_image
from torchvision.utils import save_image
from PIL import Image

logger = logging.getLogger()

gs_mode = os.getenv("GS_MODE")
if gs_mode == "render":
    from ..trainers.base_render import BasicTrainer_render as BasicTrainer
    from ..trainers.base_render import GSModelType
else:
    # 默认情况（包括 GS_MODE 不存在或其他值）
    from ..trainers.base import BasicTrainer, GSModelType

class MultiTrainer(BasicTrainer):
    def __init__(self, num_timesteps: int, **kwargs):
        self.num_timesteps = num_timesteps
        super().__init__(**kwargs)
        self.render_each_class = True

    def register_normalized_timestamps(self, num_timestamps: int):
        self.normalized_timestamps = torch.linspace(0, 1, num_timestamps, device=self.device)

    def _init_models(self):
        # gaussian model classes
        if "Background" in self.model_config:
            self.gaussian_classes["Background"] = GSModelType.Background
        if "RigidNodes" in self.model_config:
            self.gaussian_classes["RigidNodes"] = GSModelType.RigidNodes
        if "SMPLNodes" in self.model_config:
            self.gaussian_classes["SMPLNodes"] = GSModelType.SMPLNodes
        if "DeformableNodes" in self.model_config:
            self.gaussian_classes["DeformableNodes"] = GSModelType.DeformableNodes
        if "Ground" in self.model_config:
            self.gaussian_classes["Ground"] = GSModelType.Ground
        if "Trafficlight" in self.model_config:
            self.gaussian_classes["Trafficlight"] = GSModelType.Trafficlight
        if "RigidNodesLight" in self.model_config:
            self.gaussian_classes["RigidNodesLight"] = GSModelType.RigidNodesLight

        for class_name, model_cfg in self.model_config.items():
            # 每个模型的optm参数，优先使用模型自己的optm参数，如果没有，则使用gaussian_optim_general_cfg和gaussian_ctrl_general_cfg
            if class_name in self.gaussian_classes:
                model_cfg = self.model_config.pop(class_name)
                self.model_config[class_name] = self.update_gaussian_cfg(model_cfg)

            if class_name in self.gaussian_classes.keys():
                model = import_str(model_cfg.type)(
                    **model_cfg,
                    class_name=class_name,
                    scene_scale=self.scene_radius,
                    scene_origin=self.scene_origin,
                    num_train_images=self.num_train_images,
                    device=self.device,
                    data_source=self.data_source,
                    model_path=self.model_path,
                )

            if class_name in self.misc_classes_keys:
                model = import_str(model_cfg.type)(
                    class_name=class_name,
                    **model_cfg.get("params", {}),
                    n=self.num_full_images,
                    device=self.device,
                ).to(self.device)

            self.models[class_name] = model


        logger.info(f"Initialized models: {self.models.keys()}")

        # register normalized timestamps
        self.register_normalized_timestamps(self.num_timesteps)
        for class_name in self.gaussian_classes.keys():
            model = self.models[class_name]
            if hasattr(model, "register_normalized_timestamps"):
                model.register_normalized_timestamps(self.normalized_timestamps)
            if hasattr(model, "set_bbox"):
                model.set_bbox(self.aabb)

    def safe_init_models(
        self,
        model: torch.nn.Module,
        instance_pts_dict: Dict[str, Dict[str, torch.Tensor]],
    ) -> None:
        if len(instance_pts_dict.keys()) > 0:
            model.create_from_pcd(instance_pts_dict=instance_pts_dict)
            return False
        else:
            return True

    def init_misc_models_from_dataset(self, dataset: DrivingDataset):
        affine_path = os.path.join(dataset.data_path, "misc", "affine_transform.pth")
        if os.path.exists(affine_path) and "Affine" in self.models:
            try:
                self.models['Affine'].load_state_dict(torch.load(affine_path, map_location='cpu'))
                print(f"[INFO][AffineInit] Loaded affine transform from {affine_path}")
            except Exception as e:
                print(f"[ERROR][AffineInit] Affine initialization failed. Error: {e}")
        else:
            print(f"[INFO][AffineInit] Affine model not found or affine file not found: {affine_path}")
    
    def init_gaussians_from_dataset(
        self,
        dataset: DrivingDataset,
    ) -> None:
        # get instance points
        rigidnode_pts_dict, rigidnode_light_pts_dict, deformnode_pts_dict, smplnode_pts_dict = {}, {}, {}, {}
        dataset.obtain_obj_light_status("RigidNodesLight" in self.model_config)
        if "RigidNodes" in self.model_config:
            rigidnode_pts_dict = dataset.get_init_objects(
                cur_node_type="RigidNodes", **self.model_config["RigidNodes"]["init"]
            )

        if "RigidNodesLight" in self.model_config:
            rigidnode_light_pts_dict = dataset.get_init_objects(
                cur_node_type="RigidNodesLight", **self.model_config["RigidNodesLight"]["init"]
            )

        if "DeformableNodes" in self.model_config:
            deformnode_pts_dict = dataset.get_init_objects(
                cur_node_type="DeformableNodes",
                exclude_smpl="SMPLNodes" in self.model_config,
                **self.model_config["DeformableNodes"]["init"],
            )

        if "SMPLNodes" in self.model_config:
            smplnode_pts_dict = dataset.get_init_smpl_objects(**self.model_config["SMPLNodes"]["init"])
            print(f"Loaded {len(smplnode_pts_dict)} SMPL nodes for initialization.")
        allnode_pts_dict = {
            **rigidnode_pts_dict,
            **deformnode_pts_dict,
            **smplnode_pts_dict,
            **rigidnode_light_pts_dict
        }

        # NOTE: Some gaussian classes may be empty (because no points for initialization)
        #       We will delete these classes from the model_config and models
        empty_classes = []

        if "Trafficlight" in self.gaussian_classes:
            traffic_light_path = dataset.lidar_source.traffic_light_pcd_filepath
            if not os.path.isfile(traffic_light_path):
                # Remove the Trafficlight entry
                del self.gaussian_classes["Trafficlight"]
                del self.models["Trafficlight"]
                logger.warning(f"Removed Trafficlight class: point cloud file does not exist")
            else:
                logger.info(f"Trafficlight point cloud file exists, keeping the class")
        else:
            logger.info(f"Trafficlight class is not enabled, no action needed")

        # collect models
        g3r_ground_file = os.path.join(dataset.data_path, "g3r_ground", "g3r_ground.ply")
        evolsplat_bkgd_file = os.path.join(dataset.data_path, "evolsplat_bkgd", "evolsplat_init.ply")
        gs_2dgs_file = os.path.join(dataset.data_path, "misc", "ground_final.ply")
        
        for class_name in self.gaussian_classes:
            model_cfg = self.model_config[class_name]
            model = self.models[class_name]

            empty = False
            pts_counts = 0
            if class_name in ["Background", "Ground","Trafficlight"]:
                # ------ initialize gaussians ------
                init_cfg = model_cfg["init"]
                # sample points from the lidar point clouds
                if init_cfg.get("from_lidar", None) is not None:
                    sampled_pts, sampled_color, _ = dataset.get_lidar_samples(**init_cfg.from_lidar, device=self.device)
                else:
                    sampled_pts, sampled_color, _ = (
                        torch.empty(0, 3).to(self.device),
                        torch.empty(0, 3).to(self.device),
                        None,
                    )
                random_pts = []
                num_near_pts = init_cfg.get("near_randoms", 0)
                if num_near_pts > 0:  # uniformly sample points inside the scene's sphere
                    num_near_pts *= 3  # since some invisible points will be filtered out
                    random_pts.append(uniform_sample_sphere(num_near_pts, self.device))
                num_far_pts = init_cfg.get("far_randoms", 0)
                if num_far_pts > 0:  # inverse distances uniformly from (0, 1 / scene_radius)
                    num_far_pts *= 3
                    random_pts.append(uniform_sample_sphere(num_far_pts, self.device, inverse=True))

                valid_random_pts = None
                if num_near_pts + num_far_pts > 0:
                    random_pts = torch.cat(random_pts, dim=0)
                    random_pts = random_pts * self.scene_radius + self.scene_origin
                    visible_mask = dataset.check_pts_visibility(random_pts)
                    valid_random_pts = random_pts[visible_mask]

                    sampled_pts = torch.cat([sampled_pts, valid_random_pts], dim=0)
                    sampled_color = torch.cat(
                        [
                            sampled_color,
                            torch.rand(
                                valid_random_pts.shape,
                            ).to(self.device),
                        ],
                        dim=0,
                    )

                if init_cfg.get("filter_pts_in_boxes", True):
                    processed_init_pts = dataset.filter_pts_in_boxes(
                        seed_pts=sampled_pts,
                        seed_colors=sampled_color,
                        valid_instances_dict=allnode_pts_dict,
                    )
                else:
                    processed_init_pts = {"pts": sampled_pts, "colors": sampled_color}

                pts_counts = processed_init_pts["pts"].shape[0]
                
                if class_name == "Ground" and init_cfg.get("2dgs_init", False):
                    assert os.path.exists(gs_2dgs_file), f"[ERROR] 2DGS PLY file does not exist: {gs_2dgs_file}"
                    print(f"[INFO][INIT] Creating Ground from 2DGS PLY file: {gs_2dgs_file}")
                    model.create_from_2dgs_ply(gs_2dgs_file)
                elif class_name == "Ground" and init_cfg.get("g3r_ground_step", False):
                    assert os.path.exists(g3r_ground_file), f"[ERROR] G3R PLY file does not exist: {g3r_ground_file}"
                    print("[INFO][FEEDFORWARD] create from models/g3r")
                    model.create_from_feedforward(g3r_ground_file, pts_counts, class_name)

                elif class_name == "Background" and os.path.exists(evolsplat_bkgd_file) and init_cfg.get("use_feedforawrd", False):
                    print("[INFO][FEEDFORWARD] create from evolsplat")
                    pts_counts = model.create_from_feedforward(evolsplat_bkgd_file, 1e8, class_name, valid_random_pts)
                else:
                    model.create_from_pcd(
                        init_means=processed_init_pts["pts"],
                        init_colors=processed_init_pts["colors"],
                    )

            if class_name == "RigidNodes":
                moving_status = []

                for id_in_model, (id_in_dataset, v) in enumerate(rigidnode_pts_dict.items()):
                    moving_status.append(v["moving"].unsqueeze(1))
                    pts_counts = pts_counts + rigidnode_pts_dict[id_in_dataset]['pts'].shape[0]
                if len(moving_status) > 0:
                    rigid_moving_status = torch.cat(moving_status, dim=1).to(self.device)
                    self.fix_params_dict["RigidNodes#ins_rotation"] = rigid_moving_status
                    self.fix_params_dict["RigidNodes#ins_translation"] = rigid_moving_status

                model.set_class_name(class_name)
                empty = self.safe_init_models(model=model, instance_pts_dict=rigidnode_pts_dict)

            if class_name == "RigidNodesLight":
                moving_status = []

                for id_in_model, (id_in_dataset, v) in enumerate(rigidnode_light_pts_dict.items()):
                    moving_status.append(v["moving"].unsqueeze(1))
                    pts_counts = pts_counts + rigidnode_light_pts_dict[id_in_dataset]['pts'].shape[0]
                if len(moving_status) > 0:
                    rigid_moving_status = torch.cat(moving_status, dim=1).to(self.device)
                    self.fix_params_dict["RigidNodesLight#ins_rotation"] = rigid_moving_status
                    self.fix_params_dict["RigidNodesLight#ins_translation"] = rigid_moving_status

                model.set_class_name(class_name)
                empty = self.safe_init_models(model=model, instance_pts_dict=rigidnode_light_pts_dict)

            if class_name == "DeformableNodes":
                empty = self.safe_init_models(model=model, instance_pts_dict=deformnode_pts_dict)

            if class_name == "SMPLNodes":
                print(f"smplnode_pts_dict keys: {smplnode_pts_dict.keys()}")
                empty = self.safe_init_models(model=model, instance_pts_dict=smplnode_pts_dict)

            if empty:
                empty_classes.append(class_name)
                logger.warning(f"No points for {class_name} found, will remove the model")
            else:
                logger.info(f"Initialized {class_name} gaussians with {pts_counts} points")

        if len(empty_classes) > 0:
            for class_name in empty_classes:
                del self.models[class_name]
                del self.model_config[class_name]
                del self.gaussian_classes[class_name]
                logger.warning(f"Model for {class_name} is removed")

        logger.info("Initialized gaussians from pcd")

    def forward(
        self,
        image_info: ImageInfo,
        camera_info: CameraInfo,
        novel_view: bool = False,
        use_xpeng_raster: bool = False,
    ) -> Dict[str, torch.Tensor]:
        """Forward pass of the model

        Args:
            image_info (ImageInfo): image and pixels information
            camera_info (CameraInfo): camera information
                        novel_view: whether the view is novel, if True, disable the camera refinement

        Returns:
            Dict[str, torch.Tensor]: output of the model
        """
        # 训练时，normed_time在self.normalized_timestamps中能完全找得到匹配的成员，原因是normed_time = self.normalized_timestamps[frame_idx] (datasets/base/pixel_source.py - get_image)
        # 但仿真时，normed_time是真实时间，可能位于self.normalized_timestamps的成员之间
        # rigid node需要插值计算pose，所以我们令cur_frame为上一个frame_index，通过fraction_from_cur_frame插值计算pose
        # deformable无论使用最近的frame还是上一个frame作为cur_frame，影响都不大
        self.cur_frame = image_info.frame_index.detach().cpu()
        
        # for evaluation
        for model in self.models.values():
            if hasattr(model, "in_test_set"):
                model.in_test_set = self.in_test_set

        # assigne current frame to gaussian models
        for class_name in self.gaussian_classes.keys():
            model = self.models[class_name]
            if hasattr(model, "set_cur_frame"):
                model.set_cur_frame(self.cur_frame)

        # prepare data
        processed_cam = self.process_camera(
            camera_info=camera_info,
            image_info=image_info,
            novel_view=novel_view,
        )
        gs = self.collect_gaussians(cam=processed_cam, image_ids=image_info.image_index)

        # render gaussians
        outputs, render_fn = self.render_gaussians(
            gs=gs,
            cam=processed_cam,
            near_plane=self.render_cfg.near_plane,
            far_plane=self.render_cfg.far_plane,
            render_mode="RGB+ED",
            radius_clip=self.render_cfg.get("radius_clip", 0.0),
            use_xpeng_raster=use_xpeng_raster,
        )

        # render sky
        if self.use_feedforward_render and self.sky_panorama is not None:
            print("[INFO][FEEDFORWARD] render sky")
            fx = camera_info.intrinsic[0, 0]
            fy = camera_info.intrinsic[1, 1]
            cx = camera_info.intrinsic[0, 2]
            cy = camera_info.intrinsic[1, 2]
            width = camera_info.width
            height = camera_info.height
            intrinsic = torch.tensor([fx, fy, cx, cy, width, height], dtype=torch.float32)

            pose = camera_info.camera_to_world
            sky_featrues = sample_panorama_full_from_camera(pose, intrinsic, self.sky_panorama)
            sky_featrues = sky_featrues.unsqueeze(0)
            sky_image = self.sky_decoder_head(sky_featrues)
            sky_image = sky_image.squeeze(0)

            outputs["rgb_sky"] = sky_image
            outputs["rgb_sky_blend"] = (1 - outputs["opacity"]) * sky_image

        else:
            if "Sky" in self.models:
                sky_model = self.models["Sky"]
                outputs["rgb_sky"] = sky_model(image_info, opacity=outputs["opacity"].detach())
            else:
                outputs["rgb_sky"] = torch.zeros((camera_info.height, camera_info.width, 3), device=self.device)
            outputs["rgb_sky_blend"] = outputs["rgb_sky"] * (1.0 - outputs["opacity"])


        # affine transformation
        outputs["rgb"] = self.affine_transformation(
            outputs["rgb_gaussians"] + outputs["rgb_sky"] * (1.0 - outputs["opacity"]),
            image_info,
            camera_info,
        )

        if not self.training and self.render_cfg.get("render_each_class", True):
            with torch.no_grad():
                for class_name in self.gaussian_classes.keys():
                    gaussian_mask = self.pts_labels == self.gaussian_classes[class_name]
                    sep_rgb, sep_depth, sep_opacity = render_fn(gaussian_mask)
                    outputs[class_name + "_rgb"] = self.affine_transformation(sep_rgb, image_info, camera_info)
                    outputs[class_name + "_opacity"] = sep_opacity
                    outputs[class_name + "_depth"] = sep_depth

        if not self.training and self.gaussian_ctrl_general_cfg.get("opacity_loss", False):
            gaussian_mask = self.pts_labels == self.gaussian_classes["Background"]
            _, _, sep_opacity = render_fn(gaussian_mask)
            outputs["Background_opacity"] = sep_opacity

        if (not self.training or self.render_dynamic_mask) and self.render_cfg.get("render_each_class", True):
            gaussian_mask = self.pts_labels != self.gaussian_classes["Background"]
            if "Ground" in self.gaussian_classes:
                gaussian_mask = gaussian_mask & (self.pts_labels != self.gaussian_classes["Ground"])
            if self.use_grad_dynamic_opacity:
                sep_rgb, sep_depth, sep_opacity = render_fn(gaussian_mask)
                sep_rgb = self.affine_transformation(sep_rgb, image_info, camera_info)
            else:
                with torch.no_grad():
                    sep_rgb, sep_depth, sep_opacity = render_fn(gaussian_mask)
                    sep_rgb = self.affine_transformation(sep_rgb, image_info, camera_info)
            outputs["Dynamic_rgb"] = sep_rgb
            outputs["Dynamic_opacity"] = sep_opacity
            outputs["Dynamic_depth"] = sep_depth

            dynamic_asset_mask = self.pts_labels == GSModelType.DynamicAssets
            if dynamic_asset_mask.sum() > 0:
                dynamic_rgb, _, _ = render_fn(dynamic_asset_mask)
                dynamic_rgb = self.affine_transformation(dynamic_rgb, image_info, camera_info)
                outputs["DynamicAssets_masked_rgb"] = dynamic_rgb

        return outputs

    def _multi_cam_render_impl(
        self,
        image_infos: list[ImageInfo],
        camera_infos: list[CameraInfo],
        far_plane_list,
        novel_view: bool = False,
        use_xpeng_raster=True,
        use_sky_scale=False,
        group_by_resolution: bool = False,
    ) -> Dict[str, torch.Tensor]:
        self.cur_frame = image_infos[0].frame_index.detach().cpu()

        for model in self.models.values():
            if hasattr(model, "in_test_set"):
                model.in_test_set = self.in_test_set

        for class_name in self.gaussian_classes.keys():
            model = self.models[class_name]
            if hasattr(model, "set_cur_frame"):
                model.set_cur_frame(self.cur_frame)

        processed_cams = []
        processed_image_infos = []
        image_ids = []
        for image_info, camera_info in zip(image_infos, camera_infos):
            processed_cams.append(
                self.process_camera(
                    camera_info=camera_info,
                    image_info=image_info,
                    novel_view=novel_view,
                )
            )
            processed_image_infos.append(image_info)

        if group_by_resolution:
            grouped_cam_indices = {}
            for idx, cam in enumerate(processed_cams):
                grouped_cam_indices.setdefault((cam.H, cam.W), []).append(idx)

            outputs = [None] * len(processed_cams)
            for group_indices in grouped_cam_indices.values():
                grouped_cams = [processed_cams[idx] for idx in group_indices]
                grouped_far_plane_list = [far_plane_list[idx] for idx in group_indices] if far_plane_list else []
                grouped_gs = self.collect_gaussians_of_multi_cams(cams=grouped_cams, image_ids=image_ids)
                grouped_outputs = self.multi_cam_render_gaussians(
                    gs=grouped_gs,
                    cams=grouped_cams,
                    near_plane=self.render_cfg.near_plane,
                    far_plane=self.render_cfg.far_plane,
                    render_mode="RGB",
                    radius_clip=self.render_cfg.get("radius_clip", 0.0),
                    use_xpeng_raster=use_xpeng_raster,
                    far_plane_list=grouped_far_plane_list,
                )
                for idx, output in zip(group_indices, grouped_outputs):
                    outputs[idx] = output
        else:
            gs = self.collect_gaussians_of_multi_cams(cams=processed_cams, image_ids=image_ids)
            outputs = self.multi_cam_render_gaussians(
                gs=gs,
                cams=processed_cams,
                near_plane=self.render_cfg.near_plane,
                far_plane=self.render_cfg.far_plane,
                render_mode="RGB",
                radius_clip=self.render_cfg.get("radius_clip", 0.0),
                use_xpeng_raster=use_xpeng_raster,
                far_plane_list=far_plane_list,
            )

        for output, cam, image_info, raw_cam_info in zip(
            outputs, processed_cams, processed_image_infos, camera_infos
        ):
            if "Sky" in self.models:
                sky_model = self.models["Sky"]
                if use_sky_scale:
                    output["rgb_sky"] = sky_model.forward_lowres(
                        image_info, output["opacity"], cam.H, cam.W, sky_scale=4
                    )
                else:
                    output["rgb_sky"] = sky_model(image_info, opacity=output["opacity"].detach())
            else:
                output["rgb_sky"] = torch.zeros((cam.H, cam.W, 3), device=self.device)
            output["rgb_sky_blend"] = output["rgb_sky"] * (1.0 - output["opacity"])

        for output, cam, image_info, raw_cam_info in zip(
            outputs, processed_cams, processed_image_infos, camera_infos
        ):
            output["rgb"] = self.affine_transformation(
                output["rgb_gaussians"] + output["rgb_sky"] * (1.0 - output["opacity"]),
                image_info,
                raw_cam_info,
            )
        return outputs

    def multi_cam_render(
        self,
        image_infos: list[ImageInfo],
        camera_infos: list[CameraInfo],
        far_plane_list,
        novel_view: bool = False,
        use_xpeng_raster=True,
        use_sky_scale=False,
    ) -> Dict[str, torch.Tensor]:
        return self._multi_cam_render_impl(
            image_infos=image_infos,
            camera_infos=camera_infos,
            far_plane_list=far_plane_list,
            novel_view=novel_view,
            use_xpeng_raster=use_xpeng_raster,
            use_sky_scale=use_sky_scale,
            group_by_resolution=False,
        )

    def multi_cam_render_with_fixer(
        self,
        image_infos: list[ImageInfo],
        camera_infos: list[CameraInfo],
        far_plane_list,
        novel_view: bool = False,
        use_xpeng_raster=True,
        use_sky_scale=False,
    ) -> Dict[str, torch.Tensor]:
        return self._multi_cam_render_impl(
            image_infos=image_infos,
            camera_infos=camera_infos,
            far_plane_list=far_plane_list,
            novel_view=novel_view,
            use_xpeng_raster=use_xpeng_raster,
            use_sky_scale=use_sky_scale,
            group_by_resolution=True,
        )

    def precompute_gaussians(self, class_name="Ground"):
        model = self.models[class_name]
        colors = torch.cat((model._features_dc[:, None, :], model._features_rest), dim=1)
        rgbs = torch.sigmoid(colors[:, 0, :])
        activated_opacities = model.get_opacity
        activated_scales = model.get_scaling
        activated_rotations = model.get_quats
        gs_dict = dict(
            _means=model._means,
            _opacities=activated_opacities,
            _rgbs=rgbs,
            _scales=activated_scales,
            _quats=activated_rotations,
        )
        self.gs_dict = gs_dict
        return 
    
    def collect_hil_dynamic_gaussians(
        self,
        cam: dataclass_camera,
        true_region_masks: torch.Tensor, 
        enable_classes: list,
    ) -> dataclass_gs:
        hil_gs_dict = {
            "_means": [],
            "_scales": [],
            "_quats": [],
            "_rgbs": [],
            "_opacities": [],
        }
        if true_region_masks is not None:
            true_region_masks = true_region_masks.bool()
            gaussian_positions = self.gs_dict["_means"][true_region_masks]  # [N, 3] - x, y, z 坐标
            gaussian_rotations = self.gs_dict["_quats"][true_region_masks]  # [N, 4] - 四元数 (rw, rx, ry, rz)
            num_mask = int(gaussian_positions.shape[0])#/2
            hil_gs_dict["_means"].append(gaussian_positions[:num_mask,:])
            hil_gs_dict["_quats"].append(gaussian_rotations[:num_mask,:])
            hil_gs_dict["_opacities"].append(self.gs_dict["_opacities"][true_region_masks])
            hil_gs_dict["_rgbs"].append(self.gs_dict["_rgbs"][true_region_masks])
            hil_gs_dict["_scales"].append(self.gs_dict["_scales"][true_region_masks])
        else:
            hil_gs_dict["_means"].append(self.gs_dict["_means"])
            hil_gs_dict["_quats"].append(self.gs_dict["_quats"])
            hil_gs_dict["_opacities"].append(self.gs_dict["_opacities"])
            hil_gs_dict["_rgbs"].append(self.gs_dict["_rgbs"])
            hil_gs_dict["_scales"].append(self.gs_dict["_scales"])

        for class_name in self.gaussian_classes.keys():
            model = self.models[class_name]
            if class_name in enable_classes and class_name != "Ground":
                gs = model.get_gaussians(cam)
                for k, _ in gs.items():
                    if k in hil_gs_dict.keys():
                        hil_gs_dict[k].append(gs[k])
        for k, v in hil_gs_dict.items():
            hil_gs_dict[k] = torch.cat(v, dim=0)
        return hil_gs_dict

    def render_xpeng_raster(
            self,
            image_info: ImageInfo,
            camera_info: CameraInfo,
            novel_view: bool = False,
            true_region_masks = None,
            enable_classes = ["RigidNodes", "Ground"],
        ) -> Dict[str, torch.Tensor]:
        self.cur_frame = image_info.frame_index.detach().cpu()
        # for evaluation
        for model in self.models.values():
            if hasattr(model, "in_test_set"):
                model.in_test_set = self.in_test_set

        # assigne current frame to gaussian models
        for class_name in self.gaussian_classes.keys():
            model = self.models[class_name]
            if hasattr(model, "set_cur_frame"):
                model.set_cur_frame(self.cur_frame)
            if class_name in enable_classes:
                model.hil_mode = True
        processed_cam = self.process_camera(
            camera_info=camera_info,
            image_info=image_info,
            novel_view=novel_view,
        )
        hil_gs_dict = self.collect_hil_dynamic_gaussians(processed_cam, true_region_masks, enable_classes)
        # render gaussians
        renders, alphas, info = xpeng_raster_rasterization(
            means=hil_gs_dict['_means'],
            quats=hil_gs_dict['_quats'],
            scales=hil_gs_dict["_scales"],
            opacities=hil_gs_dict['_opacities'].squeeze(),
            colors=hil_gs_dict["_rgbs"],
            viewmats=torch.linalg.inv(processed_cam.camtoworlds)[None, ...],
            Ks=processed_cam.Ks[None, ...],
            width=processed_cam.W,
            height=processed_cam.H,
            tile_size=6,
        )
        renders = renders[0]
        alphas = alphas[0].squeeze(-1)
        # affine transformation
        renders = self.affine_transformation(renders, image_info, camera_info)

        outputs = {
            "rgb": renders,
            "depth": None,
            "opacity": alphas,
        }
        return outputs

    def render_camera_downwards(
        self,
        camera_info: CameraInfo,
        image_info: ImageInfo,
        **kwargs,
    ) -> Dict[str, torch.Tensor]:
        """
        使用向下俯视的相机角度进行渲染，只使用Ground类的高斯模型。
        
        Args:
            camera_info (CameraInfo): 相机信息
            image_info (ImageInfo): 图像信息
            **kwargs: 其他渲染参数
            
        Returns:
            Dict[str, torch.Tensor]: 渲染结果
        """
        # 检查是否有Ground模型
        if "Ground" not in self.gaussian_classes.keys():
            logger.warning("Ground model not found, returning empty results")
            return {
                "rgb_gaussians": torch.zeros((camera_info.height, camera_info.width, 3), device=self.device),
                "depth": torch.zeros((camera_info.height, camera_info.width, 1), device=self.device),
                "opacity": torch.zeros((camera_info.height, camera_info.width, 1), device=self.device)
            }
        
        # 处理相机信息
        processed_cam = dataclass_camera(
            camera_id=camera_info.camera_id,
            timestep_id=image_info.frame_index.detach().cpu().item(),
            fraction_from_cur_timestep=image_info.fraction_from_cur_frame,
            novel_view=True,
            camtoworlds=camera_info.camera_to_world,
            camtoworlds_gt=camera_info.camera_to_world,
            Ks=camera_info.intrinsic,
            H=camera_info.height,
            W=camera_info.width,
        )
        
        # 只获取Ground和Background类的高斯模型
        gs_dict = {
            "_means": [],
            "_scales": [],
            "_quats": [],
            "_rgbs": [],
            "_opacities": [],
            "class_labels": [],
        }
        for class_name in ["Ground", "Background","Trafficlight"]:
            gs = self.models[class_name].get_gaussians(processed_cam, save_filter_mask=False)
            # collect gaussians
            gs["class_labels"] = torch.full(
                (gs["_means"].shape[0],), self.gaussian_classes[class_name], device=self.device,
            )
            for k, _ in gs.items():
                gs_dict[k].append(gs[k])

        for k, v in gs_dict.items():
            gs_dict[k] = torch.cat(v, dim=0)

        gaussians = dataclass_gs(
            _means=gs_dict["_means"],
            _scales=gs_dict["_scales"],
            _quats=gs_dict["_quats"],
            _rgbs=gs_dict["_rgbs"],
            _opacities=gs_dict["_opacities"],
            detach_keys=[],  # if "means" in detach_keys, then the means will be detached
            extras=None,  # to save some extra information (TODO) more flexible way
        )

        # 调用向下俯视渲染函数
        render_pkg = render_camera_downwards(
            camera_info=camera_info, image_info=image_info, gaussians=gaussians,
        )
        
        return render_pkg
