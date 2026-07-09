import os, sys
import json
import yaml
import numpy as np
import torch

from lib.utils.xpeng_utils import load_yaml
from lib.utils.xpeng_utils import _label2camera
from lib.utils.graphics_utils import getWorld2View2


# load novel ego pose and camera calibration(extrinsic and intrinsic)
def load_novel_camera_info(datadir, cam_names, frame_stride=1):
    anchorpose_path = os.path.join(datadir, 'anchorpose.json')
    localpose_path = os.path.join(datadir, 'novel_localpose_3.5.json')
    
    anchor_pose = np.array(json.load(open(anchorpose_path, "r")))
    localpose = json.load(open(localpose_path, "r"))

    ######## compute ego poses from transform.json
    transform_path = os.path.join(datadir, 'novel_transform_3.5.json')
    with open(transform_path, "r") as f:
        meta = json.load(f)

    time_cam_dict = {}
    for frame in meta["frames"]:
        timestamp = frame["timestamp"]
        cam_name = frame["camera"]
        if timestamp not in time_cam_dict:
            time_cam_dict[timestamp] = {}

        time_cam_dict[timestamp][cam_name] = frame["transform_matrix"]

    # sort time_cam_dict by timestamp and stride for frame
    time_cam_dict = dict(sorted(time_cam_dict.items()))
    time_cam_dict = {k: v for i, (k, v) in enumerate(time_cam_dict.items()) if i % frame_stride == 0}
    
    
    world2anchor = np.linalg.inv(anchor_pose)
    ego_frame_poses = []
    ego_cam_poses = [[] for i in range(len(cam_names))]
    cam_to_rig_optimized = {i: [] for i in cam_names}
    for timestamp in sorted(time_cam_dict.keys()):
        ego_pose = world2anchor @ localpose[str(timestamp)]
        for i, cam_name in enumerate(cam_names):
            cam2firstRig = time_cam_dict[timestamp][cam_name]
            ego_cam_poses[i].append(cam2firstRig)
            cam_to_rig_optimized[cam_name].append(np.linalg.inv(ego_pose) @ cam2firstRig)

        ego_frame_poses.append(ego_pose)

    # normalized by center ego pose
    ego_frame_poses = np.array(ego_frame_poses)
    ego_cam_poses = [np.array(ego_cam_poses[i]) for i in range(len(cam_names))]
    ego_cam_poses = np.array(ego_cam_poses)
    return ego_frame_poses, ego_cam_poses


def generate_novel_dataparser_outputs(
        datadir, 
        start_frame, end_frame, timestamps,
        cameras=[1, 2, 3, 4, 5, 6, 7],
        frame_stride=1
    ):
    # load calibration and ego pose
    num_frames = end_frame - start_frame + 1
    cam_names = [_label2camera[cam] for cam in cameras]
    ego_frame_poses, ego_cam_poses = load_novel_camera_info(datadir, cam_names, frame_stride)
    
    # load camera, frame, path
    poses = []
    c2ws = []
    cams_timestamps = []
    frames_timestamps = []
    frames_timestamps_global = []
        
    for frame in range(start_frame, end_frame+1):
        frames_timestamps_global.append(timestamps[frame])
        frames_timestamps.append(timestamps[frame])
    
    for fake_frame, timestamp in enumerate(frames_timestamps):
        frame = fake_frame + start_frame
        for cam_id, cam in enumerate(cam_names):
            pose = ego_frame_poses[frame] 
            c2w = ego_cam_poses[cam_id, frame]
            
            poses.append(pose)
            c2ws.append(c2w)
            cams_timestamps.append(int(timestamp))

    timestamp_offset = min(cams_timestamps)
    cams_timestamps = (np.array(cams_timestamps) - timestamp_offset) / 1e9
    poses = np.stack(poses, axis=0)
    c2ws = np.stack(c2ws, axis=0)

    result = dict()
    result['novel_poses'] = poses
    result['novel_c2ws'] = c2ws
    result['novel_timestamps'] = cams_timestamps
    return result


def generate_novel_camera_info(path, novel_metadata, output_novel, idx, cam_name, image_name):
    c2w = output_novel['novel_c2ws'][idx]
    RT = np.linalg.inv(c2w)
    R = RT[:3, :3].T
    T = RT[:3, 3]

    depth_pcd_path = os.path.join(path, 'depth_pcd_3.5', cam_name, f'{image_name}.npy')
    assert os.path.exists(depth_pcd_path), f"[ERROR] Lidar depth {depth_pcd_path} not exists!"
    depth_pcd = dict(np.load(depth_pcd_path, allow_pickle=True).item())
    mask = depth_pcd['mask']
    value = depth_pcd['value']
    depth_pcd = np.zeros_like(mask).astype(np.float32)
    depth_pcd[mask] = value

    novel_metadata['lidar_depth'] = depth_pcd
    return R, T, novel_metadata


def set_camera_pitch_down_z(camera2world):
    # Extract rotation and translation
    R = camera2world[:3, :3]
    t = camera2world[:3, 3]

    # Define new forward direction (looking down -Z)
    new_forward = np.array([0, 0, -1])

    # Get original up vector in world space (camera's local Y-axis)
    original_up = R @ np.array([0, 0, 1])

    # Compute new up vector to preserve yaw
    # Project original_up onto the plane perpendicular to new_forward
    new_up = original_up - np.dot(original_up, new_forward) * new_forward
    if np.linalg.norm(new_up) < 1e-6:
        # Handle case where original_up is parallel to new_forward (rare)
        new_up = np.array([0, 0, 1])  # Default to world Y-up
    else:
        new_up = new_up / np.linalg.norm(new_up)

    # Compute right vector to complete the basis
    new_right = np.cross(new_up, new_forward)
    new_right = new_right / np.linalg.norm(new_right)

    # Recompute up to ensure orthogonality (preserves roll)
    new_up = np.cross(new_forward, new_right)
    new_up = new_up / np.linalg.norm(new_up)

    # Construct new rotation matrix (right, up, forward as columns)
    new_R = np.stack([new_right, new_up, new_forward], axis=1)

    # Construct new 4x4 camera2world matrix
    new_camera2world = np.eye(4)
    new_camera2world[:3, :3] = new_R
    new_camera2world[:3, 3] = t

    return new_camera2world


def render_camera_downwards(viewpoint_cam, gaussians_renderer, gaussians):
    c2w = viewpoint_cam.meta['c2w']
    new_camera2world = set_camera_pitch_down_z(c2w)

    RT_new = np.linalg.inv(new_camera2world)
    R_new = RT_new[:3, :3].T
    T_new = RT_new[:3, 3]

    view_matrix_new = torch.tensor(getWorld2View2(R_new, T_new, np.array([0.0, 0.0, 0.0]), 1.)).transpose(0, 1).cuda()
    view_matrix_old = viewpoint_cam.world_view_transform

    full_proj_transform_new = view_matrix_new.unsqueeze(0).bmm(viewpoint_cam.projection_matrix.unsqueeze(0)).squeeze(0)
    full_proj_transform_old = viewpoint_cam.full_proj_transform

    viewpoint_cam.world_view_transform = view_matrix_new
    viewpoint_cam.full_proj_transform = full_proj_transform_new

    option_backup = gaussians.include_sky
    gaussians.include_sky = False
    render_pkg = gaussians_renderer.render(
        viewpoint_cam, gaussians, exclude_list=list(set(gaussians.model_name_id.keys()) - set(['ground']))
    )
    gaussians.include_sky = option_backup

    viewpoint_cam.world_view_transform = view_matrix_old
    viewpoint_cam.full_proj_transform = full_proj_transform_old
    return render_pkg