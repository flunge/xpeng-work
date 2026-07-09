import argparse

import json
import math
import os
import shutil
import cv2
import numpy as np
import torch
from torch.utils.data import DataLoader
from tqdm import tqdm
import yaml
from joblib import Parallel, delayed
import matplotlib.pyplot as plt
from PIL import Image
import re
import sys
sys.path.insert(0, os.getcwd())
from ..datasets.xnet import XNetDataset as Dataset
from ..models.pose_model import ExtrinsicModel
from ..utility.misc import draw_trip_trajectory, convert_rel_to_abs_dict
from ..configs.parser import load_config
from ..utility.numpy_utils import numpy_to_list
from ..utility.image import postprocess_curb_depth, save_bev_depth_uint16
from ..utility.read_write_model import qvec2rotmat, rotmat2qvec
from copy import deepcopy

def load_pose_model(configs, num_camera, model_path):
    optim_rotation = True if configs["lr"].get("rotations", 0) != 0 else False
    optim_translation = True if configs["lr"].get("translations", 0) != 0 else False
    pose_model = ExtrinsicModel(configs, optim_rotation, optim_translation, num_camera)
    pose_model.load_state_dict(torch.load(model_path))
    pose_model.to(torch.device("cuda"))
    pose_model.eval()

    return pose_model


def get_cam_intrinsic(trip_info, cam_list,avm_cam_list = []):
    trip_intrinsic_dict = {}
    undistorted_avm_intrinsic_dict = {}
    for trip_path in trip_info.keys():
        trip_name = "_".join(trip_path.split("/")[-2:])
        if trip_name not in trip_intrinsic_dict:
            trip_intrinsic_dict[trip_name] = {}
        calib_json = json.load(open(os.path.join(trip_path, "calib.json")))
        for cam in cam_list:
            intrinsic = calib_json[cam]["intrinsic"]
            intrinsic_matrix = torch.eye(3)
            if "fx" in intrinsic and "fy" in intrinsic:
                fx = intrinsic["fx"]
                fy = intrinsic["fy"]
            else:
                fx = intrinsic["focal_length"]
                fy = intrinsic["focal_length"]
            intrinsic_matrix[0, 0] = fx
            intrinsic_matrix[1, 1] = fy
            intrinsic_matrix[0, 2] = intrinsic["cx"]
            intrinsic_matrix[1, 2] = intrinsic["cy"]
            if cam not in trip_intrinsic_dict[trip_name]:
                trip_intrinsic_dict[trip_name][cam] = {}
            trip_intrinsic_dict[trip_name][cam]["intrinsic_matrix"] = intrinsic_matrix
            trip_intrinsic_dict[trip_name][cam]["distort_coeffs"] = [
                intrinsic["k1"],
                intrinsic["k2"],
                intrinsic["p1"],
                intrinsic["p2"],
                intrinsic["k3"],
                intrinsic["k4"],
                intrinsic["k5"],
                intrinsic["k6"],
            ]
            if cam not in avm_cam_list:
                continue
            if trip_name not in undistorted_avm_intrinsic_dict:
                undistorted_avm_intrinsic_dict[trip_name] = {}
            if cam not in undistorted_avm_intrinsic_dict[trip_name]:
                undistorted_avm_intrinsic_dict[trip_name][cam] = {}
            undistorted_avm_intrinsic_dict[trip_name][cam] = deepcopy(trip_intrinsic_dict[trip_name][cam])
            K_matrix = np.array(calib_json[cam]["calibration"]["projection_model"]["K"])
            # reshape to 3x3
            K_matrix = K_matrix.reshape(3, 3)
            # convert to torch tensor
            K_matrix = torch.from_numpy(K_matrix).float()
            trip_intrinsic_dict[trip_name][cam]["intrinsic_matrix"] = K_matrix
            distort_coeffs = calib_json[cam]["calibration"]["projection_model"]["D"]
            # if len(distort_coeffs) < 8, fill to 8 with 0
            if len(distort_coeffs) < 8:
                distort_coeffs += [0.0] * (8 - len(distort_coeffs))
            trip_intrinsic_dict[trip_name][cam]["distort_coeffs"] = distort_coeffs
            trip_intrinsic_dict[trip_name][cam]["Xi"] = calib_json[cam]["calibration"]["projection_model"]["Xi"]
    return trip_intrinsic_dict, undistorted_avm_intrinsic_dict

def update_recon_pose_dict(configs, recon_pose_dict):
    rome_cam_list = configs["rome_cam_list"]
    cam_list = configs["cam_list"]
    extra_cam_list = [cam_id for cam_id in cam_list if cam_id not in rome_cam_list]
    print(f"update recon pose dict for extra cam list: {extra_cam_list}")

    ref_cam = configs["ref_cam"]
    print(f"rome ref cam: {ref_cam}")

    exp_dir = configs["exp_dir"]
    sfm_trips_path = os.path.join(exp_dir, 'sfm_trips.json')
    with open(sfm_trips_path) as f:
        sfm_trips_info = json.load(f)

    for trip_name, trip_info in sfm_trips_info.items():
        trip_name = trip_name.replace('image/', '')

        # get extra_cam intrinsic
        extra_cam_intrinsic = {}
        calib_json_path = os.path.join(exp_dir, 'image', trip_name, 'calib.json')
        assert os.path.exists(calib_json_path), f"calib.json not exists: {calib_json_path}"
        with open(calib_json_path) as f:
            calib_json = json.load(f)

        for cam_name in extra_cam_list:
            if "colmap_intrinsic" in calib_json and cam_name in calib_json["colmap_intrinsic"]:
                focal = calib_json["colmap_intrinsic"][cam_name]["focal_length"]
                cx = calib_json["colmap_intrinsic"][cam_name]["cx"]
                cy = calib_json["colmap_intrinsic"][cam_name]["cy"]
            elif cam_name in calib_json:
                focal = calib_json[cam_name]['intrinsic']["focal_length"]
                cx = calib_json[cam_name]['intrinsic']["cx"]
                cy = calib_json[cam_name]['intrinsic']["cy"]
            else:
                print(f"cam {cam_name} not in calib.json")
                continue
            intrinsic_matrix = np.eye(3)
            intrinsic_matrix[0, 0] = focal
            intrinsic_matrix[1, 1] = focal
            intrinsic_matrix[0, 2] = cx
            intrinsic_matrix[1, 2] = cy
            extra_cam_intrinsic[cam_name] = intrinsic_matrix.tolist()

        # get extra_cam2ref_cam transform
        rig_ba_json_path = os.path.join(exp_dir, 'sparse', trip_name, 'rig_ba.json')
        assert os.path.exists(rig_ba_json_path), f"rig_ba.json not exists: {rig_ba_json_path}"
        with open(rig_ba_json_path) as f:
            rig_ba_json = json.load(f)
        assert len(rig_ba_json) > 0, f"rig_ba.json is empty: {rig_ba_json_path}"
        cameras_info = rig_ba_json[0]['cameras']

        T_cam2rig_dict = {}
        for camera_info in cameras_info:
            cam_name = camera_info['image_prefix']
            if cam_name in extra_cam_list or cam_name == ref_cam:
                T_cam2rig = np.eye(4)
                T_cam2rig[:3,:3] = qvec2rotmat(np.array(camera_info['cam_to_rig_rotation']))
                T_cam2rig[:3,3] = np.array(camera_info['cam_to_rig_translation'])
                T_cam2rig_dict[cam_name] = T_cam2rig
        assert ref_cam in T_cam2rig_dict, f"ref_cam not in T_cam2rig_dict: {T_cam2rig_dict.keys()}"

        T_extra_cam2ref_cam_dict = {}
        for cam_name in extra_cam_list:
            if cam_name not in T_cam2rig_dict:
                print(f"Warning: {cam_name} not in T_cam2rig_dict")
                continue
            T_cam2ref_cam = np.linalg.inv(T_cam2rig_dict[ref_cam]) @ T_cam2rig_dict[cam_name]
            T_extra_cam2ref_cam_dict[cam_name] = T_cam2ref_cam

        # compute extra_cam2bev_world transform
        new_dict = {}
        for vehicle_trip_cam_slice_name, pose_info in recon_pose_dict.items():
            pose_trip_name = vehicle_trip_cam_slice_name.split('/cam')[0]
            pose_cam_name = vehicle_trip_cam_slice_name.split('/')[-2]
            if pose_trip_name != trip_name or pose_cam_name != ref_cam:
                continue
            ref_cam2world = np.linalg.inv(np.asarray(pose_info['world2camera']))
            ego_xy = np.asarray(pose_info['ego_xy'])
            for cam_name in extra_cam_list:
                if cam_name not in T_extra_cam2ref_cam_dict:
                    print(f"Warning: {cam_name} not in T_extra_cam2ref_cam_dict")
                    continue
                T_cam2world = ref_cam2world @ T_extra_cam2ref_cam_dict[cam_name]
                T_world2cam = np.linalg.inv(T_cam2world)
                new_value = deepcopy(pose_info)
                new_value['camera2world'] = T_cam2world.tolist()
                new_value['world2camera'] = T_world2cam.tolist()
                new_value['cam_intrinsic'] = extra_cam_intrinsic[cam_name]
                new_value['cam_distort_coeffs'] = [0,0,0,0,0,0,0,0]
                new_value['ego_xy'] = ego_xy.tolist()
                new_key = vehicle_trip_cam_slice_name.replace(ref_cam, cam_name)
                new_dict[new_key] = new_value
        recon_pose_dict.update(new_dict)
    return recon_pose_dict


def get_interpolated_pose(original_image_mapping, configs):
    orig_data_dir = configs["base_dir"]
    exp_dir = configs["exp_dir"]

    if configs["mode"] == "reloc":
        recon_config = load_config(os.path.join(configs["exp_dir"], 'config.yaml'))
        recon_dataset = Dataset(recon_config)
        dataset = Dataset(configs, recon_config["dataset_param"])
        num_camera = len(dataset.image_name_to_extrinsic_map)
    else:
        dataset = Dataset(configs)
        num_camera = len(dataset.cam_name_to_cam_index_map)

    dataset.enable_all_data()
    pose_model = load_pose_model(configs, num_camera, os.path.join(configs["rome_output_dir"], "pose_baseline.pt"))
    np.save(os.path.join(configs["rome_output_dir"], "ori_world_to_new_world.npy"), dataset.ori_world_to_new_world)

    ### Calculate the required pose information for each image
    rome_extrinsic = {}
    with torch.no_grad():
        for camera_idx in dataset.cameras_idx:
            rome_extrinsic[camera_idx] = pose_model([camera_idx])[0].detach().cpu().numpy()

    cutoff_radius = dataset.cutoff_radius
    cut_center = dataset.cut_center

    interpolate_pose_dict = {}
    interpolate_pose_vis = []
    trips_info = json.load(open(configs['trips_json'], 'r'))
    trips_info = convert_rel_to_abs_dict(trips_info, configs["reloc_dir"]) if configs["mode"] == "reloc" else convert_rel_to_abs_dict(trips_info, exp_dir)
    trip_intrinsic_dict, undistorted_avm_intrinsic_dict= get_cam_intrinsic(trips_info, configs["cam_list"], configs.get("avm_cam_list", []))

    for trip_path, clips in trips_info.items():
        trip_name = '_'.join(trip_path.split('/')[-2:])
        sorted_trip_slice_names = []
        sorted_trip_local_pose = []
        trip_slice_names_to_id = {}
        trip_slice_names_to_slice_id = {}
        for seq_num, clip_id in clips.items():
            print(f'Processing {trip_name} {seq_num} {clip_id}')
            original_data_path = os.path.join(orig_data_dir, trip_path)
            clip_calib_json = json.load(open(os.path.join(original_data_path, 'calib.json'), 'r'))

            # slice image by smooth pose distance
            for key, value in clip_calib_json.items():
                if key != 'local_pose':
                    continue
                for slice_name, pose in value.items():
                    sorted_trip_slice_names.append(os.path.join(clip_id, slice_name))
                    sorted_trip_local_pose.append(np.array(pose).astype(np.float64))
                    trip_slice_names_to_id[os.path.join(clip_id, slice_name)] = len(sorted_trip_slice_names) - 1
                    trip_slice_names_to_slice_id[os.path.join(clip_id, slice_name)] = clip_calib_json["slice_id"][slice_name]

        origin_id_to_sample_slice = {}
        origin_id_to_sample_pose = np.full(len(sorted_trip_slice_names), 0)
        for key, value in original_image_mapping.items():
            if not trip_name == '_'.join(key.split('/')[:2]):
                continue
            if 'cam2' not in key:
                continue
            tmp = key.split('/')
            sample_pose_slice = tmp[3].split('.')[0]
            origin_slice_id = trip_slice_names_to_id[value['clip_id'] + '/slice' + value['slice_idx']]
            origin_id_to_sample_slice[origin_slice_id] = sample_pose_slice
            origin_id_to_sample_pose[origin_slice_id] = 1
        # find interpolate and its prev pose pair
        sample_slice_num = np.sum(origin_id_to_sample_pose)
        prev_sample_pose_id = None
        interpolate_pose = {}
        count = 0
        for ori_id, ori_name in enumerate(sorted_trip_slice_names):
            if origin_id_to_sample_pose[ori_id] > 0:
                prev_sample_pose_id = ori_id
                count += 1
                continue
            else:
                if prev_sample_pose_id is None:
                    continue
                else:
                    if count <= sample_slice_num:
                        interpolate_pose[ori_id] = prev_sample_pose_id

        # interpolate pose
        assert len(dataset.cameras_idx) == len(dataset.image_filenames) == len(dataset.camera_extrinsics) == len(dataset.ref_camera2world)
        trip_calib = json.load(open(os.path.join(trip_path, "calib.json"), "r"))
        outlier_cam_list = trip_calib.get("outlier_cam_list", [])
        cam_extrinsics = {}
        cam_list = configs["cam_list"]
        rome_cam_list = configs["rome_cam_list"] if "rome_cam_list" in configs else cam_list
        ref_cam = configs["ref_cam"]
        for cam in cam_list:
            if outlier_cam_list is not None and cam in outlier_cam_list:
                continue
            matrix = trip_calib[cam]["extrinsic"]["transformation_matrix"]
            cam_extrinsics[cam] = np.linalg.inv(np.array(matrix).astype(np.float64)) # cam to ego

        """ Convert all camera extrinsics to the ref_cam coord system """
        ref2cam_transform = {}
        cam2ref_transform = {}
        for cam in cam_list:
            if outlier_cam_list is not None and cam in outlier_cam_list:
                continue
            if cam == ref_cam:
                ref2cam_transform[cam] = np.eye(4)
                cam2ref_transform[cam] = np.eye(4)
            else:
                cam_ext = cam_extrinsics[cam] # cam to ego
                ref_cam_ext = cam_extrinsics[ref_cam] # ref to ego
                ref2cam_transform[cam] = np.linalg.inv(cam_ext) @ ref_cam_ext
                cam2ref_transform[cam] = np.linalg.inv(ref2cam_transform[cam])

        if configs["pose_source"] == "colmap":
            for cam in cam_list:
                if outlier_cam_list is not None and cam in outlier_cam_list:
                    continue
                cam_slice0_colmap_pose = np.array(trip_calib["colmap_extrinsic"]["slice0_" + cam]).astype(np.float64) # cam to world
                ref_slice0_colmap_pose = np.array(trip_calib["colmap_extrinsic"][f"slice0_{ref_cam}"]).astype(np.float64) # ref to world
                ref2cam_transform[cam] = np.linalg.inv(cam_slice0_colmap_pose) @ ref_slice0_colmap_pose
                cam2ref_transform[cam] = np.linalg.inv(ref2cam_transform[cam])

        colmap_extrinsic = trip_calib["colmap_extrinsic"]
        for ori_id, prev_id in interpolate_pose.items():
            origin_slice = sorted_trip_slice_names[ori_id]
            origin_local_pose = sorted_trip_local_pose[ori_id] # ego to world
            prev_slice = sorted_trip_slice_names[prev_id]
            prev_local_pose = sorted_trip_local_pose[prev_id] # ego to world
            prev_to_origin = np.linalg.inv(origin_local_pose) @ prev_local_pose # ego to ego

            sample_slice = origin_id_to_sample_slice[prev_id]
            for cam in cam_list:
                if outlier_cam_list is not None and cam in outlier_cam_list:
                    continue
                prev_colmap = colmap_extrinsic[sample_slice + '_' + cam]
                translation = np.array(prev_colmap)[:3, 3]
                if type(cut_center) == np.ndarray:
                    if np.linalg.norm(translation - cut_center) > cutoff_radius:
                        continue
                prev_colmap = np.linalg.inv(np.array(prev_colmap).astype(np.float64)) # world to cam
                inter_pose = np.linalg.inv(cam_extrinsics[cam]) @ prev_to_origin @ cam_extrinsics[cam] @ prev_colmap
                camera2world = dataset.ori_world_to_new_world @ np.linalg.inv(inter_pose)

                cam_unique_name = '/'.join(['/'.join(trip_path.split('/')[-2:]), cam])
                if cam not in rome_cam_list:
                    world2camera = np.linalg.inv(camera2world)
                else:
                    camera_idx = dataset.cam_name_to_cam_index_map[cam_unique_name]
                    world2camera = rome_extrinsic[camera_idx] @ np.linalg.inv(camera2world)

                origin_img_name = os.path.join(origin_slice.split('/')[0], origin_slice.split('/')[1] + '_' + cam + '.png')
                intrinsic_matrix = trip_intrinsic_dict[trip_name][cam]["intrinsic_matrix"]
                distort_coeffs = trip_intrinsic_dict[trip_name][cam]["distort_coeffs"]
                interpolate_pose_dict[origin_img_name] = {
                    "world2camera": world2camera.tolist(),
                    "cam_intrinsic": intrinsic_matrix.numpy().tolist(),
                    "cam_distort_coeffs": np.array(distort_coeffs).tolist(),
                    "slice_id": trip_slice_names_to_slice_id[origin_slice]
                }
                if cam in configs.get("avm_cam_list", []):
                    interpolate_pose_dict[origin_img_name]["Mei_model_Xi"] = trip_intrinsic_dict[trip_name][cam]["Xi"]
                    interpolate_pose_dict[origin_img_name]["undistorted_intrinsic"] = undistorted_avm_intrinsic_dict[trip_name][cam]["intrinsic_matrix"].numpy().tolist()
                ### Calculate ego_xy for each image
                ego_xy = (camera2world @ ref2cam_transform[cam])[:2, 3]
                ego_xy /= recon_config["bev_resolution"] if configs["mode"] == "reloc" else configs["bev_resolution"]
                ego_xy[1] = recon_config["bev_y_pixel"] - ego_xy[1] if configs["mode"] == "reloc" else configs["bev_y_pixel"] - ego_xy[1]
                ego_xy = np.round(ego_xy).astype(np.int32)
                interpolate_pose_dict[origin_img_name]["ego_xy"] = ego_xy.tolist()
                interpolate_pose_vis.append(camera2world @ ref2cam_transform[cam])

    return interpolate_pose_dict


def get_recon_poses(configs):
    exp_dir = configs["exp_dir"]
    dataset = Dataset(configs)
    dataset.enable_all_data()
    draw_input_pose(configs, dataset)

    num_camera = len(dataset.cam_name_to_cam_index_map)
    pose_model = load_pose_model(configs, num_camera, os.path.join(configs["rome_output_dir"], "pose_baseline.pt"))

    ### Calculate the required pose information for each image
    rome_extrinsic = {}
    with torch.no_grad():
        for camera_idx in tqdm(dataset.cameras_idx):
            rome_extrinsic[camera_idx] = pose_model([camera_idx])[0].detach().cpu().numpy()

    trips_info = json.load(open(configs['trips_json'], 'r'))
    trips_info = convert_rel_to_abs_dict(trips_info, exp_dir)
    trip_intrinsic_dict, undistorted_avm_intrinsic_dict = get_cam_intrinsic(trips_info, configs["cam_list"], configs.get("avm_cam_list", []))
    recon_pose_dict = {}
    assert len(dataset.cameras_idx) == len(dataset.image_filenames) == len(dataset.camera_extrinsics) == len(dataset.ref_camera2world)
    for idx, camera_idx in enumerate(dataset.cameras_idx):
        img_path = dataset.image_filenames[idx]
        img_path_split = img_path.split('/')
        trip_name = '_'.join(img_path_split[-4:-2])
        img_name = img_path.split("image/")[-1]
        cam_name = img_path_split[-2]

        intrinsic_matrix = trip_intrinsic_dict[trip_name][cam_name]["intrinsic_matrix"]
        distort_coeffs = trip_intrinsic_dict[trip_name][cam_name]["distort_coeffs"]
        camera2world = dataset.world2bev @ dataset.ref_camera2world[idx] @ dataset.camera_extrinsics[idx]
        world2camera = rome_extrinsic[camera_idx] @ np.linalg.inv(camera2world)
        recon_pose_dict[img_name] = {
            "camera2world": camera2world.tolist(),
            "world2camera": world2camera.tolist(),
            "cam_intrinsic": intrinsic_matrix.numpy().tolist(),
            "cam_distort_coeffs": np.array(distort_coeffs).tolist(),
        }
        if cam_name in configs.get("avm_cam_list", []):
            recon_pose_dict[img_name]["Mei_model_Xi"] = trip_intrinsic_dict[trip_name][cam_name]["Xi"]
            recon_pose_dict[img_name]["undistorted_intrinsic"] = undistorted_avm_intrinsic_dict[trip_name][cam_name]["intrinsic_matrix"].numpy().tolist()

    ### Calculate ego_xy for each image
    world2bev_xy = dataset.world2bev[:2, 3]
    for idx, img_path in enumerate(dataset.image_filenames_all):
        img_name = img_path.split("image/")[-1]
        if img_name not in recon_pose_dict:
            continue
        ego_xy = dataset.ref_camera2world_all[idx][:2, 3]
        ego_xy += world2bev_xy
        ego_xy /= configs["bev_resolution"]
        ego_xy[1] = configs["bev_y_pixel"] - ego_xy[1]
        ego_xy = np.round(ego_xy).astype(np.int32)
        recon_pose_dict[img_name]["ego_xy"] = ego_xy.tolist()

    return recon_pose_dict

def draw_all_pose(configs, dataset, interpolate_pose_vis):
    """
    Draw the trajectory and elevation of each input trip.
    """
    ### Get lists of input image paths and poses
    all_img_poses = dataset.ref_camera2world_all
    all_img_paths = dataset.image_filenames_all
    trip_info = json.load(open(configs["trips_json"], 'r'))
    fig, ax = plt.subplots(1, 1, figsize=(10, 10), dpi=100)

    for trip_path in trip_info.keys():
        ### Get paths and poses of the reference camera of the current trip
        curr_img_paths, curr_trip_poses = [], []
        for i, img_path in enumerate(all_img_paths):
            if trip_path in img_path and configs["ref_cam"] in img_path:
                curr_img_paths.append(all_img_paths[i])
                curr_trip_poses.append(all_img_poses[i])

        ### Sort poses by slice index
        zip_path_pose = list(zip(curr_img_paths, curr_trip_poses))
        zip_path_pose = sorted(zip_path_pose, key=lambda x: int(x[0].split(".png")[0].split("slice")[-1]))
        curr_trip_poses = [pose for (path, pose) in zip_path_pose]
        curr_trip_poses = np.stack(curr_trip_poses)
        curr_trip_xy = curr_trip_poses[:, 0:2, 3]
        trip_name = trip_path.split("image/")[1]
        color = np.random.rand(3)
        draw_trip_trajectory(ax, trip_name, curr_trip_xy, color)

    world2bev = dataset.world2bev
    inter_pose = []
    for pose in interpolate_pose_vis:
        tmp = np.linalg.inv(world2bev) @ pose
        inter_pose.append(tmp)
    inter_pose = np.stack(inter_pose)
    inter_xy = inter_pose[:, 0:2, 3]
    ax.scatter(inter_xy[:, 0], inter_xy[:, 1], s=10, color='red')

    ax.set_title('Input trajectory')
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.axis('equal')
    plt.savefig(os.path.join(configs["gta_input_dir"], "interpolation.png"))
    plt.close(fig)

def get_reloc_poses(configs):
    reloc_dir = configs["reloc_dir"]
    recon_config = load_config(os.path.join(configs["exp_dir"], 'config.yaml'))
    recon_dataset = Dataset(recon_config)
    dataset = Dataset(configs, recon_config["dataset_param"])
    dataset.enable_all_data()

    num_camera = len(dataset.image_name_to_extrinsic_map)
    pose_model = load_pose_model(configs, num_camera, os.path.join(reloc_dir, "rome_output", "pose_baseline.pt"))

    ### Compute pose for reloc data
    trips_info = json.load(open(configs['trips_json'], 'r'))
    trips_info = convert_rel_to_abs_dict(trips_info, reloc_dir)
    trip_intrinsic_dict, _ = get_cam_intrinsic(trips_info, configs["cam_list"])
    reloc_pose_dict = {}
    assert len(dataset.cameras_idx) == len(dataset.image_filenames) == len(dataset.camera_extrinsics) == len(dataset.ref_camera2world)

    for idx, camera_idx in enumerate(dataset.cameras_idx):
        img_path = dataset.image_filenames[idx]
        img_path_split = img_path.split('/')
        trip_name = '_'.join(img_path_split[-4:-2])
        img_name = img_path.split("image/")[-1]
        cam_name = img_path_split[-2]

        intrinsic_matrix = trip_intrinsic_dict[trip_name][cam_name]["intrinsic_matrix"]
        distort_coeffs = trip_intrinsic_dict[trip_name][cam_name]["distort_coeffs"]
        camera2world = dataset.world2bev @ dataset.ref_camera2world[idx] @ dataset.camera_extrinsics[idx]
        image_extrics_idx = dataset.image_extrics_idx[idx]
        with torch.no_grad():
            rome_extrinsic = pose_model([image_extrics_idx])[0].to(torch.float64).detach().cpu().numpy()
        world2camera = rome_extrinsic @ np.linalg.inv(camera2world)
        reloc_pose_dict[img_name] = {
            "world2camera": world2camera.tolist(),
            "cam_intrinsic": intrinsic_matrix.numpy().tolist(),
            "cam_distort_coeffs": np.array(distort_coeffs).tolist(),
        }

    ### Calculate ego_xy for each image
    recon_config = load_config(os.path.join(configs["exp_dir"], 'config.yaml'))
    recon_dataset = Dataset(recon_config)
    recon_dataset_param = recon_config["dataset_param"]
    world2bev_xy = dataset.world2bev[:2, 3]
    for idx, img_path in enumerate(dataset.image_filenames_all):
        img_name = img_path.split("image/")[-1]
        if img_name not in reloc_pose_dict:
            continue
        ego_xy = dataset.ref_camera2world_all[idx][:2, 3]
        ego_xy += world2bev_xy
        ego_xy /= recon_dataset_param["bev_resolution"]
        ego_xy[1] = recon_dataset_param["bev_y_pixel"] - ego_xy[1]
        ego_xy = np.round(ego_xy).astype(np.int32)
        reloc_pose_dict[img_name]["ego_xy"] = ego_xy.tolist()

    return reloc_pose_dict


def draw_input_pose(configs, dataset, min_imgs=2):
    """
    Draw the trajectory and elevation of each input trip.
    """
    ### Get lists of input image paths and poses
    all_img_poses = dataset.ref_camera2world_all
    all_img_paths = dataset.image_filenames_all
    trip_info = json.load(open(configs["trips_json"], 'r'))
    fig, ax = plt.subplots(1, 1, figsize=(10, 10), dpi=100)

    for trip_path in trip_info.keys():
        ### Get paths and poses of the reference camera of the current trip
        curr_img_paths, curr_trip_poses = [], []
        for i, img_path in enumerate(all_img_paths):
            if trip_path in img_path and configs["ref_cam"] in img_path:
                curr_img_paths.append(all_img_paths[i])
                curr_trip_poses.append(all_img_poses[i])

        ### Skip trips with not enough images
        if len(curr_img_paths) < min_imgs:
            continue

        ### Sort poses by slice index
        zip_path_pose = list(zip(curr_img_paths, curr_trip_poses))
        zip_path_pose = sorted(zip_path_pose, key=lambda x: int(x[0].split(".png")[0].split("slice")[-1]))
        curr_trip_poses = [pose for (path, pose) in zip_path_pose]
        curr_trip_poses = np.stack(curr_trip_poses)
        curr_trip_xy = curr_trip_poses[:, 0:2, 3]
        trip_name = trip_path.split("image/")[1]
        color = np.random.rand(3)
        draw_trip_trajectory(ax, trip_name, curr_trip_xy, color)

    ax.set_title('Input trajectory')
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.axis('equal')
    plt.savefig(os.path.join(configs["gta_input_dir"], "trajectory.png"))
    plt.close(fig)


def merge_pose_dict(original_image_mapping, recon_pose, interpolated_pose):
    """
    Merge recon pose and interpolated pose for downstream clip cutting.
    """
    merged_pose = {}
    for img_name, pose in recon_pose.items():
        clip_id = original_image_mapping[img_name]["clip_id"]
        slice_id = original_image_mapping[img_name]["slice_id"]
        cam_id = original_image_mapping[img_name]["cam_id"]
        new_img_name = f"{clip_id}/{slice_id}/{cam_id}"
        merged_pose[new_img_name] = pose
        merged_pose[new_img_name]["slice_idx"] = original_image_mapping[img_name]["slice_idx"]

    for img_name, pose in interpolated_pose.items():
        clip_id = img_name.split('/')[0]
        slice_id = pose["slice_id"]
        cam_id = "cam" + (img_name.split("cam")[1]).replace(".png", "")
        pose.pop("slice_id", None)
        new_img_name = f"{clip_id}/{slice_id}/{cam_id}"
        slice_idx = re.search(r'slice(\d+)', img_name).group(1)
        merged_pose[new_img_name] = pose
        merged_pose[new_img_name]["slice_idx"] = slice_idx

    return merged_pose


def pack_recon_result(configs):
    exp_dir = configs["exp_dir"]
    configs["rome_output_dir"] = configs.get("rome_output_dir", os.path.join(exp_dir, "rome_output"))
    rome_dir = configs["rome_output_dir"]
    if not os.path.exists(os.path.join(rome_dir, "grid_baseline.pt")):
        raise Exception("No reconstruction model found.")

    configs["gta_input_dir"] = configs.get("gta_input_dir", os.path.join(exp_dir, "gta_input"))
    gta_dir = configs["gta_input_dir"]
    os.makedirs(gta_dir, exist_ok=True)

    max_epoch = configs['epochs']
    shutil.copyfile(os.path.join(rome_dir, f"bev_rgb_epoch_{max_epoch}.png"), os.path.join(gta_dir, "bev_rgb.png"))
    shutil.copyfile(os.path.join(rome_dir, f"bev_seg_epoch_{max_epoch}.png"), os.path.join(gta_dir, "bev_seg.png"))
    shutil.copyfile(os.path.join(exp_dir, "original_image_mapping.json"), os.path.join(gta_dir, "original_image_mapping.json"))

    recon_pose_dict = get_recon_poses(configs)
    if "rome_cam_list" in configs and len(configs["rome_cam_list"]) < len(configs["cam_list"]):
        recon_pose_dict = update_recon_pose_dict(configs, recon_pose_dict)
    json.dump(recon_pose_dict, open(os.path.join(gta_dir, "recon_pose.json"), "w"), indent=4)

    original_image_mapping = json.load(open(os.path.join(gta_dir, "original_image_mapping.json"), 'r'))
    interpolate_pose_dict = get_interpolated_pose(original_image_mapping, configs)
    merged_pose_dict = merge_pose_dict(original_image_mapping, recon_pose_dict, interpolate_pose_dict)
    json.dump(merged_pose_dict, open(os.path.join(gta_dir, "interpolated_pose.json"), "w"), indent=4)

    ### Compress depth array
    bev_depth = np.load(os.path.join(rome_dir, f"bev_depth_epoch_{max_epoch}.npy"))
    if configs["flatten_bev_curb_depth"]:
        save_bev_depth_uint16(bev_depth, os.path.join(gta_dir, "bev_depth_raw.png"))
        bev_seg = np.asarray(Image.open(os.path.join(gta_dir, "bev_seg.png")))
        bev_depth = postprocess_curb_depth(bev_seg, bev_depth)

    min_depth, max_depth = save_bev_depth_uint16(bev_depth, os.path.join(gta_dir, "bev_depth.png"))
    configs["min_depth"] = float(min_depth)
    configs["max_depth"] = float(max_depth)
    configs = numpy_to_list(configs)
    with open(os.path.join(gta_dir, "config.yaml"), 'w') as f:
        yaml.dump(configs, f)

    # pack local pose
    base_dir = configs["base_dir"]
    merged_trips_path = os.path.join(exp_dir, "merged_trips.json")
    merged_trips_info = json.load(open(merged_trips_path, 'r'))
    merged_clip_list = [clip_id for clip_info in merged_trips_info.values() for clip_id in clip_info.values()]

    local_pose_dict = {}
    for clip_id in merged_clip_list:
        local_pose_path = os.path.join(base_dir, "LocalPoseTopic.json")
        local_pose = json.load(open(local_pose_path, 'r'))
        local_pose_dict[clip_id] = local_pose[::50]

    local_pose_dict_path = os.path.join(gta_dir, "localpose.json")
    with open(local_pose_dict_path, 'w') as f:
        json.dump(local_pose_dict, f, indent=4)


def pack_reloc_result(configs):
    reloc_dir = configs["reloc_dir"]
    gta_dir = os.path.join(reloc_dir, "gta_input")
    os.makedirs(gta_dir, exist_ok=True)
    shutil.copyfile(os.path.join(reloc_dir, "original_image_mapping.json"), os.path.join(gta_dir, "original_image_mapping.json"))

    reloc_pose_dict = get_reloc_poses(configs)
    json.dump(reloc_pose_dict, open(os.path.join(gta_dir, "recon_pose.json"), "w"), indent=4)

    original_image_mapping = json.load(open(os.path.join(gta_dir, "original_image_mapping.json"), 'r'))
    interpolate_pose_dict = get_interpolated_pose(original_image_mapping, configs)
    merged_pose_dict = merge_pose_dict(original_image_mapping, reloc_pose_dict, interpolate_pose_dict)
    json.dump(merged_pose_dict, open(os.path.join(gta_dir, "interpolated_pose.json"), "w"), indent=4)

    with open(os.path.join(gta_dir, "config.yaml"), 'w') as f:
        yaml.dump(configs, f)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    config = load_config(args.config)
    try:
        if config["mode"] == "reloc":
            pack_reloc_result(config)
        elif config["mode"] == "recon":
            pack_recon_result(config)
    except Exception as e:
        print(e)
