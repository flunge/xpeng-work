import os
from typing import List
import json
import logging
import yaml
import numpy as np
import cv2
from scipy.spatial.transform import Rotation as R
from tqdm import tqdm

from .xpeng_utils import quaternion_matrix
from ...utils.geometry import project_camera_points_to_image

logger = logging.getLogger()

# Xpeng Camera IDs
# 0: front camera
# 2: fish eye front camera
# 3: front-left camera
# 4: front-right camera
# 5: rear-left camera
# 6: rear-right camera
# 7: rear camera
CAMERA_LIST = [0, 2, 3, 4, 5, 6, 7]

def project_human_boxes(
    scene_dir: str,
    camera_list: List[int],
    save_temp=True,
    verbose=False,
    narrow_width_ratio=0.2,
    fps=12,
):
    # all cams' intrinsic and extrinsic parameters are stored in transform.json 
    transform_file = os.path.join(scene_dir, "transform.json")

    # instance annotations are stored in annotation_for_train.json
    instance_annotation_file = os.path.join(scene_dir, "annotation_for_train.json")

    valid_paths = [transform_file, instance_annotation_file]
    for path in valid_paths:
        assert os.path.exists(
            path
        ), f"Path {path} does not exist, you need to run xpeng preprocess to generate the necessary files"

    # create directories for saving the results
    save_dir = f"{scene_dir}/humanpose/temp/Pedes_GTTracks"
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
    
    if verbose:
        # create directories for saving the intermediate visualization results
        video_dir = f"{scene_dir}/humanpose/temp/Pedes_GTTracks/vis"
        if not os.path.exists(video_dir):
            os.makedirs(video_dir)
        per_human_img_dir = f"{scene_dir}/humanpose/temp/Pedes_GTTracks/vis/images"
        if not os.path.exists(per_human_img_dir):
            os.makedirs(per_human_img_dir)
    
    annotation_frames = json.load(open(instance_annotation_file))['frames']

    calibrations, intrinsics, extrinsics, ego_frame_poses, _, _ = load_camera_info(scene_dir, camera_list)

    collector_all = {}
    # iterate over each camera
    for cam_id in camera_list:
        # check if already processed
        pkl_path = os.path.join(save_dir, f"{cam_id}.pkl")
        if os.path.exists(pkl_path):
            collector_all[cam_id] = json.load(open(pkl_path))
            logger.info(f"Results for camera {cam_id} already exists at {pkl_path}")
            continue

        if verbose:
            per_cam_vis_dir = os.path.join(per_human_img_dir, f"{cam_id}")
            if not os.path.exists(per_cam_vis_dir):
                os.makedirs(per_cam_vis_dir)
        
        collector = {}
        frames = []

        for frame_id, frame_info in enumerate(annotation_frames):
            frame_id = int(frame_id)
            frame_ts = frame_info['timestamp']
            objects = frame_info['objects']
            logger.info(f"Processing frame {frame_id} : {frame_ts} for camera {cam_id} with {len(objects)} objects")

            # define empty instance collector for each frame
            frame_collector = {
                "gt_bbox": [],
                "extra_data": {
                    "gt_track_id": [],
                    "gt_class": [],
                },
            }

            # load intrinsic
            intrinsic = intrinsics[camera_list.index(cam_id)]
            extrinsic = extrinsics[camera_list.index(cam_id)]

            ego_to_world = ego_frame_poses[frame_id]
            cam_to_world = ego_to_world @ extrinsic
            world_to_cam = np.linalg.inv(cam_to_world)

            img_width = calibrations['image_info'][cam_id]['image_widths']
            img_height = calibrations['image_info'][cam_id]['image_heights']
            # /workspace/wangyl11@xiaopeng.com/download/20251017_1641_raw/model1/images/cam0/1757837326321984534.png
            origin_image_path = os.path.join(scene_dir, f"images/cam{cam_id}/{frame_ts}.png") 
            origin_image = cv2.imread(origin_image_path)
            plotted_image = origin_image.copy()
            
            if len(objects) > 0:
                for obj in objects:
                    if obj['type'] != 'pedestrian':
                        continue
                    
                    instance_id = obj['gid']
                    obj_trans = np.array(obj["translation"])
                    obj_quat = np.array(obj["rotation"])
                    obj_rot = quaternion_matrix(obj_quat)[:3, :3]
                    obj_size = np.array(obj["size"])
                    obj_to_world = np.eye(4)
                    obj_to_world[:3, :3] = obj_rot
                    obj_to_world[:3, 3] = obj_trans

                    # obj_rotation = R.from_matrix(obj_to_world[:3, :3]).as_quat()
                    # obj_quat = [obj_rotation[3], obj_rotation[0], obj_rotation[1], obj_rotation[2]]
                    world_corners = get_box_corners(obj_trans, obj_size, obj_quat)
                    # print shape

                    corners_cam = (world_to_cam[:3, :3] @ world_corners.T).T + world_to_cam[:3, 3]
                    cam_points, depth = project_camera_points_to_image(corners_cam, intrinsic)

                    x_min, y_min = np.min(cam_points, axis=0)
                    x_max, y_max = np.max(cam_points, axis=0)

                    # clip left and right with this ratio
                    if narrow_width_ratio > 0.0:
                        length = x_max - x_min
                        x_min += length * narrow_width_ratio
                        x_max -= length * narrow_width_ratio

                    # clip the box to the image
                    original_area = (x_max - x_min) * (y_max - y_min)
                    x_min, x_max = np.clip(x_min, 0, img_width), np.clip(x_max, 0, img_width)
                    y_min, y_max = np.clip(y_min, 0, img_height), np.clip(y_max, 0, img_height)
                    new_area = (x_max - x_min) * (y_max - y_min)

                    # filter out boxes that are too small or too large
                    behind = depth.max() < 0
                    too_small = new_area < img_width * img_height * (0.03) ** 2
                    too_large = new_area > img_width * img_height / 1.1
                    too_far = np.linalg.norm(obj_to_world[:3, 3] - cam_to_world[:3, 3]) > 40
                    clip_large = new_area / original_area < 1 / 3
                    if too_small or too_large or clip_large or behind or too_far:
                        continue

                    # gt box on image
                    gt_box = [x_min, y_min, x_max - x_min, y_max - y_min]

                    # save the projected box to the collector
                    frame_collector["gt_bbox"].append(gt_box)
                    frame_collector["extra_data"]["gt_track_id"].append(instance_id)
                    frame_collector["extra_data"]["gt_class"].append([0])

                    if verbose:
                        # visualize the projected boxes of ONE instance
                        raw_image = cv2.rectangle(
                            origin_image.copy(),
                            (int(x_min), int(y_min)),
                            (int(x_max), int(y_max)),
                            (0, 255, 0),
                            2,
                        )
                        raw_image_path = os.path.join(per_cam_vis_dir, f"{frame_id}_{instance_id}.jpg")
                        cv2.imwrite(raw_image_path, raw_image)

                        # add this instance to the image
                        plotted_image = cv2.rectangle(
                            plotted_image,
                            (int(x_min), int(y_min)),
                            (int(x_max), int(y_max)),
                            (0, 255, 0),
                            2,
                        )

                if verbose:
                    frames.append(plotted_image)
            else:
                # if no instance in this frame, just save the original image
                if verbose:
                    frames.append(origin_image)

            collector[frame_id] = frame_collector

        if verbose:
            height, width = frames[0].shape[:2]
            output_path = os.path.join(video_dir, f"cam_{cam_id}.mp4")
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
            for frame in tqdm(frames, desc=f"Writing video for camera {cam_id}"):
                out.write(frame)
            out.release()

        if save_temp:
            # save collector to pkl
            json.dump(collector, open(pkl_path, "w"))

        collector_all[cam_id] = collector

    if not collector_all:
        logger.warning(f"No valid results found in {save_dir}")
        return None

    return collector_all

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

    ######## compute ego poses from transform.json
    transform_path = os.path.join(datadir, 'transform.json')
    with open(transform_path, "r") as f:
        meta = json.load(f)

    image_info = {}
    time_cam_dict = {}
    for frame in meta["frames"]:
        timestamp = frame["timestamp"]
        cam_name = frame["camera"]
        cam_name_code = int(cam_name.replace("cam", ""))
        if timestamp not in time_cam_dict:
            time_cam_dict[timestamp] = {}
        if cam_name_code not in image_info:
            image_info[cam_name_code] = {}
            image_info[cam_name_code]["image_widths"] = frame["w"]
            image_info[cam_name_code]["image_heights"] = frame["h"]

        time_cam_dict[timestamp][cam_name_code] = frame["transform_matrix"]

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
            key_name_code = int(key_name.replace("cam", ""))
            rig_to_cam[key_name_code] = np.array(
                calibrations[cname]['extrinsic']['transformation_matrix']
            ).reshape(4, 4)
            cam_to_rig[key_name_code] = np.linalg.inv(rig_to_cam[key_name_code])
            if key_name_code in cam_to_rig_optimized_mean:
                diff_to_optimized = np.linalg.norm(cam_to_rig_optimized_mean[key_name_code] - cam_to_rig[key_name_code])
                print(f"[INFO] cam_to_rig diff to cam_to_rig_optimized for {key_name}: {diff_to_optimized}")
                print(f"[INFO] cam_to_rig_optimized_std for {key_name_code}: \n{cam_to_rig_optimized_std[key_name_code]}")

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
            cam_intrinsic[key_name_code] = intrinsic

    intrinsics = []
    extrinsics = []
    for cname in cam_names:
        # key_name = cname.replace("new", "")
        intrinsics.append(cam_intrinsic[cname])
        extrinsics.append(cam_to_rig_optimized_mean[cname])

    return calibrations, intrinsics, extrinsics, ego_frame_poses, ego_cam_poses, anchor_pose

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

if __name__ == "__main__":
    scene_dir = "/workspace/wangyl11@xiaopeng.com/download/20251017_1641_raw/model1"
    project_human_boxes(
        scene_dir,
        camera_list=CAMERA_LIST,
        save_temp=True,
        verbose=True,
        narrow_width_ratio=0.2,
        fps=12,
    )