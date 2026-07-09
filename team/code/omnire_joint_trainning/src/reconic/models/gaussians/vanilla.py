"""
Filename: 3dgs.py

Author: Ziyu Chen (ziyu.sjtu@gmail.com)

Description:
Unofficial implementation of 3DGS based on the work by Bernhard Kerbl, Georgios Kopanas, Thomas Leimkühler,
and George Drettakis.
This implementation is modified from the nerfstudio GaussianSplattingModel.

- Original work by Bernhard Kerbl, Georgios Kopanas, Thomas Leimkühler, and George Drettakis.
- Codebase reference: nerfstudio GaussianSplattingModel
(https://github.com/nerfstudio-project/nerfstudio/blob/gaussian-splatting/nerfstudio/models/gaussian_splatting.py)

Original paper: https://arxiv.org/abs/2308.04079
"""

import logging
from typing import Dict, List, Optional
import numpy as np

import torch
from plyfile import PlyData
import torch.nn as nn
from torch.nn import Parameter
from pytorch3d.transforms import quaternion_to_matrix

from .basics import (
    RGB2SH,
    SH2RGB,
    dup_in_optim,
    k_nearest_sklearn,
    num_sh_bases,
    quat_to_rotmat,
    random_quat_tensor,
    remove_from_optim,
    inverse_sigmoid,
    IDFT,
)
from .vanilla_render import VanillaGaussians_render

logger = logging.getLogger()

MAX_FROZEN_Z_GAUSSIAN_SCALE = 0.1
MAX_FROZEN_GAUSSIAN_SCALE = 2.0
MAX_2D_SCREEN_SIZE = 0.5


class VanillaGaussians(VanillaGaussians_render):
    def __init__(self, *args, **kwargs):
        # 直接将所有参数传递给父类
        super().__init__(*args, **kwargs)

        # Fourier features特殊处理：如果使用fourier features，禁用appearance embedding
        if kwargs.get('use_fourier_features', False):
            self.appearance_embedding_cfg = None

    def create_from_pcd(self, init_means: torch.Tensor, init_colors: torch.Tensor) -> None:
        self._means = Parameter(init_means)
        if self.freeze_means:
            self._means.requires_grad = False

        distances, _ = k_nearest_sklearn(self._means.data, 3)
        distances = torch.from_numpy(distances)
        # find the average of the three nearest neighbors for each point and use that as the scale
        avg_dist = distances.mean(dim=-1, keepdim=True).to(self.device)
        if self.class_name == "Trafficlight":
            avg_dist = torch.clamp(avg_dist, min=1e-8)
            
        if self.ball_gaussians:
            self._scales = Parameter(torch.log(avg_dist.repeat(1, 1)))
        else:
            if self.gaussian_2d:
                self._scales = Parameter(torch.log(avg_dist.repeat(1, 2)))
            else:
                self._scales = Parameter(torch.log(avg_dist.repeat(1, 3)))
        self._quats = Parameter(random_quat_tensor(self.num_points).to(self.device))
        dim_sh = num_sh_bases(self.sh_degree)

        fused_color = RGB2SH(init_colors)  # float range [0, 1]
        shs = torch.zeros((fused_color.shape[0], dim_sh, 3)).float().to(self.device)
        if self.sh_degree > 0:
            shs[:, 0, :3] = fused_color
            shs[:, 1:, 3:] = 0.0
        else:
            shs[:, 0, :3] = torch.logit(init_colors, eps=1e-10)
        if self.class_name == "Trafficlight":
           features_dc = torch.zeros((fused_color.shape[0],self.fourier_dim,3)).float().to(self.device)
           features_dc[:,0,:3] = fused_color
           self._features_dc = Parameter(features_dc.requires_grad_(True))
        else:
           self._features_dc = Parameter(shs[:, 0, :])
        self._features_rest = Parameter(shs[:, 1:, :])
        self._opacities = Parameter(torch.logit(0.1 * torch.ones(self.num_points, 1, device=self.device)))
        if self.freeze_means:
            self._opacities = Parameter(torch.logit(torch.ones(self.num_points, 1, device=self.device)))
            self._opacities.requires_grad = False

        if self.appearance_embedding_cfg:
            self._appearance_features = Parameter(
                torch.zeros((self._means.shape[0], self.appearance_feature_dims)).float().to(self.device)
            )

    @property
    def colors(self):
        if self.sh_degree > 0:
            return SH2RGB(self._features_dc)
        else:
            return torch.sigmoid(self._features_dc)

    @property
    def shs_0(self):
        return self._features_dc

    @property
    def shs_rest(self):
        return self._features_rest

    @property
    def num_points(self):
        return self._means.shape[0]

    def preprocess_per_train_step(self, step: int):
        self.step = step

    def postprocess_per_train_step(
        self,
        step: int,
        optimizer: torch.optim.Optimizer,
        radii: torch.Tensor,
        xys_grad: torch.Tensor,
        last_size: int,
    ) -> None:
        if self.freeze_means:
            return
        self.after_train(radii, xys_grad, last_size)
        if (step % self.ctrl_cfg.refine_interval == 0) and self._means.size(0) > 0:
            self.refinement_after(step, optimizer)

    def after_train(
        self,
        radii: torch.Tensor,
        xys_grad: torch.Tensor,
        last_size: int,
    ) -> None:
        with torch.no_grad():
            # keep track of a moving average of grad norms
            visible_mask = (radii > 0).flatten()
            full_mask = torch.zeros(self.num_points, device=radii.device, dtype=torch.bool)
            full_mask[self.filter_mask] = visible_mask

            grads = xys_grad.norm(dim=-1)
            if self.xys_grad_norm is None:
                self.xys_grad_norm = torch.zeros(self.num_points, device=grads.device, dtype=grads.dtype)
                self.xys_grad_norm[self.filter_mask] = grads
                self.vis_counts = torch.ones_like(self.xys_grad_norm)
            else:
                assert self.vis_counts is not None
                self.vis_counts[full_mask] = self.vis_counts[full_mask] + 1
                self.xys_grad_norm[full_mask] = grads[visible_mask] + self.xys_grad_norm[full_mask]

            # update the max screen size, as a ratio of number of pixels
            if self.max_2Dsize is None:
                self.max_2Dsize = torch.zeros(self.num_points, device=radii.device, dtype=torch.float32)
            newradii = radii[visible_mask]
            self.max_2Dsize[full_mask] = torch.maximum(self.max_2Dsize[full_mask], newradii / float(last_size))

    def refinement_after(self, step, optimizer: torch.optim.Optimizer) -> None:
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

                scale_threshold = self.ctrl_cfg.densify_size_thresh * self.scene_scale
                splits = (self.get_scaling.max(dim=-1).values > scale_threshold).squeeze()

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
                ) = split_gaussians[:6]

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
                ) = dup_gaussians[:6]

                self._means = Parameter(torch.cat([self._means.detach(), split_means, dup_means], dim=0))
                # self.colors_all = Parameter(torch.cat([self.colors_all.detach(), split_colors, dup_colors], dim=0))
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

                if self.appearance_embedding_cfg:
                    split_gs_features, dup_gs_features = split_gaussians[6], dup_gaussians[6]
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

    def cull_gaussians(self):
        """
        This function deletes gaussians with under a certain opacity threshold
        """
        n_bef = self.num_points
        # cull transparent ones
        culls = (self.get_opacity.data < self.ctrl_cfg.cull_alpha_thresh).squeeze()
        if self.step > self.ctrl_cfg.reset_alpha_interval:
            # cull huge ones
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
        # self.colors_all = Parameter(self.colors_all[~culls].detach())
        self._features_dc = Parameter(self._features_dc[~culls].detach())
        self._features_rest = Parameter(self._features_rest[~culls].detach())
        self._opacities = Parameter(self._opacities[~culls].detach())
        if self.appearance_embedding_cfg:
            self._appearance_features = Parameter(self._appearance_features[~culls].detach())

        print(f"     Cull: {n_bef - self.num_points}")
        return culls

    def split_gaussians(self, split_mask: torch.Tensor, samps: int) -> List:
        """
        This function splits gaussians that are too large
        """

        n_splits = split_mask.sum().item()
        print(f"    Split: {n_splits}")
        centered_samples = torch.randn((samps * n_splits, 3), device=self.device)  # Nx3 of axis-aligned scales
        scaled_samples = (
            self.get_scaling[split_mask].repeat(samps, 1)
            * centered_samples
            # torch.exp(self._scales[split_mask].repeat(samps, 1)) * centered_samples
        )  # how these scales are rotated
        quats = self.quat_act(self._quats[split_mask])  # normalize them first
        rots = quat_to_rotmat(quats.repeat(samps, 1))  # how these scales are rotated
        rotated_samples = torch.bmm(rots, scaled_samples[..., None]).squeeze()
        new_means = rotated_samples + self._means[split_mask].repeat(samps, 1)
        # step 2, sample new colors
        # new_colors_all = self.colors_all[split_mask].repeat(samps, 1, 1)
        if self.class_name == "Trafficlight":
            new_feature_dc = self._features_dc[split_mask].repeat(samps, 1, 1)
        else:
            new_feature_dc = self._features_dc[split_mask].repeat(samps, 1)
        new_feature_rest = self._features_rest[split_mask].repeat(samps, 1, 1)
        # step 3, sample new opacities
        new_opacities = self._opacities[split_mask].repeat(samps, 1)
        # step 4, sample new scales
        size_fac = 1.6
        new_scales = torch.log(torch.exp(self._scales[split_mask]) / size_fac).repeat(samps, 1)
        self._scales[split_mask] = torch.log(torch.exp(self._scales[split_mask]) / size_fac)
        # step 5, sample new quats
        new_quats = self._quats[split_mask].repeat(samps, 1)

        new_gaussians = [
            new_means,
            new_feature_dc,
            new_feature_rest,
            new_opacities,
            new_scales,
            new_quats,
        ]
        if self.appearance_embedding_cfg:
            # step 6, sample for gaussian features
            new_gs_features = self._appearance_features[split_mask].repeat(samps, 1)
            new_gaussians.append(new_gs_features)

        return new_gaussians

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
        duplicate_gaussians = [
            dup_means,
            dup_feature_dc,
            dup_feature_rest,
            dup_opacities,
            dup_scales,
            dup_quats,
        ]
        if self.appearance_embedding_cfg:
            dup_gs_features = self._appearance_features[dup_mask]
            duplicate_gaussians.append(dup_gs_features)

        return duplicate_gaussians

    def compute_reg_loss(self):
        loss_dict = {}
        if self.reg_cfg is None:
            return loss_dict
        if self._means is None or self._means.size(0) == 0:
            return loss_dict
        sharp_shape_reg_cfg = self.reg_cfg.get("sharp_shape_reg", None)
        if sharp_shape_reg_cfg is not None:
            w = sharp_shape_reg_cfg.w
            max_gauss_ratio = sharp_shape_reg_cfg.max_gauss_ratio
            step_interval = sharp_shape_reg_cfg.step_interval
            if self.step % step_interval == 0:
                # scale regularization
                scale_exp = self.get_scaling
                scale_reg = (
                    torch.maximum(
                        scale_exp.amax(dim=-1) / scale_exp.amin(dim=-1),
                        torch.tensor(max_gauss_ratio),
                    )
                    - max_gauss_ratio
                )
                scale_reg = scale_reg.mean() * w
                loss_dict["sharp_shape_reg"] = scale_reg

        flatten_reg = self.reg_cfg.get("flatten", None)
        if flatten_reg is not None:
            sclaings = self.get_scaling
            min_scale, _ = torch.min(sclaings, dim=1)
            min_scale = torch.clamp(min_scale, 0, 30)
            flatten_loss = torch.abs(min_scale).mean()
            loss_dict["flatten"] = flatten_loss * flatten_reg.w

        sphere_reg = self.reg_cfg.get("sphere_reg", None)
        if sphere_reg is not None:
            scalings = self.get_scaling
            quats = self.get_quats
            sx, sy, sz = scalings[:, 0], scalings[:, 1], scalings[:, 2]
            rot_mats = quaternion_to_matrix(quats)
            # --- Flatten part ---
            z_axis = rot_mats[:, :, 2]  # local z-axis
            flatten_loss = z_axis[:, :2].pow(2).sum(dim=-1).mean()       # should be [0, 0]
            upward_loss = (1.0 - z_axis[:, 2]).abs().mean()              # should be 1
            scale_z_loss = sz.abs().mean()                               # suppress vertical elongation
            ground_flatten_loss = flatten_loss + upward_loss + scale_z_loss
            # --- Symmetry part ---
            isotropy_loss = (sx - sy).abs().mean()
            identity = torch.eye(2, device=rot_mats.device).unsqueeze(0)
            xy_rot = rot_mats[:, :2, :2]
            rotation_sym_loss = ((xy_rot - identity) ** 2).mean()
            ground_symmetry_loss = isotropy_loss + rotation_sym_loss
            loss_dict["sphere_reg"] = sphere_reg.w_flatten * ground_flatten_loss + \
                sphere_reg.w_symmetry * ground_symmetry_loss

        z_flatten_reg = self.reg_cfg.get("z_flatten", None)
        if z_flatten_reg is not None:
            step_interval = z_flatten_reg.step_interval
            if self.step % step_interval == 0:
                scalings = self.get_scaling
                z_scale = scalings[:, 2]
                z_scale = torch.clamp(z_scale, 0, 30)
                flatten_loss = torch.abs(z_scale).mean()
                loss_dict["z_flatten"] = flatten_loss * z_flatten_reg.w

        sparse_reg = self.reg_cfg.get("sparse_reg", None)
        if sparse_reg:
            if (self.cur_radii > 0).sum():
                opacity = torch.sigmoid(self._opacities)
                opacity = opacity.clamp(1e-6, 1 - 1e-6)
                log_opacity = opacity * torch.log(opacity)
                log_one_minus_opacity = (1 - opacity) * torch.log(1 - opacity)
                sparse_loss = -1 * (log_opacity + log_one_minus_opacity)[self.cur_radii > 0].mean()
                loss_dict["sparse_reg"] = sparse_loss * sparse_reg.w

        # compute the max of scaling
        max_s_square_reg = self.reg_cfg.get("max_s_square_reg", None)
        if max_s_square_reg is not None and not self.ball_gaussians:
            loss_dict["max_s_square"] = torch.mean((self.get_scaling.max(dim=1).values) ** 2) * max_s_square_reg.w
        return loss_dict

    def export_gaussians_to_ply(self, alpha_thresh: float) -> Dict:
        means = self._means
        direct_color = self.colors

        activated_opacities = self.get_opacity
        mask = activated_opacities.squeeze() > alpha_thresh
        return {
            "positions": means[mask],
            "colors": direct_color[mask],
        }

    def postprocess_cull_frozen_gaussians(
        self, radii: torch.Tensor, last_size: int, optimizer: Optional[torch.optim.Optimizer] = None
    ):
        with torch.no_grad():
            # keep track of a moving average of grad norms
            visible_mask = (radii > 0).flatten()
            full_mask = torch.zeros(self.num_points, device=radii.device, dtype=torch.bool)
            full_mask[self.filter_mask] = visible_mask

            # update the max screen size, as a ratio of number of pixels
            max_2Dsize = torch.zeros(self.num_points, device=radii.device, dtype=torch.float32)
            newradii = radii[visible_mask]
            max_2Dsize[full_mask] = torch.maximum(max_2Dsize[full_mask], newradii / float(last_size))

        n_bef = self.num_points
        scales = self.get_scaling
        culls = (scales[:, 2] > MAX_FROZEN_Z_GAUSSIAN_SCALE) | (scales.max(dim=-1).values > MAX_FROZEN_GAUSSIAN_SCALE)
        culls = culls & (max_2Dsize > self.ctrl_cfg.cull_screen_size).squeeze()
        culls = culls | (max_2Dsize > MAX_2D_SCREEN_SIZE).squeeze()
        self._means = Parameter(self._means[~culls].detach())
        self._scales = Parameter(self._scales[~culls].detach())
        self._quats = Parameter(self._quats[~culls].detach())
        self._features_dc = Parameter(self._features_dc[~culls].detach())
        self._features_rest = Parameter(self._features_rest[~culls].detach())
        self._opacities = Parameter(self._opacities[~culls].detach())
        if self.appearance_embedding_cfg:
            self._appearance_features = Parameter(self._appearance_features[~culls].detach())

        if optimizer is not None:
            param_groups = self.get_gaussian_param_groups()
            remove_from_optim(optimizer, culls, param_groups)

        logging.info(f"Class {self.class_prefix} cull points: {n_bef - self.num_points}")
