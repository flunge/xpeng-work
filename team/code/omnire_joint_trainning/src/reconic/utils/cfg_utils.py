from omegaconf import OmegaConf
import os
import yaml
import numpy as np
import json
from glob import glob
import shutil
import cv2

def load_yaml(yaml_path):
    with open(yaml_path, 'rb') as f:
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
                # print(f"[INFO] cam_to_rig diff to cam_to_rig_optimized for {key_name}: {diff_to_optimized}")
                # print(f"[INFO] cam_to_rig_optimized_std for {key_name}: \n{cam_to_rig_optimized_std[key_name]}")

            fx = calibrations[cname]['intrinsic']['focal_length']
            fy = calibrations[cname]['intrinsic']['focal_length']
            cx = calibrations[cname]['intrinsic']['cx']
            cy = calibrations[cname]['intrinsic']['cy']
            intrinsic = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]])
            cam_intrinsic[key_name] = intrinsic

    intrinsics = []
    extrinsics = []
    for cname in cam_names:
        key_name = cname.replace("new", "")
        intrinsics.append(cam_intrinsic[key_name])
        extrinsics.append(cam_to_rig_optimized_mean[key_name])

    return calibrations, intrinsics, extrinsics, ego_frame_poses, ego_cam_poses, anchor_pose

def gen_result_cfg(origin_cfg, frame_stride=1):
    cam_ids = origin_cfg.data.pixel_source.cameras
    cam_names = [f"cam{id}" for id in cam_ids]
    dataset_dir = os.path.join(origin_cfg.data.data_root, origin_cfg.data.scene_idx)
    
    # cam calib, pose etc...
    calibrations, intrinsics, extrinsics, ego_frame_poses, ego_cam_poses, anchor_pose = \
        load_camera_info(dataset_dir, cam_names, frame_stride)

    # timestamp
    image_dir = os.path.join(dataset_dir, 'images')
    image_timestamps_all = [os.path.basename(i) \
        for i in sorted(glob(os.path.join(image_dir, cam_names[0], '*.png')))
    ][::frame_stride]
    timestamps = sorted([i.split('.')[0] for i in image_timestamps_all])

    # annotation
    annotation_path = os.path.join(dataset_dir, 'annotation_for_train.json')
    with open(annotation_path, "r") as f:
        annotations = json.load(f)

    # convert omageconf unsupported type to support type
    for index, item in enumerate(intrinsics):
        intrinsics[index] = intrinsics[index].tolist()
    for index, item in enumerate(extrinsics):
        extrinsics[index] = extrinsics[index].tolist()

    result_conf = OmegaConf.create()
    result_conf.results = {
        "anchor_pose": anchor_pose.tolist(),
        "calibrations": calibrations,
        "intrinsics": intrinsics,
        "extrinsics": extrinsics,
        "ego_frame_poses": ego_frame_poses.tolist(),
        "ego_cam_poses": ego_cam_poses.tolist(),
        "timestamps": timestamps,
        "annotations": annotations
    }

    return result_conf

# simulator need these file
def copy_dataset_files(cfg):
    print("simdebug copy_dataset_files")
    dataset_dir = os.path.join(cfg.data.data_root, cfg.data.scene_idx)
    output_dir = cfg.project_dir
    # Copy files
    essential_files = [
        'localpose.json',
        'calib.json', 
        'LocalPoseTopic.json',
        'transform.json',
        'metadata.json'
    ]
    for file_name in essential_files:
        if not copy_file_if_exists(dataset_dir, output_dir, file_name):
            print(f"[WARNING] {file_name} does not exist in {dataset_dir}")

    # Copy folders
    essential_folders = ['segs', 'input_ply', 'gsm_bkgd']
    for folder_name in essential_folders:
        if not copy_folder_if_exists(dataset_dir, output_dir, folder_name):
            print(f"[WARNING] {folder_name} does not exist in {dataset_dir}")

    if not copy_ground_final_ply_if_exists(dataset_dir, output_dir):
        print(f"[WARNING] misc/ground_final.ply does not exist in {dataset_dir}")

    # Copy representative images and masks for redistortion
    copy_representative_image_and_mask(dataset_dir, output_dir)
    

def copy_file_if_exists(dataset_dir, output_dir, file_name):
    src_path = os.path.join(dataset_dir, file_name)
    dst_path = os.path.join(output_dir, file_name)
    if os.path.exists(src_path) and not os.path.exists(dst_path):
        shutil.copyfile(src_path, dst_path)
    return os.path.exists(src_path)

def copy_folder_if_exists(dataset_dir, output_dir, folder_name):
    src_folder = os.path.join(dataset_dir, folder_name)
    dst_folder = os.path.join(output_dir, folder_name)
    if os.path.exists(src_folder) and not os.path.exists(dst_folder):
        shutil.copytree(src_folder, dst_folder, dirs_exist_ok=True)
    return os.path.exists(src_folder)


def copy_ground_final_ply_if_exists(dataset_dir, output_dir):
    src_path = os.path.join(dataset_dir, "misc", "ground_final.ply")
    if not os.path.exists(src_path):
        return False

    dst_folder = os.path.join(output_dir, "misc")
    os.makedirs(dst_folder, exist_ok=True)
    dst_path = os.path.join(dst_folder, "ground_final.ply")
    if not os.path.exists(dst_path):
        shutil.copyfile(src_path, dst_path)
    return True

def copy_representative_image_and_mask(dataset_dir, output_dir):
    src_folder = dataset_dir
    dst_folder = output_dir
    masks = os.path.join(src_folder, "masks")
    dst_image_path = os.path.join(dst_folder, "images")
    os.makedirs(dst_image_path, exist_ok=True)
    
    for cam in os.listdir(masks):
        if 'cam' not in cam:
            continue
        masks_list = []
        masks_acc = []
        masks_path = os.path.join(masks, cam)
        for mask_path in os.listdir(masks_path):
            if mask_path.endswith('.png'):
                mask0_path = os.path.join(masks_path, mask_path)
                acc = cv2.imread(mask0_path, cv2.IMREAD_GRAYSCALE).sum()
                masks_list.append(mask0_path)
                masks_acc.append(acc)

        # choose the mask with the largest area
        target_mask = masks_list[masks_acc.index(max(masks_acc))]
        mask0_path = os.path.join(masks_path, target_mask)
        shutil.copy(mask0_path, os.path.join(dst_image_path, cam + "_mask.png"))

        images_undistort_path = os.path.join(src_folder, "images", cam)
        image0_path = os.path.join(images_undistort_path, os.listdir(images_undistort_path)[0])
        shutil.copy(image0_path, os.path.join(dst_image_path, cam + "_image.png"))