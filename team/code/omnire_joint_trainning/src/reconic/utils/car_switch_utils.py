import copy
import sys
import os
import numpy as np
from scipy.spatial.transform import Rotation, Slerp


def _pose_msg_to_matrix(pose_msg):
    p = pose_msg["p"]
    q = pose_msg["q"]
    mat = np.eye(4, dtype=np.float64)
    mat[:3, :3] = Rotation.from_quat([q["x"], q["y"], q["z"], q["w"]]).as_matrix()
    mat[:3, 3] = np.array([p["x"], p["y"], p["z"]], dtype=np.float64)
    return mat


def build_pose_buffer_from_localpose(localpose_all):
    pose_buffer = {}
    for item in localpose_all:
        ts = int(item["time_stamp"]["nsec"])
        pose_buffer[ts] = _pose_msg_to_matrix(item["smooth_pose"]["pose"])
    return pose_buffer


def lookup_pose(pose_buffer, tgt_ts, max_interval):
    next_ts = sys.maxsize
    prev_ts = 0
    for src_ts, pose in pose_buffer.items():
        if src_ts < tgt_ts:
            prev_ts = max(prev_ts, src_ts)
        elif src_ts > tgt_ts:
            next_ts = min(next_ts, src_ts)
        else:
            return pose

    if prev_ts not in pose_buffer and next_ts not in pose_buffer:
        print("prev and next not found for {}".format(tgt_ts * 1e-9))
        return None

    if prev_ts not in pose_buffer:
        ts_diff = next_ts - tgt_ts
        if (next_ts - tgt_ts) * 1e-9 < max_interval:
            return pose_buffer[next_ts]
        print(f"prev not found for tgt_ts: {tgt_ts * 1e-9}, next_ts: {next_ts * 1e-9}, ts_diff: {ts_diff * 1e-9}")
        return None

    if next_ts not in pose_buffer:
        if (tgt_ts - prev_ts) * 1e-9 < max_interval:
            return pose_buffer[prev_ts]
        return None

    prev_pose = pose_buffer[prev_ts]
    next_pose = pose_buffer[next_ts]
    ratio = float(tgt_ts - prev_ts) / float(next_ts - prev_ts)

    prev_position = prev_pose[0:3, 3]
    next_position = next_pose[0:3, 3]
    tgt_position = prev_position + ratio * (next_position - prev_position)
    tgt_rotation = Slerp(
        [0, 1], Rotation.from_matrix([prev_pose[0:3, 0:3], next_pose[0:3, 0:3]])
    )([ratio])

    tgt_pose = np.eye(4, dtype=np.float64)
    tgt_pose[:3, :3] = tgt_rotation[0].as_matrix()
    tgt_pose[:3, 3] = tgt_position
    return tgt_pose


def get_transform_json(new_calib, original_transform_json):
    available_cam_keys = sorted([k for k in new_calib.keys() if k.startswith("newcam")])
    camera_frames = copy.deepcopy(original_transform_json["frames"])
    lidar_frames = copy.deepcopy(original_transform_json.get("lidar_frames", []))
    sensor_params = extract_sensor_params(new_calib, available_cam_keys)
    return {"sensor_params": sensor_params, "frames": camera_frames, "lidar_frames": lidar_frames}


def extract_sensor_params(calib, cam_list):
    camera_order = []
    out = {}
    for cam_name in cam_list:
        camera_order.append(cam_name.replace("new", ""))
        if 'focal_length_x' in calib[cam_name]['intrinsic'] \
            and 'focal_length_y' in calib[cam_name]['intrinsic']:
            fx = calib[cam_name]['intrinsic']['focal_length_x']
            fy = calib[cam_name]['intrinsic']['focal_length_y']
        else:
            fx = calib[cam_name]['intrinsic']['focal_length']
            fy = calib[cam_name]['intrinsic']['focal_length']
        cx = calib[cam_name]['intrinsic']['cx']
        cy = calib[cam_name]['intrinsic']['cy']
        distortion = [
            calib[cam_name]['intrinsic']['k1'],
            calib[cam_name]['intrinsic']['k2'],
            calib[cam_name]['intrinsic']['p1'],
            calib[cam_name]['intrinsic']['p2'],
            calib[cam_name]['intrinsic']['k3']
        ]

        extrinsic = np.array(
            calib[cam_name]['extrinsic']['transformation_matrix']
        ).reshape((4, 4))

        cam2rig = np.linalg.inv(extrinsic)
        camera_intrinsic_mat = np.array([
                [fx, 0.0, cx],
                [0.0, fy, cy],
                [0.0, 0.0, 1.0],
            ])

        if "width" in calib[cam_name] and "height" in calib[cam_name]:
            w = int(calib[cam_name]["width"])
            h = int(calib[cam_name]["height"])
        else:
            w = int(calib[cam_name]["properties"]["width"])
            h = int(calib[cam_name]["properties"]["height"])
        out[cam_name.replace("new", "")] = {
            "type": "camera",
            "camera_model": "SIMPLE_PINHOLE",
            "camera_intrinsic": camera_intrinsic_mat.tolist(),
            "camera_D": distortion,
            "extrinsic": cam2rig.tolist(),
            "width": w,
            "height": h,
        }
    out['camera_order'] = camera_order
    return out