import os

import numpy as np
from scipy.spatial import cKDTree
import open3d as o3d


def merge_ground_ply(base_pcd: o3d.geometry.PointCloud,
                     extra_pcd: o3d.geometry.PointCloud,
                     threshold: float = 0.1) -> o3d.geometry.PointCloud:
    """
    将两个地面点云进行合并。
    以 base_pcd 作为基准，仅保留 extra_pcd 中在 XY 平面上
    与 base_pcd 最近点距离大于 threshold 的点。

    Args:
        base_pcd: 作为基准的点云（Open3D PointCloud）
        extra_pcd: 需要合并到基准点云上的点云
        threshold: 水平距离阈值（单位：米），默认 0.1m

    Returns:
        合并后的点云（Open3D PointCloud）
    """
    # 基本健壮性检查
    if base_pcd is None or len(base_pcd.points) == 0:
        return extra_pcd
    if extra_pcd is None or len(extra_pcd.points) == 0:
        return base_pcd

    base_points = np.asarray(base_pcd.points)
    extra_points = np.asarray(extra_pcd.points)

    if base_points.size == 0:
        return extra_pcd
    if extra_points.size == 0:
        return base_pcd

    # 仅使用 XY 平面坐标构建 KDTree（用 SciPy cKDTree，更适合百万级点）
    base_xy = base_points[:, :2]
    extra_xy = extra_points[:, :2]

    tree = cKDTree(base_xy)
    # query 返回最近邻距离（单位：米）；部分 SciPy 版本不支持 n_jobs 参数，这里不指定
    dists, _ = tree.query(extra_xy, k=1)

    keep_mask = dists > float(threshold)

    # 如果没有额外点需要保留，直接返回基准点云
    if not np.any(keep_mask):
        return base_pcd

    merged_points = np.vstack([base_points, extra_points[keep_mask]])

    merged_pcd = o3d.geometry.PointCloud()
    merged_pcd.points = o3d.utility.Vector3dVector(merged_points)

    # 合并颜色信息（如存在）
    has_base_color = base_pcd.has_colors()
    has_extra_color = extra_pcd.has_colors()
    if has_base_color or has_extra_color:
        # 统一颜色数组形状
        if has_base_color:
            base_colors = np.asarray(base_pcd.colors)
        else:
            base_colors = np.zeros((len(base_points), 3), dtype=np.float32)

        if has_extra_color:
            extra_colors = np.asarray(extra_pcd.colors)
        else:
            extra_colors = np.zeros((len(extra_points), 3), dtype=np.float32)

        merged_colors = np.vstack([base_colors, extra_colors[keep_mask]])
        merged_pcd.colors = o3d.utility.Vector3dVector(merged_colors)

    return merged_pcd


def segment_road_points_local_fast(point_cloud, trajectory, window_size=10, dist_threshold=10.0, ransac_thresh=0.2,
                                   min_samples=50, n_iterations=30, z_filter=True, debug_save_dir=None):
    """
    Split ground points from point cloud using local RANSAC plane fitting along the vehicle trajectory.

    Args:
    - point_cloud: o3d.geometry.PointCloud, input point cloud object
    - trajectory: np.ndarray, shape (M, 3), ego trajectory [x, y, z] points sorted by time
    - window_size: int, number of trajectory points in sliding window, default 10 (~10-20m)
    - dist_threshold: float, distance threshold (meters) for points to trajectory segments, default 5m
    - ransac_thresh: float, RANSAC inlier distance threshold (meters), default 0.2m
    - min_samples: int, minimum number of candidate points per window, default 50
    - n_iterations: int, number of RANSAC iterations per window, default 30 (reduce to speed up)
    - z_filter: bool, whether to apply z-axis filtering based on trajectory height, default True
    - debug_save_dir: str or None, if provided, saves debug point clouds to this directory

    Returns:
    - np.ndarray, shape (K, 3), K is the number of road points; returns empty array if failed.
    """
    cloud_points = np.array(point_cloud.points).astype(np.float32)
    cloud_colors = np.array(point_cloud.colors).astype(np.float32) * 255

    if len(cloud_points) == 0 or len(trajectory) == 0 or window_size < 3:
        return np.array([]), np.array([])

    # Global pre-filtering: xy distance
    full_tree = cKDTree(trajectory[:, :2])
    dists_to_traj, traj_indices = full_tree.query(cloud_points[:, :2])
    close_global_mask = dists_to_traj < dist_threshold
    if not np.any(close_global_mask):
        return np.array([]), np.array([])

    close_points_global = cloud_points[close_global_mask]
    close_colors_global = cloud_colors[close_global_mask]
    traj_indices_global = traj_indices[close_global_mask]
    global_close_indices = np.where(close_global_mask)[0]  # backup global indices

    road_points = np.array([])
    road_colors = np.array([])
    step = window_size // 3

    # Debug initialization
    window_count = 0
    if debug_save_dir is not None:
        os.makedirs(debug_save_dir, exist_ok=True)
        print(f"Debug mode enabled: First 5 window data will be saved to {debug_save_dir}")

    # Sliding window along the trajectory
    for i in range(0, len(trajectory) - window_size + 1, step):
        # Assign current window points
        window_mask = (traj_indices_global >= i) & (traj_indices_global < i + window_size)
        if not np.any(window_mask):
            continue
        close_points = close_points_global[window_mask]
        close_colors = close_colors_global[window_mask]
        if len(close_points) < min_samples:
            continue

        # Get current window trajectory (for z-filtering + debugging)
        window_traj = trajectory[i:i + window_size]
        if debug_save_dir is not None:
            pcd_traj = o3d.geometry.PointCloud()
            pcd_traj.points = o3d.utility.Vector3dVector(window_traj)
            pcd_traj.paint_uniform_color([0.0, 1.0, 1.0])  # cyan
            o3d.io.write_point_cloud(os.path.join(debug_save_dir, f'wind_traj_{window_count}.ply'), pcd_traj)

        # z-axis pre-filtering (if enabled)
        filtered_close_points = close_points
        window_global_indices = global_close_indices[window_mask]  # key: backup window global indices
        if z_filter:
            window_traj_z_mean = np.mean(window_traj[:, 2])
            z_mask = np.abs(close_points[:, 2] - window_traj_z_mean) < 1.0  # ±1m
            filtered_close_points = close_points[z_mask]
            filtered_close_colors = close_colors[z_mask]
            # Backtrack: use z_mask to filter window global indices (to avoid dimension mismatch)
            filtered_global_indices = window_global_indices[z_mask]
            if len(filtered_close_points) < min_samples:
                print(f"Window {i}: z-filtered points insufficient {min_samples}, skipping")
                window_count += 1
                continue

            # Debug: Save z-filtered points (orange)
            if debug_save_dir is not None:
                pcd_filtered = o3d.geometry.PointCloud()
                pcd_filtered.points = o3d.utility.Vector3dVector(filtered_close_points)
                pcd_filtered.colors = o3d.utility.Vector3dVector(filtered_close_colors / 255.0)
                o3d.io.write_point_cloud(os.path.join(debug_save_dir, f'filt_close_wind_{window_count}.ply'), pcd_filtered)
                print(f"  -> save filt_close_wind_{window_count}.ply ({len(filtered_close_points)} points, "
                      f"z range: {np.min(filtered_close_points[:,2]):.2f} ~ {np.max(filtered_close_points[:,2]):.2f})")

        # Debug: Save original close_points (light blue, only first 5)
        if debug_save_dir is not None:
            pcd_close = o3d.geometry.PointCloud()
            pcd_close.points = o3d.utility.Vector3dVector(close_points)
            pcd_close.colors = o3d.utility.Vector3dVector(close_colors / 255.0)
            o3d.io.write_point_cloud(os.path.join(debug_save_dir, f'close_points_window_{window_count}.ply'), pcd_close)
            print(f"Window {i}: saved close_points_window_{window_count}.ply ({len(close_points)} points, "
                  f"z range: {np.min(close_points[:,2]):.2f} ~ {np.max(close_points[:,2]):.2f})")

        # RANSAC filtered_close_points
        best_inliers = 0
        best_model = None
        for _ in range(n_iterations):
            if len(filtered_close_points) < 3:
                break
            idx = np.random.choice(len(filtered_close_points), 3, replace=False)
            pts = filtered_close_points[idx]
            A = np.c_[pts[:, 0], pts[:, 1], np.ones(3)]
            params, _, _, _ = np.linalg.lstsq(A, pts[:, 2], rcond=None)
            a, b, c = params

            pred_z = a * filtered_close_points[:, 0] + b * filtered_close_points[:, 1] + c
            residuals = np.abs(filtered_close_points[:, 2] - pred_z) / np.sqrt(a**2 + b**2 + 1)
            inliers_count = np.sum(residuals < ransac_thresh)

            if inliers_count > best_inliers:
                best_inliers = inliers_count
                best_model = (a, b, c)

        if best_model is None:
            print(f"window {i}: RANSAC failed, skipping")
            window_count += 1
            continue

        a, b, c = best_model

        # Extract local road points
        pred_z_filtered = a * filtered_close_points[:, 0] + b * filtered_close_points[:, 1] + c
        residuals_filtered = np.abs(filtered_close_points[:, 2] - pred_z_filtered) / np.sqrt(a**2 + b**2 + 1)
        local_submask = residuals_filtered < ransac_thresh

        # Key fix: backtrack using filtered_global_indices[local_submask] (dimension matching)
        local_indices_global = filtered_global_indices[local_submask] if z_filter else global_close_indices[window_mask][local_submask]
        local_road = cloud_points[local_indices_global]
        local_color = cloud_colors[local_indices_global]

        # Merge
        if len(road_points) == 0:
            road_points = local_road
            road_colors = local_color
        else:
            road_points = np.vstack([road_points, local_road])
            road_colors = np.vstack([road_colors, local_color])

        # Debug: Save local_road (red, only first 5)
        if debug_save_dir is not None:
            pcd_road = o3d.geometry.PointCloud()
            pcd_road.points = o3d.utility.Vector3dVector(local_road)
            pcd_road.colors = o3d.utility.Vector3dVector(local_color / 255.0)
            o3d.io.write_point_cloud(os.path.join(debug_save_dir, f'local_road_window_{window_count}.ply'), pcd_road)
            print(f"  -> save local_road_window_{window_count}.ply ({len(local_road)} points, "
                  f"z range: {np.min(local_road[:,2]):.2f} ~ {np.max(local_road[:,2]):.2f})")

        window_count += 1

    if len(road_points) > 1:
        _, unique_idx = np.unique(np.round(road_points, decimals=1), axis=0, return_index=True)  # 精确到0.1m
        road_points = road_points[unique_idx]
        road_colors = road_colors[unique_idx]

    # Post-process z-filtering (if enabled)
    if z_filter and len(road_points) > 0:
        full_tree_road = cKDTree(trajectory[:, :2])
        _, closest_idx = full_tree_road.query(road_points[:, :2])
        closest_traj_z = trajectory[closest_idx, 2]
        z_dev_mask = np.abs(road_points[:, 2] - closest_traj_z) < 0.5  # <0.5m
        removed_count = len(road_points) - np.sum(z_dev_mask)
        road_points = road_points[z_dev_mask]
        road_colors = road_colors[z_dev_mask]
        print(f"Post-process z-filtering: removed {removed_count} high-deviation points, remaining {len(road_points)}")

    num_windows = (len(trajectory) - window_size) // step + 1
    print(f"total ground points num: {len(road_points)} / {len(cloud_points)} (windows: {num_windows})")

    # Debug: Save total road points
    if debug_save_dir is not None:
        pcd_total_road = o3d.geometry.PointCloud()
        pcd_total_road.points = o3d.utility.Vector3dVector(road_points)
        pcd_total_road.colors = o3d.utility.Vector3dVector(road_colors / 255.0)
        o3d.io.write_point_cloud(os.path.join(debug_save_dir, 'total_road_points.ply'), pcd_total_road)
        print(f"Debug done: total road points saved to total_road_points.ply ({len(road_points)} points)")

    return road_points, road_colors