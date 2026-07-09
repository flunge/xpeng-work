import os
import cv2
import json
import glob
import numpy as np
import torch
from PIL import Image
from torch.utils.data import Dataset
import imageio.v2 as imageio
import open3d as o3d  # 或 open3d_pycg
from omegaconf import OmegaConf
from torch.distributed import get_rank, get_world_size
import random
from loguru import logger
from plyfile import PlyData

from scube.data.base import DatasetSpec as DS

def read_pfm(filepath):
    with open(filepath, 'rb') as f:
        header = f.readline().decode('utf-8').rstrip()
        if header == 'PF':
            color = True
        elif header == 'Pf':
            color = False
        else:
            raise ValueError('Not a PFM file.')

        dim_match = f.readline().decode('utf-8')
        width, height = map(int, dim_match.split())

        scale = float(f.readline().decode('utf-8').rstrip())
        endian = '<' if scale < 0 else '>'
        scale = abs(scale)
        data = np.fromfile(f, endian + 'f')

    if color:
        data = data.reshape((height, width, 3))
    else:
        data = data.reshape((height, width))

    data = np.flipud(data)
    return data

class XpengDataset(Dataset):
    def __init__(self, case_id, root_data_folder, split, spec, \
                 fvdb_grid_type='vs04', finest_voxel_size_goal='vs01', infer_case_id = None, \
                 hparams = None, duplicate_num = None, wds_scene_list_file = None, attr_subfolders = None,\
                 input_slect_ids = None, input_frame_offsets = None, sup_slect_ids = None, sup_frame_offsets = None,\
                 n_image_per_iter_sup = None, resolution = None, val_starting_frame = None, online_clips_file = None, online_data_folder = None):
        self.spec = spec
        self.mode = split

        self.cam_with_id = {"cam0": 0, "cam2": 1, "cam3": 2, "cam4": 3, "cam5": 4, "cam6": 5, "cam7": 6}
        self.depth_suffix = "pfm"
        self.cam_num_for_mvs = 6 # no cam0 for mvsa
        self.cam_name_list = ["cam2", "cam5", "cam6"]
        # cam2: 1920 * 928
        # cam5/6: 968 * 774

        if self.mode == "train":
            self.root_data_folder_list = ['/workspace/group_share/adc-sim/users/dsc/xpeng_train_data_0323/',\
                                          '/workspace/group_share/adc-sim/users/dsc/xpeng_train_data_0401/']
            case_id_list = []
            for root_folder in self.root_data_folder_list:
                case_id_list += os.listdir(root_folder)
            print("==========total train case id==========: ", len(case_id_list))
        else:
            print("Scube data space: ", root_data_folder)
            self.root_data_folder_list = [root_data_folder]
            case_id_list = [hparams.infer_case_id]

        self.total_frame = 0
        self.case_with_frame = {}
        for case_id in case_id_list:
            case_folder = None
            for root_folder in self.root_data_folder_list:
                case_folder = os.path.join(root_folder, case_id)
                if not os.path.exists(case_folder):
                    continue
                else:
                    break

            if not self.check_all_files_exist(case_folder):
                continue

            select_slice_with_time_file = os.path.join(case_folder, "misc/mvsnet/mvsnet_image_timestamps.json")
            with open(select_slice_with_time_file, 'r', encoding='utf-8') as file:
                select_slice_with_time = json.load(file)["cam0"]

            if case_id in self.case_with_frame:
                print("Error: Duplicate case id ", case_id)
                exit(-1)

            self.case_with_frame[case_id] = len(select_slice_with_time.keys())
            self.total_frame += len(select_slice_with_time.keys())

        self.grid_crop_bbox_min = [-80, -51.2, -12.8]
        if 'debug_distance' in hparams:
            print("========hparams debug_distance======== ", hparams.debug_distance)
            self.grid_crop_bbox_max = [int(hparams.debug_distance), 51.2, 38.4]
        else:
            self.grid_crop_bbox_max = [80, 51.2, 38.4]

        if 'debug_frame' in hparams:
            print("========hparams debug_frame======== ", hparams.debug_frame)
            self.img_num_per_batch = int(hparams.debug_frame) * len(self.cam_name_list)
        else:
            self.img_num_per_batch = 1

        self.inference_mode = True
        if self.inference_mode:
            self.img_num_per_batch = 10 * len(self.cam_name_list)

        self.voxel_size = 0.2
        self.sample_interval = 25
        self.length = self.total_frame * len(self.cam_name_list)

    def check_all_files_exist(self, case_folder):
        paths = {
            "depth_folder": os.path.join(case_folder, "misc/mvsnet/mvsnet_depth_est"),
            "image_folder": os.path.join(case_folder, "images_vision"),
            "seg_folder": os.path.join(case_folder, "segs_vision"),
            "ply_file": os.path.join(case_folder, "obstacle_points_new.ply"),
            "bkgd_path": os.path.join(case_folder, "input_ply/points3D_bkgd.ply"),
            "bkgd_mask_path": os.path.join(case_folder, "ground_mask.npy"),
            "select_slice_with_time_file": os.path.join(case_folder, "misc/mvsnet/mvsnet_image_timestamps.json"),
        }

        all_exist = True
        missing = []

        for name, path in paths.items():
            if not os.path.exists(path):
                all_exist = False
                missing.append(name)
        return all_exist

    def get_grid_world(self, cam2world):
        cam2world_FLU = torch.cat([cam2world[:,2:3], -cam2world[:,0:1], -cam2world[:,1:2], cam2world[:,3:4]], axis=1) # opencv -> FLU
        camera_pos = cam2world_FLU[:3, 3]
        camera_front = cam2world_FLU[:3, 0] # unit 
        camera_left = cam2world_FLU[:3, 1] # unit 
        camera_up = cam2world_FLU[:3, 2] # unit 

        new_grid_pos = camera_pos + \
                        camera_front * (self.grid_crop_bbox_min[0] + self.grid_crop_bbox_max[0]) / 2 + \
                        camera_left * (self.grid_crop_bbox_min[1] + self.grid_crop_bbox_max[1]) / 2 + \
                        camera_up * (self.grid_crop_bbox_min[2] + self.grid_crop_bbox_max[2]) / 2
        grid2world = torch.clone(cam2world_FLU)
        grid2world[:3, 3] = new_grid_pos
        return grid2world

    def get_crop_grid_points(self, grid2world):
        crop_half_range_canonical = (torch.tensor(self.grid_crop_bbox_max) - torch.tensor(self.grid_crop_bbox_min)) / 2
        plydata = PlyData.read(self.ply_file)     
        vertices = plydata['vertex']
        positions = torch.tensor(np.vstack([vertices['x'], vertices['y'], vertices['z']]).T, dtype=torch.float32)
        semantics = torch.tensor(vertices['semantic'].T, dtype=torch.int64)
        semantics.clamp_(max=22)

        if self.inference_mode:
            N = positions.shape[0]
            homogeneous_positions = torch.cat([positions, torch.ones((N, 1), device=positions.device)], dim=1)
            homogeneous_positions = homogeneous_positions.T
            world2grid = torch.inverse(grid2world).to(torch.float32)

            positions_grid_homogeneous = world2grid @ homogeneous_positions
            positions_grid = positions_grid_homogeneous[:3, :].T
            cropped_points = positions_grid
            cropped_semantics = semantics
        else:
            # add ground points
            ground_mask = np.load(self.bkgd_mask_path)
            plydata_grd = PlyData.read(self.bkgd_path)        
            vertices_grd = plydata_grd['vertex']
            positions_grd = torch.tensor(np.vstack([vertices_grd['x'], vertices_grd['y'], vertices_grd['z']]).T, dtype=torch.float32)
            positions_grd = positions_grd[ground_mask.astype(bool).flatten()]
            ground_semantics = torch.ones(positions_grd.shape[0], dtype=torch.int64, device=semantics.device)

            # concat bkgd and ground
            positions = torch.cat([positions, positions_grd], dim=0)
            semantics = torch.cat([semantics, ground_semantics], dim=0)

            N = positions.shape[0]
            homogeneous_positions = torch.cat([positions, torch.ones((N, 1), device=positions.device)], dim=1)
            homogeneous_positions = homogeneous_positions.T
            world2grid = torch.inverse(grid2world).to(torch.float32)

            positions_grid_homogeneous = world2grid @ homogeneous_positions
            positions_grid = positions_grid_homogeneous[:3, :].T

            # crop the point cloud
            crop_mask = (positions_grid[:,0] > -crop_half_range_canonical[0]) & \
                        (positions_grid[:,0] < crop_half_range_canonical[0]) & \
                        (positions_grid[:,1] > -crop_half_range_canonical[1]) & \
                        (positions_grid[:,1] < crop_half_range_canonical[1]) & \
                        (positions_grid[:,2] > -crop_half_range_canonical[2]) & \
                        (positions_grid[:,2] < crop_half_range_canonical[2])

            cropped_points = positions_grid[crop_mask]
            cropped_semantics = semantics[crop_mask]

        if self.voxel_size is not None and cropped_points.shape[0] > 0:
            points_np = cropped_points.cpu().numpy()
            semantics_np = cropped_semantics.cpu().numpy()
            pcd = o3d.geometry.PointCloud()
            pcd.points = o3d.utility.Vector3dVector(points_np)
            colors = np.zeros((len(points_np), 3), dtype=np.float32)
            pcd.colors = o3d.utility.Vector3dVector(colors)

            pcd_down = pcd.voxel_down_sample(voxel_size=self.voxel_size)
            down_points_np = np.asarray(pcd_down.points)

            from scipy.spatial import KDTree
            tree = KDTree(points_np)
            _, indices = tree.query(down_points_np, k=1)

            down_semantics_np = semantics_np[indices]

            cropped_points = torch.from_numpy(down_points_np).to(cropped_points.device, dtype=torch.float32)
            cropped_semantics = torch.from_numpy(down_semantics_np).to(cropped_semantics.device, dtype=torch.int64)
        return cropped_points, cropped_semantics

    def obtain_frame_counts(self):
        depth_files = glob.glob(os.path.join(self.depth_folder, "*." + self.depth_suffix))
        file_counts = len(depth_files)
        if file_counts % self.cam_num_for_mvs != 0:
            print("Error, mono depth counts false")

        each_cam_counts = len(self.select_slice_with_time)
        return each_cam_counts

    def __len__(self):
        return self.length

    def __getitem__(self, idx):
        img_tensor_list = []
        mask_list = []
        cam2grid_list = []
        intrinsic_list = []
        depth_list = []
        main_frame = True
        main_case = None
        data = {}

        curr_idx = idx
        while len(img_tensor_list) < self.img_num_per_batch:
            case_frame_index = curr_idx % self.total_frame
            curr_length = 0
            for case, length in self.case_with_frame.items():
                if curr_length + length > case_frame_index:
                    case_id = case
                    frame_idx = case_frame_index - curr_length
                    break
                else:
                    curr_length += length

            if main_frame:
                main_case = case_id
            if case_id != main_case:
                break

            for cam_name in self.cam_name_list:
                # ===== get file info =====
                for root_folder in self.root_data_folder_list:
                    case_folder = os.path.join(root_folder, case_id)
                    if not os.path.exists(case_folder):
                        continue
                    else:
                        break

                calib_file = os.path.join(case_folder, "calib.json")
                with open(calib_file, 'r', encoding='utf-8') as file:
                    self.calib_info = json.load(file)

                self.depth_folder = os.path.join(case_folder, "misc/mvsnet/mvsnet_depth_est")
                self.image_folder = os.path.join(case_folder, "images_vision")
                self.seg_folder = os.path.join(case_folder, "segs_vision")

                self.ply_file = os.path.join(case_folder, "obstacle_points_new.ply")
                self.bkgd_path = os.path.join(case_folder, 'input_ply/points3D_bkgd.ply')
                self.bkgd_mask_path = os.path.join(case_folder, 'ground_mask.npy')

                select_slice_with_time_file = os.path.join(case_folder, "misc/mvsnet/mvsnet_image_timestamps.json")
                with open(select_slice_with_time_file, 'r', encoding='utf-8') as file:
                    self.select_slice_with_time = json.load(file)["cam0"]
                timestamp = self.select_slice_with_time["slice" + str(frame_idx)]

                slice_with_time_file = os.path.join(case_folder, "timestamp2slice.json")
                with open(slice_with_time_file, 'r', encoding='utf-8') as file:
                    self.slice_with_time = json.load(file)

                pose_file = os.path.join(case_folder, "transform.json")
                with open(pose_file, 'r', encoding='utf-8') as file:
                    all_pose_data = json.load(file)

                self.pose_info = {}
                for frame in all_pose_data['frames']:
                    curr_timestamp = frame['timestamp']
                    camera = frame['camera']
                    if curr_timestamp not in self.pose_info:
                        self.pose_info[curr_timestamp] = {}
                    self.pose_info[curr_timestamp][camera] = frame['transform_matrix']

                cam2world = np.array(self.pose_info[timestamp][cam_name]) # cam2world
                cam2world = torch.from_numpy(cam2world).float()
                if main_frame:
                    if self.inference_mode:
                        grid2world = torch.eye(4)
                    else:
                        grid2world = self.get_grid_world(cam2world).float()
                    cropped_points, semantics = self.get_crop_grid_points(grid2world)

                    voxel_sizes_target = torch.tensor([self.voxel_size, self.voxel_size, self.voxel_size])
                    origins_target = voxel_sizes_target / 2
                    grid_batch_kwargs_target = {'voxel_sizes': voxel_sizes_target, 'origins': origins_target}

                    origins_finest = voxel_sizes_target / 2 
                    grid_batch_kwargs_finest = {'voxel_sizes': voxel_sizes_target, 'origins': origins_finest}

                    grid_info = {'points_finest': cropped_points, 'semantics_finest': semantics, 
                                'grid_batch_kwargs_target': grid_batch_kwargs_target,
                                'grid_batch_kwargs_finest': grid_batch_kwargs_finest,
                                "extra_meshes": None}

                    data[DS.SHAPE_NAME] = "No Used SHAPE_NAME"
                    data[DS.GRID_TO_WORLD] = grid2world
                    data[DS.GRID_CROP_RANGE] = torch.tensor([self.grid_crop_bbox_min, self.grid_crop_bbox_max])
                    data[DS.INPUT_PC] = "Generate on the fly from DS.INPUT_PC_RAW"
                    data[DS.INPUT_PC_RAW] = grid_info
                    data[DS.GT_SEMANTIC] = "Generate on the fly from DS.INPUT_PC_RAW from semantics finest"

                cam2grid = torch.inverse(grid2world) @ cam2world

                all_frame_idx = self.slice_with_time[str(timestamp)]
                img_name = f"slice{str(all_frame_idx)}_{cam_name}.png"
                image_path = os.path.join(self.image_folder, img_name)
                seg_path = os.path.join(self.seg_folder, img_name)

                pil_image = Image.open(image_path)
                img_np = np.array(pil_image, dtype="uint8")
                img_tensor = torch.from_numpy(img_np.astype("float32") / 255.0)
                height, width = img_np.shape[:2]

                # ===== get intrinsic =====
                fx = self.calib_info[cam_name]["intrinsic"]["focal_length"]
                fy = self.calib_info[cam_name]["intrinsic"]["focal_length"]
                cx = self.calib_info[cam_name]["intrinsic"]["cx"]
                cy = self.calib_info[cam_name]["intrinsic"]["cy"]
                intrinsic_array = np.array([fx, fy, cx, cy, width, height]).astype(np.float32)
                intrinsic = torch.from_numpy(intrinsic_array)

                # ===== get mask =====
                # (1) foreground mask from segmentation:    0 for background, 1 for foreground,
                # (2) non dynamic mask:                     0 is dynamic object, 1 is static object
                # (3) non padding mask:                     0 for padding, 1 for non-padding
                # (4) foreground mask from grid:            0 for background, 1 for foreground. generate on the fly.
                mask = torch.ones(height, width, 4, dtype=torch.bool)
                seg_img_all = cv2.imread(seg_path)
                seg_img = seg_img_all[:, :, 0]
                sky_mask = (seg_img != 27)
                mask[:, :, 0] = torch.from_numpy(sky_mask)

                CLASS_RGB_MAP = {
                    # 'ground': (13, 13, 13),
                    # 'lane': (24, 24, 24),
                    'car': (55, 55, 55),
                    'ped': (21, 21, 21),
                    'motor': (57, 57, 57)
                }
                mask_conditions = False
                for rgb in CLASS_RGB_MAP.values():
                    condition = (seg_img_all[:, :, 0] == rgb[2]) & \
                                (seg_img_all[:, :, 1] == rgb[1]) & \
                                (seg_img_all[:, :, 2] == rgb[0])
                    mask_conditions |= condition
                high_value_condition = (seg_img_all[:, :, 2] >= 52) & \
                                    (seg_img_all[:, :, 1] >= 52) & \
                                    (seg_img_all[:, :, 0] >= 52)
                mask_conditions |= high_value_condition 
                dynamic_mask = ~mask_conditions
                mask[:, :, 1] = torch.from_numpy(dynamic_mask)

                if cam_name in ["cam3", "cam4", "cam5", "cam6"]:
                    orig_h, orig_w = height, width          # 应该是 774, 968
                    target_w, target_h = 1920, 928

                    pad_right  = target_w - orig_w          # 1920 - 968 = 952
                    pad_bottom = target_h - orig_h          # 928  - 774 = 154

                    # ------------------ RGB image ------------------
                    # torch.nn.functional.pad 需要 (left, right, top, bottom) 顺序
                    img_tensor = torch.nn.functional.pad(
                        img_tensor.permute(2, 0, 1),          # C,H,W
                        (0, pad_right, 0, pad_bottom),        # left=0, right=952, top=0, bottom=154
                        mode='constant',
                        value=0
                    ).permute(1, 2, 0)                        # 变回 H,W,C

                    # save_path = str(idx) + "_img.png"
                    # img_uint8 = (img_tensor * 255).byte().cpu().numpy()
                    # Image.fromarray(img_uint8).save(save_path)

                    # ------------------ mask (H,W,4) ------------------
                    mask = torch.nn.functional.pad(
                        mask.permute(2, 0, 1),                # 4,H,W
                        (0, pad_right, 0, pad_bottom),
                        mode='constant',
                        value=0                               # False / 0
                    ).permute(1, 2, 0)                        # 变回 H,W,4

                    # ------------------ 更新内参 ------------------
                    # 原 intrinsic_array = [fx, fy, cx, cy, width, height]
                    intrinsic_array = intrinsic.numpy()   # 转 numpy 方便改
                    intrinsic_array[4] = target_w         # width  → 1920
                    intrinsic_array[5] = target_h         # height → 928
                    intrinsic = torch.from_numpy(intrinsic_array).float()

                img_tensor_list.append(img_tensor)
                mask_list.append(mask)
                cam2grid_list.append(cam2grid)
                intrinsic_list.append(intrinsic)

                main_frame = False

            curr_idx += self.sample_interval
            if curr_idx >= self.length:
                break

        img_tensor_list = self.extent_list(img_tensor_list)
        mask_list = self.extent_list(mask_list)
        cam2grid_list = self.extent_list(cam2grid_list)
        intrinsic_list = self.extent_list(intrinsic_list)

        # input info
        data[DS.IMAGES_INPUT] = torch.stack(img_tensor_list)
        data[DS.IMAGES_INPUT_MASK] = torch.stack(mask_list)
        data[DS.IMAGES_INPUT_POSE] = torch.stack(cam2grid_list)
        data[DS.IMAGES_INPUT_INTRINSIC] = torch.stack(intrinsic_list)

        # supervision info
        data[DS.IMAGES] = torch.stack(img_tensor_list)
        data[DS.IMAGES_MASK] = torch.stack(mask_list)
        data[DS.IMAGES_POSE] = torch.stack(cam2grid_list)
        data[DS.IMAGES_INTRINSIC] = torch.stack(intrinsic_list)

        return data

    def extent_list(self, lst):
        if len(lst) >= self.img_num_per_batch:
            return lst[:self.img_num_per_batch]
        else:
            last = lst[-1] if lst else None
            return lst + [last] * (self.img_num_per_batch - len(lst))
        return lst