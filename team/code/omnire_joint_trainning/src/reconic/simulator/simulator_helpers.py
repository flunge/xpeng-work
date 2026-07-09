"""Small helpers used by ReconicSimulator and closed-loop entrypoints."""

from __future__ import annotations

import os

import numpy as np
import torch
from scipy.spatial.transform import Rotation as R


def resolve_config_path(args, init_from_fastmode: bool, init_from_feedforward: bool) -> str:
    if init_from_fastmode:
        return args
    if init_from_feedforward:
        from reconic.training_loop import GenerativeReconTrainingLoop

        model_folder = os.path.join(args.output_root, args.project, args.run_name)
        config_path = os.path.join(model_folder, "configs", "config_sim.yaml")
        instance_dict_pt_path = os.path.join(model_folder, "RigidNodes_instance_dict.pt")
        if not os.path.exists(config_path) or not os.path.exists(instance_dict_pt_path):
            GenerativeReconTrainingLoop(args)
        return config_path
    return args


def build_ego_pose_world(ego_pose_arr) -> np.ndarray:
    """Convert [qw, qx, qy, qz, tx, ty, tz] array to 4x4 world pose."""
    q = ego_pose_arr[:4]
    t = ego_pose_arr[4:7]
    rotation_matrix = R.from_quat([q[1], q[2], q[3], q[0]]).as_matrix()
    ego_pose_world = np.eye(4, dtype=np.float64)
    ego_pose_world[:3, :3] = rotation_matrix
    ego_pose_world[:3, 3] = t
    return ego_pose_world


def to8b(x):
    if isinstance(x, torch.Tensor):
        x = x.detach().cpu().numpy()
    return (255 * np.clip(x, 0, 1)).astype(np.uint8)


def numpy_array_to_bytes(image_array: np.ndarray) -> bytes:
    if image_array.dtype != np.uint8:
        image_array = image_array.astype(np.uint8)
    return image_array.tobytes()
