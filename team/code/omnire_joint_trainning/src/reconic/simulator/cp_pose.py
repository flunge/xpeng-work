"""CP simulation pose helpers for novel-view rendering."""

from __future__ import annotations

import numpy as np


def refine_rig_z_from_neighbors(
    rig2anchor: np.ndarray,
    train_localpose_kdtree,
    train_localpose_list,
    k: int = 3,
) -> np.ndarray:
    """Refine rig z using weighted average of k nearest training poses."""
    nearest_idx = train_localpose_kdtree.query(rig2anchor[:3, 3], k=k)
    neighbor_poses = [train_localpose_list[idx] for idx in nearest_idx[1]]
    z_values = [pose[2, 3] for pose in neighbor_poses]
    weights = 1 / (nearest_idx[0] + 1e-8)
    rig2anchor = rig2anchor.copy()
    rig2anchor[2, 3] = np.sum(np.array(z_values) * weights) / np.sum(weights)
    return rig2anchor


def compute_rig2anchor(
    timestamp_sim: int,
    rig2world: np.ndarray,
    *,
    cp_simulation: bool,
    anchor_pose: np.ndarray,
    dds_localpose_kdtree,
    dds_localpose_list,
    train_localpose_kdtree,
    train_localpose_list,
) -> np.ndarray:
    if not cp_simulation:
        return np.linalg.inv(anchor_pose) @ rig2world

    print(f"[3DGS_INFO] Using anchor pose from transferpose_index for timestamp {timestamp_sim}")
    sim_car_position = rig2world[:3, 3]
    nearest_idx = dds_localpose_kdtree.query(sim_car_position)[1]
    nearest_real_car_pose = dds_localpose_list[nearest_idx]
    dist = np.linalg.norm(nearest_real_car_pose[:2, 3] - rig2world[:2, 3])
    print(f"[3DGS_INFO] timestamp: {timestamp_sim}, distance with real car and sim car: {dist}")

    rig2anchor = np.linalg.inv(anchor_pose) @ rig2world
    z_before = rig2anchor[2, 3]
    rig2anchor = refine_rig_z_from_neighbors(
        rig2anchor, train_localpose_kdtree, train_localpose_list
    )
    print(
        f"[3DGS_INFO] timestamp: {timestamp_sim}, "
        f"estimated diff in z: {rig2anchor[2, 3] - z_before}"
    )
    return rig2anchor
