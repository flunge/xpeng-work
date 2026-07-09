import sys
import os
import numpy as np
import open3d as o3d
import math
import time
import shutil
import random
import concurrent.futures
from pathlib import Path
from plyfile import PlyData, PlyElement
from utils.general_utils import quaternion_from_vectors


class GrdSurfelProcessor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.clip_path = Path(cfg.clip_path)
        self.save_path = os.path.join(self.clip_path, 'surfel_ground')
        os.makedirs(self.save_path, exist_ok=True)

        self.save_debug_surfel = not self.cfg.ips_deploy
        self.downsample_size = 0.02
        self.min_plane_points_number = 40
        self.min_voxel_plane_confidence = 0.8
        self.max_plane_error = 0.15
        self.voxel_size_xy = 2.0
        self.voxel_size_z = 10.0

        self.points = None
        self.rotations = None
        self.obtain_grd_points()

    def process_surfel(self):
        num_threads = min(os.cpu_count() or 1, 125)
        print("Start compute voxel normal, num threads: ", num_threads, flush = True)

        if self.save_debug_surfel:
            np.savetxt(os.path.join(self.save_path, "ground_init_points.txt"), self.points, delimiter=",", fmt="%.2f")

        voxel_origin_points = np.min(self.points, axis=0)
        world_points_id = self.points - voxel_origin_points
        world_points_id[:, :2] = world_points_id[:, :2] / self.voxel_size_xy
        world_points_id[:, 2] = world_points_id[:, 2] / self.voxel_size_z
        points_index = self.compute_hash_index(world_points_id.astype(int))
        unique_points_index = np.unique(points_index)

        args_list = []
        for idx in range(unique_points_index.shape[0]):
            curr_index = unique_points_index[idx]
            indices = np.where(points_index == curr_index)[0]
            args_list.append((
                curr_index, 
                indices, 
                self.points
            ))

        voxel_info = np.empty((0, 6))
        voxel_normal_array = np.empty((5, 0))
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(self.process_voxel, args) for args in args_list]
            for future in concurrent.futures.as_completed(futures):
                voxel_result = future.result()
                if voxel_result is not None:
                    voxel_normal_array = np.hstack((voxel_normal_array, voxel_result["plane_func"]))
                    if voxel_result["color_voxel"] is not None:
                        voxel_info = np.vstack((voxel_info, voxel_result["color_voxel"]))

        self.store_surfel(os.path.join(self.save_path, "ground_surfel.ply"))
        if self.save_debug_surfel:
            np.savetxt(os.path.join(self.save_path, "color_surfel.txt"), voxel_info, delimiter=",", fmt="%.2f")
            np.savetxt(os.path.join(self.save_path, "groud_surfel_points.txt"), self.points, delimiter=",", fmt="%.2f")
        return

    def obtain_grd_points(self):
        bkgd_ply_path = os.path.join(self.clip_path, 'input_ply/points3D_bkgd.ply')
        plydata = PlyData.read(bkgd_ply_path)        
        vertices = plydata['vertex']
        positions = np.vstack([vertices['x'], vertices['y'], vertices['z']]).T
        colors = np.vstack([vertices['red'], vertices['green'], vertices['blue']]).T

        ground_mask = np.load(os.path.join(self.clip_path, 'ground_mask.npy'))
        ground_points = positions[ground_mask.astype(bool).flatten()]
        ground_colors = colors[ground_mask.astype(bool).flatten()]

        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(ground_points)
        pcd.colors = o3d.utility.Vector3dVector(ground_colors)
        pcd = pcd.voxel_down_sample(voxel_size=self.downsample_size)
        self.points = np.asarray(pcd.points)
        self.colors = np.asarray(pcd.colors)
        self.rotations = np.zeros((self.points.shape[0], 4))
        self.rotations[:, 0] = 1

    def process_voxel(self, args):
        curr_index, indices, points  = args

        if indices.shape[0] <= self.min_plane_points_number:
            return None

        voxel_points = points[indices]
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(voxel_points)
        plane_model, inliers = pcd.segment_plane(
            distance_threshold=self.max_plane_error, 
            ransac_n=3, 
            num_iterations=500
        )
        if math.fabs(plane_model[2]) < 0.95:
            return None

        ones_column = np.ones((voxel_points.shape[0], 1))
        voxel_points_aug = np.hstack((voxel_points, ones_column))
        plane_model_fun = plane_model.reshape(4, 1)
        if np.max(np.abs(voxel_points_aug @ plane_model_fun)) > 0.5:
            return None

        if float(len(inliers)) / float(indices.shape[0]) < self.min_voxel_plane_confidence:
            return None

        self.update_sufel_points(indices, voxel_points_aug, plane_model_fun)
        self.update_gs_rot(indices, plane_model_fun[:3, 0])

        color_voxel = None
        if self.save_debug_surfel:
            color_info = [random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)]
            color_cols = np.tile(color_info, (voxel_points.shape[0], 1))
            color_voxel = np.hstack((voxel_points, color_cols))

        return {"plane_func":  np.array([[curr_index],[plane_model[0]], [plane_model[1]], [plane_model[2]], [plane_model[3]]]),
                "color_voxel": color_voxel}

    def compute_hash_index(self, voxel_points_id):
        voxel_points_id[:, 0] *= 73856093
        voxel_points_id[:, 1] *= 471943
        voxel_points_id[:, 2] *= 83492791
        points_index = (
            np.bitwise_xor(
                np.bitwise_xor(voxel_points_id[:, 0], voxel_points_id[:, 1]),
                voxel_points_id[:, 2],
            )
            % 10000000
        )
        return points_index

    def update_gs_rot(self, indices, plane_model):
        curr_rot = quaternion_from_vectors(np.array([0, 0, 1]), np.array([plane_model[0], plane_model[1], plane_model[2]]))
        self.rotations[indices] = curr_rot
        return 

    def update_sufel_points(self, indices, voxel_points_aug, plane_model_fun):
        voxel_points_aug[:, 2] = 0
        update_z = -(voxel_points_aug @ plane_model_fun) / plane_model_fun[2, 0]
        voxel_points_aug[:, 2] = np.squeeze(update_z)
        self.points[indices] = voxel_points_aug[:, :3]
        return

    def store_surfel(self, save_file):
        dtype = [('x', 'f4'), ('y', 'f4'), ('z', 'f4'),
                ('nx', 'f4'), ('ny', 'f4'), ('nz', 'f4'),
                ('red', 'u1'), ('green', 'u1'), ('blue', 'u1'),
                ('qw', 'f4'), ('qx', 'f4'), ('qy', 'f4'), ('qz', 'f4')]
        normals = np.zeros_like(self.points)

        elements = np.empty(self.points.shape[0], dtype=dtype)
        attributes = np.concatenate((self.points, normals, self.colors, self.rotations), axis=1)
        elements[:] = list(map(tuple, attributes))

        # Create the PlyData object and write to file
        vertex_element = PlyElement.describe(elements, 'vertex')
        ply_data = PlyData([vertex_element])
        ply_data.write(save_file)
