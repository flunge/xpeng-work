import numpy as np
import os
import argparse
import json
import torch
from pathlib import Path
from plyfile import PlyData, PlyElement
from utils.calib_utils import get_intrisinc_from_transform
from utils.file_utils import storePly, get_semantics_from_path, get_mask_from_semantics
from settings.globals import SemanticType
import cv2
import matplotlib.pyplot as plt
import open3d as o3d  # Import Open3D for point cloud processing
from collections import defaultdict


class TrafficLightExtractor:
    def __init__(self, cfg, lidar_processor = None):
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.cfg = cfg
        self.clip_path = Path(cfg.clip_path)
        self.transform_path = self.clip_path / "transform.json"
        self.transform_json = json.load(open(self.transform_path, "r"))
        if self.cfg.steps_controller.source != "vision":
           self.lidar_processor = lidar_processor  # Store lidar_processor instance
        else:
           self.load_ply_points()
           self.xyz = torch.tensor(self.xyzs_temp, dtype=torch.float32, device=device)
           self.rgbs = torch.tensor(self.rgbs_temp, dtype=torch.float32, device=device)
        self.traffic_light_points = []
        self.traffic_light_rgbs = []
        self.traffic_light_ratios = []  # Store pixel ratios for each frame
        self.traffic_light_points_vector=[]


    def load_ply_points(self):
        pointcloud_dir = os.path.join(self.clip_path, 'input_ply')
        ply_path = os.path.join(pointcloud_dir, f'points3D_bkgd.ply')
        plydata = PlyData.read(ply_path)
        vertices = plydata['vertex']
        positions = np.vstack([vertices['x'], vertices['y'], vertices['z']]).T
        colors = np.vstack([vertices['red'], vertices['green'], vertices['blue']]).T
        self.xyzs_temp = positions
        self.rgbs_temp = colors


    def remove_traffic_light_from_background(self):
        """Remove points from points3D_bkgd.ply that are in points3D_traffic_light_filtered.ply."""
        # Define file paths
        traffic_light_ply_path = os.path.join(self.clip_path, 'input_ply', 'points3D_tfl.ply')
        background_ply_path = os.path.join(self.clip_path, 'input_ply', 'points3D_bkgd.ply')
        ground_mask_path = os.path.join(self.clip_path, "ground_mask.npy")

        ground_mask = torch.from_numpy(np.load(ground_mask_path)).bool()
        # Load traffic light point cloud
        traffic_light_pcd = o3d.io.read_point_cloud(traffic_light_ply_path)
        if len(traffic_light_pcd.points) == 0:
            print(f"[INFO] No points in {traffic_light_ply_path}. Background remains unchanged.")
            return

        # Load background point cloud
        background_pcd = o3d.io.read_point_cloud(background_ply_path)
        print(f"Original background points: {len(background_pcd.points)}")

        # Build KD-tree from traffic light points
        kdtree = o3d.geometry.KDTreeFlann(traffic_light_pcd)

        # Define threshold for point matching (adjust based on point cloud scale)
        threshold = 1e-2

        # Identify points to keep in background (those not close to traffic light points)
        keep_indices = []
        background_points = np.asarray(background_pcd.points)
        for i, point in enumerate(background_points):
            [k, idx, dist] = kdtree.search_knn_vector_3d(point, 1)
            if dist[0] > threshold or ground_mask[i]:  # Keep if no traffic light point is within threshold
                keep_indices.append(i)

        # Filter background point cloud
        filtered_background_pcd = background_pcd.select_by_index(keep_indices)
        print(f"Filtered background points: {len(filtered_background_pcd.points)}")

        # Extract points and colors for saving
        xyz_filtered = np.asarray(filtered_background_pcd.points)
        rgb_filtered = (np.asarray(filtered_background_pcd.colors) * 255).astype(np.uint8) if filtered_background_pcd.has_colors() else np.full((len(xyz_filtered), 3), 255, dtype=np.uint8)

        # Save the updated background point cloud
        storePly(background_ply_path, xyz_filtered, rgb_filtered)
        print(f"Updated {background_ply_path} by removing {len(background_pcd.points) - len(filtered_background_pcd.points)} traffic light points.")

        filtered_ground_mask = ground_mask[keep_indices]
        np.save(self.clip_path / "ground_mask.npy", filtered_ground_mask)

        # remove tfl from background points
        kdtree = o3d.geometry.KDTreeFlann(filtered_background_pcd)
        threshold = 1e-2
        keep_indices = []
        traffic_light_points = np.asarray(traffic_light_pcd.points)
        for i, point in enumerate(traffic_light_points):
            [k, idx, dist] = kdtree.search_knn_vector_3d(point, 1)
            if dist[0] > threshold:
                keep_indices.append(i)
        filtered_traffic_light_pcd = traffic_light_pcd.select_by_index(keep_indices)
        print(f"Filtered traffic light points: {len(filtered_traffic_light_pcd.points)}")
        xyz_filtered_tfl = np.asarray(filtered_traffic_light_pcd.points)
        rgb_filtered_tfl = (np.asarray(filtered_traffic_light_pcd.colors) * 255).astype(np.uint8) if filtered_traffic_light_pcd.has_colors() else np.full((len(xyz_filtered_tfl), 3), 255, dtype=np.uint8)
        storePly(traffic_light_ply_path, xyz_filtered_tfl, rgb_filtered_tfl)

    def fuse_with_voxel_voting(self, views, voxel_size=0.1, min_votes=2):
        """
        Fuse multi-view point clouds using voxel-based voting.

        Args:
            views (list): Each element is a tuple (pts, rgbs), where:
                - pts: (N, 3) array of 3D points (e.g., from depth reprojection)
                - rgbs: (N, 3) array of corresponding RGB colors
            voxel_size (float): Voxel edge length in meters for spatial quantization.
            min_votes (int): Minimum number of distinct views required to retain a voxel.

        Returns:
            clean_pts (torch.Tensor): Fused 3D points of shape (M, 3), on CPU.
            clean_rgbs (torch.Tensor): Corresponding RGB colors of shape (M, 3), on CPU.
        """
        # Dictionary: key = voxel coordinate (tuple), value = list of (point, rgb, view_id)
        voxel_dict = defaultdict(list)

        # Iterate over each view
        for view_id, (pts, rgbs) in enumerate(views):
            if pts is None or len(pts) == 0:
                continue

            # Ensure inputs are NumPy arrays (defensive programming)
            pts = np.asarray(pts)
            rgbs = np.asarray(rgbs)

            # Quantize 3D points into voxel grid coordinates (integer indices)
            voxel_coords = np.round(pts / voxel_size).astype(np.int64)

            # Assign each point to its corresponding voxel
            for i in range(len(pts)):
                pt = pts[i]
                rgb = rgbs[i]
                v_coord = voxel_coords[i]
                key = tuple(v_coord)  # Convert to tuple for use as dict key
                voxel_dict[key].append((pt, rgb, view_id))

        # Voting filter: keep only voxels observed by at least `min_votes` distinct views
        clean_pts, clean_rgbs = [], []
        for key, items in voxel_dict.items():
            # Extract unique view IDs that contributed to this voxel
            unique_views = {item[2] for item in items}
            if len(unique_views) >= min_votes:
                # Retain all points and colors in this voxel
                for pt, rgb, _ in items:
                    clean_pts.append(pt)
                    clean_rgbs.append(rgb)

        # Return empty tensors if no valid points remain
        if not clean_pts:
            return torch.empty(0, 3), torch.empty(0, 3)
        else:
            # Convert to PyTorch tensors (always on CPU)
            return torch.from_numpy(np.stack(clean_pts)), torch.from_numpy(np.stack(clean_rgbs))

    def voxel_downsample(self,points, colors=None, voxel_size=0.005):
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(points)
        if colors is not None:
            pcd.colors = o3d.utility.Vector3dVector(colors / 255.0 if colors.max() > 1 else colors)
        pcd_down = pcd.voxel_down_sample(voxel_size=voxel_size)
        points_down = np.asarray(pcd_down.points)
        colors_down = np.asarray(pcd_down.colors) if colors is not None else None
        return points_down, colors_down

    def extract_traffic_light_points(self, frame, i):
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        # Load traffic light semantic mask
        semantics = get_semantics_from_path(self.clip_path / frame["file_path"].replace("images", "segs"))
        traffic_light_mask_img = 1 - get_mask_from_semantics(semantics, SemanticType.TrafficLight)
        # print(f"Traffic light mask sum: {traffic_light_mask_img.sum()}")
        # print(f"Traffic light mask unique values: {np.unique(traffic_light_mask_img)}")

        # Calculate and print the ratio of traffic light mask pixels to total mask pixels
        total_pixels = traffic_light_mask_img.size
        traffic_light_pixels = traffic_light_mask_img.sum()
        traffic_light_ratio = traffic_light_pixels / total_pixels if total_pixels > 0 else 0
        # print(f"Traffic light mask pixel ratio: {traffic_light_ratio:.4f} ({traffic_light_pixels}/{total_pixels})")

        # Save mask visualization
        output_dir = os.path.join(self.clip_path, 'mask_visualizations')
        os.makedirs(output_dir, exist_ok=True)
        camera_name = frame['camera']
        timestamp = frame['timestamp']
        mask_filename = f'tfl_mask_{camera_name}_{timestamp}.png'
        plt.imsave(os.path.join(output_dir, mask_filename), traffic_light_mask_img, cmap='gray')
        # print(f"Saved traffic light mask to {os.path.join(output_dir, mask_filename)}")

        # Save semantics for debugging
        semantics_filename = 'semantics_frame.png'
        cv2.imwrite(os.path.join(output_dir, semantics_filename), semantics.astype(np.uint8) * 255)
        # print(f"Saved semantics to {os.path.join(output_dir, semantics_filename)}")

        # Check if traffic light mask exists
        if not traffic_light_mask_img.any():
            # print(f"[INFO] No traffic light mask found for frame {frame['file_path']}. Skipping.")
            return

        # Move mask to GPU
        traffic_light_mask = torch.tensor(traffic_light_mask_img, dtype=torch.bool, device=device)

        # Get camera intrinsics and transformation
        intrinsic_matrix, _, _ = get_intrisinc_from_transform(frame)
        intrinsic_matrix = torch.tensor(intrinsic_matrix, dtype=torch.float32, device=device)
        camera2anchor = np.array(frame["transform_matrix"])
        anchor2camera = np.linalg.inv(camera2anchor).astype(np.float32)
        anchor2camera = torch.tensor(anchor2camera, dtype=torch.float32, device=device)

        # Get background point cloud for this frame's timestamp
        timestamp = str(frame["timestamp"])
        if self.cfg.steps_controller.source != "vision":
            if timestamp not in self.lidar_processor.background_pcds:
                # print(f"[WARNING] No background point cloud for timestamp {timestamp}. Skipping.")
                return
            # Move point cloud to GPU
            pcd = self.lidar_processor.background_pcds[timestamp]
            xyz = np.asarray(pcd.points, dtype=np.float32)
            if pcd.has_colors():
                rgbs = np.asarray(pcd.colors, dtype=np.float32) * 255.0  # Assuming colors are in [0,1]
            else:
                rgbs = np.zeros((xyz.shape[0], 3), dtype=np.float32)  # Default to black if no colors
            # print(f"Total points in point cloud: {xyz.shape[0]}")
            xyz = torch.tensor(xyz, dtype=torch.float32, device=device)
            rgbs = torch.tensor(rgbs, dtype=torch.float32, device=device)
            self.xyz = xyz
            self.rgbs = rgbs
        # Add homogeneous coordinates
        ones = torch.ones((self.xyz.shape[0], 1), device=device)
        xyz_hom = torch.cat([self.xyz, ones], dim=1)

        # Transform to camera coordinates
        xyz_in_cam = anchor2camera @ xyz_hom.T
        # print(f"Min Z: {xyz_in_cam[2].min().item()}, Max Z: {xyz_in_cam[2].max().item()}")

        # Filter points in front of the camera (z > 1 and z < 100)
        z_mask = (xyz_in_cam[2] > 1) & (xyz_in_cam[2] < 100)
        xyz_in_cam = xyz_in_cam[:, z_mask]
        # print(f"Points after z_mask: {xyz_in_cam.shape[1]}")

        # Project to image plane
        uv_homogeneous = intrinsic_matrix @ xyz_in_cam
        xy_in_front_2d = uv_homogeneous[:2] / uv_homogeneous[2]
        xy_in_front_2d = torch.round(xy_in_front_2d).to(torch.int32)

        # Filter points within image bounds
        h, w = traffic_light_mask.shape
        in_view_mask = (
            (xy_in_front_2d[0, :] >= 0) & (xy_in_front_2d[0, :] < w) &
            (xy_in_front_2d[1, :] >= 0) & (xy_in_front_2d[1, :] < h)
        )
        xy_in_view_2d = xy_in_front_2d[:, in_view_mask].T
        # print(f"Points within value counts in view: {in_view_mask.sum().item()}")

        # Get corresponding 3D points and colors
        indices_in_z = torch.nonzero(z_mask, as_tuple=False).squeeze(-1)
        indices_in_view = indices_in_z[in_view_mask]
        rgbs_in_view = self.rgbs[indices_in_view]
        xyz_in_view = xyz_in_cam[:3, in_view_mask].T
        # print(f"Points within image bounds: {xyz_in_view.shape[0]}")

        # # Filter points within traffic light mask
        traffic_light_point_mask = traffic_light_mask[xy_in_view_2d[:, 1], xy_in_view_2d[:, 0]]
        traffic_light_points = xyz_in_view[traffic_light_point_mask].cpu().numpy()
        traffic_light_colors = rgbs_in_view[traffic_light_point_mask].cpu().numpy()


        # print(f"Points in traffic light mask: {traffic_light_points.shape[0]}")
        # if traffic_light_points.shape[0] > 0:
        #     print(f"Sample traffic light points (x, y, z): {traffic_light_points[:5]}")
        #     print(f"Sample traffic light colors: {traffic_light_colors[:5]}")
        # else:
        #     print("No traffic light points found.")

        # Convert to global coordinates (assuming anchor frame is global frame)
        traffic_light_points_global = []
        if len(traffic_light_points) > 0:
            camera2global = torch.tensor(camera2anchor, dtype=torch.float32, device=device)
            traffic_light_points_hom = np.hstack([traffic_light_points, np.ones((traffic_light_points.shape[0], 1))])  # Homogeneous coordinates
            traffic_light_points_global = (camera2global @ torch.tensor(traffic_light_points_hom, dtype=torch.float32, device=device).T).T[:, :3].cpu().numpy()
            # print(f"Converted to global coordinates. Sample points: {traffic_light_points_global[:5]}")

        if i == 0:
            self.traffic_light_points_vector=[]
        pts = traffic_light_points_global   # shape: (N, 3)
        rgb = traffic_light_colors     # shape: (N, 3)
        self.traffic_light_points_vector.append((pts, rgb))
        if i == 6:
            pts_clean, rgb_clean = self.fuse_with_voxel_voting(self.traffic_light_points_vector)
            if len(pts_clean):
               # Store extracted points, colors, and pixel ratio
               self.traffic_light_points.append(pts_clean)
               self.traffic_light_rgbs.append(rgb_clean)
               self.traffic_light_ratios.append(traffic_light_ratio)

    def process_all_frames(self):
        """Process all frames and save traffic light points as PLY for top 30 frames by pixel ratio."""
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        # Extract traffic light points from each frame
        i = 0
        for frame in self.transform_json['frames']:
            pos = i % 28
            timestamp = frame['timestamp']
            # print(f'frame = {timestamp}, pos = {pos}')
            i += 1
            if pos <= 6:
               self.extract_traffic_light_points(frame, pos)

        # Select top 30 frames by pixel ratio
        if self.traffic_light_points:
            # Create list of (points, rgbs, ratio) tuples
            frames_data = list(zip(self.traffic_light_points, self.traffic_light_rgbs, self.traffic_light_ratios))
            # Sort by ratio in descending order and select top 30
            # frames_data = sorted(frames_data, key=lambda x: x[2], reverse=True)[:30]
            # Unzip the selected frames
            selected_points, selected_rgbs, _ = zip(*frames_data) if frames_data else ([], [], [])

            # Combine points from selected frames
            all_points = np.vstack(selected_points) if selected_points else np.zeros((0, 3))
            all_rgbs = np.vstack(selected_rgbs) if selected_rgbs else np.zeros((0, 3))

            # Create Open3D point cloud
            pcd = o3d.geometry.PointCloud()
            pcd.points = o3d.utility.Vector3dVector(all_points)
            pcd.colors = o3d.utility.Vector3dVector(all_rgbs / 255.0)  # Normalize colors to [0, 1]

            # # Apply statistical outlier removal
            # pcd_stat, ind_stat = pcd.remove_statistical_outlier(nb_neighbors=20, std_ratio=0.1)
            # print(f"After statistical filtering: {len(pcd_stat.points)} points")

            # # Apply radius outlier removal
            # pcd_filtered, ind_rad = pcd_stat.remove_radius_outlier(nb_points=20, radius=0.2)
            # print(f"After radius filtering: {len(pcd_filtered.points)} points")
            
            pcd_filtered = pcd

            # Save filtered point cloud to PLY file
            if len(pcd_filtered.points) > 0:
                xyz = np.asarray(pcd_filtered.points)
                rgb = np.full((len(xyz), 3), 255, dtype=np.uint8)
                # 检查并转换颜色
                if pcd_filtered.has_colors():
                    rgb = (np.asarray(pcd_filtered.colors) * 255).astype(np.uint8)
                else:
                    # 若无颜色，填充默认值（白色）
                    rgb = np.full((len(xyz), 3), 255, dtype=np.uint8)
                xyz,rgb = self.voxel_downsample(xyz, rgb)
                if len(xyz) < 50:
                    print(f"[INFO] number of points: {len(xyz)}, the number of traffic light points is insufficient. Skipping PLY file creation.")
                else:
                    pointcloud_dir = os.path.join(self.clip_path, 'input_ply')
                    os.makedirs(pointcloud_dir, exist_ok=True)
                    ply_path = os.path.join(pointcloud_dir, 'points3D_tfl.ply')
                    # o3d.io.write_point_cloud(ply_path, pcd_filtered)
                    storePly(ply_path, xyz, rgb)
                    # Remove traffic light points from background and update points3D_bkgd.ply
                    self.remove_traffic_light_from_background()
                    print(f'[INFO] Saved filtered traffic light points to {ply_path}, number of points: {len(xyz)} from {len(selected_points)} frames')
            else:
                print(f"[INFO] No traffic light points found after filtering. Skipping PLY file creation.")
        else:
            print(f"[INFO] No traffic light points found in any frames. Skipping PLY file creation.")


if __name__ == '__main__':
    from settings.config import make_default_settings, make_case_specific_settings
    from lidar_processor import LidarProcessor  # Import LidarProcessor
    parser = argparse.ArgumentParser(description='Traffic Light Point Extractor')
    parser.add_argument(
        '--clip_id',
        type=str,
        default='c-557d5b5e-c037-3945-9dc0-ea1ac93eadc3',
        required=False,
        help='Clip ID'
    )
    args = parser.parse_args()
    cfg = make_default_settings()
    cfg.ips_deploy = False
    cfg.dataset_name = "tfl_test_1_datasets"
    cfg.root = "/workspace/zhangzy30@xiaopeng.com/datasets/reconic_tfl"
    cfg.clip_id = args.clip_id
    cfg.clip_path = '/workspace/zhangzy30@xiaopeng.com/datasets/reconic_tfl'
    cfg = make_case_specific_settings(cfg)
    if cfg.steps_controller.source != "vision":
        lidar_processor = LidarProcessor(cfg)
        lidar_processor.read_all_pcds()  # Populate background_pcds
        extractor = TrafficLightExtractor(cfg, lidar_processor)
        extractor.process_all_frames()
    else:
        extractor = TrafficLightExtractor(cfg)
        extractor.process_all_frames()

