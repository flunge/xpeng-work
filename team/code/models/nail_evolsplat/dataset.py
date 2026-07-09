import os
import cv2
import sys
import glob
import json
import torch
import numpy as np
import open3d as o3d
from PIL import Image
from pathlib import Path
from plyfile import PlyData
from scipy.spatial import KDTree
from typing import Literal, Optional, Tuple, Type, List

current_dir = os.path.dirname(__file__)
root_path = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(root_path)
from nail_evolsplat.utils.cameras import Cameras
from nail_evolsplat.utils.data import read_depth_file
from nail_evolsplat.utils.colmap import read_points3D_binary
from concurrent.futures import ThreadPoolExecutor, as_completed

class Dataset():
    def __init__(self, case_id, root_data_folder, output_folder):
        self.output_folder = output_folder

        self.show_projection = False
        self.use_mono_dense = True
        self.mono_dense_cam = "cam2"
        self.use_colmap = False
        self.depth_suffix = "pfm"

        self.start_frame = 0
        self.cam_name_list = ["cam2", "cam5", "cam6"]
        self.cam_num_for_mvs = 6 # no cam0 for mvsa
        self.cam_with_id = {"cam0": 0, "cam2": 1, "cam3": 2, "cam4": 3, "cam5": 4, "cam6": 5, "cam7": 6}

        self.colmap_min_dist = 40
        self.colmap_max_dist = 200
        self.height_dist = 6.0
        self.near_dist = 10
        self.min_voxel = 0.03
        self.far_dist = 15
        self.max_voxel = 0.2
        self.min_mono_depth = 7.0
        self.max_mono_depth = 40.0
        self.max_dist_from_mvs = 0.2

        self.case_id = case_id
        case_folder = os.path.join(root_data_folder, self.case_id)
        calib_file = os.path.join(case_folder, "calib.json")
        with open(calib_file, 'r', encoding='utf-8') as file:
            self.calib_info = json.load(file)

        self.read_original_mvs = False
        self.ply_file = os.path.join(case_folder, "obstacle_points_new.ply")
        self.bkgd_path = os.path.join(case_folder, 'input_ply/points3D_bkgd.ply')
        self.bkgd_mask_path = os.path.join(case_folder, 'ground_mask.npy')

        self.colmap_file = os.path.join(case_folder, "colmap/triangulated/sparse/model/points3D.bin")
        self.depth_folder = os.path.join(case_folder, "misc/mvsnet/mvsnet_depth_est")
        self.image_folder = os.path.join(case_folder, "images_vision")
        self.seg_folder = os.path.join(case_folder, "segs_vision")
        self.segs_vision_static = os.path.join(case_folder, "segs_vision_static")

        select_slice_with_time_file = os.path.join(case_folder, "misc/mvsnet/mvsnet_image_timestamps.json")
        with open(select_slice_with_time_file, 'r', encoding='utf-8') as file:
            self.select_slice_with_time = json.load(file)["cam0"]

        slice_with_time_file = os.path.join(case_folder, "timestamp2slice.json")
        with open(slice_with_time_file, 'r', encoding='utf-8') as file:
            self.slice_with_time = json.load(file)

        pose_file = os.path.join(case_folder, "transform.json")
        with open(pose_file, 'r', encoding='utf-8') as file:
            all_pose_data = json.load(file)

        self.pose_info = {}
        for frame in all_pose_data['frames']:
            timestamp = frame['timestamp']
            camera = frame['camera']
            if timestamp not in self.pose_info:
                self.pose_info[timestamp] = {}
            self.pose_info[timestamp][camera] = frame['transform_matrix']

    def obtain_frame_counts(self):
        depth_files = glob.glob(os.path.join(self.depth_folder, "*." + self.depth_suffix))
        file_counts = len(depth_files)
        if file_counts % self.cam_num_for_mvs != 0:
            print("Error, mono depth counts false")

        each_cam_counts = len(self.select_slice_with_time)
        print("Each cam counts: ", each_cam_counts)
        return each_cam_counts

    def modify_interval(self, end_frame):
        if end_frame < 5:
            raise ValueError("Too little frames")
        elif end_frame < 30:
            self.sample_interval = 1
        else:
            self.sample_interval = 5
        self.use_dense_interval = 2 * self.sample_interval
        return

    def generate_dataparser_outputs(self):
        each_cam_counts = self.obtain_frame_counts()
        end_frame = each_cam_counts - 1
        self.modify_interval(end_frame)


        if self.read_original_mvs:
            obstacle_points_pcd = o3d.io.read_point_cloud(self.ply_file)
            obstacle_points_pcd = obstacle_pointsget_points_from_depth_pcd.voxel_down_sample(voxel_size=0.2)
        else:
            ground_mask = np.load(self.bkgd_mask_path)
            plydata = PlyData.read(self.bkgd_path)        
            vertices = plydata['vertex']
            positions = torch.tensor(np.vstack([vertices['x'], vertices['y'], vertices['z']]).T, dtype=torch.float32)
            colors = torch.tensor(np.vstack([vertices['red'], vertices['green'], vertices['blue']]).T / 255.0, dtype=torch.float32)
            positions = positions[~ground_mask.astype(bool).flatten()]
            colors = colors[~ground_mask.astype(bool).flatten()]
            obstacle_points_pcd = o3d.geometry.PointCloud()
            points_np = positions.contiguous().cpu().numpy().astype(np.float32, copy=False)
            colors_np = colors.contiguous().cpu().numpy().astype(np.float32, copy=False)
            obstacle_points_pcd.points = o3d.utility.Vector3dVector(points_np)
            obstacle_points_pcd.colors = o3d.utility.Vector3dVector(colors_np)
            pcd_save_path = os.path.join(self.output_folder, "original_mvs.ply")
            o3d.io.write_point_cloud(pcd_save_path, obstacle_points_pcd)
            obstacle_points_pcd_tensor = torch.from_numpy(np.asarray(obstacle_points_pcd.points)).float().to("cuda")

        def process_single_camera(cam_name):
            filter_mask = torch.zeros(obstacle_points_pcd_tensor.shape[0], dtype=torch.bool, device="cuda")  # (N,) 布尔张量
            curr_fx = self.calib_info[cam_name]["intrinsic"]["focal_length"]
            curr_fy = self.calib_info[cam_name]["intrinsic"]["focal_length"]
            curr_cx = self.calib_info[cam_name]["intrinsic"]["cx"]
            curr_cy = self.calib_info[cam_name]["intrinsic"]["cy"]
            cam_type = int(cam_name[-1])  # 相机类型，单相机固定

            cam_fx = []
            cam_fy = []
            cam_cx = []
            cam_cy = []
            cam_width = []
            cam_height = []
            cam_camera_type = []
            cam_mono_enhanced_points = []
            cam_poses_convert = []
            cam_poses_c2w = []
            cam_image_filenames = []
            cam_depth_filenames = []
            seg_mask_bkgds = []
            for frame_idx in range(self.start_frame, end_frame, self.sample_interval):
                timestamp = self.select_slice_with_time["slice" + str(frame_idx)]
                pose = self.pose_info[timestamp][cam_name]

                all_frame_idx = self.slice_with_time[str(timestamp)]
                img_name = f"slice{str(all_frame_idx)}_{cam_name}.png"
                image_path = os.path.join(self.image_folder, img_name)
                seg_path = os.path.join(self.seg_folder, img_name)
                segs_vision_static_name = f"slice{str(all_frame_idx)}_{cam_name}.npy"
                segs_vision_static_path = os.path.join(self.segs_vision_static, segs_vision_static_name)

                depth_idx = self.cam_with_id[cam_name] * each_cam_counts + frame_idx
                depth_file = os.path.join(self.depth_folder, f"{depth_idx:08d}.{self.depth_suffix}")
                if not os.path.exists(depth_file):
                    print(f"Error, no depth file: {depth_file}")
                    continue

                c2w = np.array(pose)
                c2w_convert = np.copy(c2w)
                c2w_convert[:3, :3] = c2w_convert[:3, :3] * np.array([[1, -1, -1]], dtype=c2w_convert.dtype)

                image = cv2.imread(image_path)
                curr_height, curr_width = image.shape[:2]

                cam_depth_filenames.append(depth_file)
                cam_image_filenames.append(image_path)
                cam_poses_convert.append(c2w_convert)
                cam_poses_c2w.append(c2w)
                cam_fx.append(curr_fx)
                cam_fy.append(curr_fy)
                cam_cx.append(curr_cx)
                cam_cy.append(curr_cy)
                cam_height.append(curr_height)
                cam_width.append(curr_width)
                cam_camera_type.append(cam_type)
                mono_points,seg_mask, seg_mask_bkgd  = self.get_points_from_depth(
                    depth_file, image_path, seg_path,
                    curr_fx, curr_fy, curr_cx, curr_cy, c2w, segs_vision_static_path
                )
                seg_mask_bkgds.append(seg_mask_bkgd)
                if self.use_mono_dense and (cam_name == self.mono_dense_cam) and (frame_idx % self.use_dense_interval == 0):
                    def filter_points_by_seg_mask_cuda(
                        obstacle_points_pcd_tensor,  
                        seg_mask_ground,            
                        c2w,                  
                        curr_fx, curr_fy,     
                        curr_cx, curr_cy,     
                        device="cuda:0"    
                    ):
                        seg_mask = seg_mask_ground
                        points_w = obstacle_points_pcd_tensor.to(device)
                        num_points = points_w.shape[0]
                        point_mask = torch.zeros(num_points, dtype=torch.bool, device=device)  # (N,) 布尔张量
                        
                        if isinstance(c2w, np.ndarray):
                            c2w = torch.from_numpy(c2w).float().to(device)
                        elif isinstance(c2w, torch.Tensor):
                            c2w = c2w.float().to(device)
                        if c2w.shape == (3, 4):
                            c2w = torch.cat([c2w, torch.tensor([[0,0,0,1]], dtype=torch.float32, device=device)], dim=0)
                        
                        seg_mask = torch.from_numpy(seg_mask).to(device)
                        H, W = seg_mask.shape
                        
                        fx = torch.tensor(curr_fx, dtype=torch.float32, device=device)
                        fy = torch.tensor(curr_fy, dtype=torch.float32, device=device)
                        cx = torch.tensor(curr_cx, dtype=torch.float32, device=device)
                        cy = torch.tensor(curr_cy, dtype=torch.float32, device=device)


                        points_w_chunk = points_w
                        chunk_global_indices = torch.arange(0, num_points, device=device)  # (chunk,)
                        w2c = torch.inverse(c2w)  # (4,4) CUDA张量
                        points_w_homo = torch.cat([points_w_chunk, torch.ones((points_w_chunk.shape[0],1), device=device)], dim=1)
                        points_c = torch.matmul(w2c, points_w_homo.T).T[:, :3]
                        
                        front_mask = points_c[:, 2] > 1e-6 
                        front_global_indices = chunk_global_indices[front_mask]
                        points_c_valid = points_c[front_mask]
                        
                        if points_c_valid.shape[0] == 0:
                            return  

                        z = points_c_valid[:, 2:3]  # (N,1)
                        u = fx * (points_c_valid[:, 0:1] / z) + cx  # (N,1)
                        v = fy * (points_c_valid[:, 1:2] / z) + cy  # (N,1)
                        pixels = torch.cat([u, v], dim=1).round().to(torch.int32)  # (N,2)
                        
                        in_img_mask = (
                            (pixels[:, 0] >= 0) & (pixels[:, 0] < W) &
                            (pixels[:, 1] >= 0) & (pixels[:, 1] < H)
                        )
                        in_img_global_indices = front_global_indices[in_img_mask]
                        pixels_in_img = pixels[in_img_mask]

                        if pixels_in_img.shape[0] == 0:
                            return
                        
                        seg_vals = seg_mask[pixels_in_img[:, 1], pixels_in_img[:, 0]]  # (N,) uint8张量
                        keep_mask = seg_vals == True  
                        keep_global_indices = in_img_global_indices[keep_mask]
                        point_mask[keep_global_indices] = True 

                        return point_mask
                    
                    # need_fileter_mask = filter_points_by_seg_mask_cuda(obstacle_points_pcd_tensor, seg_mask, c2w, curr_fx, curr_fy, curr_cx, curr_cy)
                    # filter_mask = (need_fileter_mask|filter_mask)
                    if mono_points is not None:
                        cam_mono_enhanced_points.append(mono_points)
                        if self.show_projection:
                            w2c = np.linalg.inv(c2w)
                            self.project_points_to_image(
                                np.array(mono_points["points3D_xyz"]), w2c,
                                curr_fx, curr_fy, curr_cx, curr_cy, image_path,
                                cam_name + "_" + str(frame_idx) + "_xpeng_proj.png"
                            )
                            points = obstacle_points_pcd_tensor.cpu().numpy()
                            self.project_points_to_image(
                                np.array(points[need_fileter_mask.cpu().numpy()]), w2c,
                                curr_fx, curr_fy, curr_cx, curr_cy, image_path,
                                cam_name + "_" + str(frame_idx) + "_xpeng_proj_filter.png"
                            )

            return {
                "fx": cam_fx,
                "fy": cam_fy,
                "cx": cam_cx,
                "cy": cam_cy,
                "width": cam_width,
                "height": cam_height,
                "camera_type": cam_camera_type,
                "poses_convert": cam_poses_convert,
                "poses_c2w": cam_poses_c2w,
                "image_filenames": cam_image_filenames,
                "depth_filenames": cam_depth_filenames,
                "mono_enhanced_points": cam_mono_enhanced_points,
                "filter_mask": filter_mask,
                "seg_mask_bkgd": seg_mask_bkgds,
            }

        thread_num = min(os.cpu_count() * 2, len(self.cam_name_list))
        all_cam_results = []  # 存储所有相机的处理结果
        cam_result_dict = {}
        with ThreadPoolExecutor(max_workers=thread_num) as executor:
            future_to_cam = {
                executor.submit(process_single_camera, cam_name): cam_name
                for cam_name in self.cam_name_list
            }
            for future in as_completed(future_to_cam):
                cam_name = future_to_cam[future]
                try:
                    cam_result = future.result()
                    cam_result_dict[cam_name] = cam_result  
                except Exception as e:
                    print(f"处理相机 {cam_name} 时出错: {str(e)}")
                    continue

        all_cam_results = [cam_result_dict[cam_name] for cam_name in self.cam_name_list]
        fx = []
        fy = []
        cx = []
        cy = []
        width = []
        height = []
        camera_type = []
        poses_convert = []
        poses_c2w = []
        image_filenames = []
        depth_filenames = []
        mono_enhanced_points = []
        seg_mask_bkgds = []

        filter_mask = cam_result_dict[self.mono_dense_cam]["filter_mask"]
        obstacle_points_pcd = o3d.geometry.PointCloud()
        points_np_filtered = points_np[filter_mask.cpu().numpy()].astype(np.float32, copy=False)
        colors_np_filtered = colors_np[filter_mask.cpu().numpy()].astype(np.float32, copy=False)


        points_np_filtered = points_np[~filter_mask.cpu().numpy()].astype(np.float32, copy=False)
        colors_np_filtered = colors_np[~filter_mask.cpu().numpy()].astype(np.float32, copy=False)
        obstacle_points_pcd.points = o3d.utility.Vector3dVector(points_np_filtered)
        obstacle_points_pcd.colors = o3d.utility.Vector3dVector(colors_np_filtered)


        for cam_result in all_cam_results:
            fx.extend(cam_result["fx"])
            fy.extend(cam_result["fy"])
            cx.extend(cam_result["cx"])
            cy.extend(cam_result["cy"])
            width.extend(cam_result["width"])
            height.extend(cam_result["height"])
            camera_type.extend(cam_result["camera_type"])
            poses_convert.extend(cam_result["poses_convert"])
            poses_c2w.extend(cam_result["poses_c2w"])
            image_filenames.extend(cam_result["image_filenames"])
            depth_filenames.extend(cam_result["depth_filenames"])
            mono_enhanced_points.extend(cam_result["mono_enhanced_points"])
            seg_mask_bkgds.extend(cam_result["seg_mask_bkgd"])


        output_points = self.obtain_bkgd_points(mono_enhanced_points, poses_c2w, obstacle_points_pcd)
        poses_convert = torch.from_numpy(np.array(poses_convert).astype(np.float32))
        cameras = Cameras(
            fx=torch.tensor(fx, dtype=torch.float32),
            fy=torch.tensor(fy, dtype=torch.float32),
            cx=torch.tensor(cx, dtype=torch.float32),
            cy=torch.tensor(cy, dtype=torch.float32),
            distortion_params=torch.zeros(1, 6),
            height=torch.tensor(height, dtype=torch.int32),
            width=torch.tensor(width, dtype=torch.int32),
            camera_to_worlds=poses_convert[:, :3, :4],
            camera_type=torch.tensor(camera_type, dtype=torch.int32),
            metadata={},
        )

        output_data = {
            "cameras_info": cameras,
            "image_filenames": image_filenames,
            "depth_filenames": depth_filenames if len(depth_filenames) > 0 else None,
            "seg_mask_bkgds" : seg_mask_bkgds,
            "input_pnt": output_points
        }

        return output_data, len(self.cam_name_list)


    def obtain_bkgd_points(self, mono_enhanced_points, poses_c2w, obstacle_points_pcd):
        original_mvs_points_number = len(obstacle_points_pcd.points)
        print("Background Points From 0.2 Downsample: ", original_mvs_points_number)

        if self.use_mono_dense and len(mono_enhanced_points) > 0:
            concat_points = self.concat_pointcloud_list(mono_enhanced_points)
            pcd_concat_points = o3d.geometry.PointCloud()
            points_np = concat_points["points3D_xyz"].contiguous().cpu().numpy().astype(np.float32, copy=False)
            colors_np = (concat_points["points3D_rgb"] / 255.0).contiguous().cpu().numpy().astype(np.float32, copy=False)
            pcd_concat_points.points = o3d.utility.Vector3dVector(points_np)
            pcd_concat_points.colors = o3d.utility.Vector3dVector(colors_np)
            pcd_concat_points = pcd_concat_points.voxel_down_sample(voxel_size=self.min_voxel)
            pcd_concat_points = self.obtain_near_points_from_traj(pcd_concat_points, poses_c2w)
            pcd_concat_points = self.remove_outlier_from_mvs(pcd_concat_points, obstacle_points_pcd)
            print("Mono Enhanced Points Number: ", len(pcd_concat_points.points))
            pcd_concat_points += obstacle_points_pcd
        else:
            pcd_concat_points = obstacle_points_pcd

        if self.use_colmap and os.path.exists(self.colmap_file):
            colmap_points = read_points3D_binary(self.colmap_file)
            colmap_points = self.obtain_colmap_points_from_traj(colmap_points, poses_c2w)
            pcd_concat_points += colmap_points

        pcd_concat_points, near_mask, mid_mask, far_mask = self.downsample_by_trajectory_distance(pcd_concat_points, poses_c2w)
        print("Total points after downsample from traj: ", len(pcd_concat_points.points))
        print("Additional Points From Mono: ", len(pcd_concat_points.points) - original_mvs_points_number)

        pcd_save_path = os.path.join(self.output_folder, "pcd_concat_points_final.ply")
        o3d.io.write_point_cloud(pcd_save_path, pcd_concat_points)

        points3D = np.asarray(pcd_concat_points.points, dtype=np.float32)
        points3D = torch.from_numpy(points3D)
        points3D_rgb = torch.from_numpy((np.asarray(pcd_concat_points.colors) * 255).astype(np.uint8))
        output_points = {
            "points3D_xyz": points3D,
            "points3D_rgb": points3D_rgb,
            "near_mask": near_mask,
            "mid_mask": mid_mask,
            "far_mask": far_mask
        }
        return output_points

    def filter_segmask(self, seg_img, segs_vision_static):
        CLASS_RGB_MAP = {
            'sky': (27, 27, 27),
            'ground': (13, 13, 13),
            'lane': (24, 24, 24),
            'car': (55, 55, 55),
            'ped': (21, 21, 21),
            'motor': (57, 57, 57),
            'human': (19, 19, 19),
            'Bicyclist': (20, 20, 20),
            'Motorcyclist': (21, 21, 21)
        }
        mask_conditions = np.zeros_like(seg_img[:, :, 0], dtype=bool)
        for rgb in CLASS_RGB_MAP.values():
            condition = (seg_img[:, :, 0] == rgb[2]) & \
                        (seg_img[:, :, 1] == rgb[1]) & \
                        (seg_img[:, :, 2] == rgb[0])
            mask_conditions |= condition
        high_value_condition = (seg_img[:, :, 2] >= 52) & \
                            (seg_img[:, :, 1] >= 52) & \
                            (seg_img[:, :, 0] >= 52)
        mask_conditions |= high_value_condition 
        seg_mask = ~mask_conditions
        seg_mask = segs_vision_static | seg_mask



        CLASS_RGB_MAP_GROUND = {
            'ground': (13, 13, 13),
            'lane': (24, 24, 24),
        }
        mask_conditions = False
        for rgb in CLASS_RGB_MAP_GROUND.values():
            condition = (seg_img[:, :, 0] == rgb[2]) & \
                        (seg_img[:, :, 1] == rgb[1]) & \
                        (seg_img[:, :, 2] == rgb[0])
            mask_conditions |= condition
        seg_mask_ground = mask_conditions
        return seg_mask,seg_mask_ground

    def get_points_from_depth(self, depth_npy_path, image_path, seg_path, fx, fy, cx, cy, c2w,segs_vision_static_path, voxel_size=None):
        R = c2w[:3, :3]
        T = c2w[:3, 3]
        depth_map = read_depth_file(depth_npy_path)
        height, width = depth_map.shape

        rgb_img = cv2.imread(image_path)
        h_rgb, w_rgb = rgb_img.shape[:2]

        seg_img = cv2.imread(seg_path)
        if seg_img is None:
            return None,None,None
        h_seg, w_seg = seg_img.shape[:2]
        segs_vision_static = np.load(segs_vision_static_path) == 100

        seg_mask, seg_mask_ground = self.filter_segmask(seg_img, segs_vision_static)
        if h_seg != h_rgb or w_seg != w_rgb:
            seg_mask = cv2.resize(seg_mask.astype(np.uint8), (w_rgb, h_rgb), interpolation=cv2.INTER_NEAREST).astype(bool)

        if (height != h_rgb or width != w_rgb):
            depth_map = cv2.resize(depth_map, (w_rgb, h_rgb), interpolation=cv2.INTER_LINEAR)
            height, width = depth_map.shape

            u = np.arange(width)
            v = np.arange(height)
            u_grid, v_grid = np.meshgrid(u, v)

        valid_mask = (depth_map > self.min_mono_depth) & (depth_map < self.max_mono_depth)
        if not np.any(valid_mask):
            return None,None,None

        if seg_mask is not None:
            valid_mask = valid_mask & seg_mask

        u_valid = u_grid[valid_mask]
        v_valid = v_grid[valid_mask]
        d_valid = depth_map[valid_mask]
        rgb_valid = rgb_img[v_valid, u_valid, ::-1]

        x_cam = (u_valid - cx) * d_valid / fx
        y_cam = (v_valid - cy) * d_valid / fy
        z_cam = d_valid
        pointcloud_cam = np.stack([x_cam, y_cam, z_cam], axis=1)
        dist_to_cam = np.linalg.norm(pointcloud_cam, axis=1)

        pointcloud_world = pointcloud_cam
        if R is not None and T is not None:
            R = np.array(R).reshape(3, 3)
            T = np.array(T).reshape(3, 1)
            pointcloud_world = (R @ pointcloud_cam.T + T).T

        points3D_xyz = torch.from_numpy(pointcloud_world.astype(np.float32))
        points3D_rgb_np = rgb_valid.astype(np.uint8)
        points3D_rgb = torch.from_numpy(points3D_rgb_np)

        pcd = o3d.geometry.PointCloud()
        points_np = pointcloud_world.astype(np.float32, copy=False)
        colors_np = (points3D_rgb_np / 255.0).astype(np.float32, copy=False)
        pcd.points = o3d.utility.Vector3dVector(points_np)
        pcd.colors = o3d.utility.Vector3dVector(colors_np)
        if voxel_size is None:
            near_mask = dist_to_cam <= self.near_dist
            far_mask = dist_to_cam >= self.far_dist
            mid_mask = ~(near_mask | far_mask)

            downsampled_pcds = []
            if np.any(near_mask):
                near_pcd = pcd.select_by_index(np.where(near_mask)[0])
                near_pcd = near_pcd.voxel_down_sample(voxel_size=self.min_voxel)
                downsampled_pcds.append(near_pcd)

            if np.any(far_mask):
                far_pcd = pcd.select_by_index(np.where(far_mask)[0])
                far_pcd = far_pcd.voxel_down_sample(voxel_size=self.max_voxel)
                downsampled_pcds.append(far_pcd)

            if np.any(mid_mask):
                mid_pcd = pcd.select_by_index(np.where(mid_mask)[0])
                mid_dists = dist_to_cam[mid_mask]
                mid_voxels = self.min_voxel + (mid_dists - self.near_dist) / (self.far_dist - self.near_dist) * (self.max_voxel - self.min_voxel)
                voxel_bins = np.linspace(min(mid_voxels), max(mid_voxels), 5)
                voxel_bin_indices = np.digitize(mid_voxels, voxel_bins)
                for bin_idx in range(len(voxel_bins)):
                    bin_mask = voxel_bin_indices == bin_idx
                    if np.any(bin_mask):
                        bin_pcd = mid_pcd.select_by_index(np.where(bin_mask)[0])
                        bin_voxel = np.mean(mid_voxels[bin_mask])
                        bin_pcd = bin_pcd.voxel_down_sample(voxel_size=bin_voxel)
                        downsampled_pcds.append(bin_pcd)

            if downsampled_pcds:
                pcd = downsampled_pcds[0]
                for sub_pcd in downsampled_pcds[1:]:
                    pcd += sub_pcd
            else:
                pcd = o3d.geometry.PointCloud()
        else:
            if voxel_size > 0:
                pcd = pcd.voxel_down_sample(voxel_size=voxel_size)

        points3D = np.asarray(pcd.points, dtype=np.float32)
        points3D = torch.from_numpy(points3D)
        points3D_rgb = torch.from_numpy((np.asarray(pcd.colors) * 255).astype(np.uint8))
        out = {
            "points3D_xyz": points3D,
            "points3D_rgb": points3D_rgb,
        }
        return out, seg_mask_ground, seg_mask

    def concat_pointcloud_list(self, out_list):
        xyz_tensors = []
        rgb_tensors = []
        for out in out_list:
            xyz = out["points3D_xyz"]
            rgb = out["points3D_rgb"]
            xyz_tensors.append(xyz)
            rgb_tensors.append(rgb)

        concat_xyz = torch.cat(xyz_tensors, dim=0)
        concat_rgb = torch.cat(rgb_tensors, dim=0)
        concat_out = {
            "points3D_xyz": concat_xyz,
            "points3D_rgb": concat_rgb,
        }
        return concat_out

    def extract_camera_centers(self, cam2world_list):
        camera_centers = []
        for pose in cam2world_list:
            if pose.shape == (4, 4):
                R = pose[:3, :3]
                t = pose[:3, 3:4]
            else:
                R = pose[:3, :3]
                t = pose[:3, 3:4]
            camera_centers.append(t.flatten())
        return np.array(camera_centers, dtype=np.float64)

    def obtain_near_points_from_traj(self, pcd, cam2world_trajectory):
        camera_centers = self.extract_camera_centers(cam2world_trajectory)
        n_frames = len(camera_centers)
        n_points = len(pcd.points)

        points_np = np.asarray(pcd.points, dtype=np.float32)
        if len(camera_centers) == 0:
            raise ValueError("No camera centers available")

        tree = KDTree(camera_centers.astype(np.float32))
        dist_to_trajectory, nearest_idx = tree.query(points_np)
        nearest_camera_z = camera_centers[nearest_idx, 2]
        delta_height = np.abs(points_np[:, 2] - nearest_camera_z)
        near_mask = (dist_to_trajectory <= self.near_dist) & (delta_height <= self.height_dist)

        near_pcd_down = None
        if np.any(near_mask):
            near_indices = np.where(near_mask)[0]
            near_pcd = pcd.select_by_index(near_indices)
            near_pcd_down = near_pcd.voxel_down_sample(voxel_size=self.min_voxel) 
        return near_pcd_down

    def obtain_colmap_points_from_traj(self, pcd, cam2world_trajectory):
        camera_centers = self.extract_camera_centers(cam2world_trajectory)
        n_frames = len(camera_centers)
        n_points = len(pcd.points)

        points_np = np.asarray(pcd.points, dtype=np.float32)
        if len(camera_centers) == 0:
            raise ValueError("No camera centers available.")

        tree = KDTree(camera_centers.astype(np.float32))
        dist_to_trajectory, _ = tree.query(points_np)
        mask = (dist_to_trajectory > self.colmap_min_dist) & (dist_to_trajectory < self.colmap_max_dist)
        colmap_pcd_down = None
        if np.any(mask):
            indices = np.where(mask)[0]
            colmap_pcd = pcd.select_by_index(indices)
            colmap_pcd_down = colmap_pcd.voxel_down_sample(voxel_size=self.min_voxel)

        colmap_pcd_down, ind = colmap_pcd_down.remove_statistical_outlier(nb_neighbors=10, std_ratio=1.0)
        return colmap_pcd_down

    def remove_outlier_from_mvs(self, pcd_concat_points, obstacle_points_pcd):
        distances = o3d.geometry.PointCloud.compute_point_cloud_distance(pcd_concat_points, obstacle_points_pcd)
        mask = np.asarray(distances) <= self.max_dist_from_mvs
        indices = np.where(mask)[0]
        filtered_pcd_concat_points = pcd_concat_points.select_by_index(indices)
        return filtered_pcd_concat_points

    def downsample_by_trajectory_distance(self, pcd, cam2world_trajectory):
        camera_centers = self.extract_camera_centers(cam2world_trajectory)
        n_frames = len(camera_centers)
        n_points = len(pcd.points)
        points_np = np.asarray(pcd.points, dtype=np.float32)
        if len(camera_centers) == 0:
            raise ValueError("No camera centers available.")

        tree = KDTree(camera_centers.astype(np.float32))
        dist_to_trajectory, _ = tree.query(points_np)
        near_mask = dist_to_trajectory <= self.near_dist
        far_mask = dist_to_trajectory >= self.far_dist
        mid_mask = ~(near_mask | far_mask)

        downsampled_pcds = []
        if np.any(near_mask):
            near_indices = np.where(near_mask)[0]
            near_pcd = pcd.select_by_index(near_indices)
            near_pcd_down = near_pcd.voxel_down_sample(voxel_size=self.min_voxel)
            downsampled_pcds.append(near_pcd_down)

        if np.any(far_mask):
            far_indices = np.where(far_mask)[0]
            far_pcd = pcd.select_by_index(far_indices)
            far_pcd_down = far_pcd.voxel_down_sample(voxel_size=self.max_voxel)
            downsampled_pcds.append(far_pcd_down)

        num_mid_bins = 5
        if np.any(mid_mask):
            mid_indices = np.where(mid_mask)[0]
            mid_pcd = pcd.select_by_index(mid_indices)
            mid_dists = dist_to_trajectory[mid_mask]
            mid_voxels = self.min_voxel + (mid_dists - self.near_dist) / (self.far_dist - self.near_dist) * (self.max_voxel - self.min_voxel)

            voxel_bins = np.linspace(min(mid_voxels), max(mid_voxels), num_mid_bins)
            voxel_bin_indices = np.digitize(mid_voxels, voxel_bins)

            for bin_idx in range(num_mid_bins):
                bin_mask = voxel_bin_indices == bin_idx
                if np.any(bin_mask):
                    bin_indices = np.where(bin_mask)[0]
                    bin_pcd = mid_pcd.select_by_index(bin_indices)
                    bin_voxel = np.mean(mid_voxels[bin_mask])
                    bin_pcd_down = bin_pcd.voxel_down_sample(voxel_size=bin_voxel)
                    downsampled_pcds.append(bin_pcd_down)

        downsampled_pcd = downsampled_pcds[0]
        near_len = len(downsampled_pcds[0].points)
        far_len = len(downsampled_pcds[1].points)
        for sub_pcd in downsampled_pcds[1:]:
            downsampled_pcd += sub_pcd
        
        total_points_num = len(downsampled_pcd.points)
        near_mask = torch.zeros(total_points_num, dtype=torch.bool)
        far_mask = torch.zeros(total_points_num, dtype=torch.bool)
        mid_mask = torch.zeros(total_points_num, dtype=torch.bool)
        near_mask[:near_len] = True
        start_idx = total_points_num - far_len       
        far_mask[start_idx:] = True                  
        mid_mask[near_len:start_idx] = True

        print(f"\nDownsampling completed: {len(pcd.points)} original points → {len(downsampled_pcd.points)} final points (Compression ratio: {100*(1 - len(downsampled_pcd.points)/len(pcd.points)):.1f}%)")
        return downsampled_pcd, near_mask, mid_mask, far_mask

    def project_points_to_image(self, point_cloud, pose, fx, fy, cx, cy, image_path, output_path, alpha=0.7):
        image = cv2.imread(image_path)
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        H, W = image.shape[:2]
        N = point_cloud.shape[0]
        points_hom = np.hstack((point_cloud, np.ones((N, 1))))
        points_cam_hom = (pose @ points_hom.T).T
        points_cam = points_cam_hom[:, :3] / points_cam_hom[:, 3:3+1]

        x, y, z = points_cam[:, 0], points_cam[:, 1], points_cam[:, 2]
        valid_z = z > 0
        x, y, z = x[valid_z], y[valid_z], z[valid_z]
        
        if len(x) == 0:
            return

        u = (fx * (x / z) + cx).astype(np.int32)
        v = (fy * (y / z) + cy).astype(np.int32)

        valid_uv = (0 <= u) & (u < W) & (0 <= v) & (v < H)
        u, v = u[valid_uv], v[valid_uv]
        z_filtered = z[valid_uv]
        x_f, y_f = x[valid_uv], y[valid_uv]
        
        print(f"Valid projections: {len(u)}")
        if len(u) == 0:
            print("No valid projections")
            return

        distances = np.sqrt(z_filtered**2)
        min_dist, max_dist = np.min(distances), np.max(distances)
        if max_dist > min_dist:
            normalized_dist = (distances - min_dist) / (max_dist - min_dist)
        else:
            normalized_dist = np.zeros_like(distances)

        def get_color(dist_norm):
            if dist_norm < 0.25:
                r = 0
                g = 0
                b = 255
            elif dist_norm < 0.5:
                r = 0
                g = int(255 * 4 * (dist_norm - 0.25))
                b = int(255 * (1 - 4 * (dist_norm - 0.25)))
            elif dist_norm < 0.75:
                r = int(255 * 4 * (dist_norm - 0.5))
                g = 255
                b = 0
            else:
                r = 255
                g = int(255 * (1 - 4 * (dist_norm - 0.75)))
                b = 0
            return (r, g, b)

        colors = np.array([get_color(d) for d in normalized_dist], dtype=np.uint8)
        sizes = (1 + 4 * (1 - normalized_dist)).astype(np.int32)

        overlay = image_rgb.copy()
        for i in range(len(u)):
            rgb = colors[i]
            cv2.circle(overlay, (u[i], v[i]), max(1, sizes[i]//2), (int(rgb[0]), int(rgb[1]), int(rgb[2])), -1)  # 填充圆点

        cv2.addWeighted(overlay, alpha, image_rgb, 1 - alpha, 0, image_rgb)
        image_bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)
        cv2.imwrite(output_path, image_bgr)
