import torch
import torch.nn as nn
import numpy as np
import os
from lib.config import cfg
from lib.utils.graphics_utils import BasicPointCloud
from lib.datasets.base_readers import fetchPly
from lib.models.gaussian_model import GaussianModel
from lib.utils.camera_utils import Camera, make_rasterizer
from lib.utils.general_utils import quaternion_to_matrix, get_expon_lr_func


class GaussianModelBkgd(GaussianModel):
    def __init__(
        self, 
        model_name='background', 
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
        print(f"[INFO] GaussianModelBkgd: scene_center {scene_center}, scene_radius {scene_radius}, " \
              f"sphere_center {sphere_center}, sphere_radius {sphere_radius}")
        super().__init__(model_name=model_name, num_classes=num_classes)

    def create_from_pcd(self, pcd: BasicPointCloud, spatial_lr_scale: float): 
        print(f'Create {self.model_name} model')
        return super().create_from_pcd(pcd, spatial_lr_scale)

    def set_background_mask(self, camera: Camera):
        pass
    
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

    def training_setup(self):
        args = cfg.optim
        self.xyz_gradient_accum = torch.zeros((self.get_xyz.shape[0], 2), device="cuda")
        self.denom = torch.zeros((self.get_xyz.shape[0], 1), device="cuda")
        self.active_sh_degree = 0
                
        l = [
            {'params': [self._xyz], 'lr': args.position_lr_init * self.spatial_lr_scale, "name": "xyz"},
            {'params': [self._features_dc], 'lr': args.feature_lr, "name": "f_dc"},
            {'params': [self._features_rest], 'lr': args.feature_lr / 20.0, "name": "f_rest"},
            {'params': [self._opacity], 'lr': args.opacity_lr, "name": "opacity"},
            {'params': [self._scaling], 'lr': args.scaling_lr, "name": "scaling"},
            {'params': [self._rotation], 'lr': args.rotation_lr, "name": "rotation"},
            {'params': [self._semantic], 'lr': args.semantic_lr, "name": "semantic"},
            {'params': [self._appearance_embeddings], 'lr': 0.01, "name": "appearance_embeddings"},
            {'params': self.appearance_network.parameters(), 'lr': 0.01, "name": "appearance_network"}
        ]
        
        self.optimizer = torch.optim.Adam(l, lr=0.0, eps=1e-15)
        self.percent_dense = args.percent_dense
        self.percent_big_ws = args.percent_big_ws
        
        self.xyz_scheduler_args = get_expon_lr_func(
            lr_init=args.position_lr_init * self.spatial_lr_scale,
            lr_final=args.position_lr_final * self.spatial_lr_scale,
            lr_delay_mult=args.position_lr_delay_mult,
            lr_delay_steps=args.position_lr_delay_steps,
            max_steps=args.position_lr_max_steps
        )
        
        # Custom learning rate scheduler for scaling parameters
        def lr_scaling_lambda(iteration):
            if iteration < args.densify_until_iter:
                return 1.0  # Keep initial scaling_lr
            else:
                return args.scaling_lr_final / args.scaling_lr  # Switch to final after densify_until_iter
        self.scaling_scheduler_args = lambda iter: args.scaling_lr * lr_scaling_lambda(iter)
        
        self.densify_and_prune_list = ['xyz, f_dc, f_rest, opacity, scaling, rotation, semantic']
        self.scalar_dict = dict()
        self.tensor_dict = dict()  

    def update_learning_rate(self, iteration):
        ''' Learning rate scheduling per step '''
        for param_group in self.optimizer.param_groups:
            if param_group["name"] == "xyz":
                lr = self.xyz_scheduler_args(iteration)
                param_group['lr'] = lr
            if param_group["name"] == "scaling":
                lr = self.scaling_scheduler_args(iteration)
                param_group['lr'] = lr

    def densify_and_prune(self, 
            max_grad, min_opacity, prune_big_points, bkgd_index=None, egopose_index=None, if_densify=True):
        self.scalar_dict.clear()
        self.tensor_dict.clear()
        self.scalar_dict['points_total'] = self.get_xyz.shape[0]
        extent = self.scene_radius

        if if_densify:
            max_grad = cfg.optim.get('densify_grad_threshold_bkgd', max_grad)
            if cfg.optim.get('densify_grad_abs_bkgd', False):
                grads = self.xyz_gradient_accum[:, 1:2] / self.denom
            else:
                grads = self.xyz_gradient_accum[:, 0:1] / self.denom
            grads[grads.isnan()] = 0.0

            # Clone and Split
            if bkgd_index != None and egopose_index != None:
                gaussian_means_detached = self.get_xyz.detach().cpu()
                init_lidar_threshold = cfg.optim.get('lambda_background_init_lidar_constraint', [0., 0, 0, 0])[0]
                meter_valid = cfg.optim.get('lambda_background_init_lidar_constraint', [0., 0, 0, 0])[1]
                
                ego_distances, _ = egopose_index.search(gaussian_means_detached, k=1)
                ego_distances = torch.from_numpy(ego_distances)   
                egopose_pts_mask = torch.where(ego_distances <= meter_valid**2, True, False)
                egopose_pts_mask = egopose_pts_mask.squeeze()
                distances, _ = bkgd_index.search(gaussian_means_detached[egopose_pts_mask], k=1)
                distances = torch.from_numpy(distances)
                init_lidar_pts_mask_inrange = torch.where(distances <= init_lidar_threshold**2, True, False)
                init_lidar_pts_mask_inrange = init_lidar_pts_mask_inrange.squeeze()
                init_lidar_pts_mask = torch.ones_like(egopose_pts_mask, dtype=torch.bool)
                init_lidar_pts_mask[egopose_pts_mask] = init_lidar_pts_mask_inrange

                ego_height = cfg.optim.get('lambda_background_init_lidar_constraint', [0., 0, 0, 0])[2]
                if ego_height > 1e-2:
                    ego_height_mask = gaussian_means_detached[:, 2] > ego_height
                    init_lidar_pts_mask = torch.logical_or(init_lidar_pts_mask, ego_height_mask)
                self.densify_and_clone(grads, max_grad, extent, init_lidar_pts_mask=init_lidar_pts_mask)

                init_lidar_pts_mask_after_clone = torch.zeros(self.get_xyz.shape[0], dtype=torch.bool)
                init_lidar_pts_mask_after_clone[:init_lidar_pts_mask.shape[0]] = init_lidar_pts_mask

                self.densify_and_split(grads, max_grad, extent, init_lidar_pts_mask=init_lidar_pts_mask_after_clone)
            else:
                self.densify_and_clone(grads, max_grad, extent, init_lidar_pts_mask=None)
                self.densify_and_split(grads, max_grad, extent, init_lidar_pts_mask=None)

        # Prune points below opacity
        prune_mask = (self.get_opacity < min_opacity).squeeze()
        self.scalar_dict['points_below_min_opacity'] = prune_mask.sum().item()

        big_points_vs = self.max_radii2D > cfg.optim.get('max_screen_size', 250)
        prune_mask = torch.logical_or(prune_mask, big_points_vs)

        # Prune big points in world space 
        if prune_big_points:
            dists = torch.linalg.norm(self.get_xyz - self.sphere_center, dim=1)            
            big_points_ws = torch.max(self.get_scaling, dim=1).values > extent * self.percent_big_ws
            big_points_ws[dists > 2 * self.sphere_radius] = False
            
            prune_mask = torch.logical_or(prune_mask, big_points_ws)
            
            self.scalar_dict['points_big_ws'] = big_points_ws.sum().item()

        self.scalar_dict['points_pruned'] = prune_mask.sum().item()
        self.prune_points(prune_mask)
        
        # Reset 
        self.xyz_gradient_accum = torch.zeros((self.get_xyz.shape[0], 2), device="cuda")
        self.denom = torch.zeros((self.get_xyz.shape[0], 1), device="cuda")
        self.max_radii2D = torch.zeros((self.get_xyz.shape[0]), device="cuda")

        torch.cuda.empty_cache()
        return self.scalar_dict, self.tensor_dict

    def ground_symmetry_loss(self, valid_ground_index=None):
        if valid_ground_index is None:
            return torch.tensor(0.0)
        scales, rotations = self.get_scaling, self.get_rotation    
        sx = scales[valid_ground_index, 0]
        sy = scales[valid_ground_index, 1]
        isotropy_loss = torch.abs(sx - sy).mean()
        
        rotations_mat = quaternion_to_matrix(rotations[valid_ground_index])    
        xy_rotation = rotations_mat[:, :2, :2].contiguous()
        identity = torch.eye(2, device=rotations_mat.device).unsqueeze(0)
        rotation_loss = torch.mean((xy_rotation - identity)**2)
        return isotropy_loss + rotation_loss

    def ground_flatten_loss(self, valid_ground_index=None):
        if valid_ground_index is None:
            return torch.tensor(0.0)
        scales, rotations = self.get_scaling, self.get_rotation    
        
        sz = scales[valid_ground_index, 2]
        rotations_mat = quaternion_to_matrix(rotations[valid_ground_index])    
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
