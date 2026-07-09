import os
import cv2
import sys
import time
import math
import enum
import numpy as np
import concurrent.futures
from PIL import Image
from statistics import mean

import gsplat
import torch
import torch.nn as nn
import torch.nn.functional as F
from torchsparse import SparseTensor
from torchmetrics.image import StructuralSimilarityIndexMeasure

current_dir = os.path.dirname(__file__)
root_path = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(root_path)

from g3r.sparse_unet import SparseResUNet
from g3r.utils.math_utils import quaternion_multiply_torch
from g3r.utils.loss_utils import psnr_metric
from g3r.utils.general_utils import save_img_torch, NetMode
from street_gaussians.lib.utils.lpipsPyTorch import lpips


class NeuralGaussiansDecoder(nn.Module):
    def __init__(self, total_latent_dim, explicit_dim, region):
        super().__init__()
        self.region = region
        self.explicit_dim = explicit_dim
        self.mlp = nn.Linear(total_latent_dim, explicit_dim)
        self.tanh = nn.Tanh()
        self.mlp_color = nn.Sequential(
            nn.Linear(3, 3),
            nn.ReLU(),
            nn.Linear(3, 3),
            nn.Sigmoid()
        )
        self.initialize_mlp_color()

        if self.region == "bkgd":
            self.mlp_rotations = nn.Linear(4, 4)  # rotations(4)

    def initialize_mlp_color(self):
        for module in self.mlp_color:
            if isinstance(module, nn.Linear):
                nn.init.normal_(module.weight, mean=0.0, std=0.01)
                if module.bias is not None:
                    if module == self.mlp_color[0]:
                        nn.init.constant_(module.bias, -0.1)
                    else:
                        nn.init.constant_(module.bias, -2.0)
        return

    def forward(self, features, points, rotations, priori_colors, priori_scales):
        initial_attributes = features[:, :self.explicit_dim]
        delta_attributes = self.tanh(self.mlp(features))
        updated_attributes = initial_attributes + delta_attributes

        if self.region == "ground":
            delta_scales_xy = 0.02 * torch.sigmoid(updated_attributes[:, 0:2])
            delta_scales_z = 0.01 * torch.sigmoid(updated_attributes[:, 2])
            delta_scales_z = delta_scales_z.unsqueeze(1)
            delta_scales = torch.cat([delta_scales_xy, delta_scales_z], dim=1)
            scales = delta_scales + priori_scales

        elif self.region == "bkgd":
            scales = torch.sigmoid(updated_attributes[:, 0:3]) * 0.1
            # scales = scales.clamp(min = 0.001, max = 0.15)
            delta_rotations = self.mlp_rotations(updated_attributes[:, 7:11])
            pred_rotations = F.normalize(delta_rotations, p=2, dim=-1)
            rotations = quaternion_multiply_torch(pred_rotations, rotations)

        opacities = torch.sigmoid(updated_attributes[:, 3])
        colors = self.mlp_color(updated_attributes[:, 4:7]) + priori_colors
        return {"means": points, "scales": scales, "rotations": rotations, "opacities": opacities, "colors": colors}


class G3RReconstructor(nn.Module):
    def __init__(self, cfg, log_folder):
        super().__init__()
        self.cfg = cfg
        self.decoder = NeuralGaussiansDecoder(cfg['total_latent_dim'], cfg['explicit_dim'], cfg["region"])
        self.g3r_net = SparseResUNet(
            stem_channels=32,
            time_embedding_channels=32,
            encoder_channels=[64, 128, 256, 512],
            decoder_channels=[256, 128, 64, cfg['total_latent_dim']],
            in_channels=cfg['total_latent_dim'] * 2,
            width_multiplier=1.0
        )
        self.net_mode = NetMode.TRAIN
        self.log_folder = log_folder
        self.optimizer = torch.optim.Adam(self.parameters(), lr=self.cfg['lr'])
        self.scheduler = torch.optim.lr_scheduler.ExponentialLR(self.optimizer, gamma=self.cfg['scheduler_gamma'])
        self.ssim_metric = StructuralSimilarityIndexMeasure(data_range=1.0).to(self.cfg['device'])
        self.global_step = 0

    def set_netmode(self, net_mode):
        self.net_mode = net_mode

    def to(self, device):
        super().to(device)
        return self

    def initialize_neural_gaussians(self, points):
        num_points = points.shape[0]
        device = self.cfg['device']
        points = points.to(device)

        priori_xyz = points[:, :3]
        priori_rotations = points[:, 3:7]
        priori_colors = points[:, 7:10]
        priori_scales = points[:, 10:13]
        input_opacities = points[:, 13].unsqueeze(1)

        delta_colors = torch.full((num_points, 3), 0, device=device)
        delta_scales = torch.full((num_points, 3), 0, device=device)
        latent = torch.randn(num_points, self.cfg['latent_dim_only'], device=device)

        if self.cfg['region'] == "ground":
            other_dims = torch.cat([delta_scales, input_opacities, delta_colors, latent], dim=1)
        elif self.cfg['region'] == "bkgd":
            delta_rotations = torch.full((num_points, 4), 0, device=device)
            delta_rotations[:, 0] = 1
            other_dims = torch.cat([delta_scales, input_opacities, delta_colors, delta_rotations, latent], dim=1)
        return priori_xyz, priori_rotations, priori_colors, priori_scales, other_dims

    def compute_loss(self, gaussians, cameras_info, view_ids, t_step=None):
        gt_images_stack = cameras_info["images"][view_ids, ...].cuda()
        view_matrix_stack = cameras_info["extrinsics"][view_ids, ...].cuda()
        intrinsic_stack = cameras_info["intrinsics"][view_ids, ...].cuda()
        view_list = view_ids.tolist()
        timestamps = [cameras_info["timestamps"][i] for i in view_list]

        width = gt_images_stack[0].shape[2]
        height = gt_images_stack[0].shape[1]
        packed_status = False
        if self.net_mode == NetMode.TRAIN:
            packed_status = True

        rendered_images, _, _ = gsplat.rasterization(
            means=gaussians['means'],
            quats=gaussians['rotations'],  # w x y z
            scales=gaussians['scales'],
            opacities=gaussians['opacities'],
            colors=gaussians['colors'],
            viewmats=view_matrix_stack,
            Ks=intrinsic_stack,
            width=width,
            height=height,
            near_plane=0.01,
            far_plane=1e10,
            sparse_grad=packed_status,
            rasterize_mode="antialiased",
            absgrad=True,
            packed=packed_status
        )

        rendered_images = rendered_images.permute(0, 3, 1, 2)
        mask = (gt_images_stack == 0).all(dim = 1)
        mask = mask.unsqueeze(1).expand_as(rendered_images)
        rendered_images[mask] = 0
        self.save_debug_img(t_step, rendered_images, gt_images_stack, timestamps)

        max_scales, _ = torch.max(gaussians['scales'], dim=-1)
        mse_loss = F.mse_loss(rendered_images, gt_images_stack)
        lpips_loss = lpips(rendered_images, gt_images_stack, net_type='alex')
        images_num = rendered_images.shape[0]
        total_loss = images_num * (self.cfg['lambda_mse'] * mse_loss) + self.cfg["lambda_lpips"] * lpips_loss +\
                     self.cfg['lambda_reg'] * F.relu(max_scales - self.cfg['reg_epsilon']).mean()

        psnr = psnr_metric(rendered_images, gt_images_stack, ~mask)
        del rendered_images, mask
        return total_loss, lpips_loss, psnr

    def save_debug_img(self, t_step, rendered_images, gt_images, timestamps):
        if self.log_folder is not None and self.global_step % self.cfg["save_img_step"] == 0 and \
            t_step == self.cfg['T_iterations'] - 1:
            for img_id in range(0, rendered_images.shape[0], self.cfg["save_img_id"]):
                save_path = os.path.join(self.log_folder, f"{self.global_step}_{timestamps[img_id]}_{t_step}.png")
                curr_render_img = rendered_images[img_id, ...]
                curr_gt_img = gt_images[img_id, ...]
                save_img_torch(curr_gt_img, curr_render_img, save_path)
        return

    def compute_gradient_feedback(self, features, cameras_info, src_view_ids, points, rotations, colors, scales):
        features_for_grad = features.clone().requires_grad_(True)
        gaussians = self.decoder(features_for_grad, points, rotations, colors, scales)
        step_loss, lpips, psnr = self.compute_loss(gaussians, cameras_info, src_view_ids, t_step=None)

        grad = torch.autograd.grad(outputs=step_loss, inputs=features_for_grad)[0]
        max_abs = torch.max(torch.abs(grad), dim=1, keepdim=True)[0] + 1e-8
        grad_norm = grad / max_abs

        del features_for_grad
        return grad_norm

    def forward(self, input_points, coords, cameras_info, gammas):
        data_length = len(cameras_info["timestamps"])
        src_view_ids = torch.randperm(data_length)[:self.cfg['num_src_views_train']]
        total_view_ids = torch.arange(data_length)
        points, rotations, priori_colors, priori_scales, S_t_detached = self.initialize_neural_gaussians(input_points)
        coords = coords.to(self.cfg['device'])

        psnr_list = []
        lpips_list = []
        loss_list = []
        for t_step in range(self.cfg['T_iterations']):
            self.optimizer.zero_grad()

            grad_S_t = self.compute_gradient_feedback(S_t_detached, cameras_info, src_view_ids, points, rotations, priori_colors, priori_scales)
            x_in = torch.cat([S_t_detached, grad_S_t], dim=-1)
            sparse_in = SparseTensor(feats=x_in, coords=coords)
            update_list = self.g3r_net(sparse_in, torch.tensor([t_step], dtype=self.cfg["data_type"], device=self.cfg['device']))
            update = update_list[-1]

            S_updated_feats = S_t_detached + gammas[t_step] * update.feats
            current_gaussians = self.decoder(S_updated_feats, points, rotations, priori_colors, priori_scales)

            step_loss, lpips, psnr = self.compute_loss(current_gaussians, cameras_info, total_view_ids, t_step)
            step_loss.backward()
            self.optimizer.step()

            S_t_detached = S_updated_feats.detach()
            del S_updated_feats

            psnr_list.append(psnr.item())
            lpips_list.append(lpips.item())
            loss_list.append(step_loss.item())

        self.global_step += 1
        self.scheduler.step()
        return {'loss_mean': mean(loss_list), 'loss_last': loss_list[-1], 
                'lpips_mean': mean(lpips_list),'lpips_last': lpips_list[-1],
                'psnr_mean': mean(psnr_list),'psnr_last': psnr_list[-1]}

    @property
    def get_step(self):
        return self.global_step