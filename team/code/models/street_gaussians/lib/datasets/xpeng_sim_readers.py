from lib.utils.xpeng_utils import load_camera_info, get_obj_pose_tracking, _label2camera
import os
import numpy as np
import sys
sys.path.append(os.getcwd())


def readXpengSimInfo(cameras, selected_frames, result_dict):
    cam_names = [_label2camera[cam] for cam in cameras]
    
    # timestamps = sorted([int(i) for i in result_dict['timestamps']])
    timestamps = result_dict['timestamps']
    timestamp_offset = result_dict['timestamp_offset']
    annotations =  dict(result_dict['annotations'])
    ego_frame_poses = result_dict['ego_frame_poses']
    smoothed_ego_frame_poses = result_dict['ego_frame_poses_smooth']
    num_frames_all = len(timestamps)

    if selected_frames is None or len(selected_frames) == 0:
        start_frame = 0
        end_frame = num_frames_all - 1
        selected_frames = [start_frame, end_frame]
    else:
        start_frame, end_frame = selected_frames[0], selected_frames[1]
    num_frames = end_frame - start_frame + 1

    frames_timestamps_global = []
    frames_timestamps = []
    camera_timestamps = dict()

    for frame in range(start_frame, end_frame+1):
        frames_timestamps.append((int(timestamps[frame]) - timestamp_offset) / 1e9)
        frames_timestamps_global.append(timestamps[frame])
        
    for cam_name in cam_names:
        camera_timestamps[cam_name] = dict()
        camera_timestamps[cam_name]['train_timestamps'] = np.array(frames_timestamps)

    object_tracklets_world, object_tracklets_vehicle, object_info = get_obj_pose_tracking(
        annotations, 
        selected_frames, 
        frames_timestamps_global,
        smoothed_ego_frame_poses,
        cameras
    )

    min_timestamp, max_timestamp = frames_timestamps[0], frames_timestamps[-1]
    for track_id in object_info.keys():
        object_start_frame = object_info[track_id]['start_frame']
        object_end_frame = object_info[track_id]['end_frame']
        object_start_timestamp = (int(timestamps[object_start_frame]) - timestamp_offset)/1e9 - 0.1
        object_end_timestamp = (int(timestamps[object_end_frame]) - timestamp_offset)/1e9 + 0.1
        object_info[track_id]['start_timestamp'] = max(object_start_timestamp, min_timestamp)
        object_info[track_id]['end_timestamp'] = min(object_end_timestamp, max_timestamp)

    scene_metadata = dict()
    scene_metadata['obj_tracklets'] = object_tracklets_vehicle
    scene_metadata['obj_tracklets_world'] = object_tracklets_world
    scene_metadata['obj_meta'] = object_info
    scene_metadata['frames_timestamps'] = np.array(frames_timestamps)
    scene_metadata['frames_timestamps_global'] = frames_timestamps_global
    scene_metadata['tracklet_timestamps'] = np.array(frames_timestamps)
    scene_metadata['camera_timestamps'] = camera_timestamps
    scene_metadata['num_images'] = num_frames_all * len(cameras)
    scene_metadata['num_cams'] = len(cameras)
    scene_metadata['num_frames'] = num_frames_all

    scene_metadata['scene_center'] = np.array(result_dict['scene_center'])
    scene_metadata['scene_radius'] = result_dict['scene_radius']
    scene_metadata['sphere_center'] = np.array(result_dict['sphere_center'])
    scene_metadata['sphere_radius'] = result_dict['sphere_radius']

    return scene_metadata