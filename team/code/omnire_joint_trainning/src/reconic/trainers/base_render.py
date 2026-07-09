import logging
import os
from enum import IntEnum
from typing import Dict, List
from xpeng_raster import rasterization as xpeng_raster_rasterization

import numpy as np
import torch
import torch.nn as nn
from gsplat.rendering import rasterization
from omegaconf import OmegaConf

from ..datasets.base.data_proto import CameraInfo, ImageInfo
from ..models.gaussians.basics import dataclass_camera, dataclass_gs
from ..utils.sky_panorama import ResConvHead

logger = logging.getLogger()

VISUALIZATION_DEBUG = False


def depth_to_rainbow_colors(normalized_depth: torch.Tensor) -> torch.Tensor:
    depth_colors = torch.zeros((*normalized_depth.shape, 3), device=normalized_depth.device)
    depth_colors[..., 0] = 1.0 - normalized_depth
    green_channel = torch.zeros_like(normalized_depth)
    mask_less_half = normalized_depth < 0.5
    mask_more_half = normalized_depth >= 0.5
    green_channel[mask_less_half] = normalized_depth[mask_less_half] * 2
    green_channel[mask_more_half] = 2 - normalized_depth[mask_more_half] * 2
    depth_colors[..., 1] = green_channel
    depth_colors[..., 2] = normalized_depth
    return depth_colors


class GSModelType(IntEnum):
    Background = 0
    RigidNodes = 1
    SMPLNodes = 2
    DeformableNodes = 3
    Ground = 4
    Trafficlight = 5
    DynamicAssets = 6
    RigidNodesLight = 7


def lr_scheduler_fn(cfg: OmegaConf, lr_init: float):
    if cfg.lr_final is None:
        lr_final = lr_init
    else:
        lr_final = cfg.lr_final

    def func(step):
        step = step - cfg.opt_after
        if step < 0:
            return 0.0

        if step < cfg.warmup_steps:
            if cfg.ramp == "cosine":
                lr = cfg.lr_pre_warmup + (lr_init - cfg.lr_pre_warmup) * np.sin(
                    0.5 * np.pi * np.clip(step / cfg.warmup_steps, 0, 1)
                )
            else:
                lr = cfg.lr_pre_warmup + (lr_init - cfg.lr_pre_warmup) * step / cfg.warmup_steps
        else:
            t = np.clip((step - cfg.warmup_steps) / (cfg.max_steps - cfg.warmup_steps), 0, 1)
            lr = np.exp(np.log(lr_init) * (1 - t) + np.log(lr_final) * t)
        return lr  # divided by lr_init because the multiplier is with the initial learning rate

    return func


class BasicTrainer_render (nn.Module):
    def __init__(
        self,
        data_source: str = 'lidar',
        type: str = "basic",
        optim: OmegaConf = None,
        losses: OmegaConf = None,
        render: OmegaConf = None,
        gaussian_optim_general_cfg: OmegaConf = None,
        gaussian_ctrl_general_cfg: OmegaConf = None,
        model_config: OmegaConf = None,
        num_train_images: int = 0,
        num_full_images: int = 0,
        test_set_indices: List[int] = None,
        scene_aabb: torch.Tensor = None,
        device=None,
        disable_metric=False,
        model_path=None
    ):
        super().__init__()
        self._type = type
        self.data_source = data_source
        self.model_path = model_path
        self.optim_general = optim
        self.losses_dict = losses
        self.render_cfg = render
        self.model_config = model_config
        self.num_iters = self.optim_general.get("num_iters", 30000)
        self.gaussian_optim_general_cfg = gaussian_optim_general_cfg
        self.gaussian_ctrl_general_cfg = gaussian_ctrl_general_cfg
        self.step = 0
        self.device = device

        # dataset infos
        self.num_train_images = num_train_images
        self.num_full_images = num_full_images

        # # init scene scale
        self._init_scene(scene_aabb=scene_aabb)

        # init models
        self.models = {}
        self.misc_classes_keys = ["Sky", "Affine", "CamPose", "CamPosePerturb"]
        self.gaussian_classes = {}
        self._init_models()
        self.pts_labels = None  # will be overwritten in forward
        self.render_dynamic_mask = False
        self.use_grad_dynamic_opacity = False

        self.disable_metric = disable_metric
        # background color
        self.back_color = torch.zeros(3).to(self.device)

        # for evaluation
        self.cur_frame = torch.tensor(0, device=self.device)
        self.test_set_indices = test_set_indices  # will be override

        # a simple viewer for background visualization
        self.viewer = None

        # fix parmas during optimization
        self.fix_params_dict = {}

        # ground kdtree for moving dynamic assets height to ground level
        self.ground_kdtree = None
        self.ground_all_z = None

        # EMA for asset offset z smoothing
        self.ema_alpha = 0.3  # 越大越跟随原始值（响应快），越小越平滑（惯性大）
        self._smoothed_offset_z_ema = None  # 初始为 None，首次使用时直接赋值

        self.use_feedforward_render = False
        self.sky_decoder_head = ResConvHead()
        self.sky_panorama = None
        
    @property
    def in_test_set(self):
        return self.cur_frame.item() in self.test_set_indices

    def set_eval(self):
        for model in self.models.values():
            model.eval()
        self.eval()


    def process_camera(
        self,
        camera_info: CameraInfo,
        image_info: ImageInfo,
        novel_view: bool = False,
    ) -> dataclass_camera:
        camtoworlds = camtoworlds_gt = camera_info.camera_to_world

        # if "CamPosePerturb" in self.models.keys():
        #     camtoworlds = self.models["CamPosePerturb"](camtoworlds, image_info.image_index)

        # if "CamPose" in self.models.keys():
        #     camtoworlds = self.models["CamPose"](camtoworlds, image_info.image_index)

        # collect camera information
        camera_dict = dataclass_camera(
            camera_id=camera_info.camera_id,
            timestep_id=image_info.frame_index.detach().cpu().item(),
            fraction_from_cur_timestep=image_info.fraction_from_cur_frame,
            novel_view=novel_view,
            camtoworlds=camtoworlds,
            camtoworlds_gt=camtoworlds_gt,
            Ks=camera_info.intrinsic,
            H=camera_info.height,
            W=camera_info.width,
        )

        return camera_dict

    def _init_scene(self, scene_aabb) -> None:
        self.aabb = scene_aabb.to(self.device)
        scene_origin = (self.aabb[0] + self.aabb[1]) / 2
        scene_radius = torch.max(self.aabb[1] - self.aabb[0]) / 2 * 1.1
        self.scene_radius = scene_radius.item()
        self.scene_origin = scene_origin
        logger.info(f"scene origin: {scene_origin}")
        logger.info(f"scene radius: {scene_radius}")
  
    def update_gaussian_cfg(self, model_cfg: OmegaConf) -> OmegaConf:
        class_optim_cfg = model_cfg.get("optim", None)
        class_ctrl_cfg = model_cfg.get("ctrl", None)
        new_optim_cfg = self.gaussian_optim_general_cfg.copy()
        new_ctrl_cfg = self.gaussian_ctrl_general_cfg.copy()
        if class_optim_cfg is not None:
            new_optim_cfg.update(class_optim_cfg)
        if class_ctrl_cfg is not None:
            new_ctrl_cfg.update(class_ctrl_cfg)
        model_cfg["optim"] = new_optim_cfg
        model_cfg["ctrl"] = new_ctrl_cfg

        return model_cfg

    def mirror_rigid_nodes_light_state_dict(
        self,
        rigid_state_dict: Dict[str, torch.Tensor],
        obj_dir_dict: Dict,
        hist_bin_width: float = 0.2,
        eps_min: float = 0.3,
        eps_max: float = 1.5,
        ends_band_m: float = 0.3,
        eps_mid_body: float = 0.2,
        mirror_skip_ends_m: float = 0.5,
        y_center_q_low: float = 0.05,
        y_center_q_high: float = 0.95,
    ) -> Dict[str, torch.Tensor]:

        def _estimate_y_center_quantile(y_vals: torch.Tensor, source_side: str) -> float:
            y_min = torch.min(y_vals)
            y_max = torch.max(y_vals)
            hist_bin_width = 0.02
            num_bins = max(1, int(torch.ceil((y_max - y_min) / hist_bin_width).item()))
            bin_ids = torch.floor((y_vals - y_min) / hist_bin_width).long()
            bin_ids = torch.clamp(bin_ids, min=0, max=num_bins - 1)
            hist = torch.bincount(bin_ids, minlength=num_bins)
            bin_centers = y_min + (
                torch.arange(num_bins, device=y_vals.device, dtype=y_vals.dtype) + 0.5
            ) * hist_bin_width
            occupied_centers = bin_centers[hist > 0]

            low = float(torch.quantile(occupied_centers, y_center_q_low).item())
            high = float(torch.quantile(occupied_centers, y_center_q_high).item())
            print(f"y_center_q_low: {low}, y_center_q_high: {high}")
            center = 0.5 * (low + high)
            if source_side == "left":
                center += 0.05
            elif source_side == "right":
                center -= 0.05
            return float(np.clip(center, -0.1, 0.1))

        per_point_keys = [
            "_means",
            "_features_dc",
            "_features_rest",
            "_opacities",
            "_scales",
            "_quats",
            "points_ids",
        ]
        if "_appearance_features" in rigid_state_dict:
            per_point_keys.append("_appearance_features")

        if any(k not in rigid_state_dict for k in per_point_keys):
            return rigid_state_dict

        mirrored_chunks = {k: [] for k in per_point_keys}

        def _append_original(selector, clone: bool = True) -> None:
            for key in per_point_keys:
                values = rigid_state_dict[key][selector]
                mirrored_chunks[key].append(values.clone() if clone else values)

        def _append_mirrored(source_indices: torch.Tensor, center_indices: torch.Tensor, y_center: float) -> None:
            for key in per_point_keys:
                source_values = rigid_state_dict[key][source_indices].clone()
                mirrored_values = source_values.clone()
                center_values = rigid_state_dict[key][center_indices].clone()

                if key == "_means":
                    mirrored_values[:, 1] = 2.0 * y_center - mirrored_values[:, 1]
                elif key == "_quats":
                    # Reflection across local xz-plane. q=(w,x,y,z) -> (w,-x,y,-z).
                    mirrored_values[:, 1] = -mirrored_values[:, 1]
                    mirrored_values[:, 3] = -mirrored_values[:, 3]

                mirrored_chunks[key].append(torch.cat([source_values, mirrored_values, center_values], dim=0))

        point_ids = rigid_state_dict["points_ids"].squeeze(-1)
        unique_obj_ids = torch.unique(point_ids)

        for obj_id_t in unique_obj_ids:
            obj_id = int(obj_id_t.item())
            source_side = obj_dir_dict.get(obj_id, obj_dir_dict.get(str(obj_id), None))
            obj_mask = point_ids == obj_id_t

            # Keep unchanged if direction is unknown.
            if source_side not in {"left", "right"}:
                _append_original(obj_mask, clone=False)
                continue
            print(
                f"[mirror_rigid_nodes_light_state_dict] obj_id={obj_id}, "
                f"source_side={source_side}, total_points={int(obj_mask.sum().item())}"
            )

            obj_indices = torch.where(obj_mask)[0]
            obj_means = rigid_state_dict["_means"][obj_mask]
            x_all = obj_means[:, 0]
            x_min_all = x_all.min()
            x_max_all = x_all.max()
            # Within mirror_skip_ends_m of front/rear along length (x): keep original, no mirror.
            skip_mirror_end = (x_all - x_min_all <= mirror_skip_ends_m + 1e-9) | (
                x_max_all - x_all <= mirror_skip_ends_m + 1e-9
            )
            mid_mirror = ~skip_mirror_end

            if torch.any(skip_mirror_end):
                end_indices = obj_indices[skip_mirror_end]
                _append_original(end_indices)

            if not torch.any(mid_mirror):
                print(
                    f"[mirror_rigid_nodes_light_state_dict] obj_id={obj_id}, "
                    f"all points within {mirror_skip_ends_m}m of ends; skip mid mirror."
                )
                continue

            mid_indices = obj_indices[mid_mirror]
            obj_means_mid = rigid_state_dict["_means"][mid_indices]
            y_all = obj_means[:, 1]
            y = obj_means_mid[:, 1]

            y_center_est = _estimate_y_center_quantile(y_all, source_side)
            print(
                f"======================[mirror_rigid_nodes_light_state_dict] "
                f"y_center (all points est): {y_center_est}======================"
            )

            # Symmetry plane for mirror; fixed at 0 in object coordinates.
            y_center = y_center_est
            eps_per_point = torch.full_like(y, float(eps_mid_body))

            center_mask = torch.abs(y - y_center) <= eps_per_point
            if source_side == "right":
                source_mask = y < -eps_per_point
            else:
                source_mask = y > eps_per_point

            if not torch.any(source_mask):
                print(
                    "No reliable source side on mid body; keep mid unchanged "
                    "(ends already appended if any)."
                )
                _append_original(mid_indices)
                continue

            source_indices = mid_indices[source_mask]
            center_indices = mid_indices[center_mask]
            print(
                f"[mirror_rigid_nodes_light_state_dict] obj_id={obj_id} (mid only), "
                f"source_points={int(source_indices.numel())}, center_points={int(center_indices.numel())}"
            )

            _append_mirrored(source_indices, center_indices, y_center)

        mirrored_state_dict = dict(rigid_state_dict)
        for k in per_point_keys:
            mirrored_state_dict[k] = torch.cat(mirrored_chunks[k], dim=0)
        return mirrored_state_dict

    def state_dict(self, only_model: bool = True):
        state_dict = super().state_dict()
        model_state_dict = {}
        for class_name, model in self.models.items():
            class_state_dict = model.state_dict()
            if class_name == "RigidNodesLight":
                class_state_dict = self.mirror_rigid_nodes_light_state_dict(
                    class_state_dict, getattr(model, "obj_dir_dict", {})
                )
            model_state_dict[class_name] = class_state_dict

        state_dict.update(
            {
                "models": model_state_dict,
                "step": self.step,
            }
        )
        if not only_model:
            if hasattr(self, "optimizer"):
                state_dict["optimizer"] = self.optimizer.state_dict()
            if hasattr(self, "grad_scaler"):
                state_dict["grad_scaler"] = self.grad_scaler.state_dict()
        return state_dict

    def initialize_optimizer(self) -> None:
        # get param groups first
        self.param_groups = {}
        for class_name, model in self.models.items():
            self.param_groups.update(model.get_param_groups())

        groups = []
        lr_schedulers = {}
        for params_name, params in self.param_groups.items():
            class_name = params_name.split("#")[0]
            component_name = params_name.split("#")[1]
            # self.model_config经过了update_gaussian_cfg的更新，每个模型的optm参数，优先使用模型自己的optm参数，如果没有，则使用gaussian_optim_general_cfg和gaussian_ctrl_general_cfg。具体逻辑在update_gaussian_cfg
            class_cfg = self.model_config.get(class_name)
            class_optim_cfg = class_cfg["optim"]
            raw_optim_cfg = class_optim_cfg.get(component_name, None)
            lr_scale_factor = raw_optim_cfg.get("scale_factor", 1.0)
            if isinstance(lr_scale_factor, str) and lr_scale_factor == "scene_radius":
                # scale the spatial learning rate to scene scale
                lr_scale_factor = self.scene_radius

            optim_cfg = OmegaConf.create(
                {
                    "lr": raw_optim_cfg.get("lr", 0.0005),
                    "eps": raw_optim_cfg.get("eps", 1.0e-15),
                    "weight_decay": raw_optim_cfg.get("weight_decay", 0),
                }
            )
            optim_cfg.lr = optim_cfg.lr * lr_scale_factor
            assert optim_cfg is not None, f"param group {params_name} not found in config"

            if class_name == "Background":
                init_cfg = class_cfg["init"] if "init" in class_cfg else {}
                if init_cfg.get("use_feedforawrd", False) and component_name not in ["xyz", "scaling"]:
                    optim_cfg.lr *= 2

            lr_init = optim_cfg.lr
            groups.append(
                {
                    "params": params,
                    "name": params_name,
                    "lr": optim_cfg.lr,
                    "eps": optim_cfg.eps,
                    "weight_decay": optim_cfg.weight_decay,
                }
            )

            if raw_optim_cfg.get("lr_final", None) is not None:
                sched_cfg = OmegaConf.create(
                    {
                        "opt_after": raw_optim_cfg.get("opt_after", 0),
                        "warmup_steps": raw_optim_cfg.get("warmup_steps", 0),
                        "max_steps": raw_optim_cfg.get("max_steps", self.num_iters),
                        "lr_pre_warmup": raw_optim_cfg.get("lr_pre_warmup", 1.0e-8),
                        "lr_final": raw_optim_cfg.get("lr_final", None),
                        "ramp": raw_optim_cfg.get("ramp", "cosine"),
                    }
                )
                # scale the learning rate according to the scene scale
                sched_cfg.lr_pre_warmup = sched_cfg.lr_pre_warmup * lr_scale_factor
                sched_cfg.lr_final = sched_cfg.lr_final * lr_scale_factor if sched_cfg.lr_final is not None else None
                # adjust max_steps to account for opt_after
                sched_cfg.max_steps = sched_cfg.max_steps - sched_cfg.opt_after
                lr_schedulers[params_name] = lr_scheduler_fn(sched_cfg, lr_init)

        self.optimizer = torch.optim.Adam(groups, lr=0.0, eps=1e-15)
        self.lr_schedulers = lr_schedulers
        self.grad_scaler = torch.cuda.amp.GradScaler("cuda", enabled=self.optim_general.get("use_grad_scaler", False))

    def resume_from_checkpoint(self, ckpt_path: str, load_only_model: bool = True) -> None:
        """
        Load model from checkpoint.
        """
        logger.info(f"Loading checkpoint from {ckpt_path}")
        state_dict = torch.load(ckpt_path, weights_only=False, map_location=self.device)
        if self.disable_metric:
            self.load_state_dict(state_dict, load_only_model=load_only_model, strict=False)
        else:
            self.load_state_dict(state_dict, load_only_model=load_only_model, strict=True)

    def load_state_dict(self, state_dict: dict, load_only_model: bool = True, strict: bool = True):
        step = state_dict.pop("step")
        self.step = step
        logger.info(f"Loading checkpoint at step {step}")

        # load optimizer and schedulers
        if "optimizer" in state_dict:
            loaded_optimizer = state_dict.pop("optimizer")
        if "grad_scaler" in state_dict:
            loaded_grad_scaler = state_dict.pop("grad_scaler")

        # load model
        model_state_dict = state_dict.pop("models")
        trafficlight_point_cloud = True
        smpl_nodes = True
        for class_name in self.models.keys():
            model = self.models[class_name]
            model.step = step
            if class_name not in model_state_dict:
                if class_name in self.gaussian_classes:
                    self.gaussian_classes.pop(class_name)
                if class_name == "Trafficlight":
                    trafficlight_point_cloud = False
                if class_name == "SMPLNodes":
                    smpl_nodes = False
                logger.warning(f"Cannot find {class_name} in the checkpoint")
                continue

            if class_name in ["RigidNodes", "RigidNodesLight"]:
                model.set_class_name(class_name)
            msg = model.load_state_dict(model_state_dict[class_name], strict=strict)
            logger.info(f"{class_name}: {msg}")
        if not trafficlight_point_cloud:
            del self.models["Trafficlight"]
        if not smpl_nodes:
            del self.models["SMPLNodes"]
        msg = super().load_state_dict(state_dict, strict)
        logger.info(f"BasicTrainer: {msg}")

        # match the idx of param groups between loaded optimizer and local optimizer
        self.initialize_optimizer()
        loaded_optimizer_name_list = []
        for elem in loaded_optimizer["param_groups"]:
            loaded_optimizer_name_list.append(elem["name"])
        new_param_groups = []
        for elem in self.optimizer.state_dict()["param_groups"]:
            idx = loaded_optimizer_name_list.index(elem["name"])
            new_param_groups.append(loaded_optimizer["param_groups"][idx])
        loaded_optimizer["param_groups"] = new_param_groups

        # load optimizer and schedulers
        if not load_only_model:
            self.optimizer.load_state_dict(loaded_optimizer)
            self.grad_scaler.load_state_dict(loaded_grad_scaler)

    # use KD-tree to move dynamic assets height to ground level
    def move_dynamic_assets_height_to_ground(self, gs_dict, class_labels):
        dynamic_assets_mask = (class_labels == GSModelType.DynamicAssets)
        if dynamic_assets_mask.sum() == 0:
            logging.info("[move_dynamic_assets_height_to_ground] No dynamic assets found, skip moving height.")
            return gs_dict

        if self.ground_kdtree is None or self.ground_all_z is None: 
            from scipy.spatial import KDTree
            ground_mask = (class_labels == GSModelType.Ground)
            if ground_mask.sum() == 0:
                return gs_dict
            
            # Ground points
            ground_xyz = gs_dict["_means"][ground_mask]  # [N_ground, 3]
            ground_xy = ground_xyz[:, :2].cpu().numpy()
            self.ground_all_z = ground_xyz[:, 2].cpu().numpy()   # 保留 z 坐标
            self.ground_kdtree = KDTree(ground_xy)

        # Dynamic assets points
        dynamic_xyz = gs_dict["_means"][dynamic_assets_mask]  # [N_dyn, 3]

        # 找 DynamicAssets 中 z 最小的点（可能多个）
        min_z = dynamic_xyz[:, 2].min().item()
        lowest_points_xy = dynamic_xyz[dynamic_xyz[:, 2] == min_z][:, :2].cpu().numpy()

        # 查询每个最低点对应的最近 Ground 点
        _, indices = self.ground_kdtree.query(lowest_points_xy)  # indices: [n_lowest]

        # 取第一个最低点对应的 ground z 作为参考（或可取平均）
        ref_ground_z = self.ground_all_z[indices[0]]  # 或 np.mean(ground_z[indices])

        # 计算需要下移的距离：当前最低点 z - 目标地面 z
        raw_offset_z = min_z - ref_ground_z  # 如果 min_z > ref_ground_z，offset_z > 0，需要下移
        offset_z = self._smooth_offset_z(raw_offset_z)
        logging.info(f"[move_dynamic_assets_height_to_ground] Moving dynamic assets down by offset_z: {offset_z:.4f} (raw: {raw_offset_z:.4f})")

        # 整体下移动态资产
        new_dynamic_xyz = dynamic_xyz.clone()
        new_dynamic_xyz[:, 2] -= offset_z

        gs_dict["_means"][dynamic_assets_mask] = new_dynamic_xyz
        return gs_dict

    def _smooth_offset_z(self, raw_offset_z: float) -> float:
        if self._smoothed_offset_z_ema is None:
            self._smoothed_offset_z_ema = raw_offset_z
        else:
            self._smoothed_offset_z_ema = (
                self.ema_alpha * raw_offset_z +
                (1.0 - self.ema_alpha) * self._smoothed_offset_z_ema
            )
        return self._smoothed_offset_z_ema

    def load_from_feedforward(self, data_path):
        self.training = False
        self.use_feedforward_render = True

        use_gsm_bkgd = False
        gsm_folder = os.path.join(self.model_path, "gsm_bkgd")
        if os.path.exists(gsm_folder):
            use_gsm_bkgd = True

        print(f"use_gsm_bkgd = {use_gsm_bkgd}")
        if use_gsm_bkgd:
            sky_params_path = os.path.join(gsm_folder, "sky_params.pt")
            sky_pano_path = os.path.join(gsm_folder, "sky_pano.pt")
            state_dict = torch.load(sky_params_path, map_location="cpu", weights_only=True)
            self.sky_decoder_head.load_state_dict(state_dict)
            self.sky_decoder_head = self.sky_decoder_head.to("cuda" if torch.cuda.is_available() else "cpu")
            self.sky_decoder_head.eval()
            self.sky_panorama = torch.load(sky_pano_path)

        for class_name in self.models.keys():
            model = self.models[class_name]
            if class_name == "Ground":
                gs_2dgs_file = os.path.join(self.model_path, "misc", "ground_final.ply")
                if os.path.exists(gs_2dgs_file):
                    model.create_from_2dgs_ply(gs_2dgs_file)
                    print(f"[INIT] Loaded ground from {gs_2dgs_file}")
                else:
                    print(f"[INIT] No ground found in {gs_2dgs_file}")
            elif class_name == "Background":
                if use_gsm_bkgd:
                    gsm_file = os.path.join(gsm_folder, "gsm_bkgd_init.ply")
                    if os.path.exists(gsm_file):
                        model.create_from_feedforward(gsm_file, 1e8, class_name, None)
                        print(f"[INIT] Loaded background from {gsm_file}")
                    else:
                        print(f"[INIT] No background found in {gsm_file}")
                else:
                    evolsplat_file = os.path.join(self.model_path, "evolsplat_bkgd", "evolsplat_init.ply")
                    if os.path.exists(evolsplat_file):
                        model.create_from_feedforward(evolsplat_file, 1e8, class_name, None)
                        print(f"[INIT]Loaded background from {evolsplat_file}")
                    else:
                        print(f"[INIT] No background found in {evolsplat_file}")
            elif class_name == "RigidNodes":
                instance_dict_pt_path = os.path.join(self.model_path, class_name + "_instance_dict.pt")
                if not os.path.exists(instance_dict_pt_path):
                    instance_dict_pt_path = os.path.join(self.model_path, "instance_dict.pt")
                if os.path.exists(instance_dict_pt_path):
                    instance_pts_dict = torch.load(instance_dict_pt_path, map_location='cpu')
                    model.create_from_pcd(instance_pts_dict=instance_pts_dict)
                    print(f"[INIT] Loaded rigid nodes from {instance_dict_pt_path}")
            elif class_name == "RigidNodesLight":
                instance_dict_pt_path = os.path.join(self.model_path, class_name + "_instance_dict.pt")
                if os.path.exists(instance_dict_pt_path):
                    instance_pts_dict = torch.load(instance_dict_pt_path, map_location='cpu')
                    model.create_from_pcd(instance_pts_dict=instance_pts_dict)
                    print(f"[INIT] Loaded rigid light nodes from {instance_dict_pt_path}")
            elif class_name == "Affine":
                affine_path = os.path.join(self.model_path, "misc", "affine_transform.pth")
                if os.path.exists(affine_path):
                    affine_dict = torch.load(affine_path, map_location='cpu')
                    model.load_state_dict(affine_dict)
                    print(f"[INIT] Loaded affine transform from {affine_path}")
                else:
                    print(f"[INIT] No affine transform found in {affine_path}")
        return

    def collect_gaussians(
        self,
        cam: dataclass_camera,
        image_ids: torch.Tensor,  # leave it here for future use
    ) -> dataclass_gs:
        gs_dict = {
            "_means": [],
            "_scales": [],
            "_quats": [],
            "_rgbs": [],
            "_opacities": [],
            "class_labels": [],
        }
        found_dynamic_assets_gs = False
        for class_name in self.gaussian_classes.keys():
            gs = self.models[class_name].get_gaussians(cam)

            if gs is None:
                continue

            # collect gaussians
            gs["class_labels"] = torch.full(
                (gs["_means"].shape[0],),
                self.gaussian_classes[class_name],
                device=self.device,
            )

            if self.gaussian_classes[class_name] == GSModelType.RigidNodes and "_rigid_instance_ids_mask" in gs:
                # Found dynamic assets Gaussian
                found_dynamic_assets_gs = True
                
                # convert rigid instance ids mask to special class labels
                prev_count = (gs["class_labels"] == GSModelType.DynamicAssets).sum().item()
                gs["class_labels"][gs["_rigid_instance_ids_mask"]] = GSModelType.DynamicAssets
                new_count = (gs["class_labels"] == GSModelType.DynamicAssets).sum().item()
                logging.info(f"After assignment: {new_count} points labeled as DynamicAssets (+{new_count - prev_count})")

            for k, _ in gs.items():
                if k == "_rigid_instance_ids_mask": 
                    continue
                gs_dict[k].append(gs[k])

        for k, v in gs_dict.items():
            gs_dict[k] = torch.cat(v, dim=0)

        # get the class labels
        self.pts_labels = gs_dict.pop("class_labels")

        if found_dynamic_assets_gs:
            # move dynamic assets height to ground level
            gs_dict = self.move_dynamic_assets_height_to_ground(gs_dict, self.pts_labels)

        if self.render_dynamic_mask:
            self.dynamic_pts_mask = (self.pts_labels != GSModelType.Background).float()
            if GSModelType.Ground in self.gaussian_classes:
                self.dynamic_pts_mask = self.dynamic_pts_mask & (self.pts_labels != GSModelType.Ground).float()

        gaussians = dataclass_gs(
            _means=gs_dict["_means"],
            _scales=gs_dict["_scales"],
            _quats=gs_dict["_quats"],
            _rgbs=gs_dict["_rgbs"],
            _opacities=gs_dict["_opacities"],
            detach_keys=[],  # if "means" in detach_keys, then the means will be detached
            extras=None,  # to save some extra information (TODO) more flexible way
        )

        return gaussians

    def collect_gaussians_of_multi_cams(
        self,
        cams: List[dataclass_camera],
        image_ids: torch.Tensor,  # leave it here for future use
    ) -> dataclass_gs:
        gs_dict = {
            "_means": [],
            "_scales": [],
            "_quats": [],
            "_rgbs": [],
            "_opacities": [],
            "class_labels": [],
        }
        cam = cams[0]
        found_dynamic_assets_gs = False
        for class_name in self.gaussian_classes.keys():
            gs = self.models[class_name].get_gaussians_multi_cam(cams)
            # print(f"class_name = {class_name} cam.camera_id = {cam.camera_id} _rgbs = {gs['_rgbs'].sum()} _means = {gs['_means'].sum()}")
            if gs is None:
                continue

            # collect gaussians
            gs["class_labels"] = torch.full(
                (gs["_means"].shape[0],),
                self.gaussian_classes[class_name],
                device=self.device,
            )

            if self.gaussian_classes[class_name] == GSModelType.RigidNodes and "_rigid_instance_ids_mask" in gs:
                # Found dynamic assets Gaussian
                found_dynamic_assets_gs = True
                
                # convert rigid instance ids mask to special class labels
                prev_count = (gs["class_labels"] == GSModelType.DynamicAssets).sum().item()
                gs["class_labels"][gs["_rigid_instance_ids_mask"]] = GSModelType.DynamicAssets
                new_count = (gs["class_labels"] == GSModelType.DynamicAssets).sum().item()
                logging.info(f"After assignment: {new_count} points labeled as DynamicAssets (+{new_count - prev_count})")
            for k, _ in gs.items():
                if k == "_rigid_instance_ids_mask": 
                    continue
                gs_dict[k].append(gs[k])

        for k, v in gs_dict.items():
            if k == "_rgbs": 
                gs_dict[k] = torch.cat(v, dim=1)
            else:
                gs_dict[k] = torch.cat(v, dim=0)

        # get the class labels
        self.pts_labels = gs_dict.pop("class_labels")

        if found_dynamic_assets_gs:
            # move dynamic assets height to ground level
            gs_dict = self.move_dynamic_assets_height_to_ground(gs_dict, self.pts_labels)

        if self.render_dynamic_mask:
            self.dynamic_pts_mask = (self.pts_labels != GSModelType.Background).float()
            if GSModelType.Ground in self.gaussian_classes:
                self.dynamic_pts_mask = self.dynamic_pts_mask & (self.pts_labels != GSModelType.Ground).float()

        gaussians = dataclass_gs(
            _means=gs_dict["_means"],
            _scales=gs_dict["_scales"],
            _quats=gs_dict["_quats"],
            _rgbs=gs_dict["_rgbs"],
            _opacities=gs_dict["_opacities"],
            detach_keys=[],  # if "means" in detach_keys, then the means will be detached
            extras=None,  # to save some extra information (TODO) more flexible way
        )

        return gaussians

    def render_gaussians(
        self,
        gs: dataclass_gs,
        cam: dataclass_camera,
        retain_grad: bool = True,
        use_xpeng_raster: bool = False,
        **kwargs,
    ) -> Dict[str, torch.Tensor]:
        def render_fn(opaticy_mask=None, return_info=False):
            renders, alphas, info = rasterization(
                means=gs.means,
                quats=gs.quats,
                scales=gs.scales,
                opacities=(
                    gs.opacities.squeeze() * opaticy_mask if opaticy_mask is not None else gs.opacities.squeeze()
                ),
                colors=gs.rgbs,
                viewmats=torch.linalg.inv(cam.camtoworlds)[None, ...],  # [C, 4, 4]
                Ks=cam.Ks[None, ...],  # [C, 3, 3]
                width=cam.W,
                height=cam.H,
                packed=self.render_cfg.packed,
                backgrounds=self.back_color[None, ...],
                absgrad=self.render_cfg.absgrad,
                sparse_grad=self.render_cfg.sparse_grad,
                rasterize_mode=("antialiased" if self.render_cfg.antialiased else "classic"),
                **kwargs,
            )
            renders = renders[0]
            alphas = alphas[0].squeeze(-1)
            assert self.render_cfg.batch_size == 1, "batch size must be 1, will support batch size > 1 in the future"

            if renders.shape[-1] == 4:
                rendered_rgb, rendered_depth = torch.split(renders, [3, 1], dim=-1)
            else:
                rendered_rgb = renders
                rendered_depth = None
                
            if info["radii"].dim() == 3:
                info["radii"] = torch.amax(info["radii"], dim=-1)

            if not return_info:
                return (
                    torch.clamp(rendered_rgb, max=1.0),
                    rendered_depth,
                    alphas[..., None],
                )
            else:
                return (
                    torch.clamp(rendered_rgb, max=1.0),
                    rendered_depth,
                    alphas[..., None],
                    info,
                )

        def render_xpeng_raster(opaticy_mask=None, return_info=False):
            renders, alphas, info = xpeng_raster_rasterization(
                means=gs.means,
                quats=gs.quats,
                scales=gs.scales,
                opacities=(
                    gs.opacities.squeeze() * opaticy_mask if opaticy_mask is not None else gs.opacities.squeeze()
                ),
                colors=gs.rgbs,
                viewmats=torch.linalg.inv(cam.camtoworlds)[None, ...],  # [C, 4, 4]
                Ks=cam.Ks[None, ...],  # [C, 3, 3]
                width=cam.W,
                height=cam.H,
                tile_size=6,
                near_plane=0.2,
                far_plane=1000,
            )
            renders = renders[0]
            alphas = alphas[0].squeeze(-1)
            assert self.render_cfg.batch_size == 1, "batch size must be 1, will support batch size > 1 in the future"

            if renders.shape[-1] == 4:
                rendered_rgb, rendered_depth = torch.split(renders, [3, 1], dim=-1)
            else:
                rendered_rgb = renders
                rendered_depth = None
                
            if info["radii"].dim() == 3:
                info["radii"] = torch.amax(info["radii"], dim=-1)

            if not return_info:
                return (
                    torch.clamp(rendered_rgb, max=1.0),
                    rendered_depth,
                    alphas[..., None],
                )
            else:
                return (
                    torch.clamp(rendered_rgb, max=1.0),
                    rendered_depth,
                    alphas[..., None],
                    info,
                )

        # render rgb and opacity
        if use_xpeng_raster:
            rgb, depth, opacity, self.info = render_xpeng_raster(return_info=True)
        else:
            rgb, depth, opacity, self.info = render_fn(return_info=True)
            
        results = {"rgb_gaussians": rgb, "depth": depth, "opacity": opacity}

        if self.training and retain_grad:
            self.info["means2d"].retain_grad()

        return results, render_xpeng_raster if use_xpeng_raster else render_fn

    def multi_cam_render_gaussians(
        self,
        gs: dataclass_gs,
        cams: List[dataclass_camera],
        far_plane_list,
        retain_grad: bool = True,
        **kwargs,
    ) -> Dict[str, torch.Tensor]:
        # currently only support forward, and only used in simulation rendering
        def batch_render_xpeng_raster(cams, opaticy_mask=None, return_info=False):
            # 收集所有相机的参数
            viewmats_list = []
            Ks_list = []
            width_list = []
            height_list = []
            for cam in cams:
                # 获取视图矩阵（世界到相机矩阵）
                viewmat = torch.linalg.inv(cam.camtoworlds)
                viewmats_list.append(viewmat)
                
                # 获取内参矩阵
                Ks_list.append(cam.Ks)
                width_list.append(cam.W)
                height_list.append(cam.H)
            # 堆叠所有相机的参数
            viewmats = torch.stack(viewmats_list, dim=0)  # [C, 4, 4]
            Ks = torch.stack(Ks_list, dim=0)  # [C, 3, 3]
            
            # # 获取宽度和高度（假设所有相机相同）
            # width = cams[0].W
            # height = cams[0].H
            width = max(width_list)
            height = max(height_list)
            tile_size = 6
            tile_width = (width + tile_size - 1) // tile_size
            tile_height = (height + tile_size - 1) // tile_size
            tile_masks = torch.zeros(len(cams),  tile_height, tile_width, dtype=torch.bool, device=gs.rgbs.device)
            for i, (h, w) in enumerate(zip(height_list, width_list)):
                ch = (h + tile_size - 1) // tile_size
                cw = (w + tile_size - 1) // tile_size
                tile_masks[i][:ch, :cw] = True
            assert gs.rgbs.dim() == 3 and gs.rgbs.shape[0] == viewmats.shape[0] and gs.rgbs.shape[2] == 3, f"gs.rgbs shape should be [C, N, 3], but got {gs.rgbs.shape} with viewmats shape {viewmats.shape}"
            if len(far_plane_list) > 0:
                far_planes = torch.tensor(far_plane_list).unsqueeze(0)
                renders, alphas, info = xpeng_raster_rasterization(
                    means=gs.means,
                    quats=gs.quats,
                    scales=gs.scales,
                    opacities=(
                        gs.opacities.squeeze() * opaticy_mask if opaticy_mask is not None else gs.opacities.squeeze()
                    ),
                    colors=gs.rgbs,
                    viewmats=viewmats,  # 现在支持多个相机 [C, 4, 4]
                    Ks=Ks,  # 现在支持多个相机 [C, 3, 3]
                    width=width,
                    height=height,
                    tile_size=tile_size,
                    near_plane=0.2,
                    far_planes=far_planes,
                    masks=tile_masks,
                )
            else:
                renders, alphas, info = xpeng_raster_rasterization(
                    means=gs.means,
                    quats=gs.quats,
                    scales=gs.scales,
                    opacities=(
                        gs.opacities.squeeze() * opaticy_mask if opaticy_mask is not None else gs.opacities.squeeze()
                    ),
                    colors=gs.rgbs,
                    viewmats=viewmats,  # 现在支持多个相机 [C, 4, 4]
                    Ks=Ks,  # 现在支持多个相机 [C, 3, 3]
                    width=width,
                    height=height,
                    tile_size=tile_size,
                    near_plane=0.2,
                    far_plane=1000,
                    masks=tile_masks,
                )

            renders = renders
            alphas = alphas.squeeze(-1)
    
            if renders.shape[-1] == 4:
                rendered_rgb, _ = torch.split(renders, [3, 1], dim=-1)
            else:
                rendered_rgb = renders
                
            if info["radii"].dim() == 3:
                info["radii"] = torch.amax(info["radii"], dim=-1)

            if not return_info:
                return (
                    torch.clamp(renders, max=1.0), None,
                    alphas.unsqueeze(-1) if alphas.dim() == rendered_rgb.dim() - 1 else alphas,
                )
            else:
                return (
                    torch.clamp(rendered_rgb, max=1.0), None,
                    alphas.unsqueeze(-1) if alphas.dim() == rendered_rgb.dim() - 1 else alphas, info,
                )

        # render rgb and opacity
        rgb_batch, _, opacity_batch, self.info = batch_render_xpeng_raster(cams, return_info=True)
        rgb_batch_split = torch.split(rgb_batch, 1, dim=0) 
        opacity_batch_split = torch.split(opacity_batch, 1, dim=0)  
        results = []
        for cam, rgb, opacity in zip(cams, rgb_batch_split, opacity_batch_split):
            result = {"rgb_gaussians": rgb.squeeze(dim=0)[:cam.H, :cam.W], "depth": None, "opacity": opacity.squeeze(dim=0)[:cam.H, :cam.W]}
            results.append(result)

        if self.training and retain_grad:
            self.info["means2d"].retain_grad()

        return results

    def affine_transformation(self, rgb_blended: torch.Tensor, image_info: ImageInfo, camera_info: CameraInfo = None):
        # If Affine model not enabled, bypass.
        if self.use_feedforward_render or "Affine" not in self.models:
            return rgb_blended

        # Camera gating: by default apply to all cameras unless config specifies a subset.
        should_apply = True
        try:
            affine_cfg = self.model_config.get("Affine", {})
            affine_params = affine_cfg.get("params", {}) if isinstance(affine_cfg, dict) else {}
            apply_names = affine_params.get("apply_camera_names", None)
            apply_ids = affine_params.get("apply_camera_ids", None)

            if (apply_names is not None or apply_ids is not None) and camera_info is not None:
                should_apply = False
                cam_name = getattr(camera_info, "camera_name", None)
                cam_id = getattr(camera_info, "camera_id", None)
                if apply_names is not None and cam_name is not None and cam_name in apply_names:
                    should_apply = True
                if apply_ids is not None and cam_id is not None and cam_id in apply_ids:
                    should_apply = True
        except Exception:
            # Fail-open: if any unexpected config format, keep applying to avoid blocking training
            should_apply = True

        if not should_apply:
            return rgb_blended

        affine_trs = self.models["Affine"](image_info, camera_info)
        rgb_transformed = (affine_trs[..., :3, :3] @ rgb_blended[..., None] + affine_trs[..., :3, 3:])[..., 0]

        return rgb_transformed