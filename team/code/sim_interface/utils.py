import bisect
import os, sys
import json
import cv2
import math
import numpy as np
import scipy
from scipy.spatial.transform import Rotation as R
from scipy.spatial.transform import Slerp
from scipy.spatial import KDTree
from numpy.typing import NDArray
from typing import Optional
import torch
import torch.nn.functional as F


_camera2label = {
    'cam0': 1,
    'cam2': 2,
    'cam3': 3,
    'cam4': 4,
    'cam5': 5,
    'cam6': 6,
    'cam7': 7,
}

_label2camera = {
    1: 'cam0',
    2: 'cam2',
    3: 'cam3',
    4: 'cam4',
    5: 'cam5',
    6: 'cam6',
    7: 'cam7',
}

_expand_ratio_dict = {
    "cam0": 1.0,
    "cam2": 1.0,
    "cam3": 1.0,
    "cam4": 1.0,
    "cam5": 1.0,
    "cam6": 1.0,
    "cam7": 1.0
}

_EPS = np.finfo(float).eps * 4.0

class TransferposeIndex:
    __slots__ = ('transferpose', 'kdtree', 'keys')

    def __init__(self, transferpose):
        self.transferpose = transferpose
        self.kdtree, self.keys = self.build_kdtree()
        
    def build_kdtree(self):
        translation_list = []
        keys = []

        for t in self.transferpose.keys():
            T = np.array(t).reshape(4, 4)
            translation = T[:3, 3]
            translation_list.append(translation)
            keys.append(t)

        kdtree = KDTree(translation_list)
        return kdtree, keys

    def find(self, pose):
        query_translation = pose[:3, 3]

        _, idx = self.kdtree.query(query_translation)
        nearest_key = self.keys[idx]
        nearest_value = self.transferpose[nearest_key]
        return nearest_key, nearest_value

def interpolate_pose_with_times(poses, target_time):
    """
    Interpolates a 4x4 pose matrix at a specific time.

    Args:
        poses (dict): A dictionary with timestamps as keys and 4x4 numpy arrays as values.
        target_time (float): The timestamp to interpolate at.

    Returns:
        np.ndarray: The interpolated 4x4 pose matrix.
    """
    sorted_times = sorted(poses.keys())

    if target_time < sorted_times[0] or target_time > sorted_times[-1]:
        print(
            f"Target time {target_time} is outside the range of the provided poses.[{sorted_times[0]}:{sorted_times[-1]}]"
        )
        return None

    t1 = sorted_times[0]
    t2 = None
    for t in sorted_times:
        if t <= target_time:
            t1 = t
        else:
            t2 = t
            break
            
    if t2 is None:
        return poses[t1]

    pose1 = np.array(poses[t1], dtype=np.float64)
    pose2 = np.array(poses[t2], dtype=np.float64)
    trans1 = pose1[:3, 3]
    trans2 = pose2[:3, 3]
    rot1_mat = pose1[:3, :3]
    rot2_mat = pose2[:3, :3]

    # 计算插值因子(0-1)
    interp_factor = (target_time - t1) / (t2 - t1)

    # 线性插值平移向量
    interp_trans = (1 - interp_factor) * trans1 + interp_factor * trans2

    # 球面线性插值旋转
    key_rots = R.from_matrix([rot1_mat, rot2_mat])
    slerp = Slerp([t1, t2], key_rots)
    interp_rot = slerp([target_time])
    interp_rot_mat = interp_rot.as_matrix()[0]

    interp_pose = np.identity(4)
    interp_pose[:3, :3] = interp_rot_mat
    interp_pose[:3, 3] = interp_trans

    return interp_pose

def find_closest_msg(timestamp, msgs):
    # find close timestamp from self.mflp_msgs
    closest_msg = None
    if msgs is None or len(msgs) == 0:
        return closest_msg
    
    sorted_keys = sorted(msgs.keys())
    pos = bisect.bisect_left(sorted_keys, timestamp)

    if pos == 0:
        closest_key = sorted_keys[0]
    elif pos == len(sorted_keys):
        closest_key = sorted_keys[-1]
    else:
        before = sorted_keys[pos - 1]
        after = sorted_keys[pos]
        closest_key = (
            before if abs(before - timestamp) <= abs(after - timestamp) else after
        )

    return msgs[closest_key]

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

def distort_image_with_new_intrinc(undistorted_img, new_camera_matrix, cameraMatrix, distCoeffs):
    image_size = undistorted_img.shape[:2][::-1]
    map_x, map_y = _get_distortion_map(image_size, cameraMatrix, distCoeffs, new_camera_matrix)
    return distort_image_with_distortion_map(undistorted_img, map_x, map_y)

def distort_image_with_new_intrinsic_gpu(undistorted_img: torch.Tensor,new_camera_matrix, cameraMatrix, distCoeffs):
    # undistorted_img: (C, H, W)
    image_size = undistorted_img.shape[1:]
    map_x, map_y = _get_distortion_map(image_size, cameraMatrix, distCoeffs, new_camera_matrix)
    map_x = torch.from_numpy(map_x).float().to(undistorted_img.device)
    map_y = torch.from_numpy(map_y).float().to(undistorted_img.device)
    return distort_image_with_distortion_map_gpu(undistorted_img, map_x, map_y)
    

def distort_image_with_distortion_map(undistorted_img, map_x, map_y):
    if undistorted_img.dtype == np.bool_:
        image_distort = cv2.remap(undistorted_img.astype(np.uint8), map_x, map_y, interpolation=cv2.INTER_NEAREST)
        image_distort = image_distort.astype(np.bool_)[:,:,None]
    else:
        image_distort = cv2.remap(undistorted_img, map_x, map_y, interpolation=cv2.INTER_LINEAR)
    return image_distort

def distort_image_with_distortion_map_gpu(undistorted_img: torch.Tensor, map_x: torch.Tensor, map_y: torch.Tensor):

    H_IN, W_IN = undistorted_img.shape[1:]
    map_x_norm = map_x / (W_IN - 1) * 2 - 1
    map_y_norm = map_y / (H_IN - 1) * 2 - 1
    grid = torch.stack((map_x_norm, map_y_norm), dim=-1).unsqueeze(0)
    mode = 'nearest' if undistorted_img.dtype == torch.bool else 'bilinear'
    undistorted_img = undistorted_img.float()
    distorted = F.grid_sample(
        undistorted_img.unsqueeze(0), # (B, C, H_in, W_in)
        grid, # (B, H_out, W_out, 2)
        mode=mode,
        padding_mode='border',
        align_corners=False
    )
    distorted = distorted.squeeze(0)

    if undistorted_img.dtype == torch.bool:
        distorted_uint8 = (distorted > 0.5).to(torch.bool)
    else:
        distorted_uint8 = torch.clamp(distorted.round(), 0, 255).to(torch.uint8)
    return distorted_uint8


def get_distortion_map(image_size, calib_info, cam):
    camera_matrix, dist_coeffs = get_camera_calib(calib_info[cam]["intrinsic"])
    if 'undistort_crop' in calib_info and calib_info['undistort_crop']:
        new_camera_matrix, _ = get_camera_calib(calib_info["noncrop"+cam]["intrinsic"])
        new_camera_matrix *= calib_info["expand_ratio"][cam]
        new_camera_matrix[2, 2] = 1
        image_size = [int(i*calib_info["expand_ratio"][cam]) for i in image_size]
    else:
        new_camera_matrix, _ = get_camera_calib(calib_info["new"+cam]["intrinsic"])

    return _get_distortion_map(image_size, camera_matrix, dist_coeffs, new_camera_matrix)

def _get_distortion_map(image_size, camera_matrix, dist_coeffs, new_camera_matrix):
    map_x = np.zeros(image_size, dtype=np.float32)
    map_y = np.zeros(image_size, dtype=np.float32)
    # 使用 np.meshgrid 生成 x 和 y 坐标
    x = np.arange(image_size[0], dtype=np.float32)  # 生成 x 坐标
    y = np.arange(image_size[1], dtype=np.float32)  # 生成 y 坐标

    # 使用 meshgrid 创建网格坐标
    xx, yy = np.meshgrid(x, y)

    # 组合为一个二维数组，形状为 (height * width, 2)
    pts_distort = np.stack((xx.ravel(), yy.ravel()), axis=-1)

    pts_distort = pts_distort.reshape(-1, 1, 2)
    pts_ud = cv2.undistortPoints(pts_distort, camera_matrix, dist_coeffs, R=None, P=new_camera_matrix)
    pts_ud = pts_ud.reshape(image_size[1], image_size[0], 2)
    map_x, map_y = pts_ud[..., 0], pts_ud[..., 1]
    return map_x, map_y

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


def get_expand_ratio(calib_info, force_reset=False):
    if force_reset or "expand_ratio" not in calib_info:
        calib_info["expand_ratio"] = _expand_ratio_dict
    return calib_info


def redistort(calib_info, cam, img, img_real, img_mask=None, distortion_maps=None): 
    expand_ratio = calib_info["expand_ratio"][cam]

    if distortion_maps is None:
        camera_matrix, dist_coeffs = get_camera_calib(calib_info[cam]["intrinsic"])
        new_camera_matrix, _ = get_camera_calib(calib_info["new"+cam]["intrinsic"])
        img_distort = distort_image_with_new_intrinc(img, new_camera_matrix, camera_matrix, dist_coeffs)
    else:
        # pad img bottom with black pixel
        desired_height = int(calib_info['noncrop'+cam]['height'] * expand_ratio)
        if img.shape[0] < desired_height:
            pad_height = desired_height - img.shape[0]
            img = np.pad(img, ((0, pad_height), (0, 0), (0, 0)), mode='constant', constant_values=0)
        img_distort = distort_image_with_distortion_map(img, distortion_maps[0], distortion_maps[1])

    img_distort = img_distort[:math.ceil(img.shape[0]/expand_ratio), :math.ceil(img.shape[1]/expand_ratio), :]
    # mask the distorted image
    if img_real is not None:
        if img_mask is None:
            img_mask = np.ones(img_distort.shape[:2], dtype=bool)
        img_distort[~img_mask] = img_real[~img_mask]  
    return img_distort

def redistort_gpu(calib_info: dict, 
                  cam: str, 
                  img: torch.Tensor, 
                  img_real: Optional[torch.Tensor], 
                  img_mask: Optional[torch.Tensor] = None, 
                  distortion_maps: Optional[tuple] = None):

    # 1. redistort operation
    expand_ratio = calib_info["expand_ratio"][cam]
    if distortion_maps is None:
        # currently this branch is not implemented and not tested
        camera_matrix, dist_coeffs = get_camera_calib(calib_info[cam]["intrinsic"])
        new_camera_matrix, _ = get_camera_calib(calib_info["new"+cam]["intrinsic"])
        img_distort = distort_image_with_new_intrinsic_gpu(img, new_camera_matrix, camera_matrix, dist_coeffs)
    else:
        desired_height = int(calib_info['noncrop'+cam]['height'] * expand_ratio)
        if img.shape[1] < desired_height:
            pad_height = desired_height - img.shape[1]
            img = torch.nn.functional.pad(img, (0, 0, 0, pad_height), mode='constant', value=0)
        img_distort = distort_image_with_distortion_map_gpu(img, distortion_maps[0], distortion_maps[1])

    # 2. crop the distorted image
    img_distort = img_distort[:,
                              :math.ceil(img.shape[1]/expand_ratio), 
                              :math.ceil(img.shape[2]/expand_ratio)
                              ]

    # 3. mask operation
    if img_real is not None:
        if img_mask is None:
            img_mask = torch.ones(img_distort.shape[1:], dtype=torch.bool, device=img_distort.device)
        img_mask = img_mask.to(img_distort.device)
        img_mask = img_mask.expand_as(img_distort)
        img_distort[~img_mask] = img_real[~img_mask]
    
    return img_distort

def undistort_image_with_new_intrinc(
        img, camera_matrix, dist_coeffs, expand=1., method=cv2.INTER_LINEAR, crop=False
    ):
    h, w = img.shape[:2]
    h_new, w_new = int(expand*h), int(expand*w)
    alpha = 0 if crop else 1
    new_camera_matrix, roi = cv2.getOptimalNewCameraMatrix(
        camera_matrix, dist_coeffs, (w, h), alpha, (w_new, h_new)
    )
    map1, map2 = cv2.initUndistortRectifyMap(
        camera_matrix, dist_coeffs, None, new_camera_matrix, (w_new, h_new), cv2.CV_32FC1
    )
    if img.dtype == np.bool_:
        undistorted_img = cv2.remap(img.astype(np.uint8), map1, map2, cv2.INTER_NEAREST)
        undistorted_img = undistorted_img.astype(np.bool_)[:,:,None]
    else:
        undistorted_img = cv2.remap(img, map1, map2, method)
    return undistorted_img, new_camera_matrix, roi


def get_transferpose_from_dds_json(localpose_sim_json_path, localpose_train):
    with open(localpose_sim_json_path, "r") as f:
        mflocalpose_list = json.load(f)
    mflocalposes = dict()

    for mflp in mflocalpose_list:
        timestamp = mflp["time_stamp"]['nsec'] 
        x = mflp["smooth_pose"]["pose"]['p']['x']
        y = mflp["smooth_pose"]["pose"]['p']['y']
        z = mflp["smooth_pose"]["pose"]['p']['z']
        translation = np.array([x, y, z])
        w = mflp["smooth_pose"]["pose"]['q']['w']
        x = mflp["smooth_pose"]["pose"]['q']['x']
        y = mflp["smooth_pose"]["pose"]['q']['y']
        z = mflp["smooth_pose"]["pose"]['q']['z']
        quaternion = np.array([w, x, y, z])
        mflocalpose = quaternion_matrix(quaternion)
        mflocalpose[:3, 3] = translation
        mflocalposes[timestamp] = mflocalpose

    sorted_mflocalposes = dict(sorted(mflocalposes.items(), key=lambda x: x[0]))
    train_localpose = {int(k):v for k, v in localpose_train.items()}
    calculated_transforms_over_time = {}
    for mf_timestamp, mf_pose in sorted_mflocalposes.items():
        interp_train_localpose = interpolate_pose_with_times(
            train_localpose, mf_timestamp
        )

        if interp_train_localpose is not None:
            transferpose = interp_train_localpose @ np.linalg.inv(mf_pose)
            calculated_transforms_over_time[tuple(mf_pose.ravel())] = transferpose

    return calculated_transforms_over_time, sorted_mflocalposes


def get_mflocalpose_from_dds_json(json_path, timestamps=None, localpose_train=None):
    with open(json_path, "r") as f:
        mflocalpose_list = json.load(f)
    mflocalposes = dict()

    for mflp in mflocalpose_list:
        timestamp = mflp["time_stamp"]['nsec'] 
        x = mflp["smooth_pose"]["pose"]['p']['x']
        y = mflp["smooth_pose"]["pose"]['p']['y']
        z = mflp["smooth_pose"]["pose"]['p']['z']
        translation = np.array([x, y, z])
        w = mflp["smooth_pose"]["pose"]['q']['w']
        x = mflp["smooth_pose"]["pose"]['q']['x']
        y = mflp["smooth_pose"]["pose"]['q']['y']
        z = mflp["smooth_pose"]["pose"]['q']['z']
        quaternion = np.array([w, x, y, z])
        mflocalpose = quaternion_matrix(quaternion)
        mflocalpose[:3, 3] = translation
        mflocalposes[timestamp] = mflocalpose
    
    sorted_localposes = dict(sorted(mflocalposes.items(), key=lambda x: x[0]))

    # align the localposes between train and sim
    if localpose_train is not None:
        # find the closest anchor timestamp
        timestamps_train = list(localpose_train.keys())
        closest_train_timestamp = min((abs(int(a) - b), a) for a in timestamps_train for b in list(sorted_localposes.keys()))[1]
        sim_anchored_localpose = lookup_pose(sorted_localposes, int(closest_train_timestamp), 0.1)
        train_anchor_localpose = localpose_train[closest_train_timestamp]
        for t, pose in sorted_localposes.items():
            sorted_localposes[t] = train_anchor_localpose @ np.linalg.inv(sim_anchored_localpose) @ pose

    new_timestamps = list(sorted_localposes.keys())
    if timestamps is not None:
        ret_poses = []
        ret_times = timestamps
        for t in timestamps:
            if t in sorted_localposes:
                ret_poses.append(sorted_localposes[t])
            else:
                print(f'[WARNING] timestamp {t} not found in mflocalposes')
                ret_poses.append(lookup_pose(sorted_localposes, t, 0.1))
    else:
        ret_poses = list(sorted_localposes.values())
        ret_times = new_timestamps
    ret_poses = np.array(ret_poses)
    ret_times = np.array(ret_times)
    return ret_poses, ret_times


def get_longitudinal_interpolated_egoposes(egoposes, timestamps, interval=0.08, stride=1):
    new_timestamps = np.arange(timestamps[0], timestamps[-1], int(interval*1e9))
    new_egoposes = np.zeros((len(new_timestamps), 4, 4))
    new_egoposes[:, 3, 3] = 1.
    # interpolate translation
    for i in range(3):
        new_egoposes[:, i, 3] = np.interp(new_timestamps, timestamps, egoposes[:, i, 3])
    # interpolate rotation using Slerp
    rotations = R.from_matrix(egoposes[:, :3, :3])
    slerp = Slerp(timestamps, rotations)
    new_rotations = slerp(new_timestamps)
    new_egoposes[:, :3, :3] = new_rotations.as_matrix()
    return new_egoposes[::stride], new_timestamps[::stride]


def get_lateral_shifted_egoposes(egoposes, shift_distance = 3.5, stride=1):
    displacements = np.diff(egoposes[:, :3, 3], axis=0)
    direction_norm = displacements / np.linalg.norm(displacements, axis=1)[:, None]
    direction_norm = np.vstack([direction_norm, direction_norm[-1]])

    perpendicular_vector = direction_norm.copy()
    perpendicular_vector[:, 0] = -direction_norm[:, 1]
    perpendicular_vector[:, 1] = direction_norm[:, 0]

    shift_vector = shift_distance * perpendicular_vector

    shift_matrix = np.tile(np.eye(4), (direction_norm.shape[0], 1, 1))
    shift_matrix[:, :3, 3] = shift_vector 

    shifted_egoposes = shift_matrix @ egoposes
    return shifted_egoposes[::stride]


def get_lateral_sin_waved_egoposes(egoposes, amplitude = 3.5, stride=1):
    displacements = np.diff(egoposes[:, :3, 3], axis=0)
    direction_norm = displacements / np.linalg.norm(displacements, axis=1)[:, None]
    direction_norm = np.vstack([direction_norm, direction_norm[-1]])

    perpendicular_vector = direction_norm.copy()
    perpendicular_vector[:, 0] = -direction_norm[:, 1]
    perpendicular_vector[:, 1] = direction_norm[:, 0]

    vectorized_function = np.vectorize(sine_and_line)
    sine_wave = vectorized_function(np.linspace(0, 2 * np.pi, direction_norm.shape[0]))
    shift_vector = amplitude * perpendicular_vector * sine_wave[:, None]

    shift_matrix = np.tile(np.eye(4), (direction_norm.shape[0], 1, 1))
    shift_matrix[:, :3, 3] = shift_vector 

    shifted_egoposes = shift_matrix @ egoposes
    return shifted_egoposes[::stride]


def sine_and_line(x):
    transition_point = 3 * np.pi / 2
    sine_value_at_transition = np.sin(transition_point)
    
    if x <= transition_point:
        return np.sin(x)
    else:
        return sine_value_at_transition


def lookup_pose(pose_buffer, tgt_ts, max_interval):
    next_ts = sys.maxsize
    prev_ts = 0
    for [src_ts, pose] in pose_buffer.items():
        if src_ts < tgt_ts:
            prev_ts = max(prev_ts, src_ts)
        elif src_ts > tgt_ts:
            next_ts = min(next_ts, src_ts)
        else:
            return pose

    if prev_ts not in pose_buffer and next_ts not in pose_buffer:
        print('prev and next not found for {}'.format(tgt_ts * 1e-9))
        return None

    if prev_ts not in pose_buffer:
        ts_diff = next_ts - tgt_ts
        if (next_ts - tgt_ts) * 1e-9 < max_interval:
            return pose_buffer[next_ts]
        print(f'prev not found for tgt_ts: {tgt_ts * 1e-9}, next_ts: {next_ts * 1e-9}, ts_diff: {ts_diff * 1e-9}')
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
    tgt_rotation = scipy.spatial.transform.Slerp([0, 1],
                                                scipy.spatial.transform.Rotation.from_matrix(
                                                    [prev_pose[0:3, 0:3], next_pose[0:3, 0:3]]))([ratio])

    tgt_quaternion = tgt_rotation[0].as_quat()
    tgt_pose = quaternion_matrix([tgt_quaternion[3], tgt_quaternion[0], tgt_quaternion[1], tgt_quaternion[2]])
    tgt_pose[:3, 3] = tgt_position
    return tgt_pose



def point_in_polygon(points, polygon_vertices):
    from scipy.spatial import cKDTree
    from shapely.geometry import Point, Polygon, LineString
    from shapely.ops import unary_union
    M = points.shape[0]
    N = polygon_vertices.shape[0]
    inside = torch.zeros(M, dtype=torch.bool, device=points.device)
    v = polygon_vertices
    v_next = torch.roll(v, -1, dims=0)  # [N, 2]，下一个顶点
    x, y = points[:, 0], points[:, 1]
    vx, vy = v[:, 0], v[:, 1]
    vx_next, vy_next = v_next[:, 0], v_next[:, 1]
    for i in range(N):
        y_min = torch.min(vy[i], vy_next[i])
        y_max = torch.max(vy[i], vy_next[i])
        in_y_range = (y > y_min) & (y <= y_max)
        dy = vy_next[i] - vy[i]
        dx = vx_next[i] - vx[i]
        non_zero_dy = dy != 0
        if not torch.any(non_zero_dy):
            continue
        
        m = dx / dy  # 斜率的倒数（x关于y的变化率）
        x_intersect = vx[i] + (y - vy[i]) * m  # 交点x坐标
        intersect_right = x_intersect > x
        inside = inside ^ (in_y_range & non_zero_dy & intersect_right)
    
    return inside

def split_ground_points_by_trajectory_segments(dds_positions, ground_xy, rect_width=25.0):
    from scipy.spatial import cKDTree
    from shapely.geometry import Point, Polygon, LineString
    from shapely.ops import unary_union
    # dds_positions = np.array([pose[:3, 3] for pose in self.egoposes_anchored_origin])
    traj_xy = dds_positions[:, :2]
    num_points = len(traj_xy)
    
    if num_points < 2:
        raise ValueError("轨迹点数量不足，无法分段")
    num_segs = 8
    diffs = np.diff(traj_xy, axis=0)  # [N-1, 2]
    segment_lengths = np.linalg.norm(diffs, axis=1)  # [N-1]
    cumulative_distances = np.concatenate([[0], np.cumsum(segment_lengths)])  # [N]
    total_length = cumulative_distances[-1]
    
    if total_length < 1e-6:
        raise ValueError("轨迹总长度接近零，无法分段")
    
    target_distances = np.linspace(0, total_length, num_segs + 1)  # [num_segs+1]
    segment_points = []
    for d in target_distances:
        idx = np.searchsorted(cumulative_distances, d, side='right')
        if idx == 0:
            point = traj_xy[0]
        elif idx >= num_points:
            point = traj_xy[-1]
        else:
            d_prev = cumulative_distances[idx - 1]
            d_next = cumulative_distances[idx]
            t = (d - d_prev) / (d_next - d_prev + 1e-8)
            point = (1 - t) * traj_xy[idx - 1] + t * traj_xy[idx]
        segment_points.append(point)
    
    segments = []
    for i in range(num_segs):
        p1 = segment_points[i]
        p2 = segment_points[i + 1]
        segments.append((p1, p2))
    actual_segments = []
    for idx, (p1, p2) in enumerate(segments):
        line_vec = p2 - p1
        line_len = np.linalg.norm(line_vec)
        
        if idx == len(segments) - 1:  # 最后一段
            if line_len < 1e-6:
                if len(traj_xy) >= 2:
                    last_dir = traj_xy[-1] - traj_xy[-2]
                    last_dir_norm = np.linalg.norm(last_dir)
                    if last_dir_norm > 1e-6:
                        direction = last_dir / last_dir_norm
                    else:
                        direction = np.array([1.0, 0.0])
                else:
                    direction = np.array([1.0, 0.0])
            else:
                direction = line_vec / line_len
            p2 = p2 + direction * 100.0  # 延伸
        
        actual_segments.append((p1, p2))

    key_points = []
    for i, (start, end) in enumerate(actual_segments):
        if i == 0:
            key_points.append(start)
        key_points.append(end)  # 最后一个 end 是延伸后的

    side_lines = []  # 每个关键点: [left, right]
    for i, pt in enumerate(key_points):
        if i == 0:
            seg_dir = actual_segments[0][1] - actual_segments[0][0]
        elif i == len(key_points) - 1:
            seg_dir = actual_segments[-1][1] - actual_segments[-1][0]
        else:
            seg_dir = actual_segments[i-1][1] - actual_segments[i-1][0]
        
        if np.linalg.norm(seg_dir) < 1e-6:
            perp_norm = np.array([0.0, 1.0])
        else:
            perp = np.array([-seg_dir[1], seg_dir[0]])
            perp_norm = perp / np.linalg.norm(perp)
        left_pt  = pt - perp_norm * (rect_width / 2)
        right_pt = pt + perp_norm * (rect_width / 2)
        side_lines.append(np.array([left_pt, right_pt]))

    quad_regions = []
    for i in range(len(side_lines) - 1):
        l1, r1 = side_lines[i]      # 第 i 个截面
        l2, r2 = side_lines[i + 1]  # 第 i+1 个截面
        quad = np.array([l1, l2, r2, r1])
        quad_regions.append(quad)

    rect_vertices = quad_regions
    union_regions_vertices = []
    for i in range(num_segs):
        current_rect = Polygon(rect_vertices[i])
        if i > 0:
            prev_union = unary_union([Polygon(v) for v in rect_vertices[:i]])
            current_rect = current_rect.difference(prev_union)
            if current_rect.geom_type == 'Polygon':
                vertices = np.array(current_rect.exterior.coords)[:-1]  # 移除闭合点
            elif current_rect.geom_type == 'MultiPolygon':
                vertices = np.array(list(current_rect.geoms)[0].exterior.coords)[:-1]
            else:
                vertices = np.array([])  # 空区域
        else:
            vertices = rect_vertices[i]
        union_regions_vertices.append(vertices)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    # ground_xy = self.gaussian.models["Ground"].get_xyz.detach().cpu().numpy()[:, :2]
    ground_points = torch.tensor(ground_xy, dtype=torch.float32, device=device)
    M = ground_points.shape[0]
    polygon_vertices_gpu = []
    for vertices in union_regions_vertices:
        if len(vertices) == 0:
            polygon_vertices_gpu.append(None)
            continue
        poly_tensor = torch.tensor(vertices, dtype=torch.float32, device=device)
        polygon_vertices_gpu.append(poly_tensor)
    region_masks = [torch.zeros(M, dtype=torch.bool, device=device) for _ in range(num_segs)]
    for i in range(num_segs):
        poly_vertices = polygon_vertices_gpu[i]
        if poly_vertices is None or len(poly_vertices) < 3:  # 至少3个顶点才是有效多边形
            continue
        mask = point_in_polygon(ground_points, poly_vertices)
        region_masks[i] = mask & ~torch.any(torch.stack(region_masks[:i+1]), dim=0)
    return region_masks,polygon_vertices_gpu


def _log_gpu_memory(tag, device, *, reset_peak_after=False, report_peak=False):
    """在同步 GPU 后打印当前设备的已分配/缓存显存（GiB）。

    cuda_free / cuda_total：驱动 cudaMemGetInfo 报告的全局空闲/总显存（该 GPU 上所有进程共享）。
    reset_peak_after: 打印后重置峰值统计，便于 report_peak 只统计后续区间（如一次 render）。
    report_peak: 打印自上次 reset_peak_memory_stats 以来的 max_memory_allocated（张量占用峰值）。
    """
    if not torch.cuda.is_available():
        print(f"[GPU memory {tag}] CUDA 不可用", flush=True)
        return
    dev = torch.device(device)
    if dev.type != "cuda":
        print(f"[GPU memory {tag}] 非 CUDA 设备 {device}，跳过", flush=True)
        return
    torch.cuda.synchronize(dev)
    alloc_gib = torch.cuda.memory_allocated(dev) / (1024**3)
    reserved_gib = torch.cuda.memory_reserved(dev) / (1024**3)
    free_b, total_b = torch.cuda.mem_get_info(dev)
    free_gib = free_b / (1024**3)
    total_gib = total_b / (1024**3)
    parts = [
        f"allocated={alloc_gib:.3f} GiB",
        f"reserved={reserved_gib:.3f} GiB",
        f"cuda_free={free_gib:.3f} GiB cuda_total={total_gib:.3f} GiB",
    ]
    if report_peak:
        peak_gib = torch.cuda.max_memory_allocated(dev) / (1024**3)
        parts.append(f"peak_allocated={peak_gib:.3f} GiB")
    print(f"[GPU memory {tag}] " + " ".join(parts), flush=True)
    if reset_peak_after:
        torch.cuda.reset_peak_memory_stats(dev)

