import os
import numpy as np
import cv2
import torch
import json
import yaml
import open3d as o3d
import math
from collections import defaultdict
from PIL import Image
from pathlib import Path
from glob import glob
from tqdm import tqdm
from typing import List, Tuple, Union
from numpy.typing import NDArray
from lib.config import cfg
from lib.config.globals import SemanticType, DATASET_CLASSES_IN_SEMANTIC
from lib.utils.box_utils import bbox_to_corner3d, inbbox_points, get_bound_2d_mask_fix, get_bound_2d_mask
from lib.utils.colmap_utils import read_points3D_binary, read_extrinsics_binary, qvec2rotmat
from lib.utils.data_utils import get_val_frames
from lib.utils.graphics_utils import get_rays, sphere_intersection
from lib.utils.general_utils import matrix_to_quaternion, quaternion_to_matrix_numpy
from lib.datasets.base_readers import storePly, get_Sphere_Norm
from plyfile import PlyData, PlyElement
from script.xpeng.images2video import images2video


xpeng_track2label = defaultdict(lambda: -1)
xpeng_track2label.update({"car": 0, "truck": 0, "pedestrian": 1, "cyclist": 2, "sign": 3, "misc": -1})


_label2camera = {
    1: 'cam0',
    2: 'cam2',
    3: 'cam3',
    4: 'cam4',
    5: 'cam5',
    6: 'cam6',
    7: 'cam7',
}

_EPS = np.finfo(float).eps * 4.0


def get_image_mask_tensor_from_path(filepath: Path, scale_factor: float = 1.0) -> torch.Tensor:
    """
    Utility function to read a mask image from the given path and return a boolean tensor
    """
    pil_mask = Image.open(filepath)
    if pil_mask.mode == "RGB":
        img = np.array(pil_mask)
        assert np.all((img[:,:,0] == img[:,:,1]) == (img[:,:,1] == img[:,:,2])), f"Channels of {filepath} must be the same!"
        pil_mask = pil_mask.convert("L")

    if scale_factor != 1.0:
        width, height = pil_mask.size
        newsize = (int(width * scale_factor), int(height * scale_factor))
        pil_mask = pil_mask.resize(newsize, resample=Image.NEAREST)
    mask_tensor = torch.from_numpy(np.array(pil_mask.convert("1"))).unsqueeze(-1).bool()
    if len(mask_tensor.shape) != 3:
        raise ValueError(f"The mask image {filepath} should have 1 channel, but: {mask_tensor.shape}")
    return mask_tensor


def get_mask_tensors(semantics, mask_indices):
    if isinstance(mask_indices, List):
        mask_indices = torch.tensor(mask_indices, dtype=torch.int64).view(1, 1, -1)
        # Compute mask by summing over the matching mask indices
    mask = torch.sum(semantics == mask_indices, dim=-1, keepdim=True) == 1
    return mask


def get_semantics_from_path(filepath: Path, scale_factor: float = 1.0):
    pil_image = Image.open(filepath)
    if scale_factor != 1.0:
        width, height = pil_image.size
        newsize = (int(width * scale_factor), int(height * scale_factor))
        pil_image = pil_image.resize(newsize, resample=Image.NEAREST)
    image = np.array(pil_image, dtype="int32")
    if len(image.shape) == 3:
        image = image[:, :, 0]
    
    class_to_label = {
        SemanticType.VEHICLE.value: DATASET_CLASSES_IN_SEMANTIC['VEHICLE'],
        SemanticType.HUMAN.value: DATASET_CLASSES_IN_SEMANTIC['HUMAN'],
        SemanticType.GROUND.value: DATASET_CLASSES_IN_SEMANTIC['GROUND'],
        SemanticType.SKY.value: DATASET_CLASSES_IN_SEMANTIC['SKY'],
        SemanticType.ROADSIDE.value: DATASET_CLASSES_IN_SEMANTIC['ROADSIDE'],
    }
    semantics = np.zeros_like(image)
    for label, class_ids in class_to_label.items():
        semantics[np.isin(image, class_ids)] = label

    semantics = torch.from_numpy(semantics).unsqueeze(-1)
    return semantics.to(torch.uint8)


def get_mask_from_semantics(semantics, mask_indices):
    if isinstance(mask_indices, List):
        mask_indices = torch.tensor(mask_indices, dtype=torch.uint8).view(1, 1, -1).cuda()
    # return mask if semantics are in the mask indices
    mask = torch.sum(semantics == mask_indices, dim=-1, keepdim=True) == 1
    return mask


def load_yaml(config_path):
    with open(config_path, 'rb') as f:
        config = yaml.safe_load(f)
    return config


# load ego pose and camera calibration(extrinsic and intrinsic)
def load_camera_info(datadir, cam_names, frame_stride=1):
    calib_path = os.path.join(datadir, 'calib.json')
    anchorpose_path = os.path.join(datadir, 'anchorpose.json')
    localpose_path = os.path.join(datadir, 'localpose.json')
    
    calibrations = load_yaml(calib_path)
    anchor_pose = np.array(json.load(open(anchorpose_path, "r")))
    localpose = json.load(open(localpose_path, "r"))

    ######## compute ego poses from calib.json
    # ego_frame_poses = []
    # ego_cam_poses = [[] for i in range(len(cam_names))]
    # ego_poses_timestamps = sorted(calibrations['local_pose'].keys())
    # for timestamp in ego_poses_timestamps:
    #     rig_to_world = np.array(calibrations['local_pose'][timestamp]).reshape(4, 4)
    #     ego_frame_poses.append(rig_to_world)
    #     for i, cam_name in enumerate(cam_names):
    #         cam2world = rig_to_world @ cam_to_rig[cname]
    #         ego_cam_poses[i].append(cam2world)

    ######## compute ego poses from transform.json
    transform_path = os.path.join(datadir, 'transform.json')
    with open(transform_path, "r") as f:
        meta = json.load(f)

    image_info = {}
    time_cam_dict = {}
    for frame in meta["frames"]:
        timestamp = frame["timestamp"]
        cam_name = frame["camera"]
        if timestamp not in time_cam_dict:
            time_cam_dict[timestamp] = {}
        if cam_name not in image_info:
            image_info[cam_name] = {}
            image_info[cam_name]["image_widths"] = frame["w"]
            image_info[cam_name]["image_heights"] = frame["h"]

        time_cam_dict[timestamp][cam_name] = frame["transform_matrix"]

    # sort time_cam_dict by timestamp and stride for frame
    time_cam_dict = dict(sorted(time_cam_dict.items()))
    time_cam_dict = {k: v for i, (k, v) in enumerate(time_cam_dict.items()) if i % frame_stride == 0}
    
    calibrations["image_info"] = image_info
    
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
    cam_to_rig_optimized_mean = {i: np.mean(cam_to_rig_optimized[i], axis=0) for i in cam_names}
    cam_to_rig_optimized_std = {i: np.std(cam_to_rig_optimized[i], axis=0) for i in cam_names}
    
    ######## compute intrinsics and extrinsics from calib.json
    rig_to_cam = {}
    cam_to_rig = {}
    cam_intrinsic = {}
    for cname in calibrations.keys():
        if "new" not in cname:
            continue

        if 'extrinsic' in calibrations[cname] and 'intrinsic' in calibrations[cname]:
            key_name = cname.replace("new", "")
            rig_to_cam[key_name] = np.array(
                calibrations[cname]['extrinsic']['transformation_matrix']
            ).reshape(4, 4)
            cam_to_rig[key_name] = np.linalg.inv(rig_to_cam[key_name])
            if key_name in cam_to_rig_optimized_mean:
                diff_to_optimized = np.linalg.norm(cam_to_rig_optimized_mean[key_name] - cam_to_rig[key_name])
                print(f"[INFO] cam_to_rig diff to cam_to_rig_optimized for {key_name}: {diff_to_optimized}")
                print(f"[INFO] cam_to_rig_optimized_std for {key_name}: \n{cam_to_rig_optimized_std[key_name]}")

            intrinsic = calibrations[cname]['intrinsic']
            if 'focal_length_x' in intrinsic and 'focal_length_y' in intrinsic:
                fx = intrinsic['focal_length_x']
                fy = intrinsic['focal_length_y']
            else:
                fx = intrinsic['focal_length']
                fy = intrinsic['focal_length']
            cx = intrinsic['cx']
            cy = intrinsic['cy']
            intrinsic = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]])
            cam_intrinsic[key_name] = intrinsic

    intrinsics = []
    extrinsics = []
    for cname in cam_names:
        key_name = cname.replace("new", "")
        intrinsics.append(cam_intrinsic[key_name])
        extrinsics.append(cam_to_rig_optimized_mean[key_name])

    return calibrations, intrinsics, extrinsics, ego_frame_poses, ego_cam_poses, anchor_pose


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

    
# calculate obj pose in vehicle frame
def make_obj_pose(ego_pose, translation, rotation):
    #########
    rotz_matrix = quaternion_matrix(rotation)[:3, :3]
    obj_pose_world = np.eye(4)
    obj_pose_world[:3, :3] = rotz_matrix
    obj_pose_world[:3, 3] = translation

    obj_pose_vehicle = np.matmul(np.linalg.inv(ego_pose), obj_pose_world)
    obj_rotation_vehicle = torch.from_numpy(obj_pose_vehicle[:3, :3]).float().unsqueeze(0)
    obj_quaternion_vehicle = matrix_to_quaternion(obj_rotation_vehicle).squeeze(0).numpy()
    obj_quaternion_vehicle = obj_quaternion_vehicle / np.linalg.norm(obj_quaternion_vehicle)
    obj_position_vehicle = obj_pose_vehicle[:3, 3]
    obj_pose_vehicle = np.concatenate([obj_position_vehicle, obj_quaternion_vehicle])

    obj_quaternion_world = rotation / np.linalg.norm(rotation)
    obj_position_world = translation
    obj_pose_world = np.concatenate([obj_position_world, obj_quaternion_world])

    return obj_pose_vehicle, obj_pose_world


def get_obj_pose_tracking(
        annotations, selected_frames, frames_timestamps_global, ego_poses, cameras
    ):
    n_frames = len(annotations['frames'])
    n_obj_in_frame = np.zeros(n_frames)
    
    tracklets_ls = []    
    objects_info = {}
    valid_timestamps = set(frames_timestamps_global)
    for anno_frame_id, anno in enumerate(annotations['frames']):
        timestamp = anno["timestamp"]
        try:
            frame_id = frames_timestamps_global.index(timestamp) + selected_frames[0]
        except ValueError:
            print(f"[WARNING] object timestamp (idx {anno_frame_id}) not in frames_timestamps_global!")
            continue

        objects = anno["objects"]
        for obj in objects:
            track_id = obj['gid']
            object_class = obj['type']
            length, width, height = obj['size']
            translation = obj['translation']
            rotation = obj['rotation']
            if track_id not in objects_info.keys():
                objects_info[track_id] = dict()
                objects_info[track_id]['track_id'] = track_id
                objects_info[track_id]['class'] = object_class
                objects_info[track_id]['class_label'] = xpeng_track2label[object_class]
                objects_info[track_id]['height'] = height
                objects_info[track_id]['width'] = width
                objects_info[track_id]['length'] = length
            else:
                objects_info[track_id]['height'] = max(objects_info[track_id]['height'], height)
                objects_info[track_id]['width'] = max(objects_info[track_id]['width'], width)
                objects_info[track_id]['length'] = max(objects_info[track_id]['length'], length)

            tr_array = [frame_id, track_id, translation, rotation]
            tracklets_ls.append(tr_array)
            n_obj_in_frame[frame_id] += 1
    
    start_frame, end_frame = selected_frames[0], selected_frames[1]
    max_obj_per_frame = int(n_obj_in_frame[start_frame:end_frame + 1].max())
    num_frames = end_frame - start_frame + 1
    visible_objects_ids = np.ones([num_frames, max_obj_per_frame]) * -1.0
    visible_objects_pose_vehicle = np.ones([num_frames, max_obj_per_frame, 7]) * -1.0
    visible_objects_pose_world = np.ones([num_frames, max_obj_per_frame, 7]) * -1.0

    # Iterate through the tracklets and process object data
    for tracklet in tracklets_ls:
        frame_id = int(tracklet[0])
        track_id = int(tracklet[1])
        if start_frame <= frame_id <= end_frame:            
            ego_pose = ego_poses[frame_id]
            translation = tracklet[2]
            rotation = tracklet[3]
            obj_pose_vehicle, obj_pose_world = make_obj_pose(ego_pose, translation, rotation)

            frame_idx = frame_id - start_frame
            obj_column = np.argwhere(visible_objects_ids[frame_idx, :] < 0).min()

            visible_objects_ids[frame_idx, obj_column] = track_id
            visible_objects_pose_vehicle[frame_idx, obj_column] = obj_pose_vehicle
            visible_objects_pose_world[frame_idx, obj_column] = obj_pose_world
    
    # Remove static objects
    print("Start removing static objects")
    for key in objects_info.copy().keys():
        all_obj_idx = np.where(visible_objects_ids == key)
        if len(all_obj_idx[0]) > 0:
            obj_world_postions = visible_objects_pose_world[all_obj_idx][:, :3]
            distance = np.linalg.norm(obj_world_postions[0] - obj_world_postions[-1])
            dynamic = np.any(np.std(obj_world_postions, axis=0) > 0.5) or distance > 2
            pre_distance = np.linalg.norm(obj_world_postions[0] - obj_world_postions[len(obj_world_postions)//2])
            later_distance = np.linalg.norm(obj_world_postions[len(obj_world_postions)//2] - obj_world_postions[-1])
            if not dynamic:
                visible_objects_ids[all_obj_idx] = -1.
                visible_objects_pose_vehicle[all_obj_idx] = -1.
                visible_objects_pose_world[all_obj_idx] = -1.
                # print(f"Pop static object {key}! {objects_info[key]}")
                objects_info.pop(key)
            elif len(obj_world_postions) > 10 and ((pre_distance < distance / 4 and pre_distance < 3) or pre_distance / len(obj_world_postions) < 0.02):
                objects_info[key]["keep_in_static_scene"] = True
            elif len(obj_world_postions) > 10 and ((later_distance < distance / 4 and later_distance < 3) or later_distance / len(obj_world_postions) < 0.02):
                objects_info[key]["keep_in_static_scene"] = True
            else:
                objects_info[key]["keep_in_static_scene"] = False
        else:
            print(f"Pop unseen object {key}! {objects_info[key]}")
            objects_info.pop(key)
    mask = visible_objects_ids >= 0
    max_obj_per_frame_new = np.sum(mask, axis=1).max()
    print("Max obj per frame:", max_obj_per_frame_new)

    if max_obj_per_frame_new == 0:
        print("No moving obj in current sequence, make dummy visible objects")
        visible_objects_ids = np.ones([num_frames, 1]) * -1.0
        visible_objects_pose_world = np.ones([num_frames, 1, 7]) * -1.0
        visible_objects_pose_vehicle = np.ones([num_frames, 1, 7]) * -1.0    
    elif max_obj_per_frame_new < max_obj_per_frame:
        visible_objects_ids_new = np.ones([num_frames, max_obj_per_frame_new]) * -1.0
        visible_objects_pose_vehicle_new = np.ones([num_frames, max_obj_per_frame_new, 7]) * -1.0
        visible_objects_pose_world_new = np.ones([num_frames, max_obj_per_frame_new, 7]) * -1.0
        for frame_idx in range(num_frames):
            for y in range(max_obj_per_frame):
                obj_id = visible_objects_ids[frame_idx, y]
                if obj_id >= 0:
                    obj_column = np.argwhere(visible_objects_ids_new[frame_idx, :] < 0).min()
                    visible_objects_ids_new[frame_idx, obj_column] = obj_id
                    visible_objects_pose_vehicle_new[frame_idx, obj_column] = visible_objects_pose_vehicle[frame_idx, y]
                    visible_objects_pose_world_new[frame_idx, obj_column] = visible_objects_pose_world[frame_idx, y]

        visible_objects_ids = visible_objects_ids_new
        visible_objects_pose_vehicle = visible_objects_pose_vehicle_new
        visible_objects_pose_world = visible_objects_pose_world_new

    box_scale = cfg.data.get('box_scale', 1.0)
    print('box scale: ', box_scale)
    
    frames = list(range(start_frame, end_frame + 1))
    frames = np.array(frames).astype(np.int32)

    # postprocess object_info   
    for key in objects_info.keys():
        obj = objects_info[key]
        if obj['class'] == 'pedestrian':
            obj['deformable'] = True
        else:
            obj['deformable'] = False
        
        obj['width'] = obj['width'] * box_scale
        obj['length'] = obj['length'] * box_scale
        
        obj_frame_idx = np.argwhere(visible_objects_ids == key)[:, 0]
        obj_frame_idx = obj_frame_idx.astype(np.int32)
        obj_frames = frames[obj_frame_idx]
        obj['start_frame'] = np.min(obj_frames)
        obj['end_frame'] = np.max(obj_frames)
        
        objects_info[key] = obj

    # [[num_frames], [track_id], [x, y, z, qw, qx, qy, qz]]
    objects_tracklets_world = np.concatenate(
        [visible_objects_ids[..., None], visible_objects_pose_world], axis=-1
    )

    objects_tracklets_vehicle = np.concatenate(
        [visible_objects_ids[..., None], visible_objects_pose_vehicle], axis=-1
    )

    return objects_tracklets_world, objects_tracklets_vehicle, objects_info


def padding_tracklets(tracklets, frame_timestamps, min_timestamp, max_timestamp):
    # tracklets: [num_frames, max_obj, ....]
    # frame_timestamps: [num_frames]
    
    # Clone instead of extrapolation
    if min_timestamp < frame_timestamps[0]:
        tracklets_first = tracklets[0]
        frame_timestamps = np.concatenate([[min_timestamp], frame_timestamps])
        tracklets = np.concatenate([tracklets_first[None], tracklets], axis=0)
    
    if max_timestamp > frame_timestamps[1]:
        tracklets_last = tracklets[-1]
        frame_timestamps = np.concatenate([frame_timestamps, [max_timestamp]])
        tracklets = np.concatenate([tracklets, tracklets_last[None]], axis=0)
        
    return tracklets, frame_timestamps
    

def generate_dataparser_outputs(
        datadir, 
        selected_frames=None, 
        cameras=[1, 2, 3, 4, 5, 6, 7],
        frame_stride=1
    ):
    # load calibration and ego pose
    cam_names = [_label2camera[cam] for cam in cameras]
    calibrations, intrinsics, extrinsics, ego_frame_poses, ego_cam_poses, anchor_pose = \
        load_camera_info(datadir, cam_names, frame_stride)

    # check file frames
    image_dir = os.path.join(datadir, 'images')
    image_timestamps_all = [os.path.basename(i) \
        for i in sorted(glob(os.path.join(image_dir, cam_names[0], '*.png')))
    ][::frame_stride]

    image_filenames_all = {cam: [] for cam in cam_names}
    for timestamp in image_timestamps_all:
        for cam in cam_names:
            image_path = os.path.join(image_dir, cam, timestamp)
            image_filenames_all[cam].append(image_path)

    num_frames_all = len(image_filenames_all[cam_names[0]])
    num_cameras = len(cameras)
    
    if selected_frames is None or len(selected_frames) == 0:
        start_frame = 0
        end_frame = num_frames_all - 1
        selected_frames = [start_frame, end_frame]
    else:
        start_frame, end_frame = selected_frames[0], selected_frames[1]
    num_frames = end_frame - start_frame + 1

    # load camera, frame, path
    frames = []
    frames_idx = []
    cams = []
    image_filenames = []
    
    ixts = []
    exts = []
    poses = []
    c2ws = []
    
    frames_timestamps = []
    frames_timestamps_global = []
    cams_timestamps = []
        
    split_test = cfg.data.get('split_test', -1)
    split_train = cfg.data.get('split_train', -1)
    train_frames, test_frames = get_val_frames(
        num_frames, 
        test_every=split_test if split_test > 0 else None,
        train_every=split_train if split_train > 0 else None,
    )
    
    # timestamps = sorted(calibrations['local_pose'].keys())
    timestamps = sorted([i.split('.')[0] for i in image_timestamps_all])
        
    for frame in range(start_frame, end_frame+1):
        frames_timestamps_global.append(timestamps[frame])
        frames_timestamps.append(timestamps[frame])
    
    for fake_frame, timestamp in enumerate(frames_timestamps):
        frame = fake_frame + start_frame
        for cam_id, cam in enumerate(cam_names):
            image_filename = image_filenames_all[cam][frame]
            ixt = intrinsics[cam_id]
            ext = extrinsics[cam_id]

            pose = ego_frame_poses[frame] ################### TODO: ego_cam_poses[cam_id, frame]
            c2w = ego_cam_poses[cam_id, frame]  ############# TODO: pose @ ext

            frames.append(frame)
            frames_idx.append(frame - start_frame)
            cams.append(cam)
            image_filenames.append(image_filename)
            
            ixts.append(ixt)
            exts.append(ext)
            poses.append(pose)
            c2ws.append(c2w)
            cams_timestamps.append(int(timestamp))

    exts = np.stack(exts, axis=0)
    ixts = np.stack(ixts, axis=0)
    poses = np.stack(poses, axis=0)
    c2ws = np.stack(c2ws, axis=0)

    timestamp_offset = min(cams_timestamps)
    cams_timestamps = (np.array(cams_timestamps) - timestamp_offset) / 1e9
    frames_timestamps = (np.array([int(i) for i in frames_timestamps]) - timestamp_offset) / 1e9
    min_timestamp, max_timestamp = frames_timestamps[0], frames_timestamps[-1]

    annotation_path = os.path.join(datadir, 'annotation_for_train.json')
    with open(annotation_path, "r") as f:
        annotations = json.load(f)
    # [[num_frames], [track_id], [x, y, z, qw, qx, qy, qz]]
    object_tracklets_world, object_tracklets_vehicle, object_info = get_obj_pose_tracking(
        annotations, 
        selected_frames, 
        frames_timestamps_global,
        ego_frame_poses,
        cameras
    )
    assert len(object_tracklets_world) == num_frames, \
        f"Objects info frames from annotation {len(object_tracklets_world)} != {num_frames} total frames!"

    for track_id in object_info.keys():
        object_start_frame = object_info[track_id]['start_frame']
        object_end_frame = object_info[track_id]['end_frame']
        object_start_timestamp = (int(timestamps[object_start_frame]) - timestamp_offset)/1e9 - 0.1
        object_end_timestamp = (int(timestamps[object_end_frame]) - timestamp_offset)/1e9 + 0.1
        object_info[track_id]['start_timestamp'] = max(object_start_timestamp, min_timestamp)
        object_info[track_id]['end_timestamp'] = min(object_end_timestamp, max_timestamp)
        
    result = dict()
    ### for simulation
    result['anchor_pose'] = anchor_pose
    result['calibrations'] = calibrations
    result['intrinsics'] = intrinsics
    result['extrinsics'] = extrinsics
    result['timestamps'] = timestamps
    result['timestamp_offset'] = timestamp_offset
    result['ego_frame_poses'] = ego_frame_poses
    result['annotations'] = annotations

    ### for training
    result['start_frame'] = start_frame
    result['end_frame'] = end_frame
    result['num_frames'] = num_frames
    result['exts'] = exts
    result['ixts'] = ixts
    result['poses'] = poses
    result['c2ws'] = c2ws
    result['obj_tracklets'] = object_tracklets_vehicle
    result['obj_tracklets_world'] = object_tracklets_world
    result['obj_info'] = object_info 
    result['frames'] = frames
    result['cams'] = cams
    result['frames_idx'] = frames_idx
    result['image_filenames'] = image_filenames
    result['cams_timestamps'] = cams_timestamps
    result['tracklet_timestamps'] = frames_timestamps

    # get object bounding mask
    obj_bounds = []
    obj_bounds_for_static_scene = []
    write_obj_bound = cfg.data.get('write_obj_bound', False) and cfg.mode == 'train'
    if write_obj_bound:
        print('[DEBUG] Start writing obj bound mask for debug purpose')
        obj_bound_path = Path(cfg.model_path) / "obj_bound"

    for i, image_filename in tqdm(enumerate(image_filenames)):
        cam = cams[i]
        h = calibrations["image_info"][cam]["image_heights"]
        w = calibrations["image_info"][cam]["image_widths"]
        obj_bound = np.zeros((h, w)).astype(np.uint8)
        obj_bound_for_static_scene = obj_bound
        obj_tracklets = object_tracklets_vehicle[frames_idx[i]]
        ixt, ext = ixts[i], exts[i]
        if write_obj_bound:
            write_path = obj_bound_path / f"{cam}/{str(Path(image_filename).parts[-1])}"
            write_path.parent.mkdir(parents=True, exist_ok=True)
            rgb_image = cv2.imread(image_filename)
            contours_list = []

        for obj_tracklet in obj_tracklets:
            track_id = int(obj_tracklet[0])
            if track_id >= 0:
                obj_pose_vehicle = np.eye(4)    
                obj_pose_vehicle[:3, :3] = quaternion_to_matrix_numpy(obj_tracklet[4:8])
                obj_pose_vehicle[:3, 3] = obj_tracklet[1:4]
                obj_length = object_info[track_id]['length']
                obj_width = object_info[track_id]['width']
                obj_height = object_info[track_id]['height']
                bbox = np.array([[-obj_length, -obj_width, -obj_height], 
                                 [obj_length, obj_width, obj_height]]) * 0.5
                corners_local = bbox_to_corner3d(bbox)
                corners_local = np.concatenate([corners_local, np.ones_like(corners_local[..., :1])], axis=-1)
                corners_vehicle = corners_local @ obj_pose_vehicle.T # 3D bounding box in vehicle frame
                mask_func_input = dict({
                    "corners_3d": corners_vehicle[..., :3],
                    "K": ixt,
                    "pose": np.linalg.inv(ext), 
                    "H": h, "W": w
                })
                mask = get_bound_2d_mask(**mask_func_input)
                if mask.sum() / int(mask.shape[0]*mask.shape[1]) > 0.95:
                    mask = get_bound_2d_mask_fix(**mask_func_input)

                if object_info[track_id]['keep_in_static_scene']:
                    obj_bound_for_static_scene = np.logical_or(obj_bound_for_static_scene, mask)

                obj_bound = np.logical_or(obj_bound, mask)

                if write_obj_bound:
                    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    contours_list.append(contours)
        
        obj_bounds.append(obj_bound)
        obj_bounds_for_static_scene.append(obj_bound_for_static_scene)

        if write_obj_bound:
            for contours in contours_list:
                cv2.drawContours(rgb_image, contours, -1, (0, 255, 0), 2)
            cv2.imwrite(f'{str(write_path)}', rgb_image)

    result['obj_bounds'] = obj_bounds
    result['obj_bounds_for_static_scene'] = obj_bounds_for_static_scene
    
    if write_obj_bound:
        print('[DEBUG] Start generating obj bound videos')
        images2video(obj_bound_path, log=False)
    
    return result
