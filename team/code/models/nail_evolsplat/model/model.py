from __future__ import annotations

import os
import cv2
import math
import numpy as np
from tqdm import tqdm
from einops import rearrange
from omegaconf import OmegaConf
from easydict import EasyDict as edict
from plyfile import PlyData, PlyElement
from dataclasses import dataclass, field
from gsplat.rendering import rasterization
from sklearn.neighbors import NearestNeighbors
from typing import Dict, List, Literal, Optional, Tuple, Type, Union

import torch
from torch import Tensor, nn
from torch.nn import Parameter
import torch.nn.functional as F

from .mlp import MLP
from .embedding import Embedding
from .projection import Projector
from .sparse_conv import sparse_to_dense_volume, SparseCostRegNet, construct_sparse_tensor

import sys
from pathlib import Path
current_dir = os.path.dirname(__file__)
root_path = os.path.abspath(os.path.join(current_dir, "..", ".."))
sys.path.append(root_path)
from nail_evolsplat.utils.cameras import Cameras
from nail_evolsplat.utils.math import inverse_sigmoid, construct_list_of_attributes, get_viewmat, num_sh_bases


def load_model(ckpt_path=None, strict=False, train_mode=False):
    model = EvolSplatModel(train_mode=train_mode)
    loaded_state = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    model_state = {}
    model.load_state_dict(loaded_state, strict=True)
    return model


class EvolSplatModel(nn.Module):
    def __init__(self, train_mode=False):
        self.num_scenes = 1
        self.sh_degree = 1
        self.freeze_volume = False
        self.training = False
        self.enabale_appearance_embedding = False
        self.output_depth_during_training = False
        self.rasterize_mode = "classic"
        self.debug_mode = False
        self.training = train_mode
        self.render_aabb = None  # the box that we want to render - should be a subset of scene_box
        self.collider = None

        super().__init__()
        self.populate_modules()

            
        
    def set_datas_init(self, num_train_data, seed_points, output_folder):
        self.num_train_data = num_train_data
        self.seed_points = seed_points
        self.output_folder = output_folder
        self.init_done = True
        self.means = self.seed_points['points3D_xyz']
        self.anchor_feats = self.seed_points['points3D_rgb'] / 255
        self.offset = torch.zeros_like(self.means)
        distances, _ = self.k_nearest_sklearn(self.means.data, 3)
        distances = torch.from_numpy(distances)
        avg_dist = distances.mean(dim=-1, keepdim=True)
        self.scales = torch.log(avg_dist.repeat(1, 3))
        if self.enabale_appearance_embedding:
            self.embedding_appearance = Embedding(self.num_train_data, self.appearance_embedding_dim)
        else:
            self.embedding_appearance = None

        
        
    def populate_modules(self):
        self.scene_gaussians = None
        self.update_id_counts = None

        self.process_id = 0
        self.local_radius = 1
        self.sparseConv_outdim = 16
        self.offset_max = 0.1
        self.voxel_size = 0.1
        self.num_neibours = 3

        # self.bbx_min = self.means.min(dim=0).values  # [X_min, Y_min, Z_min]
        # self.bbx_max = self.means.max(dim=0).values  # [X_max, Y_max, Z_max]
        self.bbx_min = torch.tensor([-16, -9, -20]).float()
        self.bbx_max = torch.tensor([16, 3.8, 60]).float()
        ## config the projecter
        self.projector = Projector()

         ## construct the sparse tensor
        self.sparse_conv = SparseCostRegNet(d_in=3, d_out=self.sparseConv_outdim).cuda()
        self.feature_dim_out = 3 * num_sh_bases(self.sh_degree)
        self.feature_dim_in = 4 * self.num_neibours*(2*self.local_radius+1)**2

        ## gaussian appearance MLP, predict the SH coefficients
        self.gaussion_decoder = MLP(
                in_dim= self.feature_dim_in+4,
                num_layers=3,
                layer_width=128,
                out_dim=self.feature_dim_out,
                activation=nn.ReLU(),
                out_activation=None,
                implementation="torch",
            )
        
        self.mlp_conv = MLP(
                in_dim= self.sparseConv_outdim+4,
                num_layers=2,
                layer_width=64,
                out_dim=3+4,
                activation=nn.Tanh(),
                out_activation=None,
                implementation="torch",
            )
        
        self.mlp_opacity = MLP(
                in_dim=self.sparseConv_outdim+4,
                num_layers=2,
                layer_width=64,
                out_dim=1,
                activation=nn.ReLU(),
                out_activation=None,
                implementation="torch",
            )
        
        self.mlp_offset = MLP(
                in_dim=self.sparseConv_outdim,
                num_layers=2,
                layer_width=64,
                out_dim=3,
                activation=nn.ReLU(),
                out_activation=nn.Tanh(),
                implementation="torch",
            )

    def get_param_groups(self) -> Dict[str, List[Parameter]]:
        gps = {}
        gps['gaussianDecoder'] = list(self.gaussion_decoder.parameters())
        gps['mlp_conv'] = list(self.mlp_conv.parameters())
        gps['mlp_opacity'] = list(self.mlp_opacity.parameters())
        gps['mlp_offset'] = list(self.mlp_offset.parameters())
        gps['sparse_conv'] = list(self.sparse_conv.parameters())
        return gps
    
    def load_state_dict(self, model_dict, strict=False):
        super().load_state_dict(model_dict, strict= strict)

    def k_nearest_sklearn(self, x: torch.Tensor, k: int):
        x_np = x.cpu().numpy()
        nn_model = NearestNeighbors(n_neighbors=k + 1, algorithm="auto", metric="euclidean").fit(x_np)
        distances, indices = nn_model.kneighbors(x_np)
        return distances[:, 1:].astype(np.float32), indices[:, 1:].astype(np.float32)

    def get_outputs(self, camera: Cameras,batch) -> Dict[str, Union[torch.Tensor, List]]:
        means = self.means.cuda()
        scales = self.scales.cuda()
        offset = self.offset.cuda()
        anchors_feat = self.anchor_feats.cuda()
        
        optimized_camera_to_world = camera.camera_to_worlds
        source_images = batch['source']['image']
        source_images = rearrange(source_images[None,...],"b v h w c -> b v c h w")
        source_extrinsics = batch['source']['extrinsics'] 
        target_image = batch['target']['image'].squeeze(0)
        points_mask_info = batch['points_mask_info']

        ## Query 3D features
        if not self.freeze_volume and self.init_done:
            self.init_done = False
            self.sparse_feat, self.vol_dim, self.valid_coords = construct_sparse_tensor(raw_coords=means.clone(),
                                                                                   feats=anchors_feat,
                                                                                   Bbx_max=self.bbx_max,
                                                                                   Bbx_min=self.bbx_min,
                                                                                   voxel_size=self.voxel_size) 
        if not self.freeze_volume:
            feat_3d = self.sparse_conv(self.sparse_feat)
            dense_volume = sparse_to_dense_volume(sparse_tensor=feat_3d,coords=self.valid_coords,vol_dim=self.vol_dim).unsqueeze(dim=0)
            self.dense_volume = rearrange(dense_volume, 'B H W D C -> B C H W D')
        ## Query 2D features
        sampled_feat,valid_mask,vis_map, visibility_id, project_depth = self.projector.sample_within_window(
                                        xyz = means, 
                                        train_imgs = source_images.squeeze(0),            
                                        train_cameras = source_extrinsics,
                                        train_intrinsics= batch['source']['intrinsics'],
                                        source_depth = batch['source']['depth'],
                                        local_radius=self.local_radius)
        sampled_feat = torch.concat([sampled_feat,vis_map],dim=-1).reshape(-1,self.feature_dim_in)

        valid_mask = valid_mask.reshape(-1, self.feature_dim_in // 4)
        sum_mask = valid_mask[..., :].sum(dim=1)
        projection_mask = sum_mask > self.local_radius**2 + 1
 
        pixel_locations, mask_in_front, project_depth = self.projector.compute_projections(means, batch['target']['extrinsics'],batch['target']['intrinsics'].clone())
        h1, w1 = batch['target']["image"].shape[1:3]
        pixel_locations_int = pixel_locations.round().long().squeeze(0)  # [N,2] float → long
        x_coords = pixel_locations_int[:, 0]
        y_coords = pixel_locations_int[:, 1]
        x_coords = torch.clamp(x_coords, 0, w1-1)
        y_coords = torch.clamp(y_coords, 0, h1-1)
        mask_inbound = self.projector.inbound(pixel_locations, h1, w1)
        mask_rgb_nonblack = (batch['target']["image"].squeeze(0)[y_coords,x_coords,:] != 0.0).any(dim=1)
        ori_mask = mask_in_front*mask_inbound*mask_rgb_nonblack
        projection_mask = ori_mask.squeeze(0)*projection_mask


        num_pointcs = projection_mask.sum()
        means_crop = means[projection_mask]
        sampled_color = sampled_feat[projection_mask]
        vailid_scales = scales[projection_mask]
        last_offset = offset[projection_mask]
        project_depth_crop = project_depth.squeeze(0)[projection_mask]


        dist_near_mask = points_mask_info["near_mask"].to("cuda")[projection_mask]
        dist_mid_mask = points_mask_info["mid_mask"].to("cuda")[projection_mask]
        dist_far_mask = points_mask_info["far_mask"].to("cuda")[projection_mask]

        ## Trilinear the feature volume
        grid_coords = self.get_grid_coords(means_crop + last_offset)
        feat_3d = self.interpolate_features(
            grid_coords=grid_coords, feature_volume=self.dense_volume
        ).permute(3, 4, 1, 0, 2).reshape(-1, self.sparseConv_outdim)

        ## Add the relative direction and distance
        with torch.no_grad():
            ob_view = means_crop - optimized_camera_to_world[0,:3,3]
            ob_dist = ob_view.norm(dim=1, keepdim=True)
            ob_view = ob_view / (ob_dist + 1e-6)

        if self.enabale_appearance_embedding:
            if self.training :
                camera_indicies = torch.ones(num_pointcs, dtype=torch.long, device=ob_dist.device) * camera.metadata['cam_idx']
                embedded_appearance = self.embedding_appearance(camera_indicies)
            else: 
                test_id = torch.ones(num_pointcs, dtype=torch.long, device=ob_dist.device) * camera.metadata['cam_idx']
                embedded_appearance = 0.5 * (self.embedding_appearance(test_id+2) + self.embedding_appearance(test_id - 2))
            input_feature = torch.cat([sampled_color, ob_dist, ob_view, embedded_appearance], dim=-1)
        else:
            input_feature = torch.cat([sampled_color, ob_dist, ob_view], dim=-1)

        sh = self.gaussion_decoder(input_feature)
        if sh.shape[0] == 0:
            print(f"sh.shape[0] == 0")
            return None
        features_dc_crop = sh[:,:3]
        features_rest_crop = sh[:,3:].reshape(num_pointcs,-1,3)

        ## Learn 3D scale, rotation and opacity parameters
        scale_input_feat = torch.cat([feat_3d, ob_dist, ob_view], dim=-1)
        scales_crop, quats_crop = self.mlp_conv(scale_input_feat).split([3,4],dim=-1)
        opacities_crop = self.mlp_opacity(scale_input_feat) 

        ## Optimize the 3D offset via MLP
        offset_crop = self.offset_max * self.mlp_offset(feat_3d)
        means_crop += offset_crop

        ## Update the latest offset for each 3DGS; only save the tensor without grad
        if self.training:
            self.offset[projection_mask] = offset_crop.detach().cpu()  

        colors_crop = torch.cat((features_dc_crop[:, None, :], features_rest_crop), dim=1)
        rgbs = torch.sigmoid(colors_crop[:, 0, :])
        rgbs_255 = rgbs * 255
        rgb_mask = (rgbs_255[:, 0] > 0) & (rgbs_255[:, 1] > 0) & (rgbs_255[:, 2] > 0)
        projection_mask_cpu = projection_mask.cpu()
        rgb_mask_cpu = rgb_mask.cpu()

        ones_indices = (projection_mask_cpu == 1)
        projection_mask_cpu[ones_indices] = rgb_mask_cpu

        viewmat = get_viewmat(optimized_camera_to_world)
        K = batch['target']['intrinsics'][...,:3,:3]
        H, W = target_image.shape[:2]
        self.last_size = (H, W)

        if self.output_depth_during_training or not self.training:
            render_mode = "RGB+ED"
        else:
            render_mode = "RGB"

        delta_scales = torch.tanh(torch.exp(scales_crop))
        old_exp_scales = delta_scales * torch.exp(vailid_scales)
        exp_scales = old_exp_scales
        exp_scales[dist_near_mask] = torch.clamp(old_exp_scales[dist_near_mask], max=0.06)
        exp_scales[dist_mid_mask] = torch.clamp(old_exp_scales[dist_mid_mask], max=0.1)
        exp_scales[dist_far_mask] = torch.clamp(old_exp_scales[dist_far_mask], max=0.2)

        f_rotations = quats_crop / quats_crop.norm(dim=-1, keepdim=True)
        f_opacities = torch.sigmoid(opacities_crop).squeeze(-1)
        render, alpha, info = rasterization(
            means=means_crop,
            quats=f_rotations,
            scales=exp_scales,
            opacities=f_opacities,
            colors=colors_crop,
            viewmats=viewmat,
            Ks=K,
            width=W,
            height=H,
            tile_size=16,
            packed=False,
            near_plane=0.01,
            far_plane=1e10,
            render_mode=render_mode,
            sh_degree=self.sh_degree,
            sparse_grad=False,
            absgrad=True,
            rasterize_mode=self.rasterize_mode,
        )
        alpha = alpha[:, ...][0]
        render_rgb = render[:, ..., :3].squeeze(0)
        if render_mode == "RGB+ED":
            depth_im = render[:, ..., 3:4]
            depth_im = torch.where(alpha > 0, depth_im, depth_im.detach().max()).squeeze(0)
        else:
            depth_im = None
        if not self.training:
            if self.scene_gaussians is None:
                total_num_points = self.means.shape[0]
                self.scene_gaussians = {
                    'means': torch.zeros((total_num_points, 3)),
                    'rotations': torch.zeros((total_num_points, 4)),
                    'colors': torch.zeros((total_num_points, 3)),
                    'scales': torch.zeros((total_num_points, 3)),
                    'opacities': torch.zeros(total_num_points),
                    "sh": torch.zeros((total_num_points, 4, 3)),
                }
                self.update_id_counts = torch.zeros(total_num_points)
                self.seen_counts = torch.zeros(total_num_points)  
                self.obs_count = torch.zeros(total_num_points, dtype=torch.int32)

            curr_cam_type = camera.camera_type[0]
            self.process_id += 1
            final_valid_mask = None
            if curr_cam_type == 2:
                min_depth = 18
                max_depth = 150
                indices = projection_mask.nonzero(as_tuple=True)[0].cpu()  
                if len(indices) != 0:
                    project_depth_crop = project_depth_crop.cpu() 
                    rgb_mask_cpu = rgb_mask_cpu.cpu() 
                    valid_depth_mask = (project_depth_crop >= min_depth) & (project_depth_crop <= max_depth)  
                    valid_color_mask = rgb_mask_cpu  
                    base_valid_mask = valid_depth_mask & valid_color_mask  
                    if base_valid_mask.any():
                        unseen_mask = (self.seen_counts[indices] == 0) & base_valid_mask  
                        closer_mask = (self.seen_counts[indices] > 0) & (project_depth_crop < self.seen_counts[indices]) & base_valid_mask  # [P]
                        final_valid_mask = unseen_mask | closer_mask  
            elif curr_cam_type == 5 or curr_cam_type == 6 :
                min_depth = 0
                max_depth = 150
                indices = projection_mask.nonzero(as_tuple=True)[0].cpu()
                if len(indices) != 0:
                    project_depth_crop = project_depth_crop.cpu()
                    rgb_mask_cpu = rgb_mask_cpu.cpu() 
                    valid_depth_mask = (project_depth_crop >= min_depth) & (project_depth_crop <= max_depth)
                    valid_color_mask = rgb_mask_cpu 
                    base_valid_mask = valid_depth_mask & valid_color_mask 
                    if base_valid_mask.any():
                        unseen_mask = (self.seen_counts[indices] == 0) & base_valid_mask  
                        closer_mask =  base_valid_mask 
                        final_valid_mask = unseen_mask & closer_mask
            else:
                exit("False cam type")
                
            if final_valid_mask is not None:
                final_global_ids = indices[final_valid_mask]
                final_depth = project_depth_crop[final_valid_mask]
                final_local_mask = final_valid_mask
                final_means = means_crop[final_local_mask].detach().clone().cpu()
                final_rotations = f_rotations[final_local_mask].detach().clone().cpu()
                final_colors = rgbs[final_local_mask].detach().clone().cpu()
                final_scales = exp_scales[final_local_mask].detach().clone().cpu()
                final_colors_crop = colors_crop[final_local_mask].detach().clone().cpu()
                final_opacities = f_opacities[final_local_mask].detach().clone().cpu()
                self.scene_gaussians["means"][final_global_ids, :] = final_means
                self.scene_gaussians["rotations"][final_global_ids, :] = final_rotations
                self.scene_gaussians["colors"][final_global_ids, :] = final_colors
                self.scene_gaussians["scales"][final_global_ids, :] = final_scales
                self.scene_gaussians["sh"][final_global_ids, ...] = final_colors_crop
                self.scene_gaussians["opacities"][final_global_ids] = final_opacities
                self.seen_counts[final_global_ids] = final_depth
                self.obs_count[final_global_ids] += 1

            if self.debug_mode:
                render_np = render_rgb.detach().cpu().numpy()
                render_np = (render_np * 255).clip(0, 255).astype(np.uint8)
                render_bgr = cv2.cvtColor(render_np, cv2.COLOR_RGB2BGR)
                save_path = os.path.join(self.output_folder, f"render_{self.process_id:03d}.png")
                cv2.imwrite(save_path, render_bgr)
            if self.process_id == self.num_train_data:
                init_ply_path = os.path.join(self.output_folder, f"evolsplat_init.ply")
                vis_ply_path = os.path.join(self.output_folder, f"evolsplat_vis.ply")
                self.save_ply(init_ply_path, vis_ply_path)
        return {
            "rgb": render_rgb.squeeze(0),
            "depth": depth_im,  
            "accumulation": alpha.squeeze(0),
        }  

    def diturb_pose(self, camera_to_world):
        disturb_cam_x = 0.0
        camera_to_world_rot = camera_to_world[:3, :3]
        diff_camera_xyz = np.array([[disturb_cam_x], [0.0], [0.0]])
        curr_trans = camera_to_world_rot @ diff_camera_xyz
        curr_trans = curr_trans.squeeze(1)
        camera_to_world[:3, 3] += curr_trans
        world_to_cam = np.linalg.inv(camera_to_world)

        pitch_theta = 30.0 / 180.0
        cos_pitch_theta = math.cos(pitch_theta)
        sin_pitch_theta = math.sin(pitch_theta)
        diff_rot = np.array(
            [
                [cos_pitch_theta, 0, -sin_pitch_theta, 0],
                [0, 1, 0, 0],
                [sin_pitch_theta, 0, cos_pitch_theta, 0],
                [0, 0, 0, 1],
            ]
        )
        world_to_cam = diff_rot.dot(world_to_cam)
        camera_to_world = np.linalg.inv(world_to_cam)

        return camera_to_world

    def interpolate_features(self, grid_coords, feature_volume):
        grid_coords = grid_coords[None, None, None, ...]
        feature = F.grid_sample(feature_volume,
                                grid_coords,
                                mode='bilinear',
                                align_corners=True,
                                )
        return feature

    def get_grid_coords(self, position_w, voxel_size=[0.1,0.1,0.1]):
        assert self.voxel_size == voxel_size[0]
        bounding_min = self.bbx_min
        pts = position_w - bounding_min.to(position_w)
        x_index = pts[..., 0] / voxel_size[0]
        y_index = pts[..., 1] / voxel_size[1]
        z_index = pts[..., 2] / voxel_size[2]
        """ Normalize the point coordinates to [-1,1]"""

        dhw = torch.stack([x_index, y_index, z_index], dim=1)
        dhw[..., 0] = dhw[..., 0] / self.vol_dim[0] * 2 - 1
        dhw[..., 1] = dhw[..., 1] / self.vol_dim[1] * 2 - 1
        dhw[..., 2] = dhw[..., 2] / self.vol_dim[2] * 2 - 1
        grid_coords = dhw[..., [2, 1, 0]]
        return grid_coords
    
    @torch.no_grad()
    def init_volume(self):
        ## Foreground
        self.freeze_volume = True
        means = self.means.cuda()
        anchors_feat = self.anchor_feats.cuda()
        sparse_feat, self.vol_dim, self.valid_coords = construct_sparse_tensor(raw_coords=means.clone(),
                                                                               feats=anchors_feat,
                                                                               Bbx_max=self.bbx_max,
                                                                               Bbx_min=self.bbx_min) 

        feat_3d = self.sparse_conv(sparse_feat)
        dense_volume = sparse_to_dense_volume(sparse_tensor=feat_3d,coords=self.valid_coords,vol_dim=self.vol_dim).unsqueeze(dim=0)
        self.dense_volume = rearrange(dense_volume, 'B H W D C -> B C H W D')

        ## Refine locations of3D Gaussian Primitives 
        grid_coords = self.get_grid_coords(means)
        feat_3d = self.interpolate_features(
            grid_coords=grid_coords, feature_volume=self.dense_volume
        ).permute(3, 4, 1, 0, 2).reshape(-1, self.sparseConv_outdim)

        offset_crop = self.offset_max * self.mlp_offset(feat_3d)
        self.offset = offset_crop.detach().cpu()
        return

    @torch.no_grad()
    def save_ply(self, init_ply_path, vis_ply_path):
        N = self.scene_gaussians["means"].shape[0]
        valid_mask = torch.ones(N, dtype=torch.bool, device=self.scene_gaussians["means"].device)
        counts_1d = self.update_id_counts[valid_mask].unsqueeze(-1)

        # For scales and means (assuming (N, 3))
        counts_3d = counts_1d.expand(-1, 3)
        # exp_scales = self.scene_gaussians["scales"][valid_mask] / counts_3d
        exp_scales = self.scene_gaussians["scales"][valid_mask]

        means_crop = self.scene_gaussians["means"][valid_mask] 
        colors_crop = self.scene_gaussians["colors"][valid_mask] 

        # For opacities (assuming (N,))
        # opacities_crop = self.scene_gaussians["opacities"][valid_mask] / counts_1d.squeeze(-1)  # (M,)
        opacities_crop_old = self.scene_gaussians["opacities"][valid_mask]
        # eps=1e-6
        # opacities_safe = torch.clamp(opacities_crop_old, min=eps, max=1 - eps)
        opacities_crop = inverse_sigmoid(opacities_crop_old)

        # For rotations (assuming (N, 4) quaternion)
        counts_rot_4d = counts_1d.expand(-1, 4)
        quats_crop = self.scene_gaussians["rotations"][valid_mask] 
        f_rotations = quats_crop / quats_crop.norm(dim=-1, keepdim=True)

        xyz = means_crop.detach().cpu().numpy()
        normals = np.zeros_like(xyz)

        # save init ply
        dtype = [('px', 'f4'), ('py', 'f4'), ('pz', 'f4'),
                ('nx', 'f4'), ('ny', 'f4'), ('nz', 'f4'),
                ('sx', 'f4'), ('sy', 'f4'), ('sz', 'f4'),
                ('opacity', 'f4'),
                ('red', 'f4'), ('green', 'f4'), ('blue', 'f4'),
                ('qw', 'f4'), ('qx', 'f4'), ('qy', 'f4'), ('qz', 'f4')]
        elements = np.empty(xyz.shape[0], dtype=dtype)
        attributes = np.concatenate((xyz, normals,
                                    exp_scales.detach().cpu().numpy(),
                                    opacities_crop.detach().cpu().numpy().reshape(-1, 1),
                                    colors_crop.detach().cpu().numpy(),
                                    f_rotations.detach().cpu().numpy()), axis=1)
        elements[:] = list(map(tuple, attributes))

        vertex_element = PlyElement.describe(elements, 'vertex')
        ply_data = PlyData([vertex_element])
        ply_data.write(init_ply_path)
        print("finish save init")

        # save vis ply
        fused_color = (colors_crop.detach() - 0.5) / 0.28209479177387814
        max_sh_degree = 1
        features = torch.zeros((fused_color.shape[0], 3, (max_sh_degree + 1) ** 2)).float()
        features[..., 0] = fused_color
        f_dc = features[:, :, 0:1].transpose(1, 2).contiguous()
        f_rest = features[:, :, 1:].transpose(1, 2).contiguous()
        f_dc = f_dc.transpose(1, 2).flatten(start_dim=1).contiguous()
        f_rest = f_rest.transpose(1, 2).flatten(start_dim=1).contiguous()

        opacities = opacities_crop.detach().cpu().numpy()
        opacities = opacities.reshape(-1, 1)
        scales = torch.log(exp_scales).detach().cpu().numpy()
        rotation = f_rotations.detach().cpu().numpy()
        semamtics = np.zeros((xyz.shape[0], 0))

        dtype_full = [(attribute, 'f4') for attribute in construct_list_of_attributes()]
        attributes = np.concatenate((xyz, normals, f_dc, f_rest, opacities, scales, rotation, semamtics), axis=1)

        elements = np.empty(xyz.shape[0], dtype=dtype_full)
        elements[:] = list(map(tuple, attributes))

        plydata = elements
        plydata = PlyElement.describe(plydata, 'vertex')
        plydata_list = [plydata]
        PlyData(plydata_list).write(vis_ply_path)
        print("finish save vis")
        return
