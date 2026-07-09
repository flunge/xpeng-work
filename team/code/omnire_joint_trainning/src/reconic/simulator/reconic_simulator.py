"""ReconicSimulator: core simulator for closed-loop and offline rendering."""

from __future__ import annotations

import json
import os

import numpy as np
import torch
from omegaconf import OmegaConf
from scipy.spatial import cKDTree

from reconic.datasets.base.data_proto import CameraInfo, ImageInfo, ImageMasks, Rays
from reconic.datasets.dataset_meta import DATASETS_CONFIG
from reconic.utils.misc import import_str
from sim_interface.simulator_base import BaseSimulator
from sim_interface.utils import split_ground_points_by_trajectory_segments

from ..utils.camera import get_camera_original_size_by_vehicle_model
from .closed_loop_api import fun, fun_one_frame
from .cp_pose import compute_rig2anchor
from .render_split_region import select_region_masks
from .simulator_constants import (
    CAMERA2LABEL,
    COLLISION_RIGID_CLASSES,
    LABEL2CAMERA,
    RIGID_NODE_CLASSES,
)
from .simulator_helpers import numpy_array_to_bytes, resolve_config_path, to8b

__all__ = [
    "ReconicSimulator",
    "fun",
    "fun_one_frame",
    "numpy_array_to_bytes",
    "to8b",
]


class ReconicSimulator(BaseSimulator):
    def __init__(
        self,
        args,
        device="cuda",
        cp_simulation=False,
        iter=None,
        state_dict=None,
        init_from_feedforward=False,
        vehicle_model=None,
        init_from_fastmode=False,
    ):
        config_path = resolve_config_path(args, init_from_fastmode, init_from_feedforward)
        self.device = device
        self.state_dict = state_dict
        super().__init__(
            config=config_path,
            cp_simulation=cp_simulation,
            iter=iter,
            init_from_feedforward=init_from_fastmode or init_from_feedforward,
            vehicle_model=vehicle_model,
        )
        self.load_calibrations()
        self.cp_simulation = cp_simulation

        if self.cp_simulation:
            self._setup_cp_simulation()

        self.use_split_render = False  # hack here 20260205
        if self.use_split_render:
            self._setup_split_render_regions()

        self._clipiqa_model = None  
        self.clipiqa = None       
        if os.environ.get('CLIPIQA_ENABLED', 'false').lower() != 'false':
            try:
                from .clipiqa_helper import ClipIQAHelper
                self.clipiqa = ClipIQAHelper()
                self.clipiqa.init_model()
            except Exception as _e:
                print(f"[CLIP-IQA] 自动初始化失败（可设置环境变量 CLIPIQA_ENABLED=false 关闭）: {_e}", flush=True)
                self.clipiqa = None

    @property
    def _label2camera(self):
        return LABEL2CAMERA

    @property
    def _camera2label(self):
        return CAMERA2LABEL

    # ------------------------------------------------------------------ setup
    # ─────────────────────────── CLIP-IQA 薄委托包装 ─────────────────────────

    def save_clipiqa_scores(self, save_path: str = None) -> None:
        """（向后兼容）委托给 self.clipiqa.save_scores()。"""
        if self.clipiqa is not None:
            self.clipiqa.save_scores(self.model_path, save_path)
        else:
            print("[CLIP-IQA] 未初始化，跳过保存。", flush=True)

    def apply_clipiqa_to_info(
        self,
        info: dict,
        img_rgb,
        camera: str,
        rendered_timestamp: int,
        real_car_image=None,
    ) -> None:
        """（由 closed_loop_api 通过 duck-typing 调用）委托给 self.clipiqa.apply_to_info()。"""
        if self.clipiqa is not None:
            self.clipiqa.apply_to_info(
                info, img_rgb, camera, rendered_timestamp,
                self.model_path, real_car_image=real_car_image,
            )

    # ─────────────────────────────────────────────────────────────────────────

    def _setup_cp_simulation(self):
        self.gaussian.render_cfg["render_each_class"] = False
        self._replace_cam2rig_with_origin_calib()

        self.ground_xyz = self.gaussian.models["Ground"].get_xyz.detach().cpu().numpy()
        self.ground_xy = self.ground_xyz[:, :2]
        self.ground_z = self.ground_xyz[:, 2]
        self.ground_ply_index = cKDTree(self.ground_xy)

        dds_positions = np.array([pose[:3, 3] for pose in self.dds_localpose.values()])
        self.dds_localpose_kdtree = cKDTree(dds_positions)
        self.dds_localpose_list = list(self.dds_localpose.values())

        train_anchor_pose = self.anchor_pose
        self.train_localpose_anchor = {
            k: np.linalg.inv(train_anchor_pose) @ v for k, v in self.train_localpose.items()
        }
        train_positions = np.array([pose[:3, 3] for pose in self.train_localpose_anchor.values()])
        self.train_localpose_kdtree = cKDTree(train_positions)
        self.train_localpose_list = list(self.train_localpose_anchor.values())

    def _setup_split_render_regions(self):
        ground_xy = self.gaussian.models["Ground"].get_xyz.detach().cpu().numpy()[:, :2]
        dds_positions = np.array([pose[:3, 3] for pose in self.egoposes_anchored_origin])
        self.region_masks, self.poly_vertices = split_ground_points_by_trajectory_segments(
            dds_positions, ground_xy, rect_width=25.0
        )

    def init_models(self, config):
        test_indices = []
        self.gaussian = import_str(self.cfg.recon_trainer.type)(
            **self.cfg.recon_trainer,
            num_timesteps=self.num_frames,
            model_config=self.cfg.model,
            num_train_images=self.num_frames * self.num_cams,
            num_full_images=self.num_frames * self.num_cams,
            test_set_indices=test_indices,
            scene_aabb=torch.tensor(self.cfg.data.lidar_source.aabb).reshape(2, 3),
            device=self.device,
            disable_metric=True,
            data_source=self.cfg.data.data_source,
            model_path=self.model_path,
        )
        if self.simulator_config_manager.should_load_difix():
            self.init_difix_model()

    def init_difix_model(self):
        difix_config = self.simulator_config_manager.get_difix_config()
        if difix_config is None:
            raise ValueError("No Difix configuration found")

        if not hasattr(self.cfg, "fixer"):
            self.cfg.fixer = OmegaConf.create(difix_config)
        else:
            for key, value in difix_config.items():
                setattr(self.cfg.fixer, key, value)

        if self.cfg.fixer.get("use_tensorrt", False):
            print("[INFO] use tensorrt for difix")
            from models.difix.fixerTrt import DifixTrtFixer

            self.image_fixer = DifixTrtFixer(self.cfg.fixer)
        else:
            print("[INFO] use torch model for difix")
            from models.difix.fixer import DifixFixer

            self.image_fixer = DifixFixer(self.cfg.fixer)

    def setup_models(self, config, iter=None):
        if self.state_dict is None:
            if iter is None:
                ckpt_path = os.path.join(self.model_path, "trained_model", "checkpoint_final.pth")
            else:
                ckpt_path = os.path.join(
                    self.model_path, "trained_model", f"checkpoint_{int(iter):05d}.pth"
                )
            self.gaussian.resume_from_checkpoint(ckpt_path=ckpt_path, load_only_model=True)
        else:
            self.gaussian.load_state_dict(self.state_dict, load_only_model=False, strict=False)
        self.gaussian.set_eval()
        self._interpolate_missing_poses_for_render()
        self._log_gaussian_counts()
        self._apply_scenario_modifications()

    def _interpolate_missing_poses_for_render(self):
        ego_positions = None
        if hasattr(self, "egoposes_anchored_origin") and len(self.egoposes_anchored_origin) > 0:
            ego_positions_np = np.asarray(self.egoposes_anchored_origin)[:, :3, 3]
            ego_positions = torch.from_numpy(ego_positions_np).float().to(torch.device(self.device))
        max_ego_distance = 100.0
        for node_name in RIGID_NODE_CLASSES:
            if node_name not in getattr(self.gaussian, "models", {}):
                continue
            node = self.gaussian.models[node_name]
            if not hasattr(node, "interpolate_missing_instance_poses_for_render"):
                continue
            try:
                node.interpolate_missing_instance_poses_for_render(
                    ego_positions=ego_positions,
                    max_ego_distance=max_ego_distance,
                )
            except Exception as e:
                print(f"[WARNING][RenderPoseInterp] {node_name} interpolation failed: {e}")

    def _log_gaussian_counts(self):
        total_gaussian = 0
        for gaussian_name in self.gaussian.gaussian_classes.keys():
            count = self.gaussian.models[gaussian_name]._means.shape[0]
            print(gaussian_name, " have gaussian", count)
            total_gaussian += count
            if hasattr(self.gaussian.models[gaussian_name], "in_training_job"):
                self.gaussian.models[gaussian_name].in_training_job = False
        print("total gaussian:", total_gaussian)

    def _apply_scenario_modifications(self):
        scenario_modify_json = os.path.join(self.model_path, "modified_obj.json")
        if not os.path.exists(scenario_modify_json):
            return
        scenario_modify = json.load(open(scenario_modify_json, "r"))
        print(f"[INFO] found scenario_modify json: {scenario_modify_json}")
        for node_name in ("RigidNodes", "RigidNodesLight"):
            if node_name in self.gaussian.models:
                self.gaussian.models[node_name].modify_obj_by_json(
                    scenario_modify, self.model_path, node_name
                )

    def setup_feedforward_models(self, config):
        self.gaussian.load_from_feedforward(self.source_data_path)

    def init_parameters(self, config, vehicle_model=None):
        # model_path/configs/config_sim.yaml
        self.model_path = os.path.dirname(os.path.dirname(config))
        self.data_path = self.model_path
        configs_dir = os.path.dirname(config)

        # ---- 优化: 优先加载 slim yaml + npz 缓存，大幅减少 OmegaConf 解析耗时 ---- #
        npz_path = os.path.join(configs_dir, "results_cache.npz")
        slim_yaml_path = os.path.join(configs_dir, "config_sim_slim.yaml")
        if os.path.exists(npz_path):
            # 有 npz 缓存: 加载精简 yaml（无大数组）+ npz
            if os.path.exists(slim_yaml_path):
                self.cfg = OmegaConf.load(slim_yaml_path)
            else:
                self.cfg = OmegaConf.load(config)
            _cache = np.load(npz_path, allow_pickle=False)
            self.timestamps_origin = _cache["timestamps"].tolist()
            self.egoposes_anchored_origin = _cache["ego_frame_poses"]
            self.anchor_pose = _cache["anchor_pose"]
        else:
            # 兼容旧数据: 无 npz 时走原始 yaml 解析路径
            self.cfg = OmegaConf.load(config)
            self.timestamps_origin = [int(i) for i in self.cfg.results.timestamps]
            self.egoposes_anchored_origin = np.array(self.cfg.results.ego_frame_poses)
            self.anchor_pose = np.array(self.cfg.results.anchor_pose)

        # 保存原始 4×4 anchor_pose 备份:
        # convert_anchorpose_to_transferpose() 会将 self.anchor_pose 改写为 dict，
        # load_calibrations() 需要将其复位为 4×4 矩阵，通过此备份避免再次读取 cfg/npz。
        self._raw_anchor_pose = self.anchor_pose

        self.source_data_path = os.path.join(self.cfg.data.data_root, self.cfg.data.scene_idx)
        # ---- Actual timestamps ---- #
        localpose = json.load(open(os.path.join(self.data_path, "localpose.json")))
        self.actual_timestamps = sorted([int(k) for k in localpose.keys()])
        self.num_frames = len(self.actual_timestamps)
        self.start_timestep, self.end_timestep = self.cfg.data.start_timestep, self.cfg.data.end_timestep
        if self.end_timestep < 0:
            self.end_timestep = self.num_frames
        self.selected_frames = range(self.start_timestep, self.end_timestep)
        self.num_frames = len(self.selected_frames)
        self.cameras = self.cfg.data.pixel_source.cameras
        self.num_cams = len(self.cameras)
        self.cam_names = [
            DATASETS_CONFIG["xpeng"][cam_id]["camera_name"]
            for cam_id in DATASETS_CONFIG["xpeng"].keys()
        ]
        self.downscale = 1 / self.cfg.data.pixel_source.downscale
        self.dis_shift = self.cfg.render.render_novel.traj_types[0].distance

        meta_json = json.load(open(os.path.join(self.data_path, "metadata.json"), "r"))
        self.vehicle_model_origin = meta_json.get("vehicle_model", None)
        self.vehicle_model = vehicle_model if vehicle_model is not None else self.vehicle_model_origin

    # ------------------------------------------------------------------ calib
    def load_calibrations(self):
        """
        Load the camera intrinsics, extrinsics, timestamps, etc.
        Compute the camera-to-world matrices, ego-to-world matrices, etc.
        """
        # convert_anchorpose_to_transferpose() 可能将 self.anchor_pose 改写为 dict，
        # 此处无条件从 init_parameters 保存的 4×4 矩阵备份复位。
        # slim yaml 中 anchor_pose 为 null，不可从 cfg 读取，故必须用备份。
        self.anchor_pose = self._raw_anchor_pose
        transform_json = json.load(open(os.path.join(self.data_path, "transform.json")))
        self.calib_dict = {}
        for cam_id in self.cameras:
            self.calib_dict[cam_id] = self._load_single_camera_calib(cam_id, transform_json)

    def _load_single_camera_calib(self, cam_id, transform_json):
        cam_name = DATASETS_CONFIG["xpeng"][cam_id]["camera_name"]
        transform_matrix = {
            frame["timestamp"]: frame["transform_matrix"]
            for frame in transform_json["frames"]
            if cam_name == frame["camera"]
        }
        cam_to_ego = transform_json["sensor_params"][cam_name]["extrinsic"]
        intrinsic = transform_json["sensor_params"][cam_name]["camera_intrinsic"]
        distortion = transform_json["sensor_params"][cam_name]["camera_D"]

        crop_cam_name = "noncrop" + cam_name
        expand_ratio = self.calib_info["expand_ratio"][cam_name]
        intrinsic[0][0] = self.calib_info[crop_cam_name]["intrinsic"]["focal_length_x"] * expand_ratio
        intrinsic[0][2] = self.calib_info[crop_cam_name]["intrinsic"]["cx"] * expand_ratio
        intrinsic[1][1] = self.calib_info[crop_cam_name]["intrinsic"]["focal_length_y"] * expand_ratio
        intrinsic[1][2] = self.calib_info[crop_cam_name]["intrinsic"]["cy"] * expand_ratio

        intrinsics, distortions, cam_to_worlds = [], [], []
        for t in range(self.start_timestep, self.end_timestep):
            intrinsics.append(intrinsic)
            distortions.append(distortion)
            cam_to_worlds.append(transform_matrix[self.actual_timestamps[t]])

        cam_to_ego_inv = np.linalg.inv(cam_to_ego)
        ego_to_worlds = [cam_to_world @ cam_to_ego_inv for cam_to_world in cam_to_worlds]

        return {
            "intrinsics": torch.from_numpy(np.stack(intrinsics, axis=0)).float(),
            "distortions": torch.from_numpy(np.stack(distortions, axis=0)).float(),
            "cam_to_worlds": torch.from_numpy(np.stack(cam_to_worlds, axis=0)).float(),
            "ego_to_worlds": torch.from_numpy(np.stack(ego_to_worlds, axis=0)).float(),
            "cam_to_ego": torch.from_numpy(np.array(cam_to_ego)).float(),
        }

    def get_camera(self, cam_id):
        return self.calib_dict[cam_id]["cam_to_ego"]

    # ------------------------------------------------------------------ render
    def _resolve_cam_id(self, camera):
        cam_id = self._camera2label[camera]
        if cam_id not in self.cameras:
            print(
                f"Get cam_id {cam_id}, but model cameras are {self.cameras}, render failed, return None",
                flush=True,
            )
            return None
        return cam_id

    @staticmethod
    def _to_device(image_info, cam_info, device):
        with torch.no_grad():
            image_info.to(torch.device(device))
            cam_info.to(torch.device(device))

    def _apply_collision_info(self, image_info, cam_info, ego_pose_world, collision_info_arr):
        if not collision_info_arr:
            return
        for collision_info in collision_info_arr:
            for rigid_class in COLLISION_RIGID_CLASSES:
                self.find_obj_by_col_info(
                    image_info, cam_info, ego_pose_world, rigid_class, collision_info
                )

    def render(self, camera, timestamp, ego_pose_world, collision_info_arr=None):
        collision_info_arr = collision_info_arr or []
        cam_id = self._resolve_cam_id(camera)
        if cam_id is None:
            return None, None

        image_info, cam_info = self.get_novel_view_info(timestamp, ego_pose_world, cam_id)
        self._apply_collision_info(image_info, cam_info, ego_pose_world, collision_info_arr)
        self._to_device(image_info, cam_info, self.device)

        with torch.no_grad():
            result = self.gaussian(image_info, cam_info, use_xpeng_raster=True)
        return result, cam_info.camera_name

    def render_multi_cam(
        self,
        cameras,
        timestamp,
        ego_pose_world,
        far_plane_list=None,
        collision_info_arr=None,
        use_sky_scale=False,
    ):
        far_plane_list = far_plane_list or []
        collision_info_arr = collision_info_arr or []
        image_infos, cam_infos = [], []

        for camera in cameras:
            cam_id = self._resolve_cam_id(camera)
            if cam_id is None:
                return None, None

            image_info, cam_info = self.get_novel_view_info(timestamp, ego_pose_world, cam_id)
            if collision_info_arr:
                for collision_info in collision_info_arr:
                    self.find_obj_by_col_info(
                        image_info, cam_info, ego_pose_world, collision_info
                    )
            self._to_device(image_info, cam_info, self.device)
            image_infos.append(image_info)
            cam_infos.append(cam_info)

        with torch.no_grad():
            return self.gaussian.multi_cam_render_with_fixer(
                image_infos,
                cam_infos,
                far_plane_list,
                use_xpeng_raster=True,
                use_sky_scale=use_sky_scale,
            )

    def render_hil(self, camera, timestamp, ego_pose_world):
        cam_id = self._resolve_cam_id(camera)
        if cam_id is None:
            return None, None

        image_info, cam_info = self.get_novel_view_info(timestamp, ego_pose_world, cam_id)
        self._to_device(image_info, cam_info, self.device)

        with torch.no_grad():
            if self.use_split_render:
                true_region_masks = select_region_masks(
                    self.region_masks, self.poly_vertices, cam_info.camera_to_world
                )
            else:
                true_region_masks = None
            result = self.gaussian.render_xpeng_raster(
                image_info, cam_info, true_region_masks=true_region_masks
            )
        return result, cam_info.camera_name

    # ---------------------------------------------------------------- novel view
    def get_rays(
        self,
        x: torch.Tensor,
        y: torch.Tensor,
        c2w: torch.Tensor,
        intrinsic: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        if len(intrinsic.shape) == 2:
            intrinsic = intrinsic[None, :, :]
        if len(c2w.shape) == 2:
            c2w = c2w[None, :, :]
        camera_dirs = torch.nn.functional.pad(
            torch.stack(
                [
                    (x - intrinsic[:, 0, 2] + 0.5) / intrinsic[:, 0, 0],
                    (y - intrinsic[:, 1, 2] + 0.5) / intrinsic[:, 1, 1],
                ],
                dim=-1,
            ),
            (0, 1),
            value=1.0,
        )
        directions = (camera_dirs[:, None, :] * c2w[:, :3, :3]).sum(dim=-1)
        origins = torch.broadcast_to(c2w[:, :3, -1], directions.shape)
        direction_norm = torch.linalg.norm(directions, dim=-1, keepdims=True)
        viewdirs = directions / (direction_norm + 1e-8)
        return origins, viewdirs, direction_norm

    def prepare_novel_view_render_data(
        self, c2w: torch.Tensor, timestamp_sim: int, cam_id: int
    ) -> tuple[ImageInfo, CameraInfo]:
        cam_idx = self.cameras.index(cam_id)
        cam_name = DATASETS_CONFIG["xpeng"][cam_id]["camera_name"]
        original_size = get_camera_original_size_by_vehicle_model(
            "xpeng", cam_id, self.vehicle_model
        )

        frame_idx = 0
        timestamps_array = np.array(self.actual_timestamps)
        valid_indices = np.where(timestamps_array <= timestamp_sim)[0]
        if len(valid_indices) > 0:
            frame_idx = valid_indices[np.argmax(timestamps_array[valid_indices])]

        image_idx = cam_idx + frame_idx * self.num_cams
        expand_ratio = self.calib_info["expand_ratio"][cam_name]
        H = int(original_size[0] * self.downscale * expand_ratio)
        W = int(original_size[1] * self.downscale * expand_ratio)

        x, y = torch.meshgrid(
            torch.arange(W, device=self.device),
            torch.arange(H, device=self.device),
            indexing="xy",
        )
        origins, viewdirs, direction_norm = self.get_rays(
            x.flatten(),
            y.flatten(),
            c2w.to(self.device),
            self.calib_dict[cam_id]["intrinsics"][frame_idx].to(self.device),
        )
        origins = origins.reshape(H, W, 3)
        viewdirs = viewdirs.reshape(H, W, 3)
        direction_norm = direction_norm.reshape(H, W, 1)

        cam_info = CameraInfo(
            camera_to_world=c2w,
            intrinsic=self.calib_dict[cam_id]["intrinsics"][frame_idx],
            height=H,
            width=W,
            camera_id=cam_id,
            camera_name=cam_name,
        )

        normalized_ts = (timestamp_sim - self.actual_timestamps[0]) / (
            self.actual_timestamps[-1] - self.actual_timestamps[0]
        )
        normalized_ts = max(0, normalized_ts)

        if frame_idx + 1 >= len(self.actual_timestamps):
            fraction_from_cur_frame = 0.0
        else:
            fraction_from_cur_frame = (timestamp_sim - self.actual_timestamps[frame_idx]) / (
                self.actual_timestamps[frame_idx + 1] - self.actual_timestamps[frame_idx]
            )

        image_info = ImageInfo(
            rays=Rays(origins=origins, viewdirs=viewdirs, direction_norm=direction_norm),
            masks=ImageMasks(
                sky_mask=None,
                ground_mask=None,
                dynamic_mask=None,
                human_mask=None,
                vehicle_mask=None,
                egocar_mask=None,
            ),
            image_index=torch.tensor(image_idx),
            frame_index=torch.tensor(frame_idx),
            normalized_time=torch.tensor(normalized_ts),
            fraction_from_cur_frame=fraction_from_cur_frame,
            pixel_coords=torch.stack([y.float() / H, x.float() / W], dim=-1),
        )
        return image_info, cam_info

    def get_novel_view_info(self, timestamp_sim, rig2world, cam_id):
        cams2rig = self.get_camera(cam_id).clone().detach().numpy()

        if self.cp_simulation:
            anchor_pose = self.get_anchor_pose(rig2world)
            rig2anchor = compute_rig2anchor(
                timestamp_sim,
                rig2world,
                cp_simulation=True,
                anchor_pose=anchor_pose,
                dds_localpose_kdtree=self.dds_localpose_kdtree,
                dds_localpose_list=self.dds_localpose_list,
                train_localpose_kdtree=self.train_localpose_kdtree,
                train_localpose_list=self.train_localpose_list,
            )
        else:
            rig2anchor = compute_rig2anchor(
                timestamp_sim,
                rig2world,
                cp_simulation=False,
                anchor_pose=self.anchor_pose,
                dds_localpose_kdtree=None,
                dds_localpose_list=None,
                train_localpose_kdtree=None,
                train_localpose_list=None,
            )

        cam2anchor = torch.from_numpy(rig2anchor @ cams2rig).to(torch.float32)
        return self.prepare_novel_view_render_data(cam2anchor, timestamp_sim, cam_id)

    def find_obj_by_col_info(
        self, image_info, cam_info, ego_pose_world, target_rigid_class, col_info=None
    ):
        col_info = col_info or []
        if target_rigid_class not in self.gaussian.models:
            print(
                f"[Smart Agent Info] no {target_rigid_class} in gaussian models, "
                "cannot find obj by collision info"
            )
            return

        rigid_node = self.gaussian.models[target_rigid_class]
        all_obj_ids = rigid_node.point_ids.unique().tolist()
        col_obj_x, col_obj_y = col_info[0], col_info[1]
        print(
            f"[Smart Agent Info] get info:col_obj_x={col_obj_x}, col_obj_y={col_obj_y}, "
            f"target_rigid_class={target_rigid_class}"
        )

        rigid_pose = rigid_node.instances_trans[image_info.frame_index]
        anchor_pose = self.get_anchor_pose(ego_pose_world)
        rig2world = np.eye(4)
        rig2world[:3, 3] = [col_obj_x, col_obj_y, 0.0]
        rig2anchor = np.linalg.inv(anchor_pose) @ rig2world
        col_obj_x_rig = rig2anchor[:3, 3][0]
        col_obj_y_rig = rig2anchor[:3, 3][1]

        target_id = -1
        min_dis = 99999999
        for obj_id in all_obj_ids:
            obj_x = rigid_pose[obj_id][0]
            obj_y = rigid_pose[obj_id][1]
            if obj_x == 0 or obj_y == 0:
                continue
            dis_diff_squared = abs(obj_x - col_obj_x_rig) ** 2 + abs(obj_y - col_obj_y_rig) ** 2
            if dis_diff_squared < min_dis:
                min_dis = dis_diff_squared
                target_id = obj_id

        if min_dis < 1:
            print("[Smart Agent Info] match! id = ,", target_id)
            rigid_node.set_filter_mask_by_point_ids([target_id])
        else:
            print("[Smart Agent Info] no match! id = ,")
