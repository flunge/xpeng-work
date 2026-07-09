import numpy as np
import os
import argparse 
import open3d as o3d
import json
import cv2
from pathlib import Path
from scipy.spatial.transform import Rotation as R
from scipy.spatial import cKDTree
from plyfile import PlyData, PlyElement
from multiprocessing import Pool
from functools import partial

from utils.colmap_parser import ColmapParser
from utils.calib_utils import get_intrisinc_from_transform
from utils.calib_utils import load_localpose_and_anchorpose_from_json
from utils.file_utils import storePly, timer, get_semantics_from_path, get_mask_from_semantics
from settings.globals import SemanticType


def process_frame(args, xyzs, rgbs, timestamp2p, timestamps, label_ground_func):
    t, transforms, i = args
    target_idx = int(timestamp2p[str(t)])
    target = np.where(timestamps == target_idx)[0]
    xyz = xyzs[target]
    rgb = rgbs[target]
    ground_mask = label_ground_func(transforms, xyz)
    print(f'[INFO][{t}] Label ground with frame: {i+1} with ground points: '
          f'{ground_mask.sum().astype(int)}/{len(ground_mask)}', flush=True)
    return xyz, rgb, ground_mask


class PointProcessor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.clip_path = Path(cfg.clip_path)
        self.transform_path = self.clip_path / "transform.json"
        self.transform_json = json.load(open(self.transform_path, "r"))
        self.localpose, self.anchorpose = load_localpose_and_anchorpose_from_json(self.clip_path)
        self.images_roi = dict()

        self.xyzs = None
        self.rgbs = None
        self.get_camera2anchor = None
        self.seg_class = None
        self.ground_mask = None
        self.lidar_mask = None
        # denoised results for training
        self.points_xyz_dict = dict()
        self.points_rgb_dict = dict()

        self._load_images_roi()
        self._load_input_points()

    def process_training_points(self):
        if self.cfg.steps_controller.source == "vision":
            self.process_training_points_vision()
        else:
            self.process_training_points_lidar()
    
    def process_training_points_vision(self):
        self.denoise_colmap_points()
        self.read_points_objects()
        self.save_training_points()
        self.save_ground_mask(save_vis=False)
        self.save_lidar_mask()

    def process_training_points_lidar(self):
        self.label_ground_points_from_lidar_parallel()
        self.downsize_backgroud_points(self.cfg.processor.lidar_voxel_size_init)
        self.denoise_colmap_points()
        self.denoise_points()
        self.read_points_objects()
        self.save_training_points()
        self.save_ground_mask()
        self.save_lidar_mask()

    def load_ply_points(self):
        pointcloud_dir = os.path.join(self.clip_path, 'input_ply')
        ply_path = os.path.join(pointcloud_dir, f'points3D_bkgd.ply')
        plydata = PlyData.read(ply_path)
        vertices = plydata['vertex']
        positions = np.vstack([vertices['x'], vertices['y'], vertices['z']]).T
        colors = np.vstack([vertices['red'], vertices['green'], vertices['blue']]).T
        self.xyzs = positions
        self.rgbs = colors
        self.ground_mask = np.load(self.clip_path / "ground_mask.npy")  
        self.lidar_mask = np.load(self.clip_path / "lidar_mask.npy")  

    def _load_input_points(self):            
        if self.cfg.steps_controller.source == "vision":
            self.read_points_from_static_recon()
        else:
            self.read_points_from_lidar()

    def _load_images_roi(self):
        for cam_name in self.transform_json['sensor_params']['camera_order']:
            roi_file_path = self.clip_path / f"misc/roi_{cam_name}.json"
            self.images_roi[cam_name] = json.load(open(roi_file_path, "r"))

    def read_points_from_colmap(self):
        xyzs, rgbs, _ = self.colmap_parser.get_colmap_points(file_name="points3D.bin")
        return xyzs.astype(np.float32), rgbs.astype(np.float32)

    def read_points_from_lidar(self):
        self.colmap_parser = ColmapParser(self.cfg, src="triangulated")
        self.colmap_parser.compute_localpose_from_colmap()
        # self.get_camera2anchor = self.get_camera2anchor_from_colmap
        self.get_camera2anchor = self.get_camera2anchor_from_transform_json

        pcd_data = o3d.io.read_point_cloud(str(self.clip_path / "misc/background.ply"))
        self.xyzs = np.array(pcd_data.points).astype(np.float32)
        self.rgbs = np.array(pcd_data.colors).astype(np.float32) * 255
        self.ground_mask = np.zeros((self.xyzs.shape[0], 1), dtype=bool)
        self.lidar_mask = np.ones((self.xyzs.shape[0], 1), dtype=bool)

    def read_points_from_static_recon(self):
        if os.path.exists(self.clip_path / "colmap/created/sparse/model/points3D.bin"):
            self.colmap_parser = ColmapParser(self.cfg, src="triangulated", vision_mode=True)
            self.colmap_parser.compute_localpose_from_colmap()
        else:
            self.colmap_parser = None
        bkgd_ply_path = self.clip_path / "obstacle_points_new.ply"
        grd_ply_path = self.clip_path / "road_mesh_new.ply"
        # rome_to_rig0 = np.linalg.inv(self.anchorpose)
        bkgd_ply = o3d.io.read_point_cloud(str(bkgd_ply_path))
        grd_ply = o3d.io.read_point_cloud(str(grd_ply_path))
        voxel_downsize = self.cfg.processor.vision_voxel_size
        voxel_downsize_grd = self.cfg.processor.vision_voxel_size_ground

        if voxel_downsize > 0.0:
            bkgd_ply = bkgd_ply.voxel_down_sample(voxel_downsize)
            print(f"[INFO] Downsample background points with voxel size {voxel_downsize}")
            # bkgd_ply = bkgd_ply.transform(rome_to_rig0)
        if voxel_downsize_grd > 0.0:
            grd_ply = grd_ply.voxel_down_sample(voxel_downsize_grd)
            print(f"[INFO] Downsample ground points with voxel size {voxel_downsize_grd}")
            # grd_ply = grd_ply.transform(rome_to_rig0)
        
        self.xyzs = np.concatenate((np.asarray(grd_ply.points), np.asarray(bkgd_ply.points)))
        self.rgbs = np.concatenate((np.asarray(grd_ply.colors), np.asarray(bkgd_ply.colors))) * 255
        self.ground_mask = np.concatenate((
            np.ones((np.asarray(grd_ply.points).shape[0], 1), dtype=bool), 
            np.zeros((np.asarray(bkgd_ply.points).shape[0], 1), dtype=bool)
        ))
        self.lidar_mask = np.zeros((self.xyzs.shape[0], 1), dtype=bool)
        self.points_xyz_dict['bkgd'] = self.xyzs
        self.points_rgb_dict['bkgd'] = self.rgbs
        self.get_camera2anchor = self.get_camera2anchor_from_transform_json

    def read_points_objects(self):
        threshold_num_obj = self.cfg.processor.object_downsample_threshold
        obj_basedir = os.path.join(f'{self.clip_path}/aggregate_lidar/dynamic_objects')
        obj_files = [i for i in os.listdir(obj_basedir) if i[-4:] == '.ply']
        for obj_ply in obj_files:
            track_id = int(obj_ply.replace('.ply', ''))
            ply_path = os.path.join(obj_basedir, obj_ply)
            
            plydata = PlyData.read(os.path.join(obj_basedir, f'{track_id}.ply'))
            vertices = plydata['vertex']
            positions = np.vstack([vertices['x'], vertices['y'], vertices['z']]).T
            colors = np.vstack([vertices['red'], vertices['green'], vertices['blue']]).T / 255.0
            if len(positions) > threshold_num_obj:
                print(f'[INFO] object {track_id} downsampled {len(positions)} points to {threshold_num_obj} points')
                random_indices = np.random.choice(len(positions), threshold_num_obj, replace=False)
                positions = positions[random_indices]
                colors = colors[random_indices]
            else:
                print(f'[INFO] object {track_id} sampled with {len(positions)} points')

            self.points_xyz_dict[f'obj_{track_id:09d}'] = positions
            self.points_rgb_dict[f'obj_{track_id:09d}'] = colors

    def get_camera2anchor_from_transform_json(self, transform_frame):
        return np.array(transform_frame["transform_matrix"])

    def get_camera2anchor_from_colmap(self, transform_frame):
        return self.colmap_parser.get_camera2anchor(transform_frame)

    def denoise_along_egopose(self, points_pcd, xy_radius, z_limit):
        xyz = np.asarray(points_pcd.points).astype(np.float32)
        ego_frame_poses = np.array([i for _, i in sorted(self.localpose.items())])
        ego_positions = ego_frame_poses[:, :3, 3]
        indices_inside_all_spheres = np.array([])
        for i in range(ego_positions.shape[0]):
            center = ego_positions[i]
            # Compute the distance of each point from the current center
            xy_distances = np.linalg.norm(xyz[:, :2] - center[:2], axis=1)
            z_distances = xyz[:, 2] - center[2]

            # Get the indices of points inside the current sphere
            inside_sphere_mask = np.logical_and(xy_distances <= xy_radius, z_distances <= z_limit)
            indices_inside_sphere = np.where(inside_sphere_mask)[0]

            # Append indices of points inside this sphere to the list
            indices_inside_all_spheres = np.union1d(indices_inside_all_spheres.astype(int), indices_inside_sphere)
        return indices_inside_all_spheres

    def denoise_colmap_points(self):
        if self.colmap_parser is not None:
            points_all_xyz, points_all_rgb = self.read_points_from_colmap()
            points_all = o3d.geometry.PointCloud()
            points_all.points = o3d.utility.Vector3dVector(points_all_xyz)
            points_all.colors = o3d.utility.Vector3dVector(points_all_rgb)
            if self.cfg.steps_controller.source == "vision" and self.cfg.steps_controller.vision_data_fetcher:
                rome_to_cam0 = np.linalg.inv(self.colmap_parser.cam2anchor_dict[1]['slice0'])
                cam2rig_path = self.clip_path / "poses_new"/"slice0_cam0.txt"
                cam_to_rig0 = []
                with open(cam2rig_path, "r") as f:
                    for line in f:
                        values = line.strip().split()
                        cam_to_rig0.append([float(v) for v in values])
                cam_to_rig0 = np.array(cam_to_rig0)
                rome_to_rig0 = cam_to_rig0 @ rome_to_cam0
                points_all = points_all.transform(rome_to_rig0)
                indices_inside_all_spheres = self.denoise_along_egopose(points_all, xy_radius=20, z_limit=6)
            # Remove the sfm point cloud along the egoposes
            else:
                indices_inside_all_spheres = self.denoise_along_egopose(points_all, xy_radius=50, z_limit=6)
            print(f"[INFO] Removing colmap points_inside_spheres with numbers {len(indices_inside_all_spheres)}")

            # Denoise the point cloud far away from the sphere
            points_outside_spheres = points_all.select_by_index(indices_inside_all_spheres.astype(int), invert=True)
            if self.cfg.steps_controller.source == "vision":
                denoised_points_far, _ = points_outside_spheres.remove_radius_outlier(nb_points=1, radius=20)
            else:
                denoised_points_far, _ = points_outside_spheres.remove_radius_outlier(nb_points=2, radius=1)
            print(f"[INFO] Denosing colmap points_outside_spheres from {len(points_outside_spheres.points)} to {len(denoised_points_far.points)}")

            # Add the filtered points back to the original point cloud
            points_all_new = denoised_points_far
            points_all_xyz, points_all_rgb = np.asarray(points_all_new.points), np.asarray(points_all_new.colors)
            print(f'[INFO] Denosing colmap total pointcloud from {len(points_all.points)} to {len(points_all_new.points)}')
            # concat background points
            self.xyzs = np.concatenate((points_all_xyz, self.xyzs))
            self.rgbs = np.concatenate((points_all_rgb, self.rgbs))
            self.ground_mask = np.concatenate(
                (np.zeros((points_all_xyz.shape[0], 1), dtype=bool), self.ground_mask.astype(bool))
            )
            self.lidar_mask = np.concatenate(
                (np.zeros((points_all_xyz.shape[0], 1), dtype=bool), self.lidar_mask.astype(bool))
            )
            
        self.points_xyz_dict['bkgd'] = self.xyzs
        self.points_rgb_dict['bkgd'] = self.rgbs

    @timer
    def denoise_points(self):
        xyz_grd = self.xyzs[self.ground_mask.astype(bool).flatten()]
        rgb_grd = self.rgbs[self.ground_mask.astype(bool).flatten()]
        xyz_bkgd = self.xyzs[~self.ground_mask.astype(bool).flatten()]
        rgb_bkgd = self.rgbs[~self.ground_mask.astype(bool).flatten()]
        # 1. Remove ground points with abnormal coordinates with pcd.remove_radius_outlier
        import math
        import faiss   
        xyz_nlist = int(math.sqrt(len(xyz_grd)))
        d = 3
        xyz_faiss_quantizer = faiss.IndexFlatL2(d)  
        xyz_faiss_index = faiss.IndexIVFFlat(xyz_faiss_quantizer, d, xyz_nlist)
        assert not xyz_faiss_index.is_trained
        xyz_faiss_index.train(xyz_grd)
        assert xyz_faiss_index.is_trained
        xyz_faiss_index_gpu = faiss.index_cpu_to_all_gpus(xyz_faiss_index)
        xyz_faiss_index_gpu.add(xyz_grd)    
        dist, _  = xyz_faiss_index_gpu.search(xyz_grd, k=6)
        outlier_mask = dist[:,-1] < 0.25
        before_denose_xyz_num = len(xyz_grd)
        xyz_grd = xyz_grd[outlier_mask]
        rgb_grd = rgb_grd[outlier_mask]

        print(f"[INFO] Denosing ground points from {before_denose_xyz_num} to {len(xyz_grd)}")

        # 2. Remove non-ground points along the egopose traj
        points_bkgd = o3d.geometry.PointCloud()
        points_bkgd.points = o3d.utility.Vector3dVector(xyz_bkgd)
        points_bkgd.colors = o3d.utility.Vector3dVector(rgb_bkgd / 255)
        indices_inside_all_spheres = self.denoise_along_egopose(points_bkgd, xy_radius=1.2, z_limit=3)
        print(f"[INFO] Removing bkgd points along egopose with numbers {len(indices_inside_all_spheres)}")
        points_bkgd = points_bkgd.select_by_index(indices_inside_all_spheres.astype(int), invert=True)

        # 更新lidar mask，去除被过滤的点
        filtered_pnts_mask = np.ones((self.lidar_mask.shape[0]), dtype=bool)
        # 需要依赖旧的ground mask !!!!
        grd_indices = np.where(self.ground_mask)[0]
        bkgd_indices = np.where(~self.ground_mask)[0]
        deleted_grd_indices = grd_indices[~outlier_mask]
        deleted_bkdg_indices = bkgd_indices[indices_inside_all_spheres]
        deleted_indices = np.concatenate((deleted_grd_indices,deleted_bkdg_indices))

        filtered_pnts_mask[deleted_indices] = False
        self.lidar_mask = self.lidar_mask[filtered_pnts_mask, :]
        self.ground_mask = self.ground_mask[filtered_pnts_mask, :]
        self.xyzs = self.xyzs[filtered_pnts_mask, :]
        self.rgbs = self.rgbs[filtered_pnts_mask, :]
        self.points_xyz_dict['bkgd'] = self.xyzs
        self.points_rgb_dict['bkgd'] = self.rgbs

    def downsize_backgroud_points(self, voxel_downsize):
        xyzs_ground = self.xyzs[self.ground_mask.astype(bool).flatten()]
        rgbs_ground = self.rgbs[self.ground_mask.astype(bool).flatten()]
        xyzs_backgroud = self.xyzs[~self.ground_mask.astype(bool).flatten()]
        rgbs_backgroud = self.rgbs[~self.ground_mask.astype(bool).flatten()]
        
        backgroud_ply = o3d.geometry.PointCloud()
        backgroud_ply.points = o3d.utility.Vector3dVector(xyzs_backgroud)
        backgroud_ply.colors = o3d.utility.Vector3dVector(rgbs_backgroud / 255)
        
        backgroud_ply = backgroud_ply.voxel_down_sample(voxel_downsize)
        print(f"[INFO] further downsize background points from {len(xyzs_backgroud)} to {len(backgroud_ply.points)}")

        self.xyzs = np.concatenate((xyzs_ground, np.asarray(backgroud_ply.points)))
        self.rgbs = np.concatenate((rgbs_ground, np.asarray(backgroud_ply.colors) * 255))
        self.ground_mask = np.zeros((self.xyzs.shape[0], 1), dtype=bool)
        self.lidar_mask = np.ones((self.xyzs.shape[0], 1), dtype=bool)
        self.ground_mask[:xyzs_ground.shape[0], :] = True
        self.points_xyz_dict['bkgd'] = self.xyzs
        self.points_rgb_dict['bkgd'] = self.rgbs

    def downsize_ground_points(self, voxel_downsize):
        xyzs_ground = self.xyzs[self.ground_mask.astype(bool).flatten()]
        rgbs_ground = self.rgbs[self.ground_mask.astype(bool).flatten()]

        background_lidar_mask = (~self.ground_mask) & (self.lidar_mask)
        background_non_lidar_mask = (~self.ground_mask) & (~self.lidar_mask)
        lidar_xyzs_backgroud = self.xyzs[background_lidar_mask.astype(bool).flatten()]
        lidar_rgbs_backgroud = self.rgbs[background_lidar_mask.astype(bool).flatten()]
        non_lidar_xyzs_backgroud = self.xyzs[background_non_lidar_mask.astype(bool).flatten()]
        non_lidar_rgbs_backgroud = self.rgbs[background_non_lidar_mask.astype(bool).flatten()]
        
        ground_ply = o3d.geometry.PointCloud()
        ground_ply.points = o3d.utility.Vector3dVector(xyzs_ground)
        ground_ply.colors = o3d.utility.Vector3dVector(rgbs_ground / 255)
        
        ground_ply = ground_ply.voxel_down_sample(voxel_downsize)
        print(f"[INFO] further downsize ground points from {len(xyzs_ground)} to {len(ground_ply.points)}")

        self.xyzs = np.concatenate((np.asarray(ground_ply.points), lidar_xyzs_backgroud, non_lidar_xyzs_backgroud))
        self.rgbs = np.concatenate((np.asarray(ground_ply.colors) * 255, lidar_rgbs_backgroud, non_lidar_rgbs_backgroud))
        self.ground_mask = np.zeros((self.xyzs.shape[0], 1), dtype=bool)
        self.lidar_mask = np.zeros((self.xyzs.shape[0], 1), dtype=bool)
        self.ground_mask[:len(ground_ply.points), :] = True
        gnd_and_lidar_bkgd_nums = len(ground_ply.points) + lidar_xyzs_backgroud.shape[0]
        self.lidar_mask[:gnd_and_lidar_bkgd_nums, :] = True
        self.points_xyz_dict['bkgd'] = self.xyzs
        self.points_rgb_dict['bkgd'] = self.rgbs

    def downsize_background_lidar_points(self, voxel_downsize):
        background_lidar_mask = (~self.ground_mask) & (self.lidar_mask)
        background_non_lidar_mask = (~self.ground_mask) & (~self.lidar_mask)
        ground_lidar_mask = (self.ground_mask) & (self.lidar_mask)
        ground_non_lidar_mask = (self.ground_mask) & (~self.lidar_mask)

        lidar_xyzs_backgroud = self.xyzs[background_lidar_mask.astype(bool).flatten()]
        lidar_rgbs_backgroud = self.rgbs[background_lidar_mask.astype(bool).flatten()]
        lidar_xyzs_ground = self.xyzs[ground_lidar_mask.astype(bool).flatten()]
        lidar_rgbs_ground = self.rgbs[ground_lidar_mask.astype(bool).flatten()]
        non_lidar_xyzs_backgroud = self.xyzs[background_non_lidar_mask.astype(bool).flatten()]
        non_lidar_rgbs_backgroud = self.rgbs[background_non_lidar_mask.astype(bool).flatten()]
        non_lidar_xyzs_ground = self.xyzs[ground_non_lidar_mask.astype(bool).flatten()]
        non_lidar_rgbs_ground = self.rgbs[ground_non_lidar_mask.astype(bool).flatten()]

        backgroud_lidar_ply = o3d.geometry.PointCloud()
        backgroud_lidar_ply.points = o3d.utility.Vector3dVector(lidar_xyzs_backgroud)
        backgroud_lidar_ply.colors = o3d.utility.Vector3dVector(lidar_rgbs_backgroud / 255)
        
        backgroud_lidar_ply = backgroud_lidar_ply.voxel_down_sample(voxel_downsize)
        print(f"[INFO] further downsize background lidar points from {len(lidar_xyzs_backgroud)} to {len(backgroud_lidar_ply.points)}")

        self.xyzs = np.concatenate((lidar_xyzs_ground, non_lidar_xyzs_ground, np.asarray(backgroud_lidar_ply.points), non_lidar_xyzs_backgroud))
        self.rgbs = np.concatenate((lidar_rgbs_ground, non_lidar_rgbs_ground, np.asarray(backgroud_lidar_ply.colors) * 255, non_lidar_rgbs_backgroud))
        self.ground_mask = np.zeros((self.xyzs.shape[0], 1), dtype=bool)
        self.ground_mask[:(lidar_xyzs_ground.shape[0] + non_lidar_xyzs_ground.shape[0]), :] = True
        self.points_xyz_dict['bkgd'] = self.xyzs
        self.points_rgb_dict['bkgd'] = self.rgbs

        self.lidar_mask = np.zeros((self.xyzs.shape[0], 1), dtype=bool)
        lidar_ground_counts = lidar_xyzs_ground.shape[0]
        non_lidar_ground_counts = non_lidar_xyzs_ground.shape[0]
        ground_counts = lidar_ground_counts + non_lidar_ground_counts
        lidar_bkgd_counts = len(backgroud_lidar_ply.points)
        self.lidar_mask[:lidar_ground_counts, :] = True
        self.lidar_mask[ground_counts:ground_counts+lidar_bkgd_counts, :] = True

    # 重新对ply降采样
    # 背景：使用密集点云生成深度图后，需要降采样ply，降低点数以提升高斯重建速度
    def resample_ply_points(self):
        self.load_ply_points()
        # 使用稠密点云生成背景深度图，会导致背景退化（背景仅靠rgb监督能学得更好），所以暂不开启背景的稠密深度图
        # self.downsize_background_lidar_points(self.cfg.processor.lidar_voxel_size_final)
        self.downsize_ground_points(self.cfg.processor.lidar_voxel_size_ground_final)
        self.save_training_points()
        self.save_ground_mask()
        self.save_lidar_mask()

    @timer
    def label_points_class(self):
        cam_order = ['cam2', 'cam0', 'cam3', 'cam4', 'cam5', 'cam6', 'cam7'] # 
        # use reverse sorted frames in time for each camera since the last frame is the closest to the far-away scene,
        # and this makes the filter out process automatically based on the distance to the camera in most cases
        cam_transform = {i: [j for j in self.transform_json['frames'][::-1] if j['camera'] == i] for i in cam_order}
        sorted_transforms = [cam_transform[i] for i in cam_order]
        
        points_np = np.hstack([self.points_xyz_dict['bkgd'] , np.ones((self.points_xyz_dict['bkgd'].shape[0], 1))])
        seg_class = np.zeros((points_np.shape[0], 1))
        seg_class_idx = np.array([i for i in range(points_np.shape[0])])

        for i, transforms in enumerate(sorted_transforms):
            cam_name = cam_order[i]
            for idx, frame in enumerate(transforms):
                print(f'[INFO] Labeling seg with cam {cam_name} frame: {idx}/{len(transforms)}. ' \
                      f'Rest points: {points_np.shape[0]}')
                if points_np.shape[0] < 10:
                    break

                camera2anchor = self.get_camera2anchor(frame)
                anchor2camera = np.linalg.inv(camera2anchor)

                intrinsic_matrix, _1, _2 = get_intrisinc_from_transform(frame)
                x, y = self.images_roi[cam_name]['x'], self.images_roi[cam_name]['y']
                h, w = self.images_roi[cam_name]['h'], self.images_roi[cam_name]['w']
                
                seg_img = cv2.imread(str(self.clip_path / frame["file_path"].replace("images", "segs")))
                mask_img = cv2.imread(
                    str(self.clip_path / frame["file_path"].replace("images", "masks")), cv2.IMREAD_GRAYSCALE
                ).astype(bool)

                camera_coordinates = anchor2camera.astype(np.float32) @ points_np.astype(np.float32).T
                points_front_camera = camera_coordinates[2, :] > 0
                filtered_points = points_np[points_front_camera]
                uv_homogeneous = intrinsic_matrix.astype(np.float32) @ camera_coordinates[:, points_front_camera].astype(np.float32)
                # uv_homogeneous = intrinsic_matrix @ anchor2camera @ points_np.T
                division_row = uv_homogeneous[2, :]
                cam_pcl = (uv_homogeneous[:2,:] / division_row).astype(int)
                mask_from_roi = (cam_pcl[0, :] >= x) * (cam_pcl[0, :] < x+w) * \
                                (cam_pcl[1, :] >= y) * (cam_pcl[1, :] < y+h)
                pixels = cam_pcl[:, mask_from_roi]
                mask_from_img = mask_img[pixels[1, :], pixels[0, :]]
                seg_label = seg_img[pixels[1, :], pixels[0, :]][..., 0]
                # get masked points of this iteration
                points_front_camera[points_front_camera] &= mask_from_roi # mask out points outside roi or not on the ground
                points_front_camera[points_front_camera] &= mask_from_img # mask out points on the ego car
                point_idx_found = seg_class_idx[points_front_camera]
                seg_class[point_idx_found] = seg_label[mask_from_img, None]
                
                # remove masked points and continue iteration for rest points
                points_np = points_np[~points_front_camera, :]
                seg_class_idx = seg_class_idx[~points_front_camera]
        self.seg_class = seg_class

    @timer
    def label_ground_points(self):
        cam_order = ['cam2', 'cam0', 'cam3', 'cam4', 'cam5', 'cam6', 'cam7'] # 
        # use reverse sorted frames in time for each camera since the last frame is the closest to the far-away scene,
        # and this makes the filter out process automatically based on the distance to the camera in most cases
        cam_transform = {i: [j for j in self.transform_json['frames'][::-1] if j['camera'] == i] for i in cam_order}
        sorted_transforms = [cam_transform[i] for i in cam_order]
        
        points_np = np.hstack([self.points_xyz_dict['bkgd'] , np.ones((self.points_xyz_dict['bkgd'].shape[0], 1))])
        ground_mask = np.zeros((points_np.shape[0], 1))
        ground_mask_idx = np.array([i for i in range(points_np.shape[0])])

        for i, transforms in enumerate(sorted_transforms):
            cam_name = cam_order[i]
            for idx, frame in enumerate(transforms):
                print(f'[INFO] Labeling ground with cam {cam_name} frame: {idx}/{len(transforms)}. '\
                      f'Rest points: {points_np.shape[0]}/{len(ground_mask)}')
                if points_np.shape[0] < 10:
                    break

                camera2anchor = self.get_camera2anchor(frame)
                anchor2camera = np.linalg.inv(camera2anchor)

                intrinsic_matrix, _1, _2 = get_intrisinc_from_transform(frame)
                x, y = self.images_roi[cam_name]['x'], self.images_roi[cam_name]['y']
                h, w = self.images_roi[cam_name]['h'], self.images_roi[cam_name]['w']
                
                semantics = get_semantics_from_path(self.clip_path / frame["file_path"].replace("images", "segs"))
                ground = (1 - get_mask_from_semantics(semantics, SemanticType.GROUND)).astype(bool)[:, :, None]

                camera_coordinates = anchor2camera.astype(np.float32) @ points_np.astype(np.float32).T
                points_front_camera = camera_coordinates[2, :] > 0
                filtered_points = points_np[points_front_camera]
                uv_homogeneous = intrinsic_matrix.astype(np.float32) @ camera_coordinates[:, points_front_camera].astype(np.float32)
                division_row = uv_homogeneous[2, :]
                cam_pcl = (uv_homogeneous[:2,:] / division_row).astype(int)
                mask = (cam_pcl[0, :] >= x) * (cam_pcl[0, :] < x+w) * \
                    (cam_pcl[1, :] >= y) * (cam_pcl[1, :] < y+h)
                pixels = cam_pcl[:, mask]
                ground_label = ground[pixels[1, :], pixels[0, :]]
                mask[mask] &= ground_label.flatten()  # combine roi mask with ground mask
                # get masked points of this iteration
                points_front_camera[points_front_camera] = mask # mask out points outside roi or not on the ground
                ground_mask_idx_found = ground_mask_idx[points_front_camera]
                ground_mask[ground_mask_idx_found] = 1

                # remove masked points and continue iteration for rest points
                points_np = points_np[~points_front_camera, :]
                ground_mask_idx = ground_mask_idx[~points_front_camera]
        self.ground_mask = ground_mask
    
    @timer
    def label_ground_points_from_lidar_parallel(self):
        # transform.json
        sorted_transforms = {}
        for i in self.transform_json['frames']:
            timestamp = i['timestamp']
            if timestamp not in sorted_transforms:
                sorted_transforms[timestamp] = []
            sorted_transforms[timestamp].append(i)
        sorted_transforms = dict(sorted(sorted_transforms.items()))

        timestamps = np.load(self.clip_path / "misc/points_timestamp.npy")
        p2timestamp = json.load(open(self.clip_path / "misc/points2timestamp.json", "r"))
        timestamp2p = {v: k for k, v in p2timestamp.items()}
        assert np.unique(timestamps).shape[0] == len(sorted_transforms), \
            "Timestamps in points_timestamp.npy not match with transform.json!"

        # Prepare arguments for multiprocessing
        args = [(t, transforms, i) for i, (t, transforms) in enumerate(sorted_transforms.items())]
        
        # Use multiprocessing Pool
        num_processes = min(8, len(args)) or 1  # Use available CPU cores, at least 1

        with Pool(processes=num_processes) as pool:
            result = pool.map_async(partial(process_frame,
                xyzs=self.xyzs, rgbs=self.rgbs, timestamp2p=timestamp2p, 
                timestamps=timestamps, label_ground_func=self.label_ground_points_one_frame), 
            args)
            results = result.get(timeout=3600)  # 1 hour max for point processing

        # Collect results
        res_xyzs, res_rgbs, res_mask = zip(*results)
        
        sorted_xyzs = np.concatenate(res_xyzs)
        sorted_rgbs = np.concatenate(res_rgbs)
        sorted_ground_mask = np.concatenate(res_mask)
        
        assert sorted_xyzs.shape[0] == self.xyzs.shape[0], "New xyz points not match with original points!"
        print(f'[INFO] Label ground points done, total ground points: {sorted_ground_mask.sum().astype(int)}/{len(sorted_ground_mask)}')
        
        self.xyzs = sorted_xyzs
        self.rgbs = sorted_rgbs
        self.ground_mask = sorted_ground_mask
        # below is optional, already setted
        self.lidar_mask = np.ones((self.xyzs.shape[0], 1), dtype=bool)
        self.filter_bkgd_points_on_ground()

    @timer
    def label_ground_points_from_lidar(self):
        # transform.json
        sorted_transforms = {}
        for i in self.transform_json['frames']:
            timestamp = i['timestamp']
            if timestamp not in sorted_transforms:
                sorted_transforms[timestamp] = []
            sorted_transforms[timestamp].append(i)
        sorted_transforms = dict(sorted(sorted_transforms.items()))

        # 每个点是在哪一帧采集的，shape等于self.xyzs.shape
        timestamps = np.load(self.clip_path / "misc/points_timestamp.npy")
        # 每一帧的时间戳，如第6帧的时间戳 '6': '1745049194388944855'
        p2timestamp = json.load(open(self.clip_path / "misc/points2timestamp.json", "r"))
        # 每个时间戳对应的帧，即p2timestamp反过来
        timestamp2p = {v: k for k, v in p2timestamp.items()}
        assert np.unique(timestamps).shape[0] == len(sorted_transforms), \
            "Timestamps in points_timestamp.npy not match with transform.json!"
        
        res_xyzs = []
        res_rgbs = []
        res_mask = []
        # transform.json: sensor param, sensor to current car ; frame, sensor to first car
        for i, (t, transforms) in enumerate(sorted_transforms.items()):
            # 取当前时间戳对应的frame index
            target_idx = int(timestamp2p[str(t)])
            # recall timestamps是每个点被采集的帧数，这句话是获取在target_idx帧被采集的点的（在所有点中的）index集合
            target = np.where(timestamps == target_idx)[0]
            # target是被选中的点的index集合，这句话是取出被选中的点的坐标
            xyz = self.xyzs[target]
            # 取出被选中的点的rgb值
            rgb = self.rgbs[target]
            # xyz为在i帧被采集的点，transform为i帧7个camera的内外参，因此下面这句话标注i帧采集的点中属于地面为true，不属于地面的为false
            ground_mask = self.label_ground_points_one_frame(transforms, xyz)
            # 已被标注过的点xyz添加进结果中
            res_xyzs.append(xyz)
            # 已被标注过的点rgb添加进结果中
            res_rgbs.append(rgb)
            # 每个点的标注结果添加进结果中
            # 核心是这三个res中，相同的index代表的都是同一个点，例如res_xyzs[456] res_rgbs[456] res_mask[456]都是同一个点
            res_mask.append(ground_mask)
            print(f'[INFO][{t}] Label ground with frame: {i+1}/{len(sorted_transforms)} with ground points: '
                  f'{ground_mask.sum().astype(int)}/{len(ground_mask)}')
        sorted_xyzs = np.concatenate(res_xyzs)
        sorted_rgbs = np.concatenate(res_rgbs)
        sorted_ground_mask = np.concatenate(res_mask)
        assert sorted_xyzs.shape[0] == self.xyzs.shape[0], "New xyz points not match with original points!"
        print(f'[INFO] Label ground points done, total ground points: {sorted_ground_mask.sum().astype(int)}/{len(sorted_ground_mask)}')
        self.xyzs = sorted_xyzs
        self.rgbs = sorted_rgbs
        self.ground_mask = sorted_ground_mask
        self.filter_bkgd_points_on_ground()
        self.lidar_mask = np.ones((self.xyzs.shape[0], 1), dtype=bool)

    def label_ground_points_one_frame(self, transforms, points_xyz):
        # 将3D点转换为齐次坐标 (x, y, z, 1)
        points_np = np.hstack([points_xyz , np.ones((points_xyz.shape[0], 1))]).astype(np.float32)
        # 初始化ground mask，表示哪些点属于ground
        ground_mask = np.zeros((points_np.shape[0], 1))
        # 生成点的index数组，例如[0,1,2,3,4....points_np.shape[0]]
        ground_mask_idx = np.array([i for i in range(points_np.shape[0])])

        for idx, frame in enumerate(transforms):
            if points_np.shape[0] < 10:
                break

            camera2anchor = self.get_camera2anchor_from_transform_json(frame)
            anchor2camera = np.linalg.inv(camera2anchor).astype(np.float32)
            cam_name = frame["camera"]

            intrinsic_matrix, _1, _2 = get_intrisinc_from_transform(frame)

            semantics = get_semantics_from_path(self.clip_path / frame["file_path"].replace("images", "segs"))
            # ground mask, 将地面区域置为true, 非地面区域置为false
            ground = (1 - get_mask_from_semantics(semantics, SemanticType.GROUND)).astype(bool)[:, :, None]
            # 车体mask
            mask_img = cv2.imread(
                str(self.clip_path / frame["file_path"].replace("images", "masks")), cv2.IMREAD_GRAYSCALE
            ).astype(bool)

            # 所有点从第一帧坐标系转化到当前帧的camera坐标系（仍然是3d坐标）
            # 注意camera_coordinates是4*N的坐标，因为points_np求了转置
            camera_coordinates = anchor2camera @ points_np.T
            # 筛选出z值（第3列）大于0的点，返回的将是表示每个点z是否大于0的bool数组，true代表点z>0，即在camera前方的点，false代表在camera后方的点
            points_front_camera = camera_coordinates[2, :] > 0
            # 取出在camera前方的点
            filtered_points = points_np[points_front_camera]
            # 3D to 2D，camera_coordinates[:, points_front_camera]表示取所有行（xyz及齐次坐标1），列取在camera前方的点
            uv_homogeneous = intrinsic_matrix.astype(np.float32) @ camera_coordinates[:, points_front_camera]
            # 3D to 2D必要计算，uv_homogeneous = [u, v, z]，像素坐标为u/z, v/z
            division_row = uv_homogeneous[2, :]
            # 注意，cam_pcl包括了图片范围之外的点，需要滤掉
            # 提醒下，uv_homogeneous和cam_pcl只包括在camera前方的点
            cam_pcl = (uv_homogeneous[:2,:] / division_row).astype(int)

            # x, y = self.images_roi[cam_name]['x'], self.images_roi[cam_name]['y']
            # h, w = self.images_roi[cam_name]['h'], self.images_roi[cam_name]['w']
            x, y = 0, 0
            h, w = mask_img.shape
            # 滤掉图片范围之外的点，cam_pcl[0, :] >= x返回一个bool数组，横轴坐标大于x的为True，小于x的为false，* 等同于 & 求与
            # 最终返回的mask_roi表示在图片中的点的mask，在图片中的点为True，不在图片中的点为False
            mask_roi = (cam_pcl[0, :] >= x) * (cam_pcl[0, :] < x+w) * \
                (cam_pcl[1, :] >= y) * (cam_pcl[1, :] < y+h)
            # 取出在图片中的点的坐标
            pixels = cam_pcl[:, mask_roi]
            # 在语义分割图中找到（投影到2D的激光）点，ground_label数组表示激光点是否在地面，投影到地面区域的点为true，投影到非地面区域的点为false
            ground_label = ground[pixels[1, :], pixels[0, :]]
            # 在车身mask图中找到（投影到2D的激光）点，mask_point数组表示激光点是否在非车身区域，投影到非车身区域的点为true，投影到车身区域的点为false
            mask_point = mask_img[pixels[1, :], pixels[0, :]]

            # 三者取并集，即在图片中(mask_roi) & 非车身 & 地面区域的激光点
            mask_roi[mask_roi] &= ground_label.flatten() & mask_point.flatten()  
            # 回忆：points_front_camera表示每个点是否在camera前方，true代表是，false代表不是
            # 这句话选中了points_front_camera中true的部分，令这部分等于mask_roi（在图片中(mask_roi) & 非车身 & 地面区域的点为true，其余点为false）
            # 所以points_front_camera中为true的是在camera前方，在图片中(mask_roi) & 非车身 & 地面区域的点
            points_front_camera[points_front_camera] = mask_roi # mask out points outside roi or not on the ground
            # 返回“在camera前方，在图片中(mask_roi) & 非车身 & 地面区域“的点的index
            ground_mask_idx_found = ground_mask_idx[points_front_camera]
            # ground_mask初始值为长度与所有点集数量相同的0/1数组，这里令ground_mask中属于地面区域的点变成1
            ground_mask[ground_mask_idx_found] = 1

            # 剔除已经标注为地面的点
            points_np = points_np[~points_front_camera, :]
            ground_mask_idx = ground_mask_idx[~points_front_camera]
        
        return ground_mask     

    def filter_bkgd_points_on_ground(self):
        # # find the nearest 10 points (including ground points) for each background points
        kdtree = cKDTree(self.xyzs)
        dist, idx = kdtree.query(self.xyzs[~self.ground_mask.astype(bool).flatten()], k=10)   
        # filter out background points whose nearest N points are ground points
        mask = np.sum(self.ground_mask[idx], axis=1) > 0
        self.ground_mask[~self.ground_mask.astype(bool).flatten()] = mask

    def save_ground_mask(self, save_vis=True):
        # save for training: ground_mask.npy
        self.ground_mask = self.ground_mask.astype(bool)
        np.save(self.clip_path / "ground_mask.npy", self.ground_mask)
        # save for visualization: misc/ground_labels.ply, misc/seg_class.npy
        if self.seg_class is not None:
            np.save(self.clip_path / "misc/seg_class.npy", self.seg_class)
        
        if save_vis:
            points_xyz = self.points_xyz_dict['bkgd']
            points_rgb = self.points_rgb_dict['bkgd']
            xyz_bkgd = points_xyz[~self.ground_mask.flatten()]
            rgb_bkgd = points_rgb[~self.ground_mask.flatten()]
            storePly(os.path.join(self.clip_path, "misc/vis_background_new.ply"), xyz_bkgd, rgb_bkgd)

            xyz_grd = points_xyz[self.ground_mask.flatten()]
            rgb_grd = points_rgb[self.ground_mask.flatten()]
            storePly(os.path.join(self.clip_path, "misc/vis_ground_new.ply"), xyz_grd, rgb_grd)
    
    def save_lidar_mask(self, save_vis=True):
        self.lidar_mask = self.lidar_mask.astype(bool)
        np.save(self.clip_path / "lidar_mask.npy", self.lidar_mask)
        
    def save_training_points(self):
        pointcloud_dir = os.path.join(self.clip_path, 'input_ply')
        os.makedirs(pointcloud_dir, exist_ok=True)

        for k in self.points_xyz_dict.keys():
            points_xyz = self.points_xyz_dict[k]
            points_rgb = self.points_rgb_dict[k]
            ply_path = os.path.join(pointcloud_dir, f'points3D_{k}.ply')
            try:
                storePly(ply_path, points_xyz, points_rgb)
                print(f'[INFO] saving pointcloud for {k}, number of initial points is {points_xyz.shape}')
            except:
                print(f'[ERROR] failed to save pointcloud for {k}')
                continue
    
    def load_training_points(self):
        pointcloud_dir = os.path.join(self.clip_path, 'input_ply')
        ply_path = os.path.join(pointcloud_dir, f'points3D_bkgd.ply')
        plydata = PlyData.read(ply_path)
        vertices = plydata['vertex']
        positions = np.vstack([vertices['x'], vertices['y'], vertices['z']]).T
        colors = np.vstack([vertices['red'], vertices['green'], vertices['blue']]).T
        self.points_xyz_dict['bkgd'] = positions
        self.points_rgb_dict['bkgd'] = colors
        self.xyzs = positions
        self.rgbs = colors
        self.ground_mask = np.load(self.clip_path / "ground_mask.npy")        
        

if __name__ == '__main__':
    from settings.config import make_default_settings, make_case_specific_settings
    cfg = make_default_settings()
    cfg.ips_deploy = False
    cfg.dataset_name = "dev_test_dataset"
    cfg.root = f"/workspace/group_share/adc-sim/users/zhangzy27/dataset/dev_test_dataset_resample/"
    cfg.clip_id = "c-0ce7c9b3-288b-3984-8a1b-38f7ad28cbf4"
    cfg.ips_deploy = False
    cfg = make_case_specific_settings(cfg)
    cfg.steps_controller.source = "lidar"

    point_processor = PointProcessor(cfg)
    point_processor.process_training_points()

        
