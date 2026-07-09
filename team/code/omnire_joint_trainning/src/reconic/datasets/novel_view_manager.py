import glob
import os
import random
from typing import List, Optional, Tuple

import imageio
import numpy as np
import torch
from omegaconf import OmegaConf

from .base.data_proto import CameraInfo, ImageInfo
from .base.utils import get_rays


class NovelViewManager:
    def __init__(self, novel_view_dir: str, debug_mode: bool = True, cfg: OmegaConf = None):
        self.novel_view_dir = novel_view_dir
        self.debug_mode = debug_mode
        self.cfg = cfg
        self.use_mask_in_novel_view = True
        if "generative_engine" in self.cfg:
            self.use_mask_in_novel_view = self.cfg.generative_engine.get("use_mask_in_novel_view", True)

        os.makedirs(self.novel_view_dir, exist_ok=True)

        if self.debug_mode:
            self.infer_vis_log_dir = os.path.join(self.novel_view_dir, "vis_infer")
            os.makedirs(self.infer_vis_log_dir, exist_ok=True)

    def save_novel_view_data(
        self,
        image_index: int,
        shift_value_name: str,
        novel_view_cam_extrinsic: torch.Tensor,
        novel_view_render_image: torch.Tensor,
        novel_view_render_fix_image: torch.Tensor,
        novel_view_sky_mask: torch.Tensor,
    ):
        """
        Save the novel view data to the disk

        Args:
            image_index: The index of the image
            shift_value_name: The shift value name
            novel_view_cam_extrinsic: The camera extrinsic of the novel view
            novel_view_render_image: The rendered image of the novel view
            novel_view_render_fix_image: The generative image conditioned on the rendered novel view image
            novel_view_sky_mask: The sky mask of the novel view.
        """
        # Save the image info to the disk
        novel_view_render_image = (novel_view_render_image.to(torch.float32).cpu().numpy() * 255).astype(np.uint8)
        novel_view_render_fix_image = (novel_view_render_fix_image.to(torch.float32).cpu().numpy() * 255).astype(
            np.uint8
        )
        image_path = os.path.join(self.novel_view_dir, f"image_{image_index:04d}_shift_{shift_value_name}.png")
        imageio.imwrite(image_path, novel_view_render_fix_image)

        # Save the sky mask to the disk
        if novel_view_sky_mask is not None:
            novel_view_sky_mask = (novel_view_sky_mask.to(torch.float32).cpu().numpy() * 255).astype(np.uint8)
            sky_mask_path = os.path.join(self.novel_view_dir, f"sky_mask_{image_index:04d}_shift_{shift_value_name}.png")
            imageio.imwrite(sky_mask_path, novel_view_sky_mask)

        # Save the camera info to the disk
        cam_info_path = os.path.join(
            self.novel_view_dir, f"cam_extrinsic_{image_index:04d}_shift_{shift_value_name}.npy"
        )
        np.save(cam_info_path, novel_view_cam_extrinsic.cpu().numpy())

        # Debug mode: save intermediate visualized images to the disk
        if self.debug_mode:
            vis_img = np.concatenate([novel_view_render_image, novel_view_render_fix_image], axis=1)
            vis_path = os.path.join(self.infer_vis_log_dir, f"gen_vis_{image_index:04d}_shift_{shift_value_name}.png")
            imageio.imwrite(vis_path, vis_img)

    def exist_novel_view_data(self, image_index: int, shift_value_name: str):
        """
        Check if the novel view data exists

        Args:
            image_index: The index of the image
            shift_value_name: The pose delta level
        """
        image_path = os.path.join(self.novel_view_dir, f"image_{image_index:04d}_shift_{shift_value_name}.png")
        sky_mask_path = os.path.join(self.novel_view_dir, f"sky_mask_{image_index:04d}_shift_{shift_value_name}.png")
        cam_info_path = os.path.join(
            self.novel_view_dir, f"cam_extrinsic_{image_index:04d}_shift_{shift_value_name}.npy"
        )
        return os.path.exists(image_path) and os.path.exists(cam_info_path)

    def get_random_novel_view_shift_value_name(self, image_index: int) -> Optional[str]:
        """
        Get the latest novel view data
        """
        image_files = glob.glob(os.path.join(self.novel_view_dir, f"image_{image_index:04d}_shift_*.png"))
        if len(image_files) == 0:
            return None
        random.shuffle(image_files)
        shift_value_name = os.path.basename(image_files[0]).split("_shift_")[1].split(".png")[0]
        if not self.exist_novel_view_data(image_index, shift_value_name):
            return None
        return shift_value_name

    def get_all_novel_view_shift_value_name(self, image_index: int) -> List[str]:
        """
        Get the latest novel view data
        """
        image_files = glob.glob(os.path.join(self.novel_view_dir, f"image_{image_index:04d}_shift_*.png"))
        shift_value_names = [
            os.path.basename(image_file).split("_shift_")[1].split(".png")[0] for image_file in image_files
        ]
        return shift_value_names

    def load_novel_view_data(
        self,
        image_index: int,
        base_image_info: ImageInfo,
        base_cam_info: CameraInfo,
        shift_value_name: Optional[str] = None,
    ) -> Tuple[Optional[ImageInfo], Optional[CameraInfo]]:
        """
        Load the novel view data from the disk.

        # [Note] This is a non-thread-safe function for dataloader.
        # There is a race condition that the main processor is saving the data and one of multiple workers(dataloader)
        #  is loading the data.
        # We ignore the thread safety issue for now.

        Args:
            image_index: The index of the image
            base_image_info: The base image info
        """
        if shift_value_name is None:
            shift_value_name = self.get_random_novel_view_shift_value_name(image_index)
        if shift_value_name is None:
            return None, None
        if "downsample" in shift_value_name and base_cam_info.intrinsic_downsample is None:
            return None, None
        novel_view_image_info = base_image_info.clone()
        novel_view_cam_info = base_cam_info.clone()

        if "noncrop" in shift_value_name:
            novel_view_cam_info.intrinsic = novel_view_cam_info.intrinsic_noncrop

        # Load the novel view image and sky mask from the disk
        image_path = os.path.join(self.novel_view_dir, f"image_{image_index:04d}_shift_{shift_value_name}.png")
        image = imageio.imread(image_path)
        image = torch.from_numpy(image).float() / 255.0
        novel_view_image_info.pixels = image

        # Load the sky mask from the disk
        sky_mask_path = os.path.join(self.novel_view_dir, f"sky_mask_{image_index:04d}_shift_{shift_value_name}.png")
        if os.path.exists(sky_mask_path):
            sky_mask = imageio.imread(sky_mask_path)
            sky_mask = torch.from_numpy(sky_mask).float() / 255.0
            novel_view_image_info.masks.sky_mask = sky_mask
        else:
            novel_view_image_info.masks.sky_mask = None

        # Load the camera info from the disk
        cam_info_path = os.path.join(
            self.novel_view_dir, f"cam_extrinsic_{image_index:04d}_shift_{shift_value_name}.npy"
        )
        cam_extrinsic = torch.from_numpy(np.load(cam_info_path)).float()
        novel_view_cam_info.camera_to_world = cam_extrinsic

        # Update the ray origins and directions
        H, W = image.shape[:2]
        x, y = torch.meshgrid(torch.arange(W), torch.arange(H), indexing="xy")
        x, y = x.flatten(), y.flatten()
        origins, viewdirs, direction_norm = get_rays(x, y, cam_extrinsic, novel_view_cam_info.intrinsic.cpu())
        novel_view_image_info.rays.origins = origins.reshape(H, W, 3)
        novel_view_image_info.rays.viewdirs = viewdirs.reshape(H, W, 3)
        novel_view_image_info.rays.direction_norm = direction_norm.reshape(H, W, 1)

        if "downsample" in shift_value_name and novel_view_cam_info.intrinsic_downsample is not None:
            if "noncrop" not in shift_value_name:
                novel_view_cam_info.intrinsic = novel_view_cam_info.intrinsic_downsample
            novel_view_cam_info.height, novel_view_cam_info.width = H, W
            novel_view_image_info.pixel_coords = novel_view_image_info.pixel_coords_downsample
            novel_view_image_info.masks.egocar_mask = novel_view_image_info.masks_downsample.egocar_mask

        # Reset the unmatched info
        novel_view_image_info.masks.dynamic_mask = None
        novel_view_image_info.masks.human_mask = None
        novel_view_image_info.masks.vehicle_mask = None
        novel_view_image_info.masks.ground_mask = None
        novel_view_image_info.depth_map = None
        if not self.use_mask_in_novel_view:
            novel_view_image_info.masks.egocar_mask = None

        novel_view_image_info.from_synthesis = True
        return novel_view_image_info, novel_view_cam_info
