import torch
import numpy as np
import torch.nn as nn
from .basic_modules import ResBlock

def create_rays_from_intrinsic_torch(pose_matric, intrinsic):
    """
    Returns rays in the world coordinate system

    Args:
        pose_matric: (4, 4)
        intrinsic: (6, ), [fx, fy, cx, cy, w, h]
    Returns:
        camera_origin: (3, )
        d: (H, W, 3)
    """
    camera_origin = pose_matric[:3, 3]
    fx, fy, cx, cy, w, h = intrinsic
    ii, jj = torch.meshgrid(torch.arange(w), torch.arange(h), indexing='xy') # attention, indexing is 'xy'
    ii, jj = ii.to(pose_matric), jj.to(pose_matric)
    uu, vv = (ii - cx) / fx, (jj - cy) / fy
    local_xyz = torch.stack([uu, vv, torch.ones_like(uu).to(uu)], dim=-1) # (H, W, 3)

    local_xyz = torch.cat([local_xyz, torch.ones((int(h), int(w), 1)).to(local_xyz)], axis=-1)
    pixel_xyz = torch.einsum('ij, hwj->hwi', pose_matric, local_xyz)[:, :, :3] # (H, W, 3) # ! fix error

    d = (pixel_xyz - camera_origin)
    # normalize the direction
    d = d / torch.norm(d, dim=-1, keepdim=True)

    return camera_origin, d

def to_opengl(ray_d):
    """
    transform the ray direction vector into OpenGL convention (-z is FRONT, +x is RIGHT, +y is UP)
    FLU to RUB

    Attention! The waymo dataset processed by Jiahui is RFU, but the deepmap data and waymo_wds is FLU! 
    The code still works, but the saved panorama/cubemap is rotated.

            z                        y
            |  x (front)             |
            |/                       |
    y <-----o    ===========>>       o----> x  
                                    /
                                 z /   
                                (back)
    Args:
        ray_d : torch.tensor
            shape [*, 3]
    """
    return torch.cat([-ray_d[...,1:2], ray_d[...,2:3], -ray_d[...,0:1]], dim=-1)

def from_opengl(ray_d):
    """
    transform the ray direction vector from OpenGL convention to our convention (+y is front, +x is right, +z is up)
    FLU to RFU

    Attention! The waymo dataset processed by Jiahui is RFU, but the deepmap data and waymo_wds is FLU! 
    The code still works, but the saved panorama/cubemap is rotated.

            z                        y
            |  x (front)             |
            |/                       |
    y <-----o    <<===========       o----> x  
                                    /
                                 z /   
                                (back)
    Args:
        ray_d : torch.tensor
            shape [*, 3]
    """
    return torch.cat([-ray_d[...,2:3], -ray_d[...,0:1], ray_d[...,1:2]], dim=-1)

def world2latlong(xyz):
    """
    https://github.com/yifanlu0227/skylibs/blob/f9bbf0ab30a61a4cb8963a779d379c1b94f022d0/envmap/projections.py#L15C1-L22C16
    Get the (u, v) coordinates of the point defined by (x, y, z) for
    a latitude-longitude map 
    (u, v) coordinates are in the [0, 1] interval.

    (0, 0)--------------------> (u=1)
    |
    |
    v (v=1)
    

    Args:
        xyz: np.ndarray or torch.Tensor, shape [..., 3]. Needs to be OpenGL coordinates
    Returns:
        uv: np.ndarray or torch.Tensor, shape [..., 2]
    """
    if isinstance(xyz, np.ndarray):
        x, y, z = xyz[..., 0], xyz[..., 1], xyz[..., 2]
        u = 1 + (1 / np.pi) * np.arctan2(x, -z)
        v = (1 / np.pi) * np.arccos(y)
        u = u / 2
        return np.stack([u, v], axis=-1)

    elif isinstance(xyz, torch.Tensor):
        x, y, z = xyz[..., 0], xyz[..., 1], xyz[..., 2]
        u = 1 + (1 / np.pi) * torch.atan2(x, -z)
        v = (1 / np.pi) * torch.acos(y) 
        u = u / 2
        return torch.stack([u, v], dim=-1)

    else:
        raise NotImplementedError

def sample_panorama_full_from_camera(pose_matrice, intrinsic, panorama):
    """
    Args:
        pose_matrice : torch.tensor
            camera pose matrix, shape [4, 4]
        
        intrinsic : torch.tensor
            camera intrinsic, shape [6, ]
        
        panorama : torch.tensor
            panorama to sample, shape [H, 2*H, C]

    Returns:
        skybox_color : torch.tensor
            sampled color given pose_matrice and intrinsic, shape [H', W', C]
    """
    camera_origin, ray_d_world = create_rays_from_intrinsic_torch(pose_matrice, intrinsic)
    ray_d_opengl = to_opengl(ray_d_world)
    uv = world2latlong(ray_d_opengl) # [H', W', 2], range in [0, 1]

    # sampling using nn.functional.grid_sample
    panorama = panorama.permute(2, 0, 1).unsqueeze(0).cuda() # [1, C, H, W]
    grid = uv.unsqueeze(0) * 2 - 1 # [1, H', W', 2], range in [-1, 1]

    print("panorama ", panorama.device)
    print("grid ", grid.device)

    skybox_color = nn.functional.grid_sample(panorama, grid, align_corners=True) # [1, C, H', W']

    return skybox_color.squeeze(0).permute(1, 2, 0)


class ResConvHead(nn.Module):
    def __init__(self):
        super().__init__()
        self.n_residual_block = [True, True, False]
        self.n_fitler_list = [32, 16, 16, 3]
        self.n_upsample_list = [False, False, False]
        self.n_downsample_list = [False, False, False]

        self.model = nn.Sequential(
            *[
                ResBlock(
                    channels=self.n_fitler_list[i],
                    out_channels=self.n_fitler_list[i+1],
                    up=self.n_upsample_list[i],
                    down=self.n_downsample_list[i],
                    use_gn=False, 
                ) if self.n_upsample_list[i] else nn.Conv2d(
                    self.n_fitler_list[i],
                    self.n_fitler_list[i+1],
                    kernel_size=3,
                    stride=2 if self.n_downsample_list[i] else 1,
                    padding=1,
                )
                for i in range(len(self.n_fitler_list) - 1)
            ]
        )

    def forward(self, target_2d_feature):
        """
        Args:
            target_2d_feature: torch.Tensor, [B, H, W, C]
        
        Returns:
            torch.Tensor, [B, H, W, C']
        """
        return self.model(target_2d_feature.permute(0,3,1,2)).permute(0,2,3,1)