import torch
import numpy as np
import torch.nn as nn
import os
import math
from simple_knn._C import distCUDA2
from lib.config import cfg
from lib.utils.sh_utils import RGB2SH
from lib.utils.graphics_utils import BasicPointCloud
from lib.datasets.base_readers import fetchPly
from lib.models.gaussian_model import GaussianModel
from lib.utils.camera_utils import Camera, make_rasterizer
from lib.utils.general_utils import inverse_sigmoid, get_expon_lr_func, quaternion_to_matrix


class GaussianModelGround(GaussianModel):
    def __init__(
        self, 
        model_name='ground', 
        scene_center=np.array([0, 0, 0]),
        scene_radius=20,
        sphere_center=np.array([0, 0, 0]),
        sphere_radius=20,
    ):
        self.scene_center = torch.from_numpy(scene_center).float().cuda()
        self.scene_radius = torch.tensor([scene_radius]).float().cuda()
        self.sphere_center = torch.from_numpy(sphere_center).float().cuda()
        self.sphere_radius = torch.tensor([sphere_radius]).float().cuda()
        num_classes = cfg.data.num_classes if cfg.data.get('use_semantic', False) else 0
        self.background_mask = None
        self.scalar_dict = dict()
        self.tensor_dict = dict()  
        super().__init__(model_name=model_name, num_classes=num_classes)

    def create_from_pcd(self, pcd: BasicPointCloud, spatial_lr_scale: float):
        self.spatial_lr_scale = spatial_lr_scale
        fused_point_cloud = torch.tensor(np.asarray(pcd.points)).float().cuda()
        fused_color = RGB2SH(torch.tensor(np.asarray(pcd.colors)).float().cuda())

        features = torch.zeros((fused_color.shape[0], 3, (self.max_sh_degree + 1) ** 2)).float().cuda()
        features[..., 0] = fused_color
        rots = torch.tensor(pcd.rots).float().cuda() # gs to world, w x y z
        semamtics = torch.zeros((fused_point_cloud.shape[0], self.num_classes), dtype=torch.float, device="cuda")
        print(f"Number of points at initialisation for {self.model_name}: ", fused_point_cloud.shape[0])

        if cfg.data.use_g3r_ground_init:
            scales = torch.log(torch.tensor(np.asarray(pcd.scales))).float().cuda()
            opacities = inverse_sigmoid(torch.tensor(np.asarray(pcd.opacities)).float().cuda())
        else:
            dist2 = torch.clamp_min(distCUDA2(torch.from_numpy(np.asarray(pcd.points)).float().cuda()), 0.0000001)
            ground_z_scale = math.log(0.04)
            scales = torch.log(torch.sqrt(dist2))[..., None].repeat(1, 3)
            scales[scales[:,2] > ground_z_scale, 2] = ground_z_scale
            opacities = inverse_sigmoid(0.1 * torch.ones((fused_point_cloud.shape[0], 1), dtype=torch.float, device="cuda"))

        self._xyz = nn.Parameter(fused_point_cloud.requires_grad_(True))
        self._features_dc = nn.Parameter(features[:, :, 0:1].transpose(1, 2).contiguous().requires_grad_(True))
        self._features_rest = nn.Parameter(features[:, :, 1:].transpose(1, 2).contiguous().requires_grad_(True))
        self._scaling = nn.Parameter(scales.requires_grad_(True))
        self._rotation = nn.Parameter(rots.requires_grad_(True))
        self._opacity = nn.Parameter(opacities.requires_grad_(True))
        self._semantic = nn.Parameter(semamtics.requires_grad_(True))
        self.max_radii2D = torch.zeros((self.get_xyz.shape[0]), device="cuda")

    def set_background_mask(self, camera: Camera):
        pass

    def training_setup(self):
        args = cfg.optim
        self.xyz_gradient_accum = torch.zeros((self.get_xyz.shape[0], 2), device="cuda")
        self.denom = torch.zeros((self.get_xyz.shape[0], 1), device="cuda")
        self.active_sh_degree = 0
                
        l = [
            {'params': [self._xyz], 'lr': args.position_lr_init_grd, "name": "xyz"},
            {'params': [self._features_dc], 'lr': args.feature_lr, "name": "f_dc"},
            {'params': [self._features_rest], 'lr': args.feature_lr / 20.0, "name": "f_rest"},
            {'params': [self._opacity], 'lr': args.opacity_lr, "name": "opacity"},
            {'params': [self._scaling], 'lr': args.scaling_lr, "name": "scaling"},
            {'params': [self._rotation], 'lr': args.rotation_lr, "name": "rotation"},
            {'params': [self._semantic], 'lr': args.semantic_lr, "name": "semantic"}
        ]
        
        self.optimizer = torch.optim.Adam(l, lr=0.0, eps=1e-15)
        self.percent_dense = args.percent_dense
        self.percent_big_ws = args.percent_big_ws

        self.xyz_scheduler_args = get_expon_lr_func(
            lr_init=args.position_lr_init_grd * self.spatial_lr_scale, 
            lr_final=args.position_lr_final_grd * self.spatial_lr_scale, 
            lr_delay_mult=args.position_lr_delay_mult,
            max_steps=args.position_lr_max_steps
        )
        
        self.densify_and_prune_list = ['xyz, f_dc, f_rest, opacity, scaling, rotation, semantic']
        self.training_setup_phase2()
    
    def update_learning_rate(self, iteration):
        ''' Learning rate scheduling per step '''
        for param_group in self.optimizer.param_groups:
            if param_group["name"] == "xyz":
                lr = self.xyz_scheduler_args(iteration)
                param_group['lr'] = lr

    @property
    def get_scaling(self):
        scaling = super().get_scaling
        return scaling if self.background_mask is None else scaling[self.background_mask]

    @property
    def get_rotation(self):
        rotation = super().get_rotation
        return rotation if self.background_mask is None else rotation[self.background_mask]

    @property
    def get_xyz(self):
        xyz = super().get_xyz
        return xyz if self.background_mask is None else xyz[self.background_mask]        
    
    @property
    def get_features(self):
        features = super().get_features
        return features if self.background_mask is None else features[self.background_mask]        
    
    @property
    def get_opacity(self):
        opacity = super().get_opacity
        return opacity if self.background_mask is None else opacity[self.background_mask]
    
    @property
    def get_semantic(self):
        semantic = super().get_semantic
        return semantic if self.background_mask is None else semantic[self.background_mask]

    def densify_and_prune(self, max_grad, min_opacity, prune_big_points, bkgd_index=None, egopose_index=None):
        return self.scalar_dict, self.tensor_dict

    def prune(self, min_opacity, prune_big_points):
        # Prune points below opacity
        extent = self.scene_radius
        prune_mask = (self.get_opacity < min_opacity).squeeze()
        self.scalar_dict['ground_points_below_min_opacity'] = prune_mask.sum().item()

        # Prune big points in world space 
        if prune_big_points:
            big_points_ws = torch.max(self.get_scaling, dim=1).values > extent * self.percent_big_ws
            
            prune_mask = torch.logical_or(prune_mask, big_points_ws)
            
            self.scalar_dict['ground_points_big_ws'] = big_points_ws.sum().item()

        self.scalar_dict['ground_points_total_pruned'] = prune_mask.sum().item()
        self.prune_points(prune_mask)
        
        return self.scalar_dict

    def ground_maxscale_loss(self, size=0.8):
        scales = self.get_scaling
        sx = scales[:, 0]
        sy = scales[:, 1]   
        ground_maxscale_loss = torch.clamp(sx-size,min=0.0).nanmean() + torch.clamp(sy-size,min=0.0).nanmean()
        return ground_maxscale_loss

    def ground_symmetry_loss(self):
        scales, rotations = self.get_scaling, self.get_rotation    
        sx = scales[:, 0]
        sy = scales[:, 1]
        isotropy_loss = torch.abs(sx - sy).mean()
        
        rotations_mat = quaternion_to_matrix(rotations)    
        xy_rotation = rotations_mat[:, :2, :2].contiguous()
        identity = torch.eye(2, device=rotations_mat.device).unsqueeze(0)
        rotation_loss = torch.mean((xy_rotation - identity)**2)
        return isotropy_loss + rotation_loss

    def ground_flatten_loss(self):
        scales, rotations = self.get_scaling, self.get_rotation    
        sz = scales[:, 2]
        
        rotations_mat = quaternion_to_matrix(rotations)    
        # Rotation around x-axis
        roll = torch.atan2(
            rotations_mat[:, 2, 1].contiguous(), 
            rotations_mat[:, 2, 2].contiguous()
        )  
        # Rotation around y-axis
        pitch = torch.atan2(
            -rotations_mat[:, 2, 0].contiguous(), 
            torch.sqrt(rotations_mat[:, 2, 1].contiguous()**2 + rotations_mat[:, 2, 2].contiguous()**2)
        )  
        ground_flatten_loss = abs(sz).nanmean() + abs(roll).nanmean() + abs(pitch).nanmean()
        return ground_flatten_loss

    def ground_regularization_loss(self):
        scales, rotations = self.get_scaling, self.get_rotation  # [N, 3], [N, 4]
        sx, sy, sz = scales[:, 0], scales[:, 1], scales[:, 2]

        # Get rotation matrix once
        R = quaternion_to_matrix(rotations)  # [N, 3, 3]

        # --- Flatten part ---
        z_axis = R[:, :, 2]  # local z-axis
        flatten_loss = z_axis[:, :2].pow(2).sum(dim=-1).mean()       # should be [0, 0]
        upward_loss = (1.0 - z_axis[:, 2]).abs().mean()              # should be 1
        scale_z_loss = sz.abs().mean()                               # suppress vertical elongation
        ground_flatten_loss = flatten_loss + upward_loss + scale_z_loss

        # --- Symmetry part ---
        isotropy_loss = (sx - sy).abs().mean()
        identity = torch.eye(2, device=R.device).unsqueeze(0)
        xy_rot = R[:, :2, :2]
        rotation_sym_loss = ((xy_rot - identity) ** 2).mean()
        ground_symmetry_loss = isotropy_loss + rotation_sym_loss

        return ground_flatten_loss, ground_symmetry_loss