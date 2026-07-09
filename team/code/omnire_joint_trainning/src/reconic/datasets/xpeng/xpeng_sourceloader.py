import glob
import json
import logging
import os
import joblib
from typing import Dict

import cv2
import numpy as np
import torch
from omegaconf import OmegaConf
from PIL import Image
from torch import Tensor
from tqdm import tqdm
from pytorch3d.transforms import matrix_to_quaternion

from ..base.lidar_source import SceneLidarSource
from ..base.pixel_source import CameraData, ScenePixelSource
from ..base.scene_dataset import ModelType, ObjectType, DistLevel
from .constants import SemanticType
from .xpeng_utils import (
    bbox_to_corner3d,
    fetchPly,
    get_bound_2d_mask,
    get_bound_2d_mask_fix,
    get_mask_from_semantics,
    get_semantics_from_path,
    load_xpeng_obj_points,
    quaternion_matrix,
)

logger = logging.getLogger()

# define each class's node type
# TODO(team): Support pedestrian SMPLNodes
OBJECT_CLASS_NODE_MAPPING = {
    "car": ModelType.RigidNodes,
    "truck": ModelType.RigidNodes,
    "pedestrian": ModelType.SMPLNodes,
    "cyclist": ModelType.RigidNodes,
}
OBJECT_TYPE = {
    "car": ObjectType.Vehicle,
    "truck": ObjectType.Vehicle,
    "pedestrian": ObjectType.Pedestrian,
    "cyclist": ObjectType.Cyclist,
    "motorcycle": ObjectType.Cyclist,
}


class XpengCameraData(CameraData):
    def __init__(self, **kwargs):
        self.egocar_dilated_mask = kwargs.pop("egocar_dilated_mask", None)

        super().__init__(**kwargs)

        # load the expand_ratio and distortion_map to redistort the images
        self.load_redistort_info()

    def create_all_filelist(self):
        """
        Create file lists for all data files.
        e.g., img files, feature files, etc.
        """
        # ---- Actual timestamps ---- #
        localpose = json.load(open(os.path.join(self.data_path, "localpose.json")))
        self.actual_timestamps = sorted([int(k) for k in localpose.keys()])

        # ---- define filepaths ---- #
        img_filepaths = []
        segmentation_filepaths = []
        ego_mask_filepaths = []
        lidar_depth_filepaths = []
        # Note: we assume all the files in xpeng dataset are synchronized
        for idx, t in enumerate(self.actual_timestamps):
            if self.start_timestep <= idx < self.end_timestep:
                img_filepaths.append(os.path.join(self.data_path, "images", self.cam_name, f"{t}.png"))
                segmentation_filepaths.append(os.path.join(self.data_path, "segs", self.cam_name, f"{t}.png"))
                ego_mask_filepaths.append(os.path.join(self.data_path, "masks", self.cam_name, f"{t}.png"))
                lidar_depth_filepaths.append(os.path.join(self.data_path, "depth", self.cam_name, f"{t}.npy"))
        self.img_filepaths = np.array(img_filepaths)
        self.segmentation_filepaths = np.array(segmentation_filepaths)
        self.ego_mask_filepaths = np.array(ego_mask_filepaths)
        self.lidar_depth_filepaths = np.array(lidar_depth_filepaths)

    def _get_camera_calib(self, data):
        fpx = data["focal_length"]
        fpy = data["focal_length"]
        cx = data["cx"]
        cy = data["cy"]

        # 3x3 matrix
        cameraMatrix = np.zeros((3, 3))
        cameraMatrix[0, 0] = fpx
        cameraMatrix[1, 1] = fpy
        cameraMatrix[0, 2] = cx
        cameraMatrix[1, 2] = cy
        cameraMatrix[2, 2] = 1

        p1, p2 = data["p1"], data["p2"]
        k1, k2, k3, k4, k5, k6 = data["k1"], data["k2"], data["k3"], data["k4"], data["k5"], data["k6"]

        distCoeffs = [k1, k2, p1, p2, k3, k4, k5, k6]
        distCoeffs = np.array(distCoeffs)

        return cameraMatrix, distCoeffs

    def _get_expand_ratio(self, calib_info):
        if "expand_ratio" not in calib_info:
            default_expand_ratio_dict = {
                "cam0": 1.2,
                "cam1": 1.2,
                "cam2": 2.0,
                "cam3": 1.5,
                "cam4": 1.5,
                "cam5": 1.5,
                "cam6": 1.5,
                "cam7": 1.2,
            }
            return default_expand_ratio_dict[self.cam_name]
        return calib_info["expand_ratio"][self.cam_name]

    def _get_distortion_map(self, calib_info):
        camera_matrix, dist_coeffs = self._get_camera_calib(calib_info[self.cam_name]["intrinsic"])
        new_camera_matrix, _ = self._get_camera_calib(calib_info["new" + self.cam_name]["intrinsic"])

        x = np.arange(self.WIDTH, dtype=np.float32)
        y = np.arange(self.HEIGHT, dtype=np.float32)

        xx, yy = np.meshgrid(x, y)

        pts_distort = np.stack((xx.ravel(), yy.ravel()), axis=-1)

        pts_distort = pts_distort.reshape(-1, 1, 2)
        pts_ud = cv2.undistortPoints(pts_distort, camera_matrix, dist_coeffs, R=None, P=new_camera_matrix)
        pts_ud = pts_ud.reshape(self.HEIGHT, self.WIDTH, 2)
        map_x, map_y = pts_ud[..., 0], pts_ud[..., 1]
        return map_x, map_y

    def load_redistort_info(self):
        calib_info_path = os.path.join(self.data_path, "calib.json")
        with open(calib_info_path, "r") as fr:
            calib_info = json.load(fr)
        self.expand_ratio = self._get_expand_ratio(calib_info)
        self.distortion_maps = self._get_distortion_map(calib_info)

    def load_calibrations(self):
        """
        Load the camera intrinsics, extrinsics, timestamps, etc.
        Compute the camera-to-world matrices, ego-to-world matrices, etc.
        """
        transform_json = json.load(open(os.path.join(self.data_path, "transform.json")))
        transform_matrix = {}
        intrinsics = []
        distortions = []
        cam_to_worlds = []
        for frame in transform_json["frames"]:
            if self.cam_name == frame["camera"]:
                transform_matrix[frame["timestamp"]] = frame["transform_matrix"]
        cam_to_ego = transform_json["sensor_params"][self.cam_name]["extrinsic"]

        intrinsic = transform_json["sensor_params"][self.cam_name]["camera_intrinsic"]
        intrinsic[0][0] = intrinsic[0][0] * self.load_size[1] / self.original_size[1]
        intrinsic[0][2] = intrinsic[0][2] * self.load_size[1] / self.original_size[1]
        intrinsic[1][1] = intrinsic[1][1] * self.load_size[0] / self.original_size[0]
        intrinsic[1][2] = intrinsic[1][2] * self.load_size[0] / self.original_size[0]

        distortion = transform_json["sensor_params"][self.cam_name]["camera_D"]

        for t in range(self.start_timestep, self.end_timestep):
            intrinsics.append(intrinsic)
            distortions.append(distortion)
            cam_to_worlds.append(transform_matrix[self.actual_timestamps[t]])

        cam_to_ego_inv = np.linalg.inv(cam_to_ego)
        ego_to_worlds = []
        for cam_to_world in cam_to_worlds:
            ego_to_world = cam_to_world @ cam_to_ego_inv
            ego_to_worlds.append(ego_to_world)

        self.intrinsics = torch.from_numpy(np.stack(intrinsics, axis=0)).float()
        self.distortions = torch.from_numpy(np.stack(distortions, axis=0)).float()
        self.cam_to_worlds = torch.from_numpy(np.stack(cam_to_worlds, axis=0)).float()
        self.ego_to_worlds = torch.from_numpy(np.stack(ego_to_worlds, axis=0)).float()
        self.cam_to_ego = torch.from_numpy(np.array(cam_to_ego)).float()
        self.load_noncrop_cam_info()
        if abs(self.difix_downsample - 1.0) > 1e-5:
            self.load_downsample_cam_info()
        else:
            self.intrinsics_downsample = None

    def load_downsample_cam_info(self):
        self.intrinsics_downsample = self.intrinsics.clone()
        fx_new = self.intrinsics_downsample[:, 0, 0] * self.difix_downsample
        fy_new = self.intrinsics_downsample[:, 1, 1] * self.difix_downsample
        cx_new = self.intrinsics_downsample[:, 0, 2] * self.difix_downsample
        cy_new = self.intrinsics_downsample[:, 1, 2] * self.difix_downsample
        self.intrinsics_downsample[:, 0, 0] = fx_new
        self.intrinsics_downsample[:, 1, 1] = fy_new
        self.intrinsics_downsample[:, 0, 2] = cx_new
        self.intrinsics_downsample[:, 1, 2] = cy_new
        fx_new_noncrop = self.intrinsics_noncrop[:, 0, 0] * self.difix_downsample
        fy_new_noncrop = self.intrinsics_noncrop[:, 1, 1] * self.difix_downsample
        cx_new_noncrop = self.intrinsics_noncrop[:, 0, 2] * self.difix_downsample
        cy_new_noncrop = self.intrinsics_noncrop[:, 1, 2] * self.difix_downsample
        self.intrinsics_noncrop[:, 0, 0] = fx_new_noncrop
        self.intrinsics_noncrop[:, 1, 1] = fy_new_noncrop
        self.intrinsics_noncrop[:, 0, 2] = cx_new_noncrop
        self.intrinsics_noncrop[:, 1, 2] = cy_new_noncrop

    def load_noncrop_cam_info(self):
        calib_info = json.load(open(os.path.join(self.data_path, "calib.json")))
        noncrop_cam_info = calib_info["noncrop" + self.cam_name]
        intrinsic = noncrop_cam_info["intrinsic"]
        fx, fy, cx, cy = intrinsic["focal_length_x"], intrinsic["focal_length_y"], intrinsic["cx"], intrinsic["cy"]
        intrinsic = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]])
        intrinsics_noncrop = []
        for t in range(self.start_timestep, self.end_timestep):
            intrinsics_noncrop.append(intrinsic)
        self.intrinsics_noncrop = torch.from_numpy(np.stack(intrinsics_noncrop, axis=0)).float()

    def load_egocar_mask(self):
        egocar_mask = self.ego_mask_filepaths[0]
        if os.path.exists(egocar_mask):
            egocar_mask = Image.open(egocar_mask).convert("L")
            # resize them to the load_size
            if self.load_size[0] != egocar_mask.size[1] or self.load_size[1] != egocar_mask.size[0]:
                egocar_mask = egocar_mask.resize((self.load_size[1], self.load_size[0]), Image.BILINEAR)
            if self.undistort:
                egocar_mask = cv2.undistort(
                    np.array(egocar_mask),
                    self.intrinsics[0].numpy(),
                    self.distortions[0].numpy(),
                )
            if self.egocar_dilated_mask is not None and self.egocar_dilated_mask > 0:
                kernel = np.ones((self.egocar_dilated_mask, self.egocar_dilated_mask), np.uint8)
                egocar_mask = cv2.erode(np.array(egocar_mask).astype(np.uint8), kernel, iterations=1)

            self.egocar_mask = ~torch.from_numpy(np.array(egocar_mask) > 0).bool()
        else:
            raise FileNotFoundError(f"Ego car mask file not found: {egocar_mask}")

    def load_dynamic_mask_by_frame_idx(self, frame_idx):
        # 真正的dynamic mask由load_obj_boundings得出，存放在self.camera_data[cam_id] (CameraData类)的self.dynamic_masks（多了个s）中，在基类(pixel_source.py) if self.load_dynamic_mask相关逻辑中将self.dynamic_masks赋值给image_info
        # self.dynamic_masks使用annotation作为dyanmic的标注框
        dynamic_mask = None
        human_mask = None
        vehicle_mask = None

        # load human mask
        fname = self.segmentation_filepaths[frame_idx]
        semantics = get_semantics_from_path(fname)

        human_mask = np.squeeze(get_mask_from_semantics(semantics, SemanticType.HUMAN), axis=-1)
        if self.load_size[0] != human_mask.shape[1] or self.load_size[1] != human_mask.shape[0]:
            human_mask = cv2.resize(
                human_mask.astype(np.float32), (self.load_size[1], self.load_size[0]), interpolation=cv2.INTER_NEAREST
            )
        human_mask = torch.from_numpy(human_mask).bool()

        # load vehicle mask
        vehicle_mask = np.squeeze(get_mask_from_semantics(semantics, SemanticType.VEHICLE), axis=-1)
        if self.load_size[0] != vehicle_mask.shape[0] or self.load_size[1] != vehicle_mask.shape[1]:
            vehicle_mask = cv2.resize(
                vehicle_mask.astype(np.float32), (self.load_size[1], self.load_size[0]), interpolation=cv2.INTER_NEAREST
            )
        vehicle_mask = torch.from_numpy(vehicle_mask).bool()

        if self.undistort:
            raise NotImplementedError("Undistorting segmentation masks is not implemented.")
        return dynamic_mask, human_mask, vehicle_mask

    def load_ground_mask_by_frame_idx(self, frame_idx):
        fname = self.segmentation_filepaths[frame_idx]
        semantics = get_semantics_from_path(fname)
        ground_mask = np.squeeze(get_mask_from_semantics(semantics, SemanticType.GROUND), axis=-1)
        if self.load_size[0] != ground_mask.shape[0] or self.load_size[1] != ground_mask.shape[1]:
            ground_mask = cv2.resize(
                ground_mask.astype(np.float32), (self.load_size[1], self.load_size[0]), interpolation=cv2.INTER_NEAREST
            )

        if self.undistort:
            raise NotImplementedError("Undistorting segmentation masks is not implemented.")
        return torch.from_numpy(ground_mask).bool()

    def load_sky_mask_by_frame_idx(self, frame_idx):
        fname = self.segmentation_filepaths[frame_idx]
        semantics = get_semantics_from_path(fname)
        sky_mask = np.squeeze(get_mask_from_semantics(semantics, SemanticType.SKY), axis=-1)
        if self.load_size[0] != sky_mask.shape[0] or self.load_size[1] != sky_mask.shape[1]:
            sky_mask = cv2.resize(
                sky_mask.astype(np.float32), (self.load_size[1], self.load_size[0]), interpolation=cv2.INTER_NEAREST
            )
        if self.undistort:
            raise NotImplementedError("Undistorting segmentation masks is not implemented.")
        return torch.from_numpy(sky_mask).bool()

    def load_tfl_mask_by_frame_idx(self,frame_idx):
        fname = self.segmentation_filepaths[frame_idx]
        semantics = get_semantics_from_path(fname)
        tfl_mask = np.squeeze(get_mask_from_semantics(semantics, SemanticType.TRAFFICLIGHT), axis=-1)
        if self.load_size[0] != tfl_mask.shape[0] or self.load_size[1] != tfl_mask.shape[1]:
            tfl_mask = cv2.resize(
                tfl_mask.astype(np.float32), (self.load_size[1], self.load_size[0]), interpolation=cv2.INTER_NEAREST
            )
        if self.undistort:
            raise NotImplementedError("Undistorting segmentation masks is not implemented.")
        return torch.from_numpy(tfl_mask).bool()

    def load_projected_lidar_depth_by_frame_idx(self, frame_idx):
        fname = self.lidar_depth_filepaths[frame_idx]
        if os.path.exists(fname):
            try:
                depth = np.load(fname)
            except:
                depth = np.load(fname, allow_pickle=True)
                depth = dict(depth.item())
                mask = depth["mask"]
                value = depth["value"]
                depth = np.zeros_like(mask).astype(np.float32)
                depth[mask] = value
        else:
            depth = np.zeros((self.load_size[0],self.load_size[1]))
            print(f"[WARNING] No lidar depth file found for {fname}")
        assert isinstance(depth, np.ndarray)
        # TODO(team): Resize the depth map to the load_size for downscale_when_loading
        assert (
            self.load_size[0] == self.original_size[0] and self.load_size[1] == self.original_size[1]
        ), "Downscaling is not supported for lidar depth maps"
        return torch.from_numpy(depth).float()

    @classmethod
    def get_camera2worlds(cls, data_path: str, cam_id: str, start_timestep: int, end_timestep: int) -> torch.Tensor:
        """
        Returns camera-to-world matrices for the specified camera and time range.

        Args:
            data_path (str): Path to the dataset.
            cam_id (str): Camera ID.
            start_timestep (int): Start timestep.
            end_timestep (int): End timestep.

        Returns:
            torch.Tensor: Camera-to-world matrices of shape (num_frames, 4, 4).
        """
        raise NotImplementedError

# 在datasets/driving_dataset.py，build_data_source中构建
class XpengPixelSource(ScenePixelSource):
    def __init__(
        self,
        dataset_name: str,
        pixel_data_config: OmegaConf,
        data_path: str,
        start_timestep: int,
        end_timestep: int,
        device: torch.device = torch.device("cpu"),
        data_source: str = 'lidar'
    ):
        super().__init__(dataset_name, pixel_data_config, device=device)
        self.data_path = data_path
        # 从yaml中读取，搜索build_data_source
        self.start_timestep = start_timestep
        self.end_timestep = end_timestep
        self.data_source = data_source
        self.load_data()
        self.load_max_range_info()
        self.load_obj_boundings()

    def load_cameras(self):
        # 为等差数列，并非数据集中的时间戳
        self._timesteps = torch.arange(self.start_timestep, self.end_timestep)
        # 由于self._timesteps为0到self.end_timestep的等差数列
        # 这一步等于没做，self._normalized_time和self._timesteps完全等价
        self.register_normalized_timestamps()

        # self._normalized_time和训练集中的frame/图像长度相等，一一对应
        
        for idx, cam_id in enumerate(self.camera_list):
            camera = XpengCameraData(
                dataset_name=self.dataset_name,
                data_path=self.data_path,
                cam_id=cam_id,
                start_timestep=self.start_timestep,
                end_timestep=self.end_timestep,
                load_dynamic_mask=self.data_cfg.load_dynamic_mask,
                load_projected_lidar_depth=self.data_cfg.load_projected_lidar_depth,
                load_sky_mask=self.data_cfg.load_sky_mask,
                load_tfl_mask=self.data_cfg.get("load_tfl_mask", False),
                load_ground_mask=self.data_cfg.load_ground_mask,
                egocar_dilated_mask=self.data_cfg.egocar_dilated_mask,
                downscale_when_loading=self.data_cfg.downscale_when_loading[idx],
                undistort=self.data_cfg.undistort,
                buffer_downscale=self.buffer_downscale,
                device=self.device,
                data_source=self.data_source
            )
            # 注意self.normalized_time和self._normalized_time等价，self.normalized_time即return self._normalized_time
            camera.load_time(self.normalized_time)
            unique_img_idx = torch.arange(len(camera), device=self.device) * len(self.camera_list) + idx
            camera.set_unique_ids(unique_cam_idx=idx, unique_img_idx=unique_img_idx)
            self.camera_data[cam_id] = camera

    def _get_valid_timestamps(self):
        localpose = json.load(open(os.path.join(self.data_path, "localpose.json")))
        self.localpose = localpose
        timestamps = sorted([int(k) for k in localpose.keys()])
        timestamps_valid = timestamps[self.start_timestep : self.end_timestep]
        return timestamps_valid
    
    def _generate_dist_from_ego_to_obj_dict(self, instances_pose, save_cache=False):
        # ego pose
        localpose = self.localpose
        if not localpose:
            localpose = json.load(open(os.path.join(self.data_path, "localpose.json")))
        
        # obj poses
        # instances_pose: (num_frames, num_instances, 4, 4), obj_to_world
        num_frames, num_instances = instances_pose.shape[0], instances_pose.shape[1]
        dist_ego_to_obj_dict = {}

        for frame_idx in range(num_frames):
            dist_ego_to_obj_dict[frame_idx] = {}
            ego_to_world = np.array(localpose[self.timestamps[frame_idx]])
            world_to_ego = np.linalg.inv(ego_to_world)

            for inst_idx in range(num_instances):
                # skip the invalid instances
                if torch.all(instances_pose[frame_idx, inst_idx] == 0): 
                    continue
                
                obj_to_world = instances_pose[frame_idx, inst_idx].numpy()
                obj_to_ego = world_to_ego @ obj_to_world
                obj_translation_in_ego = obj_to_ego[:3, 3]
                dist_ego_to_obj = np.linalg.norm(obj_translation_in_ego)
                dist_ego_to_obj_dict[frame_idx][inst_idx] = dist_ego_to_obj

        # write to self.data_path as a cache file
        if save_cache:
            cache_path = os.path.join(self.data_path, "dist_ego_to_obj_all_frames.json")
            with open(cache_path, "w") as fw:
                json.dump(dist_ego_to_obj_dict, fw)

        return dist_ego_to_obj_dict
    
    def _check_obj_dist_level(self, dist_ego_to_obj_dict):
        # key: object index, value: distance level
        # near level (0): 0-10m, mid level (1): 10-30m, far level (2): >30m
        # far level can converted to mid/near level, mid level can converted to near level, not allow the opposite
        obj_dist_level_dict = {}

        # check each object's distance level in all frames, once it reaches a level, it belongs to that level
        for frame_idx in dist_ego_to_obj_dict:
            for inst_idx in dist_ego_to_obj_dict[frame_idx]:
                dist_ego_to_obj = dist_ego_to_obj_dict[frame_idx][inst_idx]
                # initialize as far level
                if inst_idx not in obj_dist_level_dict:
                    obj_dist_level_dict[inst_idx] = DistLevel.Far  # far level

                # update distance level
                if dist_ego_to_obj <= 10.0:
                    obj_dist_level_dict[inst_idx] = DistLevel.Close  # near level
                elif dist_ego_to_obj <= 30.0 and obj_dist_level_dict[inst_idx] > DistLevel.Mid:
                    obj_dist_level_dict[inst_idx] = DistLevel.Mid  # mid level

        logging.info(f"Object distance level dict: {obj_dist_level_dict}")

        return obj_dist_level_dict

    def load_objects(self):
        """
        get ground truth bounding boxes of the dynamic objects
        """
        annotation_path = os.path.join(self.data_path, "annotation_for_train.json")
        annotation_json = json.load(open(annotation_path))
        timestamps_valid = self._get_valid_timestamps()

        gid_to_localid = {}
        localid = 0
        for frame in annotation_json["frames"]:
            if int(frame["timestamp"]) not in timestamps_valid:
                continue
            for o in frame["objects"]:
                if o["gid"] not in gid_to_localid:
                    gid_to_localid[o["gid"]] = localid
                    localid += 1

        localid_to_gid = {v: k for k, v in gid_to_localid.items()}
        num_instances = len(gid_to_localid)

        num_full_frames = len(timestamps_valid)
        timestamps = []
        instances_pose = np.zeros((num_full_frames, num_instances, 4, 4))
        instances_size = np.zeros((num_full_frames, num_instances, 3))
        instances_true_id = np.arange(num_instances)
        instances_global_id = np.array([localid_to_gid[i] for i in range(num_instances)])
        instance_class_types = [[] for i in range(num_instances)]
        instances_model_types = np.ones(num_instances) * -1
        instances_types = np.ones((num_full_frames, num_instances)) * -1

        instances_moving = torch.empty((num_full_frames, num_instances), dtype=torch.bool)
        instances_moving.fill_(True)

        # get annotation info
        frame_idx = 0
        for frame in annotation_json["frames"]:
            if int(frame["timestamp"]) not in timestamps_valid:
                continue
            for o in frame["objects"]:
                gid = o["gid"]
                localid = gid_to_localid[gid]
                obj_trans = np.array(o["translation"])
                obj_rot = quaternion_matrix(np.array(o["rotation"]))[:3, :3]
                obj_size = np.array(o["size"])
                obj_to_world = np.eye(4)
                obj_to_world[:3, :3] = obj_rot
                obj_to_world[:3, 3] = obj_trans
                instances_pose[frame_idx, localid] = obj_to_world
                instances_size[frame_idx, localid] = obj_size
                instances_moving[frame_idx, localid] = o["is_moving"]
                instance_class_types[localid].append(o["type"])
                instances_types[frame_idx, localid] = OBJECT_TYPE[o["type"]]
            timestamps.append(frame["timestamp"])
            frame_idx += 1

        # get object types
        for i in range(num_instances):
            class_types = list(set(instance_class_types[i]))
            is_smpl_open = self.data_cfg.get("load_smpl", False)
            if len(class_types) == 1 and class_types[0] in OBJECT_CLASS_NODE_MAPPING:
                curr_object_class = OBJECT_CLASS_NODE_MAPPING[class_types[0]]
                if not is_smpl_open and curr_object_class == ModelType.SMPLNodes:
                    print(f"[WARNING] SMPL loading is disabled, but instance {i} is pedestrian, use rigid node as default.")
                    instances_model_types[i] = ModelType.RigidNodes
                else:   
                    instances_model_types[i] = curr_object_class
            else:
                print(f"[WARNING] Unknown object class: {class_types}, use rigid node as default.")
                instances_model_types[i] = ModelType.RigidNodes

        # get frame valid instances
        # shape (num_frames, num_instances)
        per_frame_instance_mask = np.zeros((num_full_frames, num_instances))
        frame_idx = 0
        for frame in annotation_json["frames"]:
            if int(frame["timestamp"]) not in timestamps_valid:
                continue
            for o in frame["objects"]:
                localid = gid_to_localid[o["gid"]]
                per_frame_instance_mask[frame_idx, localid] = 1
            frame_idx += 1

        # select the frames that are in the range of start_timestep and end_timestep
        instances_pose = torch.from_numpy(instances_pose).float()
        instances_size = torch.from_numpy(instances_size).float()
        instances_true_id = torch.from_numpy(instances_true_id).long()
        instances_global_id = torch.from_numpy(instances_global_id).long()
        instances_types = torch.from_numpy(instances_types).long()
        instances_model_types = torch.from_numpy(np.array(instances_model_types)).long()
        per_frame_instance_mask = torch.from_numpy(per_frame_instance_mask).bool()

        # filter out the instances that are not visible in selected frames
        ins_frame_cnt = per_frame_instance_mask.sum(dim=0)
        instances_pose = instances_pose[:, ins_frame_cnt > 0]
        instances_size = instances_size[:, ins_frame_cnt > 0]
        instances_true_id = instances_true_id[ins_frame_cnt > 0]
        instances_global_id = instances_global_id[ins_frame_cnt > 0]
        instances_types = instances_types[:, ins_frame_cnt > 0]
        instances_model_types = instances_model_types[ins_frame_cnt > 0]
        per_frame_instance_mask = per_frame_instance_mask[:, ins_frame_cnt > 0]
        instances_moving = instances_moving[:, ins_frame_cnt > 0]

        self.localpose = json.load(open(os.path.join(self.data_path, "localpose.json")))

        # assign to the class
        # (num_frames, num_instances)
        self.instances_moving = instances_moving
        # (num_frames, num_instances, 4, 4)
        self.instances_pose = instances_pose
        self.origin_instances_size = instances_size
        # (num_instances, 3)
        self.instances_origin_size = instances_size
        # (num_instances, 3)
        self.instances_size = instances_size.sum(0) / per_frame_instance_mask.sum(0).unsqueeze(-1)
        # (num_frames, num_instances)
        self.per_frame_instance_mask = per_frame_instance_mask
        # (num_instances)
        self.instances_true_id = instances_true_id
        self.instances_global_id = instances_global_id
        self.instances_model_types = instances_model_types
        self.instances_types = instances_types
        self.timestamps = timestamps

        dist_ego_to_obj_dict = self._generate_dist_from_ego_to_obj_dict(self.instances_pose)
        self.obj_dist_level_dict = self._check_obj_dist_level(dist_ego_to_obj_dict)

        # load SMPL parameters
        if self.data_cfg.load_smpl:
            # load SMPL parameters
            smpl_dict = joblib.load(os.path.join(self.data_path, "humanpose", "smpl.pkl"))
            frame_num = self.end_timestep - self.start_timestep

            smpl_human_all = {}
            for fi in tqdm(range(self.start_timestep, self.end_timestep), desc="Loading SMPL"):
                for instance_id, ins_smpl in smpl_dict.items():
                    if instance_id not in smpl_human_all:
                        smpl_human_all[instance_id] = {
                            "smpl_quats": torch.zeros((frame_num, 24, 4), dtype=torch.float32),
                            "smpl_trans": torch.zeros((frame_num, 3), dtype=torch.float32),
                            "smpl_betas": torch.zeros((frame_num, 10), dtype=torch.float32),
                            "frame_valid": torch.zeros((frame_num), dtype=torch.bool)
                        }
                        smpl_human_all[instance_id]["smpl_quats"][:, :, 0] = 1.0
                    
                    if ins_smpl["valid_mask"][fi]:
                        betas = ins_smpl["smpl"]["betas"][fi]
                        smpl_human_all[instance_id]["smpl_betas"][fi - self.start_timestep] = betas
                        
                        body_pose = ins_smpl["smpl"]["body_pose"][fi]
                        smpl_orient = ins_smpl["smpl"]["global_orient"][fi]
                        cam_depend = ins_smpl["selected_cam_idx"][fi].item()

                        print(f"[load_objects] fi: {fi}, start_time: {self.start_timestep}, instance_id: {instance_id}, localid: {gid_to_localid[instance_id]}, cam_depend: {cam_depend}, instances shape: {self.instances_pose.shape}")
                        c2w = self.camera_data[cam_depend].cam_to_worlds[fi - self.start_timestep]
                        world_orient = c2w[:3, :3].to(smpl_orient.device) @ smpl_orient.squeeze()
                        smpl_quats = matrix_to_quaternion(
                            torch.cat([world_orient[None, ...], body_pose], dim=0)
                        )
                        
                        # get obj2world from instances_pose
                        o2w = self.instances_pose[fi - self.start_timestep, gid_to_localid[instance_id]]

                        smpl_human_all[instance_id]["smpl_quats"][fi - self.start_timestep] = smpl_quats
                        smpl_human_all[instance_id]["smpl_trans"][fi - self.start_timestep] = o2w[:3, 3]
                        smpl_human_all[instance_id]["frame_valid"][fi - self.start_timestep] = True

            self.smpl_human_all = smpl_human_all
            print(f"Total loaded SMPL humans: {len(self.smpl_human_all)}")
        else:
            self.smpl_human_all = {}
            print("SMPL loading is disabled.")

    def load_max_range_info(self):
        range_json_path = os.path.join(self.data_path, "range.json")
        if not os.path.exists(range_json_path):
            timestamps_valid = self._get_valid_timestamps()
            self.max_range_info = {}
            frame_idx = 0
            for timestamp in timestamps_valid:
                self.max_range_info[frame_idx] = [np.inf, -np.inf]
                frame_idx += 1
            print(f"max_range_info: {len(self.max_range_info)}")
            print(f"timestamps_valid: {len(timestamps_valid)}")
            assert len(self.max_range_info) == len(timestamps_valid)
            return

        max_ranges = json.load(open(range_json_path))
        timestamps_valid = self._get_valid_timestamps()
        self.max_range_info = {}
        max_range_timestamps = [int(t) for t in sorted(max_ranges.keys())]

        frame_idx = 0
        for timestamp in timestamps_valid:
            max_range_idx = np.abs(np.array(max_range_timestamps) - timestamp).argmin()
            ts_in_ranges = str(max_range_timestamps[max_range_idx])
            self.max_range_info[frame_idx] = [max_ranges[ts_in_ranges]["left_range"], max_ranges[ts_in_ranges]["right_range"]]
            frame_idx += 1

        print(f"max_range_info: {len(self.max_range_info)}")
        print(f"timestamps_valid: {len(timestamps_valid)}")
        assert len(self.max_range_info) == len(timestamps_valid)

    def object_init_check(self, cur_node_type, o_type):
        if cur_node_type == "DeformableNodes":
            if not (o_type == ModelType.DeformableNodes or o_type == ModelType.SMPLNodes):
                return True
        elif cur_node_type == "RigidNodes" or cur_node_type == "RigidNodesLight":
            if not o_type == ModelType.RigidNodes:
                return True
        return False

    def load_obj_boundings(self):
        anchor_pose = np.array(json.load(open(os.path.join(self.data_path, "anchorpose.json"), "r")))
        world2anchor = np.linalg.inv(anchor_pose)
        for _, cam_id in enumerate(self.camera_list):
            ixt = self.camera_data[cam_id].intrinsics.numpy()
            ext = self.camera_data[cam_id].cam_to_ego.numpy()
            h = self.camera_data[cam_id].original_size[0]
            w = self.camera_data[cam_id].original_size[1]
            num_frames = self.instances_pose.shape[0]
            num_instances = self.instances_pose.shape[1]
            dynamic_masks = []
            for frame_idx in tqdm(
                range(num_frames),
                desc="Loading dynamic masks",
                dynamic_ncols=True,
                total=num_frames,
            ):
                obj_bound = np.zeros((h, w)).astype(np.uint8)
                for instance_idx in range(num_instances):
                    if not self.per_frame_instance_mask[frame_idx, instance_idx]:
                        continue
                    instance_obj_to_world = self.instances_pose[frame_idx, instance_idx]
                    instance_size = self.origin_instances_size[frame_idx, instance_idx]
                    instance_obj_pose = torch.tensor(
                        world2anchor @ np.array(self.localpose[self.timestamps[frame_idx]])
                    ).float()
                    instance_obj_pose_vehicle = torch.inverse(instance_obj_pose) @ instance_obj_to_world
                    obj_length = instance_size[0].numpy()
                    obj_width = instance_size[1].numpy()
                    obj_height = instance_size[2].numpy()
                    bbox = np.array([[-obj_length, -obj_width, -obj_height], [obj_length, obj_width, obj_height]]) * 0.5
                    corners_local = bbox_to_corner3d(bbox)
                    corners_local = np.concatenate([corners_local, np.ones_like(corners_local[..., :1])], axis=-1)
                    corners_vehicle = (
                        corners_local @ instance_obj_pose_vehicle.numpy().T
                    )  # 3D bounding box in vehicle frame
                    mask_func_input = dict(
                        {
                            "corners_3d": corners_vehicle[..., :3],
                            "K": ixt[frame_idx],
                            "pose": np.linalg.inv(ext),
                            "H": h,
                            "W": w,
                        }
                    )
                    mask = get_bound_2d_mask(**mask_func_input)
                    if mask.sum() / int(mask.shape[0] * mask.shape[1]) > 0.95:
                        mask = get_bound_2d_mask_fix(**mask_func_input)
                    obj_bound = np.logical_or(obj_bound, mask)
                dynamic_masks.append(obj_bound > 0)
            self.camera_data[cam_id].dynamic_masks = torch.from_numpy(np.stack(dynamic_masks, axis=0)).bool()


class XpengLiDARSource(SceneLidarSource):
    def __init__(
        self,
        lidar_data_config: OmegaConf,
        data_path: str,
        start_timestep: int,
        end_timestep: int,
        device: None,
    ):
        super().__init__(lidar_data_config, device=device)
        self.data_path = data_path
        self.start_timestep = start_timestep
        self.end_timestep = end_timestep
        self.create_all_filelist()
        self.device = device

    def create_all_filelist(self):
        """
        Create a list of all the files in the dataset.
        e.g., a list of all the lidar scans in the dataset.
        """
        self.background_pcd_filepath = os.path.join(self.data_path, "input_ply", "points3D_bkgd.ply")
        self.gound_mask_filepath = os.path.join(self.data_path, "ground_mask.npy")
        self.object_pcd_filepaths = sorted(glob.glob(os.path.join(self.data_path, "input_ply", "points3D_obj_*.ply")))
        self.traffic_light_pcd_filepath = os.path.join(self.data_path,"input_ply","points3D_tfl.ply")

    def load_calibrations(self):
        pass

    def load_lidar(self):
        pass

    def ground_mask(self):
        mask_array = np.load(self.gound_mask_filepath)
        # Handle both 1D and 2D arrays
        if mask_array.ndim == 2:
            ground_mask = torch.from_numpy(mask_array[:, 0]).bool()
        else:
            ground_mask = torch.from_numpy(mask_array).bool()
        if self.device is not None:
            ground_mask = ground_mask.to(self.device)
        return ground_mask

    def background_points(self):
        # load background pcds
        background_pcd = fetchPly(self.background_pcd_filepath)
        background_pts_xyz = torch.tensor(background_pcd.points, dtype=torch.float32)
        background_colors = torch.tensor(background_pcd.colors, dtype=torch.float32)
        # background_colors = torch.tensor(np.zeros((len(background_pcd.points), 3)), dtype=torch.float32)
        if self.device is not None:
            background_pts_xyz = background_pts_xyz.to(self.device)
            background_colors = background_colors.to(self.device)
        return background_pts_xyz, background_colors

    def trafficlight_points(self):
        # load trafficlight pcds
        tfl_pcd = fetchPly(self.traffic_light_pcd_filepath)
        tfl_pts_xyz = torch.tensor(tfl_pcd.points, dtype=torch.float32)
        tfl_colors = torch.tensor(tfl_pcd.colors, dtype=torch.float32)
        if self.device is not None:
            tfl_pts_xyz = tfl_pts_xyz.to(self.device)
            tfl_colors = tfl_colors.to(self.device)
        return tfl_pts_xyz, tfl_colors

    def object_points(self):
        # load object pcds
        object_pts_xyz = {}
        object_colors = {}
        for obj_pcd_filepath in self.object_pcd_filepaths:
            gid = int(os.path.basename(obj_pcd_filepath).split("_")[-1].split(".")[0])
            pts, colors = load_xpeng_obj_points(gid, obj_pcd_filepath)
            if pts is None or colors is None:
                continue
            object_pts_xyz[gid] = torch.tensor(pts, dtype=torch.float32)
            object_colors[gid] = torch.tensor(colors, dtype=torch.float32)
            if self.device is not None:
                object_pts_xyz[gid] = object_pts_xyz[gid].to(self.device)
                object_colors[gid] = object_colors[gid].to(self.device)
        return object_pts_xyz, object_colors

    def to(self, device: torch.device):
        self.device = device

    def get_lidar_rays(self, time_idx: int) -> Dict[str, Tensor]:
        raise NotImplementedError("[ERROR] LiDAR get_lidar_rays is invalid for xpeng dataset.")

    def delete_invisible_pts(self) -> None:
        """
        Clear the unvisible points.
        """
        logger.info("[Lidar] No unvisible points to clear.")
        raise NotImplementedError

    def get_aabb(self) -> Tensor:
        """
        Returns:
            aabb_min, aabb_max: the min and max of the axis-aligned bounding box of the scene
        Note:
            we assume the lidar points are already in the world coordinate system
            we first downsample the lidar points, then compute the aabb by taking the
            given percentiles of the lidar coordinates in each dimension.
        """
        logger.info("[Lidar] Computing auto AABB based on downsampled lidar points....")

        background_pts_xyz, _ = self.background_points()
        # downsample the lidar points by uniformly sampling a subset of them
        lidar_pts = background_pts_xyz[
            torch.randperm(len(background_pts_xyz))[
                : int(len(background_pts_xyz) / self.data_cfg.lidar_downsample_factor)
            ]
        ]
        # compute the aabb by taking the given percentiles of the lidar coordinates in each dimension
        aabb_min = torch.quantile(lidar_pts, self.data_cfg.lidar_percentile, dim=0)
        aabb_max = torch.quantile(lidar_pts, 1 - self.data_cfg.lidar_percentile, dim=0)

        # TODO: images from back cameras at initial frames are not reliable, so we need to extend the aabb.
        #  But I'm not sure if it is necessary to do this.

        # usually the lidar's height is very small, so we slightly increase the height of the aabb
        if aabb_max[-1] < 20:
            aabb_max[-1] = 20.0
        aabb = torch.tensor([*aabb_min, *aabb_max])
        logger.info(f"[Lidar] Auto AABB from LiDAR: {aabb}")
        return aabb