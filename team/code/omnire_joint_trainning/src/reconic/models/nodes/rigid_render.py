import logging
from typing import Dict, List, Optional
import time
import os
import json

import glob
import torch
import torch.nn.functional as F
from torch.nn import Parameter
from gsplat.cuda._wrapper import spherical_harmonics
from ..gaussians.vanilla_render import VanillaGaussians_render
from ..gaussians.basics import (
    dataclass_camera,
    interpolate_quats,
    quat_mult,
    quat_to_rotmat,
    num_sh_bases,
    RGB2SH
)
from ..fourier_utils import get_features_fourier
from scipy.spatial import KDTree
from ...utils.dynamic_asset_render_utils import load_instance_tensors_from_yaml, load_rigid_ply
logger = logging.getLogger()

import numpy as np
from scipy.spatial.transform import Rotation as R

def matrix_to_quaternion(matrix):
    device = matrix.device
    dtype = matrix.dtype
    m = matrix.detach().cpu().numpy()
    quat_scipy = R.from_matrix(m).as_quat()
    quat_p3d_style = np.concatenate([quat_scipy[:, -1:], quat_scipy[:, :3]], axis=1)
    return torch.from_numpy(quat_p3d_style).to(device=device, dtype=dtype)

class RigidNodes_render(VanillaGaussians_render):
    def __init__(self, **kwargs):
        print("rigid_render success")
        super().__init__(**kwargs)
        self.xys_grad_norm = None
        self.vis_counts = None
        self.max_2Dsize = None
        self.filter_mask = None
        self.filter_mask_by_point_ids = None

        self.history_world_means = dict()
        self.history_smoothed_means = dict()

        # Initialize Fourier features if enabled
        ctrl_cfg = kwargs.get('ctrl', {})
        self.use_fourier_features = ctrl_cfg.get("use_fourier_features", False)
        self.fourier_dim = ctrl_cfg.get("fourier_dim", 40)
        self.fourier_scale = ctrl_cfg.get("fourier_scale", 1.0)
        self.load_rigid_assets = ctrl_cfg.get("load_rigid_assets", False)
        self.is_only_retain_dynamic_assets = ctrl_cfg.get("only_retain_dynamic_assets", False)
        self.rigid_assets_base_path = ctrl_cfg.get("rigid_assets_base_path", "dynamic_assets_ply")
        self.cur_frame = 0
        self.timing = []
        self.instance_id_dict = {}

    def create_from_pcd(self, instance_pts_dict: Dict[str, torch.Tensor]) -> None:
        """
        instance_pts_dict: {
            id in dataset: {
                "class_name": str,
                "pts": torch.Tensor, (N, 3)
                "colors": torch.Tensor, (N, 3)
                "poses": torch.Tensor, (num_frame, 4, 4)
                "size": torch.Tensor, (3, )
                "frame_info": torch.Tensor, (num_frame)
                "num_pts": int,
                "moving": bool,
            },
        }
        """
        # collect all instances
        init_means = []
        init_colors = []
        init_opacities = []
        init_scales = []
        init_rots = []

        instances_pose = []
        instances_size = []
        instances_fv = []
        point_ids = []
        moving_status = []
        self.kdtree_instance_id = {}
        self.kdtree_points_instance_id = {}
        self.ins_id_with_curr_id = {}
        self.obj_dir_dict = {}

        for id_in_model, (id_in_dataset, v) in enumerate(instance_pts_dict.items()):
            init_means.append(v["pts"])
            init_colors.append(v["colors"])
            init_opacities.append(v["opacities"])
            init_scales.append(v["scales"])
            init_rots.append(v["rots"])

            instances_pose.append(v["poses"].unsqueeze(1))
            instances_size.append(v["size"])
            instances_fv.append(v["frame_info"].unsqueeze(1))
            moving_status.append(v["moving"].unsqueeze(1))
            point_ids.append(torch.full((v["num_pts"], 1), id_in_model, dtype=torch.long))

            self.kdtree_points_instance_id[id_in_model] = v["pts"]
            self.kdtree_instance_id[id_in_model] = KDTree(v["pts"])
            self.obj_dir_dict[id_in_model] = v["dir"] if "dir" in v else None
            self.ins_id_with_curr_id[id_in_dataset] = id_in_model

        print(f"======================[create_from_pcd] obj_dir_dict: {self.obj_dir_dict}======================")

        init_opacities = torch.cat(init_opacities, dim=0).to(self.device)  # (N, 3)
        self._opacities = Parameter(init_opacities)

        init_means = torch.cat(init_means, dim=0).to(self.device)  # (N, 3)
        instances_pose = torch.cat(instances_pose, dim=1).to(self.device)  # (num_frame, num_instances, 4, 4)
        self.instances_size = torch.stack(instances_size).to(self.device)  # (num_instances, 3)
        self.instances_fv = torch.cat(instances_fv, dim=1).to(self.device)  # (num_frame, num_instances)

        self.point_ids = torch.cat(point_ids, dim=0).to(self.device)
        instances_quats = self.get_instances_quats(instances_pose)
        instances_trans = instances_pose[..., :3, 3]
        self.instances_moving = torch.cat(moving_status, dim=1).to(self.device)

        self._means = Parameter(init_means)
        self._scales = Parameter(torch.cat(init_scales, dim=0).to(self.device))  # (N, 3)
        self._quats = Parameter(torch.cat(init_rots, dim=0).to(self.device))
        dim_sh = num_sh_bases(self.sh_degree)

        self.instances_quats = Parameter(self.quat_act(instances_quats))  # (num_frame, num_instances, 4)
        self.instances_trans = Parameter(instances_trans)  # (num_frame, num_instances, 3)

        init_colors = torch.cat(init_colors, dim=0).to(self.device)  # (N, 3)
        fused_color = RGB2SH(init_colors)  # float range [0, 1]
        if self.use_fourier_features:
            # Initialize features with Fourier dimensions for temporal modeling
            # Shape: [N, fourier_dim, 3]
            features_dc = torch.zeros((fused_color.shape[0], self.fourier_dim, 3)).float().to(self.device)
            features_dc[:, 0, :3] = fused_color  # Initialize first dimension with color
            # Randomly initialize other Fourier dimensions
            if self.fourier_dim > 1:
                features_dc[:, 1:, :] = torch.randn_like(features_dc[:, 1:, :]) * 0.01

            self._features_dc = Parameter(features_dc)
            # Initialize SH features for higher degrees
            sh_dim = max(0, dim_sh - 1)
            self._features_rest = Parameter(torch.zeros((fused_color.shape[0], sh_dim, 3)).float().to(self.device))
        else:
            # Standard initialization
            shs = torch.zeros((fused_color.shape[0], dim_sh, 3)).float().to(self.device)
            if self.sh_degree > 0:
                shs[:, 0, :3] = fused_color
                shs[:, 1:, 3:] = 0.0
            else:
                shs[:, 0, :3] = torch.logit(init_colors, eps=1e-10)
            self._features_dc = Parameter(shs[:, 0, :])
            self._features_rest = Parameter(shs[:, 1:, :])

        if self.appearance_embedding_cfg:
            self._appearance_features = Parameter(
                torch.zeros((self._means.shape[0], self.appearance_feature_dims)).float().to(self.device)
            )
        self.cull_points_use_box()
        self.save_id_corr()

    @staticmethod
    def _slerp_quat(q0: torch.Tensor, q1: torch.Tensor, t: torch.Tensor) -> torch.Tensor:
        """
        Spherical linear interpolation for quaternions in (w, x, y, z) format.
        q0, q1: (..., 4)
        t: (...,) or (..., 1)
        Returns: (..., 4)
        """
        if t.ndim == q0.ndim:
            t_ = t
        else:
            t_ = t.unsqueeze(-1)

        q0 = F.normalize(q0, dim=-1)
        q1 = F.normalize(q1, dim=-1)

        dot = (q0 * q1).sum(dim=-1, keepdim=True)
        # Take the shorter path
        q1 = torch.where(dot < 0.0, -q1, q1)
        dot = dot.abs().clamp(-1.0, 1.0)

        # If very close, fall back to lerp to avoid numerical issues
        close = dot > 0.9995
        lerp = F.normalize(q0 + (q1 - q0) * t_, dim=-1)

        theta_0 = torch.acos(dot)  # (..., 1)
        sin_theta_0 = torch.sin(theta_0).clamp_min(1.0e-8)
        theta_t = theta_0 * t_
        s0 = torch.sin(theta_0 - theta_t) / sin_theta_0
        s1 = torch.sin(theta_t) / sin_theta_0
        slerp = s0 * q0 + s1 * q1
        slerp = F.normalize(slerp, dim=-1)

        return torch.where(close, lerp, slerp)

    @staticmethod
    def _quat_conjugate(q: torch.Tensor) -> torch.Tensor:
        out = q.clone()
        out[..., 1:] = -out[..., 1:]
        return out

    @torch.no_grad()
    def interpolate_missing_instance_poses_for_render(
        self,
        max_gap: int | None = None,
        fill_instances_fv: bool = True,
        ego_positions: Optional[torch.Tensor] = None,
        max_ego_distance: float | None = None,
    ) -> None:
        """
        Render-only utility:
        Some instances have discontinuous trajectories (instances_fv == False in middle frames).
        This fills missing poses between two valid endpoints by interpolation:
        - translation: linear
        - rotation: quaternion slerp

        Training should NOT rely on this. Call it only in simulator/render code path.
        """
        if not hasattr(self, "instances_fv") or not hasattr(self, "instances_trans") or not hasattr(self, "instances_quats"):
            return

        max_gap = 100
        fv = self.instances_fv.bool()
        num_frames, num_instances = fv.shape
        if num_frames <= 2 or num_instances == 0:
            return

        filled_cnt = 0
        for ins_id in range(num_instances):
            valid_idx = torch.where(fv[:, ins_id])[0]
            if valid_idx.numel() == 0:
                continue

            # Only interpolate/extrapolate near-ego objects if threshold is enabled.
            # If ego_positions is not provided, this filter is skipped.
            if (
                max_ego_distance is not None
                and ego_positions is not None
                and ego_positions.shape[0] >= num_frames
            ):
                valid_obj_trans = self.instances_trans[valid_idx, ins_id]
                valid_ego_trans = ego_positions[valid_idx]
                min_dist = torch.norm(valid_obj_trans - valid_ego_trans, dim=-1).min().item()
                if min_dist > max_ego_distance:
                    continue

            # Restrict to dynamic instances when motion flags are available.
            if hasattr(self, "instances_moving"):
                moving_mask = self.instances_moving[:, ins_id].bool()
                if not torch.any(moving_mask[valid_idx]):
                    continue
            for a, b in zip(valid_idx[:-1], valid_idx[1:]):
                gap = int((b - a).item())
                if gap <= 1:
                    continue
                if max_gap is not None and gap - 1 > max_gap:
                    continue

                # frames to fill: (a+1 ... b-1)
                ts = torch.arange(a + 1, b, device=self.instances_trans.device)
                alpha = (ts - a).float() / float(gap)  # (gap-1,)

                t0 = self.instances_trans[a, ins_id]
                t1 = self.instances_trans[b, ins_id]
                trans = t0[None, :] + (t1 - t0)[None, :] * alpha[:, None]

                q0 = self.instances_quats[a, ins_id]
                q1 = self.instances_quats[b, ins_id]
                quats = self._slerp_quat(q0[None, :].expand(ts.shape[0], -1), q1[None, :].expand(ts.shape[0], -1), alpha)

                self.instances_trans.data[ts, ins_id] = trans
                self.instances_quats.data[ts, ins_id] = quats
                if fill_instances_fv:
                    self.instances_fv.data[ts, ins_id] = True
                filled_cnt += ts.numel()

        if filled_cnt > 0:
            print(
                f"[INFO][RenderPoseInterp] Filled {filled_cnt} gaps with ins id {ins_id}"
            )

    def save_id_corr(self):
        corr_id_file = os.path.join(self.model_path, f"{self.class_name}_corr_id.json")
        with open(corr_id_file, "w", encoding="utf-8") as f:
            json.dump(self.ins_id_with_curr_id, f, ensure_ascii=False, indent=4)

    def cull_points_use_box(self):
        culls = self.get_out_of_bound_mask()
        self._means = Parameter(self._means[~culls].detach())
        self._scales = Parameter(self._scales[~culls].detach())
        self._quats = Parameter(self._quats[~culls].detach())
        self._features_dc = Parameter(self._features_dc[~culls].detach())
        self._features_rest = Parameter(self._features_rest[~culls].detach())
        self._opacities = Parameter(self._opacities[~culls].detach())
        self.point_ids = self.point_ids[~culls]
        if self.appearance_embedding_cfg:
            self._appearance_features = Parameter(self._appearance_features[~culls].detach())
        # print(f"     Init Cull: {n_bef - self.num_points}")
        return culls

    def get_instances_quats(self, instances_pose: torch.Tensor) -> torch.Tensor:
        """
        Convert the pose to quaternion for all frames and instances
        """
        num_frames = instances_pose.shape[0]
        num_instances = instances_pose.shape[1]
        quats = torch.zeros(num_frames * num_instances, 4, device=self.device)

        poses = instances_pose[..., :3, :3].view(-1, 3, 3)
        valid_mask = self.instances_fv.view(-1)
        _quats = matrix_to_quaternion(poses[valid_mask])
        _quats = self.quat_act(_quats)

        quats[valid_mask] = _quats
        quats[~valid_mask, 0] = 1.0
        return quats.reshape(num_frames, num_instances, 4)

    def get_out_of_bound_mask(self):
        """
        This function checks if the gaussians are out of instance boxes
        """
        # get the instance boxes
        per_pts_size = self.instances_size[self.point_ids[..., 0]]
        instance_pts = self._means

        mask = (instance_pts.abs() > per_pts_size / 2).any(dim=-1)
        return mask

    @property
    def num_instances(self):
        return self.instances_fv.shape[1]

    @property
    def num_frames(self):
        return self.instances_fv.shape[0]

    def get_pts_valid_mask(self):
        """
        get the mask for valid points
        """
        return self.instances_fv[self.cur_frame][self.point_ids[..., 0]]

    def set_cur_frame(self, frame_id: int):
        self.cur_frame = frame_id

    def set_class_name(self, class_name):
        self.class_name = class_name

    def transform_means(self, means: torch.Tensor, fraction_from_cur_frame: float, valid_mask=None) -> torch.Tensor:
        """
        transform the means of instances to world space
        according to the pose at the current frame
        """
        assert means.shape[0] == self.point_ids.shape[0], "its a bug here, we need to pass the mask for points_ids"
        
        # 获取当前帧的四元数
        if fraction_from_cur_frame != 0.0 and (self.cur_frame + 1 < self.num_frames):
            _quats_next_frame = self.instances_quats[self.cur_frame + 1]
            _quats_cur_frame = self.instances_quats[self.cur_frame]
            interpolated_quats = interpolate_quats(_quats_cur_frame, _quats_next_frame, fraction_from_cur_frame)

            inter_valid_mask = self.instances_fv[self.cur_frame] & self.instances_fv[self.cur_frame + 1]
            quats_cur_frame = torch.where(inter_valid_mask[:, None], interpolated_quats, _quats_cur_frame)
        else:
            quats_cur_frame = self.instances_quats[self.cur_frame]  # (num_instances, 4)
        
        # 应用四元数激活函数
        quats_cur_frame_act = self.quat_act(quats_cur_frame)
        
        # 识别单位四元数 [1, 0, 0, 0]
        identity_quat = torch.tensor([1.0, 0.0, 0.0, 0.0], 
                                    device=quats_cur_frame_act.device, 
                                    dtype=quats_cur_frame_act.dtype)

        def torch_allclose(a, b, rtol=1e-5, atol=1e-5):
            """torch版本的allclose，用于比较两个张量是否接近"""
            return torch.all(torch.abs(a - b) <= atol + rtol * torch.abs(b))
        # 创建掩码：非单位四元数
        non_identity_mask = ~torch_allclose(quats_cur_frame_act, identity_quat, rtol=1e-5, atol=1e-5)
        
        # 初始化旋转矩阵为单位矩阵
        num_instances = quats_cur_frame_act.shape[0]
        rot_cur_frame = torch.eye(3, device=quats_cur_frame_act.device, 
                                dtype=quats_cur_frame_act.dtype).unsqueeze(0).repeat(num_instances, 1, 1)
        
        # 只对非单位四元数计算旋转矩阵
        if non_identity_mask.any():
            non_identity_quats = quats_cur_frame_act[non_identity_mask]
            non_identity_rot = quat_to_rotmat(non_identity_quats)
            rot_cur_frame[non_identity_mask] = non_identity_rot
        
        # 平移部分（按实例）
        if fraction_from_cur_frame != 0.0 and (self.cur_frame + 1 < self.num_frames):
            _next_ins_trans = self.instances_trans[self.cur_frame + 1]
            _cur_ins_trans = self.instances_trans[self.cur_frame]
            interpolated_trans = _cur_ins_trans + (_next_ins_trans - _cur_ins_trans) * fraction_from_cur_frame

            inter_valid_mask = self.instances_fv[self.cur_frame - 1] & self.instances_fv[self.cur_frame + 1]
            trans_cur_frame = torch.where(inter_valid_mask[:, None], interpolated_trans, _cur_ins_trans)
        else:
            trans_cur_frame = self.instances_trans[self.cur_frame]  # (num_instances, 3)

        # 根据 valid_mask 决定对哪些点做变换
        point_ids_flat = self.point_ids[..., 0]  # (num_points,)

        if valid_mask is not None:
            # 如果没有有效点，直接返回原 means（避免不必要计算）
            if not valid_mask.any():
                return means

            # 只取有效点对应的实例 id
            valid_point_ids = point_ids_flat[valid_mask]              # (num_valid_points,)
            rot_per_valid_pts = rot_cur_frame[valid_point_ids]        # (num_valid_points, 3, 3)
            trans_per_valid_pts = trans_cur_frame[valid_point_ids]    # (num_valid_points, 3)

            # 只对有效点做 bmm
            means_valid = means[valid_mask]                           # (num_valid_points, 3)
            means_valid_world = torch.bmm(
                rot_per_valid_pts, means_valid.unsqueeze(-1)
            ).squeeze(-1) + trans_per_valid_pts

            # 将结果 scatter 回全量 tensor，保证输出 shape 不变
            means_world = means.clone()
            means_world[valid_mask] = means_valid_world
        else:
            # 没有提供 valid_mask，退化为对所有点计算（原逻辑）
            rot_per_pts = rot_cur_frame[point_ids_flat]               # (num_points, 3, 3)
            trans_per_pts = trans_cur_frame[point_ids_flat]           # (num_points, 3)
            means_world = torch.bmm(rot_per_pts, means.unsqueeze(-1)).squeeze(-1) + trans_per_pts

        # 可选的平滑
        if self.ctrl_cfg.get("use_world_means_smooth", False):
            return self.smooth_means_z_value_ema(means_world, self.cur_frame, fraction_from_cur_frame)
        else:
            return means_world

    def transform_quats(self, quats: torch.Tensor, fraction_from_cur_frame: float, valid_mask=None) -> torch.Tensor:
        """
        transform the quats of instances to world space
        according to the pose at the current frame
        """
        assert quats.shape[0] == self.point_ids.shape[0], "its a bug here, we need to pass the mask for points_ids"
        
        # 获取全局四元数
        if fraction_from_cur_frame != 0.0 and (self.cur_frame + 1 < self.num_frames):
            _quats_next_frame = self.instances_quats[self.cur_frame + 1]
            _quats_cur_frame = self.instances_quats[self.cur_frame]
            global_quats_cur_frame = interpolate_quats(_quats_cur_frame, _quats_next_frame, fraction_from_cur_frame)
        else:
            global_quats_cur_frame = self.instances_quats[self.cur_frame]

        point_ids_flat = self.point_ids[..., 0]

        # 局部四元数激活（按点）
        _quats_act = self.quat_act(quats)
        
        # 检测单位四元数 [1, 0, 0, 0]
        def is_identity_quat(quats, tol=1e-6):
            """检测单位四元数"""
            w_near_1 = torch.abs(quats[:, 0] - 1.0) < tol
            x_near_0 = torch.abs(quats[:, 1]) < tol
            y_near_0 = torch.abs(quats[:, 2]) < tol  
            z_near_0 = torch.abs(quats[:, 3]) < tol
            return w_near_1 & x_near_0 & y_near_0 & z_near_0
        
        # 初始化结果为输入的quats（相当于单位四元数乘以任何四元数等于该四元数本身）
        result_quats = _quats_act.clone()

        if valid_mask is not None:
            # 如果没有有效点，直接返回原结果，避免不必要计算
            if not valid_mask.any():
                return result_quats

            # 仅为有效点取对应的全局四元数并激活
            valid_point_ids = point_ids_flat[valid_mask]  # (num_valid_points,)
            global_quats_per_valid_pts = global_quats_cur_frame[valid_point_ids]
            global_quats_valid_act = self.quat_act(global_quats_per_valid_pts)

            # 仅在有效点上判断是否为单位四元数
            identity_mask_valid = is_identity_quat(global_quats_valid_act)
            non_identity_valid = ~identity_mask_valid

            if non_identity_valid.any():
                # 对有效且非单位四元数的点做乘法
                non_identity_global = global_quats_valid_act[non_identity_valid]

                # 将 valid_mask 中的局部索引映射回全局点索引
                valid_indices = valid_mask.nonzero(as_tuple=True)[0]          # (num_valid_points,)
                non_identity_indices = valid_indices[non_identity_valid]      # (num_non_identity_valid_points,)
                non_identity_local = _quats_act[non_identity_indices]

                multiplied_quats = quat_mult(non_identity_global, non_identity_local)

                # 回写到结果中
                result_quats[non_identity_indices] = multiplied_quats
        else:
            # 没有 valid_mask，退化为对所有点计算（原逻辑）
            global_quats_per_pts = global_quats_cur_frame[point_ids_flat]
            global_quats_per_pts_act = self.quat_act(global_quats_per_pts)

            identity_mask = is_identity_quat(global_quats_per_pts_act)
            non_identity_mask = ~identity_mask

            if non_identity_mask.any():
                non_identity_global = global_quats_per_pts_act[non_identity_mask]
                non_identity_local = _quats_act[non_identity_mask]
                multiplied_quats = quat_mult(non_identity_global, non_identity_local)
                result_quats[non_identity_mask] = multiplied_quats

        return result_quats

    def get_gaussians(self, cam: dataclass_camera) -> Dict[str, torch.Tensor]:
        """
        - 先在全局点上计算一次 world_means / world_quats（仅对 valid_mask=True 的点做重计算）；
        - 再根据 valid_mask 与 filter_mask 组合成最终渲染用索引 idx；
        - 后续颜色、SH/Fourier、opacity/scale/quat 全部只在压缩后的子集上计算。
        """
        # 基于当前帧可见性得到点级 valid_mask（[N]，bool）
        valid_mask = self.get_pts_valid_mask()  # (num_points,)
        if self.filter_mask_by_point_ids is not None:
            valid_mask = valid_mask & self.filter_mask_by_point_ids
            
        self.filter_mask = valid_mask

        # 如果没有任何有效点，直接返回空 dict，避免后续无意义计算
        if not valid_mask.any():
            device = self.device
            empty_means = torch.empty((0, 3), device=device, dtype=self._means.dtype)
            empty_opacities = torch.empty((0, 1), device=device, dtype=self._opacities.dtype)
            empty_rgbs = torch.empty((0, 3), device=device, dtype=self._features_dc.dtype)
            empty_scales = torch.empty((0, 3), device=device, dtype=self.get_scaling.dtype)
            empty_quats = torch.empty((0, 4), device=device, dtype=self._quats.dtype)
            return {
                "_means": empty_means,
                "_opacities": empty_opacities,
                "_rgbs": empty_rgbs,
                "_scales": empty_scales,
                "_quats": empty_quats,
            }

        # 先得到有效点的索引，并仅在这些点上做坐标/姿态变换
        valid_idx = valid_mask.nonzero(as_tuple=True)[0]  # [N_valid]
        fraction_from_cur_frame = cam.fraction_from_cur_timestep
        world_means_valid = self.transform_means_valid(self._means, fraction_from_cur_frame, valid_idx)
        world_quats_valid = self.transform_quats_valid(self._quats, fraction_from_cur_frame, valid_idx)

        # 组合 valid_mask 与外部 filter_mask，得到真正参与渲染的点（当前等价于全部 valid 点）
        filter_mask_valid = torch.ones(valid_idx.shape[0], dtype=torch.bool, device=valid_idx.device)  # [N_valid]

        # 如果 filter 全关掉了，则无需渲染
        if not filter_mask_valid.any():
            device = self.device
            empty_means = torch.empty((0, 3), device=device, dtype=self._means.dtype)
            empty_opacities = torch.empty((0, 1), device=device, dtype=self._opacities.dtype)
            empty_rgbs = torch.empty((0, 3), device=device, dtype=self._features_dc.dtype)
            empty_scales = torch.empty((0, 3), device=device, dtype=self.get_scaling.dtype)
            empty_quats = torch.empty((0, 4), device=device, dtype=self._quats.dtype)
            return {
                "_means": empty_means,
                "_opacities": empty_opacities,
                "_rgbs": empty_rgbs,
                "_scales": empty_scales,
                "_quats": empty_quats,
            }

        render_idx_in_valid = filter_mask_valid.nonzero(as_tuple=True)[0]  # [N_render]
        idx = valid_idx[render_idx_in_valid]                                # 原始索引空间中的渲染点

        # 在压缩后的 valid 子空间上进一步压缩到 render 子集
        world_means = world_means_valid[render_idx_in_valid]   # [N_render, 3]
        world_quats = world_quats_valid[render_idx_in_valid]   # [N_render, 4]

        # -------- 颜色与 SH / Fourier 仅在压缩子集上计算 --------
        if hasattr(self, "use_fourier_features") and self.use_fourier_features:
            # Apply Fourier transform to features for temporal modeling
            current_frame = getattr(cam, "timestep_id", getattr(self, "cur_frame", 0))
            start_frame = getattr(self.ctrl_cfg, "start_frame", 0)
            end_frame = getattr(self.ctrl_cfg, "end_frame", getattr(self, "num_frames", 1) - 1)
            fourier_dim = getattr(self, "fourier_dim", 40)
            fourier_scale = getattr(self, "fourier_scale", 1.0)

            # 只对渲染子集的特征做 Fourier
            if self._features_dc.dim() == 3:  # [N, fourier_dim, 3]
                fourier_features_dc = get_features_fourier(
                    self._features_dc[idx],
                    current_frame,
                    start_frame,
                    end_frame,
                    fourier_dim,
                    fourier_scale,
                )
                # 对 Fourier 特征，直接视为颜色 [N_render, 1, 3]
                colors = fourier_features_dc
            else:
                colors = torch.cat(
                    (self._features_dc[idx, None, :], self._features_rest[idx]), dim=1
                )
        else:
            # 标准颜色处理，仅在渲染子集上拼接
            colors = torch.cat(
                (self._features_dc[idx, None, :], self._features_rest[idx]), dim=1
            )

        if (
            self.sh_degree > 0
            and not (hasattr(self, "use_fourier_features") and self.use_fourier_features)  
            and not self.hil_mode
        ):
            # 使用 SH 时，仅用渲染子集的 world_means
            viewdirs = world_means.detach() - cam.camtoworlds.data[..., :3, 3]  # (N_render, 3)
            viewdirs = viewdirs / viewdirs.norm(dim=-1, keepdim=True)
            n = min(self.step // self.ctrl_cfg.sh_degree_interval, self.sh_degree)
            rgbs = spherical_harmonics(n, viewdirs, colors)
            rgbs = torch.clamp(rgbs + 0.5, 0.0, 1.0)
        else:
            # Fourier 特征或 SH_degree=0
            if colors.dim() == 3 and colors.shape[1] == 1:
                # Fourier features case: [N_render, 1, 3]
                rgbs = torch.sigmoid(colors[:, 0, :])
            else:
                rgbs = torch.sigmoid(colors[:, 0, :])

        # -------- opacity / scale / rotation 也仅在子集上计算/取值 --------
        full_opacity = self.get_opacity  # [N, 1]
        full_scales = self.get_scaling   # [N, 3] 或 [N, ?]

        opacities = full_opacity[idx]
        scales = full_scales[idx]
        activated_rotations = self.quat_act(world_quats)

        # -------- 外观 embedding（如有） --------
        if self.appearance_embedding_cfg and not self.hil_mode:
            rgb_offset = self.appearance_embedding_model(
                self._appearance_features,
                camera_id=torch.Tensor([cam.camera_id]).int().to(self.device),
                timestep_id=torch.Tensor([cam.timestep_id]).int().to(self.device),
                viewdirs=viewdirs,
                is_novel_view=torch.Tensor([cam.novel_view]).int().to(self.device),
                test_mode=not self.in_training_job,
            )[idx]
            activated_colors = torch.clamp(rgbs + rgb_offset, min=0.0, max=1.0)
        else:
            activated_colors = rgbs

        # -------- 组装渲染用的 gs_dict（完全基于压缩后的点集） --------
        gs_dict = dict(
            _means=world_means,
            _opacities=opacities,
            _rgbs=activated_colors,
            _scales=scales,
            _quats=activated_rotations,
        )

        # 若存在 rigid 资产信息，则在压缩索引空间下构造 mask
        if hasattr(self, "load_rigid_assets") and self.load_rigid_assets:
            all_rigid_instance_id = []
            for v in self.instance_id_dict.values():
                all_rigid_instance_id.append(v)

            if len(all_rigid_instance_id) == 0:
                rigid_mask_render = torch.zeros_like(idx, dtype=torch.bool, device=idx.device)
            else:
                point_ids_full = self.point_ids[..., 0]  # [N]
                point_ids_render = point_ids_full[idx]   # [N_render]
                rigid_ids_tensor = torch.tensor(
                    all_rigid_instance_id,
                    dtype=point_ids_render.dtype,
                    device=point_ids_render.device,
                )
                rigid_mask_render = torch.isin(point_ids_render, rigid_ids_tensor)

            gs_dict.update({"_rigid_instance_ids_mask": rigid_mask_render})
        return gs_dict

    def state_dict(self) -> Dict:
        state_dict = super().state_dict()
        state_dict.update(
            {
                "points_ids": self.point_ids,
                "instances_size": self.instances_size,
                "instances_fv": self.instances_fv,
            }
        )
        return state_dict

    def get_gaussians_multi_cam(self, cams: list[dataclass_camera]) -> Dict[str, torch.Tensor]:
        valid_mask = self.get_pts_valid_mask()  # (num_points,)
        if self.filter_mask_by_point_ids is not None:
            valid_mask = valid_mask & self.filter_mask_by_point_ids
            
        self.filter_mask = valid_mask
        cam_num = len(cams)
        multi_cam_rgbs = {}
        # 如果没有任何有效点，直接返回空 dict，避免后续无意义计算
        if not valid_mask.any():
            device = self.device
            empty_means = torch.empty((0, 3), device=device, dtype=self._means.dtype)
            empty_opacities = torch.empty((0, 1), device=device, dtype=self._opacities.dtype)
            empty_rgbs = torch.empty((cam_num, 0, 3), device=device, dtype=self._features_dc.dtype)
            empty_scales = torch.empty((0, 3), device=device, dtype=self.get_scaling.dtype)
            empty_quats = torch.empty((0, 4), device=device, dtype=self._quats.dtype)
            return {
                "_means": empty_means,
                "_opacities": empty_opacities,
                "_rgbs": empty_rgbs,
                "_scales": empty_scales,
                "_quats": empty_quats,
            }

        # 先得到有效点的索引，并仅在这些点上做坐标/姿态变换
        valid_idx = valid_mask.nonzero(as_tuple=True)[0]  # [N_valid]
        fraction_from_cur_frame = cams[0].fraction_from_cur_timestep
        world_means_valid = self.transform_means_valid(self._means, fraction_from_cur_frame, valid_idx)
        world_quats_valid = self.transform_quats_valid(self._quats, fraction_from_cur_frame, valid_idx)

        # 组合 valid_mask 与外部 filter_mask，得到真正参与渲染的点（当前等价于全部 valid 点）
        filter_mask_valid = torch.ones(valid_idx.shape[0], dtype=torch.bool, device=valid_idx.device)  # [N_valid]

        # 如果 filter 全关掉了，则无需渲染
        if not filter_mask_valid.any():
            device = self.device
            empty_means = torch.empty((0, 3), device=device, dtype=self._means.dtype)
            empty_opacities = torch.empty((0, 1), device=device, dtype=self._opacities.dtype)
            empty_rgbs = torch.empty((cam_num, 0, 3), device=device, dtype=self._features_dc.dtype)
            empty_scales = torch.empty((0, 3), device=device, dtype=self.get_scaling.dtype)
            empty_quats = torch.empty((0, 4), device=device, dtype=self._quats.dtype)
            return {
                "_means": empty_means,
                "_opacities": empty_opacities,
                "_rgbs": empty_rgbs,
                "_scales": empty_scales,
                "_quats": empty_quats,
            }

        render_idx_in_valid = filter_mask_valid.nonzero(as_tuple=True)[0]  # [N_render]
        idx = valid_idx[render_idx_in_valid]                                # 原始索引空间中的渲染点

        # 在压缩后的 valid 子空间上进一步压缩到 render 子集
        world_means = world_means_valid[render_idx_in_valid]   # [N_render, 3]
        world_quats = world_quats_valid[render_idx_in_valid]   # [N_render, 4]

        # -------- 颜色与 SH / Fourier 仅在压缩子集上计算 --------
        if hasattr(self, "use_fourier_features") and self.use_fourier_features:
            # Apply Fourier transform to features for temporal modeling
            current_frame = getattr(cams[0], "timestep_id", getattr(self, "cur_frame", 0))
            start_frame = getattr(self.ctrl_cfg, "start_frame", 0)
            end_frame = getattr(self.ctrl_cfg, "end_frame", getattr(self, "num_frames", 1) - 1)
            fourier_dim = getattr(self, "fourier_dim", 40)
            fourier_scale = getattr(self, "fourier_scale", 1.0)

            # 只对渲染子集的特征做 Fourier
            if self._features_dc.dim() == 3:  # [N, fourier_dim, 3]
                fourier_features_dc = get_features_fourier(
                    self._features_dc[idx],
                    current_frame,
                    start_frame,
                    end_frame,
                    fourier_dim,
                    fourier_scale,
                )
                # 对 Fourier 特征，直接视为颜色 [N_render, 1, 3]
                colors = fourier_features_dc
            else:
                colors = torch.cat(
                    (self._features_dc[idx, None, :], self._features_rest[idx]), dim=1
                )
        else:
            # 标准颜色处理，仅在渲染子集上拼接
            colors = torch.cat(
                (self._features_dc[idx, None, :], self._features_rest[idx]), dim=1
            )

        if (
            self.sh_degree > 0
            and not (hasattr(self, "use_fourier_features") and self.use_fourier_features)
        ):
            # 使用 SH 时，仅用渲染子集的 world_means
            for cam in cams:
                viewdirs = world_means.detach() - cam.camtoworlds.data[..., :3, 3]  # (N_render, 3)
                viewdirs = viewdirs / viewdirs.norm(dim=-1, keepdim=True)
                n = min(self.step // self.ctrl_cfg.sh_degree_interval, self.sh_degree)
                rgbs = spherical_harmonics(n, viewdirs, colors)
                rgbs = torch.clamp(rgbs + 0.5, 0.0, 1.0)
                multi_cam_rgbs[cam.camera_id] = rgbs
        else:
            # Fourier 特征或 SH_degree=0
            for cam in cams:
                if colors.dim() == 3 and colors.shape[1] == 1:
                    # Fourier features case: [N_render, 1, 3]
                    rgbs = torch.sigmoid(colors[:, 0, :])
                else:
                    rgbs = torch.sigmoid(colors[:, 0, :])
                multi_cam_rgbs[cam.camera_id] = rgbs

        # -------- opacity / scale / rotation 也仅在子集上计算/取值 --------
        full_opacity = self.get_opacity  # [N, 1]
        full_scales = self.get_scaling   # [N, 3] 或 [N, ?]

        opacities = full_opacity[idx]
        scales = full_scales[idx]
        activated_rotations = self.quat_act(world_quats)

        # -------- 外观 embedding（如有） --------
        if self.appearance_embedding_cfg:
            for cam in cams:
                rgb_offset = self.appearance_embedding_model(
                    self._appearance_features,
                    camera_id=torch.Tensor([cam.camera_id]).int().to(self.device),
                    timestep_id=torch.Tensor([cam.timestep_id]).int().to(self.device),
                    viewdirs=viewdirs,
                    is_novel_view=torch.Tensor([cam.novel_view]).int().to(self.device),
                    test_mode=not self.in_training_job,
                )[idx]
                multi_cam_rgbs[cam.camera_id] = activated_colors = torch.clamp(multi_cam_rgbs[cam.camera_id] + rgb_offset, min=0.0, max=1.0)
        
        activated_colors = torch.stack(list(multi_cam_rgbs.values()), dim=0)

        # -------- 组装渲染用的 gs_dict（完全基于压缩后的点集） --------
        gs_dict = dict(
            _means=world_means,
            _opacities=opacities,
            _rgbs=activated_colors,
            _scales=scales,
            _quats=activated_rotations,
        )

        # 若存在 rigid 资产信息，则在压缩索引空间下构造 mask
        if hasattr(self, "load_rigid_assets") and self.load_rigid_assets:
            all_rigid_instance_id = []
            for v in self.instance_id_dict.values():
                all_rigid_instance_id.append(v)

            if len(all_rigid_instance_id) == 0:
                rigid_mask_render = torch.zeros_like(idx, dtype=torch.bool, device=idx.device)
            else:
                point_ids_full = self.point_ids[..., 0]  # [N]
                point_ids_render = point_ids_full[idx]   # [N_render]
                rigid_ids_tensor = torch.tensor(
                    all_rigid_instance_id,
                    dtype=point_ids_render.dtype,
                    device=point_ids_render.device,
                )
                rigid_mask_render = torch.isin(point_ids_render, rigid_ids_tensor)

            gs_dict.update({"_rigid_instance_ids_mask": rigid_mask_render})
        return gs_dict

    def load_state_dict(self, state_dict: Dict, **kwargs) -> str:
        if self.load_rigid_assets and self.class_name == "RigidNodes":
            _, all_dynamic_assets_ids = self.load_rigid_assets_from_path(state_dict)
        self.point_ids = state_dict.pop("points_ids")
        self.instances_size = state_dict.pop("instances_size")
        self.instances_fv = state_dict.pop("instances_fv").bool()
        self.instances_trans = Parameter(torch.zeros(self.num_frames, self.num_instances, 3, device=self.device))
        self.instances_quats = Parameter(torch.zeros(self.num_frames, self.num_instances, 4, device=self.device))
        # Handle Fourier features compatibility
        if self.use_fourier_features and "_features_dc" in state_dict:
            checkpoint_features_shape = state_dict["_features_dc"].shape
            N = checkpoint_features_shape[0]

            # Create _features_dc with the correct Fourier dimensions
            self._features_dc = Parameter(torch.zeros((N, self.fourier_dim, 3), device=self.device))

            # create _features_rest for Fourier mode
            dim_sh = num_sh_bases(self.ctrl_cfg.sh_degree)
            sh_dim = max(0, dim_sh - 1)
            self._features_rest = Parameter(torch.zeros((N, sh_dim, 3), device=self.device))

            logger.warning(f"Loaded Fourier features checkpoint with shape {checkpoint_features_shape}")

        msg = super().load_state_dict(state_dict, **kwargs)

        if self.load_rigid_assets and self.class_name == "RigidNodes":
            all_instance_ids = set(self.point_ids[..., 0].cpu().numpy().tolist())
            rigid_instance_ids = all_instance_ids - all_dynamic_assets_ids
            self.set_filter_mask_by_point_ids(list(rigid_instance_ids))
        return msg

    def set_filter_mask_by_point_ids(self, filter_indices: List[int]):
        point_ids_flat = self.point_ids[..., 0]
        should_filter = torch.isin(point_ids_flat, torch.tensor(filter_indices, device=point_ids_flat.device))
        self.filter_mask_by_point_ids = (
            ~should_filter if self.filter_mask_by_point_ids is None
            else self.filter_mask_by_point_ids & ~should_filter
        )

    def modify_obj_by_json(self, scenario_modify_json, model_path, class_name):
        ### get ins_id_with_curr_id
        json_path = os.path.join(model_path, f"{class_name}_corr_id.json")
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                self.ins_id_with_curr_id = json.load(f)
            print(f"[INFO] load corr json: {json_path}")
        else:
            num_instances = self.instances_fv.shape[1]
            self.ins_id_with_curr_id = {}
            for i in range(num_instances):
                key = str(i)
                value = i
                self.ins_id_with_curr_id[key] = value

        ### mask out
        total_masked_out_obj = dict()
        mask_out_frames = scenario_modify_json["mask_obj_frames"]
        for idx, frame_info in enumerate(mask_out_frames):
            frame_idx = int(frame_info["index"])
            local_id = frame_info["local_id"]
            if str(local_id) not in self.ins_id_with_curr_id.keys():
                continue

            vis_info = frame_info["vis"]
            if local_id not in total_masked_out_obj:
                total_masked_out_obj[local_id] = dict()
            total_masked_out_obj[local_id][frame_idx] = vis_info

        for local_id, instance_vis_info in total_masked_out_obj.items():
            for frame_idx, vis_info in instance_vis_info.items():
                curr_id = self.ins_id_with_curr_id[str(local_id)]
                self.instances_fv[frame_idx, curr_id] = vis_info

        ### modify traj
        total_modified_traj = set()
        modify_traj_frames = scenario_modify_json["modified_frames"]
        self.instances_trans.requires_grad = False
        self.instances_quats.requires_grad = False
        for idx, frame_info in enumerate(modify_traj_frames):
            for obj_info in frame_info["objects"]:
                local_id = obj_info["local_id"]
                if str(local_id) not in self.ins_id_with_curr_id.keys():
                    continue

                translation = obj_info["translation"]
                rotation = obj_info["rotation"]
                curr_id = self.ins_id_with_curr_id[str(local_id)]
                for i, t in enumerate(translation):
                    self.instances_trans[idx, curr_id, i] = t
                for i, r in enumerate(rotation):
                    self.instances_quats[idx, curr_id, i] = r
                total_modified_traj.add(curr_id)

        print(f"[INFO] total masked out obj: {list(total_masked_out_obj.keys())}")
        print(f"[INFO] total modified traj: {total_modified_traj}")
    
    def transform_means_valid(
        self, means: torch.Tensor, fraction_from_cur_frame: float, valid_idx: torch.Tensor
    ) -> torch.Tensor:
        """
        只对 valid_idx 对应的点进行世界坐标变换，返回压缩后的 means_world_valid，shape [N_valid, 3]。
        不做 scatter 回全量 tensor，以避免不必要的 O(N) 内存写入。
        """
        assert means.shape[0] == self.point_ids.shape[0], "its a bug here, we need to pass the mask for points_ids"

        # 没有有效点，直接返回空 tensor
        if valid_idx.numel() == 0:
            return means.new_empty((0, means.shape[1]))

        # 获取当前帧的四元数（按实例）
        if fraction_from_cur_frame != 0.0 and (self.cur_frame + 1 < self.num_frames):
            _quats_next_frame = self.instances_quats[self.cur_frame + 1]
            _quats_cur_frame = self.instances_quats[self.cur_frame]
            interpolated_quats = interpolate_quats(_quats_cur_frame, _quats_next_frame, fraction_from_cur_frame)

            inter_valid_mask = self.instances_fv[self.cur_frame] & self.instances_fv[self.cur_frame + 1]
            quats_cur_frame = torch.where(inter_valid_mask[:, None], interpolated_quats, _quats_cur_frame)
        else:
            quats_cur_frame = self.instances_quats[self.cur_frame]  # (num_instances, 4)

        # 应用四元数激活函数
        quats_cur_frame_act = self.quat_act(quats_cur_frame)

        # 识别单位四元数 [1, 0, 0, 0]
        identity_quat = torch.tensor(
            [1.0, 0.0, 0.0, 0.0],
            device=quats_cur_frame_act.device,
            dtype=quats_cur_frame_act.dtype,
        )

        def torch_allclose_local(a, b, rtol=1e-5, atol=1e-5):
            """torch版本的allclose，用于比较两个张量是否接近"""
            return torch.all(torch.abs(a - b) <= atol + rtol * torch.abs(b))

        # 创建掩码：非单位四元数
        non_identity_mask = ~torch_allclose_local(quats_cur_frame_act, identity_quat, rtol=1e-5, atol=1e-5)

        # 初始化旋转矩阵为单位矩阵（按实例）
        num_instances = quats_cur_frame_act.shape[0]
        rot_cur_frame = torch.eye(
            3,
            device=quats_cur_frame_act.device,
            dtype=quats_cur_frame_act.dtype,
        ).unsqueeze(0).repeat(num_instances, 1, 1)

        # 只对非单位四元数计算旋转矩阵
        if non_identity_mask.any():
            non_identity_quats = quats_cur_frame_act[non_identity_mask]
            non_identity_rot = quat_to_rotmat(non_identity_quats)
            rot_cur_frame[non_identity_mask] = non_identity_rot

        # 平移部分（按实例）
        if fraction_from_cur_frame != 0.0 and (self.cur_frame + 1 < self.num_frames):
            _next_ins_trans = self.instances_trans[self.cur_frame + 1]
            _cur_ins_trans = self.instances_trans[self.cur_frame]
            interpolated_trans = _cur_ins_trans + (_next_ins_trans - _cur_ins_trans) * fraction_from_cur_frame

            inter_valid_mask = self.instances_fv[self.cur_frame - 1] & self.instances_fv[self.cur_frame + 1]
            trans_cur_frame = torch.where(inter_valid_mask[:, None], interpolated_trans, _cur_ins_trans)
        else:
            trans_cur_frame = self.instances_trans[self.cur_frame]  # (num_instances, 3)

        # 仅对 valid_idx 对应的点取实例 id，并做变换
        point_ids_flat = self.point_ids[..., 0]  # (num_points,)
        valid_point_ids = point_ids_flat[valid_idx]                 # (num_valid_points,)
        rot_per_valid_pts = rot_cur_frame[valid_point_ids]          # (num_valid_points, 3, 3)
        trans_per_valid_pts = trans_cur_frame[valid_point_ids]      # (num_valid_points, 3)

        means_valid = means[valid_idx]                              # (num_valid_points, 3)
        means_valid_world = torch.bmm(
            rot_per_valid_pts, means_valid.unsqueeze(-1)
        ).squeeze(-1) + trans_per_valid_pts

        # 注意：这里不做 world_means_smooth，以避免与全量缓存逻辑冲突
        return means_valid_world

    def transform_quats_valid(
        self, quats: torch.Tensor, fraction_from_cur_frame: float, valid_idx: torch.Tensor
    ) -> torch.Tensor:
        """
        只对 valid_idx 对应的点进行全局四元数变换，返回压缩后的 quats_world_valid，shape [N_valid, 4]。
        """
        assert quats.shape[0] == self.point_ids.shape[0], "its a bug here, we need to pass the mask for points_ids"

        if valid_idx.numel() == 0:
            return quats.new_empty((0, quats.shape[1]))

        # 获取全局四元数（按实例）
        if fraction_from_cur_frame != 0.0 and (self.cur_frame + 1 < self.num_frames):
            _quats_next_frame = self.instances_quats[self.cur_frame + 1]
            _quats_cur_frame = self.instances_quats[self.cur_frame]
            global_quats_cur_frame = interpolate_quats(_quats_cur_frame, _quats_next_frame, fraction_from_cur_frame)
        else:
            global_quats_cur_frame = self.instances_quats[self.cur_frame]

        point_ids_flat = self.point_ids[..., 0]

        # 仅对 valid_idx 对应的点取全局四元数并激活
        valid_point_ids = point_ids_flat[valid_idx]                  # (num_valid_points,)
        global_quats_per_valid_pts = global_quats_cur_frame[valid_point_ids]
        global_quats_valid_act = self.quat_act(global_quats_per_valid_pts)

        # 局部四元数激活（仅 valid_idx 子集）
        _quats_valid_act = self.quat_act(quats[valid_idx])

        # 检测单位四元数 [1, 0, 0, 0]
        def is_identity_quat_local(quats, tol=1e-6):
            """检测单位四元数"""
            w_near_1 = torch.abs(quats[:, 0] - 1.0) < tol
            x_near_0 = torch.abs(quats[:, 1]) < tol
            y_near_0 = torch.abs(quats[:, 2]) < tol
            z_near_0 = torch.abs(quats[:, 3]) < tol
            return w_near_1 & x_near_0 & y_near_0 & z_near_0

        identity_mask_valid = is_identity_quat_local(global_quats_valid_act)
        non_identity_valid = ~identity_mask_valid

        # 初始化结果为输入的 _quats_valid_act
        result_quats_valid = _quats_valid_act.clone()

        if non_identity_valid.any():
            non_identity_global = global_quats_valid_act[non_identity_valid]
            non_identity_local = result_quats_valid[non_identity_valid]
            multiplied_quats = quat_mult(non_identity_global, non_identity_local)
            result_quats_valid[non_identity_valid] = multiplied_quats

        return result_quats_valid

    def load_rigid_assets_from_path(self, state_dict: Dict):
        if not self.load_rigid_assets:
            logging.info("[load_rigid_assets_from_path] No rigid assets to load.")
            return state_dict, set()
        
        logging.info(f"[load_rigid_assets_from_path] Loading rigid assets from: {self.rigid_assets_base_path}")

        if not self.rigid_assets_base_path.startswith("/"):
            rigid_assets_abs_path = os.path.join(self.model_path, self.rigid_assets_base_path)
        else:
            rigid_assets_abs_path = self.rigid_assets_base_path
        
        all_ply_files_in_base = glob.glob(os.path.join(rigid_assets_abs_path, "*.ply"))
        total_frames = state_dict["instances_trans"].shape[0]

        all_dynamic_assets_ids = set()

        for ply_file in all_ply_files_in_base:
            max_instance_id_in_checkpoint = state_dict["instances_size"].shape[0] - 1
            # file name: model_obj_000000999.ply
            file_name = os.path.basename(ply_file)
            instance_id_str = file_name.split(".ply")[0].split("_")[-1]
            instance_id = int(instance_id_str)
            ckp_instance_id = max_instance_id_in_checkpoint + 1

            self.instance_id_dict[instance_id] = ckp_instance_id
            all_dynamic_assets_ids.add(ckp_instance_id)

            logging.info(f"[load_rigid_assets_from_path] Loading rigid asset: {file_name} with ckp instance ID: {ckp_instance_id}")
            new_rigid_gs_tensors = load_rigid_ply(
                ply_path=ply_file,
                new_instance_id=ckp_instance_id,
                appearance_dim=8,
                device=self.device
            )
            for key, tensor in new_rigid_gs_tensors.items():
                old_tensor = state_dict.get(key, None)
                if old_tensor is not None:
                    state_dict[key] = torch.cat([old_tensor, tensor], dim=0)
                else:
                    state_dict[key] = tensor

            # file name: model_obj_000000999.yaml
            yaml_file_name = file_name.replace(".ply", ".yaml")
            instance_tensors = load_instance_tensors_from_yaml(
                yaml_path=os.path.join(rigid_assets_abs_path, yaml_file_name),
                target_gid=instance_id,
                device=self.device
            )

            for key, tensor in instance_tensors.items():
                old_tensor = state_dict.get(key, None)
                if old_tensor is not None:
                    dim = 0 if key == "instances_size" else 1
                    state_dict[key] = torch.cat([old_tensor, tensor], dim=dim)
                else:
                    state_dict[key] = tensor

            logging.info(f"[load_rigid_assets_from_path] Loaded rigid asset: {file_name} with instance ID: {ckp_instance_id}")
        
        logging.info(f"[load_rigid_assets_from_path] Completed loading rigid assets. Instance ID mapping: {self.instance_id_dict}")
        return state_dict, all_dynamic_assets_ids
    