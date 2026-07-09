from dataclasses import dataclass
from typing import Optional

import torch


@dataclass
class Rays:
    origins: torch.Tensor  # [H, W, 3]
    viewdirs: torch.Tensor  # [H, W, 3]
    direction_norm: torch.Tensor  # [H, W, 1]

    def to(self, device: torch.device):
        self.origins = self.origins.to(device, non_blocking=True)
        self.viewdirs = self.viewdirs.to(device, non_blocking=True)
        self.direction_norm = self.direction_norm.to(device, non_blocking=True)
        return self

    def detach(self):
        return Rays(
            origins=self.origins.detach(),
            viewdirs=self.viewdirs.detach(),
            direction_norm=self.direction_norm.detach(),
        )

    def clone(self):
        return Rays(
            origins=self.origins.clone(),
            viewdirs=self.viewdirs.clone(),
            direction_norm=self.direction_norm.clone(),
        )


@dataclass
class ImageMasks:
    sky_mask: Optional[torch.Tensor] = None
    ground_mask: Optional[torch.Tensor] = None
    dynamic_mask: Optional[torch.Tensor] = None
    human_mask: Optional[torch.Tensor] = None
    vehicle_mask: Optional[torch.Tensor] = None
    egocar_mask: Optional[torch.Tensor] = None
    tfl_mask: Optional[torch.Tensor] = None

    def to(self, device: torch.device):
        if self.sky_mask is not None:
            self.sky_mask = self.sky_mask.to(device, non_blocking=True)
        if self.ground_mask is not None:
            self.ground_mask = self.ground_mask.to(device, non_blocking=True)
        if self.dynamic_mask is not None:
            self.dynamic_mask = self.dynamic_mask.to(device, non_blocking=True)
        if self.human_mask is not None:
            self.human_mask = self.human_mask.to(device, non_blocking=True)
        if self.vehicle_mask is not None:
            self.vehicle_mask = self.vehicle_mask.to(device, non_blocking=True)
        if self.egocar_mask is not None:
            self.egocar_mask = self.egocar_mask.to(device, non_blocking=True)
        if self.tfl_mask is not None:
            self.tfl_mask = self.tfl_mask.to(device, non_blocking=True)
        return self

    def detach(self):
        return ImageMasks(
            sky_mask=self.sky_mask.detach() if self.sky_mask is not None else None,
            ground_mask=self.ground_mask.detach() if self.ground_mask is not None else None,
            dynamic_mask=self.dynamic_mask.detach() if self.dynamic_mask is not None else None,
            human_mask=self.human_mask.detach() if self.human_mask is not None else None,
            vehicle_mask=self.vehicle_mask.detach() if self.vehicle_mask is not None else None,
            egocar_mask=self.egocar_mask.detach() if self.egocar_mask is not None else None,
            tfl_mask=self.tfl_mask.detach() if self.tfl_mask is not None else None,
        )

    def clone(self):
        return ImageMasks(
            sky_mask=self.sky_mask.clone() if self.sky_mask is not None else None,
            ground_mask=self.ground_mask.clone() if self.ground_mask is not None else None,
            dynamic_mask=self.dynamic_mask.clone() if self.dynamic_mask is not None else None,
            human_mask=self.human_mask.clone() if self.human_mask is not None else None,
            vehicle_mask=self.vehicle_mask.clone() if self.vehicle_mask is not None else None,
            egocar_mask=self.egocar_mask.clone() if self.egocar_mask is not None else None,
            tfl_mask=self.tfl_mask.clone() if self.tfl_mask is not None else None,
        )


@dataclass
class ImageInfo:
    rays: Rays

    pixel_coords: torch.Tensor  # [H, W, 2]
    image_index: torch.Tensor
    frame_index: torch.Tensor

    fraction_from_cur_frame: Optional[float] = 0.0 # 仿真中，当前帧超出frame_index多少比例，用于插值计算
    pixels: Optional[torch.Tensor] = None  # [H, W, 3]
    masks: Optional[ImageMasks] = None
    depth_map: Optional[torch.Tensor] = None  # [H, W]
    normalized_time: Optional[torch.Tensor] = None
    from_synthesis: Optional[bool] = False
    
    # 下采样相关属性
    rays_downsample: Optional[Rays] = None
    pixels_downsample: Optional[torch.Tensor] = None  # [H', W', 3]
    masks_downsample: Optional[ImageMasks] = None
    depth_map_downsample: Optional[torch.Tensor] = None  # [H', W']
    pixel_coords_downsample: Optional[torch.Tensor] = None  # [H', W', 2]

    def to(self, device: torch.device):
        self.rays = self.rays.to(device)
        self.pixel_coords = self.pixel_coords.to(device, non_blocking=True)
        self.image_index = self.image_index.to(device)
        self.frame_index = self.frame_index.to(device)

        if self.pixels is not None:
            self.pixels = self.pixels.to(device, non_blocking=True)
        if self.depth_map is not None:
            self.depth_map = self.depth_map.to(device, non_blocking=True)
        if self.masks is not None:
            self.masks = self.masks.to(device)
        if self.normalized_time is not None:
            self.normalized_time = self.normalized_time.to(device, non_blocking=True)
            
        # 处理下采样属性
        if self.rays_downsample is not None:
            self.rays_downsample = self.rays_downsample.to(device)
        if self.pixels_downsample is not None:
            self.pixels_downsample = self.pixels_downsample.to(device, non_blocking=True)
        if self.masks_downsample is not None:
            self.masks_downsample = self.masks_downsample.to(device)
        if self.depth_map_downsample is not None:
            self.depth_map_downsample = self.depth_map_downsample.to(device, non_blocking=True)
        if self.pixel_coords_downsample is not None:
            self.pixel_coords_downsample = self.pixel_coords_downsample.to(device, non_blocking=True)
        return self

    def detach(self):
        rays = self.rays.detach()
        pixel_coords = self.pixel_coords.detach()
        image_index = self.image_index.detach()
        frame_index = self.frame_index.detach()

        new_info = ImageInfo(rays=rays, pixel_coords=pixel_coords, image_index=image_index, frame_index=frame_index)

        if self.pixels is not None:
            new_info.pixels = self.pixels.detach()

        if self.depth_map is not None:
            new_info.depth_map = self.depth_map.detach()

        if self.normalized_time is not None:
            new_info.normalized_time = self.normalized_time.detach()

        if self.masks is not None:
            new_info.masks = self.masks.detach()
            
        # 处理下采样属性
        if self.rays_downsample is not None:
            new_info.rays_downsample = self.rays_downsample.detach()
        if self.pixels_downsample is not None:
            new_info.pixels_downsample = self.pixels_downsample.detach()
        if self.masks_downsample is not None:
            new_info.masks_downsample = self.masks_downsample.detach()
        if self.depth_map_downsample is not None:
            new_info.depth_map_downsample = self.depth_map_downsample.detach()
        if self.pixel_coords_downsample is not None:
            new_info.pixel_coords_downsample = self.pixel_coords_downsample.detach()

        return new_info

    def clone(self):
        new_info = ImageInfo(
            rays=self.rays.clone(),
            pixel_coords=self.pixel_coords.clone(),
            image_index=self.image_index.clone(),
            frame_index=self.frame_index.clone(),
        )

        if self.pixels is not None:
            new_info.pixels = self.pixels.clone()

        if self.depth_map is not None:
            new_info.depth_map = self.depth_map.clone()

        if self.masks is not None:
            new_info.masks = self.masks.clone()

        if self.normalized_time is not None:
            new_info.normalized_time = self.normalized_time.clone()
            
        # 处理下采样属性
        if self.rays_downsample is not None:
            new_info.rays_downsample = self.rays_downsample.clone()
        if self.pixels_downsample is not None:
            new_info.pixels_downsample = self.pixels_downsample.clone()
        if self.masks_downsample is not None:
            new_info.masks_downsample = self.masks_downsample.clone()
        if self.depth_map_downsample is not None:
            new_info.depth_map_downsample = self.depth_map_downsample.clone()
        if self.pixel_coords_downsample is not None:
            new_info.pixel_coords_downsample = self.pixel_coords_downsample.clone()

        return new_info


@dataclass
class CameraInfo:
    intrinsic: torch.Tensor  # [3, 3]
    camera_to_world: torch.Tensor  # [4, 4]

    height: int
    width: int

    camera_id: Optional[int] = None
    camera_name: Optional[str] = None
    ego_to_world: Optional[torch.Tensor] = None  # [4, 4]
    camera_to_ego: Optional[torch.Tensor] = None  # [4, 4]
    intrinsic_noncrop: Optional[torch.Tensor] = None  # [3, 3]
    intrinsic_downsample:Optional[torch.Tensor] = None # [3, 3]

    def to(self, device: torch.device):
        self.intrinsic = self.intrinsic.to(device, non_blocking=True)
        self.camera_to_world = self.camera_to_world.to(device, non_blocking=True)
        if self.ego_to_world is not None:
            self.ego_to_world = self.ego_to_world.to(device, non_blocking=True)
        if self.camera_to_ego is not None:
            self.camera_to_ego = self.camera_to_ego.to(device, non_blocking=True)
        if self.intrinsic_noncrop is not None:
            self.intrinsic_noncrop = self.intrinsic_noncrop.to(device, non_blocking=True)
        if self.intrinsic_downsample is not None:
            self.intrinsic_downsample = self.intrinsic_downsample.to(device, non_blocking=True)
        return self

    def detach(self):
        new_info = CameraInfo(
            intrinsic=self.intrinsic.detach(),
            camera_to_world=self.camera_to_world.detach(),
            height=self.height,
            width=self.width,
            camera_id=self.camera_id,
            camera_name=self.camera_name,
        )
        if self.ego_to_world is not None:
            new_info.ego_to_world = self.ego_to_world.detach()
        if self.camera_to_ego is not None:
            new_info.camera_to_ego = self.camera_to_ego.detach()
        if self.intrinsic_noncrop is not None:
            new_info.intrinsic_noncrop = self.intrinsic_noncrop.detach()
        if self.intrinsic_downsample is not None:
            new_info.intrinsic_downsample = self.intrinsic_downsample.detach()
        return new_info

    def clone(self):
        new_info = CameraInfo(
            intrinsic=self.intrinsic.clone(),
            camera_to_world=self.camera_to_world.clone(),
            height=self.height,
            width=self.width,
            camera_id=self.camera_id,
            camera_name=self.camera_name,
        )

        if self.ego_to_world is not None:
            new_info.ego_to_world = self.ego_to_world.clone()

        if self.camera_to_ego is not None:
            new_info.camera_to_ego = self.camera_to_ego.clone()

        if self.intrinsic_noncrop is not None:
            new_info.intrinsic_noncrop = self.intrinsic_noncrop.clone()
        
        if self.intrinsic_downsample is not None:
            new_info.intrinsic_downsample = self.intrinsic_downsample.clone()
        return new_info