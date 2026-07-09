import logging
import os
import json
from typing import Literal, Optional

import torch
from omegaconf import OmegaConf
from torch import Tensor
from plyfile import PlyData, PlyElement

import open3d as o3d
import numpy as np

from .xpeng_utils import rescale_points, save_vis_gaussians, extract_static_ids
from ...utils.misc import export_points_to_ply
from ..base.scene_dataset import ModelType, ObjectType, DistLevel
from ..driving_dataset import DrivingDataset

from ...models.gaussians.basics import k_nearest_sklearn, random_quat_tensor
from pytorch3d.transforms import quaternion_to_matrix, matrix_to_quaternion

logger = logging.getLogger()

DEBUG_PCD = False
if DEBUG_PCD:
    DEBUG_OUTPUT_DIR = "debug"
    os.makedirs(DEBUG_OUTPUT_DIR, exist_ok=True)

NAME_TO_NODE = {
    "RigidNodes": ModelType.RigidNodes,
    "SMPLNodes": ModelType.SMPLNodes,
    "DeformableNodes": ModelType.DeformableNodes,
}

class XpengDrivingDataset(DrivingDataset):
    def __init__(
        self,
        project_dir: str,
        cfg: OmegaConf,
        debug_mode: bool = False,
    ) -> None:
        self.model_path = project_dir
        super().__init__(project_dir, cfg, debug_mode)

    def _get_lidar_pts_mask(self, mask_mode: Optional[str] = None) -> torch.Tensor:
        ground_mask = self.lidar_source.ground_mask().bool()
        if mask_mode is None:
            return torch.ones_like(ground_mask).bool()

        if mask_mode == "ground_only":
            return ground_mask
        if mask_mode == "ground_excluded":
            return ~ground_mask
        raise ValueError(f"Invalid mask mode: {mask_mode}")

    def get_lidar_samples(
        self,
        num_samples: Optional[float] = None,
        downsample_factor: Optional[float] = None,
        return_color: bool = False,
        return_normalized_time: bool = False,
        mask_mode: Optional[str] = None,
        model_type: Optional[str] = None,
        device: torch.device = torch.device("cpu"),
    ) -> Tensor:
        assert self.lidar_source is not None, "Must have lidar source if you want to get init pcd"



        pts_xyz = torch.empty(0, 3, dtype=torch.float32)
        colors = torch.empty(0, 3, dtype=torch.float32)
        if model_type == "Trafficlight":
           pts_xyz, colors = self.lidar_source.trafficlight_points()
        else:
           mask = self._get_lidar_pts_mask(mask_mode)
           pts_xyz, colors = self.lidar_source.background_points()
           pts_xyz, colors = pts_xyz[mask], colors[mask]
        if downsample_factor is not None:
            num_samples = int(len(pts_xyz) / downsample_factor)
        if num_samples is None:
            num_samples = len(pts_xyz)
        if num_samples > len(pts_xyz):
            logger.warning(
                f"num_samples {num_samples} is larger than the number of points {len(pts_xyz)}. Using all points."
            )
            num_samples = len(pts_xyz)

        sampled_idx = torch.randperm(len(pts_xyz))[:num_samples]
        sampled_pts = pts_xyz[sampled_idx].to(device)
        sampled_color = None
        if return_color:
            sampled_color = colors[sampled_idx].to(device)

        sampled_time = None
        assert return_normalized_time is False, "Normalized time is not available for Xpeng dataset"

        return sampled_pts, sampled_color, sampled_time

    def _load_random_obj_points(self, obj_size, model_type=None, ins_type=None, base_max_pts=20000, obj_dist_level_dict=DistLevel.Close):
        type_weights = {
            ModelType.RigidNodes: 1.2,
            ModelType.SMPLNodes: 0.8,
            ModelType.DeformableNodes: 1.2,
        }
        volume = obj_size[0] * obj_size[1] * obj_size[2]
        volume_factor = min(max(volume / 10.0, 0.3), 3.0)
        if model_type is not None:
            type_weight = type_weights.get(model_type, 1.0)
        else:
            type_weight = 1.0
        origin_adjusted_max_pts = int(base_max_pts * type_weight * volume_factor)

        max_ptr_upper_bound = 20000
        if obj_dist_level_dict == DistLevel.Mid:
            max_ptr_upper_bound = 15000
        elif obj_dist_level_dict == DistLevel.Far:
            max_ptr_upper_bound = 8000

        raw_adjusted_max_pts = max(8000, min(origin_adjusted_max_pts, 30000))
        adjusted_max_pts = max(8000, min(origin_adjusted_max_pts, max_ptr_upper_bound))

        # if VRU, sample volume points in the bounding box
        is_obj_type_vru = ins_type is not None and ins_type in [ObjectType.Pedestrian, ObjectType.Cyclist, ObjectType.Motorcycle]
        if is_obj_type_vru:  # pedestrian
            adjusted_max_pts = min(8000, origin_adjusted_max_pts)

            half_size = torch.tensor(obj_size) / 2.0  # [hx, hy, hz]
            rand_vals = torch.rand(adjusted_max_pts, 3)  # [N, 3] in [0, 1]
            pointcloud_xyz = (rand_vals * 2.0 - 1.0) * half_size  # scale to [-hx, hx] etc.

            pointcloud_rgb = torch.rand_like(pointcloud_xyz)

            logger.info(f"[VRU] Generated {len(pointcloud_xyz)} volume points for object with size {obj_size}, "
                        f"type {ins_type}, volume_factor {volume_factor:.2f}")
            return pointcloud_xyz, pointcloud_rgb

        # if not VRU, sample surface points on the bounding box
        bbox_xyz_scale = obj_size / 2.0
        surface_thickness = 0.02
        faces = [
            {'axis': 0, 'sign': 1, 'range': [bbox_xyz_scale[0] * (1 - surface_thickness), bbox_xyz_scale[0]]},
            {'axis': 0, 'sign': -1, 'range': [-bbox_xyz_scale[0], -bbox_xyz_scale[0] * (1 - surface_thickness)]},
            {'axis': 1, 'sign': 1, 'range': [bbox_xyz_scale[1] * (1 - surface_thickness), bbox_xyz_scale[1]]},
            {'axis': 1, 'sign': -1, 'range': [-bbox_xyz_scale[1], -bbox_xyz_scale[1] * (1 - surface_thickness)]},
            {'axis': 2, 'sign': 1, 'range': [bbox_xyz_scale[2] * (1 - surface_thickness), bbox_xyz_scale[2]]},
            {'axis': 2, 'sign': -1, 'range': [-bbox_xyz_scale[2], -bbox_xyz_scale[2] * (1 - surface_thickness)]},
        ]

        face_areas = []
        for face in faces:
            if face['axis'] == 0:
                face_area = bbox_xyz_scale[1] * bbox_xyz_scale[2]
            elif face['axis'] == 1:
                face_area = bbox_xyz_scale[0] * bbox_xyz_scale[2]
            else:
                face_area = bbox_xyz_scale[0] * bbox_xyz_scale[1]
            face_areas.append(face_area)
        total_area = sum(face_areas)

        all_surface_points = []
        for i, face in enumerate(faces):
            current_points = int(adjusted_max_pts * face_areas[i] / total_area)
            current_points = max(current_points, 1)

            if face['axis'] == 0: # YZ
                y_length = 2.0 * bbox_xyz_scale[1]
                z_length = 2.0 * bbox_xyz_scale[2]

                aspect_ratio = y_length / z_length
                y_grid_size = max(int((current_points * aspect_ratio) ** 0.5), 3)
                z_grid_size = max(int((current_points / aspect_ratio) ** 0.5), 3)

                while y_grid_size * z_grid_size < current_points:
                    if y_length >= z_length:
                        y_grid_size += 1
                    else:
                        z_grid_size += 1

                y_coords = torch.linspace(-bbox_xyz_scale[1], bbox_xyz_scale[1], y_grid_size)
                z_coords = torch.linspace(-bbox_xyz_scale[2], bbox_xyz_scale[2], z_grid_size)
                y_grid, z_grid = torch.meshgrid(y_coords, z_coords, indexing='ij')
                x_coords = torch.rand(current_points) * (face['range'][1] - face['range'][0]) + face['range'][0]

                yz_indices = torch.randperm(y_grid.numel())[:current_points]
                y_points = y_grid.flatten()[yz_indices]
                z_points = z_grid.flatten()[yz_indices]

                min_len = min(len(x_coords), len(y_points), len(z_points))
                x_coords = x_coords[:min_len]
                y_points = y_points[:min_len]
                z_points = z_points[:min_len]

                face_points = torch.stack([x_coords, y_points, z_points], dim=-1)

            elif face['axis'] == 1: # XZ
                x_length = 2.0 * bbox_xyz_scale[0]
                z_length = 2.0 * bbox_xyz_scale[2]

                aspect_ratio = x_length / z_length
                x_grid_size = max(int((current_points * aspect_ratio) ** 0.5), 3)
                z_grid_size = max(int((current_points / aspect_ratio) ** 0.5), 3)

                while x_grid_size * z_grid_size < current_points:
                    if x_length >= z_length:
                        x_grid_size += 1
                    else:
                        z_grid_size += 1

                x_coords = torch.linspace(-bbox_xyz_scale[0], bbox_xyz_scale[0], x_grid_size)
                z_coords = torch.linspace(-bbox_xyz_scale[2], bbox_xyz_scale[2], z_grid_size)
                x_grid, z_grid = torch.meshgrid(x_coords, z_coords, indexing='ij')
                y_coords = torch.rand(current_points) * (face['range'][1] - face['range'][0]) + face['range'][0]

                xz_indices = torch.randperm(x_grid.numel())[:current_points]
                x_points = x_grid.flatten()[xz_indices]
                z_points = z_grid.flatten()[xz_indices]

                min_len = min(len(x_points), len(y_coords), len(z_points))
                x_points = x_points[:min_len]
                y_coords = y_coords[:min_len]
                z_points = z_points[:min_len]

                face_points = torch.stack([x_points, y_coords, z_points], dim=-1)

            else: # XY
                x_length = 2.0 * bbox_xyz_scale[0]
                y_length = 2.0 * bbox_xyz_scale[1]

                aspect_ratio = x_length / y_length
                x_grid_size = max(int((current_points * aspect_ratio) ** 0.5), 3)
                y_grid_size = max(int((current_points / aspect_ratio) ** 0.5), 3)

                while x_grid_size * y_grid_size < current_points:
                    if x_length >= y_length:
                        x_grid_size += 1
                    else:
                        y_grid_size += 1

                x_coords = torch.linspace(-bbox_xyz_scale[0], bbox_xyz_scale[0], x_grid_size)
                y_coords = torch.linspace(-bbox_xyz_scale[1], bbox_xyz_scale[1], y_grid_size)
                x_grid, y_grid = torch.meshgrid(x_coords, y_coords, indexing='ij')
                z_coords = torch.rand(current_points) * (face['range'][1] - face['range'][0]) + face['range'][0]

                xy_indices = torch.randperm(x_grid.numel())[:current_points]
                x_points = x_grid.flatten()[xy_indices]
                y_points = y_grid.flatten()[xy_indices]

                min_len = min(len(x_points), len(y_points), len(z_coords))
                x_points = x_points[:min_len]
                y_points = y_points[:min_len]
                z_coords = z_coords[:min_len]

                face_points = torch.stack([x_points, y_points, z_coords], dim=-1)

            all_surface_points.append(face_points)

        pointcloud_xyz = torch.cat(all_surface_points, dim=0)

        if len(pointcloud_xyz) > adjusted_max_pts:
            sample_idx = torch.randperm(len(pointcloud_xyz))[:adjusted_max_pts]
            pointcloud_xyz = pointcloud_xyz[sample_idx]

        pointcloud_rgb = torch.rand_like(pointcloud_xyz)

        logger.info(f"[Vehicle] Generated {len(pointcloud_xyz)} surface points for object with size {obj_size}, "
                    f"type {model_type}, volume_factor {volume_factor:.2f}")

        return pointcloud_xyz, pointcloud_rgb

    def obtain_obj_light_status(self, use_obj_light):
        self.use_obj_light = use_obj_light
        return

    def get_obj_dir(self, ins_id: int) -> Optional[str]:
        valid_frames = torch.where(self.pixel_source.per_frame_instance_mask[:, ins_id])[0]
        if valid_frames.numel() == 0:
            return None

        left_count = 0
        right_count = 0
        for frame_idx_t in valid_frames:
            frame_idx = int(frame_idx_t.item())
            obj_to_world = self.pixel_source.instances_pose[frame_idx, ins_id]
            localpose = self.pixel_source.localpose

            ego_to_world = torch.from_numpy(
                np.array(localpose[self.pixel_source.timestamps[frame_idx]])
            ).float().to(obj_to_world.device)

            obj_center_world = obj_to_world[:3, 3]
            ego_center_world = ego_to_world[:3, 3]
            ego_to_obj_vec = obj_center_world - ego_center_world
            if torch.norm(ego_to_obj_vec) > 15.0:
                continue

            # Use object local +x axis as heading direction in world coordinates.
            obj_heading_world = obj_to_world[:3, 0]

            ego_to_obj_xy = ego_to_obj_vec[:2]
            obj_heading_xy = obj_heading_world[:2]
            cross_z = ego_to_obj_xy[0] * obj_heading_xy[1] - ego_to_obj_xy[1] * obj_heading_xy[0]
            if cross_z >= 0:
                left_count += 1
            else:
                right_count += 1
        total_count = left_count + right_count
        if total_count == 0:
            return None

        left_ratio = left_count / total_count
        right_ratio = right_count / total_count
        if left_ratio > 0.9:
            return "left"
        if right_ratio > 0.9:
            return "right"
        return None

    def get_init_objects(
        self,
        cur_node_type: Literal["RigidNodes", "RigidNodesLight", "DeformableNodes"],
        instance_max_pts: int = 20000,
        only_moving: bool = True,
        traj_length_thres: float = 0.5,
        exclude_smpl: bool = False,
        use_feedforawrd: bool = False
    ):
        """
        return:
            instances_dict: Dict[int, Dict[str, Tensor]]
                keys: instance_id
                values: Dict[str, Tensor]
                    keys: "pts", "colors", "num_pts", "flows"(Optional)
                    values: Tensor

        NOTE: pts are in object coordinate system
        """
        assert only_moving is False, "Only moving objects are not supported for Xpeng dataset"
        assert exclude_smpl is False, "SMPL is not supported for Xpeng dataset"

        static_ids = extract_static_ids(os.path.join(self.data_path, "static_obs_ids.json"))
        instance_dict = {}
        object_pts, object_colors = self.lidar_source.object_points()
        for ins_id in range(self.instance_num):
            if self.pixel_source.object_init_check(cur_node_type, self.pixel_source.instances_model_types[ins_id]):
                continue
            gid = self.pixel_source.instances_global_id[ins_id].item()
            if gid in static_ids:
                print("Skip init obj: ", gid)
                continue
            
            obj_type = self.pixel_source.instances_types[0, ins_id]
            if self.use_obj_light:
                if obj_type in [ObjectType.Pedestrian, ObjectType.Cyclist, ObjectType.Motorcycle]:
                    # do not use light for non-rigid obj
                    if cur_node_type == "RigidNodesLight":
                        continue
                else:
                    if cur_node_type == "RigidNodes":
                        # if close, use light mode
                        if self.pixel_source.obj_dist_level_dict.get(ins_id, DistLevel.Close) == DistLevel.Close:
                            continue
                    if cur_node_type == "RigidNodesLight":
                        # if not close, do not use light
                        if self.pixel_source.obj_dist_level_dict.get(ins_id, DistLevel.Close) != DistLevel.Close:
                            continue

            instance_dict[ins_id] = {}
            instance_dict[ins_id]["node_type"] = cur_node_type
            if gid in object_pts:
                pts, colors = object_pts[gid], object_colors[gid]
                min_points_threshold = 2000
                obj_size = self.pixel_source.instances_size[ins_id].cpu().numpy()
                max_length = max(obj_size)

                if pts.shape[0] < min_points_threshold or max_length > 5.0:
                    pts, colors = self._load_random_obj_points(
                        obj_size,
                        model_type=self.pixel_source.instances_model_types[ins_id],
                        ins_type=obj_type,
                        base_max_pts=instance_max_pts,
                        obj_dist_level_dict=self.pixel_source.obj_dist_level_dict.get(ins_id, DistLevel.Close),
                    )
            else:
                sam3d_ply_path = os.path.join(self.data_path, "input_ply", f"{gid}.ply")
                if use_feedforawrd and os.path.exists(sam3d_ply_path):
                    logger.info(f"use sam3d init, ins_id: {ins_id}, gid: {gid}")
                    pts, opacities, scales, rots, colors = self.obtain_sam3d_gs(sam3d_ply_path, self.pixel_source.instances_size[ins_id].cpu().numpy())

                    save_sam3d_init = False
                    if save_sam3d_init:
                        save_vis_gaussians(pts, opacities, scales, rots, colors, f"sam3d_{gid}.ply")
                else:
                    pts, colors = self._load_random_obj_points(
                        self.pixel_source.instances_size[ins_id].cpu().numpy(),
                        model_type=self.pixel_source.instances_model_types[ins_id],
                        ins_type=obj_type,
                        base_max_pts=instance_max_pts,
                        obj_dist_level_dict=self.pixel_source.obj_dist_level_dict.get(ins_id, DistLevel.Close),
                    )

                    distances, _ = k_nearest_sklearn(pts, 3)
                    distances = torch.from_numpy(distances)
                    avg_dist = distances.mean(dim=-1, keepdim=True)
                    avg_dist = avg_dist.clamp(0.002, 100)
                    scales = torch.log(avg_dist.repeat(1, 3))
                    rots = random_quat_tensor(pts.shape[0])
                    opacities = torch.logit(0.1 * torch.ones(pts.shape[0], 1))

            instance_dict[ins_id]["dir"] = None
            if cur_node_type == "RigidNodesLight":
                instance_dict[ins_id]["dir"] = self.get_obj_dir(ins_id)
                print(f"gid: {gid}, direction: {instance_dict[ins_id]['dir']}")

            instance_dict[ins_id]["pts"] = pts.clone().detach()
            instance_dict[ins_id]["colors"] = colors.clone().detach()
            instance_dict[ins_id]["opacities"] = opacities.clone().detach()
            instance_dict[ins_id]["scales"] = scales.clone().detach()
            instance_dict[ins_id]["rots"] = rots.clone().detach()
            instance_dict[ins_id]["num_pts"] = instance_dict[ins_id]["pts"].shape[0]

            instance_dict[ins_id]["poses"] = self.pixel_source.instances_pose[:, ins_id]
            instance_dict[ins_id]["size"] = self.pixel_source.instances_size[ins_id]
            instance_dict[ins_id]["frame_info"] = self.pixel_source.per_frame_instance_mask[:, ins_id]
            instance_dict[ins_id]["moving"] = self.pixel_source.instances_moving[:, ins_id]

        if DEBUG_PCD:
            output_dir = os.path.join(DEBUG_OUTPUT_DIR, "aggregated_instance_lidar_pts")
            os.makedirs(output_dir, exist_ok=True)
            for ins_id in instance_dict:
                export_points_to_ply(
                    instance_dict[ins_id]["pts"],
                    instance_dict[ins_id]["colors"],
                    save_path=os.path.join(output_dir, f"ID={ins_id}.ply"),
                )

        torch.save(instance_dict, os.path.join(self.model_path, cur_node_type + "_instance_dict.pt"))
        return instance_dict

    def obtain_sam3d_gs(self, ply_path, bounding_box):
        plydata = PlyData.read(ply_path)
        # xyz
        xyz = np.stack(
            (
                np.asarray(plydata.elements[0]["x"]),
                np.asarray(plydata.elements[0]["y"]),
                np.asarray(plydata.elements[0]["z"]),
            ),
            axis=1,
        )
        xyz, scale_factors, fixed_rot = rescale_points(xyz, bounding_box, self.device)
        xyz = torch.from_numpy(xyz)

        # opacity
        opacities = np.asarray(plydata.elements[0]["opacity"])[..., np.newaxis]
        opacities = torch.tensor(opacities, dtype=torch.float, device=self.device)

        # rot
        rot_names = [
            p.name for p in plydata.elements[0].properties if p.name.startswith("rot")
        ]
        rot_names = sorted(rot_names, key=lambda x: int(x.split("_")[-1]))
        rots = np.zeros((xyz.shape[0], len(rot_names)))
        for idx, attr_name in enumerate(rot_names):
            rots[:, idx] = np.asarray(plydata.elements[0][attr_name])
        rots = torch.tensor(rots, dtype=torch.float, device=self.device) # wxyz

        rots_normalized = torch.nn.functional.normalize(rots, dim=-1)
        R = quaternion_to_matrix(rots_normalized)  # gs_2_old_obj
        fixed_rot_batch = fixed_rot.unsqueeze(0).expand(R.shape[0], -1, -1) # old_obj_2_new_obj
        R = torch.bmm(fixed_rot_batch, R)  # gs_2_new_obj
        rots = matrix_to_quaternion(R)

        # scale
        scale_names = [
            p.name
            for p in plydata.elements[0].properties
            if p.name.startswith("scale_")
        ]
        scale_names = sorted(scale_names, key=lambda x: int(x.split("_")[-1]))
        scales = np.zeros((xyz.shape[0], len(scale_names)))
        for idx, attr_name in enumerate(scale_names):
            scales[:, idx] = np.asarray(plydata.elements[0][attr_name])
        scales = torch.tensor(scales, dtype=torch.float, device=self.device)

        if isinstance(scale_factors, (int, float)):
            scale_factors = torch.full((3,), scale_factors, device=self.device, dtype=torch.float)
        else:
            scale_factors = torch.tensor(scale_factors, device=self.device, dtype=torch.float)
        scale_matrix = torch.diag(scale_factors)
        scale_matrix_batch = scale_matrix.unsqueeze(0).expand(rots.shape[0], -1, -1)
        local_proj = torch.bmm(R.transpose(1, 2), torch.bmm(scale_matrix_batch, R))
        scale_factors_local = torch.diagonal(local_proj, dim1=1, dim2=2)
        scales += torch.log(scale_factors_local.clamp(min=1e-6))

        # rgb
        features_dc = np.zeros((xyz.shape[0], 3))
        features_dc[:, 0] = np.asarray(plydata.elements[0]["f_dc_0"])
        features_dc[:, 1] = np.asarray(plydata.elements[0]["f_dc_1"])
        features_dc[:, 2] = np.asarray(plydata.elements[0]["f_dc_2"])
        features_dc = (
            torch.tensor(features_dc, dtype=torch.float, device=self.device)
            .contiguous()
        )
        C0 = 0.28209479177387814
        rgb = features_dc * C0 + 0.5

        return xyz, opacities, scales, rots, rgb


    def get_init_smpl_objects(self, only_moving: bool = False, traj_length_thres: float = 0.5):
        instance_dict = {}
        """
        instance_dict = {
            ins_id: {
                "node_type": str,
                "pts": Tensor, [frame_num, num_pts, 3]
                "colors": Tensor, [frame_num, num_pts, 3]
                "quats": Tensor, [frame_num, 4]
                "trans": Tensor, [frame_num, 3]
                "size": Tensor, [3]
                "frame_info": Tensor, [frame_num]
        }
        """

        for ins_id in range(self.instance_num):
            true_id = self.pixel_source.instances_true_id[ins_id].item()
            if true_id in self.pixel_source.smpl_human_all.keys():
                if self.pixel_source.smpl_human_all[true_id]["frame_valid"].sum() == 0:
                    continue
                smpl_trans = self.pixel_source.smpl_human_all[true_id]["smpl_trans"]
                frame_info = self.pixel_source.smpl_human_all[true_id]["frame_valid"]
                if only_moving and traj_length_thres > 0:
                    # compute the distance between two consecutive frames
                    traj_length = smpl_trans[frame_info][1:] - smpl_trans[frame_info][:-1]
                    traj_length = torch.norm(traj_length, dim=-1).sum()
                    if traj_length < traj_length_thres:
                        continue
                smpl_quats = self.pixel_source.smpl_human_all[true_id]["smpl_quats"]
                smpl_betas = self.pixel_source.smpl_human_all[true_id]["smpl_betas"]
                size = self.pixel_source.instances_size[ins_id]
                # NOTE: set the first frame's betas as the betas of the instance
                first_frame_betas = smpl_betas[frame_info][0]

                collected_lidar_pts = []
                collected_lidar_colors = []
                for fi in range(self.frame_num):
                    # lidar_dict = self.lidar_source.get_lidar_rays(fi)
                    # lidar_pts = lidar_dict["lidar_origins"] + lidar_dict["lidar_viewdirs"] * lidar_dict["lidar_ranges"]
                    instance_active = self.pixel_source.per_frame_instance_mask[fi, ins_id]
                    if not instance_active:
                        continue

                    valid_pts, valid_colors = self._load_random_obj_points(
                        size,
                        obj_type=self.pixel_source.instances_model_types[ins_id],
                        base_max_pts=20000
                    )

                    collected_lidar_pts.append(valid_pts)
                    collected_lidar_colors.append(valid_colors)

                instance_dict[ins_id] = {
                    "node_type": "SMPLNodes",
                    "smpl_quats": smpl_quats,  # [frame_num, 24, 4]
                    "smpl_trans": smpl_trans,  # [frame_num, 3]
                    "smpl_betas": first_frame_betas,  # [10]
                    "size": size,  # [3]
                    "frame_info": frame_info,  # [frame_num]
                    "pts": torch.cat(collected_lidar_pts, dim=0),
                    "colors": torch.cat(collected_lidar_colors, dim=0),
                }

        return instance_dict