import json
import os, sys
import math
import numpy as np

from bisect import bisect_left
from typing import Any, Dict, List
from scipy.spatial.transform import Rotation as R, Slerp

current_dir = os.path.dirname(__file__)
root_path = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(root_path)

from utils.annotation_utils import apply_transformation, dynamic_object_mapping
from utils.calib_utils import get_localpose_based_on_the_first_frame


def _shortest_angular_distance(src_angle, dst_angle):
    """
    计算两个角之间的最短有向角度差，范围[-pi, pi]
    """
    return (dst_angle - src_angle + math.pi) % (2 * math.pi) - math.pi


def quaternion_to_rotation_matrix(q):
    """
    将四元数转换为旋转矩阵
    q: [x, y, z, w]
    """
    x, y, z, w = q
    return np.array([
        [1 - 2*(y*y + z*z), 2*(x*y - z*w), 2*(x*z + y*w)],
        [2*(x*y + z*w), 1 - 2*(x*x + z*z), 2*(y*z - x*w)],
        [2*(x*z - y*w), 2*(y*z + x*w), 1 - 2*(x*x + y*y)]
    ])

def rotation_matrix_to_euler_angles(R_mat):
    """
    从旋转矩阵提取欧拉角 (roll, pitch, yaw)
    使用XYZ顺序
    """
    sy = math.sqrt(R_mat[0,0] * R_mat[0,0] + R_mat[1,0] * R_mat[1,0])
    
    singular = sy < 1e-6
    
    if not singular:
        x = math.atan2(R_mat[2,1], R_mat[2,2])
        y = math.atan2(-R_mat[2,0], sy)
        z = math.atan2(R_mat[1,0], R_mat[0,0])
    else:
        x = math.atan2(-R_mat[1,2], R_mat[1,1])
        y = math.atan2(-R_mat[2,0], sy)
        z = 0
    
    return np.array([x, y, z])


def transform_point_enu_to_rig(point_enu, ego_position, ego_quaternion):
    """
    将ENU坐标系下的点转换为RIG坐标系
    point_enu: [x, y, z] - 目标点在ENU坐标系下的位置
    ego_position: [x, y, z] - 自车在ENU坐标系下的位置
    ego_quaternion: [x, y, z, w] - 自车在ENU坐标系下的姿态四元数
    """
    # 构建从ENU到RIG的变换矩阵
    # 首先将点移动到以自车为原点的坐标系
    relative_position = np.array(point_enu) - np.array(ego_position)
    
    # 获取自车的旋转矩阵（ENU到RIG）
    rot_matrix = quaternion_to_rotation_matrix(ego_quaternion)
    
    # 转换位置到RIG坐标系
    point_rig = rot_matrix.T @ relative_position
    
    return point_rig


def transform_yaw_enu_to_rig(yaw_enu, ego_quaternion):
    """
    将ENU坐标系下的航向角转换为RIG坐标系
    yaw_enu: ENU坐标系下的航向角
    ego_quaternion: [x, y, z, w] - 自车在ENU坐标系下的姿态四元数
    """
    # 将自车四元数转换为欧拉角以获取自车的偏航角
    ego_rot = R.from_quat(ego_quaternion)
    ego_euler = ego_rot.as_euler('xyz')
    ego_yaw = ego_euler[2]  # 偏航角(z轴旋转)
    
    # 计算目标在RIG坐标系下的航向角
    yaw_rig = yaw_enu - ego_yaw
    
    # 规范化角度到[-π, π]
    while yaw_rig > math.pi:
        yaw_rig -= 2 * math.pi
    while yaw_rig < -math.pi:
        yaw_rig += 2 * math.pi
        
    return yaw_rig


def convert_obj_to_rig(json_data):
    """
    转换JSON数据中的坐标系
    """
    # 提取自车信息
    egomotion = json_data['egomotion']
    ego_position = [
        egomotion['local_pose']['p']['x'],
        egomotion['local_pose']['p']['y'],
        egomotion['local_pose']['p']['z']
    ]
    ego_quaternion = [
        egomotion['local_pose']['q']['x'],
        egomotion['local_pose']['q']['y'],
        egomotion['local_pose']['q']['z'],
        egomotion['local_pose']['q']['w']
    ]
    
    # 处理每个动态对象
    for obj in json_data['dynamic_object_vector']:
        # 转换位置 local_pose
        if 'local_pose' in obj:
            point_enu = [
                obj['local_pose']['x'],
                obj['local_pose']['y'],
                obj['local_pose']['z']
            ]
            
            point_rig = transform_point_enu_to_rig(point_enu, ego_position, ego_quaternion)
            
            # 更新对象的位置信息
            obj['local_pose']['x'] = float(point_rig[0])
            obj['local_pose']['y'] = float(point_rig[1])
            obj['local_pose']['z'] = float(point_rig[2]) + obj["size"]["height"]/2
        
        # 转换航向角 local_yaw
        if 'local_yaw' in obj:
            yaw_enu = obj['local_yaw']
            yaw_rig = transform_yaw_enu_to_rig(yaw_enu, ego_quaternion)
            obj['local_yaw'] = float(yaw_rig)
    
    return json_data


def convert_json_coordinates(
    prev_sf_timestamp,
    next_sf_timestamp,
    timestamp,
    sensor_fusion_data,
    rig_objects_cache,
):
    """
    根据前后两帧 sensor fusion 数据插值出目标 timestamp 对应的帧，
    在各自自车坐标系下先转换，再在自车系中插值。
    """
    prev_ts = int(prev_sf_timestamp)
    next_ts = int(next_sf_timestamp)
    target_ts = int(timestamp)

    if next_ts < prev_ts:
        prev_ts, next_ts = next_ts, prev_ts

    prev_frame = sensor_fusion_data.get(str(prev_ts))
    next_frame = sensor_fusion_data.get(str(next_ts))

    if prev_frame is None and next_frame is None:
        return {"timestamp": str(timestamp), "dynamic_object_vector": []}
    if prev_frame is None:
        prev_frame = next_frame
        prev_ts = next_ts
    if next_frame is None:
        next_frame = prev_frame
        next_ts = prev_ts

    if next_ts == prev_ts:
        ratio = 0.0
    else:
        ratio = (target_ts - prev_ts) / float(next_ts - prev_ts)
    ratio = float(np.clip(ratio, 0.0, 1.0))

    prev_rig_objs = rig_objects_cache.get(prev_ts)
    if prev_rig_objs is None:
        prev_rig_objs = _frame_to_rig_objects(prev_frame)
        rig_objects_cache[prev_ts] = prev_rig_objs

    next_rig_objs = rig_objects_cache.get(next_ts)
    if next_rig_objs is None:
        next_rig_objs = _frame_to_rig_objects(next_frame)
        rig_objects_cache[next_ts] = next_rig_objs
    all_obj_ids = set(prev_rig_objs.keys()) | set(next_rig_objs.keys())

    converted_objects = []
    for obj_id in all_obj_ids:
        prev_obj = prev_rig_objs.get(obj_id)
        next_obj = next_rig_objs.get(obj_id)
        interpolated_obj = _interpolate_object(prev_obj, next_obj, ratio, obj_id)
        if interpolated_obj is None:
            continue
        converted_objects.append(interpolated_obj)

    converted_frame = {
        "timestamp": str(timestamp),
        "dynamic_object_vector": converted_objects,
    }
    return converted_frame


def _frame_to_rig_objects(frame_data):
    """
    将单帧 SensorFusion 数据中的所有障碍物转换到自车坐标系
    """
    ego_pos, ego_quat = _extract_ego_pose(frame_data)
    ego_pose = np.eye(4)
    ego_pose[:3, :3] = quaternion_to_rotation_matrix(ego_quat)
    ego_pose[:3, 3] = ego_pos
    world_to_rig = np.linalg.inv(ego_pose)

    obj_map = {}
    for obj in frame_data.get("dynamic_object_vector", []):
        obj_id = obj.get("sf_id")
        if obj_id is None:
            continue
        obj_map[obj_id] = _convert_object_to_rig(obj, world_to_rig)
    return obj_map


def _extract_ego_pose(frame_data):
    pose = frame_data.get("egomotion", {}).get("local_pose", {})
    p = pose.get("p", {})
    q = pose.get("q", {})
    pos = np.array(
        [
            p.get("x", 0.0),
            p.get("y", 0.0),
            p.get("z", 0.0),
        ],
        dtype=np.float64,
    )
    quat = np.array(
        [
            q.get("x", 0.0),
            q.get("y", 0.0),
            q.get("z", 0.0),
            q.get("w", 1.0),
        ],
        dtype=np.float64,
    )
    return pos, quat


def _interpolate_ego_pose(prev_frame, next_frame, ratio):
    prev_pos, prev_quat = _extract_ego_pose(prev_frame)
    next_pos, next_quat = _extract_ego_pose(next_frame)
    pos = prev_pos + ratio * (next_pos - prev_pos)
    if ratio <= 0.0:
        quat = prev_quat
    elif ratio >= 1.0:
        quat = next_quat
    else:
        key_rots = R.from_quat([prev_quat, next_quat])
        slerp = Slerp([0, 1], key_rots)
        quat = slerp([ratio])[0].as_quat()
    return pos, quat


def _interpolate_object(prev_obj, next_obj, ratio, obj_id):
    if prev_obj is None and next_obj is None:
        return None
    if prev_obj is None:
        prev_obj = next_obj
        ratio = 1.0
    if next_obj is None:
        next_obj = prev_obj
        ratio = 0.0

    pose_prev = prev_obj.get("local_pose", {})
    pose_next = next_obj.get("local_pose", pose_prev)
    prev_pose_arr = np.array(
        [pose_prev.get("x", 0.0), pose_prev.get("y", 0.0), pose_prev.get("z", 0.0)],
        dtype=np.float64,
    )
    next_pose_arr = np.array(
        [pose_next.get("x", 0.0), pose_next.get("y", 0.0), pose_next.get("z", 0.0)],
        dtype=np.float64,
    )
    interp_pose = prev_pose_arr + ratio * (next_pose_arr - prev_pose_arr)

    yaw_prev = float(prev_obj.get("local_yaw", 0.0))
    yaw_next = float(next_obj.get("local_yaw", yaw_prev))
    yaw_delta = _shortest_angular_distance(yaw_prev, yaw_next)
    interp_yaw = yaw_prev + ratio * yaw_delta

    size = prev_obj.get("size") or next_obj.get("size") or {}
    obj_type = prev_obj.get("type") or next_obj.get("type") or ""

    vx = prev_obj['local_linear_velocity']['x']
    vy = prev_obj['local_linear_velocity']['y']

    return {
        "sf_id": obj_id,
        "size": size,
        "type": obj_type,
        "local_pose": {
            "x": float(interp_pose[0]),
            "y": float(interp_pose[1]),
            "z": float(interp_pose[2]),
        },
        "local_yaw": float((interp_yaw + math.pi) % (2 * math.pi) - math.pi),
        "local_linear_velocity": {
            "x": float(vx),
            "y": float(vy),
        }
    }


def _convert_object_to_rig(obj, world2rig):
    size = obj.get("size") or {}
    height = size.get("height", 0.0)
    pose = obj.get("local_pose", {})
    point_enu = np.array(
        [
            pose.get("x", 0.0),
            pose.get("y", 0.0),
            pose.get("z", 0.0) + height * 0.5,
        ],
        dtype=np.float64,
    )

    yaw_enu = obj.get("local_yaw", 0.0)
    obj_rotation_world = R.from_euler("xyz", [0.0, 0.0, yaw_enu]).as_matrix()
    obj_pose_world = np.eye(4)
    obj_pose_world[:3, :3] = obj_rotation_world
    obj_pose_world[:3, 3] = point_enu

    obj_pose_rig = world2rig @ obj_pose_world
    obj_center_rig = obj_pose_rig[:3, 3]
    obj_rotation_rig = obj_pose_rig[:3, :3]
    _, _, yaw_rig = rotation_matrix_to_euler_angles(obj_rotation_rig)

    converted_obj = dict(obj)
    converted_obj["local_pose"] = {
        "x": float(obj_center_rig[0]),
        "y": float(obj_center_rig[1]),
        "z": float(obj_center_rig[2]),
    }
    converted_obj["local_rotation"] = obj_rotation_rig.tolist()
    converted_obj["local_yaw"] = float(yaw_rig)
    return converted_obj


def interpolate_sf(prev_obj, next_obj, prev_ts, next_ts, target_ts):
    """
    在两帧传感器融合对象之间插值位置与朝向。
    """
    if prev_obj is None or next_obj is None:
        raise ValueError("prev_obj 和 next_obj 不能为空")
    if prev_ts == next_ts:
        ratio = 0.0
    else:
        ratio = (target_ts - prev_ts) / float(next_ts - prev_ts)
    ratio = float(np.clip(ratio, 0.0, 1.0))

    def _pose_to_array(obj):
        pose = obj.get("local_pose", {})
        return np.array(
            [
                pose.get("x", 0.0),
                pose.get("y", 0.0),
                pose.get("z", 0.0),
            ],
            dtype=np.float64,
        )

    prev_pose = _pose_to_array(prev_obj)
    next_pose = _pose_to_array(next_obj)
    interp_pose = prev_pose + ratio * (next_pose - prev_pose)

    prev_yaw = float(prev_obj.get("local_yaw", 0.0))
    next_yaw = float(next_obj.get("local_yaw", 0.0))
    yaw_delta = _shortest_angular_distance(prev_yaw, next_yaw)
    interp_yaw = prev_yaw + ratio * yaw_delta

    position_dict = {
        "x": float(interp_pose[0]),
        "y": float(interp_pose[1]),
        "z": float(interp_pose[2]),
    }
    return position_dict, float((interp_yaw + math.pi) % (2 * math.pi) - math.pi)


def _split_tracks_by_gap(
    object_tracks: Dict[Any, Dict[str, List]],
    max_gap_ns: int,
) -> Dict[Any, Dict[str, List]]:
    """
    如果同一对象轨迹中存在超过 max_gap_ns 的时间间隔，则拆分成多个轨迹。
    新轨迹会被分配新的 gid（在现有最大 id 基础上自增）。
    """

    def _to_int(obj_id):
        if isinstance(obj_id, int):
            return obj_id
        try:
            return int(obj_id)
        except (TypeError, ValueError):
            return None

    numeric_ids = [val for val in (_to_int(k) for k in object_tracks.keys()) if val is not None]
    next_new_id = (max(numeric_ids) + 1) if numeric_ids else 10 ** 6
    used_ids = set(object_tracks.keys())

    new_tracks: Dict[Any, Dict[str, List]] = {}

    for obj_id, track in object_tracks.items():
        ts_list = track.get("timestamps", [])
        obj_list = track.get("objects", [])
        if len(ts_list) <= 1:
            new_tracks[obj_id] = track
            continue

        segments = []
        start_idx = 0
        for idx in range(1, len(ts_list)):
            if ts_list[idx] - ts_list[idx - 1] > max_gap_ns:
                segments.append((start_idx, idx))
                start_idx = idx
        segments.append((start_idx, len(ts_list)))

        if len(segments) == 1:
            new_tracks[obj_id] = track
            continue

        for seg_idx, (seg_start, seg_end) in enumerate(segments):
            seg_track = {
                "type": track.get("type", ""),
                "timestamps": ts_list[seg_start:seg_end],
                "objects": obj_list[seg_start:seg_end],
            }
            if seg_idx == 0:
                new_tracks[obj_id] = seg_track
            else:
                while next_new_id in used_ids or next_new_id in new_tracks:
                    next_new_id += 1
                new_tracks[next_new_id] = seg_track
                used_ids.add(next_new_id)
                next_new_id += 1

    return new_tracks


def _apply_track_split_to_frames(sensor_fusion_data, max_gap_ns):
    """
    在原始 sensor fusion 帧上应用轨迹拆分，更新对象 ID。
    """
    object_tracks: Dict[Any, Dict[str, List]] = {}
    frames_by_ts: Dict[int, Dict] = {}
    for ts_str, frame in sensor_fusion_data.items():
        ts_int = int(ts_str)
        frames_by_ts[ts_int] = frame
        for obj in frame.get("dynamic_object_vector", []):
            obj_id = obj.get("sf_id")
            if obj_id is None:
                continue
            track = object_tracks.setdefault(
                obj_id,
                {"type": obj.get("type", ""), "timestamps": [], "objects": []},
            )
            if obj.get("type"):
                track["type"] = obj["type"]
            track["timestamps"].append(ts_int)
            track["objects"].append(obj)

    if not object_tracks:
        return sensor_fusion_data, 0, 0

    split_tracks = _split_tracks_by_gap(object_tracks, max_gap_ns)
    min_track_duration_ns = int(0.5 * 1e9)
    removed_track_ids = set()

    for new_id, track in split_tracks.items():
        ts_list = track.get("timestamps", [])
        if not ts_list:
            removed_track_ids.add(new_id)
            continue
        duration = max(ts_list) - min(ts_list)
        if duration < min_track_duration_ns:
            removed_track_ids.add(new_id)
            continue
        for obj in track.get("objects", []):
            obj["sf_id"] = new_id

    for removed_id in removed_track_ids:
        track = split_tracks[removed_id]
        for ts_int, obj in zip(track.get("timestamps", []), track.get("objects", [])):
            frame = frames_by_ts.get(ts_int)
            if frame is None:
                continue
            objs = frame.get("dynamic_object_vector", [])
            if obj in objs:
                objs.remove(obj)

    new_track_count = len(split_tracks) - len(removed_track_ids)
    removed_track_count = len(removed_track_ids)

    return sensor_fusion_data, len(object_tracks), new_track_count, removed_track_count


def _count_unique_sf_ids(sensor_fusion_data: Dict[str, Dict]) -> int:
    unique_ids = set()
    for frame in sensor_fusion_data.values():
        for obj in frame.get("dynamic_object_vector", []):
            obj_id = obj.get("sf_id")
            if obj_id is not None:
                unique_ids.add(obj_id)
    return len(unique_ids)


def sensor_fusion_to_annotation_intp(sensor_fusion_data, localpose, anchorpose):
    annotation_sensor_fusion = {"frames": []}
    world2anchor = np.linalg.inv(np.array(anchorpose, dtype=np.float64))

    sf_frames_by_int = {}
    for ts_str, frame_data in sensor_fusion_data.items():
        ts_int = int(ts_str)
        sf_frames_by_int[ts_int] = frame_data

    sf_timestamps = sorted(sf_frames_by_int.keys())
    object_tracks = {}

    for ts_int in sf_timestamps:
        frame = sf_frames_by_int[ts_int]
        for obj in frame.get("dynamic_object_vector", []):
            obj_id = obj.get("sf_id")
            if obj_id is None:
                continue
            track = object_tracks.setdefault(
                obj_id,
                {"type": obj.get("type", ""), "timestamps": [], "objects": []},
            )
            if obj.get("type"):
                track["type"] = obj["type"]
            track["timestamps"].append(ts_int)
            track["objects"].append(obj)

    max_track_gap_ns = int(3.0 * 1e9)
    object_tracks = _split_tracks_by_gap(object_tracks, max_track_gap_ns)

    sorted_localpose = sorted(localpose.keys(), key=lambda x: int(x))
    max_obj_time_gap_ns = int(0.1 * 1e9)  # 单个障碍物允许的最大时间差

    for timestamp in sorted_localpose:
        target_ts = int(timestamp)
        frame_objects = []

        for obj_id, track in object_tracks.items():
            ts_list = track["timestamps"]
            obj_list = track["objects"]
            if not ts_list:
                continue

            idx = bisect_left(ts_list, target_ts)
            if idx < len(ts_list) and ts_list[idx] == target_ts:
                prev_idx = next_idx = idx
            else:
                if idx == 0 or idx == len(ts_list):
                    continue
                prev_idx = idx - 1
                next_idx = idx

            prev_obj = obj_list[prev_idx]
            next_obj = obj_list[next_idx]
            prev_ts = ts_list[prev_idx]
            next_ts = ts_list[next_idx]

            time_gap = min(abs(target_ts - prev_ts), abs(next_ts - target_ts))
            if time_gap > max_obj_time_gap_ns:
                continue

            position_dict, interp_yaw = interpolate_sf(
                prev_obj, next_obj, prev_ts, next_ts, target_ts
            )

            dimension = prev_obj.get("size") or next_obj.get("size")
            if not dimension:
                continue
            length = dimension.get("length", 0.0)
            width = dimension.get("width", 0.0)
            height = dimension.get("height", 0.0)
            size = [length, width, height]

            center_world = np.array(
                [
                    position_dict["x"],
                    position_dict["y"],
                    position_dict["z"] + height * 0.5,
                ],
                dtype=np.float64,
            )
            center_world_h = np.ones(4, dtype=np.float64)
            center_world_h[:3] = center_world
            anchor_center = world2anchor @ center_world_h
            anchor_translation = anchor_center[:3].tolist()

            R_world_obj = R.from_euler("xyz", [0.0, 0.0, interp_yaw]).as_matrix()
            R_anchor_obj = world2anchor[:3, :3] @ R_world_obj
            anchor_quat_xyzw = R.from_matrix(R_anchor_obj).as_quat()
            anchor_rotation = [
                float(anchor_quat_xyzw[3]),
                float(anchor_quat_xyzw[0]),
                float(anchor_quat_xyzw[1]),
                float(anchor_quat_xyzw[2]),
            ]

            mod_type = track.get("type", "") or prev_obj.get("type", "") or next_obj.get("type", "")
            obj_type = mod_type.split("::")[-1] if "::" in mod_type else (mod_type or "car")

            frame_objects.append(
                {
                    "type": dynamic_object_mapping(obj_type.lower()),
                    "gid": obj_id,
                    "translation": anchor_translation,
                    "size": size,
                    "rotation": anchor_rotation,
                    "is_moving": True,
                }
            )

        annotation_sensor_fusion["frames"].append(
            {
                "timestamp": timestamp,
                "objects": frame_objects,
            }
        )

    return annotation_sensor_fusion


def _build_obj_distance_series(frames: List[Dict]) -> Dict[int, List[Dict[str, float]]]:
    obj_distance_series: Dict[int, List[Dict[str, float]]] = {}
    for frame in frames:
        ts = frame["timestamp"]
        for obj in frame.get("objects", []):
            gid = obj.get("gid")
            translation = obj.get("translation", [0.0, 0.0, 0.0])
            dist = float(np.linalg.norm(translation))
            obj_distance_series.setdefault(gid, []).append({"timestamp": ts, "distance": dist})
    return obj_distance_series


def filter_objects_by_distance_and_time(
    annotation: Dict,
    dist_threshold: float,
    time_threshold_sec: float,
) -> None:
    """
    如果某个对象在其整个存续期间的最近距离超过 dist_threshold 且持续时间少于 time_threshold_sec，则删除该对象
    """
    frames = annotation.get("frames", [])
    obj_series = annotation.get("object_distance_series") or _build_obj_distance_series(frames)
    annotation["object_distance_series"] = obj_series

    time_threshold_ns = int(time_threshold_sec * 1e9)
    to_remove = set()

    for obj_id, measurements in obj_series.items():
        if not measurements:
            to_remove.add(obj_id)
            continue
        min_dist = min(m["distance"] for m in measurements)
        first_ts = int(measurements[0]["timestamp"])
        last_ts = int(measurements[-1]["timestamp"])
        duration = last_ts - first_ts
        if min_dist > dist_threshold and duration < time_threshold_ns:
            to_remove.add(obj_id)

    removed_count = len(to_remove)
    if removed_count == 0:
        print("[INFO][DIST] Distance filter removed 0 objs; remaining unchanged")
        return

    kept_series = {gid: series for gid, series in obj_series.items() if gid not in to_remove}
    annotation["object_distance_series"] = kept_series

    for frame in frames:
        objs = frame.get("objects", [])
        frame["objects"] = [o for o in objs if o.get("gid") not in to_remove]

    remaining = len(kept_series)
    print(
        f"[INFO][OBJ] Distance filter removed {removed_count} objs; remaining {remaining} objs"
    )


def sensor_fusion_to_annotation(sensor_fusion_data, localpose_anchored):
    annotation_sensor_fusion = {"frames": []}
    max_track_gap_ns = int(3.0 * 1e9)

    (
        sensor_fusion_data,
        orig_obj_count,
        new_obj_count,
        removed_track_count,
    ) = _apply_track_split_to_frames(
        sensor_fusion_data, max_track_gap_ns
    )
    net_delta = new_obj_count - orig_obj_count
    print(
        "[INFO][OBJ] SensorFusion objs: "
        f"original={orig_obj_count}, final_unique={new_obj_count}, "
        f"short_removed={removed_track_count}, final_added={net_delta}"
    )

    sf_timestamps = sorted(sensor_fusion_data.keys(), key=lambda x: int(x))
    sf_timestamps_int = [int(ts) for ts in sf_timestamps]
    rig_objects_cache: Dict[int, Dict[int, Dict]] = {}
    localpose_anchored = {k: localpose_anchored[k] for k in sorted(localpose_anchored.keys())}
    obj_prev_pos = {}

    for timestamp, rig2anchor in localpose_anchored.items():
        target_ts = int(timestamp)
        idx = bisect_left(sf_timestamps_int, target_ts)
        if idx == 0:
            prev_ts = next_ts = sf_timestamps_int[0]
        elif idx >= len(sf_timestamps_int):
            prev_ts = next_ts = sf_timestamps_int[-1]
        else:
            prev_ts = sf_timestamps_int[idx - 1]
            next_ts = sf_timestamps_int[idx]

        converted_frame_data = convert_json_coordinates(
            prev_ts, next_ts, target_ts, sensor_fusion_data, rig_objects_cache
        )

        frame = {
            "timestamp": timestamp,
            "objects": []
        }
            
        for obj in converted_frame_data["dynamic_object_vector"]:
            obj_id = obj["sf_id"]
            position = obj["local_pose"]

            rig_rotation_mat = np.array(obj.get("local_rotation", []))
            if rig_rotation_mat.size == 9:
                rig_rot = R.from_matrix(rig_rotation_mat.reshape(3, 3))
            else:
                yaw = obj.get("local_yaw", 0.0)
                rig_rot = R.from_euler('xyz', [0.0, 0.0, yaw])
            rig_rot_quat = rig_rot.as_quat()  # [x, y, z, w]
            rig_rotation = [rig_rot_quat[3], rig_rot_quat[0], rig_rot_quat[1], rig_rot_quat[2]]

            rig_translation = np.array([
                position["x"],
                position["y"],
                position["z"]
            ])
            anchor_translation, anchor_rotation = apply_transformation(
                rig_translation, rig_rotation, rig2anchor)
            
            dimension = obj["size"]
            size = [
                dimension["length"],
                dimension["width"],
                dimension["height"]
            ]

            mod_type = obj["type"]
            obj_type = mod_type.split("::")[-1]
            
            is_moving = True
            if dynamic_object_mapping(obj_type.lower()) != "pedestrian" and \
                dynamic_object_mapping(obj_type.lower()) != "cyclist":
                if abs(obj["local_linear_velocity"]["x"]) < 0.05 and \
                   abs(obj["local_linear_velocity"]["y"]) < 0.05:
                   is_moving = False

                if is_moving and obj_id in obj_prev_pos:
                    delta_translation = np.linalg.norm(np.array(obj_prev_pos[obj_id]) - np.array(anchor_translation))
                    if delta_translation < 0.05:
                        is_moving = False
                obj_prev_pos[obj_id] = anchor_translation

            dynamic_obj = {
                "type": dynamic_object_mapping(obj_type.lower()),
                "gid": obj_id,
                "translation": anchor_translation,
                "size": size,
                "rotation": anchor_rotation,
                "is_moving": is_moving
            }
            frame["objects"].append(dynamic_obj)
        
        annotation_sensor_fusion["frames"].append(frame)

    filter_objects_by_distance_and_time(annotation_sensor_fusion, 30.0, 1.0)
    return annotation_sensor_fusion


def load_sensor_fusion_data(input_file):
    if not os.path.exists(input_file):
        return None
    try:
        with open(input_file, 'r') as f:
            sensor_fusion_data = json.load(f)
            if isinstance(sensor_fusion_data, list):
                sensor_fusion_dict = {}
                for item in sensor_fusion_data:
                    if "time_stamp" in item and "nsec" in item["time_stamp"]:
                        timestamp_key = str(item["time_stamp"]["nsec"])
                        sensor_fusion_dict[timestamp_key] = item
                sensor_fusion_data = sensor_fusion_dict
            return sensor_fusion_data
    except Exception as e:
        print(f"[INFO] Failed to parse sensor_fusion_topic file {input_file}: {e}")
        return None    
        

def get_annotation_from_sf(clip_path, localpose):
    localpose_anchored, _ = get_localpose_based_on_the_first_frame(localpose)
    sensor_fusion_path = os.path.join(clip_path, 'SensorFusionTopic.json')
    sensor_fusion_json = load_sensor_fusion_data(sensor_fusion_path)
    if sensor_fusion_json is None:
        return None
    else:
        return sensor_fusion_to_annotation(sensor_fusion_json, localpose_anchored)
        # return sensor_fusion_to_annotation_intp(sensor_fusion_json, localpose_anchored, anchorpose)


if __name__ == "__main__":
    import time
    clip_path = "/workspace/yangxh7@xiaopeng.com/test_clip"
    localpose = json.load(open(os.path.join(clip_path, "localpose.json"), "r"))
    # anchorpose = json.load(open(os.path.join(clip_path, "anchorpose.json"), "r"))
    # sensor_fusion_path = os.path.join(clip_path, 'SensorFusionTopic.json')
    # sensor_fusion_json = load_sensor_fusion_data(sensor_fusion_path)
    start_time = time.time()
    annotation_sensor_fusion = get_annotation_from_sf(clip_path, localpose)
    json.dump(annotation_sensor_fusion, open(os.path.join(clip_path, "annotation_for_train.json"), "w"), indent=4)
    end_time = time.time()
    print(f"Time taken: {end_time - start_time} seconds")

