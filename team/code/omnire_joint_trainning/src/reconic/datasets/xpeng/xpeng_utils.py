import os
import json
import math
import torch
from pathlib import Path
from typing import List, NamedTuple

import cv2
import numpy as np
from numpy import ndarray as NDArray
from PIL import Image
from plyfile import PlyData, PlyElement

from .constants import DATASET_CLASSES_IN_SEMANTIC, SemanticType

_EPS = np.finfo(float).eps * 4.0


class BasicPointCloud(NamedTuple):
    points: np.array
    colors: np.array
    normals: np.array

    def __len__(self):
        return len(self.points)

    def __getitem__(self, idx):
        return BasicPointCloud(points=self.points[idx], colors=self.colors[idx], normals=self.normals[idx])

    def downsample(self, voxel_size):
        import open3d as o3d

        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(self.points)
        pcd.colors = o3d.utility.Vector3dVector(self.colors)
        pcd.normals = o3d.utility.Vector3dVector(self.normals)
        pcd = pcd.voxel_down_sample(voxel_size=voxel_size)
        positions = np.asarray(pcd.points)
        colors = np.asarray(pcd.colors)
        normals = np.asarray(pcd.normals)
        return BasicPointCloud(points=positions, colors=colors, normals=normals)


def fetchPly(path):
    plydata = PlyData.read(path)
    vertices = plydata["vertex"]
    positions = np.vstack([vertices["x"], vertices["y"], vertices["z"]]).T
    colors = np.vstack([vertices["red"], vertices["green"], vertices["blue"]]).T / 255.0
    normals = np.vstack([vertices["nx"], vertices["ny"], vertices["nz"]]).T
    return BasicPointCloud(points=positions, colors=colors, normals=normals)


def get_mask_from_semantics(semantics, mask_indices):
    if isinstance(mask_indices, List):
        mask_indices = np.array(mask_indices, dtype=np.int64).reshape(-1)
    mask = np.isin(semantics, mask_indices)
    return mask


def get_semantics_from_path(filepath: Path, scale_factor: float = 1.0):
    pil_image = Image.open(filepath)
    if scale_factor != 1.0:
        width, height = pil_image.size
        newsize = (int(width * scale_factor), int(height * scale_factor))
        pil_image = pil_image.resize(newsize, resample=Image.NEAREST)
    image = np.array(pil_image, dtype="int64")
    if len(image.shape) == 3:
        image = image[:, :, 0]

    class_to_label = {
        SemanticType.VEHICLE.value: DATASET_CLASSES_IN_SEMANTIC["VEHICLE"],
        SemanticType.HUMAN.value: DATASET_CLASSES_IN_SEMANTIC["HUMAN"],
        SemanticType.GROUND.value: DATASET_CLASSES_IN_SEMANTIC["GROUND"],
        SemanticType.SKY.value: DATASET_CLASSES_IN_SEMANTIC["SKY"],
        SemanticType.TRAFFICLIGHT.value: DATASET_CLASSES_IN_SEMANTIC["TRAFFICLIGHT"],
    }
    semantics = np.zeros_like(image)
    for label, class_ids in class_to_label.items():
        semantics[np.isin(image, class_ids)] = label

    semantics = np.expand_dims(semantics, axis=-1)
    return semantics


def quaternion_matrix(quaternion: NDArray) -> np.ndarray:
    """Return homogeneous rotation matrix from quaternion.

    Args:
        quaternion: value to convert to matrix
    """
    q = np.array(quaternion, dtype=np.float64, copy=True)
    n = np.dot(q, q)
    if n < _EPS:
        return np.identity(4)
    q *= math.sqrt(2.0 / n)
    q = np.outer(q, q)
    return np.array(
        [
            [1.0 - q[2, 2] - q[3, 3], q[1, 2] - q[3, 0], q[1, 3] + q[2, 0], 0.0],
            [q[1, 2] + q[3, 0], 1.0 - q[1, 1] - q[3, 3], q[2, 3] - q[1, 0], 0.0],
            [q[1, 3] - q[2, 0], q[2, 3] + q[1, 0], 1.0 - q[1, 1] - q[2, 2], 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )


def load_xpeng_obj_points(obj_gid, obj_pcd_path):
    try:
        obj_pcd = fetchPly(obj_pcd_path)
        if obj_pcd.points.shape[0] < 2000:
            raise FileNotFoundError
    except FileNotFoundError:
        print(f"[INFO] Object {obj_gid} point cloud not found, generating random points")
        points, colors = None, None
    else:
        points, colors = obj_pcd.points, obj_pcd.colors
    return points, colors


def get_bound_2d_mask(corners_3d, K, pose, H, W):
    corners_3d = np.dot(corners_3d, pose[:3, :3].T) + pose[:3, 3:].T
    if np.all(corners_3d[..., 2] <= 0):
        return np.zeros((H, W), dtype=np.uint8)
    corners_3d[..., 2] = np.clip(corners_3d[..., 2], a_min=1e-3, a_max=None)
    corners_3d = np.dot(corners_3d, K.T)
    corners_2d = corners_3d[:, :2] / corners_3d[:, 2:]
    corners_2d = np.round(corners_2d).astype(np.int32)
    mask = np.zeros((H, W), dtype=np.uint8)
    cv2.fillPoly(mask, [corners_2d[[0, 1, 3, 2, 0]]], 1)
    cv2.fillPoly(mask, [corners_2d[[4, 5, 7, 6, 5]]], 1)
    cv2.fillPoly(mask, [corners_2d[[0, 1, 5, 4, 0]]], 1)
    cv2.fillPoly(mask, [corners_2d[[2, 3, 7, 6, 2]]], 1)
    cv2.fillPoly(mask, [corners_2d[[0, 2, 6, 4, 0]]], 1)
    cv2.fillPoly(mask, [corners_2d[[1, 3, 7, 5, 1]]], 1)
    return mask


def get_bound_2d_mask_fix(corners_3d, K, pose, H, W):
    corners_3d = np.dot(corners_3d, pose[:3, :3].T) + pose[:3, 3:].T
    # Filter out points with negative or zero z-coordinates
    valid_indices = np.where(corners_3d[:, 2] > 0)[0]
    corners_3d = corners_3d[valid_indices]
    corners_3d[..., 2] = np.clip(corners_3d[..., 2], a_min=1e-3, a_max=None)
    corners_3d = np.dot(corners_3d, K.T)
    corners_2d = corners_3d[:, :2] / corners_3d[:, 2:]
    corners_2d = np.round(corners_2d).astype(np.int32)
    mask = np.zeros((H, W), dtype=np.uint8)
    if len(corners_2d) >= 4:
        all_faces = [
            [0, 1, 3, 2, 0],
            [4, 5, 7, 6, 5],
            [0, 1, 5, 4, 0],
            [2, 3, 7, 6, 2],
            [0, 2, 6, 4, 0],
            [1, 3, 7, 5, 1],
        ]
        for face in all_faces:
            if set(face).issubset(valid_indices):
                query_idx = [np.where(idx == valid_indices)[0][0] for idx in face]
                cv2.fillPoly(mask, [corners_2d[query_idx]], 1)
    return mask


def scale_to_corrner(scale):
    min_x, min_y, min_z = -scale, -scale, -scale
    max_x, max_y, max_z = scale, scale, scale
    corner3d = np.array(
        [
            [min_x, min_y, min_z],
            [min_x, min_y, max_z],
            [min_x, max_y, min_z],
            [min_x, max_y, max_z],
            [max_x, min_y, min_z],
            [max_x, min_y, max_z],
            [max_x, max_y, min_z],
            [max_x, max_y, max_z],
        ]
    )
    return corner3d


def bbox_to_corner3d(bbox):
    min_x, min_y, min_z = bbox[0]
    max_x, max_y, max_z = bbox[1]

    corner3d = np.array(
        [
            [min_x, min_y, min_z],
            [min_x, min_y, max_z],
            [min_x, max_y, min_z],
            [min_x, max_y, max_z],
            [max_x, min_y, min_z],
            [max_x, min_y, max_z],
            [max_x, max_y, min_z],
            [max_x, max_y, max_z],
        ]
    )
    return corner3d


def points_to_bbox(points):
    min_xyz = np.min(points, axis=0)
    max_xyz = np.max(points, axis=0)
    bbox = np.array([min_xyz, max_xyz])
    return bbox


def inbbox_points(points, corner3d):
    min_xyz = corner3d[0]
    max_xyz = corner3d[-1]
    return np.logical_and(np.all(points >= min_xyz, axis=-1), np.all(points <= max_xyz, axis=-1))


def construct_list_of_attributes():
    l = ['x', 'y', 'z', 'nx', 'ny', 'nz']
    # All channels except the 3 DC
    for i in range(3):
        l.append('f_dc_{}'.format(i))
    for i in range(9):
        l.append('f_rest_{}'.format(i))
    l.append('opacity')
    for i in range(3):
        l.append('scale_{}'.format(i))
    for i in range(4):
        l.append('rot_{}'.format(i))
    return l


def rescale_points(points, bounding_box, device):
    min_orig = np.min(points, axis=0)
    max_orig = np.max(points, axis=0)
    size_orig_x = max_orig[0] - min_orig[0]
    size_orig_y = max_orig[1] - min_orig[1]
    size_orig_z = max_orig[2] - min_orig[2]

    target_length, target_width, target_height = bounding_box
    scale_x = target_width / size_orig_x
    scale_y = target_length / size_orig_y
    scale_z = target_height / size_orig_z
    scale_factors = np.array([scale_x, scale_y, scale_z])

    center_orig = (min_orig + max_orig) / 2.0
    points_centered = points - center_orig
    points_scaled = points_centered * scale_factors
    points_scaled[:, [0, 1]] = points_scaled[:, [1, 0]]
    points_scaled[:, 0] = -1 * points_scaled[:, 0]

    fixed_rot = torch.tensor([
        [0., 1., 0.],
        [-1., 0., 0.],
        [0., 0., 1.]
    ], dtype=torch.float, device=device)
    return points_scaled, np.array([scale_y, scale_x, scale_z]), fixed_rot

def make_vis_ply(xyz, opacities, scales, rots, rgb):
    xyz = xyz.detach().cpu().numpy()
    normals = np.zeros_like(xyz)

    fused_color = (rgb.detach() - 0.5) / 0.28209479177387814
    max_sh_degree = 1
    features = torch.zeros((fused_color.shape[0], 3, (max_sh_degree + 1) ** 2)).float()
    features[..., 0] = fused_color
    f_dc = features[:, :, 0:1].transpose(1, 2).contiguous()
    f_rest = features[:, :, 1:].transpose(1, 2).contiguous()
    f_dc = f_dc.transpose(1, 2).flatten(start_dim=1).contiguous()
    f_rest = f_rest.transpose(1, 2).flatten(start_dim=1).contiguous()

    opacities = opacities.detach().cpu().numpy()
    opacities = opacities.reshape(-1, 1)
    scales = scales.detach().cpu().numpy()
    rotation = rots.detach().cpu().numpy()
    semamtics = np.zeros((xyz.shape[0], 0))

    dtype_full = [(attribute, 'f4') for attribute in construct_list_of_attributes()]
    attributes = np.concatenate((xyz, normals, f_dc, f_rest, opacities, scales, rotation, semamtics), axis=1)

    elements = np.empty(xyz.shape[0], dtype=dtype_full)
    elements[:] = list(map(tuple, attributes))
    return elements

def save_vis_gaussians(xyz, opacities, scales, rots, rgb, save_path):
    plydata = make_vis_ply(xyz, opacities, scales, rots, rgb)
    plydata = PlyElement.describe(plydata, 'vertex')
    plydata_list = [plydata]
    PlyData(plydata_list).write(save_path)
    return

def extract_static_ids(static_id_json):
    if not os.path.exists(static_id_json):
        return []

    with open(static_id_json, 'r') as f:
        data = json.load(f)

    all_ids = []
    for cam_list in data.values():
        all_ids.extend([int(id_str) for id_str in cam_list])

    unique_ids = sorted(list(set(all_ids)))
    return unique_ids