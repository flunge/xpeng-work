import os, sys
import numpy as np
import json
from copy import deepcopy


def get_trip_and_clip_ids(trip_json):
    """
    Get the trip name and clip ids from the trip json file.
    """
    trip_dict = json.load(open(trip_json, 'r'))
    trip_path = list(trip_dict.keys())[0]
    clip_id_list = [clip_id for idx, clip_id in trip_dict[trip_path].items()]
    _, vehicle_name, timestamp = trip_path.split("/")
    trip_name = f"{vehicle_name}_{timestamp}"

    return trip_name, clip_id_list


def generate_rig0_to_cams_info(interpolated_poses, image_timestamps_info, rig0_to_rome):
    rig0_to_cams = {}
    rig0_to_cams_info = {}
    for key, value in interpolated_poses.items():
        cam_name = key.split("/")[-1]
        slice_id = key.split("/")[-2]
        slice_idx = value["slice_idx"]
        world2camera = value["world2camera"]
        rome_to_cam = np.array(world2camera).reshape(4, 4)
        rig0_to_cam = (rome_to_cam @ rig0_to_rome).tolist()

        key_name = "slice"+slice_idx+"/"+slice_id+"/"+cam_name+"/"+str(image_timestamps_info['cam2'][int(slice_idx)])
        rig0_to_cams[key_name] = rig0_to_cam

        timestamp = str(image_timestamps_info['cam2'][int(slice_idx)])
        key_name = cam_name + "/" + timestamp
        rig0_to_cams_info[key_name] = rig0_to_cam
    return rig0_to_cams, rig0_to_cams_info


def get_localpose_and_anchorpose_from_static_recon(interpolated_poses, image_timestamps_info, calibrations):
    cam2_to_rig = np.linalg.inv(calibrations._cam_from_rig['cam2'])
    anchorpose = None
    localpose = {}
    for key, value in interpolated_poses.items():
        cam_name = key.split("/")[-1]
        if cam_name == "cam2":
            slice_idx = value["slice_idx"]
            world2camera = value["world2camera"]
            rig0_to_cam2 = np.array(world2camera).reshape(4, 4)
            timestamp = str(image_timestamps_info['cam2'][int(slice_idx)])
            rig0_to_ego = cam2_to_rig @ rig0_to_cam2
            localpose[timestamp] = np.linalg.inv(rig0_to_ego).tolist()
            if slice_idx == "0":
                anchorpose = np.array(localpose[timestamp])
    localpose = dict(sorted(localpose.items()))
    return localpose, anchorpose


def get_tansform_json_from_static_recon(tranform_json, rig0_to_cams_info):
    tranform_json_new = deepcopy(tranform_json)
    for i, frame_info in enumerate(tranform_json_new["frames"]):
        image_path = frame_info["file_path"]
        # 去掉文件扩展名
        filename_without_extension = os.path.splitext(os.path.basename(image_path))[0]
        # 提取目录
        directory = os.path.dirname(image_path)
        key_name = os.path.join(directory, filename_without_extension).replace("images/", "")
        tranform_json_new["frames"][i]["transform_matrix"] = np.linalg.inv(rig0_to_cams_info[key_name]).tolist()
    return tranform_json_new


def get_localpose_from_static_recon_oss(root, clip_id, calibrations):
    clip_root = os.path.join(root, clip_id)
    data_dir = os.path.join(clip_root, 'localpose_and_timestamp', clip_id)
    image_timestamps = os.path.join(data_dir, "image_timestamps.json")
    with open(os.path.join(image_timestamps), 'r') as f:
        image_timestamps_info = json.load(f)

    interpolated_pose_dir = os.path.join(clip_root, "interpolated_pose_new.json")
    with open(interpolated_pose_dir, 'r') as f:
        interpolated_poses = json.load(f)

    localpose, anchorpose = get_localpose_and_anchorpose_from_static_recon(
        interpolated_poses, image_timestamps_info, calibrations
    )
    return localpose, anchorpose


def get_transform_json_new_from_static_recon_oss(root, clip_id, tranform_json, anchorpose):
    clip_root = os.path.join(root, clip_id)
    data_dir = os.path.join(clip_root, 'localpose_and_timestamp', clip_id)
    image_timestamps = os.path.join(data_dir, "image_timestamps.json")
    with open(os.path.join(image_timestamps), 'r') as f:
        image_timestamps_info = json.load(f)

    interpolated_pose_dir = os.path.join(clip_root, "interpolated_pose_new.json")
    with open(interpolated_pose_dir, 'r') as f:
        interpolated_poses = json.load(f)

    rig0_to_cams, rig0_to_cams_info = generate_rig0_to_cams_info(
        interpolated_poses, image_timestamps_info, anchorpose
    )
    tranform_json_new = get_tansform_json_from_static_recon(tranform_json, rig0_to_cams_info)
    return tranform_json_new


def load_vision_intrinsics(calib_path):
    intrinsics = {}
    cam_list = ["cam0", "cam2", "cam3", "cam4", "cam5", "cam6", "cam7"]
    for cam_name in cam_list:
        with open(os.path.join(calib_path, "intrinsics", cam_name+".txt")) as f:
            lines = f.readlines()
        fx = float(lines[0])
        fy = float(lines[1])
        cx = float(lines[2])
        cy = float(lines[3])
        dist_coeffs = [float(k) for k in lines[4:9]]

        dist_coeffs = np.array(dist_coeffs)
        intrinsics[cam_name] = {
            "intrinsic": {
                "focal_length_x": fx,
                "focal_length_y": fy,
                "cx": cx,
                "cy": cy,
                "distortion": dist_coeffs.tolist(),
                "name": cam_name
            }
        }
    return intrinsics