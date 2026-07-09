#!/usr/bin/env python3
import os
from typing import Dict, List, Tuple, Optional

import cv2
import numpy as np

def get_random_color_by_gid(gid):
    RAINBOW_COLORS = [
        (0, 0, 255),    # 红 (Red)
        (0, 165, 255),  # 橙 (Orange)
        (0, 255, 255),  # 黄 (Yellow)
        (0, 255, 0),    # 绿 (Green)
        (255, 0, 0),    # 蓝 (Blue)
        (130, 0, 75),   # 靛 (Indigo)
        (128, 0, 128)   # 紫 (Purple)
    ]
    return RAINBOW_COLORS[gid % len(RAINBOW_COLORS)]

def ensure_dir(path: str) -> None:
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def quaternion_to_rotation_matrix_xyzw(q: np.ndarray) -> np.ndarray:
    # q = [x, y, z, w]
    x, y, z, w = q
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    R = np.array(
        [
            [1 - 2 * (yy + zz), 2 * (xy - wz), 2 * (xz + wy)],
            [2 * (xy + wz), 1 - 2 * (xx + zz), 2 * (yz - wx)],
            [2 * (xz - wy), 2 * (yz + wx), 1 - 2 * (xx + yy)],
        ],
        dtype=np.float64,
    )
    return R


def quaternion_to_rotation_matrix_wxyz(q: np.ndarray) -> np.ndarray:
    # q = [w, x, y, z]
    w, x, y, z = q
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    R = np.array(
        [
            [1 - 2 * (yy + zz), 2 * (xy - wz), 2 * (xz + wy)],
            [2 * (xy + wz), 1 - 2 * (xx + zz), 2 * (yz - wx)],
            [2 * (xz - wy), 2 * (yz + wx), 1 - 2 * (xx + yy)],
        ],
        dtype=np.float64,
    )
    return R


def choose_rotation_matrix(q_arr: List[float], corners_obj: np.ndarray, obj_translation_ego: np.ndarray,
                           R_ego2cam: np.ndarray, t_ego2cam: np.ndarray) -> np.ndarray:
    """
    在两种四元数排列 ([x,y,z,w] 与 [w,x,y,z]) 中选择使更多角点在相机前方(z>0)的旋转。
    """
    q = np.array(q_arr, dtype=np.float64)
    R2 = quaternion_to_rotation_matrix_wxyz(q)
    return R2


def bbox_to_corner3d(bbox: np.ndarray) -> np.ndarray:
    """
    bbox: [[-l,-w,-h],[l,w,h]] (min,max) in local frame
    返回按面填充顺序组织的8个角点:
    0:(x1,y1,z1), 1:(x2,y1,z1), 2:(x1,y2,z1), 3:(x2,y2,z1),
    4:(x1,y1,z2), 5:(x2,y1,z2), 6:(x1,y2,z2), 7:(x2,y2,z2)
    """
    x1, y1, z1 = bbox[0]
    x2, y2, z2 = bbox[1]
    corners = np.array(
        [
            [x1, y1, z1],
            [x2, y1, z1],
            [x1, y2, z1],
            [x2, y2, z1],
            [x1, y1, z2],
            [x2, y1, z2],
            [x1, y2, z2],
            [x2, y2, z2],
        ],
        dtype=np.float64,
    )
    return corners


def get_bound_2d_mask(corners_3d: np.ndarray, K: np.ndarray, pose: np.ndarray, H: int, W: int) -> np.ndarray:
    """
    使用六个面的投影生成2D掩膜
    pose: (4,4) world2cam
    """
    R = pose[:3, :3]
    t = pose[:3, 3]
    cam_pts = corners_3d @ R.T + t.reshape(1, 3)
    if np.all(cam_pts[:, 2] <= 0):
        return np.zeros((H, W), dtype=np.uint8)
    cam_pts[:, 2] = np.clip(cam_pts[:, 2], 1e-3, None)
    proj = cam_pts @ K.T
    uv = proj[:, :2] / proj[:, 2:]
    uv = np.round(uv).astype(np.int32)
    mask = np.zeros((H, W), dtype=np.uint8)
    faces = [
        [0, 1, 3, 2, 0],
        [4, 5, 7, 6, 5],
        [0, 1, 5, 4, 0],
        [2, 3, 7, 6, 2],
        [0, 2, 6, 4, 0],
        [1, 3, 7, 5, 1],
    ]
    for f in faces:
        poly = uv[f]
        cv2.fillPoly(mask, [poly], 1)
    return mask


def get_bound_2d_mask_fix(corners_3d: np.ndarray, K: np.ndarray, pose: np.ndarray, H: int, W: int) -> np.ndarray:
    """
    退化情况兜底：用角点凸包生成掩膜
    """
    R = pose[:3, :3]
    t = pose[:3, 3]
    cam_pts = corners_3d @ R.T + t.reshape(1, 3)
    if np.all(cam_pts[:, 2] <= 0):
        return np.zeros((H, W), dtype=np.uint8)
    cam_pts[:, 2] = np.clip(cam_pts[:, 2], 1e-3, None)
    proj = cam_pts @ K.T
    uv = proj[:, :2] / proj[:, 2:]
    uv = np.round(uv).astype(np.int32)
    mask = np.zeros((H, W), dtype=np.uint8)
    pts = uv.reshape(-1, 1, 2)
    hull = cv2.convexHull(pts)
    cv2.fillConvexPoly(mask, hull, 1)
    return mask


def build_dynamic_camera_index(transform_json: Dict) -> Dict[str, Dict[str, Dict]]:
    """
    建立 timestamp+camera 的动态索引，返回K、R_world2cam、t_world2cam、分辨率
    """
    idx: Dict[str, Dict[str, Dict]] = {}
    frames = transform_json.get("frames", [])
    for f in frames:
        ts = f.get("timestamp")
        cam_id = f.get("camera")
        if ts is None or not cam_id:
            continue
        ts_str = str(ts)
        T = np.array(f.get("transform_matrix", np.eye(4)), dtype=np.float64)
        R_cw = T[:3, :3]
        t_cw = T[:3, 3]
        R_world2cam = R_cw.T
        t_world2cam = -R_cw.T @ t_cw
        fl_x = float(f.get("fl_x", 0.0))
        fl_y = float(f.get("fl_y", 0.0))
        cx = float(f.get("cx", 0.0))
        cy = float(f.get("cy", 0.0))
        K = np.array([[fl_x, 0.0, cx], [0.0, fl_y, cy], [0.0, 0.0, 1.0]], dtype=np.float64)
        w = int(f.get("w", 0))
        h = int(f.get("h", 0))
        if ts_str not in idx:
            idx[ts_str] = {}
        idx[ts_str][cam_id] = {
            "K": K,
            "R_world2cam": R_world2cam,
            "t_world2cam": t_world2cam,
            "width": w,
            "height": h,
        }
    return idx


