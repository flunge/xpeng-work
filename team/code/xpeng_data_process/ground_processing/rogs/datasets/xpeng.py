import json
import os
from copy import deepcopy
from multiprocessing.pool import ThreadPool as Pool
from pathlib import Path

import cv2
import numpy as np
from plyfile import PlyData, PlyElement
from pyquaternion import Quaternion
from tqdm import tqdm

from ..datasets.base import BaseDataset


def get_xpeng_filted_color_map():
    colors = np.zeros((256, 1, 3), dtype='uint8')
    colors[0, :, :] = [0, 0, 0]  # mask
    colors[1, :, :] = [0, 0, 255]  # all lane
    colors[2, :, :] = [255, 0, 0]  # curb
    colors[3, :, :] = [211, 211, 211]  # road and manhole
    colors[4, :, :] = [0, 191, 255]  # sidewalk
    colors[5, :, :] = [152, 251, 152]  # terrain
    colors[6, :, :] = [157, 234, 50]  # background
    return colors


def get_xpeng_origin_color_map():
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


def get_xpeng_label_remaps():
    colors = np.ones((256, 1), dtype="uint8")
    colors *= 6  # background
    colors[7, :] = 1  # Lane marking
    colors[8, :] = 1
    colors[14, :] = 1
    colors[23, :] = 1
    colors[24, :] = 1
    colors[2, :] = 2  # curb
    colors[9, :] = 2  # curb cut
    colors[41, :] = 3  # Manhole
    colors[13, :] = 3  # road
    colors[15, :] = 4  # sidewalk
    colors[29, :] = 5  # terrain
    return colors


def label2mask(label):
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
    label_off_road = ((0 <= label) & (label <= 1)) | ((3 <= label) & (label <= 6)) | ((10 <= label) & (label <= 12)) \
                     | ((16 <= label) & (label <= 22)) | ((25 <= label) & (label <= 28)) | (
                             (30 <= label) & (label <= 40)) | (label >= 42)

    # dilate itereation 2 for moving objects
    label_movable = label >= 52
    kernel = np.ones((10, 10), dtype=np.uint8)
    label_movable = cv2.dilate(label_movable.astype(np.uint8), kernel, 2).astype(bool)

    label_off_road = label_off_road | label_movable
    mask[label_off_road] = 0
    label[~(mask.astype(bool))] = 64
    mask = mask.astype(np.float32)
    return mask, label


def worldpoint2camera(points: np.ndarray, WH, cam2world, cam_intrinsic, min_dist: float = 1.0):
    """
    1. transform world points to camera points
    Args:
        points: (N, 3)
        image:  (H, W, 3)
        cam2world: (4, 4)
        cam_intrinsic: (3, 3)
        min_dist: float

    Returns:
        uv: (2, N)
        depths: (N, )
        mask: (N, )

    """
    width, height = WH
    world2cam = np.linalg.inv(cam2world)  # (4, 4)
    points_cam = world2cam[:3, :3] @ points.T + world2cam[:3, 3:4]  # (3, N)
    depths = points_cam[2, :]  # (N, )
    points_uv1 = view_points(points_cam, np.array(cam_intrinsic), normalize=True)  # (3, N)

    # Remove points that are either outside or behind the camera. Leave a margin of 1 pixel for aesthetic reasons.
    # Also make sure points are at least 1m in front of the camera to avoid seeing the lidar points on the camera
    # casing for non-keyframes which are slightly out of sync.
    mask = np.ones(depths.shape[0], dtype=bool)
    mask = np.logical_and(mask, depths > min_dist)
    mask = np.logical_and(mask, points_uv1[0, :] > 1)
    mask = np.logical_and(mask, points_uv1[0, :] < width - 1)
    mask = np.logical_and(mask, points_uv1[1, :] > 1)
    mask = np.logical_and(mask, points_uv1[1, :] < height - 1)

    uv = points_uv1[:, mask][:2, :]
    uv = np.round(uv).astype(np.uint16)
    depths = depths[mask]
    return uv, depths, mask



def view_points(points: np.ndarray, view: np.ndarray, normalize: bool) -> np.ndarray:
    """
    This is a helper class that maps 3d points to a 2d plane. It can be used to implement both perspective and
    orthographic projections. It first applies the dot product between the points and the view. By convention,
    the view should be such that the data is projected onto the first 2 axis. It then optionally applies a
    normalization along the third dimension.

    For a perspective projection the view should be a 3x3 camera matrix, and normalize=True
    For an orthographic projection with translation the view is a 3x4 matrix and normalize=False
    For an orthographic projection without translation the view is a 3x3 matrix (optionally 3x4 with last columns
     all zeros) and normalize=False

    :param points: <np.float32: 3, n> Matrix of points, where each point (x, y, z) is along each column.
    :param view: <np.float32: n, n>. Defines an arbitrary projection (n <= 4).
        The projection should be such that the corners are projected onto the first 2 axis.
    :param normalize: Whether to normalize the remaining coordinate (along the third axis).
    :return: <np.float32: 3, n>. Mapped point. If normalize=False, the third coordinate is the height.
    """

    assert view.shape[0] <= 4
    assert view.shape[1] <= 4
    assert points.shape[0] == 3

    viewpad = np.eye(4)
    viewpad[:view.shape[0], :view.shape[1]] = view

    nbr_points = points.shape[1]

    # Do operation in homogenous coordinates.
    points = np.concatenate((points, np.ones((1, nbr_points))))
    points = np.dot(viewpad, points)
    points = points[:3, :]

    if normalize:
        points = points / points[2:3, :].repeat(3, 0).reshape(3, nbr_points)

    return points


def load_localpose_and_anchorpose_from_json(clip_path):
    clip_path = Path(clip_path)
    localpose_anchored = {}
    localpose_global = json.load(open(clip_path / "localpose.json"))
    anchorpose = np.array(json.load(open(clip_path / "anchorpose.json", "r")))
    world2anchor = np.linalg.inv(anchorpose)
    for timestamp, pose in localpose_global.items():
        localpose_anchored[timestamp] = world2anchor @ np.array(pose).reshape(4, 4)

    return localpose_anchored, anchorpose


def draw_depth_image(img, depth_image, point_size=1, max_distance=100, valid_mask=None):
    depth_normalized = np.clip(depth_image, a_min=0, a_max=max_distance) / max_distance
    depth_normalized = np.expand_dims((depth_normalized * 255).astype(np.uint8), axis=-1)
    # 使用 matplotlib 的 colormap (例如 'viridis' 或 'jet')
    # colormap = cm.get_cmap('jet')  # 'jet' 映射为蓝-绿-红梯度
    rgb_image = cv2.applyColorMap(depth_normalized, cv2.COLORMAP_JET)
    # depth_colors = colormap(depth_normalized)[:, :3]  # 提取 RGB 值 (忽略 alpha 通道)
    # depth_colors = (depth_colors * 255)
    for x in range(depth_normalized.shape[0]):
        for y in range(depth_normalized.shape[1]):
            if valid_mask is not None and not valid_mask[x, y]:
                continue
            color = rgb_image[x, y]
            color = (int(color[0]), int(color[1]), int(color[2]))
            cv2.circle(img, (y, x), point_size, color, -1)


def load_gt_points(ply_path):
    plydata = PlyData.read(ply_path)
    xyz = np.stack((np.asarray(plydata.elements[0]["x"]),
                    np.asarray(plydata.elements[0]["y"]),
                    np.asarray(plydata.elements[0]["z"])), axis=1)  # [N, 3]
    rgb = np.stack((np.asarray(plydata.elements[0]["red"]),
                    np.asarray(plydata.elements[0]["green"]),
                    np.asarray(plydata.elements[0]["blue"])), axis=1)
    # label = np.asarray(plydata.elements[0]["label"]).astype(np.uint8)
    # label = label[..., None]  # [N, 1]
    return xyz, rgb #, label


class XpengDataset(BaseDataset):
    def __init__(self, configs, use_label=True, use_depth=False):
        super().__init__()
        self.resized_image_size = (configs["image_width"], configs["image_height"])
        self.camera_names = configs["camera_names"]
        self.min_distance = configs["min_distance"]

        self.use_label = use_label
        self.use_depth = use_depth

        self.cfg = configs
        self.base_dir = self.cfg["clip_path"]
        self.image_dir = self.cfg["clip_path"]
        self.transform_name = "transform.json"
        self.transform_json = json.load(open(os.path.join(self.cfg["clip_path"], self.transform_name), "r"))

        self.localpose, self.anchorpose = load_localpose_and_anchorpose_from_json(self.cfg["clip_path"])
        print(f"localpose: {len(self.localpose)}")

        self.depth_images = []

        for frame in self.transform_json["frames"]:
            file_path = frame["file_path"]
            K = np.eye(3, 3)
            K[0, 0] = frame["fl_x"]
            K[1, 1] = frame["fl_y"]
            K[0, 2] = frame["cx"]
            K[1, 2] = frame["cy"]
            w, h = frame["w"], frame["h"]
            camera_name = frame["camera"]
            timestamp = frame["timestamp"]
            camera2world = np.array(frame["transform_matrix"])

            if camera_name not in self.camera_names:
                continue

            self.chassis2world_all.append(self.localpose[str(timestamp)])
            self.camera2world_all.append(camera2world)
            self.camera_times_all.append(timestamp)
            self.cameras_K_all.append(K)
            self.cameras_idx_all.append(self.camera_names.index(camera_name))
            self.image_filenames_all.append(file_path)
            self.label_filenames_all.append(file_path.replace("images", "segs"))

            if self.use_depth:
                npy_file_name = os.path.join(self.cfg["clip_path"], file_path.replace("images", "depth")[:-4] + ".npy")
                if not os.path.exists(npy_file_name):
                    print(f"[WARNING] No depth file for {file_path}, skip this frame.")
                    continue
                npy_file = np.load(npy_file_name, allow_pickle=True).tolist()
                dimage = np.zeros((h, w), dtype=np.float32)
                if len(npy_file['value'].shape) == 1:
                    dimage[npy_file['mask']] = npy_file['value']
                else:
                    dimage[npy_file['mask']] = npy_file['value'][:, 1]
                    dimage = (dimage + 1) * 50
                self.depth_images.append(dimage)

        self.file_check()
        if len(self.image_filenames_all) == 0:
            raise FileNotFoundError("No data found in the dataset")

        self.chassis2world_unique = np.array(list(self.localpose.values()))
        print(f"self.chassis2world_unique shape: {self.chassis2world_unique.shape}")
        self.chassis2world_all = np.array(self.chassis2world_all)
        self.camera2world_all = np.array(self.camera2world_all)
        self.camera_times_all = np.array(self.camera_times_all)
        self.ref_pose = self.anchorpose

        self.road_pointcloud = None
        if "ground_ply" in configs and os.path.exists(configs["ground_ply"]):
            xyz, rgb = load_gt_points(configs["ground_ply"])
            self.road_pointcloud = {"xyz": xyz, "rgb": rgb}

        nerf_normalization = self.getNerfppNorm()
        self.cameras_extent = nerf_normalization["radius"]

        # 构建与 reconic 相同规则的 unique_img_idx：
        # unique_img_idx = frame_idx * num_cameras + cam_idx
        self._build_unique_img_idx()

    def __len__(self):
        return len(self.image_filenames_all)

    def __getitem__(self, idx):
        cam_idx = self.cameras_idx_all[idx]
        cam2world = self.camera2world_all[idx]
        K = self.cameras_K_all[idx]
        camera_name = self.camera_names[cam_idx]
        image_path = os.path.join(self.base_dir, self.image_filenames_all[idx])
        image_name = os.path.basename(image_path).split(".")[0]
        input_image = cv2.imread(image_path)
        if input_image is None:
            raise FileNotFoundError(f"[ERROR][RoGS] Image file not found: {image_path}")

        origin_image_size = input_image.shape
        crop_cy = origin_image_size[0] // 2  # int(self.resized_image_size[1] * 0.5)
        resized_image = input_image  # cv2.resize(input_image, dsize=self.resized_image_size, interpolation=cv2.INTER_LINEAR)
        resized_image = cv2.cvtColor(resized_image, cv2.COLOR_BGR2RGB)
        resized_image = resized_image[crop_cy:, :, :]
        gt_image = (np.asarray(resized_image) / 255.0).astype(np.float32)
        gt_image = np.clip(gt_image, 0.0, 1.0)
        width, height = gt_image.shape[1], gt_image.shape[0]

        new_K = deepcopy(K)
        # width_scale = self.resized_image_size[0] / origin_image_size[1]
        # height_scale = self.resized_image_size[1] / origin_image_size[0]
        # new_K[0, :] *= width_scale
        # new_K[1, :] *= height_scale
        new_K[1][2] -= crop_cy
        R = cam2world[:3, :3]
        T = cam2world[:3, 3]

        # 使用与 reconic 一致的 image 全局索引：frame-major, camera 次序
        unique_img_idx = int(self.unique_img_idx_all[idx])

        sample = {"image": gt_image, "idx": unique_img_idx, "cam_idx": cam_idx, "image_name": image_name,
                  "R": R, "T": T, "K": new_K, "W": width, "H": height}

        if self.use_label:
            label_path = os.path.join(self.image_dir, self.label_filenames_all[idx])
            label = cv2.imread(label_path, cv2.IMREAD_UNCHANGED)
            resized_label = label  # cv2.resize(label, dsize=self.resized_image_size, interpolation=cv2.INTER_NEAREST)
            mask, label = label2mask(resized_label)
            label = self.remap_semantic(label).astype(int)
            mask = mask[crop_cy:, :]
            label = label[crop_cy:, :]
            sample["mask"] = mask
            sample["label"] = label

        if self.use_depth:
            sample["depth"] = self.depth_images[idx][crop_cy:, :]

        return sample

    def file_check(self):
        image_paths = [os.path.join(self.base_dir, image_path) for image_path in self.image_filenames_all]
        image_exists = np.asarray(self.check_filelist_exist(image_paths))
        print(f"Drop {len(image_paths) - len(np.where(image_exists)[0])} frames out of {len(image_paths)} by image exists check")
        exists = image_exists
        label_paths = [os.path.join(self.image_dir, label_path) for label_path in self.label_filenames_all]
        label_exists = np.asarray(self.check_filelist_exist(label_paths))
        print(f"Drop {len(label_paths) - len(np.where(label_exists)[0])} frames out of {len(label_paths)} by label exists check")
        exists *= label_exists

        available_index = list(np.where(exists)[0])
        print(f"Drop {len(image_paths) - len(available_index)} frames out of {len(image_paths)} by file exists check")
        self.filter_by_index(available_index)

    def label_valid_check(self):
        label_paths = [os.path.join(self.image_dir, label_path) for label_path in self.label_filenames_all]
        label_valid = np.asarray(self.check_label_valid(label_paths))
        available_index = list(np.where(label_valid)[0])
        print(f"Drop {len(label_paths) - len(available_index)} frames out of {len(label_paths)} by label valid check")
        self.filter_by_index(available_index)

    def label_valid(self, label_name):
        label = cv2.imread(label_name, cv2.IMREAD_UNCHANGED)
        label_movable = label >= 52
        ratio_movable = label_movable.sum() / label_movable.size
        label_off_road = ((0 <= label) & (label <= 1)) | ((3 <= label) & (label <= 6)) | ((10 <= label) & (label <= 12)) \
                         ((15 <= label) & (label <= 22)) | ((25 <= label) & (label <= 40)) | (label >= 42)
        ratio_static = label_off_road.sum() / label_off_road.size
        if ratio_movable > 0.3 or ratio_static > 0.9:
            return False
        else:
            return True

    def check_label_valid(self, filelist):
        with Pool(8) as p:
            exist_list = p.map(self.label_valid, filelist)
        return exist_list

    def filter_by_index(self, index):
        self.image_filenames_all = [self.image_filenames_all[i] for i in index]
        self.camera2world_all = [self.camera2world_all[i] for i in index]
        self.cameras_K_all = [self.cameras_K_all[i] for i in index]
        self.cameras_idx_all = [self.cameras_idx_all[i] for i in index]
        self.camera_times_all = [self.camera_times_all[i] for i in index]
        self.chassis2world_all = [self.chassis2world_all[i] for i in index]
        self.label_filenames_all = [self.label_filenames_all[i] for i in index]

        # 重新构建 unique_img_idx，保持与当前数据一致
        self._build_unique_img_idx()

    @property
    def label_remaps(self):
        return get_xpeng_label_remaps()

    @property
    def origin_color_map(self):
        return get_xpeng_origin_color_map()

    @property
    def num_class(self):
        return 7

    @property
    def filted_color_map(self):
        return get_xpeng_filted_color_map()

    def _build_unique_img_idx(self):
        """
        构造与 reconic.xpeng_sourceloader 中 unique_img_idx 一致的索引规则：
        对于每个时间戳 frame_idx，按 camera_names 中的相机顺序赋予：
            unique_img_idx = frame_idx * len(camera_names) + cam_idx
        其中 cam_idx 是 camera_names.index(camera_name)。
        """
        if len(self.camera_times_all) == 0:
            self.unique_img_idx_all = []
            self.max_unique_img_idx = -1
            return

        times = np.array(self.camera_times_all)
        cam_indices = np.array(self.cameras_idx_all)

        unique_times = sorted(set(times.tolist()))
        time_to_frame = {ts: i for i, ts in enumerate(unique_times)}
        num_cams = len(self.camera_names)

        unique_idx_list = []
        for t, c_idx in zip(times, cam_indices):
            frame_idx = time_to_frame[t]
            unique_idx = frame_idx * num_cams + int(c_idx)
            unique_idx_list.append(unique_idx)

        self.unique_img_idx_all = np.array(unique_idx_list, dtype=np.int64)
        self.max_unique_img_idx = int(self.unique_img_idx_all.max()) if len(self.unique_img_idx_all) > 0 else -1
