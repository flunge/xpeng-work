#!/usr/bin/env python3
import os
import json
from typing import Dict, List, Optional, Tuple, Set
from scipy.spatial.transform import Rotation as R

import cv2
import numpy as np
from utils_geom import (
    ensure_dir,
    bbox_to_corner3d,
    choose_rotation_matrix,
    get_bound_2d_mask,
    get_bound_2d_mask_fix,
    build_dynamic_camera_index,
    get_random_color_by_gid
)


def load_json(path: str) -> Dict:
    with open(path, "r") as f:
        return json.load(f)


def quaternion_to_rotation_matrix_xyzw(q: np.ndarray) -> np.ndarray:
    # kept for backward compatibility; prefer utils_geom
    from utils_geom import quaternion_to_rotation_matrix_xyzw as _f
    return _f(q)


def quaternion_to_rotation_matrix_wxyz(q: np.ndarray) -> np.ndarray:
    from utils_geom import quaternion_to_rotation_matrix_wxyz as _f
    return _f(q)


def generate_obb_corners(size_lwh: np.ndarray) -> np.ndarray:
    l, w, h = size_lwh.astype(np.float64)
    hl, hw, hh = l / 2.0, w / 2.0, h / 2.0
    corners = np.array(
        [
            [hl, hw, hh],
            [hl, hw, -hh],
            [hl, -hw, hh],
            [hl, -hw, -hh],
            [-hl, hw, hh],
            [-hl, hw, -hh],
            [-hl, -hw, hh],
            [-hl, -hw, -hh],
        ],
        dtype=np.float64,
    )
    return corners


def choose_rotation_matrix(q_arr: List[float], corners_obj: np.ndarray, obj_translation_ego: np.ndarray,
                           R_ego2cam: np.ndarray, t_ego2cam: np.ndarray) -> np.ndarray:
    from utils_geom import choose_rotation_matrix as _c
    return _c(q_arr, corners_obj, obj_translation_ego, R_ego2cam, t_ego2cam)


def project_points_cam_to_image(pts_cam: np.ndarray, K: np.ndarray) -> np.ndarray:
    x = pts_cam[:, 0]
    y = pts_cam[:, 1]
    z = np.maximum(pts_cam[:, 2], 1e-6)
    u = K[0, 0] * (x / z) + K[0, 2]
    v = K[1, 1] * (y / z) + K[1, 2]
    return np.stack([u, v], axis=1)


def polygon_from_projected_corners(uv: np.ndarray, img_w: int, img_h: int) -> Optional[np.ndarray]:
    margin = 10.0
    valid = (uv[:, 0] >= -margin) & (uv[:, 0] <= img_w + margin) & (uv[:, 1] >= -margin) & (uv[:, 1] <= img_h + margin)
    if np.sum(valid) < 3:
        return None
    pts = uv[valid].astype(np.float32)
    pts = pts.reshape(-1, 1, 2)
    hull = cv2.convexHull(pts)
    if hull.shape[0] < 3:
        return None
    return hull.astype(np.int32)


def bbox_to_corner3d(bbox: np.ndarray) -> np.ndarray:
    from utils_geom import bbox_to_corner3d as _b2c
    return _b2c(bbox)


def get_bound_2d_mask(corners_3d: np.ndarray, K: np.ndarray, pose: np.ndarray, H: int, W: int) -> np.ndarray:
    from utils_geom import get_bound_2d_mask as _m
    return _m(corners_3d, K, pose, H, W)


def get_bound_2d_mask_fix(corners_3d: np.ndarray, K: np.ndarray, pose: np.ndarray, H: int, W: int) -> np.ndarray:
    from utils_geom import get_bound_2d_mask_fix as _mf
    return _mf(corners_3d, K, pose, H, W)


def build_dynamic_camera_index(transform_json: Dict) -> Dict[str, Dict[str, Dict]]:
    from utils_geom import build_dynamic_camera_index as _b
    return _b(transform_json)


def draw_poly_aabb_on_image(image_bgr: np.ndarray, poly: np.ndarray, color=(0, 255, 0), thickness=2) -> None:
    x, y, w, h = cv2.boundingRect(poly)
    cv2.rectangle(image_bgr, (x, y), (x + w, y + h), color, thickness)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Debug visualize projected polygon AABBs and save videos.")
    parser.add_argument("--root", type=str, default=os.path.dirname(os.path.abspath(__file__)),
                        help="Dataset root")
    parser.add_argument("--start_idx", type=int, default=0, help="Start frame index (inclusive) in annotation frames")
    parser.add_argument("--end_idx", type=int, default=300, help="End frame index (exclusive) in annotation frames")
    parser.add_argument("--cams", type=str, default="", help="Comma-separated camera ids; empty means all")
    parser.add_argument("--only_gids", type=str, default="", help="Comma-separated gid list to draw; empty means all")
    parser.add_argument("--fps", type=int, default=10, help="FPS for output videos")
    parser.add_argument("--out_dir", type=str, default="debug_vis", help="Output debug directory")
    args = parser.parse_args()

    dataset_root = args.root
    ann = load_json(os.path.join(dataset_root, "annotation_for_train.json"))
    tf = load_json(os.path.join(dataset_root, "transform.json"))
    dyn_index = build_dynamic_camera_index(tf)

    if args.cams:
        cam_ids = [c.strip() for c in args.cams.split(",") if c.strip()]
    else:
        cam_ids = list(tf.get("sensor_params", {}).get("camera_order", []))
        if not cam_ids:
            # fallback by scanning dyn_index
            seen = set()
            for per_ts in dyn_index.values():
                for c in per_ts.keys():
                    seen.add(c)
            cam_ids = sorted(seen)

    only_gids: Optional[Set[int]] = None
    if args.only_gids:
        try:
            only_gids = set(int(x.strip()) for x in args.only_gids.split(",") if x.strip())
        except Exception:
            only_gids = None

    frames: List[Dict] = ann.get("frames", [])
    start_idx = max(0, args.start_idx)
    end_idx = min(len(frames), max(args.start_idx, args.end_idx))

    images_root = os.path.join(dataset_root, "images")
    ensure_dir(os.path.join(dataset_root, args.out_dir))

    # Prepare per-camera frame list for video stitching
    saved_frames_per_cam: Dict[str, List[str]] = {cam: [] for cam in cam_ids}
    target_size_per_cam: Dict[str, Tuple[int, int]] = {}

    for fi in range(start_idx, end_idx):
        frame = frames[fi]
        timestamp = frame.get("timestamp")
        objects = frame.get("objects", [])
        if not timestamp or not objects:
            continue
        ts_key = str(timestamp)

        for cam_id in cam_ids:
            dyn_cam = dyn_index.get(ts_key, {}).get(cam_id)
            if dyn_cam is None:
                continue
            K = dyn_cam["K"]
            R_ego2cam = dyn_cam["R_world2cam"]
            t_ego2cam = dyn_cam["t_world2cam"]
            img_w, img_h = dyn_cam["width"], dyn_cam["height"]

            img_path = os.path.join(images_root, cam_id, f"{timestamp}.png")
            if not os.path.exists(img_path):
                continue
            image_bgr = cv2.imread(img_path, cv2.IMREAD_COLOR)
            if image_bgr is None:
                continue

            # 初始化可视化图像
            vis_img = image_bgr.copy()
            has_any_obj = False

            for obj in objects:
                gid = obj.get("gid")
                if only_gids is not None and gid not in only_gids:
                    continue
                translation = np.array(obj.get("translation", [0, 0, 0]), dtype=np.float64)
                size = np.array(obj.get("size", [0, 0, 0]), dtype=np.float64)
                rotation = obj.get("rotation", [1, 0, 0, 0]) #wxyz
                if gid is None or size.min() <= 0:
                    continue

                # if gid == 47406 or gid == 47172 or gid == 46992 or gid == 46523 or gid == 46510:
                #     q_xyzw = [rotation[1], rotation[2], rotation[3], rotation[0]]
                #     rot = R.from_quat(q_xyzw)
                #     rpy = rot.as_euler('xyz', degrees=True)
                #     print("gid ", gid)
                #     print("rpy ", rpy)

                # build ordered corners in local frame
                l, w_, h_ = size.astype(np.float64)
                bbox_local = np.array([[-l * 0.5, -w_ * 0.5, -h_ * 0.5], [l * 0.5, w_ * 0.5, h_ * 0.5]], dtype=np.float64)
                corners_local = bbox_to_corner3d(bbox_local)
                # rotate to world/ego and translate
                R_obj = choose_rotation_matrix(rotation, corners_local, translation, R_ego2cam, t_ego2cam)
                
                # R_obj = R.from_matrix(R_obj)
                # euler = R_obj.as_euler('xyz', degrees=False)
                # new_euler = [euler[0], 0.0, euler[2]]
                # R_obj = R.from_euler('xyz', new_euler)
                # R_obj = R_obj.as_matrix()

                corners_ego = (R_obj @ corners_local.T).T + translation.reshape(1, 3)
                # world2cam pose
                pose = np.eye(4, dtype=np.float64)
                pose[:3, :3] = R_ego2cam
                pose[:3, 3] = t_ego2cam
                mask = get_bound_2d_mask(corners_ego, K, pose, img_h, img_w)
                if mask.sum() == 0:
                    continue
                if mask.sum() / float(img_w * img_h) > 0.95:
                    mask = get_bound_2d_mask_fix(corners_ego, K, pose, img_h, img_w)
                if mask.sum() == 0:
                    continue

                has_any_obj = True

                # overlay mask on image (green semi-transparent)
                color = np.zeros_like(vis_img)
                # color[:, :, 1] = 255  # green

                random_rgb = get_random_color_by_gid(gid)  # 根据gid生成随机颜色
                color[:, :, 0] = random_rgb[0]  # 红通道
                color[:, :, 1] = random_rgb[1]  # 绿通道
                color[:, :, 2] = random_rgb[2]  # 蓝通道

                alpha = 0.35
                # apply only on mask region
                m = mask.astype(bool)
                vis_img[m] = (vis_img[m].astype(np.float32) * (1 - alpha) + color[m].astype(np.float32) * alpha).astype(np.uint8)

                # Draw gid text on the mask center
                # Get bounding rect of the mask
                contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                if contours:
                    largest_contour = max(contours, key=cv2.contourArea)
                    x, y, w_rect, h_rect = cv2.boundingRect(largest_contour)
                    center_x = x + w_rect // 2
                    center_y = y + h_rect // 2
                    # Draw text
                    cv2.putText(vis_img, str(gid), (center_x - 10, center_y + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

            if not has_any_obj:
                continue

            # quarter resolution (user-adjusted)
            half_img = cv2.resize(vis_img, (img_w // 2, img_h // 2), interpolation=cv2.INTER_AREA)

            cam_out_dir = os.path.join(dataset_root, args.out_dir, cam_id)
            ensure_dir(cam_out_dir)
            out_name = f"frame_{fi:06d}_{timestamp}.png"
            out_path = os.path.join(cam_out_dir, out_name)
            cv2.imwrite(out_path, half_img)
            saved_frames_per_cam[cam_id].append(out_path)
            target_size_per_cam[cam_id] = (half_img.shape[1], half_img.shape[0])  # (w, h)

    # Stitch videos per camera
    for cam_id in cam_ids:
        frames_list = saved_frames_per_cam.get(cam_id, [])
        if not frames_list:
            continue
        w, h = target_size_per_cam[cam_id]
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        video_out_path = os.path.join(dataset_root, args.out_dir, f"{cam_id}_debug.mp4")
        writer = cv2.VideoWriter(video_out_path, fourcc, args.fps, (w, h))
        # 按文件名排序，确保顺序一致
        frames_list.sort()
        for fp in frames_list:
            frame_img = cv2.imread(fp, cv2.IMREAD_COLOR)
            if frame_img is None:
                continue
            if (frame_img.shape[1], frame_img.shape[0]) != (w, h):
                frame_img = cv2.resize(frame_img, (w, h), interpolation=cv2.INTER_AREA)
            writer.write(frame_img)
        writer.release()
        print(f"Saved video: {video_out_path}")


if __name__ == "__main__":
    main()