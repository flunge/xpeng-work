from copy import deepcopy
import json
import math
import os
import re

import cv2
import numpy as np
from scipy.spatial.transform import Rotation as ScipyRotation

from ..datasets.base import BaseDataset
from ..utility.plane_fit import robust_estimate_flatplane
from ..utility.misc import convert_rel_to_abs_dict
import copy


def compute_between_pose_dist_and_angle(pose1, pose2):
    pose_matrix1= np.array(pose1)
    pose_matrix2= np.array(pose2)

    distance_diff = np.linalg.norm(pose_matrix1[0:3,3] - pose_matrix2[0:3,3])
    angle_diff = np.arccos(np.clip((np.trace(pose_matrix1[0:3,0:3].T @ pose_matrix2[0:3,0:3]) - 1.0) / 2.0, -1.0, 1.0))

    return distance_diff, angle_diff


class XNetDataset(BaseDataset):
    def __init__(self, configs, recon_dataset_param=None):
        super().__init__()

        if configs["mode"] == "reloc":
            assert recon_dataset_param is not None, "recon_dataset_param is required for reloc mode"

        """ Configuration """
        exp_dir = configs['exp_dir']
        cam_list = configs["rome_cam_list"] if "rome_cam_list"in configs else configs["cam_list"]
        print(f"rome_cam_list: {cam_list}")

        ref_cam = configs["ref_cam"]
        cut_range = configs['cut_range']
        assert(ref_cam in cam_list)
        self.training_crop_image_by_label = configs.get("training_crop_image_by_label", True)
        rome_downsample_distance_threshold = configs.get('rome_downsample_distance_threshold', 0.0)
        rome_downsample_angle_threshold = configs.get('rome_downsample_angle_threshold', 0.0)
        self.resized_image_size = (configs["image_width"], configs["image_height"])
        self.cutoff_radius = configs.get("cutoff_radius", 150.0)
        self.use_auto_cut_center = configs.get("use_auto_cut_center", True)
        slice_interval = configs.get("extrinsic_slice_interval", 30)

        ### Get path of trips
        trips_info = json.load(open(configs['trips_json'], 'r'))
        if configs["mode"] == "recon":
            trips_info = convert_rel_to_abs_dict(trips_info, configs["exp_dir"])
        elif configs["mode"] == "reloc":
            trips_info = convert_rel_to_abs_dict(trips_info, configs['reloc_dir'])
        else:
            raise ValueError(f"Unsupported mode: {configs['mode']}")
        trip_list = list(trips_info.keys())

        ### Get cut center
        self.cut_center = None
        if configs["mode"] == "recon":
            if self.use_auto_cut_center:
                self.cut_center = self.get_average_center(trip_list, ref_cam)
            else:
                if "cut_center" in configs:
                    self.cut_center = np.array(configs['cut_center'])
        elif configs["mode"] == "reloc":
            self.cut_center = np.array(recon_dataset_param["cut_center"])

        """ Start loading all filename and poses """
        self.calib_dict = {}
        original_ego_pose_all = []
        cam_name_to_cam_index_map = dict()
        image_name_to_extrinsic_map = dict()
        for trip_image_path in trip_list:
            trip_name = '/'.join(trip_image_path.split('/')[-2:])
            trip_mask_path = 'seg_mask'.join(trip_image_path.rsplit('image', 1))
            trip_calib = json.load(open(os.path.join(trip_image_path, "calib.json"), "r"))
            trip_depth_path = os.path.join(exp_dir, 'dense', 'single_depth', trip_name)
            outlier_cam_list = trip_calib.get("outlier_cam_list", [])

            if ref_cam in outlier_cam_list:
                continue

            """ Load camera intrinsics """
            cam_intrinsics = {}
            cam_intrinsics_all = {}
            for cam in cam_list:
                if outlier_cam_list is not None and cam in outlier_cam_list:
                    continue
                if configs["pose_source"] == "colmap":
                    assert trip_calib["colmap_intrinsic"] != {}
                    focal = trip_calib["colmap_intrinsic"][cam]["focal_length"]
                    cx = trip_calib["colmap_intrinsic"][cam]["cx"]
                    cy = trip_calib["colmap_intrinsic"][cam]["cy"]
                else:
                    focal = trip_calib[cam]["intrinsic"]["focal_length"]
                    cx = trip_calib[cam]["intrinsic"]["cx"]
                    cy = trip_calib[cam]["intrinsic"]["cy"]
                matrix = np.zeros((3, 3))
                matrix[0, 0] = focal
                matrix[1, 1] = focal
                matrix[0, 2] = cx
                matrix[1, 2] = cy
                matrix[2, 2] = 1
                cam_intrinsics[cam] = matrix.astype(np.float32)
                cam_intrinsics_all[cam] = trip_calib[cam]['intrinsic']
            self.calib_dict[trip_name] = cam_intrinsics_all
            assert cam_intrinsics != {}

            """ Load camera extrinsics """
            cam_extrinsics = {}
            for cam in cam_list + [ref_cam]:
                if outlier_cam_list is not None and cam in outlier_cam_list:
                    continue
                matrix = trip_calib[cam]["extrinsic"]["transformation_matrix"]
                cam_extrinsics[cam] = np.linalg.inv(np.array(matrix).astype(np.float32))

            planecam_ext = np.linalg.inv(np.array(trip_calib[ref_cam]["extrinsic"]["transformation_matrix"]).astype(np.float32))

            """ Convert all camera extrinsics to the ref_cam coord system """
            ref2cam_transform = {}
            cam2ref_transform = {}
            for cam in cam_list:
                if outlier_cam_list is not None and cam in outlier_cam_list:
                    continue
                if cam == ref_cam:
                    ref2cam_transform[cam] = np.eye(4)
                    cam2ref_transform[cam] = np.eye(4)
                else:
                    cam_ext = cam_extrinsics[cam] # cam to ego
                    ref_cam_ext = cam_extrinsics[ref_cam] # ref to ego
                    ref2cam_transform[cam] = np.linalg.inv(cam_ext) @ ref_cam_ext
                    cam2ref_transform[cam] = np.linalg.inv(ref2cam_transform[cam])

            if configs["pose_source"] == "colmap":
                for cam in cam_list:
                    if outlier_cam_list is not None and cam in outlier_cam_list:
                        continue
                    cam_slice0_colmap_pose = np.array(trip_calib["colmap_extrinsic"]["slice0_" + cam]).astype(np.float32) # cam to world
                    ref_slice0_colmap_pose = np.array(trip_calib["colmap_extrinsic"][f"slice0_{ref_cam}"]).astype(np.float32) # ref to world
                    ref2cam_transform[cam] = np.linalg.inv(cam_slice0_colmap_pose) @ ref_slice0_colmap_pose
                    cam2ref_transform[cam] = np.linalg.inv(ref2cam_transform[cam])

                for cam in cam_list:
                    if outlier_cam_list is not None and cam in outlier_cam_list:
                        continue
                    cam_extrinsics[cam] = planecam_ext @ cam2ref_transform[cam]

            """ Sort colmap_extrinsic by cam and slice name """
            colmap_extrinsic = trip_calib["colmap_extrinsic"]
            colmap_extrinsic_sorted = sorted(colmap_extrinsic.keys(), key=lambda x: (int(re.findall(r'cam(\d+)', x)[0]), int(re.findall(r'slice(\d+)_cam', x)[0])))
            colmap_extrinsic_sorted = sorted(colmap_extrinsic_sorted, key=lambda x:int(x.split("_")[0].split("slice")[-1]))

            trip_calib["colmap_extrinsic"] = {k: colmap_extrinsic[k] for k in colmap_extrinsic_sorted}

            """ Get last image name for each cam """
            last_slice = {}
            for keys, colmap_extrinsic in trip_calib["colmap_extrinsic"].items():
                cam_id = int(re.findall(r'cam(\d+)', keys)[0])
                last_slice[cam_id] = keys

            last_slice_list = []
            for keys, colmap_extrinsic in last_slice.items():
                last_slice_list.append(colmap_extrinsic)

            """ Load frame data """
            prev_local_pose = None
            selected_slices = []
            for slice_name, pose in trip_calib["local_pose"].items():
                local_pose = np.array(pose)
                if prev_local_pose is not None:
                    [distance_diff, angle_diff] = compute_between_pose_dist_and_angle(prev_local_pose, local_pose)
                    if distance_diff < rome_downsample_distance_threshold and math.degrees(angle_diff) < rome_downsample_angle_threshold:
                        continue
                prev_local_pose = local_pose
                selected_slices.append(slice_name)

            for keys, colmap_extrinsic in trip_calib["colmap_extrinsic"].items():
                slice_name, cam_name = keys.split('_')
                if slice_name not in selected_slices or cam_name not in cam_list:
                    continue
                if outlier_cam_list is not None and cam_name in outlier_cam_list:
                    continue
                translation = np.array(colmap_extrinsic)[:3, 3]
                if type(self.cut_center) == np.ndarray:
                    if np.linalg.norm(translation - self.cut_center) > self.cutoff_radius:
                        continue

                cam_unique_name = '/'.join([trip_name, cam_name])
                if len(cam_name_to_cam_index_map) == 0:
                     cam_name_to_cam_index_map[cam_unique_name] = 0
                elif cam_unique_name not in cam_name_to_cam_index_map:
                    cam_name_to_cam_index_map[cam_unique_name] = list(cam_name_to_cam_index_map.values())[-1] + 1

                slice_idx = int(slice_name.split("slice")[1])
                extrinsic_idx = slice_idx // slice_interval
                image_unique_name = '/'.join([trip_name, cam_name, str(extrinsic_idx)])
                if len(image_name_to_extrinsic_map) == 0:
                    image_name_to_extrinsic_map[image_unique_name] = 0
                elif image_unique_name not in image_name_to_extrinsic_map:
                    image_name_to_extrinsic_map[image_unique_name] = list(image_name_to_extrinsic_map.values())[-1] + 1

                self.cameras_idx_all.append(cam_name_to_cam_index_map[cam_unique_name])
                self.image_extrics_idx_all.append(image_name_to_extrinsic_map[image_unique_name])
                self.image_filenames_all.append(os.path.join(trip_image_path, cam_name, slice_name+'.png'))
                self.depth_filenames_all.append(os.path.join(trip_depth_path, cam_name, slice_name+'.png'))
                self.label_filenames_all.append(os.path.join(trip_mask_path, cam_name, slice_name+'.png'))
                self.cameras_K_all.append(cam_intrinsics[cam_name].astype(np.float32))
                self.camera_extrinsics_all.append(cam2ref_transform[cam_name].astype(np.float32))
                cam_ext = cam_extrinsics[cam_name]
                if configs["pose_source"] == "local":
                    if f"slice{slice_idx}" not in trip_calib["local_pose"].keys():
                        continue
                    ego_pose = np.array(trip_calib["local_pose"][f"slice{slice_idx}"])
                elif configs["pose_source"] == "global":
                    if f"slice{slice_idx}" not in trip_calib["global_pose"].keys():
                        continue
                    ego_pose = np.array(trip_calib["global_pose"][f"slice{slice_idx}"])
                elif configs["pose_source"] == "colmap":
                    colmap_pose = np.array(colmap_extrinsic)
                    ego_pose = colmap_pose @ np.linalg.inv(cam_ext)
                if cam_name == ref_cam:
                    original_ego_pose_all.append(ego_pose)
                ref2cam = ref2cam_transform[cam_name]
                cam2world = ego_pose @ cam_ext @ ref2cam
                self.ref_camera2world_all.append(cam2world.astype(np.float32))

        self.cam_name_to_cam_index_map = cam_name_to_cam_index_map
        self.image_name_to_extrinsic_map = image_name_to_extrinsic_map

        """ Convert to an intermediate plane to reduce z std """
        assert len(original_ego_pose_all) > 0, "ego pose is empty"
        original_ego_pose_all = np.array(original_ego_pose_all)
        if configs["mode"] == "recon":
            transform_normal2origin = robust_estimate_flatplane(np.array(original_ego_pose_all)[:, :3, 3], configs).astype(np.float32)
        elif configs["mode"] == "reloc":
            transform_normal2origin = np.array(recon_dataset_param["transform_normal2origin"])
        ego_pose_all = transform_normal2origin[None] @ original_ego_pose_all
        self.ref_camera2world_all = transform_normal2origin[None] @ np.array(self.ref_camera2world_all)

        if configs["mode"] == "recon":
            poses_xy_min = ego_pose_all[:, :2, 3].min(0) - np.array([cut_range, cut_range])
        elif configs["mode"] == "reloc":
            poses_xy_min = np.array(recon_dataset_param["poses_xy_min"])

        self.world2bev = np.asarray([
            [1, 0, 0, -poses_xy_min[0]],
            [0, 1, 0, -poses_xy_min[1]],
            [0, 0, 1, 0],
            [0, 0, 0, 1]
        ], dtype=np.float32)
        self.ori_world_to_new_world = self.world2bev @ transform_normal2origin
        self.ego_pose_xyz = self.world2bev[None] @ np.array(ego_pose_all)

        ### Calculate mesh size
        if configs["mode"] == "recon":
            bev_pose_xy = np.array(self.ego_pose_xyz)[:, :2, 3]
            bev_pose_xy_min = bev_pose_xy.min(0)
            bev_pose_xy_max = bev_pose_xy.max(0)
            x_length = math.ceil(bev_pose_xy_max[0] - bev_pose_xy_min[0] + 2.0 * configs["cut_range"])
            x_length = math.ceil(x_length / 8.0) * 8.0
            y_length = math.ceil(bev_pose_xy_max[1] - bev_pose_xy_min[1] + 2.0 * configs["cut_range"])
            y_length = math.ceil(y_length / 8.0) * 8.0
            configs["bev_x_length"] = x_length
            configs["bev_y_length"] = y_length
            configs["bev_x_pixel"] = int(configs["bev_x_length"] / configs["bev_resolution"])
            configs["bev_y_pixel"] = int(configs["bev_y_length"] / configs["bev_resolution"])

            dataset_param = {}
            dataset_param["transform_normal2origin"] = transform_normal2origin
            dataset_param["cut_center"] = self.cut_center
            dataset_param["poses_xy_min"] = poses_xy_min
            dataset_param["bev_x_length"] = configs["bev_x_length"]
            dataset_param["bev_y_length"] = configs["bev_y_length"]
            dataset_param["bev_x_pixel"] = configs["bev_x_pixel"]
            dataset_param["bev_y_pixel"] = configs["bev_y_pixel"]
            dataset_param["bev_resolution"] = configs["bev_resolution"]
            configs["dataset_param"] = dataset_param


    def filter_by_index(self, index):
        self.image_filenames_all = [self.image_filenames_all[i] for i in index]
        self.depth_filenames_all = [self.depth_filenames_all[i] for i in index]
        self.label_filenames_all = [self.label_filenames_all[i] for i in index]
        self.ref_camera2world_all = [self.ref_camera2world_all[i] for i in index]
        self.cameras_K_all = [self.cameras_K_all[i] for i in index]
        self.cameras_idx_all = [self.cameras_idx_all[i] for i in index]
        self.camera_extrinsics_all = [self.camera_extrinsics_all[i] for i in index]
        self.image_extrics_idx_all = [self.image_extrics_idx_all[i] for i in index]

    def enable_all_data(self):
        self.image_filenames = self.image_filenames_all
        self.depth_filename = self.depth_filenames_all
        self.label_filenames = self.label_filenames_all
        self.ref_camera2world = self.ref_camera2world_all
        self.cameras_idx = self.cameras_idx_all
        self.cameras_K = self.cameras_K_all
        self.camera_extrinsics = self.camera_extrinsics_all
        self.image_extrics_idx = self.image_extrics_idx_all

    def set_waypoint(self, center_xy, radius):
        self.enable_all_data()

    def get_average_center(self, trip_list, ref_cam):
        all_translation = []
        for trip_image_path in trip_list:
            trip_name = '/'.join(trip_image_path.split('/')[-2:])
            trip_calib = json.load(open(os.path.join(trip_image_path, "calib.json"), "r"))

            for keys, colmap_extrinsic in trip_calib["colmap_extrinsic"].items():
                slice_name, cam_name = keys.split('_')
                if cam_name != ref_cam:
                    continue
                translation = np.array(colmap_extrinsic)[:3, 3]
                all_translation.append(translation)
        all_translation = np.array(all_translation)
        return all_translation.mean(0)

    def label2mask(self, label):
        # Bird, Ground Animal, Curb, Fence, Guard Rail,
        # Barrier, Wall, Bike Lane, Crosswalk - Plain, Curb Cut,
        # Parking, Pedestrian Area, Rail Track, Road, Service Lane,
        # Sidewalk, Bridge, Building, Tunnel, Person,
        # Bicyclist, Motorcyclist, Other Rider, Lane Marking - Crosswalk, Lane Marking - General,
        # Mountain, Sand, Sky, Snow, Terrain,
        # Vegetation, Water, Banner, Bench, Bike Rack,
        # Billboard, Catch Basin, CCTV Camera, Fire Hydrant, Junction Box,
        # Mailbox, Manhole, Phone Booth, Pothole, Street Light,
        # Pole, Traffic Sign Frame, Utility Pole, Traffic Light, Traffic Sign (Back),
        # Traffic Sign (Front), Trash Can, Bicycle, Boat, Bus,
        # Car, Caravan, Motorcycle, On Rails, Other Vehicle,
        # Trailer, Truck, Wheeled Slow, Car Mount, Ego Vehicle
        mask = np.ones_like(label)
        label_off_road = ((0 <= label) & (label <= 1)) | ((3 <= label) & (label <= 6)) | ((11 <= label) & (label <= 12)) \
            | ((16 <= label) & (label <= 22)) | ((25 <= label) & (label <= 28)) | ((30 <= label) & (label <= 40)) | (label >= 42)

        # dilate itereation 2 for moving objects
        label_movable = label >= 52
        kernel = np.ones((10, 10), dtype=np.uint8)
        label_movable = cv2.dilate(label_movable.astype(np.uint8), kernel, 2).astype(bool)

        label_off_road = label_off_road | label_movable
        mask[label_off_road] = 0
        label[~(mask.astype(bool))] = 64
        mask = mask.astype(np.float32)

        return mask, label

    def label2mask2(self, label):
        # Bird, Ground Animal, Curb, Fence, Guard Rail,
        # Barrier, Wall, Bike Lane, Crosswalk - Plain, Curb Cut,
        # Parking, Pedestrian Area, Rail Track, Road, Service Lane,
        # Sidewalk, Bridge, Building, Tunnel, Person,
        # Bicyclist, Motorcyclist, Other Rider, Lane Marking - Crosswalk, Lane Marking - General,
        # Mountain, Sand, Sky, Snow, Terrain,
        # Vegetation, Water, Banner, Bench, Bike Rack,
        # Billboard, Catch Basin, CCTV Camera, Fire Hydrant, Junction Box,
        # Mailbox, Manhole, Phone Booth, Pothole, Street Light,
        # Pole, Traffic Sign Frame, Utility Pole, Traffic Light, Traffic Sign (Back),
        # Traffic Sign (Front), Trash Can, Bicycle, Boat, Bus,
        # Car, Caravan, Motorcycle, On Rails, Other Vehicle,
        # Trailer, Truck, Wheeled Slow, Car Mount, Ego Vehicle
        mask = np.ones_like(label)
        label_off_road = ((0 <= label) & (label <= 1)) | ((3 <= label) & (label <= 5)) | ((11 <= label) & (label <= 12)) \
            | ((19 <= label) & (label <= 22)) | ((25 <= label) & (label <= 28)) | ((31 <= label) & (label <= 40)) | (label >= 42)

        # dilate itereation 2 for moving objects
        label_movable = label >= 52
        kernel = np.ones((10, 10), dtype=np.uint8)
        label_movable = cv2.dilate(label_movable.astype(np.uint8), kernel, 2).astype(bool)

        label_off_road = label_off_road | label_movable
        mask[label_off_road] = 0
        label[~(mask.astype(bool))] = 64
        mask = mask.astype(np.float32)

        return mask, label
    def _get_image(self, image_path):
        input_image = cv2.imread(image_path)
        input_image = cv2.cvtColor(input_image, cv2.COLOR_BGR2RGB)
        return input_image

    def __getitem__(self, idx):
        sample = dict()
        sample["idx"] = idx
        sample["camera_idx"] = self.cameras_idx[idx]
        sample["image_extrics_idx"] = self.image_extrics_idx[idx]

        # read label
        label = cv2.imread(self.label_filenames[idx], cv2.IMREAD_UNCHANGED)
        label_cp = copy.deepcopy(label)
        mask, _ = self.label2mask(label_cp)
        valid_y, _ = np.where(mask > 0)
        crop_cy = 0
        if self.training_crop_image_by_label and valid_y.shape[0] > 0:
            #  dilate 10 pixel, and crop 80% at most
            crop_cy = np.clip(valid_y.min() - 10, 0, int(label.shape[0] * 0.8))

        # read image
        image_path = self.image_filenames[idx]
        sample["image_path"] = image_path
        input_image = self._get_image(image_path)
        sample["original_image_size"] = np.array([input_image.shape[1], input_image.shape[0]])
        input_image = input_image[crop_cy:, ...]

        resized_image = cv2.resize(input_image, dsize=self.resized_image_size, interpolation=cv2.INTER_LINEAR)
        sample["image"] = (np.asarray(resized_image)/255.0).astype(np.float32)

        # read depth
        depth_path = self.depth_filename[idx]
        sample["depth_path"] = depth_path
        if os.path.exists(depth_path):
            input_depth = cv2.imread(depth_path, cv2.IMREAD_UNCHANGED)
            resized_depth = cv2.resize(input_depth[crop_cy:, ...], dsize=self.resized_image_size, interpolation=cv2.INTER_NEAREST)
            resized_depth = resized_depth[..., None].astype(np.float32)*1e-3
            sample["depth"] = resized_depth
        else:
            w, h = self.resized_image_size
            sample["depth"] = np.zeros((h, w, 1), np.float32)

        # semantic label
        label = label[crop_cy:, ...]
        resized_label = cv2.resize(label, dsize=self.resized_image_size, interpolation=cv2.INTER_NEAREST)
        resized_label_cp = copy.deepcopy(resized_label)
        mask, label = self.label2mask(resized_label)
        mask2, label2 = self.label2mask2(resized_label_cp)
        h, w = mask.shape
        label = self.remap_semantic(label).astype(np.int64)
        label2 = self.remap_semantic(label2).astype(np.int64)

        sample["static_mask"] = mask
        sample["static_mask2"] = mask2
        sample["static_label"] = label
        sample["static_label2"] = label2

        camera2world = self.world2bev @ self.ref_camera2world[idx] @ self.camera_extrinsics[idx]
        sample["world2camera"] = np.linalg.inv(camera2world).astype(np.float64)

        K = self.cameras_K[idx]
        K[1, 2] -= crop_cy
        resized_K = deepcopy(K)
        width_scale = self.resized_image_size[0]/input_image.shape[1]
        height_scale = self.resized_image_size[1]/input_image.shape[0]
        resized_K[0, :] *= width_scale
        resized_K[1, :] *= height_scale
        sample["camera_K"] = resized_K
        sample["image_shape"] = np.asarray(sample["image"].shape)[:2]
        sample = self.opencv_camera2pytorch3d_(sample)
        return sample

    @ property
    def label_remaps(self):
        colors = np.ones((256, 1), dtype="uint8")
        colors *= 6          # background
        colors[7, :] = 1     # Lane marking
        colors[8, :] = 1
        colors[14, :] = 1
        colors[23, :] = 1
        colors[24, :] = 1
        colors[2, :] = 2     # curb
        colors[9, :] = 2     # curb cut
        colors[41, :] = 3    # Manhole
        colors[13, :] = 3    # road
        colors[10, :] = 3    # parking
        colors[15, :] = 4    # sidewalk
        colors[29, :] = 5    # terrain
        return colors

    @ property
    def origin_color_map(self):
        colors = np.zeros((256, 1, 3), dtype='uint8')
        colors[0, :, :] = [165, 42, 42]  # Bird
        colors[1, :, :] = [0, 192, 0]  # Ground Animal
        colors[2, :, :] = [196, 196, 196]  # Curb
        colors[3, :, :] = [190, 153, 153]  # Fence
        colors[4, :, :] = [180, 165, 180]  # Guard Rail
        colors[5, :, :] = [90, 120, 150]  # Barrier
        colors[6, :, :] = [102, 102, 156]  # Wall
        colors[7, :, :] = [128, 64, 255]  # Bike Lane
        colors[8, :, :] = [140, 140, 200]  # Crosswalk - Plain
        colors[9, :, :] = [170, 170, 170]  # Curb Cut
        colors[10, :, :] = [250, 170, 160]  # Parking
        colors[11, :, :] = [96, 96, 96]  # Pedestrian Area
        colors[12, :, :] = [230, 150, 140]  # Rail Track
        colors[13, :, :] = [128, 64, 128]  # Road
        colors[14, :, :] = [110, 110, 110]  # Service Lane
        colors[15, :, :] = [244, 35, 232]  # Sidewalk
        colors[16, :, :] = [150, 100, 100]  # Bridge
        colors[17, :, :] = [70, 70, 70]  # Building
        colors[18, :, :] = [150, 120, 90]  # Tunnel
        colors[19, :, :] = [220, 20, 60]  # Person
        colors[20, :, :] = [255, 0, 0]  # Bicyclist
        colors[21, :, :] = [255, 0, 100]  # Motorcyclist
        colors[22, :, :] = [255, 0, 200]  # Other Rider
        colors[23, :, :] = [200, 128, 128]  # Lane Marking - Crosswalk
        colors[24, :, :] = [255, 255, 255]  # Lane Marking - General
        colors[25, :, :] = [64, 170, 64]  # Mountain
        colors[26, :, :] = [230, 160, 50]  # Sand
        colors[27, :, :] = [70, 130, 180]  # Sky
        colors[28, :, :] = [190, 255, 255]  # Snow
        colors[29, :, :] = [152, 251, 152]  # Terrain
        colors[30, :, :] = [107, 142, 35]  # Vegetation
        colors[31, :, :] = [0, 170, 30]  # Water
        colors[32, :, :] = [255, 255, 128]  # Banner
        colors[33, :, :] = [250, 0, 30]  # Bench
        colors[34, :, :] = [100, 140, 180]  # Bike Rack
        colors[35, :, :] = [220, 220, 220]  # Billboard
        colors[36, :, :] = [220, 128, 128]  # Catch Basin
        colors[37, :, :] = [222, 40, 40]  # CCTV Camera
        colors[38, :, :] = [100, 170, 30]  # Fire Hydrant
        colors[39, :, :] = [40, 40, 40]  # Junction Box
        colors[40, :, :] = [33, 33, 33]  # Mailbox
        colors[41, :, :] = [100, 128, 160]  # Manhole
        colors[42, :, :] = [142, 0, 0]  # Phone Booth
        colors[43, :, :] = [70, 100, 150]  # Pothole
        colors[44, :, :] = [210, 170, 100]  # Street Light
        colors[45, :, :] = [153, 153, 153]  # Pole
        colors[46, :, :] = [128, 128, 128]  # Traffic Sign Frame
        colors[47, :, :] = [0, 0, 80]  # Utility Pole
        colors[48, :, :] = [250, 170, 30]  # Traffic Light
        colors[49, :, :] = [192, 192, 192]  # Traffic Sign (Back)
        colors[50, :, :] = [220, 220, 0]  # Traffic Sign (Front)
        colors[51, :, :] = [140, 140, 20]  # Trash Can
        colors[52, :, :] = [119, 11, 32]  # Bicycle
        colors[53, :, :] = [150, 0, 255]  # Boat
        colors[54, :, :] = [0, 60, 100]  # Bus
        colors[55, :, :] = [0, 0, 142]  # Car
        colors[56, :, :] = [0, 0, 90]  # Caravan
        colors[57, :, :] = [0, 0, 230]  # Motorcycle
        colors[58, :, :] = [0, 80, 100]  # On Rails
        colors[59, :, :] = [128, 64, 64]  # Other Vehicle
        colors[60, :, :] = [0, 0, 110]  # Trailer
        colors[61, :, :] = [0, 0, 70]  # Truck
        colors[62, :, :] = [0, 0, 192]  # Wheeled Slow
        colors[63, :, :] = [32, 32, 32]  # Car Mount
        colors[64, :, :] = [120, 10, 10]  # Ego Vehicle
        # colors[65, :, :] = [0, 0, 0] # Unlabeled
        return colors

    @property
    def num_class(self):
        return 7

    @ property
    def filted_color_map(self):
        colors = np.zeros((256, 1, 3), dtype='uint8')
        colors[0, :, :] = [0, 0, 0]         # mask
        colors[1, :, :] = [0, 0, 255]       # all lane
        colors[2, :, :] = [255, 0, 0]       # curb
        colors[3, :, :] = [211, 211, 211]   # road and manhole
        colors[4, :, :] = [0, 191, 255]     # sidewalk
        colors[5, :, :] = [152, 251, 152]   # terrain
        colors[6, :, :] = [157, 234, 50]    # background
        return colors
