import os
import gc
import cv2
import json
import math
import time
import torch
import numpy as np
from PIL import Image
import concurrent.futures
from plyfile import PlyData
import torchvision.io as tvio
from torch.utils.data import Dataset
import torchvision.transforms as transforms
from torchsparse.utils.quantize import sparse_quantize

from g3r.utils.math_utils import quaternion_from_vectors, compute_normals_and_quaternions,\
                                 nearest_distances_kdtree
from g3r.utils.general_utils import load_yaml, SemanticType, get_semantics_from_path, \
                                    get_mask_from_semantics, depth_to_rgb, NetMode


class XpengDataset(Dataset):
    def __init__(self, config, data_path, net_mode, folder_name = None):
        super().__init__()
        self.cfg = config
        self.check_new_view = False
        self.use_mask_check = True
        self.use_distance_check = True
        self.data_path = data_path
        self.folder_name = folder_name
        self.net_mode = net_mode
        self.cam_name = None

        self.scenes_data = {}
        self.data_length = 0
        self.points_info, self.coords, self.unquantized_points_info = self.get_xpeng_points()

    def get_points_info(self):
        return self.points_info, self.coords, self.unquantized_points_info

    def get_xpeng_points(self):
        init_opacity = 0.7
        if self.cfg["region"] == "ground":
            positions, rotations, colors = self.obtain_ground_points()
            init_scale_z = 0.01
        elif self.cfg["region"] == "bkgd":
            positions, rotations, colors = self.obtain_bkgd_points()
            init_scale_z = 0.1

        # obtain quantized points info
        sparse_positions, sparse_rotations, sparse_colors, sparse_coords, sparse_scales, unquantized_ids, all_scales =\
            self.process_points(positions, rotations, colors)
        points_num = sparse_positions.shape[0]

        scales_xy = torch.cat((sparse_scales, sparse_scales), 1)
        scales_z = torch.full((points_num, 1), init_scale_z)
        opacity = torch.full((points_num, 1), init_opacity)
        sparse_points_info = torch.cat((sparse_positions, sparse_rotations, sparse_colors, scales_xy, scales_z, opacity), 1)

        sparse_coords = torch.tensor(sparse_coords, dtype=torch.int)
        batch_indices = torch.zeros(sparse_coords.shape[0], 1)
        sparse_coords = torch.cat((sparse_coords, batch_indices), dim=1).to(torch.int32)

        # obtain unquantized points info
        unquantized_points_num = unquantized_ids.size
        unquantized_positions = positions[unquantized_ids]
        unquantized_rotations = rotations[unquantized_ids]
        unquantized_colors = colors[unquantized_ids]

        temp_scales = all_scales[unquantized_ids]
        temp_scales = temp_scales.unsqueeze(1)
        unquantized_scales_xy = torch.cat((temp_scales, temp_scales), 1)
        unquantized_scales_z = torch.full((unquantized_points_num, 1), init_scale_z)

        unquantized_opacity = torch.full((unquantized_points_num, 1), init_opacity)
        unquantized_points_info =\
            torch.cat((unquantized_positions, unquantized_rotations, unquantized_colors, unquantized_scales_xy, unquantized_scales_z, unquantized_opacity), 1)

        print("sparse points num ", points_num)
        print("unquantized points num ", unquantized_points_num)
        return sparse_points_info, sparse_coords, unquantized_points_info

    def clean_images_info(self):
        self.scenes_data.clear()
        self.data_length = 0

    def get_meta(self, cam_name):
        transform_path = os.path.join(self.data_path, 'transform.json')
        with open(transform_path, "r") as f:
            meta = json.load(f)
        meta = meta["frames"]
        meta = [frame for frame in meta if frame["camera"] == cam_name]

        timestamps = [frame["timestamp"] for frame in meta]
        timestamps.sort()
        total_timestamps = len(timestamps)
        if total_timestamps > self.cfg["sample_camera_num"]:
            indices = np.linspace(0, total_timestamps - 1, self.cfg["sample_camera_num"], dtype=int)
            selected_timestamps = [timestamps[i] for i in indices]

            filtered_meta = [frame for frame in meta if frame["timestamp"] in selected_timestamps]
            return filtered_meta
        else:
            sorted_meta = sorted(meta, key=lambda x: x["timestamp"])
            return sorted_meta

    def write_delta_distance(self, meta_info):
        for frame_id in range(len(meta_info) - 1):
            curr_meta = meta_info[frame_id]
            next_meta = meta_info[frame_id + 1]

            curr_cam_to_w = np.array(curr_meta["transform_matrix"])
            w_to_next_cam = np.linalg.inv(np.array(next_meta["transform_matrix"]))
            curr_cam_to_next_cam = w_to_next_cam @ curr_cam_to_w
            meta_info[frame_id]["shift_distance"] = math.fabs(curr_cam_to_next_cam[2, 3])
        meta_info[-1]["shift_distance"] = 15
        return meta_info

    def modify_inference_view(self):
        if self.cam_name == "cam0" or self.cam_name == "cam2":
            self.cfg['num_batch_views'] = self.cfg['num_batch_views_cam02']
        else:
            self.cfg['num_batch_views'] = self.cfg['num_batch_views_cam34']

    def get_xpeng_scene(self, cam_name):
        self.cam_name = cam_name
        if self.net_mode == NetMode.INFERENCE:
            self.modify_inference_view()
        self.clean_images_info()
        meta_info = self.get_meta(cam_name)
        meta_info = self.write_delta_distance(meta_info)

        images = []
        cameras = []
        valid_points_id = []
        num_threads = min(len(meta_info), os.cpu_count(), 32)
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = []
            for frame in meta_info:
                futures.append(executor.submit(self.process_frame, frame, cam_name))

            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result is not None:
                    cameras.append(result["camera_data"])
                    images.append(result["image"])
                    valid_points_id.append(result["valid_columns"])

        self.data_length = (len(images) // self.cfg['num_batch_views'])
        print("Scene Data Length: ", self.data_length)
        if self.data_length == 0:
            return

        gc.collect()
        indexed = list(zip(range(len(cameras)), cameras, images, valid_points_id))
        indexed.sort(key=lambda x: x[1]['timestamp'])
        sorted_indices, cameras_sorted, images_sorted, valid_points_id_sorted = zip(*indexed)
        cameras, images, valid_points_id = list(cameras_sorted), list(images_sorted), list(valid_points_id_sorted)
        self.scenes_data = {"images": images, "cameras": cameras, "valid_ids": valid_points_id}
        return

    def obtain_ground_points(self):
        points_path = os.path.join(self.data_path, 'surfel_ground/ground_surfel.ply')
        plydata = PlyData.read(points_path)        
        vertices = plydata['vertex']
        positions = torch.tensor(np.vstack([vertices['x'], vertices['y'], vertices['z']]).T, dtype=self.cfg["data_type"])
        rotations = torch.tensor(np.vstack([vertices['qw'], vertices['qx'], vertices['qy'], vertices['qz']]).T, dtype=self.cfg["data_type"])
        colors = torch.tensor(np.vstack([vertices['red'], vertices['green'], vertices['blue']]).T / 255.0, dtype=self.cfg["data_type"])
        return positions, rotations, colors

    def obtain_bkgd_points(self):
        points_path = os.path.join(self.data_path, 'input_ply/points3D_bkgd.ply')
        ground_mask = np.load(os.path.join(self.data_path, 'ground_mask.npy'))

        plydata = PlyData.read(points_path)        
        vertices = plydata['vertex']
        positions = torch.tensor(np.vstack([vertices['x'], vertices['y'], vertices['z']]).T, dtype=self.cfg["data_type"])
        colors = torch.tensor(np.vstack([vertices['red'], vertices['green'], vertices['blue']]).T / 255.0, dtype=self.cfg["data_type"])
        rotations = torch.zeros((positions.shape[0], 4), dtype=self.cfg["data_type"])
        rotations[:, 0] = 1  # gs to world, w x y z

        positions = positions[~ground_mask.astype(bool).flatten()]
        rotations = rotations[~ground_mask.astype(bool).flatten()]
        colors = colors[~ground_mask.astype(bool).flatten()]
        return positions, rotations, colors

    def process_points(self, points, rotations, colors):
        points_num = points.shape[0]
        points_np = points.to(dtype=self.cfg["data_type"]).numpy()
        xyz_min_values = np.min(points_np, axis=0)
        clip_points = points_np - xyz_min_values
        dist_scales = nearest_distances_kdtree(clip_points[:, :2]).to(dtype=self.cfg["data_type"])

        coords, indices = sparse_quantize(clip_points, self.cfg['voxel_size'], return_index=True)
        all_ids = set(range(points_num))
        unquantized_ids = np.array(list(all_ids - set(indices)))

        # if coords.shape[0] > self.cfg['num_points_train']:
        #     random_indices = torch.randperm(coords.shape[0])[ : self.cfg['num_points_train']]
        #     coords = coords[random_indices]
        #     indices = indices[random_indices]

        points = points[indices]
        rotations = rotations[indices]
        colors = colors[indices]
        scales = dist_scales[indices]
        scales = scales.unsqueeze(1)
        return points, rotations, colors, coords, scales, unquantized_ids, dist_scales

    def diturb_pose(self, camera_to_world):
        disturb_cam_x = 1.0
        camera_to_world_rot = camera_to_world[:3, :3]
        diff_camera_xyz = np.array([[disturb_cam_x], [0.0], [0.0]])
        curr_trans = camera_to_world_rot @ diff_camera_xyz
        curr_trans = curr_trans.squeeze(1)
        camera_to_world[:3, 3] += curr_trans
        world_to_cam = np.linalg.inv(camera_to_world)

        pitch_theta = 30.0 / 180.0
        cos_pitch_theta = math.cos(pitch_theta)
        sin_pitch_theta = math.sin(pitch_theta)
        diff_rot = np.array(
            [
                [cos_pitch_theta, 0, -sin_pitch_theta, 0],
                [0, 1, 0, 0],
                [sin_pitch_theta, 0, cos_pitch_theta, 0],
                [0, 0, 0, 1],
            ]
        )
        world_to_cam = diff_rot.dot(world_to_cam)
        return world_to_cam

    def process_frame(self, frame, cam_name):
        timestamp = frame["timestamp"]
        seg_folder = os.path.join(self.data_path, "segs", cam_name)
        seg_img = get_semantics_from_path(os.path.join(seg_folder, f"{timestamp}.png"))
        grd_mask = get_mask_from_semantics(seg_img, SemanticType.GROUND)
        if torch.all(grd_mask == 0):
            return None

        image_path = os.path.join(self.data_path, "images", cam_name, f"{timestamp}.png")
        torch_image = tvio.read_image(image_path) / 255.0
        grd_mask_3c = grd_mask.squeeze(-1).unsqueeze(0).expand(3, -1, -1)

        camera_mask = tvio.read_image(os.path.join(self.data_path, "masks", cam_name, f"{timestamp}.png"))
        camera_mask = camera_mask == 0
        camera_mask_3c = camera_mask.expand(3, -1, -1)
        torch_image[camera_mask_3c] = 0

        if self.cfg["region"] == "ground":
            torch_image[~grd_mask_3c] = 0
            if self.net_mode == NetMode.TRAIN:
                non_zero_mask = (torch_image != 0).any(dim=0)  # shape: (H, W)
                non_zero_count = non_zero_mask.sum().item()
                if float(non_zero_count) / float(torch_image.shape[1] * torch_image.shape[2]) < 0.1:
                    return None

        elif self.cfg["region"] == "bkgd":
            torch_image[grd_mask_3c] = 0

            sky_mask = get_mask_from_semantics(seg_img, SemanticType.SKY)
            sky_mask_3c = sky_mask.squeeze(-1).unsqueeze(0).expand(3, -1, -1)
            torch_image[sky_mask_3c] = 0

            obj_mask_path = os.path.join(self.data_path, "masks_obj", cam_name, f"{timestamp}.png")
            obj_mask = tvio.read_image(obj_mask_path).bool()
            obj_mask_3c = obj_mask.expand(3, -1, -1)
            torch_image[~obj_mask_3c] = 0

        camera_to_world = np.array(frame["transform_matrix"])
        if self.check_new_view:
            world_to_cam_np = self.diturb_pose(camera_to_world)
        else:
            world_to_cam_np = np.linalg.inv(camera_to_world)

        world_to_cam = torch.from_numpy(world_to_cam_np).to(dtype=self.cfg["data_type"])
        intrinsic = torch.tensor([
            [frame['fl_x'], 0, frame['cx']],
            [0, frame['fl_y'], frame['cy']],
            [0, 0, 1]
        ], dtype=self.cfg["data_type"])

        rot = world_to_cam_np[:3, :3]
        trans = world_to_cam_np[:3, 3]

        positions = self.points_info[:, :3]
        cam_points = rot @ positions.numpy().T + trans[:, None]
        uv_points = intrinsic.numpy() @ cam_points
        projections = uv_points[:-1, :] / uv_points[-1, :]
        del uv_points

        left_bound = 0
        right_bound = torch_image.shape[2]
        max_distance = 1e5
        if self.net_mode == NetMode.INFERENCE:
            if cam_name != "cam0" and cam_name != "cam2":
                if self.use_distance_check and self.cfg["region"] == "ground":
                    max_distance = 30.0
                if cam_name == "cam3" or cam_name == "cam6":
                    right_bound = torch_image.shape[2] * 0.66
                elif cam_name == "cam4" or cam_name == "cam5":
                    left_bound = torch_image.shape[2] * 0.33
            elif cam_name == "cam0":
                if self.use_distance_check and self.cfg["region"] == "ground":
                    max_distance = frame["shift_distance"] + 60.0
            elif cam_name == "cam2":
                if self.use_distance_check and self.cfg["region"] == "ground":
                    max_distance = frame["shift_distance"] + 30.0
                left_bound = torch_image.shape[2] * 0.33
                right_bound = torch_image.shape[2] * 0.66

        # check projection in img
        valid_mask = (
            (cam_points[-1] > 0) & (cam_points[-1] < max_distance) &
            (projections[0] > left_bound) & (projections[0] < right_bound) &
            (projections[1] > 0) & (projections[1] < torch_image.shape[1])
        )
        valid_columns = np.where(valid_mask)[0]
        if valid_columns.size < 100:
            return None

        # check projection in mask
        if self.use_mask_check:
            x_coords = projections[0, :]
            y_coords = projections[1, :]
            x_coords_int = np.floor(x_coords[valid_columns]).astype(int)
            y_coords_int = np.floor(y_coords[valid_columns]).astype(int)
            grd_mask_squeeze = grd_mask.squeeze()
            if self.cfg["region"] == "ground":
                in_mask = grd_mask_squeeze[y_coords_int, x_coords_int] == 1
            elif self.cfg["region"] == "bkgd":
                in_mask = grd_mask_squeeze[y_coords_int, x_coords_int] == 0
            valid_columns = valid_columns[in_mask]
            if valid_columns.size == 0:
                return None

        if self.folder_name is not None:
            proj_img = (torch_image.permute(1, 2, 0).numpy() * 255).astype(np.uint8)
            for idx in valid_columns:
                center = (int(projections[0, idx]), int(projections[1, idx]))
                b, g, r = depth_to_rgb(cam_points[2][idx])
                cv2.circle(proj_img, center, 3, (b, g, r), -1)
            cv2.imwrite(
                os.path.join(self.folder_name, f"{cam_name}_{timestamp}_debug_projection.png"),
                proj_img
            )

        if self.net_mode == NetMode.TRAIN:
            if cam_name == "cam0" or cam_name == "cam2":
                resize_ratio = 0.5
                resize_height = int(torch_image.shape[1] * resize_ratio)
                resize_width = int(torch_image.shape[2] * resize_ratio)
                target_size = (resize_height, resize_width)  # height * width
                resize_trans = transforms.Resize(size=target_size)
                torch_image = resize_trans(torch_image)
                intrinsic *= resize_ratio
                intrinsic[2, 2] = 1

        return {
            "camera_data": {
                "cam_name": cam_name,
                "view_matrix": world_to_cam,
                "K": intrinsic,
                "timestamp": timestamp
            },
            "image": torch_image,
            "valid_columns": valid_columns
        }

    def __len__(self):
        return self.data_length

    def __getitem__(self, idx):
        start_id = min(idx * self.cfg['num_batch_views'], len(self.scenes_data["cameras"]) - self.cfg['num_batch_views'])
        end_id = start_id + self.cfg['num_batch_views']

        return {"images": self.scenes_data["images"][start_id : end_id],
                "cameras": self.scenes_data["cameras"][start_id : end_id],
                "valid_ids": self.scenes_data["valid_ids"][start_id : end_id]}

def sparse_scenes_collate(batch):
    scene = batch[0]
    num_cameras = len(scene["cameras"])
    view_matrix_stack = torch.empty((num_cameras, *scene["cameras"][0]['view_matrix'].shape))
    intrinsic_stack = torch.empty((num_cameras, *scene["cameras"][0]['K'].shape))
    gt_img_stack = torch.empty((num_cameras, *scene["images"][0].shape))
    timestamps = []

    for i, (cam, gt_image) in enumerate(zip(scene["cameras"], scene["images"])):
        view_matrix_stack[i] = cam['view_matrix']
        intrinsic_stack[i] = cam['K']
        gt_img_stack[i] = gt_image
        timestamps.append(cam['timestamp'])

    cameras_info = {"timestamps": timestamps, "extrinsics": view_matrix_stack, \
                    "intrinsics": intrinsic_stack, "images": gt_img_stack}
    return {"cameras_info": cameras_info, "valid_ids": scene["valid_ids"]}
