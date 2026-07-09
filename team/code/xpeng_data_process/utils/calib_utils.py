import numpy as np
import json
import os
from pathlib import Path

from utils.file_utils import load_yaml
from utils.general_utils import lookup_pose, pq_pose_to_4x4, get_ecef2enu


class Calibrations:
    @classmethod
    def __init__(self, config_path, new_mode=True, target_lidar='lidar1', calib_json=None, vision_mode=False):
        self.config_path = config_path
        self._calibrations = load_yaml(self.config_path) if calib_json is None else calib_json
        self._cam_list = ['cam0', 'cam2', 'cam3', 'cam4', 'cam5', 'cam6', 'cam7'] ### DONOT change this order
        self._cam_from_rig = {}
        for cam_id in self._cam_list:
            self._cam_from_rig[cam_id] = np.array(
                self._calibrations[cam_id]['extrinsic']['transformation_matrix']
            ).reshape(4, 4)
            if new_mode:
                self._calibrations[cam_id]["intrinsic"] = self._calibrations["new"+cam_id]["intrinsic"]

        if not vision_mode:
            lidar_extrinsic = self._calibrations[target_lidar]['extrinsic']['transformation_matrix']
            lidar_extrinsic = np.array(lidar_extrinsic).reshape(4, 4)
            self._lidar2rig = np.linalg.inv(lidar_extrinsic)
        return


def get_camera_calib(data):
    if 'focal_length_x' in data and 'focal_length_y' in data:
        fpx = data['focal_length_x']
        fpy = data['focal_length_y']
    else:
        fpx = data['focal_length']
        fpy = data['focal_length']
    cx = data['cx']
    cy = data['cy']

    # 3x3 matrix
    cameraMatrix = np.zeros((3, 3))
    cameraMatrix[0, 0] = fpx
    cameraMatrix[1, 1] = fpy
    cameraMatrix[0, 2] = cx
    cameraMatrix[1, 2] = cy
    cameraMatrix[2, 2] = 1

    p1, p2 = data['p1'], data['p2']
    k1, k2, k3, k4, k5, k6 = data['k1'], data['k2'], data['k3'], data['k4'], data['k5'], data['k6']

    distCoeffs = [k1, k2, p1, p2, k3, k4, k5, k6]
    distCoeffs = np.array(distCoeffs)

    return cameraMatrix, distCoeffs


def get_intrisinc_from_transform(transform_frame):
    h = transform_frame['h']
    w = transform_frame['w']
    fl_x = transform_frame['fl_x']
    fl_y = transform_frame['fl_y']
    cx = transform_frame['cx']
    cy = transform_frame['cy']
    
    intrinsic_matrix=np.array([[fl_x,0,cx,0],
                            [0,fl_y,cy,0],
                            [0,0,1,0],
                            [0,0,0,1]])  
    return intrinsic_matrix, h, w


def get_calibration(calib_path, target_lidar="lidar1", vision_mode=False):
    calibrations = Calibrations(calib_path, True, target_lidar=target_lidar, vision_mode=vision_mode)
    return calibrations


def get_localpose_and_anchorpose(autolabel_json):
    local_pose = dict()
    frames_timestamp = sorted(list(autolabel_json.keys()))
    for frame_timestamp in frames_timestamp:
        auto_label_info = autolabel_json[frame_timestamp]
        local_pose[frame_timestamp] = auto_label_info["local_pose"]
    
    first_frame_timestamp = frames_timestamp[0]
    rig_to_world = local_pose[first_frame_timestamp]
    rig_to_world = np.array(rig_to_world).reshape(4, 4)
    # anchorpose = np.eye(4)
    # anchorpose[:3, 3] = rig_to_world[:3, 3]
    anchorpose = rig_to_world
    return local_pose, anchorpose


def get_localpose_and_anchorpose_from_calib(calib_path):
    calib = load_yaml(calib_path)
    localpose = calib["local_pose"]
    frames_timestamp = sorted(list(localpose.keys()))
    first_frame_timestamp = frames_timestamp[0]
    rig_to_world = localpose[first_frame_timestamp]
    rig_to_world = np.array(rig_to_world).reshape(4, 4)
    # anchorpose = np.eye(4)
    # anchorpose[:3, 3] = rig_to_world[:3, 3]
    anchorpose = rig_to_world
    return localpose, anchorpose


def get_pose_buffer_from_localpose_topic(all_local_pose, ecef2enu, clip_id, raise_on_smooth_pose_error=True):
    local_pose_buffer = dict()
    global_pose_buffer = dict()
    skipped_error_frames = 0
    for local_pose in all_local_pose:
        local_pose_ts = local_pose["time_stamp"]["nsec"]
        # adapt two poses format from dataloader
        if "smooth_pose_info" in local_pose:
            pose = pq_pose_to_4x4(local_pose["smooth_pose_info"]["local_pose"])
        elif "smooth_pose" in local_pose:
            error_code = local_pose["smooth_pose"].get("error_code", 0)
            if error_code != 0:
                msg = f"smooth_pose error_code: {error_code}, clip_id: {clip_id}, ts: {local_pose_ts}"
                if raise_on_smooth_pose_error:
                    print(f"ERROR: smooth_pose error_code: {error_code}, clip_id: {clip_id}")
                    raise Exception(f"ERROR: smooth_pose error_code: {error_code}, clip_id: {clip_id}")
                print(f"WARNING: skip frame due to {msg}")
                skipped_error_frames += 1
                continue
            pose = pq_pose_to_4x4(local_pose["smooth_pose"]["pose"])
        else:
            print(f"ERROR: No smooth_pose_info/smooth_pose found, clip_id: {clip_id}")
            raise Exception(f'No smooth_pose_info/smooth_pose found:\n{local_pose}')
        local_pose_buffer[local_pose_ts] = pose

        if "global_pose" in local_pose:
            global_pose_dict = local_pose["global_pose"]
            global_pose_ts = global_pose_dict["time_stamp"]["nsec"]
            if "world_pose_in_ecef" in global_pose_dict:
                global_pose_buffer[global_pose_ts] = pq_pose_to_4x4(global_pose_dict["world_pose_in_ecef"])
            elif "pose" in global_pose_dict:
                global_pose_buffer[global_pose_ts] = pq_pose_to_4x4(global_pose_dict["pose"])
            else:
                print(f"ERROR: No global pose/world_pose_ecef found, clip_id: {clip_id}")
                raise Exception(f'No global pose/world_pose_ecef found:\n{local_pose}')
            global_pose_buffer[global_pose_ts] = ecef2enu @ global_pose_buffer[global_pose_ts]

    if skipped_error_frames > 0:
        print(
            f"[WARNING] Skipped {skipped_error_frames} frames due to smooth_pose error_code != 0, clip_id: {clip_id}"
        )
    
    local_pose_buffer = dict(sorted(local_pose_buffer.items(), key=lambda x: x[0]))
    global_pose_buffer = dict(sorted(global_pose_buffer.items(), key=lambda x: x[0]))
    return local_pose_buffer, global_pose_buffer


def get_pose_buffer_from_mflocalpose_topic(mf_localpose, ecef2enu, clip_id, raise_on_smooth_pose_error=True):
    """Convert MFLocalPose topic entries to the same format as LocalPoseTopic.

    mf_localpose entries use:
      - time_stamp.nsec          -> timestamp
      - mf_local_pose            -> equivalent to smooth_pose (same sub-structure)
      - world_pose_in_ecef {p,q} -> equivalent to global_pose.world_pose_in_ecef

    Returns:
        local_pose_buffer  - dict[nsec -> 4x4 ndarray]
        global_pose_buffer - dict[nsec -> 4x4 ndarray] (already in ENU frame)
        all_local_pose     - list of dicts in LocalPoseTopic format
    """
    all_local_pose = []
    invalid_frame_count = 0
    for entry in mf_localpose:
        converted = {
            "time_stamp": entry["time_stamp"],
            "smooth_pose": entry["mf_local_pose"],
        }
        if "world_pose_in_ecef" in entry:
            converted["global_pose"] = {
                "time_stamp": entry["time_stamp"],
                "world_pose_in_ecef": entry["world_pose_in_ecef"],
            }
        else:
            invalid_frame_count += 1
            converted["global_pose"] = {
                "time_stamp": entry["time_stamp"],
                "world_pose_in_ecef": entry["mf_local_pose"]['pose'],  # fallback to local pose if global pose is missing
            }
        all_local_pose.append(converted)

    if invalid_frame_count > 0:
        print(f"[WARNING] MFLocalPoseTopic has {invalid_frame_count} frames without valid global pose, clip_id: {clip_id}")
    local_pose_buffer, global_pose_buffer = get_pose_buffer_from_localpose_topic(
        all_local_pose, ecef2enu, clip_id, raise_on_smooth_pose_error=raise_on_smooth_pose_error
    )
    return local_pose_buffer, global_pose_buffer, all_local_pose


def get_localpose_for_lidar_timestamp(
    clip_path,
    use_raw_localpose=False,
    raise_on_smooth_pose_error=True,
):
    if not use_raw_localpose:
        pose_mapping = json.load(open(os.path.join(clip_path, "pose_mapping/pose_mapping.json"), "r"))
        localpose_topic = pose_mapping['lidar_pose_list']
    else:
        localpose_topic = json.load(open(os.path.join(clip_path, "LocalPoseTopic.json"), "r"))
    ecef2enu = get_ecef2enu()
    local_pose_buffer, _ = get_pose_buffer_from_localpose_topic(
        localpose_topic,
        ecef2enu,
        clip_path,
        raise_on_smooth_pose_error=raise_on_smooth_pose_error,
    )
    lidar_metas = json.load(open(os.path.join(clip_path, "lidar_metas.json"), "r"))
    lidar_timestamps = {t: i['collected_at'] for t, i in lidar_metas.items()}
    localpose_lidar = {}
    for _, t_lidar in lidar_timestamps.items():
        localpose_lidar[t_lidar] = lookup_pose(local_pose_buffer, t_lidar, 0.1)
    localpose_lidar = {i: localpose_lidar[i].tolist() for i in sorted(localpose_lidar.keys())}
    return localpose_lidar


def interpolate_localpose_data(localpose_data, lidar_timestamps):
    """
    对localpose数据进行插值，使其与lidar时间戳对齐
    
    Args:
        localpose_data: 原始localpose数据
        lidar_timestamps: lidar时间戳列表
        
    Returns:
        dict: 插值后的localpose数据
    """
    # 提取原始时间戳和位姿
    original_timestamps = sorted([int(k) for k in localpose_data.keys()])
    original_poses = [localpose_data[str(ts)] for ts in original_timestamps]
    
    # 对每个lidar时间戳进行插值
    interpolated_data = {}
    for lidar_ts in lidar_timestamps:
        # 找到最近的两个时间戳进行线性插值
        if lidar_ts <= original_timestamps[0]:
            pose1 = np.array(original_poses[0]).reshape(4, 4)
            pose2 = np.array(original_poses[1]).reshape(4, 4)
            alpha = (lidar_ts - original_timestamps[0]) / (original_timestamps[1] - original_timestamps[0])
            interpolated_pose = pose1 + alpha * (pose2 - pose1)
            interpolated_data[str(lidar_ts)] = interpolated_pose.tolist()
            t_diff = original_timestamps[0] - lidar_ts
            print(f"[WARNING] lidar timestamp earlier than localpose for {t_diff/1e9} seconds.")
        elif lidar_ts >= original_timestamps[-1]:
            pose1 = np.array(original_poses[-2]).reshape(4, 4)
            pose2 = np.array(original_poses[-1]).reshape(4, 4)
            alpha = (lidar_ts - original_timestamps[-1]) / (original_timestamps[-1] - original_timestamps[-2])
            interpolated_pose = pose1 + alpha * (pose2 - pose1)
            interpolated_data[str(lidar_ts)] = interpolated_pose.tolist()
            t_diff = lidar_ts - original_timestamps[-1]
            print(f"[WARNING] lidar timestamp later than localpose for {t_diff/1e9} seconds.")
        else:
            # 找到插值区间
            for i in range(len(original_timestamps) - 1):
                if original_timestamps[i] <= lidar_ts <= original_timestamps[i + 1]:
                    t1, t2 = original_timestamps[i], original_timestamps[i + 1]
                    pose1, pose2 = original_poses[i], original_poses[i + 1]
                    
                    # 线性插值
                    alpha = (lidar_ts - t1) / (t2 - t1)
                    interpolated_pose = {}
                    pose1 = np.array(pose1).reshape(4, 4)
                    pose2 = np.array(pose2).reshape(4, 4)
                    interpolated_pose = pose1 + alpha * (pose2 - pose1)
                    interpolated_data[str(lidar_ts)] = interpolated_pose.tolist()
                    break
    
    return interpolated_data


def load_localpose_lidar_and_anchorpose_from_json(clip_path):
    clip_path = Path(clip_path)
    localpose_lidar_anchored = {}
    localpose_global = json.load(open(clip_path / "localpose_lidar.json"))
    anchorpose = np.array(json.load(open(clip_path / "anchorpose.json", "r")))
    world2anchor = np.linalg.inv(anchorpose)
    for timestamp, pose in localpose_global.items():
        localpose_lidar_anchored[timestamp] = world2anchor @ np.array(pose).reshape(4, 4)
    
    return localpose_lidar_anchored, anchorpose


def load_localpose_and_anchorpose_from_json(clip_path):
    clip_path = Path(clip_path)
    localpose_anchored = {}
    localpose_global = json.load(open(clip_path / "localpose.json"))
    anchorpose = np.array(json.load(open(clip_path / "anchorpose.json", "r")))
    world2anchor = np.linalg.inv(anchorpose)
    for timestamp, pose in localpose_global.items():
        localpose_anchored[timestamp] = world2anchor @ np.array(pose).reshape(4, 4)
    
    return localpose_anchored, anchorpose


def load_localpose_lidar_aligned(clip_path):
    localpose_anchored, _ = load_localpose_and_anchorpose_from_json(clip_path)
    localpose_lidar_anchored, _ = load_localpose_lidar_and_anchorpose_from_json(clip_path)
    localpose_aligned = {}
    timestamps_slice = np.array([int(i) for i in localpose_anchored.keys()])
    timestamps_lidar = np.array([int(i) for i in localpose_lidar_anchored.keys()])
    for t_slice in timestamps_slice:
        nearest_lidar_idx = np.argmin(np.abs(timestamps_lidar - t_slice))
        # time_diff = abs(timestamps_lidar[nearest_lidar_idx] - t_slice) / 1e9
        localpose_aligned[str(t_slice)] = localpose_lidar_anchored[str(timestamps_lidar[nearest_lidar_idx])]
    return localpose_aligned

    
def get_anchored_localpose(localpose, anchorpose):
    xyz_anchored = []
    for i in localpose.values():
        xyz_anchored.append(np.linalg.inv(anchorpose) @ np.array(i))
    xyz_anchored = np.array(xyz_anchored)
    return xyz_anchored


def get_localpose_based_on_the_first_frame(localpose):
    localpose_anchored = {}
    anchorpose = localpose[min(localpose.keys())]
    for timestamp, pose in localpose.items():
        localpose_anchored[timestamp] = (np.linalg.inv(anchorpose) @ np.array(pose)).tolist()
    return localpose_anchored, anchorpose

