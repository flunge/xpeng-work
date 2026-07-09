import json
import logging
import os

import cv2
import numpy as np
import PIL.Image as pil
import torch
import torch.nn.functional as F
from torchvision import transforms

from mvsnet.mvsa.src.mvsanywhere.datasets.generic_mvs_dataset import GenericMVSDataset

logger = logging.getLogger(__name__)


class XPengDataset(GenericMVSDataset):
    """
    Reads a XPeng scan folder.

    self.capture_metadata is a dictionary indexed with a scan's id and is
    populated with a scan's frame information when a frame is loaded for the
    first time from that scan.

    This class loads depth data from .npy files and supports multi-camera setup.

    Inherits from GenericMVSDataset and implements missing methods.
    """

    def __init__(
        self,
        dataset_path,
        split,
        mv_tuple_file_suffix="_tuples.txt",
        include_full_res_depth=False,
        limit_to_scan_id=None,
        num_images_in_tuple=None,
        tuple_info_file_location=None,
        image_height=384,
        image_width=512,
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
        disable_flip=False,
        rotate_images=False,
        matching_scale=0.25,
        prediction_scale=0.5,
        prediction_num_scales=5,
        allowed_cam_ids=None,
    ):
        self.capture_metadata = {}
        
        super().__init__(
            dataset_path=dataset_path,
            split=split,
            mv_tuple_file_suffix=mv_tuple_file_suffix,
            include_full_res_depth=include_full_res_depth,
            limit_to_scan_id=limit_to_scan_id,
            num_images_in_tuple=num_images_in_tuple,
            tuple_info_file_location=tuple_info_file_location,
            image_height=image_height,
            image_width=image_width,
            high_res_image_width=high_res_image_width,
            high_res_image_height=high_res_image_height,
            image_depth_ratio=image_depth_ratio,
            shuffle_tuple=shuffle_tuple,
            include_full_depth_K=include_full_depth_K,
            include_high_res_color=include_high_res_color,
            pass_frame_id=pass_frame_id,
            skip_frames=skip_frames,
            skip_to_frame=skip_to_frame,
            verbose_init=verbose_init,
            disable_flip=disable_flip,
            matching_scale=matching_scale,
            prediction_scale=prediction_scale,
            prediction_num_scales=prediction_num_scales,
            allowed_cam_ids=allowed_cam_ids,
        )

        self.image_resampling_mode = pil.BICUBIC

    @staticmethod
    def get_sub_folder_dir(split):
        return "scans"

    def get_frame_id_string(self, frame_id):
        """Returns an id string for this frame_id that's unique to this frame
        within the scan.

        This string is what this dataset uses as a reference to store files
        on disk.
        """
        return frame_id

    def get_valid_frame_path(self, split, scan):
        """returns the filepath of a file that contains valid frame ids for a
        scan."""
        scan_dir = os.path.join(self.dataset_path, self.get_sub_folder_dir(split), scan)

        return os.path.join(scan_dir, "valid_frames.txt")

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
        scan = scan.rstrip("\n")
        valid_frame_path = self.get_valid_frame_path(split, scan)

        if os.path.exists(valid_frame_path):
            # valid frame file exists, read that to find the ids of frames with
            # valid poses.
            with open(valid_frame_path) as f:
                valid_frames = f.readlines()
        else:
            print(f"Computing valid frames for scene {scan}.")
            # find out which frames have valid poses

            # load scan metadata
            self.load_capture_metadata(scan)
            color_file_count = len(self.capture_metadata[scan])

            valid_frames = []
            dist_to_last_valid_frame = 0
            bad_file_count = 0
            for frame_ind in range(len(self.capture_metadata[scan])):
                world_T_cam_44, _ = self.load_pose(scan, frame_ind)
                if (
                    np.isnan(np.sum(world_T_cam_44))
                    or np.isinf(np.sum(world_T_cam_44))
                    or np.isneginf(np.sum(world_T_cam_44))
                ):
                    bad_file_count += 1
                    dist_to_last_valid_frame += 1
                    continue

                valid_frames.append(f"{scan} {frame_ind} {dist_to_last_valid_frame}")
                dist_to_last_valid_frame = 0

            print(
                f"Scene {scan} has {bad_file_count} bad frame files out of " f"{color_file_count}."
            )

            # store computed if we're being asked, but wrapped inside a try
            # incase this directory is read only.
            if store_computed:
                # store those files to valid_frames.txt
                try:
                    with open(valid_frame_path, "w") as f:
                        f.write("\n".join(valid_frames) + "\n")
                except Exception as e:
                    print(f"Couldn't save valid_frames at {valid_frame_path}, " f"cause:")
                    print(e)

        return valid_frames

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

        self.load_capture_metadata(scan_id)
        frame_key = self._get_frame_index(scan_id, frame_id)
        frame_metadata = self.capture_metadata[scan_id][frame_key]

        world_T_cam = torch.tensor(frame_metadata["pose4x4"], dtype=torch.float32).view(4, 4)
        world_T_cam = world_T_cam.numpy()
        cam_T_world = np.linalg.inv(world_T_cam)

        return world_T_cam, cam_T_world

    def load_intrinsics(self, scan_id, frame_id, flip=None):
        """Loads intrinsics, computes scaled intrinsics, and returns a dict
        with intrinsics matrices for a frame at multiple scales.

        Args:
            scan_id: the scan this file belongs to.
            frame_id: id for the frame. Not needed for ScanNet as images
            share intrinsics across a scene.
            flip: unused

        Returns:
            output_dict: A dict with
                - K_s{i}_b44 (intrinsics) and invK_s{i}_b44
                (backprojection) where i in [0,1,2,3,4]. i=0 provides
                intrinsics at the scale for depth_b1hw.
                - K_full_depth_b44 and invK_full_depth_b44 provides
                intrinsics for the maximum available depth resolution.
                Only provided when include_full_res_depth is true.

        """
        output_dict = {}

        self.load_capture_metadata(scan_id)
        frame_key = self._get_frame_index(scan_id, frame_id)
        frame_metadata = self.capture_metadata[scan_id][frame_key]

        image_width, image_height = frame_metadata["resolution"]

        # XPeng uses 3x3 intrinsics matrix format
        intrinsics_matrix = np.array(frame_metadata["intrinsics"])
        fx = intrinsics_matrix[0, 0]
        fy = intrinsics_matrix[1, 1]
        cx = intrinsics_matrix[0, 2]
        cy = intrinsics_matrix[1, 2]

        native_depth_width, native_depth_height = frame_metadata["depthResolution"]

        K = torch.eye(4, dtype=torch.float32)
        K[0, 0] = float(fx)
        K[1, 1] = float(fy)
        K[0, 2] = float(cx)
        K[1, 2] = float(cy)

        # optionally include the intrinsics matrix for the full res depth map.
        if self.include_full_depth_K:
            full_K = K.clone()

            full_K[0] *= native_depth_width / image_width
            full_K[1] *= native_depth_height / image_height

            output_dict[f"K_full_depth_b44"] = full_K.clone()
            if self.rotate_images:
                temp = output_dict[f"K_full_depth_b44"].clone()
                output_dict[f"K_full_depth_b44"][0, 0] = temp[1, 1]
                output_dict[f"K_full_depth_b44"][1, 1] = temp[0, 0]
                output_dict[f"K_full_depth_b44"][1, 2] = temp[0, 2]
                output_dict[f"K_full_depth_b44"][0, 2] = native_depth_height - temp[1, 2]
            output_dict[f"invK_full_depth_b44"] = torch.linalg.inv(output_dict[f"K_full_depth_b44"])

        K_matching = K.clone()
        K_matching[0] *= self.matching_width / float(image_width)
        K_matching[1] *= self.matching_height / float(image_height)
        output_dict["K_matching_b44"] = K_matching
        output_dict["invK_matching_b44"] = torch.linalg.inv(K_matching)

        # scale intrinsics to the dataset's configured depth resolution.
        K[0] *= self.depth_width / image_width
        K[1] *= self.depth_height / image_height
        if self.rotate_images:
            temp = K.clone()
            K[0, 0] = temp[1, 1]
            K[1, 1] = temp[0, 0]
            K[1, 2] = temp[0, 2]
            K[0, 2] = self.depth_height - temp[1, 2]

        # Get the intrinsics of all scales at various resolutions.
        for i in range(self.prediction_num_scales):
            K_scaled = K.clone()
            K_scaled[:2] /= 2**i # 2**0, 2**1, 2**2, 2**3, 2**4
            invK_scaled = torch.linalg.inv(K_scaled)
            output_dict[f"K_s{i}_b44"] = K_scaled
            output_dict[f"invK_s{i}_b44"] = invK_scaled

        return output_dict, None

    def load_capture_metadata(self, scan_id):
        """Reads a xpeng scan file and loads metadata for that scan into
        self.capture_metadata

        It does this by loading a metadata json file that contains frame
        RGB information, intrinsics, and poses for each frame.

        Metadata for each scan is cached in the dictionary
        self.capture_metadata.

        Args:
            scan_id: a scan_id whose metadata will be read.
        """
        if scan_id in self.capture_metadata:
            return

        possible_paths = [
            os.path.join(self.dataset_path, "mvsnet_metadata", "capture.json"),
            os.path.join(self.dataset_path, "capture.json"),
            os.path.join(self.dataset_path, scan_id, "capture.json"),
        ]
        
        metadata_path = None
        for path in possible_paths:
            if os.path.exists(path):
                metadata_path = path
                break
        
        if metadata_path is None:
            raise FileNotFoundError(f"capture.json not found. Tried: {possible_paths}")

        with open(metadata_path) as f:
            capture_metadata = json.load(f)

        self.capture_metadata[scan_id] = capture_metadata["frames"]

    def get_cached_depth_filepath(self, scan_id, frame_id):
        """returns the filepath for a frame's depth file at the dataset's
        configured depth resolution.

        Args:
            scan_id: the scan this file belongs to.
            frame_id: id for the frame.

        Returns:
            Either the filepath for a precached depth file at the size
            required, or if that doesn't exist, the full size depth frame
            from the dataset.

        """
        # Use absolute path from capture.json metadata
        self.load_capture_metadata(scan_id)

        frame_key = self._get_frame_index(scan_id, frame_id)
        frame_metadata = self.capture_metadata[scan_id][frame_key]
            
        # Check for cached resized version first
        depth_path = frame_metadata["depth"]
        dir_path = os.path.dirname(depth_path)
        filename = os.path.basename(depth_path)
        name, ext = os.path.splitext(filename)
        cached_path = os.path.join(dir_path, f"{name}.{self.depth_width}{ext}")
        
        if os.path.exists(cached_path):
            return cached_path
        else:
            return depth_path

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
        # Use absolute path from capture.json metadata
        self.load_capture_metadata(scan_id)

        frame_key = self._get_frame_index(scan_id, frame_id)
        frame_metadata = self.capture_metadata[scan_id][frame_key]
            
        # Check for cached resized version first
        seg_path = frame_metadata["seg"]
        dir_path = os.path.dirname(seg_path)
        filename = os.path.basename(seg_path)
        name, ext = os.path.splitext(filename)
        cached_path = os.path.join(dir_path, f"{name}.{self.image_width}{ext}")
        
        static_seg_path = seg_path.replace("seg_mask", "seg_mask_static")
        static_seg_path = os.path.splitext(static_seg_path)[0] + ".npy"
        static_cached_path = cached_path.replace("seg_mask", "seg_mask_static")
        static_cached_path = os.path.splitext(static_cached_path)[0] + ".npy"
        
        if os.path.exists(cached_path):
            final_seg_path = cached_path
        else:
            final_seg_path = seg_path
        
        if os.path.exists(static_cached_path):
            final_static_seg_path = static_cached_path
        else:
            final_static_seg_path = static_seg_path
        
        return final_seg_path, final_static_seg_path

    def get_cached_mask_filepath(self, scan_id, frame_id):
        """returns the filepath for a frame's mask file at the native
        resolution in the dataset.

        Args:
            scan_id: the scan this file belongs to.
            frame_id: id for the frame.

        Returns:
            Either the filepath for a precached mask file at the size
            required, or if that doesn't exist, the full size mask frame
            from the dataset.

        """
        # Use absolute path from capture.json metadata
        self.load_capture_metadata(scan_id)

        frame_key = self._get_frame_index(scan_id, frame_id)
        frame_metadata = self.capture_metadata[scan_id][frame_key]
            
        # Check for cached resized version first
        mask_path = frame_metadata["mask"]
        dir_path = os.path.dirname(mask_path)
        filename = os.path.basename(mask_path)
        name, ext = os.path.splitext(filename)
        cached_path = os.path.join(dir_path, f"{name}.{self.image_width}{ext}")
        
        if os.path.exists(cached_path):
            return cached_path
        else:
            return mask_path

    def load_and_process_seg_ego_mask(self, scan_id, frame_id, target_height, target_width):
        """Loads and processes segmentation and ego masks, combining them into a single mask.

        Args:
            scan_id: the scan this file belongs to.
            frame_id: id for the frame.
            target_height: target height to resize the mask to.
            target_width: target width to resize the mask to.

        Returns:
            seg_ego_mask: combined segmentation and ego mask as a boolean tensor,
                         or None if masks don't exist.
        """
        seg_mask_filepath, static_seg_mask_filepath = self.get_cached_seg_filepath(scan_id, frame_id)
        # ego_mask_filepath = self.get_cached_mask_filepath(scan_id, frame_id)
        
        seg_ego_mask = None
        
        # Load and process seg_mask
        if os.path.exists(seg_mask_filepath):
            seg_mask_hr = cv2.imread(seg_mask_filepath, cv2.IMREAD_UNCHANGED).astype(np.uint8)
            
            # sky: 27, ground lines: 19-22, obj: >= 52
            mask_conditions = [
                (0 <= seg_mask_hr) & (seg_mask_hr <= 1),
                (19 <= seg_mask_hr) & (seg_mask_hr <= 22),
                # seg_mask_hr >= 52,
                seg_mask_hr == 27
            ]
            seg_mask_valid = 1 - np.logical_or.reduce(mask_conditions).astype(np.uint8)
            seg_mask_invalid = cv2.bitwise_not(seg_mask_valid)
            
            kernel = np.ones((10, 10), dtype=np.uint8)
            seg_mask_invalid_dilated = cv2.dilate(seg_mask_invalid, kernel, iterations=2)
            seg_mask_valid = cv2.bitwise_not(seg_mask_invalid_dilated)
            
            seg_mask_valid = cv2.resize(
                seg_mask_valid, (target_width, target_height), interpolation=cv2.INTER_NEAREST
            )
            seg_ego_mask = torch.from_numpy(seg_mask_valid.astype(bool)).clone()
        
        # # Load and process ego_mask
        # if os.path.exists(ego_mask_filepath):
        #     ego_mask = cv2.imread(ego_mask_filepath, cv2.IMREAD_GRAYSCALE)
        #     ego_mask_valid = (ego_mask > 0).astype(np.uint8)
        
        #     ego_mask_valid = cv2.resize(ego_mask_valid, (target_width, target_height),
        #                                interpolation=cv2.INTER_NEAREST)
        #     ego_mask_torch = torch.from_numpy(ego_mask_valid.astype(bool))
        
        #     if seg_ego_mask is not None:
        #         seg_ego_mask = seg_ego_mask & ego_mask_torch
        #     else:
        #         seg_ego_mask = ego_mask_torch
        
        return seg_ego_mask

    def get_cached_confidence_filepath(self, scan_id, frame_id):
        """returns the filepath for a frame's depth confidence file at the
        dataset's configured depth resolution.

        Args:
            scan_id: the scan this file belongs to.
            frame_id: id for the frame.

        Returns:
            Either the filepath for a precached depth confidence file at the
            size required, or if that doesn't exist, the full size depth
            frame from the dataset.

        """
        # cached_resized_path = os.path.join(
        #     self.dataset_path,
        #     self.get_sub_folder_dir(self.split),
        #     scan_id,
        #     f"depthConfidence.{self.depth_width}_" f"{frame_id}.bin",
        # )

        # # check if we have cached resized depth on disk first
        # if os.path.exists(cached_resized_path):
        #     return cached_resized_path

        # # instead return the default image
        # return os.path.join(
        #     self.dataset_path,
        #     self.get_sub_folder_dir(self.split),
        #     scan_id,
        #     f"depthConfidence_{frame_id}.bin",
        # )
        return None

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
        self.load_capture_metadata(scan_id)
        
        frame_key = self._get_frame_index(scan_id, frame_id)
        frame_metadata = self.capture_metadata[scan_id][frame_key]
            
        return frame_metadata["depth"]

    def get_full_res_confidence_filepath(self, scan_id, frame_id):
        """returns the filepath for a frame's depth confidence file at the
        dataset's maximum depth resolution.

        Args:
            scan_id: the scan this file belongs to.
            frame_id: id for the frame.

        Returns:
            Either the filepath for a precached depth confidence file at the
            size required, or if that doesn't exist, the full size depth
            frame from the dataset.

        """
        # return os.path.join(
        #     self.dataset_path,
        #     self.get_sub_folder_dir(self.split),
        #     scan_id,
        #     f"depthConfidence_{frame_id}.bin",
        # )
        return None

    def load_full_res_depth_and_mask(self, scan_id, frame_id, crop=None):
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
        full_res_depth_filepath = self.get_full_res_depth_filepath(scan_id, frame_id)

        self.load_capture_metadata(scan_id)
        
        frame_key = self._get_frame_index(scan_id, frame_id)
        frame_metadata = self.capture_metadata[scan_id][frame_key]
        native_depth_width, native_depth_height = frame_metadata["depthResolution"]

        full_res_depth_np = np.load(
            full_res_depth_filepath, allow_pickle=True
        ).transpose(1, 0).reshape(native_depth_height, native_depth_width)
        full_res_depth = torch.from_numpy(full_res_depth_np).unsqueeze(0).float().clone()

        # confidence_filepath = self.get_full_res_confidence_filepath(scan_id, frame_id)

        # conf = torch.from_numpy(
        #     np.load(confidence_filepath, allow_pickle=True).reshape(
        #         native_depth_height, native_depth_width
        #     )
        # ).unsqueeze(0)

        # full_res_mask_b = conf != 0
        full_res_mask_b = (full_res_depth > 0) & torch.isfinite(full_res_depth)
        
        full_res_mask = full_res_mask_b.float().clone()

        nan_value = float("nan")
        full_res_depth = full_res_depth.clone()
        full_res_depth[~full_res_mask_b] = nan_value

        return full_res_depth, full_res_mask, full_res_mask_b

    def load_target_size_depth_and_mask(self, scan_id, frame_id, crop=None):
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
        depth_filepath = self.get_cached_depth_filepath(scan_id, frame_id)

        self.load_capture_metadata(scan_id)
        frame_key = self._get_frame_index(scan_id, frame_id)
        frame_metadata = self.capture_metadata[scan_id][frame_key]
        native_depth_width, native_depth_height = frame_metadata["depthResolution"]

        if os.path.exists(depth_filepath):
            depth_np = np.load(depth_filepath, allow_pickle=True).reshape(
                native_depth_height, native_depth_width
            )
            depth = torch.from_numpy(depth_np).unsqueeze(0).float().clone()
        else:
            depth_filepath = self.get_full_res_depth_filepath(scan_id, frame_id)
            depth_np = np.load(depth_filepath, allow_pickle=True).reshape(
                native_depth_height, native_depth_width
            )
            depth = torch.from_numpy(depth_np).unsqueeze(0).float().clone()

            depth = F.interpolate(
                depth,
                size=(self.depth_height, self.depth_width),
                mode="nearest",
            )

        depth = F.interpolate(depth[None], size=(self.depth_height, self.depth_width), mode="nearest")[0]

        # confidence_filepath = self.get_cached_confidence_filepath(scan_id, frame_id)

        # if os.path.exists(confidence_filepath):
        #     conf = torch.from_numpy(
        #         np.load(confidence_filepath, allow_pickle=True).reshape(
        #             native_depth_height, native_depth_width
        #         )
        #     ).unsqueeze(0)
        # else:
        #     confidence_filepath = self.get_full_res_confidence_filepath(scan_id, frame_id)
        #     conf = torch.from_numpy(
        #         np.load(confidence_filepath, allow_pickle=True).reshape(
        #             native_depth_height, native_depth_width
        #         )
        #     ).unsqueeze(0)

        #     conf = F.interpolate(conf, size=(self.depth_height, self.depth_width), mode="nearest")
        
        # conf = F.interpolate(conf[None], size=(self.depth_height, self.depth_width), mode="nearest")[0]

        # mask_b = conf != 0
        mask_b = (depth > 0) & torch.isfinite(depth)
        mask = mask_b.float().clone()

        nan_value = float("nan")
        depth = depth.clone()
        depth[~mask_b] = nan_value

        return depth, mask, mask_b

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
        self.load_capture_metadata(scan_id)
        frame_key = self._get_frame_index(scan_id, frame_id)
        frame_metadata = self.capture_metadata[scan_id][frame_key]
            
        # Check for cached resized version first
        image_path = frame_metadata["image"]
        dir_path = os.path.dirname(image_path)
        filename = os.path.basename(image_path)
        name, ext = os.path.splitext(filename)
        cached_path = os.path.join(dir_path, f"{name}.{self.image_width}{ext}")
        
        if os.path.exists(cached_path):
            return cached_path
        else:
            return image_path

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

        self.load_capture_metadata(scan_id)
        frame_key = self._get_frame_index(scan_id, frame_id)
        frame_metadata = self.capture_metadata[scan_id][frame_key]
            
        # Check for cached resized version first
        image_path = frame_metadata["image"]
        dir_path = os.path.dirname(image_path)
        filename = os.path.basename(image_path)
        name, ext = os.path.splitext(filename)
        cached_path = os.path.join(dir_path, f"{name}.{self.high_res_image_height}{ext}")
        
        if os.path.exists(cached_path):
            return cached_path
        else:
            return image_path