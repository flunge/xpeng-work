import os
import random
import re
import cv2
import numpy as np
import PIL.Image as pil
import torch
import torch.nn.functional as F
from torch.utils.data import Dataset
from torchvision import transforms

from mvsnet.mvsa.src.mvsanywhere.utils.generic_utils import (
    imagenet_normalize,
    read_image_file,
    readlines,
)
from mvsnet.mvsa.src.mvsanywhere.utils.geometry_utils import pose_distance, rotz


class GenericMVSDataset(Dataset):
    """
    Generic MVS dataset class. This class can be used as a base
    for different multi-view datasets.

    It houses the main __getitem__ function that will assemble a tuple of imgaes
    and their data.

    Tuples are read from a tuple file defined as
        tuple_info_file_location/{split}{mv_tuple_file_suffix}

    Each line in the tuple file should contain a scene id and frame ids for each
    frame in the tuple:

        scan_id frame_id_0 frame_id_1 ... frame_id_N-1

    where frame_id_0 is the reference image.

    These will be loaded and stored in self.frame_tuples.

    If no tuple file suffix is provided, the dataset will only allow basic frame
    data loading from the split.

    Datasets that use this base class as a parent should modify base file load
    functions that do not have an implementation below.

    """

    def __init__(
        self,
        dataset_path,
        split,
        mv_tuple_file_suffix,
        include_full_res_depth=False,
        limit_to_scan_id=None,
        num_images_in_tuple=None,
        tuple_info_file_location=None,
        image_height=480,
        image_width=640,
        high_res_image_width=None,
        high_res_image_height=None,
        image_depth_ratio=2,
        shuffle_tuple=False,
        include_full_depth_K=False,
        include_high_res_color=False,
        pass_frame_id=False,
        skip_frames=None,
        skip_to_frame=None,
        verbose_init=True,
        image_resampling_mode=pil.BILINEAR,
        disable_flip=False,
        rotate_images=False,
        matching_scale=0.25,
        prediction_scale=0.5,
        prediction_num_scales=5,
        allowed_cam_ids=None,
    ):
        """
        Args:
            dataset_path: base path to the dataaset directory.
            split: the dataset split.
            mv_tuple_file_suffix: a suffix for the tuple file's name. The
                tuple filename searched for wil be
                {split}{mv_tuple_file_suffix}.
            tuple_info_file_location: location to search for a tuple file, if
                None provided, will search in the dataset directory under
                'tuples'.
            limit_to_scan_id: limit loaded tuples to one scan's frames.
            num_images_in_tuple: optional integer to limit tuples to this number
                of images.
            image_height, image_width: size images should be loaded at/resized
                to.
            include_high_res_color: should the dataset pass back higher
                resolution images.
            high_res_image_height, high_res_image_width: resolution images
                should be resized if we're passing back higher resolution
                images.
            image_depth_ratio: returned gt depth maps "depth_b1hw" will be of
                size (image_height, image_width)/image_depth_ratio.
            include_full_res_depth: if true will return depth maps from the
                dataset at the highest resolution available.
            shuffle_tuple: by default source images will be ordered according to
                overall pose distance to the reference image. When this flag is
                true, source images will be shuffled. Only used for ablation.
            pass_frame_id: if we should return the frame_id as part of the item
                dict
            skip_frames: if not none, will stride the tuple list by this value.
                Useful for only fusing every 'skip_frames' frame when fusing
                depth.
            verbose_init: if True will let the init print details on the
                initialization.
            native_depth_width, native_depth_height: for some datasets, it's
                useful to know what the native depth resolution is in advance.
            image_resampling_mode: resampling method for resizing images.

        """
        super(GenericMVSDataset).__init__()

        self.split = split
        scan_folder = self.get_sub_folder_dir(split)

        self.dataset_path = dataset_path
        self.scenes_path = os.path.join(dataset_path, scan_folder)

        self.mv_tuple_file_suffix = mv_tuple_file_suffix
        self.num_images_in_tuple = num_images_in_tuple
        self.shuffle_tuple = shuffle_tuple
        self.allowed_cam_ids = self._normalize_allowed_cam_ids(allowed_cam_ids)

        # default to where the dataset is to look for a tuple file
        if tuple_info_file_location is None:
            tuple_info_file_location = os.path.join(dataset_path, "tuples")

        if mv_tuple_file_suffix is not None:
            # tuple info should be available
            tuple_information_filepath = os.path.join(
                os.environ["PWD"], tuple_info_file_location, f"{split}{mv_tuple_file_suffix}"
            )

            # check if this file exists
            assert os.path.exists(tuple_information_filepath), (
                f"Tuple file {tuple_information_filepath} "
                "doesn't exist! Pass none for mv_tuple_file_suffix if you don't"
                " actually need a tuple file, otherwise check your paths."
            )

            # read in those tuples
            self.frame_tuples = readlines(tuple_information_filepath)

            # optionally limit frames to just one scan.
            if limit_to_scan_id is not None:
                self.frame_tuples = [
                    frame_tuple
                    for frame_tuple in self.frame_tuples
                    if limit_to_scan_id == frame_tuple.split(" ")[0]
                ]

            if skip_to_frame is not None:
                if verbose_init:
                    print(f"".center(80, "#"))
                    print(f"".center(80, "#"))
                    print(f"".center(80, "#"))
                    print(f" Skipping to frame {skip_to_frame} ".center(80, "#"))
                    print(f"".center(80, "#"))
                    print(f"".center(80, "#"))
                    print(f"".center(80, "#"), "\n")
                self.frame_tuples = self.frame_tuples[skip_to_frame:]

            # optionally skip every frame with interval skip_frame
            if skip_frames is not None:
                if verbose_init:
                    print(f"".center(80, "#"))
                    print(f"".center(80, "#"))
                    print(f"".center(80, "#"))
                    print(f" Skipping every {skip_frames} ".center(80, "#"))
                    print(f"".center(80, "#"))
                    print(f"".center(80, "#"))
                    print(f"".center(80, "#"), "\n")
                self.frame_tuples = self.frame_tuples[::skip_frames]

            if self.allowed_cam_ids:
                self._filter_frame_tuples_by_cam(split)
        else:
            if verbose_init:
                print(f"".center(80, "#"))
                print(
                    f" tuple_information_filepath isn't provided."
                    "Only basic dataloader functions are available. ".center(80, "#")
                )
                print(f"".center(80, "#"), "\n")

        self.image_width = image_width
        self.image_height = image_height
        self.high_res_image_width = high_res_image_width
        self.high_res_image_height = high_res_image_height

        # Random resize crop
        self.random_resize_crop = transforms.RandomResizedCrop((self.image_height, self.image_width), scale=(0.75, 1.0), ratio=(4/3, 4/3))

        # size up depth using ratio of RGB to depth
        self.depth_height = int(self.image_height * prediction_scale)
        self.depth_width = int(self.image_width * prediction_scale)

        self.matching_height = int(self.image_height * matching_scale)
        self.matching_width = int(self.image_width * matching_scale)

        self.include_full_depth_K = include_full_depth_K
        self.include_high_res_color = include_high_res_color
        self.include_full_res_depth = include_full_res_depth

        self.pass_frame_id = pass_frame_id

        self.disable_resize_warning = False
        self.image_resampling_mode = image_resampling_mode

        self.disable_flip = disable_flip

        self.rotate_images = rotate_images

        self.matching_scale = matching_scale
        self.prediction_scale = prediction_scale
        self.prediction_num_scales = prediction_num_scales

        # If high resolution image size is not provided, 
        # we use the one from the first frame
        if self.include_high_res_color and (
            self.high_res_image_height is None or self.high_res_image_width is None
        ):
            self.high_res_image_height = None
            self.high_res_image_width = None
            first_frame = self.frame_tuples[0].split(" ")
            first_image = self.load_high_res_color(
                first_frame[0], first_frame[1]
            )
            self.high_res_image_height = first_image.shape[1]
            self.high_res_image_width = first_image.shape[2]

    def __len__(self):
        return len(self.frame_tuples)

    @staticmethod
    def get_sub_folder_dir(split):
        """Where scans are for each split."""
        return ""

    def get_valid_frame_path(self, split, scan):
        """returns the filepath of a file that contains valid frame ids for a
        scan."""

        raise NotImplementedError()

    def get_valid_frame_ids(self, split, scan, store_computed=True):
        """Either loads or computes the ids of valid frames in the dataset for
        a scan.

        A valid frame is one that has an existing RGB frame, an existing
        depth file, and existing pose file where the pose isn't inf, -inf,
        or nan.

        Args:
            split: the data split (train/val/test)
            scan: the name of the scan
            store_computed: store the valid_frame file where we'd expect to
            see the file in the scan folder. get_valid_frame_path defines
            where this file is expected to be. If the file can't be saved,
            a warning will be printed and the exception reason printed.

        Returns:
            valid_frames: a list of strings with info on valid frames.
            Each string is a concat of the scan_id and the frame_id.
        """
        raise NotImplementedError()

    def get_color_filepath(self, scan_id, frame_id):
        """returns the filepath for a frame's color file at the dataset's
        configured RGB resolution.

        Args:
            scan_id: the scan this file belongs to.
            frame_id: id for the frame.

        Returns:
            Either the filepath for a precached RGB file at the size
            required, or if that doesn't exist, the full size RGB frame
            from the dataset.

        """
        raise NotImplementedError()

    def get_high_res_color_filepath(self, scan_id, frame_id):
        """returns the filepath for a frame's higher res color file at the
        dataset's configured high RGB resolution.

        Args:
            scan_id: the scan this file belongs to.
            frame_id: id for the frame.

        Returns:
            Either the filepath for a precached RGB file at the high res
            size required, or if that doesn't exist, the full size RGB frame
            from the dataset.

        """

        raise NotImplementedError()

    def get_cached_seg_filepath(self, scan_id, frame_id):
        """returns the filepath for a frame's segmentation file at the native
        resolution in the dataset.

        Args:
            scan_id: the scan this file belongs to.
            frame_id: id for the frame.

        Returns:
            Either the filepath for a precached segmentation file at the size
            required, or if that doesn't exist, the full size segmentation frame
            from the dataset.

        """
        raise NotImplementedError()

    def get_cached_depth_filepath(self, scan_id, frame_id):
        """returns the filepath for a frame's depth file at the dataset's
        configured depth resolution.

        Args:
            scan_id: the scan this file belongs to.
            frame_id: id for the frame.

        Returns:
            Filepath for a precached depth file at the size
            required.

        """
        raise NotImplementedError()

    def get_full_res_depth_filepath(self, scan_id, frame_id):
        """returns the filepath for a frame's depth file at the native
        resolution in the dataset.

        Args:
            scan_id: the scan this file belongs to.
            frame_id: id for the frame.

        Returns:
            Either the filepath for a precached depth file at the size
            required, or if that doesn't exist, the full size depth frame
            from the dataset.

        """
        raise NotImplementedError()

    def get_pose_filepath(self, scan_id, frame_id):
        """returns the filepath for a frame's pose file.

        Args:
            scan_id: the scan this file belongs to.
            frame_id: id for the frame.

        Returns:
            Filepath for pose information.

        """
        raise NotImplementedError()

    def get_frame_id_string(self, frame_id):
        """Returns an id string for this frame_id that's unique to this frame
        within the scan.

        This string is what this dataset uses as a reference to store files
        on disk.
        """
        raise NotImplementedError()

    def get_gt_mesh_path(dataset_path, split, scan_id):
        """
        Returns a path to a gt mesh reconstruction file.
        """
        raise NotImplementedError()

    def load_intrinsics(self, scan_id, frame_id=None, flip=None):
        """Loads intrinsics, computes scaled intrinsics, and returns a dict
        with intrinsics matrices for a frame at multiple scales.

        Args:
            scan_id: the scan this file belongs to.
            frame_id: id for the frame. Not needed for ScanNet as images
            share intrinsics across a scene.
            flip: flips intrinsics along x for flipped images.

        Returns:
            output_dict: A dict with
                - K_s{i}_b44 (intrinsics) and invK_s{i}_b44
                (backprojection) where i in [0,1,2,3,4]. i=0 provides
                intrinsics at the scale for depth_b1hw.
                - K_full_depth_b44 and invK_full_depth_b44 provides
                intrinsics for the maximum available depth resolution.
                Only provided when include_full_res_depth is true.

        """
        raise NotImplementedError()

    def load_target_size_depth_and_mask(self, scan_id, frame_id):
        """Loads a depth map at the resolution the dataset is configured for.

        Internally, if the loaded depth map isn't at the target resolution,
        the depth map will be resized on-the-fly to meet that resolution.

        NOTE: This function will place NaNs where depth maps are invalid.

        Args:
            scan_id: the scan this file belongs to.
            frame_id: id for the frame.

        Returns:
            depth: depth map at the right resolution. Will contain NaNs
                where depth values are invalid.
            mask: a float validity mask for the depth maps. (1.0 where depth
            is valid).
            mask_b: like mask but boolean.
        """
        raise NotImplementedError()

    def load_full_res_depth_and_mask(self, scan_id, frame_id):
        """Loads a depth map at the native resolution the dataset provides.

        NOTE: This function will place NaNs where depth maps are invalid.

        Args:
            scan_id: the scan this file belongs to.
            frame_id: id for the frame.

        Returns:
            full_res_depth: depth map at the right resolution. Will contain
                NaNs where depth values are invalid.
            full_res_mask: a float validity mask for the depth maps. (1.0
            where depth is valid).
            full_res_mask_b: like mask but boolean.
        """
        raise NotImplementedError()

    def load_and_process_seg_ego_mask(self, scan_id, frame_id, target_height, target_width):
        """Loads and processes segmentation and ego masks, combining them into a single mask.

        This is an optional method that subclasses can override. By default returns None.

        Args:
            scan_id: the scan this file belongs to.
            frame_id: id for the frame.
            target_height: target height to resize the mask to.
            target_width: target width to resize the mask to.

        Returns:
            seg_ego_mask: combined segmentation and ego mask as a boolean tensor,
                         or None if masks don't exist or method not implemented.
        """
        return None

    def load_pose(self, scan_id, frame_id):
        """Loads a frame's pose file.

        Args:
            scan_id: the scan this file belongs to.
            frame_id: id for the frame.

        Returns:
            world_T_cam (numpy array): matrix for transforming from the
                camera to the world (pose).
            cam_T_world (numpy array): matrix for transforming from the
                world to the camera (extrinsics).

        """
        raise NotImplementedError()

    def load_color(self, scan_id, frame_id, crop=None):
        """Loads a frame's RGB file, resizes it to configured RGB size.

        Args:
            scan_id: the scan this file belongs to.
            frame_id: id for the frame.

        Returns:
            iamge: tensor of the resized RGB image at self.image_height and
            self.image_width resolution.

        """
        color_filepath = self.get_color_filepath(scan_id, frame_id)
        try:
            image = read_image_file(
                color_filepath,
                height=self.image_height,
                width=self.image_width,
                resampling_mode=self.image_resampling_mode,
                disable_warning=True,
                crop=crop,
            )
        except:
            print("Failed to load: ", scan_id, frame_id)
            image = torch.zeros((3, self.image_height, self.image_width)).float()

        # Remove alpha channel for PNGs
        image = image[:3]

        return image

    def load_high_res_color(self, scan_id, frame_id):
        """Loads a frame's RGB file at a high resolution as configured.

        Args:
            scan_id: the scan this file belongs to.
            frame_id: id for the frame.

        Returns:
            iamge: tensor of the resized RGB image at
            self.high_res_image_height and self.high_res_image_width
            resolution.

        """

        color_high_res_filepath = self.get_high_res_color_filepath(scan_id, frame_id)
        high_res_color = read_image_file(
            color_high_res_filepath,
            height=self.high_res_image_height,
            width=self.high_res_image_width,
            resampling_mode=self.image_resampling_mode,
            disable_warning=self.disable_resize_warning,
        )

        # Remove alpha channel for PNGs
        high_res_color = high_res_color[:3]

        return high_res_color
    
    def load_high_res_origin_color(self, scan_id, frame_id):
        """load high res color
        
        Args:
            scan_id: the scan this file belongs to.
            frame_id: id for the frame.
            
        Returns:
            high_res_color
        """
        color_high_res_filepath = self.get_high_res_color_filepath(scan_id, frame_id)
        
        high_res_color = read_image_file(
            color_high_res_filepath,
            height=None,
            width=None,
            resampling_mode=self.image_resampling_mode,
            disable_warning=True,
        )
        
        # Remove alpha channel for PNGs
        high_res_color = high_res_color[:3]
        
        return high_res_color

    def load_high_res_origin_seg(self, scan_id, frame_id):
        """load high res segmentation
        
        Args:
            scan_id: the scan this file belongs to.
            frame_id: id for the frame.
            
        Returns:
            high_res_seg: segmentation mask as numpy array (H, W)
        """
        seg_result = self.get_cached_seg_filepath(scan_id, frame_id)
        if isinstance(seg_result, tuple):
            seg_mask_filepath, static_seg_mask_filepath = seg_result
        else:
            seg_mask_filepath = seg_result
        
        high_res_seg = cv2.imread(seg_mask_filepath, cv2.IMREAD_UNCHANGED).astype(np.uint8)
        
        return high_res_seg

    def get_frame(self, scan_id, frame_id, load_depth, load_mask=True, flip=False):
        """Retrieves a single frame's worth of information.

        NOTE: Returned depth maps will use NaN for values where the depth
        map is invalid.

        Args:
            scan_id: a string defining the scan this frame belongs to.
            frame_id: an integer id for this frame.
            load_depth: a bool flag for loading depth maps and not dummy
                data
            flip: flips images, depth maps, and intriniscs along x.
        Returns:
            output_dict: a dictionary with this frame's information,
            including:
             - image_b3hw: an imagenet normalized RGB tensor of the image,
                resized to [self.image_height, self.image_width].
             - depth_b1hw: groundtruth depth map for this frame tensor,
                resized to [self.depth_height, self.depth_width.]
             - mask_b1hw: valid float mask where 1.0 indicates a valid depth
                value in depth_b1hw.
             - mask_b_b1hw: like mask_b1hw but binary.
             - world_T_cam_b44: transform for transforming points from
                camera to world coordinates. (pose)
             - cam_T_world_b44: transform for transforming points from world
                to camera coordinaetes. (extrinsics)
             - intrinsics: a dictionary with intrinsics at various
                resolutions and their inverses. Includes:
                    - K_s{i}_b44 (intrinsics) and invK_s{i}_b44
                    (backprojection) where i in [0,1,2,3,4]. i=0 provides
                    intrinsics at the scale for depth_b1hw.
                    - K_full_depth_b44 and invK_full_depth_b44 provides
                    intrinsics for the maximum available depth resolution.
                    Only provided when include_full_res_depth is true.
             - frame_id_string: a string that uniquly identifies the frame
                as it is on disk in its filename. Provided when
                pass_frame_id is true.
             - high_res_color_b3hw: an imagenet normalized RGB tensor of the
                image, at 640 (w) by 480 (h) resolution.
                Provided when include_high_res_color is true.
             - full_res_depth_b1hw: highest resolution depth map available.
                Will only be available if include_full_res_depth is true.
                Provided when include_full_res_depth is true.
             - full_res_mask_b1hw: valid float mask where 1.0 indicates a
                valid depth value in full_res_depth_b1hw.
                Provided when include_full_res_depth is true.
             - full_res_mask_b_b1hw: like full_res_mask_b1hw but binary.
             - min_depth: minimum depth in the gt
             - max_depth: maximum depth value in the gt

        """
        # stores output
        output_dict = {}

        # load pose
        world_T_cam, cam_T_world = self.load_pose(scan_id, frame_id)

        # load intrinsics
        intrinsics, crop = self.load_intrinsics(scan_id, frame_id, flip=flip)

        if self.rotate_images:
            T = np.eye(4)
            T[:3, :3] = rotz(-np.pi / 2)
            world_T_cam = world_T_cam @ T
            cam_T_world = np.linalg.inv(world_T_cam)

        if flip:
            T = np.eye(4).astype(world_T_cam.dtype)
            T[0, 0] = -1.0
            world_T_cam = world_T_cam @ T
            cam_T_world = np.linalg.inv(world_T_cam)

        # Load image
        image = self.load_color(scan_id, frame_id, crop)

        if self.rotate_images:
            image = torch.rot90(image, 3, [1, 2])

        if flip:
            image = torch.flip(image, (-1,))

        # Do imagenet normalization
        image = imagenet_normalize(image)

        world_T_cam_tensor = torch.tensor(world_T_cam, dtype=torch.float32)
        cam_T_world_tensor = torch.tensor(cam_T_world, dtype=torch.float32)

        output_dict.update(
            {
                "image_b3hw": image,
                "world_T_cam_b44": world_T_cam_tensor,
                "cam_T_world_b44": cam_T_world_tensor,
            }
        )

        intrinsics_tensors = {}
        for key, value in intrinsics.items():
            if isinstance(value, torch.Tensor):
                intrinsics_tensors[key] = value.clone()
            else:
                intrinsics_tensors[key] = torch.tensor(value, dtype=torch.float32)

        output_dict.update(intrinsics_tensors)
        output_dict.update(intrinsics)

        seg_ego_mask = None
        if load_mask:
            seg_ego_mask = self.load_and_process_seg_ego_mask(
                scan_id, frame_id, self.depth_height, self.depth_width
            )

        if load_depth:
            depth_outputs = self.load_target_size_depth_and_mask(scan_id, frame_id, crop)
            
            if len(depth_outputs) == 3:
                depth, mask, mask_b = depth_outputs
                skymask = torch.full_like(mask, torch.nan)
            else:
                depth, mask, mask_b = depth_outputs[:3]
                skymask = torch.full_like(mask, torch.nan)

            if seg_ego_mask is not None:
                mask_b = mask_b & seg_ego_mask.unsqueeze(0)
                mask = mask_b.float()

            if self.rotate_images:
                depth = torch.rot90(depth, 3, [1, 2])
                mask = torch.rot90(mask, 3, [1, 2])
                mask_b = torch.rot90(mask_b, 3, [1, 2])
                skymask = torch.rot90(skymask, 3, [1, 2])
                if seg_ego_mask is not None:
                    seg_ego_mask = torch.rot90(seg_ego_mask.unsqueeze(0), 3, [1, 2]).squeeze(0)

            if flip:
                depth = torch.flip(depth, (-1,))
                mask = torch.flip(mask, (-1,))
                mask_b = torch.flip(mask_b, (-1,))
                skymask = torch.flip(skymask, (-1,))
                if seg_ego_mask is not None:
                    seg_ego_mask = torch.flip(seg_ego_mask, (-1,))

            max_depth = depth[torch.isfinite(depth)].max() if torch.isfinite(depth).any().item() else torch.tensor(10.0)
            min_depth = depth[torch.isfinite(depth)].min() if torch.isfinite(depth).any().item() else torch.tensor(10.0)

            max_depth = max_depth * (torch.rand(1)[0] + 1.0)
            min_depth = min_depth * (torch.rand(1)[0] * 0.5 + 0.5)

            output_dict.update(
                {
                    "depth_b1hw": depth,
                    "mask_b1hw": mask,
                    "mask_b_b1hw": mask_b,
                    "max_depth": max_depth,
                    "min_depth": min_depth,
                    "skymask_b1hw": skymask,
                }
            )
            
            if seg_ego_mask is not None:
                output_dict["seg_ego_mask_b1hw"] = seg_ego_mask.unsqueeze(0) if seg_ego_mask.dim() == 2 else seg_ego_mask
        else:
            mask_b = seg_ego_mask.unsqueeze(0)
            mask = mask_b.float()

            if self.rotate_images:
                mask = torch.rot90(mask, 3, [1, 2])
                mask_b = torch.rot90(mask_b, 3, [1, 2])
            
            if flip:
                mask = torch.flip(mask, (-1,))
                mask_b = torch.flip(mask_b, (-1,))

            output_dict.update(
                {
                    "mask_b1hw": mask,
                    "mask_b_b1hw": mask_b
                }
            )

        # Load high res image
        if self.include_high_res_color:
            high_res_color = self.load_high_res_origin_color(scan_id, frame_id)
            high_res_color = imagenet_normalize(high_res_color)

            if self.rotate_images:
                high_res_color = torch.rot90(high_res_color, 3, [1, 2])

            if flip:
                high_res_color = torch.flip(high_res_color, (-1,))

            # load high res segmentation
            high_res_seg = self.load_high_res_origin_seg(scan_id, frame_id)
            high_res_seg = torch.from_numpy(high_res_seg)
            
            if self.rotate_images:
                high_res_seg = torch.rot90(high_res_seg, 3, [0, 1])
            
            if flip:
                high_res_seg = torch.flip(high_res_seg, (-1,))

            output_dict.update(
                {
                    "high_res_color_b3hw": high_res_color,
                    "high_res_seg_bhw": high_res_seg,
                }
            )

        cam_id = self.extract_cam_id(scan_id, frame_id)

        frame_key = self._get_frame_index(scan_id, frame_id)
        frame_metadata = self.capture_metadata[scan_id][frame_key]
        native_depth_width, native_depth_height = frame_metadata["depthResolution"]
        full_res_seg_ego_mask = None
        full_res_seg_ego_mask = self.load_and_process_seg_ego_mask(
                scan_id, frame_id, native_depth_height, native_depth_width
            )

        if self.include_full_res_depth:
            # get high res depth
            full_res_result = self.load_full_res_depth_and_mask(
                scan_id, frame_id, crop
            )
            
            if len(full_res_result) == 3:
                full_res_depth, full_res_mask, full_res_mask_b = full_res_result
            else:
                full_res_depth, full_res_mask, full_res_mask_b = full_res_result[:3]

            if full_res_seg_ego_mask is not None:
                full_res_mask_b = full_res_mask_b & full_res_seg_ego_mask.unsqueeze(0)
                full_res_mask = full_res_mask_b.float()

            if self.rotate_images:
                full_res_depth = torch.rot90(full_res_depth, 3, [1, 2])
                full_res_mask = torch.rot90(full_res_mask, 3, [1, 2])
                full_res_mask_b = torch.rot90(full_res_mask_b, 3, [1, 2])
                if full_res_seg_ego_mask is not None:
                    full_res_seg_ego_mask = torch.rot90(full_res_seg_ego_mask.unsqueeze(0), 3, [1, 2]).squeeze(0)

            if flip:
                full_res_depth = torch.flip(full_res_depth, (-1,))
                full_res_mask = torch.flip(full_res_mask, (-1,))
                full_res_mask_b = torch.flip(full_res_mask_b, (-1,))
                if full_res_seg_ego_mask is not None:
                    full_res_seg_ego_mask = torch.flip(full_res_seg_ego_mask, (-1,))

            output_dict.update(
                {
                    "full_res_depth_b1hw": full_res_depth,
                    "full_res_mask_b1hw": full_res_mask,
                    "full_res_mask_b_b1hw": full_res_mask_b,
                }
            )
        else:
            full_res_mask_b = full_res_seg_ego_mask.unsqueeze(0)
            full_res_mask = full_res_mask_b.float()

            if self.rotate_images:
                full_res_mask = torch.rot90(full_res_mask, 3, [1, 2])
                full_res_mask_b = torch.rot90(full_res_mask_b, 3, [1, 2])
                if full_res_seg_ego_mask is not None:
                    full_res_seg_ego_mask = torch.rot90(full_res_seg_ego_mask.unsqueeze(0), 3, [1, 2]).squeeze(0)
            
            if flip:
                full_res_mask = torch.flip(full_res_mask, (-1,))
                full_res_mask_b = torch.flip(full_res_mask_b, (-1,))
                if full_res_seg_ego_mask is not None:
                    full_res_seg_ego_mask = torch.flip(full_res_seg_ego_mask, (-1,))

            output_dict.update(
                {
                    "full_res_mask_b1hw": full_res_mask,
                    "full_res_mask_b_b1hw": full_res_mask_b,
                }
            )
        
        if full_res_seg_ego_mask is not None:
            output_dict["full_res_seg_ego_mask_b1hw"] = full_res_seg_ego_mask.unsqueeze(0) if full_res_seg_ego_mask.dim() == 2 else full_res_seg_ego_mask

        if self.pass_frame_id:
            output_dict["frame_id_string"] = self.get_frame_id_string(frame_id)
        
        if cam_id is not None:
            output_dict["cam_id"] = cam_id

        for key, value in list(output_dict.items()):
            if isinstance(value, torch.Tensor):
                output_dict[key] = value.clone().contiguous()

        return output_dict

    def _get_frame_index(self, scan_id, frame_id):
        self.load_capture_metadata(scan_id)
        frames = self.capture_metadata[scan_id]
        
        if isinstance(frames, dict):
            frame_key = str(frame_id)
            if frame_key in frames:
                return frame_key
            raise KeyError(f"Frame ID {frame_id} (sequence={frame_key}) not found in capture.json for scan {scan_id}")
        
        frame_id_int = int(frame_id)
        for idx, frame in enumerate(frames):
            if frame.get("sequence") == frame_id_int:
                return idx
        
        raise KeyError(f"Frame ID {frame_id} not found in capture.json for scan {scan_id}")

    def extract_cam_id(self, scan_id, frame_id):
        self.load_capture_metadata(scan_id)
        frame_key = self._get_frame_index(scan_id, frame_id)
        frame_metadata = self.capture_metadata[scan_id][frame_key]
        image_path = frame_metadata["image"]
        cam_match = re.search(r'/cam(\d+)/', image_path)
        return cam_match.group(1) if cam_match else None

    @staticmethod
    def _normalize_cam_id_value(cam_value):
        if cam_value is None:
            return None
        cam_str = str(cam_value).strip()
        if not cam_str:
            return None
        match = re.search(r"(\d+)", cam_str)
        if match:
            return match.group(1)
        cam_str = cam_str.replace("cam", "")
        return cam_str or None

    def _normalize_allowed_cam_ids(self, allowed_cam_ids):
        if not allowed_cam_ids:
            return None
        normalized = set()
        for cam_id in allowed_cam_ids:
            normalized_value = self._normalize_cam_id_value(cam_id)
            if normalized_value is not None:
                normalized.add(normalized_value)
        return normalized if normalized else None

    def _filter_frame_tuples_by_cam(self, split):
        if not hasattr(self, "frame_tuples"):
            return
        filtered_tuples = []
        skipped = 0
        failures = 0
        for frame_tuple in self.frame_tuples:
            tokens = frame_tuple.strip().split()
            if len(tokens) < 2:
                continue
            scan_id, ref_frame_id = tokens[0], tokens[1]
            try:
                cam_id = self.extract_cam_id(scan_id, ref_frame_id)
            except Exception as exc:
                failures += 1
                print(f"Failed to extract cam_id for scan {scan_id} frame {ref_frame_id}: {exc}")
                filtered_tuples.append(frame_tuple)
                continue
            cam_id_normalized = self._normalize_cam_id_value(cam_id)
            if cam_id_normalized in self.allowed_cam_ids:
                filtered_tuples.append(frame_tuple)
            else:
                skipped += 1
        if skipped > 0:
            print(f"{self.__class__.__name__}: filtered {skipped} tuples by allowed_cam_ids {sorted(self.allowed_cam_ids)}")
        if failures > 0:
            print(f"{self.__class__.__name__}: failed to determine cam_id for {failures} tuples; kept them unfiltered")
        if not filtered_tuples:
            print(f"{self.__class__.__name__}[{split}]: no tuples left after cam_id filtering. Check allowed_cam_ids configuration.")
        else:
            self.frame_tuples = filtered_tuples

    def stack_src_data(self, src_data):
        """Stacks source image data into tensors."""

        tensor_names = src_data[0].keys()
        stacked_src_data = {}
        for tensor_name in tensor_names:
            if (
                "frame_id_string" in tensor_name
                or "frame_id" in tensor_name
                or "cam_id" in tensor_name
            ):
                stacked_src_data[tensor_name] = [t[tensor_name] for t in src_data]
                continue

            values = [t[tensor_name] for t in src_data]
            first_value = values[0]

            if isinstance(first_value, torch.Tensor):
                tensors = [
                    value.clone().contiguous()
                    if isinstance(value, torch.Tensor)
                    else torch.as_tensor(value).clone().contiguous()
                    for value in values
                ]
                
                if ("high_res" in tensor_name or "full_res" in tensor_name) and len(tensors) > 1 and len(tensors[0].shape) >= 2:
                    first_shape = tensors[0].shape
                    spatial_dims = first_shape[-2:]
                    
                    all_same_size = all(
                        t.shape[-2:] == spatial_dims for t in tensors
                    )
                    
                    if not all_same_size:
                        print(f"MVSA resizing tensors for {tensor_name}, spatial_dims: {spatial_dims}")
                        max_h = max(t.shape[-2] for t in tensors)
                        max_w = max(t.shape[-1] for t in tensors)
                        
                        resized_tensors = []
                        for t in tensors:
                            if t.shape[-2:] != (max_h, max_w):
                                # Check if tensor is boolean type
                                is_bool = t.dtype == torch.bool
                                # Convert bool to float for interpolation
                                if is_bool:
                                    t = t.float()
                                
                                if len(t.shape) == 3:  # [C, H, W]
                                    interpolate_kwargs = {'size': (max_h, max_w), 'mode': 'nearest' if is_bool else 'bilinear'}
                                    if not is_bool:
                                        interpolate_kwargs['align_corners'] = False
                                    t = F.interpolate(
                                        t.unsqueeze(0),
                                        **interpolate_kwargs
                                    ).squeeze(0)
                                elif len(t.shape) == 2:  # [H, W]
                                    interpolate_kwargs = {'size': (max_h, max_w), 'mode': 'nearest' if is_bool else 'bilinear'}
                                    if not is_bool:
                                        interpolate_kwargs['align_corners'] = False
                                    t = F.interpolate(
                                        t.unsqueeze(0).unsqueeze(0),
                                        **interpolate_kwargs
                                    ).squeeze(0).squeeze(0)
                                elif len(t.shape) == 4:  # [B, C, H, W] or similar
                                    interpolate_kwargs = {'size': (max_h, max_w), 'mode': 'nearest' if is_bool else 'bilinear'}
                                    if not is_bool:
                                        interpolate_kwargs['align_corners'] = False
                                    t = F.interpolate(
                                        t,
                                        **interpolate_kwargs
                                    )
                                else:
                                    # For other shapes, try to interpolate the last 2 dims
                                    interpolate_kwargs = {'size': (max_h, max_w), 'mode': 'nearest' if is_bool else 'bilinear'}
                                    if not is_bool:
                                        interpolate_kwargs['align_corners'] = False
                                    t = F.interpolate(
                                        t.unsqueeze(0) if len(t.shape) < 4 else t,
                                        **interpolate_kwargs
                                    )
                                    if len(t.shape) == 4 and len(first_shape) == 3:
                                        t = t.squeeze(0)
                                
                                # Convert back to bool if original was bool
                                if is_bool:
                                    t = t.bool()
                            resized_tensors.append(t.contiguous())
                        tensors = resized_tensors
                
                stacked_value = torch.stack(tensors, dim=0).contiguous()
            elif isinstance(first_value, np.ndarray):
                stacked_value = torch.tensor(
                    np.stack(values, axis=0), dtype=torch.as_tensor(first_value).dtype
                ).contiguous()
            else:
                stacked_value = torch.tensor(values).contiguous()

            stacked_src_data[tensor_name] = stacked_value.contiguous()

        return stacked_src_data

    def __getitem__(self, idx):
        """Loads data for all frames for the MVS tuple at index idx.

        Args:
            idx: the index for the elmeent in the dataset.

        Returns:
            cur_data: frame data for the reference frame
            src_data: stacked frame data for each source frame
        """

        flip_threshold = 0.5 if self.split == "train" and not self.disable_flip else 0.0
        flip = torch.rand(1).item() < flip_threshold

        # get the index of the tuple
        scan_id, *frame_ids = self.frame_tuples[idx].split(" ")

        # shuffle tuple order, by default false
        if self.shuffle_tuple:
            first_frame_id = frame_ids[0]
            shuffled_list = frame_ids[1:]
            random.shuffle(shuffled_list)
            frame_ids = [first_frame_id] + shuffled_list

        # the tuple file may have more images in the tuple than what might be
        # requested, so limit the tuple length to num_images_in_tuple
        if self.num_images_in_tuple is not None:
            frame_ids = frame_ids[: self.num_images_in_tuple]

        # assemble the dataset element by getting all data for each frame
        inputs = []
        if self.split == "train":
            for frame_ind, frame_id in enumerate(frame_ids):
                inputs += [
                    self.get_frame(
                        scan_id,
                        frame_id,
                        load_depth=(frame_ind == 0),
                        load_mask=True,
                        flip=flip
                    )
                ]
        else:
            for frame_ind, frame_id in enumerate(frame_ids):
                inputs += [
                    self.get_frame(
                        scan_id,
                        frame_id,
                        load_depth=False,
                        load_mask=True,
                        flip=flip
                    )
                ]

        # cur_data is the reference frame
        cur_data, *src_data_list = inputs
        # src_data contains data for all source frames
        src_data = self.stack_src_data(src_data_list)

        # now sort all source frames (src_data) according to pose penalty w.r.t
        # to the refernce frame (cur_data)
        if not self.shuffle_tuple:
            if isinstance(src_data["world_T_cam_b44"], torch.Tensor):
                src_world_T_cam = src_data["world_T_cam_b44"].clone().detach()
            else:
                src_world_T_cam = torch.tensor(src_data["world_T_cam_b44"], dtype=torch.float32)
            
            if isinstance(cur_data["cam_T_world_b44"], torch.Tensor):
                cur_cam_T_world = cur_data["cam_T_world_b44"].clone().detach()
            else:
                cur_cam_T_world = torch.tensor(cur_data["cam_T_world_b44"], dtype=torch.float32)

            # Compute cur_cam_T_src_cam
            cur_cam_T_src_cam = cur_cam_T_world.unsqueeze(0) @ src_world_T_cam

            # get penalties.
            frame_penalty_k, _, _ = pose_distance(cur_cam_T_src_cam)

            # order based on indices
            indices = torch.argsort(frame_penalty_k).tolist()
            src_data_list = [src_data_list[index] for index in indices]

            # stack again
            src_data = self.stack_src_data(src_data_list)

        return cur_data, src_data