import os
import torch
import numpy as np
import torch.nn as nn
import torch.nn.functional as F


class Projector():
    def __init__(self):
        return
    
    def inbound(self, pixel_locations, h, w):
        return (pixel_locations[..., 0] <=(w - 1.)) & \
               (pixel_locations[..., 0] >= 0) & \
               (pixel_locations[..., 1] <= h - 1.) &\
               (pixel_locations[..., 1] >= 0)

    def normalize(self, pixel_locations, h, w):
        resize_factor = torch.tensor([w-1., h-1.]).to(pixel_locations.device)[None, None, :]
        normalized_pixel_locations = 2 * pixel_locations / resize_factor - 1.
        return normalized_pixel_locations

    def compute_projections(self, xyz, train_cameras,train_intrinsics):
        original_shape = xyz.shape[:1]
        xyz = xyz.reshape(-1, 3)
        num_views = len(train_cameras)
        train_cameras = train_cameras * torch.tensor([1, -1, -1, 1],device="cuda")
        train_poses = train_cameras.reshape(-1, 4, 4)

        xyz_h = torch.cat([xyz, torch.ones_like(xyz[..., :1])], dim=-1)
        projections = train_intrinsics.bmm(torch.inverse(train_poses)) \
            .bmm(xyz_h.t()[None, ...].repeat(num_views, 1, 1))
        projections = projections.permute(0, 2, 1)
        pixel_locations = projections[..., :2] / torch.clamp(projections[..., 2:3], min=1e-8)
        pixel_locations = torch.clamp(pixel_locations, min=-1e6, max=1e6)

        min_depth = 0
        max_depth = 100000000
        mask = (projections[..., 2] > min_depth) & (projections[..., 2] < max_depth)
        mask_reshape = mask.reshape((num_views, ) + original_shape)
        depth = projections[..., 2].reshape((num_views, ) + original_shape)

        return pixel_locations.reshape((num_views, ) + original_shape + (2, )), \
               mask_reshape,\
               depth
    
    def compute(self,  xyz, train_imgs, train_cameras, train_intrinsics):
        xyz = xyz.detach()
        h, w = train_imgs.shape[2:]

        # compute the projection of the query points to each reference image
        pixel_locations, mask_in_front, _ = self.compute_projections(xyz, train_cameras,train_intrinsics.clone())
        normalized_pixel_locations = self.normalize(pixel_locations, h, w)
        normalized_pixel_locations = normalized_pixel_locations.unsqueeze(dim=1)

        # rgb sampling
        rgbs_sampled = F.grid_sample(train_imgs, normalized_pixel_locations, align_corners=False)
        rgb_sampled = rgbs_sampled.permute(2, 3, 0, 1).squeeze(dim=0)

        # mask
        inbound = self.inbound(pixel_locations, h, w)
        mask = (inbound * mask_in_front).float().permute(1, 0)[..., None]
        rgb = rgb_sampled.masked_fill(mask==0, 0)

        projection_mask = mask[..., :].sum(dim=1) > 0
        return rgb[projection_mask.squeeze()], projection_mask.squeeze()

    def sample_within_window(self, xyz, train_imgs, train_cameras, train_intrinsics, source_depth=None, local_radius = 2):
        n_views, _ ,_ = train_cameras.shape
        n_samples = xyz.shape[0]
        
        local_h = 2 * local_radius + 1
        local_w = 2 * local_radius + 1
        window_grid = self.generate_window_grid(-local_radius, local_radius,
                                                -local_radius, local_radius,
                                                local_h, local_w, device=xyz.device)  # [2R+1, 2R+1, 2]
        window_grid = window_grid.reshape(-1, 2).repeat(n_views, 1, 1)

        xyz = xyz.detach()
        h, w = train_imgs.shape[2:]

        # sample within the window size
        pixel_locations, mask_in_front, project_depth = self.compute_projections(xyz, train_cameras,train_intrinsics.clone())

        ## Occlusion-Aware check for IBR:
        if source_depth is not None:
            source_depth = source_depth.unsqueeze(-1).permute(0, 3, 1, 2).cuda()
            depths_sampled = F.grid_sample(source_depth, self.normalize(pixel_locations, h, w).unsqueeze(dim=1), align_corners=False)
            depths_sampled = depths_sampled.squeeze()
            retrived_depth = depths_sampled.masked_fill(mask_in_front==0, 0)
            projected_depth = project_depth*mask_in_front

            """Use depth priors to distinguish the Occlusion Region"""
            visibility_map = projected_depth - retrived_depth
            visibility_id = (visibility_map < 10) & (visibility_map > -10)
            visibility_map = visibility_map.unsqueeze(-1).repeat(1,1, local_h*local_w).reshape(n_views,n_samples,-1)
        else:
            visibility_map = torch.ones_like(project_depth)

        pixel_locations = pixel_locations.unsqueeze(dim=2) + window_grid.unsqueeze(dim=1)
        pixel_locations = pixel_locations.reshape(n_views,-1,2)  ## [N_view, N_points,2]

        ## boardcasting the mask
        mask_in_front = mask_in_front.unsqueeze(-1).repeat(1,1, local_h*local_w).reshape(n_views,-1)
        normalized_pixel_locations = self.normalize(pixel_locations, h, w)   # [n_views, n_points, 2]
        normalized_pixel_locations = normalized_pixel_locations.unsqueeze(dim=1) # [n_views, 1, n_points, 2]
        visibility_id = visibility_id.unsqueeze(-1).repeat(1,1, local_h*local_w).reshape(n_views,-1)

        # rgb sampling
        rgbs_sampled = F.grid_sample(train_imgs, normalized_pixel_locations, align_corners=False)
        rgb_sampled = rgbs_sampled.permute(2, 3, 0, 1).squeeze(dim=0)  # [n_points, n_views, 3]

        # mask
        inbound = self.inbound(pixel_locations, h, w)
        mask = (inbound * mask_in_front * visibility_id).float().permute(1, 0)[..., None]  
        rgb = rgb_sampled.masked_fill(mask==0, 0)

        return rgb.reshape(n_samples,n_views,local_w*local_h,3), \
                mask.reshape(n_samples,n_views,local_w*local_h),\
                visibility_map.permute(1,0,2).unsqueeze(-1), visibility_id, project_depth[0, ...]

    def generate_window_grid(self, h_min, h_max, w_min, w_max, len_h, len_w, device=None):
        assert device is not None

        x, y = torch.meshgrid([torch.linspace(w_min, w_max, len_w, device=device),
                            torch.linspace(h_min, h_max, len_h, device=device)],
                            )
        grid = torch.stack((x, y), -1).transpose(0, 1).float()  # [H, W, 2]

        return grid










