import argparse
import json
import math
import os
import re
import shutil
import yaml
import numpy as np
import cv2
import matplotlib.pyplot as plt
from scipy.spatial.transform import Rotation as R
from scipy.spatial import KDTree
from copy import deepcopy

vehicle_type_list = ['e38', 'e28a', 'f30', 'h93', 'f57', 'f01', 'e29', 'e38b', 'd01m']

calibration_map = {
    "front_narrow": "cam0",
    "front_fisheye" : "cam2",
    "side_front_left"   : "cam3",
    "side_front_right"  : "cam4",
    "side_rear_left"    : "cam5",
    "side_rear_right"   : "cam6",
    "rear_main"  : "cam7",
}
vehicle_model_map = {
    21: "e28a",
    40: "e38",
    43: "e38",
    50: "f30",
    60: "h93",
    70: "f57",
    200: "e28a",
    202: "e38",
    204: "e38",
    206: "f30",
    207: "f30",
    208: "f57",
    209: "h93",
    205: "f01",
    201: "e29",
    203: "e38b",
    210: "h93",
    212: "d01m",
}

def create_trip_from_clip_list(data_dir, clip_list):
    trip_meta_dict = dict()
    for clip_id in clip_list:
        meta_path = os.path.join(data_dir, clip_id, 'metadata.json')
        if not os.path.exists(meta_path):
            print(f'No metadata.json found in {os.path.join(data_dir, clip_id)}, ignore clip: {clip_id}')
            continue
        clip_metadata = json.load(open(meta_path, 'r'))
        vehicle_name = clip_metadata["vehicle_name"]
        if vehicle_name not in trip_meta_dict:
            trip_meta_dict[vehicle_name] = dict()
        description_file = clip_metadata["description_file"]
        if description_file not in trip_meta_dict[vehicle_name]:
            trip_meta_dict[vehicle_name][description_file] = []
        trip_meta_dict[vehicle_name][description_file].append(clip_metadata)

    for vehicle_name, trips in trip_meta_dict.items():
        sorted_trips = dict()
        for collection_time, trip in trips.items():
            sorted_trip = sorted(trip, key=lambda x: x['seq_num'])
            if len(sorted_trip) < 2:
                sorted_trips[sorted_trip[0]['start_time']] = sorted_trip
                continue

            prev_seq_num = sorted_trip[0]['seq_num']
            trip_start_time = sorted_trip[0]['start_time']
            sorted_trips[trip_start_time] = [sorted_trip[0]]
            for i in range(1, len(sorted_trip)):
                if sorted_trip[i]['seq_num'] == prev_seq_num + 1:
                    sorted_trips[trip_start_time].append(sorted_trip[i])
                else:
                    trip_start_time = sorted_trip[i]['start_time']
                    sorted_trips[trip_start_time] = [sorted_trip[i]]
                prev_seq_num = sorted_trip[i]['seq_num']
        trip_meta_dict[vehicle_name] = sorted_trips

    return trip_meta_dict

def compute_between_pose_dist_and_angle(pose1, pose2):
    pose_matrix1= np.array(pose1)
    pose_matrix2= np.array(pose2)

    distance_diff = np.linalg.norm(pose_matrix1[0:3,3] - pose_matrix2[0:3,3])
    angle_diff = np.arccos(np.clip((np.trace(pose_matrix1[0:3,0:3].T @ pose_matrix2[0:3,0:3]) - 1.0) / 2.0, -1.0, 1.0))

    return distance_diff, angle_diff

def replace_translation_calibration(yaml_info, calib_json, given_vehicle):
    if not yaml_info or given_vehicle not in vehicle_type_list:
        return calib_json

    for vehicle in yaml_info["vehicle"]:
        if vehicle["vehicle_name"] == given_vehicle:
            for camera_info in vehicle["camera"]:
                camera_index = calibration_map[camera_info["name"]]
                camera_calib = np.array(calib_json[camera_index]["extrinsic"]["transformation_matrix"])
                camera_position = np.array(camera_info["position"])/1000
                camera_calib_inv = np.linalg.inv(camera_calib)
                camera_calib_inv[:3, 3] = camera_position
                calib_json[camera_index]["extrinsic"]["transformation_matrix"] = np.linalg.inv(camera_calib_inv).tolist()
                print("replace {}---{},finshed".format(vehicle["vehicle_name"], camera_index))
    return calib_json

def get_calibration_diff(yaml_info, calib_json, given_vehicle):
    if not yaml_info or given_vehicle not in vehicle_type_list:
        return {}
    calibration_diff = dict()
    for vehicle in yaml_info["vehicle"]:
        if vehicle["vehicle_name"] == given_vehicle:
            calibration_diff["translation"] = dict()
            calibration_diff["rotation"] = dict()
            for camera_info in vehicle["camera"]:
                camera_index = calibration_map[camera_info["name"]]
                camera_calib = np.array(calib_json[camera_index]["extrinsic"]["transformation_matrix"])
                camera_position = np.array(camera_info["position"])/1000
                camera_calib_inv = np.linalg.inv(camera_calib)
                camera_position_diff = camera_calib_inv[:3, 3] - camera_position
                calibration_diff["translation"][camera_index] = camera_position_diff.tolist()

                camera_calib_rotation = R.from_matrix(camera_calib_inv[:3, :3]).as_euler('xyz', degrees=True)
                camera_calib_rotation = camera_calib_rotation[[1,2,0]]
                camera_rotation = np.array(camera_info["angle"])
                camera_rotation_diff = camera_calib_rotation - camera_rotation
                calibration_diff["rotation"][camera_index] = camera_rotation_diff.tolist()
    return calibration_diff

def merge_calib_json(original_calib_json, merge_calib_json, original_slice_id, merge_slice_id):
    for item in ['local_pose', 'global_pose']:
        if item not in original_calib_json:
            print(f'fail to find {item} in original calib.json')
            continue
        if original_slice_id in original_calib_json[item]:
            if item not in merge_calib_json:
                merge_calib_json[item] = dict()
            merge_calib_json[item][merge_slice_id] = original_calib_json[item][original_slice_id]

def create_image_link(original_data_path, exp_data_path, cam_list, original_slice_name, 
                      merge_slice_name, mapping_dict, data_dir, clip_calib_json, timestamp_idx):
    original_image_timestamps_file_path = os.path.join(original_data_path, "image_timestamps.json")
    original_image_timestamps = json.load(open(original_image_timestamps_file_path, 'r'))

    original_image_slice_ids_file_path = os.path.join(original_data_path, "image_slice_ids.json")
    original_image_slice_ids = json.load(open(original_image_slice_ids_file_path, 'r'))

    image_timestamps = {cam: {} for cam in cam_list}
    image_slice_ids = {cam: {} for cam in cam_list}

    avm_list = ["cam9", "cam10", "cam11", "cam12"]

    for item in ['image', 'seg_mask', 'seg_mask_static']:
        original_image_path = os.path.join(original_data_path, item)
        target_image_path = os.path.join(exp_data_path, item)

        if not os.path.exists(original_image_path):
            print(f'fail to find original image path: {original_image_path}')
            continue

        match = re.match(r'slice(\d+)', original_slice_name)
        if not match:
            continue
        slice_idx = int(match.group(1))
        for cam_name in cam_list:
            target_cam_dir = os.path.join(target_image_path, cam_name)
            os.makedirs(target_cam_dir, exist_ok=True)
            image_name = f'slice{slice_idx}_{cam_name}.png'
            valid_slice_idx = int(match.group(1))

            if cam_name in avm_list:
                target_cam_dir_raw = os.path.join(target_image_path, cam_name + "_raw")
                os.makedirs(target_cam_dir_raw, exist_ok=True)
                raw_image_name = f'slice{slice_idx}_{cam_name}_raw.png'
                raw_real_path = os.path.realpath(os.path.join(original_image_path, raw_image_name))
                if os.path.exists(raw_real_path):
                    raw_target_path = os.path.join(target_cam_dir_raw, merge_slice_name + '.png')
                    if os.path.exists(raw_target_path) or os.path.islink(raw_target_path):
                        os.unlink(raw_target_path)
                    os.symlink(raw_real_path, raw_target_path)

            if item == 'image':
                tmp_info_dict = {}
                tmp_info_dict['slice_idx'] = str(slice_idx)
                tmp_info_dict['cam_id'] = cam_name
                if "slice_id" in clip_calib_json:
                    tmp_info_dict['slice_id'] = clip_calib_json["slice_id"][timestamp_idx]
                else:
                    tmp_info_dict['slice_id'] = 'UNKNOWN'
                mapping_dict[os.path.join(cam_name, merge_slice_name + '.png')] = tmp_info_dict

                image_timestamp = original_image_timestamps[cam_name][valid_slice_idx]
                image_timestamps[cam_name][merge_slice_name] = image_timestamp

                image_slice_id = original_image_slice_ids[cam_name][valid_slice_idx]
                image_slice_ids[cam_name][merge_slice_name] = image_slice_id

            real_path = None
            file_ext = '.png'
            real_path = os.path.realpath(os.path.join(original_image_path, image_name))
            if not os.path.exists(real_path):
                if item == 'seg_mask_static':
                    npy_image_name = f'slice{slice_idx}_{cam_name}.npy'
                    npy_real_path = os.path.realpath(os.path.join(original_image_path, npy_image_name))
                    if os.path.exists(npy_real_path):
                        real_path = npy_real_path
                        file_ext = '.npy'
                    else:
                        # print(f'Warning: fail to find original {item} path for {cam_name}: {image_name} or {npy_image_name}, skipping...')
                        continue
                else:
                    raise FileNotFoundError(f'fail to find original {item} path: {real_path}')
            
            target_link_path = os.path.join(target_cam_dir, merge_slice_name + file_ext)
            if os.path.exists(target_link_path) or os.path.islink(target_link_path):
                os.unlink(target_link_path)            
            os.symlink(real_path, target_link_path)
    return image_timestamps, image_slice_ids

def create_pcd_link(original_data_path, exp_data_path, lidar_list, original_slice_name, merge_slice_name):
    for lidar_name in lidar_list:
        original_pcd_path = os.path.join(original_data_path, "pcd", f"{original_slice_name}_{lidar_name}.pcd")
        if not os.path.exists(original_pcd_path):
            print(f'fail to find original pcd path: {original_pcd_path}')
            return
        target_pcd_dir = os.path.join(exp_data_path, "pcd", lidar_name)
        os.makedirs(target_pcd_dir, exist_ok=True)
        target_pcd_path = os.path.join(target_pcd_dir, f"{merge_slice_name}.pcd")
        original_pcd_real_path = os.path.realpath(original_pcd_path)
        if os.path.exists(target_pcd_path) or os.path.islink(target_pcd_path):
            os.unlink(target_pcd_path)
        os.symlink(original_pcd_real_path, target_pcd_path)

def traj_alignment(from_points, to_points):
    assert len(from_points.shape) == 2, \
        "from_points must be a m x n array"
    assert from_points.shape == to_points.shape, \
        "from_points and to_points must have the same shape"

    N, m = from_points.shape
    mean_from = from_points.mean(axis=0)
    mean_to = to_points.mean(axis=0)
    delta_from = from_points - mean_from  # N x m
    delta_to = to_points - mean_to  # N x m
    sigma_from = (delta_from * delta_from).sum(axis=1).mean()
    cov_matrix = delta_to.T.dot(delta_from) / N
    U, d, V_t = np.linalg.svd(cov_matrix, full_matrices=True)
    cov_rank = np.linalg.matrix_rank(cov_matrix)
    S = np.eye(m)

    if cov_rank >= m - 1 and np.linalg.det(cov_matrix) < 0:
        S[m - 1, m - 1] = -1
    elif cov_rank < m - 1:
        raise ValueError("colinearility detected in covariance matrix:\n{}".format(cov_matrix))

    R = U.dot(S).dot(V_t)
    c = (d * S.diagonal()).sum() / sigma_from
    t = mean_to - c * R.dot(mean_from)
    R = c * R
    residual = np.linalg.norm(np.dot(from_points, R.T) + t - to_points, axis=1)

    return R, t, residual

def calculate_clip_distance(local_pose_json):
    try:
        start_pt = local_pose_json[0]["local_pose_info"]["local_pose"]["p"]
        end_pt = local_pose_json[-1]["local_pose_info"]["local_pose"]["p"]
        start_pt = np.array([start_pt["x"], start_pt["y"]])
        end_pt = np.array([end_pt["x"], end_pt["y"]])
        distance = np.linalg.norm(start_pt - end_pt)
        return distance
    except:
        return 0

def filter_invalid_local_pose_trip(trip_paths, original_data_dir, exp_dir):
    filtered_paths = {}
    dist_thres = 0.1

    for trip_path, clips in trip_paths.items():
        local_pose_xy_list = []
        smooth_pose_xy_list = []
        for clip in clips.values():
            local_pose_json = json.load(open(os.path.join(original_data_dir, "LocalPoseTopic.json"), "r"))

            clip_distance = calculate_clip_distance(local_pose_json)
            if clip_distance < dist_thres:
                print(f"trip: {trip_path} filtered: distance too short ({clip_distance} < {dist_thres})")
                continue

            prev_local_pose_xy = None
            for slice in local_pose_json:
                if "local_pose_info" not in slice or "smooth_pose_info" not in slice:
                    break
                local_pose_info = slice["local_pose_info"]
                local_pose_xy = np.array([local_pose_info["local_pose"]["p"]["x"], local_pose_info["local_pose"]["p"]["y"]])
                smooth_pose_info = slice["smooth_pose_info"]
                smooth_pose_xy = np.array([smooth_pose_info["local_pose"]["p"]["x"], smooth_pose_info["local_pose"]["p"]["y"]])
                if prev_local_pose_xy is not None:
                    movement = np.linalg.norm(local_pose_xy - prev_local_pose_xy)
                    if movement < dist_thres:
                        continue
                prev_local_pose_xy = local_pose_xy
                local_pose_xy_list.append(local_pose_xy)
                smooth_pose_xy_list.append(smooth_pose_xy)
        
        if len(local_pose_xy_list) == 0 or len(smooth_pose_xy_list) == 0:
            print(f"trip: {trip_path} filtered: pose list is empty (local_pose: {len(local_pose_xy_list)}, smooth_pose: {len(smooth_pose_xy_list)})")
            filtered_paths[trip_path] = clips
            continue

        local_pose_xy_list = np.array(local_pose_xy_list)
        smooth_pose_xy_list = np.array(smooth_pose_xy_list)
        rotation, translation, residual = traj_alignment(local_pose_xy_list, smooth_pose_xy_list)
        print(f"trip: {trip_path}")
        print(f"residual min/max/mean/norm: {residual.min()}/{residual.max()}/{residual.mean()}/{np.linalg.norm(residual) / residual.shape[0]}")

        output_path = os.path.join(exp_dir, 'summary', '/'.join(trip_path.split('/')[-2:]))
        if not os.path.exists(output_path):
            os.makedirs(output_path, exist_ok=True)
        np.savetxt(os.path.join(output_path, "local_pose_smooth_pose_alignment_residual.csv"), residual, delimiter=",", fmt="%.2f")

        local_pose_points = np.dot(local_pose_xy_list, rotation.T) + translation

        title = '_'.join(trip_path.split('/')[-2:])
        fig = plt.figure(title)
        plt.plot(local_pose_points[:, 0], local_pose_points[:, 1], "-*", label="transformed_local_pose")
        plt.plot(smooth_pose_xy_list[:, 0], smooth_pose_xy_list[:, 1], "-*", label="smooth_pose")
        plt.axis('equal')
        plt.grid()
        plt.legend()
        plt.title(title)
        plt.savefig(os.path.join(output_path, "smooth_local_pose_alignment.png"), dpi=200)
        plt.close(fig)

        if residual.max() < 20.0 and residual.mean() < 5.0:
            filtered_paths[trip_path] = clips
            print(f"trip: {trip_path} passed filter, added to results")
        else:
            print(f"trip: {trip_path}/{clips} filtered: alignment residual too large (max: {residual.max():.2f}, mean: {residual.mean():.2f})")

    print(f"filtering completed, final retained {len(filtered_paths)} trips")
    return filtered_paths

def is_slice_downsample_valid(pose, prev_pose, slice_distance_diff_threshold, slice_angle_diff_threshold):
    if prev_pose is None:
        return True
    [distance_diff, angle_diff] = compute_between_pose_dist_and_angle(pose, prev_pose)
    if distance_diff < slice_distance_diff_threshold and math.degrees(angle_diff) < slice_angle_diff_threshold:
        return False
    return True

def _parse_clip_dir_from_data_dir(data_dir):
    clip_dir = data_dir
    if clip_dir.endswith('/vision/data'):
        clip_dir = clip_dir[:-len('/vision/data')]
    elif clip_dir.endswith('/recon'):
        clip_dir = clip_dir[:-len('/recon')]
    else:
        clip_dir = re.sub(r'/vision/data$', '', clip_dir)
        clip_dir = re.sub(r'/recon$', '', clip_dir)
    
    return clip_dir

def _create_symlink_safe(source_path, link_path):
    if not os.path.exists(source_path):
        print(f"Warning: Source path does not exist: {source_path}")
        return False

    if os.path.exists(link_path) or os.path.islink(link_path):
        if os.path.islink(link_path):
            os.unlink(link_path)
        elif os.path.isdir(link_path):
            shutil.rmtree(link_path)
        else:
            os.remove(link_path)

    try:
        os.symlink(source_path, link_path)
        # print(f"Created symlink: {link_path} -> {source_path}")
        return True
    except OSError as e:
        print(f"Failed to create symlink {link_path} -> {source_path}: {e}")
        return False

def create_vision_image_link(data_dir):
    base_path = _parse_clip_dir_from_data_dir(data_dir)

    os.makedirs(os.path.join(data_dir, 'image'), exist_ok=True)
    os.makedirs(os.path.join(data_dir, 'seg_mask'), exist_ok=True)
    os.makedirs(os.path.join(data_dir, 'seg_mask_static'), exist_ok=True)

    print(f"Base path for vision links: {base_path}")

    link_mappings = [
        {
            'link_path': os.path.join(data_dir, 'image'),
            'target_path': os.path.join(base_path, 'images_vision')
        },
        {
            'link_path': os.path.join(data_dir, 'seg_mask'),
            'target_path': os.path.join(base_path, 'segs_vision')
        },
        {
            'link_path': os.path.join(data_dir, 'seg_mask_static'),
            'target_path': os.path.join(base_path, 'segs_vision_static')
        }
    ]

    success_count = 0
    for mapping in link_mappings:
        link_path = mapping['link_path']
        target_path = mapping['target_path']
        if _create_symlink_safe(target_path, link_path):
            success_count += 1

    print(f"Vision image links created successfully ({success_count}/{len(link_mappings)} links created)")

def create_json_link(data_dir):
    clip_dir = _parse_clip_dir_from_data_dir(data_dir)
    
    json_files = ['calib.json', 'LocalPoseTopic.json', 'metadata.json']
    
    success_count = 0
    for json_file in json_files:
        source_path = os.path.join(clip_dir, json_file)
        link_path = os.path.join(data_dir, json_file)
        
        if _create_symlink_safe(source_path, link_path):
            success_count += 1
    
    print(f"JSON file links created successfully ({success_count}/{len(json_files)} links created)")
    
def _load_json_safe(json_path, default=None):
    if not os.path.exists(json_path):
        print(f"Warning: JSON file not found at {json_path}")
        return default

    try:
        with open(json_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading JSON from {json_path}: {e}")
        return default

def _get_cam_list_from_calib(calib_json):
    cam_list = []
    cam_to_ignore = ['cam9', 'cam10', 'cam11', 'cam12', 'cam_image_size']
    
    for key in calib_json.keys():
        if key.startswith('cam') and key not in cam_to_ignore:
            cam_list.append(key)
    
    return cam_list

def create_image_timestamps(data_dir):
    clip_dir = _parse_clip_dir_from_data_dir(data_dir)
    timestamp2slice_path = os.path.join(clip_dir, "timestamp2slice.json")
    timestamp2slice = _load_json_safe(timestamp2slice_path, {})
    if not timestamp2slice:
        return

    slice2timestamp = {}
    for timestamp_str, slice_idx in timestamp2slice.items():
        slice2timestamp[slice_idx] = int(timestamp_str)

    calib_path = os.path.join(clip_dir, "calib.json")
    calib_json = _load_json_safe(calib_path, {})
    if not calib_json:
        return

    cam_list = _get_cam_list_from_calib(calib_json)
    
    if not cam_list:
        print(f"Warning: No camera found in calib.json")
        return

    sorted_slice_indices = sorted(slice2timestamp.keys())
    timestamp_array = [slice2timestamp[idx] for idx in sorted_slice_indices]

    image_timestamps = {}
    for cam_name in cam_list:
        image_timestamps[cam_name] = timestamp_array
    
    output_path = os.path.join(data_dir, "image_timestamps.json")
    json.dump(image_timestamps, open(output_path, 'w+'), indent=4)
    print(f"Created image_timestamps.json at {output_path} with {len(timestamp_array)} timestamps")

def create_image_slice_ids(data_dir):
    clip_dir = _parse_clip_dir_from_data_dir(data_dir)
    timestamp2slice_path = os.path.join(clip_dir, "timestamp2slice.json")
    timestamp2slice = _load_json_safe(timestamp2slice_path, {})
    if not timestamp2slice:
        return

    calib_path = os.path.join(clip_dir, "calib.json")
    calib_json = _load_json_safe(calib_path, {})
    if not calib_json:
        return
    
    if 'slice_id' not in calib_json:
        print(f"Warning: slice_id field not found in calib.json")
        return
    
    slice_id_dict = calib_json['slice_id']
    slice_idx_to_id = {}
    for timestamp_str, slice_id in slice_id_dict.items():
        if timestamp_str in timestamp2slice:
            slice_idx = timestamp2slice[timestamp_str]
            slice_idx_to_id[slice_idx] = slice_id

    sorted_slice_indices = sorted(slice_idx_to_id.keys())
    slice_id_array = [slice_idx_to_id[idx] for idx in sorted_slice_indices]

    cam_list = _get_cam_list_from_calib(calib_json)
    
    if not cam_list:
        print(f"Warning: No camera found in calib.json")
        return

    image_slice_ids = {}
    for cam_name in cam_list:
        image_slice_ids[cam_name] = slice_id_array

    output_path = os.path.join(data_dir, "image_slice_ids.json")
    json.dump(image_slice_ids, open(output_path, 'w+'), indent=4)
    print(f"Created image_slice_ids.json at {output_path} with {len(slice_id_array)} slice IDs")

def prepare_workspace(cfg):
    exp_dir = cfg['exp_dir']
    data_dir = cfg["base_dir"]
    clip_id = cfg.get("clip_id", None)

    cam_list = deepcopy(cfg["cam_list"])

    slice_distance_diff_threshold = cfg.get("slice_distance_diff_threshold", 0)
    slice_angle_diff_threshold = cfg.get("slice_angle_diff_threshold", 0)
    filter_trip_by_smooth_local_pose_alignment = cfg.get("filter_trip_by_smooth_local_pose_alignment", True)

    create_vision_image_link(data_dir)

    create_json_link(data_dir)

    clip_calib_json = _load_json_safe(os.path.join(data_dir, 'calib.json'), {})
    if not clip_calib_json:
        raise Exception(f"Failed to load calib.json from {data_dir}")

    metadata_path = os.path.join(data_dir, 'metadata.json')
    metadata = _load_json_safe(metadata_path, {})

    vehicle_model_id = metadata.get('vehicle_model', 0)
    vehicle_name = metadata.get('vehicle_name', 'unknown_vehicle')
    trip_start_time = metadata.get('start_time', 0)
    seq_num = metadata.get('seq_num', 0)

    if not metadata:
        print(f"metadata.json not found for clip {clip_id}, using default values")

    if vehicle_model_id not in vehicle_model_map:
        vehicle_model = vehicle_model_id
    else:
        vehicle_model = vehicle_model_map[vehicle_model_id]

    trip_path_key = os.path.join('image', vehicle_name, str(trip_start_time))
    trip_paths = {
        trip_path_key: {seq_num: clip_id}
    }

    if filter_trip_by_smooth_local_pose_alignment:
        trip_paths = filter_invalid_local_pose_trip(trip_paths, data_dir, exp_dir)

    if len(trip_paths) == 0:
        raise Exception("No input trip found.")

    json.dump(trip_paths, open(os.path.join(exp_dir, 'input_trips.json'), 'w+'), indent=4)

    vehicle_calibration = yaml.load(open(cfg["vehicle_calibration_path"]), Loader=yaml.FullLoader)

    create_image_timestamps(data_dir)

    create_image_slice_ids(data_dir)

    mapping_dict = {}
    lidar_list = cfg.get("lidar_list", [])

    image_timestamps = {cam: {} for cam in cam_list}
    image_slice_ids = {cam: {} for cam in cam_list}

    for trip_path, clips in trip_paths.items():
        slice_id_base = 0
        merged_calib_json = {}
        prev_slice_local_pose = None

        clip_dir = _parse_clip_dir_from_data_dir(data_dir)

        timestamp2slice_path = os.path.join(clip_dir, "timestamp2slice.json")
        timestamp2slice = _load_json_safe(timestamp2slice_path, {})

        for seq_num, clip_id in clips.items():
            clip_calib_json = _load_json_safe(os.path.join(data_dir, 'calib.json'), {})
            if not clip_calib_json:
                print(f"Warning: Failed to load calib.json for {clip_id}, skipping")
                continue

            if len(merged_calib_json) == 0:
                for key, value in clip_calib_json.items():
                    if key != 'local_pose' and key != 'global_pose':
                        merged_calib_json[key] = value

            for timestamp_idx, pose in clip_calib_json['local_pose'].items():
                if timestamp_idx in timestamp2slice:
                    original_slice_idx = timestamp2slice[timestamp_idx]
                    slice_name = 'slice{}'.format(original_slice_idx)
                else:
                    print(f"Warning: timestamp {timestamp_idx} not found in timestamp2slice.json, skipping")
                    continue

                if not is_slice_downsample_valid(pose, prev_slice_local_pose, slice_distance_diff_threshold, slice_angle_diff_threshold):
                    continue
                merge_slice_name = 'slice{}'.format(slice_id_base)
                merge_calib_json(clip_calib_json, merged_calib_json, timestamp_idx, merge_slice_name)

                slice_image_timestamps, slice_image_slice_ids = create_image_link(data_dir, exp_dir, cam_list, slice_name, 
                                                                                  merge_slice_name, mapping_dict, data_dir, clip_calib_json, timestamp_idx)

                for cam in cam_list:
                    image_timestamps[cam].update(slice_image_timestamps[cam])
                    image_slice_ids[cam].update(slice_image_slice_ids[cam])

                if lidar_list:
                    create_pcd_link(data_dir, exp_dir, lidar_list, slice_name, merge_slice_name)
                prev_slice_local_pose = pose
                slice_id_base += 1

        calibration_diff = get_calibration_diff(vehicle_calibration, merged_calib_json, vehicle_model)
        if calibration_diff:
            merged_calib_json["calibration_diff"] = calibration_diff
        else:
            merged_calib_json["calibration_diff"] = vehicle_model

        if cfg.get('replace_translation_calibration', False):
            merged_calib_json = replace_translation_calibration(vehicle_calibration, merged_calib_json, vehicle_model)

        merged_calib_json["cam_image_size"] = {}
        current_trip_image_dir = os.path.join(exp_dir, 'image')
        for cam in cam_list:
            image_filename = os.path.join(current_trip_image_dir, cam, "slice0.png")
            if os.path.exists(image_filename):
                image = cv2.imread(image_filename)
                merged_calib_json["cam_image_size"][cam] = [image.shape[0], image.shape[1]]
        merged_calib_json_path = '{}'.format(os.path.join(current_trip_image_dir, 'calib.json'))
        print(f'{merged_calib_json_path} dumped')
        json.dump(merged_calib_json, open(merged_calib_json_path, 'w+'), indent=4)
        json.dump(mapping_dict, open(os.path.join(exp_dir, 'original_image_mapping.json'), 'w+'), indent=4)

        merged_timestamps_path = os.path.join(current_trip_image_dir, 'image_timestamps.json')
        json.dump(image_timestamps, open(merged_timestamps_path, 'w+'), indent=4)

        merged_slice_ids_path = os.path.join(current_trip_image_dir, 'image_slice_ids.json')
        json.dump(image_slice_ids, open(merged_slice_ids_path, 'w+'), indent=4)

    with open(os.path.join(exp_dir, 'input_trips.json'), 'r') as trip_f:
        trip_paths = json.load(trip_f)
        if cfg.get('check_calibration', True):
            valid_trip_paths = []
            for trip_path in list(trip_paths.keys()):
                calib_path = os.path.join(exp_dir, 'image', 'calib.json')
                valid_trip = True
                max_angle_diff_thr = cfg.get('max_angle_diff_thr', 5.0) # degree   
                with open(calib_path, 'r') as calib_f:
                    calib_json = json.load(calib_f)
                    ### Check calibration_diff
                    if isinstance(calib_json['calibration_diff'], int):
                        valid_trip = False
                    else:
                        rot_diff = calib_json['calibration_diff']['rotation']
                        for cam, values in rot_diff.items():
                            values = np.array(values)
                            if np.linalg.norm(values) > max_angle_diff_thr:
                                print(f'bad calibration angle diff: {np.linalg.norm(values)}')
                                valid_trip = False
                                break
                    ### Check multi-stage parking
                    local_pose_dict = calib_json['local_pose']
                    position_3d_list = []
                    position_2d_list = []
                    ref_pose = np.linalg.inv(np.asarray(local_pose_dict['slice0']))
                    for slice_name in local_pose_dict.keys():
                        relative_pose = np.dot(ref_pose, np.asarray(local_pose_dict[slice_name]))
                        position_3d_list.append(relative_pose[0:3, 3])
                        position_2d_list.append(relative_pose[0:2, 3])

                    position_2d_list = np.asarray(position_2d_list)
                    kdtree = KDTree(position_2d_list)
                    for index, position in enumerate(position_2d_list):
                        _, indexes = kdtree.query(position, k=3)
                        z_gap_list = []
                        for t_index in indexes:
                            z_gap_list.append(position_3d_list[t_index][2] - position_3d_list[index][2])
                        if max(z_gap_list) > 2.0:
                            print(f'bad parking slice: {max(z_gap_list)}')
                            valid_trip = False
                            break

                if valid_trip:
                    valid_trip_paths.append(trip_path)
                else:
                    print(f'bad trip: {trip_path}')
            valid_trips = {}
            for trip_path in list(trip_paths.keys()):
                if trip_path in valid_trip_paths:
                    valid_trips[trip_path] = trip_paths[trip_path]
            print(f'Valid trips: {len(valid_trip_paths)} / {len(trip_paths.keys())}')
        else:
            valid_trips = trip_paths
    json.dump(valid_trips, open(os.path.join(exp_dir, 'input_trips.json'), 'w+'), indent=4)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="Path to config file")
    args = parser.parse_args()

    if args.config:
        import yaml
        config = yaml.safe_load(open(args.config, 'r'))
        prepare_workspace(config)
        print("Workspace preparation completed successfully")
    else:
        print("Error: Please provide a config file using --config argument")
