
from multiprocessing.pool import ThreadPool as Pool
from os.path import exists, getsize

import cv2
import numpy as np
from torch.utils.data import Dataset
from copy import deepcopy

class BaseDataset(Dataset):
    def __init__(self):
        self.base_dir = ""
        self.image_filenames = []  # list of image relative path w.r.t to self.base_dir
        self.label_filenames = []  # list of label relative path w.r.t to self.base_dir
        self.ref_camera2world = []  # list of 4x4 ndarray camera2world transform
        self.cameras_K = []  # list of 3x3 ndarray camera intrinsics
        self.cameras_d = []  # list of camera distortion coefficients
        self.cameras_idx = []  # list of camera idx
        self.camera_extrinsics = []

        self.image_filenames_all = []  # list of image relative path w.r.t to self.base_dir
        self.depth_filenames_all = []  # list of depth relative path w.r.t to self.base_dir
        self.label_filenames_all = []  # list of label relative path w.r.t to self.base_dir
        self.lane_filenames_all = []   # list of lane relative path w.r.t to self.base_dir
        self.ref_camera2world_all = []  # list of 4x4 ndarray camera2world transform
        self.ori_world_to_new_world = [] # transform origin world to new world
        self.cameras_K_all = []  # list of 3x3 ndarray camera intrinsics
        self.cameras_d_all = []  # list of camera distortion coefficients
        self.cameras_idx_all = []  # list of camera idx
        self.camera_extrinsics_all = []
        self.image_extrics_idx_all = [] # list of image extrinsics idx

    def __len__(self):
        return len(self.image_filenames)

    def filter_by_index(self, index):
        self.image_filenames_all = [self.image_filenames_all[i] for i in index]
        self.label_filenames_all = [self.label_filenames_all[i] for i in index]
        self.lane_filenames_all = [self.lane_filenames_all[i] for i in index]
        self.ref_camera2world_all = [self.ref_camera2world_all[i] for i in index]
        self.cameras_K_all = [self.cameras_K_all[i] for i in index]
        self.cameras_d_all = [self.cameras_d_all[i] for i in index]
        self.cameras_idx_all = [self.cameras_idx_all[i] for i in index]
        if hasattr(self, "depth_filenames_all"):
            self.depth_filenames_all = [self.depth_filenames_all[i] for i in index]

    @ staticmethod
    def file_valid(file_name):
        if exists(file_name) and (getsize(file_name) != 0):
            return True
        else:
            return False

    @ staticmethod
    def check_filelist_exist(filelist):
        with Pool(32) as p:
            exist_list = p.map(BaseDataset.file_valid, filelist)
        return exist_list

    def remap_semantic(self, semantic_label):
        semantic_label = semantic_label.astype('uint8')
        remaped_label = np.array(cv2.LUT(semantic_label, self.label_remaps))
        return remaped_label

    def set_waypoint(self, center_xy, radius):
        center_xy = np.asarray([center_xy[0], center_xy[1]], dtype=np.float32)
        all_camera_xy = np.asarray(self.ref_camera2world_all)[:, :2, 3]
        distances = np.linalg.norm(all_camera_xy - center_xy, ord=np.inf, axis=1)
        activated_idx = list(np.where(distances < radius)[0])
        self.image_filenames = [self.image_filenames_all[i] for i in activated_idx]
        self.label_filenames = [self.label_filenames_all[i] for i in activated_idx]
        self.lane_filenames = [self.lane_filenames_all[i] for i in activated_idx]
        self.cameras_idx = [self.cameras_idx_all[i] for i in activated_idx]
        self.cameras_K = [self.cameras_K_all[i] for i in activated_idx]
        self.cameras_d = [self.cameras_d_all[i] for i in activated_idx]
        self.ref_camera2world = [self.ref_camera2world_all[i] for i in activated_idx]
        if hasattr(self, "depth_filenames_all"):
            self.depth_filenames = [self.depth_filenames_all[i] for i in activated_idx]
        self.activated_idx = activated_idx

    def opencv_camera2pytorch3d_(self, sample):
        focal_length, principal_point, image_shape = self.__opencv_camera2pytorch3d(sample["camera_K"], sample["image_shape"])
        sample["focal_length"] = focal_length
        sample["principal_point"] = principal_point
        sample["image_shape"] = image_shape
        return sample

    def __opencv_camera2pytorch3d(self, camera_K, image_shape):
        """Convert OpenCV camera convension to pytorch3d convension

        Args:
            camera_K (ndarray): 3x3 intrinsic matrix
            image_shape (ndarray): [image_heigt, width]
        """
        focal_length = np.asarray([camera_K[0, 0], camera_K[1, 1]])
        principal_point = camera_K[:2, 2]
        image_size_wh = np.asarray([image_shape[1], image_shape[0]], dtype=image_shape.dtype)
        scale = (image_size_wh * 0.5).astype(camera_K.dtype)
        c0 = image_size_wh / 2.0

        focal_length /= scale
        principal_point = (principal_point - c0) / scale
        return focal_length, principal_point, image_shape
