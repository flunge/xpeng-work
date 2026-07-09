import os
import json
import numpy as np
import cv2
import open3d as o3d
import torch
from pathlib import Path
from scipy.spatial.transform import Rotation as R
from pathlib import Path

from utils.file_utils import get_files_in_folder
from utils.general_utils import quaternion_matrix, matrix_to_quaternion, quaternion_to_matrix_numpy


CAM_MODEL = "SIMPLE_PINHOLE"


def get_box_corners(center, dimensions, orientation):
    # 解包中心坐标、维度和四元数
    cx, cy, cz = center
    length, width, height = dimensions
    q = orientation
    # 生成正交的包围盒顶点集
    dx = length / 2.0
    dy = width / 2.0
    dz = height / 2.0

    corners = np.array(
        [
            [dx, dy, dz],
            [-dx, dy, dz],
            [-dx, -dy, dz],
            [dx, -dy, dz],
            [dx, dy, -dz],
            [-dx, dy, -dz],
            [-dx, -dy, -dz],
            [dx, -dy, -dz],
        ]
    )
    # 使用四元数创建旋转并应用到顶点集
    rotation = R.from_quat([q[1], q[2], q[3], q[0]])  # 注意quaternion顺序为[x, y, z, w]
    rotated_corners = rotation.apply(corners)
    # 将局部坐标添加到中心点坐标上得到世界坐标
    world_corners = rotated_corners + center

    return world_corners


def get_o3d_box(rotation, translation, sizes, scales=[1.2, 1.2, 2.0]):
    rotation = rotation
    translation = translation
    lwh = sizes
    world_corners = get_box_corners(translation, lwh, rotation)
    obb = o3d.geometry.OrientedBoundingBox.create_from_points(
        o3d.utility.Vector3dVector(world_corners)
    )
    scale_x = scales[0]
    scale_y = scales[1]
    scale_z = scales[2]
    extents = np.array(obb.extent) * np.array([scale_x, scale_y, scale_z]) # 更新边界长度
    obb = o3d.geometry.OrientedBoundingBox(obb.center, obb.R, extents)
    return obb


def parser_autolabel_json(files_path, select_box_info):
    file_paths = get_files_in_folder(files_path)
    autolabel_json = {}
    uuid2timestamp = {}
    if type(select_box_info) != list:
        select_box_info = [select_box_info]

    for i in range(len(file_paths)):
        file = file_paths[i]
        file_name = Path(file).name
        if not file_name.startswith("c-") or not file_name.endswith(".json") or "check" in file_name:
            print("[WARNING] Found invalid autolabel json: ", file)
            continue
        with open(file, "r") as fout:
            meta = json.load(fout)
            time_stamp = meta["frame_info"]["time_stamp"].get("cam2", None)
            if time_stamp == None:
                print(f"[FATAL] File not own time_stamp {file}")
                continue

            if time_stamp in autolabel_json:
                print(f"[WARNING] File {file} has same time_stamp {time_stamp} with other file")
                continue
            uuid2timestamp[meta["frame_info"]["uuid"]] = time_stamp

            local_pose = np.eye(4)
            local_pose[:3,:3] = meta["ego_info"]["rotation_enu_to_rig"]
            local_pose[:3,3] = meta["ego_info"]["translation_enu_to_rig"]
            local_pose = np.linalg.inv(local_pose)
            objs = []
            for obj in meta["mod_list"]:
                if not obj.get("mod_3d", None) or any([obj["mod_3d"].get(bname, False) for bname in select_box_info]) == False:
                    continue
                for j in select_box_info:
                    if j in obj["mod_3d"]:
                        obj_info = obj["mod_3d"][j]
                        break
                size = [obj_info["length"], obj_info["width"], obj_info["height"]]
                translation = [obj_info["x"], obj_info["y"], obj_info["z"]]
                rotation = [obj_info["quaternion"]["w"],\
                            obj_info["quaternion"]["x"],\
                            obj_info["quaternion"]["y"],\
                            obj_info["quaternion"]["z"]]
                gid = obj["mod_3d"]["track_id"]
                obj_type = obj["mod_3d"]["category"]

                vx = obj["mod_3d"]["velocity"]["world_formula"]["x"]
                vy = obj["mod_3d"]["velocity"]["world_formula"]["y"]
                credible = obj["mod_3d"]["velocity"]["credible"]
                vector = np.array([vx, vy])
                norm_2 = np.linalg.norm(vector)
                is_moving = True if norm_2 > 0.5 and credible else False
                objs.append({"type": obj_type, \
                    "gid": gid, \
                    "translation": translation, \
                    "size": size, \
                    "rotation": rotation, \
                    "is_moving": is_moving
                })
            autolabel_json[str(time_stamp)]={
                "objects": objs,\
                "local_pose": local_pose.tolist(),
                "uuid": meta["frame_info"]["uuid"]
            }
    ### obj coordinate is in the rig coordinate of that frame
    return autolabel_json


def get_transform_json(images_list, calibrations, cam_hw_dict, localpose, anchorpose, target_lidar, vision_mode=False):
    camera_frames = []
    lidar_frames = []

    for img_name in images_list:
        rig2world = localpose[img_name.split('.')[0]]
        rig2world = np.array(rig2world).reshape(4, 4)
        for cam_name in calibrations._cam_list:
            cam2rig = np.linalg.inv(calibrations._cam_from_rig[cam_name])
            cam2anchor = np.linalg.inv(anchorpose) @ rig2world @ cam2rig
            lidar2anchor = None
            if not vision_mode:
                lidar2anchor = np.linalg.inv(anchorpose) @ rig2world @ calibrations._lidar2rig
            
            w, h = cam_hw_dict[cam_name]["w"], cam_hw_dict[cam_name]["h"]
            frame_image, frame_lidar = get_transform_one_frame(
                cam2anchor, lidar2anchor, cam_name, img_name, w, h, calibrations._calibrations, vision_mode=vision_mode
            )
            camera_frames.append(frame_image)
        lidar_frames.append(frame_lidar)

    sensor_params = extract_sensor_params(calibrations, cam_hw_dict, target_lidar, vision_mode=vision_mode)
    meta = {"sensor_params": sensor_params, "frames": camera_frames, "lidar_frames": lidar_frames}
    return meta


def get_transform_one_frame(cam2anchor, lidar2anchor, cam_name, img_name, w, h, calib, vision_mode=False):
    if 'focal_length_x' in calib[cam_name]['intrinsic'] and 'focal_length_y' in calib[cam_name]['intrinsic']:
        fl_x = calib[cam_name]['intrinsic']['focal_length_x']
        fl_y = calib[cam_name]['intrinsic']['focal_length_y']
    else:
        fl_x = calib[cam_name]['intrinsic']['focal_length']
        fl_y = calib[cam_name]['intrinsic']['focal_length']

    frame_image = {
        "file_path": os.path.join('images', cam_name, img_name),
        "fl_x": fl_x,
        "fl_y": fl_y,
        "cx": calib[cam_name]['intrinsic']['cx'],
        "cy": calib[cam_name]['intrinsic']['cy'],
        "w": w,
        "h": h,
        "camera_model": CAM_MODEL,
        "camera": cam_name,
        "timestamp": int(img_name.split('.')[0]),
        "k1": calib[cam_name]['intrinsic']['k1'],
        "k2": calib[cam_name]['intrinsic']['k2'],
        "k3": calib[cam_name]['intrinsic']['k3'],
        "k4": calib[cam_name]['intrinsic']['k4'],
        "k5": calib[cam_name]['intrinsic']['k5'],
        "k6": calib[cam_name]['intrinsic']['k6'],
        "p1": calib[cam_name]['intrinsic']['p1'],
        "p2": calib[cam_name]['intrinsic']['p2'],
        "transform_matrix": cam2anchor.tolist(),
    }
    frame_lidar = {}
    if not vision_mode:
        frame_lidar = {
            "file_path": os.path.join('pcd', img_name.replace('png', 'pcd')),
            "lidar": 'lidarm1',
            "timestamp": int(img_name.split('.')[0]),
            "transform_matrix": lidar2anchor.tolist(),
        }
    return frame_image, frame_lidar


def extract_sensor_params(calib, cam_hw_dict, target_lidar, vision_mode=False):
    camera_order = []
    out = {}
    for i, cam_name in enumerate(calib._cam_list):
        camera_order.append(cam_name)
        if 'focal_length_x' in calib._calibrations[cam_name]['intrinsic'] \
            and 'focal_length_y' in calib._calibrations[cam_name]['intrinsic']:
            fx = calib._calibrations[cam_name]['intrinsic']['focal_length_x']
            fy = calib._calibrations[cam_name]['intrinsic']['focal_length_y']
        else:
            fx = calib._calibrations[cam_name]['intrinsic']['focal_length']
            fy = calib._calibrations[cam_name]['intrinsic']['focal_length']
        cx = calib._calibrations[cam_name]['intrinsic']['cx']
        cy = calib._calibrations[cam_name]['intrinsic']['cy']
        distortion = [
            calib._calibrations[cam_name]['intrinsic']['k1'],
            calib._calibrations[cam_name]['intrinsic']['k2'],
            calib._calibrations[cam_name]['intrinsic']['p1'],
            calib._calibrations[cam_name]['intrinsic']['p2'],
            calib._calibrations[cam_name]['intrinsic']['k3']
        ]

        extrinsic = np.array(
            calib._calibrations[cam_name]['extrinsic']['transformation_matrix']
        ).reshape((4, 4))

        cam2rig = np.linalg.inv(extrinsic)
        camera_intrinsic_mat = np.array([
                [fx, 0.0, cx],
                [0.0, fy, cy],
                [0.0, 0.0, 1.0],
            ])

        w = cam_hw_dict[cam_name]["w"]
        h = cam_hw_dict[cam_name]["h"]
        out[cam_name] = {
            "type": "camera",
            "camera_model": CAM_MODEL,
            "camera_intrinsic": camera_intrinsic_mat.tolist(),
            "camera_D": distortion,
            "extrinsic": cam2rig.tolist(),
            "width": w,
            "height": h,
        }
    out['camera_order'] = camera_order
    if not vision_mode:
        lidar_name = target_lidar
        extrinsic = np.array(
            calib._calibrations[target_lidar]['extrinsic']['transformation_matrix']
        ).reshape((4, 4))
        lidar2rig = np.linalg.inv(extrinsic)
        out[lidar_name] = {"type": "lidar", "extrinsic": lidar2rig.tolist()}
    return out


def tranform_to_matrix(rotation, translation):
    tranform_matrix = np.eye(4)
    mat = R.from_quat([rotation[1], rotation[2], rotation[3], rotation[0]])
    tranform_matrix[:3,:3] = mat.as_matrix()
    tranform_matrix[:3, 3] = translation
    return tranform_matrix


def get_global_object_moving_status(annotations):
    obj_xyz = {}
    obj_moving = {}
    sorted_objects = list(sorted(annotations.items()))
    t_0 = -1
    for t_obj in sorted_objects:
        assert int(t_obj[0]) > t_0, "timestamps are not sorted"
        t_0 = int(t_obj[0])

        frame = t_obj[1]
        objects = frame["objects"]
        for obj in objects:
            xyz = obj["translation"]
            gid = obj["gid"]
            if gid not in obj_xyz:
                obj_xyz[gid] = []
            obj_xyz[gid].append(xyz)

    for gid, xyz in obj_xyz.items():
        xyz = np.array(xyz)
        distance = np.linalg.norm(xyz[0] - xyz[-1])
        dynamic = np.any(np.std(xyz, axis=0) > 0.5) or distance > 2
        obj_moving[gid] = True if dynamic else False        

    return obj_moving


def get_mask_obj_bound(annotation_dict, transform_frame, moving_gids, calib):
    timestamp = transform_frame["timestamp"]
    camera = transform_frame["camera"]
    cam2anchor = np.array(transform_frame["transform_matrix"])
    rig2cam = np.array(calib[camera]['extrinsic']['transformation_matrix']).reshape(4, 4)
    
    ego_pose = cam2anchor @ rig2cam
    h = transform_frame["h"]
    w = transform_frame["w"]
    fl_x = transform_frame["fl_x"]
    fl_y = transform_frame["fl_y"]
    cx = transform_frame["cx"]
    cy = transform_frame["cy"]
    intrinsic_matrix = np.array([[fl_x, 0, cx], [0, fl_y, cy], [0, 0, 1]])

    found_dict = annotation_dict.get(str(timestamp), None)
    obj_bound = np.zeros((h, w)).astype(np.uint8)

    if found_dict is not None:
        boxes = []
        for object in found_dict["objects"]:
            if moving_gids[object["gid"]]:
                translation = object['translation']
                rotation = object['rotation']
                obj_pose_vehicle_tracklet, _ = make_obj_pose(ego_pose, translation, rotation)
                obj_pose_vehicle = np.eye(4)    
                obj_pose_vehicle[:3, :3] = quaternion_to_matrix_numpy(obj_pose_vehicle_tracklet[3:])
                obj_pose_vehicle[:3, 3] = obj_pose_vehicle_tracklet[:3]

                obj_length, obj_width, obj_height = object["size"]
                bbox = np.array([[-obj_length, -obj_width, -obj_height], 
                                 [obj_length, obj_width, obj_height]]) * 0.5
                corners_local = bbox_to_corner3d(bbox)
                corners_local = np.concatenate([corners_local, np.ones_like(corners_local[..., :1])], axis=-1)
                corners_vehicle = corners_local @ obj_pose_vehicle.T # 3D bounding box in vehicle frame
                mask_func_input = dict({
                    "corners_3d": corners_vehicle[..., :3],
                    "K": intrinsic_matrix,
                    "pose": rig2cam, 
                    "H": h, "W": w
                })
                mask = get_bound_2d_mask(**mask_func_input)
                if mask.sum() / int(mask.shape[0]*mask.shape[1]) > 0.95:
                    mask = get_bound_2d_mask_fix(**mask_func_input)
                obj_bound = np.logical_or(obj_bound, mask)
    obj_bound = 255 - obj_bound * 255
    return obj_bound


# calculate obj pose in vehicle frame
def make_obj_pose(ego_pose, translation, rotation):
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


def bbox_to_corner3d(bbox):
    min_x, min_y, min_z = bbox[0]
    max_x, max_y, max_z = bbox[1]
    
    corner3d = np.array([
        [min_x, min_y, min_z],
        [min_x, min_y, max_z],
        [min_x, max_y, min_z],
        [min_x, max_y, max_z],
        [max_x, min_y, min_z],
        [max_x, min_y, max_z],
        [max_x, max_y, min_z],
        [max_x, max_y, max_z],
    ])
    return corner3d


def get_bound_2d_mask_fix(corners_3d, K, pose, H, W):
    # Transform corners from world to camera coordinates
    corners_3d = np.dot(corners_3d, pose[:3, :3].T) + pose[:3, 3:].T
    
    # Filter out points with negative or zero z-coordinates
    valid_indices = np.where(corners_3d[:, 2] > 0)[0]
    corners_3d = corners_3d[valid_indices]
    
    # Project valid 3D points to 2D image plane
    corners_3d[..., 2] = np.clip(corners_3d[..., 2], a_min=1e-3, a_max=None)
    corners_3d = np.dot(corners_3d, K.T)
    corners_2d = corners_3d[:, :2] / corners_3d[:, 2:]
    corners_2d = np.round(corners_2d).astype(int)
    
    # Create the mask and draw only polygons with valid points
    mask = np.zeros((H, W), dtype=np.uint8)
    
    if len(corners_2d) >= 4:
        all_faces = [
            [0, 1, 3, 2, 0],
            [4, 5, 7, 6, 5],
            [0, 1, 5, 4, 0],
            [2, 3, 7, 6, 2],
            [0, 2, 6, 4, 0],
            [1, 3, 7, 5, 1]
        ]
        for face in all_faces:
            if set(face).issubset(valid_indices):
                query_idx = [np.where(idx==valid_indices)[0][0] for idx in face]
                cv2.fillPoly(mask, [corners_2d[query_idx]], 1)
    
    return mask


def get_bound_2d_mask(corners_3d, K, pose, H, W):
    corners_3d = np.dot(corners_3d, pose[:3, :3].T) + pose[:3, 3:].T
    if np.all(corners_3d[..., 2] <= 0):
        return np.zeros((H, W), dtype=np.uint8)
    corners_3d[..., 2] = np.clip(corners_3d[..., 2], a_min=1e-3, a_max=None)
    corners_3d = np.dot(corners_3d, K.T)
    corners_2d = corners_3d[:, :2] / corners_3d[:, 2:]
    corners_2d = np.round(corners_2d).astype(int)
    mask = np.zeros((H, W), dtype=np.uint8)
    cv2.fillPoly(mask, [corners_2d[[0, 1, 3, 2, 0]]], 1)
    cv2.fillPoly(mask, [corners_2d[[4, 5, 7, 6, 5]]], 1)
    cv2.fillPoly(mask, [corners_2d[[0, 1, 5, 4, 0]]], 1)
    cv2.fillPoly(mask, [corners_2d[[2, 3, 7, 6, 2]]], 1)
    cv2.fillPoly(mask, [corners_2d[[0, 2, 6, 4, 0]]], 1)
    cv2.fillPoly(mask, [corners_2d[[1, 3, 7, 5, 1]]], 1)
    return mask

