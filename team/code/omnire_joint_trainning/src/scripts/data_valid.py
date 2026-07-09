import sys
import os
sys.path.append(os.getcwd())
import json
import argparse
import numpy as np
import cv2
import open3d as o3d
from glob import glob
from tqdm import tqdm
from pypcd import pypcd
from matplotlib import cm
from scipy.spatial.transform import Rotation as R
# from lib.utils.img_utils import visualize_depth_numpy
# from lib.config import cfg, args
from utils.projection import Projection
from utils.xp_data_reader import XP_data_reader

"""
generate depth image for pcd, check c2w(transform.json, transform_matrix)
"""
def generate_xpeng_depth(data_reader, projection, all_camera_position, include_list=[]):
    print(data_reader.data_ids)
    for f in list(data_reader.data_ids):
        if f.startswith("."):
            continue
        if f.endswith(".zip"):
            continue
        if f.endswith("failed"):
            continue
        if f not in include_list:
            continue
        print(f)
        bkgd_pcd_path = os.path.join(data_reader.data_root, f, "input_ply", 'points3D_bkgd.ply')
        bkgd_pcd = o3d.io.read_point_cloud(bkgd_pcd_path)
        # Print some information about the point cloud
        print(f"Point cloud has {len(bkgd_pcd.points)} points.")
        # Access points
        points = bkgd_pcd.points
        points_np = np.asarray(points)
        print(points_np.shape)
        images_path = os.path.join(data_reader.data_root, f, "images")
        calib_path = os.path.join(data_reader.data_root, f, "transform.json")
        calib_data = data_reader.read_json(calib_path)
        points = points_np.transpose((1, 0))
        frame_pose_dict = dict()
        for frame in calib_data["frames"]:
            file_key = frame["file_path"]
            if file_key not in frame_pose_dict:
                frame_pose_dict.update({file_key: frame["transform_matrix"]})
        for cam in all_camera_position:
            print(cam)
            in_params_cam = calib_data["sensor_params"][cam]["camera_intrinsic"]
            res_w = calib_data["sensor_params"][cam]["width"]
            res_h = calib_data["sensor_params"][cam]["height"]
            print(f"w: {res_w}, h: {res_h}")
            dist_params = calib_data["sensor_params"][cam]["camera_D"]
            images_path_cam = os.path.join(images_path, cam)
            for img_name in os.listdir(images_path_cam):
                lidar_depth_out_path = os.path.join(data_reader.data_root, f, "lidar_depth")
                os.makedirs(lidar_depth_out_path, exist_ok=True)
                save_path = os.path.join(lidar_depth_out_path, f"{img_name[:-4]}_{cam}.npy")
                query = os.path.join("images", cam, img_name)
                frame_pose = frame_pose_dict[str(query)]
                # lidar to cam, frame pose is cam to first frame
                lidar_points_cam = projection.lidar_points_to_camera(points, np.linalg.inv(frame_pose))
                lidar_points_image = projection.points_camera_to_image(lidar_points_cam, in_params_cam)
                lidar_points_image = lidar_points_image.transpose((1, 0))
                lidar_points_cam = lidar_points_cam.transpose((1, 0))
                lidar_points_image = lidar_points_image.round().astype(np.int32)
                mask = ((lidar_points_image[:, 0] > 0) & (lidar_points_image[:, 0] < res_w) & 
                        (lidar_points_image[:, 1] > 0) & (lidar_points_image[:, 1] < res_h) & (lidar_points_cam[:, 2] > 0.0))
                lidar_points_image = lidar_points_image[mask]
                lidar_points_cam = lidar_points_cam[mask]
                points_depth = lidar_points_cam[:, 2]
                depth_image = (np.ones((res_h, res_w)) * np.finfo(np.float32).max)
                h = lidar_points_image[:, 1].astype(int)
                w = lidar_points_image[:, 0].astype(int)
                np.minimum.at(depth_image, (h, w), points_depth)
                # for idx in range(points_depth.shape[0]):
                #     w = lidar_points_image[idx, 0]
                #     h = lidar_points_image[idx, 1]
                #     d = points_depth[idx]
                #     if d < depth_image[h, w]:
                #         depth_image[h, w] = d
                image_path = os.path.join(images_path_cam, img_name)
                print(image_path)
                image = cv2.imread(image_path)
                point_size = 0
                if cam == "cam0":
                    point_size = 1
                elif cam == "cam2":
                    point_size = 1
                else:
                    point_size = 0
                point_size = 0 if cam != "cam0" else 1
                # projection.draw_lidar_points(image, lidar_points_image, colors, point_size)
                projection.draw_depth_image(image, depth_image, point_size=point_size)
                # lidar_max_distance = 100
                depth_image_mask = (depth_image >= 0) & (depth_image <= 100)                
                out_path = os.path.join(data_reader.data_root, f, "ex_valid")
                os.makedirs(out_path, exist_ok=True)
                os.makedirs(os.path.join(out_path, cam), exist_ok=True)
                cv2.imwrite(os.path.join(out_path, cam, f"{img_name[:-4]}.png"), image)

                depth_file = dict()
                depth_file['mask'] = depth_image_mask
                depth_file['value'] = depth_image[depth_image_mask]
                
                np.save(save_path, depth_file)

"""
single pcd projection, check cam2ego and lidar2ego
"""
def generate_xpeng_single_lidar_frame_projection(data_reader, projection, all_camera_position, include_list=[]):
    print(data_reader.data_ids)
    for f in list(data_reader.data_ids):
        if f.startswith("."):
            continue
        if f.endswith(".zip"):
            continue
        if f.endswith("failed"):
            continue
        if f not in include_list:
            continue
        print(f)       
        single_pcd_path = os.path.join(data_reader.data_root, f, "pcd")
        images_path = os.path.join(data_reader.data_root, f, "images")
        transform_json = json.load(open(os.path.join(data_reader.data_root, f, "transform.json")))
        ex_lidar_to_ego = transform_json["sensor_params"]["lidar1"]["extrinsic"]
        for pcd_path in os.listdir(single_pcd_path):
            print(pcd_path)
            pc = pypcd.PointCloud.from_path(os.path.join(single_pcd_path, pcd_path))
            # Extract x, y, z coordinates
            x = pc.pc_data['x']
            y = pc.pc_data['y']
            z = pc.pc_data['z']
            intensity = pc.pc_data['intensity']
            # intensity = o3d.t.io.read_point_cloud(pcd_files[index]).point["intensity"].numpy()  # 假设 intensity 存储在颜色的第一个通道
            intensity_normalized = (intensity - intensity.min()) / (intensity.max() - intensity.min() + 1e-8)
            # 使用 matplotlib 的 colormap (例如 'viridis' 或 'jet')
            colormap = cm.get_cmap('jet')  # 'jet' 映射为蓝-绿-红梯度
            # N, 3(BGR)
            colors = colormap(intensity_normalized)[:, :3]  # 提取 RGB 值 (忽略 alpha 通道)
            colors = (colors * 255)
            # Example: Create a (N, 3) numpy array of point positions
            points = np.column_stack((x, y, z))
            points = points.transpose((1, 0))
            for cam in all_camera_position:
                print(cam)
                # cam to ego
                ex_params_cam = transform_json["sensor_params"][cam]["extrinsic"]
                in_params_cam = transform_json["sensor_params"][cam]["camera_intrinsic"]
                res_w = transform_json["sensor_params"][cam]["width"]
                res_h = transform_json["sensor_params"][cam]["height"]
                dist_params = transform_json["sensor_params"][cam]["camera_D"]
                images_path_cam = os.path.join(images_path, cam)
                img_name = pcd_path[:-4] + ".png"
                undistorted_image = cv2.imread(str(os.path.join(images_path_cam, img_name)))
                # lidar to ego
                lidar_points_cam = projection.lidar_points_to_camera(points, np.linalg.inv(ex_params_cam) @ ex_lidar_to_ego)
                # lidar_points_dist = add_distortion_to_points(lidar_points_cam, dist_params, in_mat)
                # ego to camera 
                lidar_points_image = projection.points_camera_to_image(lidar_points_cam, in_params_cam)
                lidar_points_image = lidar_points_image.transpose((1, 0))
                point_size = 0
                if cam == "cam0":
                    point_size = 1
                elif cam == "cam2":
                    point_size = 1
                else:
                    point_size = 0
                point_size = 0 if cam != "cam0" else 1
                projection.draw_lidar_points(undistorted_image, lidar_points_image, colors)
                save_path = os.path.join(data_reader.data_root, f, "single_pcd_projection")
                os.makedirs(save_path, exist_ok=True)
                save_path = os.path.join(data_reader.data_root, f, "single_pcd_projection", cam)
                os.makedirs(save_path, exist_ok=True)
                cv2.imwrite(os.path.join(save_path, f"{img_name}"), undistorted_image)

"""
single lidar frame to world, check ego2world and lidar2ego
"""
def generate_xpeng_single_lidar_frame_to_world(data_reader, projection, all_camera_position, diff=0, include_list=[]):
    print(data_reader.data_ids)
    for f in list(data_reader.data_ids):
        if f.startswith("."):
            continue
        if f.endswith(".zip"):
            continue
        if f.endswith("failed"):
            continue
        if f not in include_list:
            continue
        print(f)       
        single_pcd_path = os.path.join(data_reader.data_root, f, "pcd")
        images_path = os.path.join(data_reader.data_root, f, "images")
        transform_json = json.load(open(os.path.join(data_reader.data_root, f, "transform.json")))
        anchorpose_json = json.load(open(os.path.join(data_reader.data_root, f, "anchorpose.json")))
        localpose_topic = json.load(open(os.path.join(data_reader.data_root, f, "LocalPoseTopic.json")))
        localpose_dict = dict()
        for elem in localpose_topic:
            if elem["time_stamp"]["nsec"] not in localpose_dict:
                t = np.array([elem["smooth_pose"]["pose"]["p"]["x"], 
                            elem["smooth_pose"]["pose"]["p"]["y"],
                            elem["smooth_pose"]["pose"]["p"]["z"]])
                q = np.array([elem["smooth_pose"]["pose"]["q"]["x"], 
                            elem["smooth_pose"]["pose"]["q"]["y"],
                            elem["smooth_pose"]["pose"]["q"]["z"],
                            elem["smooth_pose"]["pose"]["q"]["w"]])
                rotation_matrix = R.from_quat(q).as_matrix()
                rotation_matrix = np.array(rotation_matrix)
                translation_matrix = np.array([t[0],t[1],t[2]])
                ego_pose_world = np.eye(4)
                ego_pose_world[:3, :3] = rotation_matrix
                ego_pose_world[:3, 3] = translation_matrix
                # ego_pose_world = torch.from_numpy(ego_pose_world).float()
                localpose_dict[elem["time_stamp"]["nsec"]] = ego_pose_world
        ex_lidar_to_ego = transform_json["sensor_params"]["lidar1"]["extrinsic"]
        save_path = os.path.join(data_reader.data_root, f, "pcd_world")
        os.makedirs(save_path, exist_ok=True)
        for pcd_path in os.listdir(single_pcd_path):
            print(pcd_path)
            pc = pypcd.PointCloud.from_path(os.path.join(single_pcd_path, pcd_path))
            # Extract x, y, z coordinates
            x = pc.pc_data['x']
            y = pc.pc_data['y']
            z = pc.pc_data['z']
            intensity = pc.pc_data['intensity']
            # Example: Create a (N, 3) numpy array of point positions
            points = np.column_stack((x, y, z))
            points = points.transpose((1, 0))
            # lidar to first frame
            # lidar to ego, ego to world, world to first frame
            ego_pose_timestamps = [t for t in localpose_dict.keys()]
            pcd_timestamp = int(pcd_path[:-4])
            # ego_pose_frame_idx = np.abs(np.array(ego_pose_timestamps) - pcd_timestamp).argmin()
            ego_pose_frame_idx = np.argsort(np.abs(np.array(ego_pose_timestamps) - pcd_timestamp))[diff]
            ego_pose_timestamp = ego_pose_timestamps[ego_pose_frame_idx]
            ego2world = localpose_dict[ego_pose_timestamp]
            lidar2first_frame = np.linalg.inv(np.array(anchorpose_json)) @ ego2world @ ex_lidar_to_ego
            lidar_points_first_frame = projection.lidar_points_to_camera(points, lidar2first_frame)
            lidar_points_first_frame = lidar_points_first_frame.transpose((1, 0))
            new_lidar_points = np.concatenate((lidar_points_first_frame, intensity[:, np.newaxis]), axis=1)
            pcd_header = {}
            pcd_header["version"] = pc.version
            pcd_header["count"] = pc.count
            pcd_header["data"] = pc.data
            pcd_header["fields"] = pc.fields
            pcd_header["size"] = pc.size
            pcd_header["type"] = pc.type
            pcd_header["viewpoint"] = pc.viewpoint
            pcd_header["width"] = pc.width
            pcd_header["height"] = pc.height
            pcd_header["points"] = pc.points
            pcd_first_frame = pypcd.PointCloud(pcd_header, new_lidar_points)
            pcd_first_frame.save_pcd(os.path.join(save_path, pcd_path), compression='ascii')
        
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--data_dir', required=True, type=str)
    parser.add_argument('--clip_ids', nargs='+', help='List of clip id')
    args = parser.parse_args()
    all_camera_position = ["cam0", "cam2", "cam3", "cam4", "cam5", "cam6", "cam7"]
    projection = Projection()
    data_reader = XP_data_reader(data_root=args.data_dir)
    generate_xpeng_depth(data_reader, projection, all_camera_position, include_list=args.clip_ids)
    generate_xpeng_single_lidar_frame_projection(data_reader, projection, all_camera_position, include_list=args.clip_ids)
    generate_xpeng_single_lidar_frame_to_world(data_reader, projection, all_camera_position, include_list=args.clip_ids)
    