import abc
import logging
import os
import random
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np
import torch
from omegaconf import OmegaConf
from PIL import Image
from torch import Generator, Tensor

from ..dataset_meta import DATASETS_CONFIG
from .data_proto import CameraInfo, ImageInfo, ImageMasks, Rays
from .utils import get_rays
from ...utils.camera import get_camera_original_size_by_vehicle_model
import json

logger = logging.getLogger()


def idx_to_3d(idx, H, W):
    """
    Converts a 1D index to a 3D index (img_id, row_id, col_id)

    Args:
        idx (int): The 1D index to convert.
        H (int): The height of the 3D space.
        W (int): The width of the 3D space.

    Returns:
        tuple: A tuple containing the 3D index (i, j, k),
                where i is the image index, j is the row index,
                and k is the column index.
    """
    i = idx // (H * W)
    j = (idx % (H * W)) // W
    k = idx % W
    return i, j, k


def sparse_lidar_map_downsampler(lidar_depth_map, downscale_factor):
    raw_avg = (
        torch.nn.functional.interpolate(
            lidar_depth_map.unsqueeze(0).unsqueeze(0),
            scale_factor=downscale_factor,
            mode="area",
        )
        .squeeze(0)
        .squeeze(0)
    )
    raw_mask = (
        torch.nn.functional.interpolate(
            (lidar_depth_map > 1e-3).float().unsqueeze(0).unsqueeze(0),
            scale_factor=downscale_factor,
            mode="area",
        )
        .squeeze(0)
        .squeeze(0)
    )
    downsampled_lidar_map = torch.zeros_like(raw_avg)
    downsampled_lidar_map[raw_mask > 0] = raw_avg[raw_mask > 0] / raw_mask[raw_mask > 0]
    return downsampled_lidar_map


class CameraData(object):
    def __init__(
        self,
        dataset_name: str,
        data_path: str,
        cam_id: int,
        # the start timestep to load
        start_timestep: int = 0,
        # the end timestep to load
        end_timestep: int = None,
        # whether to load the dynamic masks
        load_dynamic_mask: bool = False,
        # whether to load the ground masks
        load_ground_mask: bool = False,
        # whether to load the sky masks
        load_sky_mask: bool = False,
        # whether to load the tfl masks
        load_tfl_mask: bool = False,
        # whether to load the projected lidar depths
        load_projected_lidar_depth: bool = False,
        # the size to load the images
        downscale_when_loading: float = 1.0,
        # whether to undistort the images
        undistort: bool = False,
        # whether to use buffer sampling
        buffer_downscale: float = 1.0,
        # the device to move the camera to
        device: torch.device = torch.device("cpu"),
        # the data source to load
        data_source: str = 'lidar'
    ):
        self.difix_downsample = 1.0
        self.dataset_name = dataset_name
        self.cam_id = cam_id
        self.data_path = data_path
        self.start_timestep = start_timestep
        self.end_timestep = end_timestep
        self.undistort = undistort
        self.buffer_downscale = buffer_downscale
        self.device = device
        self.ego_to_worlds = None
        self.cam_to_ego = None
        self.distortions = None
        self.data_source = data_source
        self.cam_name = DATASETS_CONFIG[dataset_name][cam_id]["camera_name"]
        meta_json = json.load(open(os.path.join(self.data_path, "metadata.json"), "r"))
        self.vehicle_model = meta_json.get("vehicle_model", None)
        self.original_size = get_camera_original_size_by_vehicle_model(dataset_name, cam_id, self.vehicle_model)
        self.load_size = [
            int(self.original_size[0] / downscale_when_loading),
            int(self.original_size[1] / downscale_when_loading),
        ]
        self.lidar_depth_maps = None
        self.load_dynamic_mask = load_dynamic_mask
        self.load_ground_mask = load_ground_mask
        self.load_sky_mask = load_sky_mask
        self.load_tfl_mask = load_tfl_mask
        self.load_projected_lidar_depth = load_projected_lidar_depth

        # Load all file paths and calibrations
        self.create_all_filelist()
        self.load_calibrations()
        self.load_egocar_mask()
        self.dynamic_masks = None

        self.image_error_maps = None  # will be built by: self.build_image_error_buffer()
        self.to(self.device)
        self.downscale_factor = 1.0

    @property
    def num_frames(self) -> int:
        return self.cam_to_worlds.shape[0]

    @property
    def HEIGHT(self) -> int:
        return self.load_size[0]

    @property
    def WIDTH(self) -> int:
        return self.load_size[1]

    def __len__(self):
        return self.num_frames

    def set_downscale_factor(self, downscale_factor: float):
        self.downscale_factor = downscale_factor

    def set_difix_downsample(self, difix_downsample: float):
        self.difix_downsample = difix_downsample

    def set_unique_ids(self, unique_cam_idx: int, unique_img_idx: Tensor):
        """
        unique id is the compact order of the camera index and frame index
        for example camera idx is [0, 2, 4]
        the camera index is [0, 1, 2]
        """
        self.unique_cam_idx = unique_cam_idx
        self.unique_img_idx = unique_img_idx.to(self.device)

    def load_calibrations(self):
        raise NotImplementedError

    def load_ground_mask_by_frame_idx(self, frame_idx: int):
        raise NotImplementedError

    def load_projected_lidar_depth_by_frame_idx(self, frame_idx: int):
        raise NotImplementedError

    def load_downsample_cam_info(self):
        raise NotImplementedError

    def create_all_filelist(self):
        """
        Create file lists for all data files.
        e.g., img files, feature files, etc.
        """
        # ---- define filepaths ---- #
        img_filepaths = []
        dynamic_mask_filepaths, sky_mask_filepaths = [], []
        human_mask_filepaths, vehicle_mask_filepaths = [], []

        fine_mask_path = os.path.join(self.data_path, "fine_dynamic_masks")
        if os.path.exists(fine_mask_path):
            dynamic_mask_dir = "fine_dynamic_masks"
            logger.info("Using fine dynamic masks")
        else:
            dynamic_mask_dir = "dynamic_masks"
            logger.info("Using coarse dynamic masks")

        # Note: we assume all the files in waymo dataset are synchronized
        for t in range(self.start_timestep, self.end_timestep):
            img_filepaths.append(os.path.join(self.data_path, "images", f"{t:03d}_{self.cam_id}.jpg"))
            dynamic_mask_filepaths.append(
                os.path.join(
                    self.data_path,
                    dynamic_mask_dir,
                    "all",
                    f"{t:03d}_{self.cam_id}.png",
                )
            )
            human_mask_filepaths.append(
                os.path.join(
                    self.data_path,
                    dynamic_mask_dir,
                    "human",
                    f"{t:03d}_{self.cam_id}.png",
                )
            )
            vehicle_mask_filepaths.append(
                os.path.join(
                    self.data_path,
                    dynamic_mask_dir,
                    "vehicle",
                    f"{t:03d}_{self.cam_id}.png",
                )
            )
            sky_mask_filepaths.append(os.path.join(self.data_path, "sky_masks", f"{t:03d}_{self.cam_id}.png"))
        self.img_filepaths = np.array(img_filepaths)
        self.dynamic_mask_filepaths = np.array(dynamic_mask_filepaths)
        self.human_mask_filepaths = np.array(human_mask_filepaths)
        self.vehicle_mask_filepaths = np.array(vehicle_mask_filepaths)
        self.sky_mask_filepaths = np.array(sky_mask_filepaths)

    def load_image_by_frame_idx(self, frame_idx: int):
        fname = self.img_filepaths[frame_idx]
        rgb = Image.open(fname).convert("RGB")
        # resize them to the load_size
        if self.load_size[0] != rgb.size[1] or self.load_size[1] != rgb.size[0]:
            rgb = rgb.resize((self.load_size[1], self.load_size[0]), Image.BILINEAR)
        # undistort the images
        if self.undistort:
            rgb = cv2.undistort(
                np.array(rgb),
                self.intrinsics[frame_idx].numpy(),
                self.distortions[frame_idx].numpy(),
            )
        # normalize the images to [0, 1]
        return torch.from_numpy(np.array(rgb)) / 255.0

    def load_egocar_mask(self):
        """
        Since in some datasets, the ego car body is visible in the images,
        we need to load the ego car mask to mask out the ego car body.
        """
        egocar_mask = os.path.join("data", "ego_masks", self.dataset_name, f"{self.cam_id}.png")
        if os.path.exists(egocar_mask):
            egocar_mask = Image.open(egocar_mask).convert("L")
            # resize them to the load_size
            egocar_mask = egocar_mask.resize((self.load_size[1], self.load_size[0]), Image.BILINEAR)
            if self.undistort:
                egocar_mask = cv2.undistort(
                    np.array(egocar_mask),
                    self.intrinsics[0].numpy(),
                    self.distortions[0].numpy(),
                )
            self.egocar_mask = torch.from_numpy(np.array(egocar_mask) > 0).bool()
        else:
            self.egocar_mask = None

    def load_dynamic_mask_by_frame_idx(self, frame_idx: int):
        fname = self.dynamic_mask_filepaths[frame_idx]
        dynamic_mask = Image.open(fname).convert("L")
        # resize them to the load_size
        if self.load_size[0] != dynamic_mask.size[1] or self.load_size[1] != dynamic_mask.size[0]:
            dynamic_mask = dynamic_mask.resize((self.load_size[1], self.load_size[0]), Image.BILINEAR)
        if self.undistort:
            dynamic_mask = cv2.undistort(
                np.array(dynamic_mask),
                self.intrinsics[frame_idx].numpy(),
                self.distortions[frame_idx].numpy(),
            )
        dynamic_mask = torch.from_numpy(np.array(dynamic_mask) > 0).bool()

        fname = self.human_mask_filepaths[frame_idx]
        human_mask = Image.open(fname).convert("L")
        # resize them to the load_size
        if self.load_size[0] != human_mask.size[1] or self.load_size[1] != human_mask.size[0]:
            human_mask = human_mask.resize((self.load_size[1], self.load_size[0]), Image.BILINEAR)
        if self.undistort:
            human_mask = cv2.undistort(
                np.array(human_mask),
                self.intrinsics[frame_idx].numpy(),
                self.distortions[frame_idx].numpy(),
            )
        human_mask = torch.from_numpy(np.array(human_mask) > 0).bool()

        fname = self.vehicle_mask_filepaths[frame_idx]
        vehicle_mask = Image.open(fname).convert("L")
        # resize them to the load_size
        if self.load_size[0] != vehicle_mask.size[1] or self.load_size[1] != vehicle_mask.size[0]:
            vehicle_mask = vehicle_mask.resize((self.load_size[1], self.load_size[0]), Image.BILINEAR)
        if self.undistort:
            vehicle_mask = cv2.undistort(
                np.array(vehicle_mask),
                self.intrinsics[frame_idx].numpy(),
                self.distortions[frame_idx].numpy(),
            )
        vehicle_mask = torch.from_numpy(np.array(vehicle_mask) > 0).bool()

        return dynamic_mask, human_mask, vehicle_mask

    def load_sky_mask_by_frame_idx(self, frame_idx: int):
        fname = self.sky_mask_filepaths[frame_idx]
        sky_mask = Image.open(fname).convert("L")
        # resize them to the load_size
        if self.load_size[0] != sky_mask.size[1] or self.load_size[1] != sky_mask.size[0]:
            sky_mask = sky_mask.resize((self.load_size[1], self.load_size[0]), Image.NEAREST)
        if self.undistort:
            sky_mask = cv2.undistort(
                np.array(sky_mask),
                self.intrinsics[frame_idx].numpy(),
                self.distortions[frame_idx].numpy(),
            )
        sky_mask = torch.from_numpy(np.array(sky_mask) > 0).bool()
        return sky_mask

    def load_tfl_mask_by_frame_idx(self, frame_idx: int):
        raise NotImplementedError

    def load_depth(
        self,
        lidar_depth_maps: Tensor,
    ):
        self.lidar_depth_maps = lidar_depth_maps.to(self.device)

    def load_time(
        self,
        normalized_time: Tensor,
    ):
        self.normalized_time = normalized_time.to(self.device)

    def build_image_error_buffer(self) -> None:
        """
        Build the image error buffer.
        """
        # Tensor (num_frames, H // buffer_downscale, W // buffer_downscale)
        self.image_error_maps = torch.ones(
            (
                self.num_frames,
                self.HEIGHT // self.buffer_downscale,
                self.WIDTH // self.buffer_downscale,
            ),
            dtype=torch.float32,
            device=self.device,
        )

    def get_image_error_video(self) -> List[np.ndarray]:
        """
        Get the pixel sample weights video.
        Returns:
            frames: the pixel sample weights video.
                shape: (num_frames, H, W, 3)
        """
        # normalize the image error buffer to [0, 1]
        image_error_maps = (self.image_error_maps - self.image_error_maps.min()) / (
            self.image_error_maps.max() - self.image_error_maps.min()
        )

        maps = []
        loss_maps = (
            image_error_maps.detach()
            .cpu()
            .numpy()
            .reshape(
                self.num_frames,
                self.HEIGHT // self.buffer_downscale,
                self.WIDTH // self.buffer_downscale,
            )
        )
        for i in range(self.num_frames):
            maps.append(loss_maps[i])
        return maps

    def update_image_error_maps(self, render_results: Dict[str, Tensor]) -> None:
        """
        Update the image error buffer with the given render results.
        """
        gt_rgbs = render_results["gt_rgbs"]
        pred_rgbs = render_results["rgbs"]
        gt_rgbs = torch.from_numpy(np.stack(gt_rgbs, axis=0))
        pred_rgbs = torch.from_numpy(np.stack(pred_rgbs, axis=0))
        image_error_maps = torch.abs(gt_rgbs - pred_rgbs).mean(dim=-1)
        assert image_error_maps.shape == self.image_error_maps.shape
        if "Dynamic_opacities" in render_results:
            if len(render_results["Dynamic_opacities"]) > 0:
                dynamic_opacity = render_results["Dynamic_opacities"]
                dynamic_opacity = torch.from_numpy(np.stack(dynamic_opacity, axis=0))
                # we prioritize the dynamic objects by multiplying the error by 5
                image_error_maps[dynamic_opacity > 0.1] *= 5
        # update the image error buffer
        self.image_error_maps: Tensor = image_error_maps.to(self.device)
        logger.info(f"Updated image error buffer for camera {self.cam_id}.")

    def to(self, device: torch.device):
        """
        Move the camera to the given device.
        Args:
            device: the device to move the camera to.
        """
        self.cam_to_worlds = self.cam_to_worlds.to(device)
        self.intrinsics = self.intrinsics.to(device)
        if self.ego_to_worlds is not None:
            self.ego_to_worlds = self.ego_to_worlds.to(device)
        if self.cam_to_ego is not None:
            self.cam_to_ego = self.cam_to_ego.to(device)
        if self.distortions is not None:
            self.distortions = self.distortions.to(device)
        if self.egocar_mask is not None:
            self.egocar_mask = self.egocar_mask.to(device)
        if self.lidar_depth_maps is not None:
            self.lidar_depth_maps = self.lidar_depth_maps.to(device)
        if self.image_error_maps is not None:
            self.image_error_maps = self.image_error_maps.to(device)
        if self.dynamic_masks is not None:
            self.dynamic_masks = self.dynamic_masks.to(device)
        if self.intrinsics_noncrop is not None:
            self.intrinsics_noncrop = self.intrinsics_noncrop.to(device)
        if self.intrinsics_downsample is not None:
            self.intrinsics_downsample = self.intrinsics_downsample.to(device)

    def get_image(self, frame_idx: int) -> Dict[str, Tensor]:
        """
        Get the rays for rendering the given frame index.
        Args:
            frame_idx: the frame index.
        Returns:
            a dict containing the rays for rendering the given frame index.
        """
        rgb, sky_mask, ground_mask = None, None, None
        dynamic_mask, human_mask, vehicle_mask = None, None, None
        tfl_mask = None
        pixel_coords = None
        egocar_mask = None
        ego_to_world, cam_to_ego = None, None
        rgb = self.load_image_by_frame_idx(frame_idx)
        if self.downscale_factor != 1.0:
            rgb = (
                torch.nn.functional.interpolate(
                    rgb.unsqueeze(0).permute(0, 3, 1, 2),
                    scale_factor=self.downscale_factor,
                    mode="bicubic",
                    antialias=True,
                )
                .squeeze(0)
                .permute(1, 2, 0)
            )
            img_height, img_width = rgb.shape[:2]
        else:
            img_height, img_width = self.HEIGHT, self.WIDTH

        x, y = torch.meshgrid(
            torch.arange(img_width),
            torch.arange(img_height),
            indexing="xy",
        )
        x, y = x.flatten(), y.flatten()
        x, y = x.to(self.device), y.to(self.device)
        # pixel coordinates
        pixel_coords = torch.stack([y / img_height, x / img_width], dim=-1).float().reshape(img_height, img_width, 2)
        if self.egocar_mask is not None:
            egocar_mask = self.egocar_mask
            if self.downscale_factor != 1.0:
                egocar_mask = (
                    torch.nn.functional.interpolate(
                        egocar_mask.unsqueeze(0).unsqueeze(0),
                        scale_factor=self.downscale_factor,
                        mode="nearest",
                    )
                    .squeeze(0)
                    .squeeze(0)
                )
        if self.load_ground_mask:
            ground_mask = self.load_ground_mask_by_frame_idx(frame_idx)
            if self.downscale_factor != 1.0:
                ground_mask = (
                    torch.nn.functional.interpolate(
                        ground_mask.unsqueeze(0).unsqueeze(0),
                        scale_factor=self.downscale_factor,
                        mode="nearest",
                    )
                    .squeeze(0)
                    .squeeze(0)
                )
        if self.load_sky_mask:
            sky_mask = self.load_sky_mask_by_frame_idx(frame_idx)
            if self.downscale_factor != 1.0:
                sky_mask = (
                    torch.nn.functional.interpolate(
                        sky_mask.unsqueeze(0).unsqueeze(0),
                        scale_factor=self.downscale_factor,
                        mode="nearest",
                    )
                    .squeeze(0)
                    .squeeze(0)
                )
        if self.load_tfl_mask:
            tfl_mask = self.load_tfl_mask_by_frame_idx(frame_idx)
            if self.downscale_factor != 1.0:
                tfl_mask = (
                    torch.nn.functional.interpolate(
                        tfl_mask.unsqueeze(0).unsqueeze(0),
                        scale_factor=self.downscale_factor,
                        mode="nearest",
                    )
                    .squeeze(0)
                    .squeeze(0)
                )
        if self.load_dynamic_mask:
            dynamic_mask, human_mask, vehicle_mask = self.load_dynamic_mask_by_frame_idx(frame_idx)
            if dynamic_mask is None and self.dynamic_masks is not None:
                dynamic_mask = self.dynamic_masks[frame_idx]
            if dynamic_mask is not None and self.downscale_factor != 1.0:
                dynamic_mask = (
                    torch.nn.functional.interpolate(
                        dynamic_mask.unsqueeze(0).unsqueeze(0),
                        scale_factor=self.downscale_factor,
                        mode="nearest",
                    )
                    .squeeze(0)
                    .squeeze(0)
                )
            if human_mask is not None and self.downscale_factor != 1.0:
                human_mask = (
                    torch.nn.functional.interpolate(
                        human_mask.unsqueeze(0).unsqueeze(0),
                        scale_factor=self.downscale_factor,
                        mode="nearest",
                    )
                    .squeeze(0)
                    .squeeze(0)
                )
            if vehicle_mask is not None and self.downscale_factor != 1.0:
                vehicle_mask = (
                    torch.nn.functional.interpolate(
                        vehicle_mask.unsqueeze(0).unsqueeze(0),
                        scale_factor=self.downscale_factor,
                        mode="nearest",
                    )
                    .squeeze(0)
                    .squeeze(0)
                )
        if self.cam_to_worlds is not None:
            ego_to_world = self.ego_to_worlds[frame_idx]
        if self.cam_to_ego is not None:
            cam_to_ego = self.cam_to_ego

        lidar_depth_map = None
        if self.lidar_depth_maps is not None:
            lidar_depth_map = self.lidar_depth_maps[frame_idx]
        elif self.load_projected_lidar_depth:
            lidar_depth_map = self.load_projected_lidar_depth_by_frame_idx(frame_idx)

        if lidar_depth_map is not None and self.downscale_factor != 1.0:
            lidar_depth_map = sparse_lidar_map_downsampler(lidar_depth_map, self.downscale_factor)

        c2w = self.cam_to_worlds[frame_idx]
        intrinsics = self.intrinsics[frame_idx] * self.downscale_factor
        intrinsics[2, 2] = 1.0
        intrinsic_noncrop = self.intrinsics_noncrop[frame_idx] * self.downscale_factor
        intrinsic_noncrop[2, 2] = 1.0
        if self.intrinsics_downsample is not None:
            intrinsic_downsample = self.intrinsics_downsample[frame_idx] * self.downscale_factor
            intrinsic_downsample[2, 2] = 1.0     
        origins, viewdirs, direction_norm = get_rays(x, y, c2w, intrinsics)
        origins = origins.reshape(img_height, img_width, 3)
        viewdirs = viewdirs.reshape(img_height, img_width, 3)
        direction_norm = direction_norm.reshape(img_height, img_width, 1)
        
        # Initialize downsampled components as None
        rays_downsample = None
        pixels_downsample = None
        depth_map_downsample = None
        masks_downsample = None
        pixel_coords_downsample = None
        
        # If downsample is enabled, create downsampled components
        if abs(self.difix_downsample - 1.0) > 1e-5:
            # Calculate downsampled dimensions
            downsampled_height = int(img_height * self.difix_downsample)
            downsampled_width = int(img_width * self.difix_downsample)
            
            # Create downsampled pixel coordinates
            x_down, y_down = torch.meshgrid(
                torch.arange(downsampled_width),
                torch.arange(downsampled_height),
                indexing="xy",
            )
            x_down, y_down = x_down.flatten(), y_down.flatten()
            x_down, y_down = x_down.to(self.device), y_down.to(self.device)
            pixel_coords_downsample = torch.stack([y_down / downsampled_height, x_down / downsampled_width], dim=-1).float().reshape(downsampled_height, downsampled_width, 2)
            
            # Downsample RGB image
            pixels_downsample = (
                torch.nn.functional.interpolate(
                    rgb.unsqueeze(0).permute(0, 3, 1, 2),
                    scale_factor=self.difix_downsample,
                    mode="bicubic",
                    antialias=True,
                )
                .squeeze(0)
                .permute(1, 2, 0)
            )
            
            # Downsample masks if they exist
            egocar_mask_downsample = None
            if egocar_mask is not None:
                egocar_mask_float = egocar_mask.float()
                egocar_mask_downsample = (
                    torch.nn.functional.interpolate(
                        egocar_mask_float.unsqueeze(0).unsqueeze(0),
                        scale_factor=self.difix_downsample,
                        mode="nearest",
                    )
                    .squeeze(0)
                    .squeeze(0)
                )
                egocar_mask_downsample = egocar_mask_downsample.round().bool()
            
            ground_mask_downsample = None
            if ground_mask is not None:
                ground_mask_float = ground_mask.float()
                ground_mask_downsample = (
                    torch.nn.functional.interpolate(
                        ground_mask_float.unsqueeze(0).unsqueeze(0),
                        scale_factor=self.difix_downsample,
                        mode="nearest",
                    )
                    .squeeze(0)
                    .squeeze(0)
                )
                ground_mask_downsample = ground_mask_downsample.round().bool()
            
            sky_mask_downsample = None
            if sky_mask is not None:
                sky_mask_float = sky_mask.float()
                sky_mask_downsample = (
                    torch.nn.functional.interpolate(
                        sky_mask_float.unsqueeze(0).unsqueeze(0),
                        scale_factor=self.difix_downsample,
                        mode="nearest",
                    )
                    .squeeze(0)
                    .squeeze(0)
                )
                sky_mask_downsample = sky_mask_downsample.round().bool()

            tfl_mask_downsample = None
            if tfl_mask is not None:
                tfl_mask_float = tfl_mask.float()
                tfl_mask_downsample = (
                    torch.nn.functional.interpolate(
                        tfl_mask_float.unsqueeze(0).unsqueeze(0),
                        scale_factor=self.difix_downsample,
                        mode="nearest",
                    )
                    .squeeze(0)
                    .squeeze(0)
                )
                tfl_mask_downsample = tfl_mask_downsample.round().bool()
            
            dynamic_mask_downsample = None
            human_mask_downsample = None
            vehicle_mask_downsample = None
            if dynamic_mask is not None:
                dynamic_mask_float = dynamic_mask.float()
                dynamic_mask_downsample = (
                    torch.nn.functional.interpolate(
                        dynamic_mask_float.unsqueeze(0).unsqueeze(0),
                        scale_factor=self.difix_downsample,
                        mode="nearest",
                    )
                    .squeeze(0)
                    .squeeze(0)
                )
                dynamic_mask_downsample = dynamic_mask_downsample.round().bool()
            
            if human_mask is not None:
                human_mask_float = human_mask.float()
                human_mask_downsample = (
                    torch.nn.functional.interpolate(
                        human_mask_float.unsqueeze(0).unsqueeze(0),
                        scale_factor=self.difix_downsample,
                        mode="nearest",
                    )
                    .squeeze(0)
                    .squeeze(0)
                )
                human_mask_downsample = human_mask_downsample.round().bool()
            if vehicle_mask is not None:
                vehicle_mask_float = vehicle_mask.float()
                vehicle_mask_downsample = (
                    torch.nn.functional.interpolate(
                        vehicle_mask_float.unsqueeze(0).unsqueeze(0),
                        scale_factor=self.difix_downsample,
                        mode="nearest",
                    )
                    .squeeze(0)
                    .squeeze(0)
                )
                vehicle_mask_downsample = vehicle_mask_downsample.round().bool()
            
            masks_downsample = ImageMasks(sky_mask_downsample, ground_mask_downsample, dynamic_mask_downsample, human_mask_downsample, vehicle_mask_downsample, egocar_mask_downsample,tfl_mask_downsample)
            
            # Downsample depth map if it exists
            depth_map_downsample = None
            if lidar_depth_map is not None:
                depth_map_downsample = sparse_lidar_map_downsampler(lidar_depth_map, self.difix_downsample)
            
            # Adjust intrinsics for downsampled image
            intrinsics_downsampled = intrinsics * self.difix_downsample
            intrinsics_downsampled[2, 2] = 1.0
            
            # Calculate rays for downsampled image
            origins_down, viewdirs_down, direction_norm_down = get_rays(x_down, y_down, c2w, intrinsics_downsampled)
            origins_down = origins_down.reshape(downsampled_height, downsampled_width, 3)
            viewdirs_down = viewdirs_down.reshape(downsampled_height, downsampled_width, 3)
            direction_norm_down = direction_norm_down.reshape(downsampled_height, downsampled_width, 1)
            
            rays_downsample = Rays(origins_down, viewdirs_down, direction_norm_down)

        image_info = ImageInfo(
            rays=Rays(origins, viewdirs, direction_norm),
            pixels=rgb,
            depth_map=lidar_depth_map,
            masks=ImageMasks(sky_mask, ground_mask, dynamic_mask, human_mask, vehicle_mask, egocar_mask,tfl_mask),
            pixel_coords=pixel_coords,
            normalized_time=self.normalized_time[frame_idx],
            image_index=self.unique_img_idx[frame_idx],
            frame_index=torch.tensor(frame_idx),
        )
        camera_info = CameraInfo(
            camera_id=self.cam_id,
            camera_name=self.cam_name,
            intrinsic=intrinsics,
            camera_to_world=c2w,
            ego_to_world=ego_to_world,
            camera_to_ego=cam_to_ego,
            height=img_height,
            width=img_width,
            intrinsic_noncrop=intrinsic_noncrop
        )
        # Add downsampled components to image_info if enabled
        if abs(self.difix_downsample - 1.0) > 1e-5:
            image_info.rays_downsample = rays_downsample
            image_info.pixels_downsample = pixels_downsample
            image_info.depth_map_downsample = depth_map_downsample
            image_info.masks_downsample = masks_downsample
            image_info.pixel_coords_downsample = pixel_coords_downsample
            camera_info.intrinsic_downsample=intrinsic_downsample

        return image_info, camera_info


class ScenePixelSource(abc.ABC):
    """
    The base class for all pixel sources of a scene.
    """

    # define a transformation matrix to convert the opencv
    # camera coordinate system to the dataset camera coordinate system
    data_cfg: OmegaConf = None
    # the dataset name, choose from ["waymo", "kitti", "nuscenes", "pandaset", "argoverse"]
    dataset_name: str = None
    # the dict of camera data
    camera_data: Dict[int, CameraData] = {}
    # the normalized time of all images (normalized to [0, 1]), shape: (num_frames,)
    _normalized_time: Tensor = None
    # timestep indices of frames, shape: (num_frames,)
    _timesteps: Tensor = None
    # image error buffer, (num_images, )
    image_error_buffer: Tensor = None
    # whether the buffer is computed
    image_error_buffered: bool = False
    # the downscale factor of the error buffer
    buffer_downscale: float = 1.0

    # -------------- object annotations
    # (num_frame, num_instances, 4, 4)
    instances_pose: Tensor = None
    # (num_instances, 3)
    instances_size: Tensor = None
    # (num_instances, )
    instances_true_id: Tensor = None
    # (num_instances, )
    instances_model_types: Tensor = None
    # (num_frame, num_instances)    
    instances_types: Tensor = None
    # (num_frame, num_instances)
    per_frame_instance_mask: Tensor = None

    obj_dist_level_dict: Dict = {}

    difix_downsample_list: list = []

    def __init__(
        self,
        dataset_name,
        pixel_data_config: OmegaConf,
        device: torch.device = torch.device("cpu"),
    ) -> None:
        # hold the config of the pixel data
        self.dataset_name = dataset_name
        self.data_cfg = pixel_data_config
        self.device = device
        self._downscale_factor = 1 / pixel_data_config.downscale
        self.difix_downsample_list = getattr(self.data_cfg, 'difix_downsample', [1.0] * len(self.data_cfg.cameras))
        self._old_downscale_factor = []
        # epoch-wise image sampler state
        self._epoch_order = None  # type: Optional[List[int]]
        self._epoch_ptr = 0

    @abc.abstractmethod
    def load_cameras(self) -> None:
        """
        Load the camera intrinsics, extrinsics, timestamps, etc.
        Load the images, dynamic masks, sky masks, etc.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def load_objects(self) -> None:
        """
        Load the object annotations.
        """
        raise NotImplementedError

    def load_data(self) -> None:
        """
        A general function to load all data.
        """
        self.load_cameras()
        self.build_image_error_buffer()
        logger.info("[Pixel] All Pixel Data loaded.")

        if self.data_cfg.load_objects:
            self.load_objects()
            logger.info("[Pixel] All Object Annotations loaded.")

        # set initial downscale factor
        for cam_id in self.camera_list:
            self.camera_data[cam_id].set_downscale_factor(self._downscale_factor)

    def to(self, device: torch.device) -> "ScenePixelSource":
        """
        Move the dataset to the given device.
        Args:
            device: the device to move the dataset to.
        """
        self.device = device
        if self._timesteps is not None:
            self._timesteps = self._timesteps.to(device)
        if self._normalized_time is not None:
            self._normalized_time = self._normalized_time.to(device)
        if self.instances_pose is not None:
            self.instances_pose = self.instances_pose.to(device)
        if self.instances_moving is not None:
            self.instances_moving = self.instances_moving.to(device)
        if self.instances_size is not None:
            self.instances_size = self.instances_size.to(device)
        if self.per_frame_instance_mask is not None:
            self.per_frame_instance_mask = self.per_frame_instance_mask.to(device)
        if self.instances_model_types is not None:
            self.instances_model_types = self.instances_model_types.to(device)
        return self

    def get_aabb(self) -> Tensor:
        """
        Returns:
            aabb_min, aabb_max: the min and max of the axis-aligned bounding box of the scene
        Note:
            We compute the coarse aabb by using the front camera positions / trajectories. We then
            extend this aabb by 40 meters along horizontal directions and 20 meters up and 5 meters
            down along vertical directions.
        """
        front_camera_trajectory = self.front_camera_trajectory

        # compute the aabb
        aabb_min = front_camera_trajectory.min(dim=0)[0]
        aabb_max = front_camera_trajectory.max(dim=0)[0]

        # extend aabb by 40 meters along forward direction and 40 meters along the left/right direction
        # aabb direction: x, y, z: front, left, up
        aabb_max[0] += 40
        aabb_max[1] += 40
        # when the car is driving uphills
        aabb_max[2] = min(aabb_max[2] + 20, 20)

        # for waymo, there will be a lot of waste of space because we don't have images in the back,
        # it's more reasonable to extend the aabb only by a small amount, e.g., 5 meters
        # we use 40 meters here for a more general case
        aabb_min[0] -= 40
        aabb_min[1] -= 40
        # when a car is driving downhills
        aabb_min[2] = max(aabb_min[2] - 5, -5)
        aabb = torch.tensor([*aabb_min, *aabb_max])
        logger.info(f"[Pixel] Auto AABB from camera: {aabb}")
        return aabb

    @property
    def front_camera_trajectory(self) -> Tensor:
        """
        Returns:
            the front camera trajectory.
        """
        front_camera = self.camera_data[0]
        assert (
            front_camera.cam_to_worlds is not None
        ), "Camera poses not loaded, cannot compute front camera trajectory."
        return front_camera.cam_to_worlds[:, :3, 3]

    def parse_img_idx(self, img_idx: int) -> Tuple[int, int]:
        """
        Parse the image index to the camera index and frame index.
        Args:
            img_idx: the image index.
        Returns:
            cam_idx: the camera index.
            frame_idx: the frame index.
        """
        unique_cam_idx = img_idx % self.num_cams
        frame_idx = img_idx // self.num_cams
        return unique_cam_idx, frame_idx

    def get_image(self, img_idx: int) -> Dict[str, Tensor]:
        """
        Get the rays for rendering the given image index.
        Args:
            img_idx: the image index.
        Returns:
            a dict containing the rays for rendering the given image index.
        """
        unique_cam_idx, frame_idx = self.parse_img_idx(img_idx)
        for cam_id in self.camera_list:
            if unique_cam_idx == self.camera_data[cam_id].unique_cam_idx:
                return self.camera_data[cam_id].get_image(frame_idx)

    @property
    def camera_list(self) -> List[int]:
        """
        Returns:
            the list of camera indices
        """
        return self.data_cfg.cameras

    @property
    def num_cams(self) -> int:
        """
        Returns:
            the number of cameras in the dataset
        """
        return len(self.data_cfg.cameras)

    @property
    def num_frames(self) -> int:
        """
        Returns:
            the number of frames in the dataset
        """
        return len(self._timesteps)

    @property
    def num_timesteps(self) -> int:
        """
        Returns:
            the number of image timesteps in the dataset
        """
        return len(self._timesteps)

    @property
    def num_imgs(self) -> int:
        """
        Returns:
            the number of images in the dataset
        """
        return self.num_cams * self.num_frames

    @property
    def timesteps(self) -> Tensor:
        """
        Returns:
            the integer timestep indices of all images,
            shape: (num_imgs,)
        Note:
            the difference between timestamps and timesteps is that
            timestamps are the actual timestamps (minus 1e9) of images
            while timesteps are the integer timestep indices of images.
        """
        return self._timesteps

    @property
    def normalized_time(self) -> Tensor:
        """
        Returns:
            the normalized timestamps of all images
            (normalized to the range [0, 1]),
            shape: (num_imgs,)
        """
        return self._normalized_time

    def register_normalized_timestamps(self) -> None:
        # normalized timestamps are between 0 and 1
        normalized_time = (self._timesteps - self._timesteps.min()) / (self._timesteps.max() - self._timesteps.min())

        self._normalized_time = normalized_time.to(self.device)
        self._unique_normalized_timestamps = self._normalized_time.unique()

    def find_closest_timestep(self, normed_timestamp: float) -> int:
        """
        Find the closest timestep to the given timestamp.
        Args:
            normed_timestamp: the normalized timestamp to find the closest timestep for.
        Returns:
            the closest timestep to the given timestamp.
        """
        return torch.argmin(torch.abs(self._normalized_time - normed_timestamp))

    def propose_training_image(
        self,
        candidate_indices: Tensor,
        num_samples: int = 1,
        generator: Optional[Generator] = None,
    ) -> Dict[str, Tensor]:
        # Option: ensure every image is seen once before reshuffle
        ensure_once = self.data_cfg.sampler.get("ensure_once_per_round", False)
        if ensure_once:
            # Build a set for fast membership test on allowed candidates
            if isinstance(candidate_indices, Tensor):
                cand_list = candidate_indices.tolist()
            else:
                cand_list = list(candidate_indices)
            cand_set = set(int(x) for x in cand_list)

            # Initialize epoch order on first use or if exhausted
            if (self._epoch_order is None) or (self._epoch_ptr >= len(self._epoch_order)):
                # Shuffle all images for a new round
                self._epoch_order = list(range(self.num_imgs))
                random.shuffle(self._epoch_order)
                self._epoch_ptr = 0

            # Collect next indices that are in the current candidate set
            selected = []
            while len(selected) < num_samples:
                if self._epoch_ptr >= len(self._epoch_order):
                    # start a new shuffled round
                    random.shuffle(self._epoch_order)
                    self._epoch_ptr = 0
                idx = self._epoch_order[self._epoch_ptr]
                self._epoch_ptr += 1
                if idx in cand_set:
                    selected.append(idx)

            return selected

        if random.random() < self.buffer_ratio and self.image_error_buffered:
            # sample according to the image error buffer
            image_mean_error = self.image_error_buffer[candidate_indices]
        else:
            image_mean_error = torch.ones(self.num_imgs)

        start_enhance_weight = self.data_cfg.sampler.get("start_enhance_weight", 1)
        if start_enhance_weight > 1:
            frame_num = int(self.num_imgs / self.num_cams)
            # increase the error of the first 10% frames
            error_weight = torch.cat(
                (
                    torch.linspace(start_enhance_weight, 1, int(frame_num * 0.05)),
                    torch.ones(frame_num - int(frame_num * 0.05)),
                )
            )
            error_weight = error_weight[..., None].repeat(1, self.num_cams).reshape(-1)
            error_weight = error_weight[candidate_indices].to(self.device)

            image_mean_error = image_mean_error * error_weight

        idx = torch.multinomial(image_mean_error, num_samples, replacement=False, generator=generator).tolist()
        img_idx = [candidate_indices[i] for i in idx]

        return img_idx

    def build_image_error_buffer(self) -> None:
        """
        Build the image error buffer.
        """
        if self.buffer_ratio > 0:
            for cam_id in self.camera_list:
                self.camera_data[cam_id].build_image_error_buffer()
        else:
            logger.info("Not building image error buffer because buffer_ratio <= 0.")

    def update_image_error_maps(self, render_results: Dict[str, Tensor]) -> None:
        """
        Update the image error buffer with the given render results for each camera.
        """
        # (img_num, )
        image_error_buffer = torch.zeros(self.num_imgs, device=self.device)
        image_cam_id = torch.from_numpy(np.stack(render_results["cam_ids"], axis=0))
        for cam_id in self.camera_list:
            cam_name = self.camera_data[cam_id].cam_name
            gt_rgbs, pred_rgbs = [], []
            Dynamic_opacities = []
            for img_idx, img_cam in enumerate(render_results["cam_names"]):
                if img_cam == cam_name:
                    gt_rgbs.append(render_results["gt_rgbs"][img_idx])
                    pred_rgbs.append(render_results["rgbs"][img_idx])
                    if "Dynamic_opacities" in render_results:
                        Dynamic_opacities.append(render_results["Dynamic_opacities"][img_idx])

            camera_results = {
                "gt_rgbs": gt_rgbs,
                "rgbs": pred_rgbs,
            }
            if len(Dynamic_opacities) > 0:
                camera_results["Dynamic_opacities"] = Dynamic_opacities
            self.camera_data[cam_id].update_image_error_maps(camera_results)

            # update the image error buffer
            image_error_buffer[image_cam_id == cam_id] = self.camera_data[cam_id].image_error_maps.mean(dim=(1, 2))

        self.image_error_buffer = image_error_buffer
        self.image_error_buffered = True
        logger.info("Successfully updated image error buffer")

    def get_image_error_video(self, layout: Callable) -> List[np.ndarray]:
        """
        Get the image error buffer video.
        Returns:
            frames: the pixel sample weights video.
        """
        per_cam_video = {}
        for cam_id in self.camera_list:
            per_cam_video[cam_id] = self.camera_data[cam_id].get_image_error_video()

        all_error_images = []
        all_cam_names = []
        for frame_id in range(self.num_frames):
            for cam_id in self.camera_list:
                all_error_images.append(per_cam_video[cam_id][frame_id])
                all_cam_names.append(self.camera_data[cam_id].cam_name)

        merged_list = []
        for i in range(len(all_error_images) // self.num_cams):
            frames = all_error_images[i * self.num_cams : (i + 1) * self.num_cams]
            frames = [np.stack([frame, frame, frame], axis=-1) for frame in frames]
            cam_names = all_cam_names[i * self.num_cams : (i + 1) * self.num_cams]
            tiled_img = layout(frames, cam_names)
            merged_list.append(tiled_img)

        merged_video = np.stack(merged_list, axis=0)
        merged_video -= merged_video.min()
        merged_video /= merged_video.max()
        merged_video = np.clip(merged_video * 255, 0, 255).astype(np.uint8)
        return merged_video

    @property
    def downscale_factor(self) -> float:
        """
        Returns:
            downscale_factor: the downscale factor of the images
        """
        return self._downscale_factor

    def update_downscale_factor(self, downscale: float) -> None:
        """
        Args:
            downscale: the new downscale factor
        Updates the downscale factor
        """
        self._old_downscale_factor.append(self._downscale_factor)
        self._downscale_factor = downscale
        for cam_id in self.camera_list:
            self.camera_data[cam_id].set_downscale_factor(self._downscale_factor)
    
    def update_difix_downsample(self) -> None:
        """
        Args:
            difix_downsample: the new difix downsample factor
        Updates the difix downsample factor
        """
        for index, cam_id in enumerate(self.camera_list):
            self.camera_data[cam_id].set_difix_downsample(self.difix_downsample_list[index])
            self.camera_data[cam_id].load_downsample_cam_info()

    def reset_downscale_factor(self) -> None:
        """
        Resets the downscale factor to the original value
        """
        assert len(self._old_downscale_factor) > 0, "No downscale factor to reset to"
        self._downscale_factor = self._old_downscale_factor.pop()
        for cam_id in self.camera_list:
            self.camera_data[cam_id].set_downscale_factor(self._downscale_factor)

    @property
    def buffer_ratio(self) -> float:
        """
        Returns:
            buffer_ratio: the ratio of the rays sampled from the image error buffer
        """
        return self.data_cfg.sampler.buffer_ratio

    @property
    def buffer_downscale(self) -> float:
        """
        Returns:
            buffer_downscale: the downscale factor of the image error buffer
        """
        return self.data_cfg.sampler.buffer_downscale

    def prepare_novel_view_render_data(self, c2w: torch.Tensor, image_idx: int) -> Tuple[ImageInfo, CameraInfo]:
        """
        Prepare all necessary elements for novel view rendering.

        Args:
            c2w (torch.Tensor): Camera to world matrix of the novel view, shape (4, 4).
            image_idx (int): The frame index to render

        Returns:
            Tuple[ImageInfo, CameraInfo]: The image information and camera information.
        """
        frame_idx = image_idx // self.num_cams
        cam_id = self.camera_list[image_idx % self.num_cams]

        intrinsics = self.camera_data[cam_id].intrinsics[0]  # Assume intrinsics are constant across frames
        H, W = self.camera_data[cam_id].HEIGHT, self.camera_data[cam_id].WIDTH

        # Generate ray origins and directions
        x, y = torch.meshgrid(torch.arange(W), torch.arange(H), indexing="xy")
        x, y = x.to(self.device), y.to(self.device)

        origins, viewdirs, direction_norm = get_rays(x.flatten(), y.flatten(), c2w, intrinsics)
        origins = origins.reshape(H, W, 3)
        viewdirs = viewdirs.reshape(H, W, 3)
        direction_norm = direction_norm.reshape(H, W, 1)

        cam_info = CameraInfo(
            camera_to_world=c2w,
            intrinsic=intrinsics,
            height=H,
            width=W,
            camera_id=cam_id,
            camera_name=self.camera_data[cam_id].cam_name,
        )

        egocar_mask = None
        if self.camera_data[cam_id].egocar_mask is not None:
            egocar_mask = self.camera_data[cam_id].egocar_mask

        image_info = ImageInfo(
            rays=Rays(
                origins=origins,
                viewdirs=viewdirs,
                direction_norm=direction_norm,
            ),
            masks=ImageMasks(
                sky_mask=None,
                ground_mask=None,
                dynamic_mask=None,
                human_mask=None,
                vehicle_mask=None,
                egocar_mask=egocar_mask,
                tfl_mask=None,
            ),
            image_index=torch.tensor(image_idx),
            frame_index=torch.tensor(frame_idx),
            normalized_time=self.normalized_time[frame_idx],
            pixel_coords=torch.stack([y.float() / H, x.float() / W], dim=-1),
        )

        return image_info, cam_info