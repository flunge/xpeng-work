import logging
import random
import numpy as np
from typing import Dict, List
from scipy.spatial import KDTree
import time
from plyfile import PlyData
import os
import json

import torch
from gsplat.cuda._wrapper import spherical_harmonics
from pytorch3d.transforms import matrix_to_quaternion
from torch.nn import Parameter
from omegaconf import OmegaConf

from ..gaussians.basics import (
    RGB2SH,
    dataclass_camera,
    dup_in_optim,
    interpolate_quats,
    k_nearest_sklearn,
    num_sh_bases,
    quat_mult,
    quat_to_rotmat,
    random_quat_tensor,
    remove_from_optim,
    fit_plane_to_points,
    project_point_to_plane
)
from ..gaussians.vanilla import VanillaGaussians
from ..fourier_utils import IDFT, get_features_fourier
from .rigid_render import RigidNodes_render

logger = logging.getLogger()


class RigidNodes(RigidNodes_render, VanillaGaussians):
    def __init__(self, **kwargs):
        ctrl_cfg = kwargs.get('ctrl', OmegaConf.create({}))
        use_fourier_features = ctrl_cfg.get("use_fourier_features", False)
        fourier_dim = ctrl_cfg.get("fourier_dim", 40)
        fourier_scale = ctrl_cfg.get("fourier_scale", 1.0)

        super().__init__(**kwargs)

        if self.use_fourier_features:
            self.appearance_embedding_cfg = None
            logger.info("Fourier features enabled - Appearance embedding disabled")

    def register_normalized_timestamps(self, normalized_timestamps: int):
        self.normalized_timestamps = normalized_timestamps

    def update_model_kdtree(self):
        for model_id in self.kdtree_points_instance_id.keys():
            pts_mask = self.point_ids[..., 0] == model_id
            model_points = self._means[pts_mask].cpu().detach()
            self.kdtree_points_instance_id[model_id] = model_points
            self.kdtree_instance_id[model_id] = KDTree(model_points)

    def get_param_groups(self) -> Dict[str, List[Parameter]]:
        param_groups = super().get_param_groups()
        param_groups[self.class_prefix + "ins_rotation"] = [self.instances_quats]
        param_groups[self.class_prefix + "ins_translation"] = [self.instances_trans]
        return param_groups

    def refinement_after(self, step: int, optimizer: torch.optim.Optimizer) -> None:
        assert step == self.step
        if self.step <= self.ctrl_cfg.warmup_steps:
            return
        if self.step >= self.ctrl_cfg.stop_refine_at:
            return
        with torch.no_grad():
            # only split/cull if we've seen every image since opacity reset
            reset_interval = self.ctrl_cfg.reset_alpha_interval
            do_densification = self.step < self.ctrl_cfg.stop_split_at and self.step % reset_interval > max(
                self.num_train_images, self.ctrl_cfg.refine_interval
            )
            # split & duplicate
            logging.info("Class %s current points: %d @ step %d", self.class_prefix, self.num_points, self.step)
            if do_densification:
                assert self.xys_grad_norm is not None and self.vis_counts is not None and self.max_2Dsize is not None

                avg_grad_norm = self.xys_grad_norm / self.vis_counts
                high_grads = (avg_grad_norm > self.ctrl_cfg.densify_grad_thresh).squeeze()

                splits = (
                    self.get_scaling.max(dim=-1).values > self.ctrl_cfg.densify_size_thresh * self.scene_scale
                ).squeeze()
                if self.step < self.ctrl_cfg.stop_screen_size_at:
                    splits |= (self.max_2Dsize > self.ctrl_cfg.split_screen_size).squeeze()
                splits &= high_grads
                nsamps = self.ctrl_cfg.n_split_samples
                split_gaussians = self.split_gaussians(splits, nsamps)
                (
                    split_means,
                    split_feature_dc,
                    split_feature_rest,
                    split_opacities,
                    split_scales,
                    split_quats,
                    split_ids,
                ) = split_gaussians[:7]

                dups = (
                    self.get_scaling.max(dim=-1).values <= self.ctrl_cfg.densify_size_thresh * self.scene_scale
                ).squeeze()
                dups &= high_grads
                dup_gaussians = self.dup_gaussians(dups)
                (
                    dup_means,
                    dup_feature_dc,
                    dup_feature_rest,
                    dup_opacities,
                    dup_scales,
                    dup_quats,
                    dup_ids,
                ) = dup_gaussians[:7]

                self._means = Parameter(torch.cat([self._means.detach(), split_means, dup_means], dim=0))
                self._features_dc = Parameter(
                    torch.cat(
                        [self._features_dc.detach(), split_feature_dc, dup_feature_dc],
                        dim=0,
                    )
                )
                self._features_rest = Parameter(
                    torch.cat(
                        [
                            self._features_rest.detach(),
                            split_feature_rest,
                            dup_feature_rest,
                        ],
                        dim=0,
                    )
                )
                self._opacities = Parameter(
                    torch.cat(
                        [self._opacities.detach(), split_opacities, dup_opacities],
                        dim=0,
                    )
                )
                self._scales = Parameter(torch.cat([self._scales.detach(), split_scales, dup_scales], dim=0))
                self._quats = Parameter(torch.cat([self._quats.detach(), split_quats, dup_quats], dim=0))

                self.point_ids = torch.cat([self.point_ids, split_ids, dup_ids], dim=0)

                if self.appearance_embedding_cfg:
                    split_gs_features, dup_gs_features = split_gaussians[7], dup_gaussians[7]
                    self._appearance_features = Parameter(
                        torch.cat(
                            [
                                self._appearance_features.detach(),
                                split_gs_features,
                                dup_gs_features,
                            ],
                            dim=0,
                        )
                    )

                # append zeros to the max_2Dsize tensor
                self.max_2Dsize = torch.cat(
                    [
                        self.max_2Dsize,
                        torch.zeros_like(split_scales[:, 0]),
                        torch.zeros_like(dup_scales[:, 0]),
                    ],
                    dim=0,
                )

                split_idcs = torch.where(splits)[0]
                param_groups = self.get_gaussian_param_groups()
                dup_in_optim(optimizer, split_idcs, param_groups, n=nsamps)

                dup_idcs = torch.where(dups)[0]
                param_groups = self.get_gaussian_param_groups()
                dup_in_optim(optimizer, dup_idcs, param_groups, 1)

                # cull NOTE: Offset all the opacity reset logic by refine_every so that we don't
                # save checkpoints right when the opacity is reset (saves every 2k)
                deleted_mask = self.cull_gaussians()
                param_groups = self.get_gaussian_param_groups()
                remove_from_optim(optimizer, deleted_mask, param_groups)

            print(f"Class {self.class_prefix} left points: {self.num_points}")

            # reset opacity
            if (
                self.step % reset_interval == self.ctrl_cfg.refine_interval
                and self.step < self.ctrl_cfg.stop_reset_alpha_at
            ):
                # NOTE: in nerfstudio, reset_value = cull_alpha_thresh * 0.8
                # we align to original repo of gaussians spalting
                reset_value = torch.min(
                    self.get_opacity.data,
                    torch.ones_like(self._opacities.data) * self.ctrl_cfg.reset_alpha_value,
                )
                self._opacities.data = torch.logit(reset_value)
                # reset the exp of optimizer
                for group in optimizer.param_groups:
                    if group["name"] == self.class_prefix + "opacity":
                        old_params = group["params"][0]
                        param_state = optimizer.state[old_params]
                        param_state["exp_avg"] = torch.zeros_like(param_state["exp_avg"])
                        param_state["exp_avg_sq"] = torch.zeros_like(param_state["exp_avg_sq"])
            self.xys_grad_norm = None
            self.vis_counts = None
            self.max_2Dsize = None

        if self.ctrl_cfg.get("use_plane_fit", False):
            if step % 500 == 0:
                t1 = time.time()
                self.update_model_kdtree()
                t2 = time.time()
                print("update kdtree time ", t2 - t1)

    def cull_gaussians(self):
        """
        This function deletes gaussians with under a certain opacity threshold
        """
        n_bef = self.num_points
        # cull transparent ones
        culls = (self.get_opacity.data < self.ctrl_cfg.cull_alpha_thresh).squeeze()

        if self.ctrl_cfg.cull_out_of_bound:
            culls = culls | self.get_out_of_bound_mask()

        if self.step > self.ctrl_cfg.reset_alpha_interval:
            # cull huge ones
            max_scale = self.ctrl_cfg.get("cull_scale_max_meters", None)
            if max_scale is not None:
                toobigs = (
                    torch.exp(self._scales).max(dim=-1).values > max_scale
                ).squeeze()
            else:
                toobigs = (
                    torch.exp(self._scales).max(dim=-1).values > self.ctrl_cfg.cull_scale_thresh * self.scene_scale
                ).squeeze()

            culls = culls | toobigs
            if self.step < self.ctrl_cfg.stop_screen_size_at:
                # cull big screen space
                assert self.max_2Dsize is not None
                culls = culls | (self.max_2Dsize > self.ctrl_cfg.cull_screen_size).squeeze()
        
        self._means = Parameter(self._means[~culls].detach())
        self._scales = Parameter(self._scales[~culls].detach())
        self._quats = Parameter(self._quats[~culls].detach())
        self._features_dc = Parameter(self._features_dc[~culls].detach())
        self._features_rest = Parameter(self._features_rest[~culls].detach())
        self._opacities = Parameter(self._opacities[~culls].detach())
        self.point_ids = self.point_ids[~culls]
        if self.appearance_embedding_cfg:
            self._appearance_features = Parameter(self._appearance_features[~culls].detach())

        print(f"     Cull: {n_bef - self.num_points}")
        return culls

    def split_gaussians(self, split_mask: torch.Tensor, samps: int = 2) -> List:
        """
        This function splits gaussians that are too large
        """

        n_splits = split_mask.sum().item()
        print(f"    Split: {n_splits}")
        centered_samples = torch.randn((samps * n_splits, 3), device=self.device)  # Nx3 of axis-aligned scales
        scaled_samples = (
            torch.exp(self._scales[split_mask].repeat(samps, 1)) * centered_samples
        )  # how these scales are rotated
        quats = self.quat_act(self._quats[split_mask])  # normalize them first
        rots = quat_to_rotmat(quats.repeat(samps, 1))  # how these scales are rotated
        rotated_samples = torch.bmm(rots, scaled_samples[..., None]).squeeze()
        split_clap = self.ctrl_cfg.get("split_clap", None)
        if split_clap is not None:
            rotated_samples = torch.clamp(rotated_samples, min=-split_clap, max=split_clap)

        new_means = rotated_samples + self._means[split_mask].repeat(samps, 1)
        # step 2, sample new colors
        # new_colors_all = self.colors_all[split_mask].repeat(samps, 1, 1)
        # Handle both 2D (standard) and 3D (Fourier) features
        if self._features_dc.dim() == 3:  # Fourier features [N, fourier_dim, 3]
            new_feature_dc = self._features_dc[split_mask].repeat(samps, 1, 1)
        else:  # Standard features [N, 3]
            new_feature_dc = self._features_dc[split_mask].repeat(samps, 1)
        new_feature_rest = self._features_rest[split_mask].repeat(samps, 1, 1)
        # step 3, sample new opacities
        new_opacities = self._opacities[split_mask].repeat(samps, 1)
        # step 4, sample new scales
        size_fac = 1.6
        new_scales = torch.log(torch.exp(self._scales[split_mask]) / size_fac).repeat(samps, 1)
        # Note: The original scales should be updated when the new gaussians are added to the model
        # step 5, sample new quats
        new_quats = self._quats[split_mask].repeat(samps, 1)
        # step 6, sample new ids
        new_ids = self.point_ids[split_mask].repeat(samps, 1)

        if self.ctrl_cfg.get("use_plane_fit", False):
            t1 = time.time()
            new_means = self.fit_points(new_means, new_ids)
            t2 = time.time()
            print("fit plane time ", t2 - t1)

        new_gaussians = [
            new_means,
            new_feature_dc,
            new_feature_rest,
            new_opacities,
            new_scales,
            new_quats,
            new_ids,
        ]
        if self.appearance_embedding_cfg:
            # step 7, sample for gaussian features
            new_gs_features = self._appearance_features[split_mask].repeat(samps, 1)
            new_gaussians.append(new_gs_features)

        return new_gaussians

    def fit_points(self, new_xyz, new_ids):
        for model_id, model_kdtree in self.kdtree_instance_id.items():
            pts_mask = new_ids[..., 0] == model_id
            query_xyz = new_xyz[pts_mask].cpu().detach()
            if query_xyz.shape[0] == 0:
                continue

            distances, indices = model_kdtree.query(query_xyz, k=20)
            proj_list = []

            for i, query_point in enumerate(query_xyz):
                nearest_points = self.kdtree_points_instance_id[model_id][indices[i]]
                normal, plane_point = fit_plane_to_points(nearest_points)
                projection = project_point_to_plane(query_point, normal, plane_point)
                proj_list.append(projection)

            points_tensor = torch.from_numpy(np.array(proj_list))
            new_xyz[pts_mask] = points_tensor.cuda()
        return new_xyz

    def dup_gaussians(self, dup_mask: torch.Tensor) -> List:
        """
        This function duplicates gaussians that are too small
        """
        n_dups = dup_mask.sum().item()
        print(f"      Dup: {n_dups}")
        dup_means = self._means[dup_mask]
        # dup_colors = self.colors_all[dup_mask]
        dup_feature_dc = self._features_dc[dup_mask]
        dup_feature_rest = self._features_rest[dup_mask]
        dup_opacities = self._opacities[dup_mask]
        dup_scales = self._scales[dup_mask]
        dup_quats = self._quats[dup_mask]
        dup_ids = self.point_ids[dup_mask]
        duplicate_gaussians = [
            dup_means,
            dup_feature_dc,
            dup_feature_rest,
            dup_opacities,
            dup_scales,
            dup_quats,
            dup_ids,
        ]
        if self.appearance_embedding_cfg:
            dup_gs_features = self._appearance_features[dup_mask]
            duplicate_gaussians.append(dup_gs_features)

        return duplicate_gaussians

    def get_out_of_bound_mask(self):
        """
        This function checks if the gaussians are out of instance boxes
        """
        # get the instance boxes
        per_pts_size = self.instances_size[self.point_ids[..., 0]]
        instance_pts = self._means

        mask = (instance_pts.abs() > per_pts_size / 2).any(dim=-1)
        return mask

    def smooth_means_z_value_ema(self, means, cur_frame, fraction_from_cur_frame):
        """
        Exponential moving average for the z value of the means.
        """
        frac_frame_id = float(cur_frame + fraction_from_cur_frame)
        self.history_world_means[frac_frame_id] = means

        alpha = 0.8
        device = means.device

        # check if cache contains history smooth result
        if frac_frame_id in self.history_smoothed_means:
            return self.history_smoothed_means[frac_frame_id]

        # Get previous frame's smoothed z value. if not found, use current frame's z value
        hist_frame_ids = sorted(self.history_smoothed_means.keys())
        if hist_frame_ids:
            prev_z = self.history_smoothed_means[hist_frame_ids[-1]][:, 2]
        else:
            prev_z = means[:, 2].clone()

        # window check: check if the latest 10 frames contain unchange z value
        origin_frame_range = min(10, len(hist_frame_ids))
        if origin_frame_range == 0:                               
            changing_mask = torch.zeros(means.shape[0], dtype=torch.bool, device=device)
        else:
            recent_keys = hist_frame_ids[-origin_frame_range:]
            hist_z = torch.stack(
                [self.history_world_means[k][:, 2].to(device) for k in recent_keys],
                dim=0
            )  # (win, N)
            # 任一帧内有三帧z值不变 即视为无效高斯
            # 连续不变检测：相邻差分 == 0 的计数
            dz = torch.diff(hist_z, dim=0)                 # (win-1, N)
            static_count = (dz.abs() < 0.001).sum(dim=0)    # (N,)  零差分个数
            # 要求至少 3 帧没有变化（win=5 时 static_count>=3 即满足）
            no_change_mask = static_count >= 3             # (N,)  True=static
            changing_mask = ~no_change_mask

        # 仅对 z 做 EMA
        z_raw = means[:, 2]
        z_smooth = alpha * z_raw + (1 - alpha) * prev_z
        z_smooth_filtered = torch.where(changing_mask, z_smooth, z_raw)

        # write back to smoothed means
        means_smoothed = means.clone()
        means_smoothed[:, 2] = z_smooth_filtered

        # save in cache
        self.history_smoothed_means[frac_frame_id] = means_smoothed
        return means_smoothed

    def smooth_weighted_means_z_value(self, means, cur_frame, fraction_from_cur_frame):
        """
        Use the latest 3 frames' z values for weighted averaging.
        """
        frac_frame_id = float(cur_frame + fraction_from_cur_frame)
        self.history_world_means[frac_frame_id] = means

        win = 3
        w = torch.tensor([0.2, 0.3, 0.5], device=means.device)  # (3,)

        # cache hit
        if frac_frame_id in self.history_smoothed_means:
            return self.history_smoothed_means[frac_frame_id]

        means_smoothed = means.clone()
        # not enough frames => return as is
        if len(self.history_world_means) < win:
            self.history_smoothed_means[frac_frame_id] = means_smoothed
            return means_smoothed

        # get recent 3 frames, which will be used for weighted averaging
        recent_keys = sorted(self.history_world_means.keys())[-win:]
        hist = torch.stack(
            [self.history_world_means[k].to(means.device) for k in recent_keys],
            dim=0
        )  # shape: (3, N, 3)

        # Weighted average calculation for debugging (unused in production)
        # gs_0_window_value = hist[:, 0, 2]
        # gs_0_weighted_value = torch.sum(gs_0_window_value * w)

        # 2. only z channel
        z_hist = hist[..., 2]

        # 3. weighted sum along frame dimension -> (N,)
        z_smooth = torch.einsum('w,wN->N', w, z_hist)

        # 4. write back to output and cached
        means_smoothed[:, 2] = z_smooth
        self.history_smoothed_means[frac_frame_id] = means_smoothed
        return means_smoothed

    def visualize_history_plot(self):
        import matplotlib.pyplot as plt

        if self.cur_frame < self.num_frames - 1:
            return

        # 1. random Gaussian
        any_key = next(iter(self.history_world_means))
        n_gs = self.history_world_means[any_key].shape[0]
        gs_id = torch.randint(0, n_gs, (1,)).item()

        # 2. sort the history means and output z value
        hist_ids = sorted(self.history_world_means.keys())
        z_values = [
            self.history_world_means[hid][gs_id, 2].cpu().item()
            for hid in hist_ids
        ]

        smoothed_z_values = [
            self.history_smoothed_means[hid][gs_id, 2].cpu().item()
            for hid in hist_ids
        ]

        # 3. display history plots
        plt.figure()
        plt.plot(hist_ids, z_values, label=f'GS #{gs_id} Z')
        plt.plot(hist_ids, smoothed_z_values, label=f'GS #{gs_id} Smoothed Z')
        plt.xlabel('History index')
        plt.ylabel('Z value')
        plt.title(f'Z evolution of Gaussian #{gs_id} across history')
        plt.legend()
        fname = f'history_z_values_gs_{gs_id}.png'
        plt.savefig(fname, dpi=150)

    
    
    def get_instance_activated_gs_dict(self, ins_id: int) -> Dict[str, torch.Tensor]:
        curr_id = self.ins_id_with_curr_id[str(ins_id)]
        pts_mask = self.point_ids[..., 0] == curr_id
        if pts_mask.sum() < 100:
            return None
        local_means = self._means[pts_mask]
        activated_opacities = torch.sigmoid(self._opacities[pts_mask])
        activated_scales = torch.exp(self._scales[pts_mask])
        activated_local_rotations = self.quat_act(self._quats[pts_mask])
        gaussian_dict = {
            "means": local_means,
            "opacities": activated_opacities,
            "scales": activated_scales,
            "quats": activated_local_rotations,
            "sh_dcs": self._features_dc[pts_mask],
            "sh_rests": self._features_rest[pts_mask],
            "ids": self.point_ids[pts_mask],
        }
        if self.appearance_embedding_cfg:
            # TODO: This function is not used yet. So make sure it's correct in the future.
            gaussian_dict["appearance_features"] = self._appearance_features[pts_mask]
        return gaussian_dict

    def selective_trajectory_smoothing(self, trajectory_tensor, acceleration_threshold=0.05, smooth_loop = 5, weights=None):
        if weights is None:
            weights = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0] # euqal weight
        weights_tensor = torch.tensor(weights, device=trajectory_tensor.device, dtype=torch.float32)
        offsets = [-4, -3, -2, -1, 0, 1, 2, 3, 4]

        frame_counts, obstacle_counts, _ = trajectory_tensor.shape
        smoothed_tensor = trajectory_tensor.clone()
        valid_mask = torch.norm(trajectory_tensor, dim=2) > 1e-6

        all_smooth_cnt = 0
        all_smooth_skipped_cnt = 0

        for idx in range(smooth_loop):
            for obstacle_idx in range(obstacle_counts):
                mask = valid_mask[:, obstacle_idx]
                valid_indices = torch.where(mask)[0]
                if len(valid_indices) < 3:
                    continue

                frames_to_smooth = self.find_high_acceleration_frames(
                    trajectory_tensor[:, obstacle_idx, :], 
                    valid_indices, 
                    acceleration_threshold
                )

                jump_frames_set = set(self.detect_jump_frames_as_list(
                    trajectory_tensor[:, obstacle_idx, :],
                    valid_indices,
                    obstacle_idx,
                    buffer=2
                ))
                
                if len(frames_to_smooth) == 0:
                    continue

                obstacle_traj = trajectory_tensor[:, obstacle_idx, :]
                for frame_idx in frames_to_smooth:
                    window_indices = []
                    current_weights = []
                    
                    for i, offset in enumerate(offsets):
                        win_frame = frame_idx + offset
                        if 0 <= win_frame < frame_counts and mask[win_frame]:
                            window_indices.append(win_frame)
                            current_weights.append(weights_tensor[i])

                    # if windows indices contains any jump frame, skip smoothing
                    if any(f in jump_frames_set for f in window_indices):
                        all_smooth_skipped_cnt += 1
                        continue

                    all_smooth_cnt += 1
                    if len(window_indices) >= 2:
                        current_weights_tensor = torch.stack(current_weights)
                        normalized_weights = current_weights_tensor / current_weights_tensor.sum()

                        window_data = obstacle_traj[window_indices, :]
                        weighted_avg = torch.sum(window_data * normalized_weights.unsqueeze(1), dim=0)
                        smoothed_tensor[frame_idx, obstacle_idx, :] = weighted_avg
        
        logging.info(f"[selective_trajectory_smoothing] Total smoothed frames: {all_smooth_cnt}, Total skipped frames due to jumps: {all_smooth_skipped_cnt}")
        
        return smoothed_tensor

    def find_high_acceleration_frames(self, obstacle_traj, valid_indices, threshold):
        frames_to_smooth = set()
        gaps = valid_indices[1:] - valid_indices[:-1]
        discontinuity_points = torch.where(gaps > 1)[0] + 1
        
        segments = []
        start = 0
        for point in discontinuity_points:
            segments.append(valid_indices[start:point])
            start = point
        segments.append(valid_indices[start:])
        
        for segment in segments:
            if len(segment) >= 3:
                segment_traj = obstacle_traj[segment, :]  # (L, 2)

                second_order_diff = segment_traj[2:] - 2 * segment_traj[1:-1] + segment_traj[:-2]  # (L-2, 2)
                diff_norms = torch.norm(second_order_diff, dim=1)  # (L-2,)
                high_accel_local_indices = torch.where(diff_norms > threshold)[0]

                for local_idx in high_accel_local_indices:
                    global_idx = segment[local_idx + 1]
                    frames_to_smooth.add(global_idx.item())

                    if local_idx > 0:
                        frames_to_smooth.add(segment[local_idx].item())
                    if local_idx + 2 < len(segment):
                        frames_to_smooth.add(segment[local_idx + 2].item())
        return sorted(frames_to_smooth)

    def detect_jump_frames_as_list(self, obstacle_traj, valid_indices, obstacle_idx, k_mad=3.0, min_jump_ratio=3.0, buffer=2):
        jump_frames = set()
        
        if len(valid_indices) < 2:
            return []

        # 分段（处理非连续）
        gaps = valid_indices[1:] - valid_indices[:-1]
        disc_pts = torch.where(gaps > 1)[0] + 1
        segments = []
        start = 0
        for p in disc_pts:
            segments.append(valid_indices[start:p])
            start = p
        segments.append(valid_indices[start:])

        for seg in segments:
            if len(seg) < 2:
                continue
            pos = obstacle_traj[seg]
            displacements = torch.norm(pos[1:] - pos[:-1], dim=1)  # (L-1,), all the displacements in this segment
            
            if displacements.numel() == 0:
                continue

            # robust jump threshold estimation
            median_disp = torch.median(displacements)
            mad = torch.median(torch.abs(displacements - median_disp))
            sigma_est = 1.4826 * mad # estimate standard deviation

            abs_min_jump = 5.0
            jump_threshold = max(
                median_disp + k_mad * sigma_est,
                median_disp * min_jump_ratio if median_disp > 1e-3 else 1.0,
                abs_min_jump
            )

            # detect jumps
            for i, disp in enumerate(displacements):
                if disp > jump_threshold:
                    for j in range(max(0, i - buffer), min(len(seg), i + 2 + buffer)):
                        jump_frames.add(seg[j].item())       # jump start frame and its surrounding buffer frames

        return sorted(jump_frames)

    def compute_reg_loss(self) -> Dict[str, torch.Tensor]:
        loss_dict = super().compute_reg_loss()
        if self.reg_cfg is None:
            return loss_dict
        if self._means is None or self._means.size(0) == 0:
            return loss_dict
        scaling_reg = self.reg_cfg.get("scaling_reg", None)
        if scaling_reg is not None:
            w = scaling_reg.w
            precentile = scaling_reg.precentile
            stop_after = scaling_reg.stop_after
            start_after = scaling_reg.start_after

            if self.step < stop_after and self.step > start_after and w > 0:
                scale_prod = self._gs_cache["_scales"].prod(dim=-1)
                p = torch.kthvalue(scale_prod, int(scale_prod.shape[0] * precentile)).values
                # penalize the scales that are too large
                loss_dict["scaling_percentile_reg"] = torch.relu(scale_prod - p).mean() * w

        # temporal smooth regularization
        temporal_smooth_reg = self.reg_cfg.get("temporal_smooth_reg", None)
        if temporal_smooth_reg is not None:
            instance_mask = self.instances_fv[self.cur_frame]
            if instance_mask.sum() > 0:
                trans_cfg = temporal_smooth_reg.get("trans", None)
                if trans_cfg is not None:
                    fi_interval = random.randint(1, trans_cfg.smooth_range)
                    if self.cur_frame >= fi_interval and self.cur_frame < self.num_frames - fi_interval:
                        valid_mask = (
                            self.instances_fv[self.cur_frame - fi_interval]
                            & self.instances_fv[self.cur_frame + fi_interval]
                            & self.instances_fv[self.cur_frame]
                        )
                        if valid_mask.sum() > 0:
                            cur_trans = self.instances_trans[self.cur_frame]
                            pre_trans = self.instances_trans[self.cur_frame - fi_interval].data
                            next_trans = self.instances_trans[self.cur_frame + fi_interval].data
                            loss = (
                                (next_trans[valid_mask] + pre_trans[valid_mask] - 2 * cur_trans[valid_mask])
                                .abs()
                                .mean()
                            )
                            loss_dict["trans_temporal_smooth"] = loss * trans_cfg.w
        return loss_dict


    def load_state_dict(self, state_dict: Dict, **kwargs) -> str:
        all_dynamic_assets_ids = set()
        if self.class_name == "RigidNodes":
            _, all_dynamic_assets_ids = self.load_rigid_assets_from_path(state_dict)

        # Handle instances_trans shape mismatch (子类特有逻辑)
        if "instances_trans" in state_dict:
            checkpoint_trans_shape = state_dict["instances_trans"].shape
            if len(checkpoint_trans_shape) == 4 and checkpoint_trans_shape[2] == 1:
                # Reshape from (num_frame, num_instances, 1, 3) to (num_frame, num_instances, 3)
                state_dict["instances_trans"] = state_dict["instances_trans"].squeeze(2)
                logger.warning(f"Reshaped instances_trans from {checkpoint_trans_shape} to {state_dict['instances_trans'].shape}")

        # Check if the checkpoint has Fourier features and adjust model accordingly
        if "_features_dc" in state_dict:
            checkpoint_features_shape = state_dict["_features_dc"].shape
            current_features_shape = self._features_dc.shape

            # Check for Fourier features mismatch and adapt accordingly

            # If checkpoint has 3D features [N, dim, 3] but current model has 2D [N, 3]
            if len(checkpoint_features_shape) == 3 and checkpoint_features_shape[1] > 1:
                if not self.use_fourier_features or len(current_features_shape) == 2:
                    logger.warning(f"Checkpoint has Fourier features shape {checkpoint_features_shape} but model is not configured for Fourier. Enabling Fourier features.")

                    # Force enable Fourier features
                    self.use_fourier_features = True
                    self.fourier_dim = checkpoint_features_shape[1]

                    # Update config to reflect Fourier mode
                    if hasattr(self, 'ctrl_cfg'):
                        self.ctrl_cfg.use_fourier_features = True
                        self.ctrl_cfg.fourier_dim = checkpoint_features_shape[1]
                        self.ctrl_cfg.appearance_embedding_cfg = None

                    # Disable appearance embedding when using Fourier
                    self.appearance_embedding_cfg = None
                    if hasattr(self, 'appearance_embedding_model'):
                        delattr(self, 'appearance_embedding_model')
                    if hasattr(self, '_appearance_features'):
                        delattr(self, '_appearance_features')

                    # Remove appearance embedding keys from state_dict since we're switching to Fourier mode
                    keys_to_remove = []
                    for key in state_dict.keys():
                        if key.startswith('_appearance_features') or key.startswith('appearance_embedding_model'):
                            keys_to_remove.append(key)

                    for key in keys_to_remove:
                        state_dict.pop(key, None)
                        logger.warning(f"Removed appearance embedding key '{key}' from state_dict when switching to Fourier mode")

                    # Reinitialize features with Fourier dimensions
                    features_dc = torch.zeros(checkpoint_features_shape).float().to(self.device)
                    self._features_dc = Parameter(features_dc)

                    # Initialize _features_rest for Fourier mode
                    dim_sh = num_sh_bases(self.sh_degree)
                    sh_dim = max(0, dim_sh - 1)
                    self._features_rest = Parameter(torch.zeros((checkpoint_features_shape[0], sh_dim, 3)).float().to(self.device))

        msg = super().load_state_dict(state_dict, **kwargs)

        self.only_retain_dynamic_assets(all_dynamic_assets_ids)

        if self.data_source == "vision":
            smooth_pose = self.selective_trajectory_smoothing(self.instances_trans).cuda()
            self.instances_trans = Parameter(smooth_pose)
        return msg

    def only_retain_dynamic_assets(self, all_dynamic_assets_ids: set):
        # remove all rigid except dynamic assets
        if not self.is_only_retain_dynamic_assets or not all_dynamic_assets_ids:
            return 
        
        # get instance id from self.point_ids
        all_instance_ids = set(self.point_ids[..., 0].cpu().numpy().tolist())
        rigid_instance_ids = all_instance_ids - all_dynamic_assets_ids
        self.remove_instances(list(rigid_instance_ids))
        print(f"After loading rigid assets, model has {self.instances_size.shape[0]} instances.")

    # editting functions
    def remove_instances(self, remove_id_list: List[int]) -> None:
        """
        remove instances from the model

        Args:
            remove_id_list: list of instance ids to be removed
        """
        for ins_id in remove_id_list:
            curr_id = self.ins_id_with_curr_id[str(ins_id)]
            mask = ~(self.point_ids[..., 0] == curr_id)
            self._means = Parameter(self._means[mask])
            self._scales = Parameter(self._scales[mask])
            self._quats = Parameter(self._quats[mask])
            self._features_dc = Parameter(self._features_dc[mask])
            self._features_rest = Parameter(self._features_rest[mask])
            self._opacities = Parameter(self._opacities[mask])
            self.point_ids = self.point_ids[mask]
            if self.appearance_embedding_cfg:
                self._appearance_features = Parameter(self._appearance_features[mask])

    def collect_gaussians_from_ids(self, ins_ids_list: List[int]) -> Dict:
        gaussian_dict = {}
        for ins_id in ins_ids_list:
            if ins_id not in gaussian_dict:
                curr_id = self.ins_id_with_curr_id[str(ins_id)]
                instance_raw_dict = {
                    "_means": self._means[self.point_ids[..., 0] == curr_id],
                    "_scales": self._scales[self.point_ids[..., 0] == curr_id],
                    "_quats": self._quats[self.point_ids[..., 0] == curr_id],
                    "_features_dc": self._features_dc[self.point_ids[..., 0] == curr_id],
                    "_features_rest": self._features_rest[self.point_ids[..., 0] == curr_id],
                    "_opacities": self._opacities[self.point_ids[..., 0] == curr_id],
                    "point_ids": self.point_ids[self.point_ids[..., 0] == curr_id],
                }
                if self.appearance_embedding_cfg:
                    instance_raw_dict["_appearance_features"] = self._appearance_features[self.point_ids[..., 0] == curr_id]
                gaussian_dict[ins_id] = instance_raw_dict
        return gaussian_dict

    def replace_instances(self, replace_dict: Dict[int, int]) -> None:
        """
        replace instances from the model

        Args:
            replace_dict: {
                ins_id(to be replaced): ins_id(replace with)
                ...
            }
        """
        new_gaussians_dict = self.collect_gaussians_from_ids(replace_dict.values())
        for ins_id, new_id in replace_dict.items():
            self.remove_instances([ins_id])
            new_gaussian = new_gaussians_dict[new_id]
            self._means = Parameter(torch.cat([self._means, new_gaussian["_means"]], dim=0))
            self._scales = Parameter(torch.cat([self._scales, new_gaussian["_scales"]], dim=0))
            self._quats = Parameter(torch.cat([self._quats, new_gaussian["_quats"]], dim=0))
            self._features_dc = Parameter(torch.cat([self._features_dc, new_gaussian["_features_dc"]], dim=0))
            self._features_rest = Parameter(torch.cat([self._features_rest, new_gaussian["_features_rest"]], dim=0))
            self._opacities = Parameter(torch.cat([self._opacities, new_gaussian["_opacities"]], dim=0))
            # keeps original point ids
            self.point_ids = torch.cat(
                [self.point_ids, torch.full_like(new_gaussian["point_ids"], curr_id)],
                dim=0,
            )
            if self.appearance_embedding_cfg:
                self._appearance_features = Parameter(
                    torch.cat([self._appearance_features, new_gaussian["_appearance_features"]], dim=0)
                )

    def export_gaussians_to_ply(self, alpha_thresh: float, instance_id: List[int] = None) -> Dict[str, torch.Tensor]:
        curr_id_list = []
        for ins_id in instance_id:
            curr_id_list.append(self.ins_id_with_curr_id[str(ins_id)])
        pts_mask = self.point_ids[..., 0] == curr_id_list

        means = self._means[pts_mask]
        direct_color = self.colors[pts_mask]

        activated_opacities = self.get_opacity[pts_mask]
        mask = activated_opacities.squeeze() > alpha_thresh
        return {
            "positions": means[mask],
            "colors": direct_color[mask],
        }
