from pathlib import Path
from scipy.spatial.transform import Rotation as R
from collections import defaultdict
import numpy as np
import os
import open3d as o3d
import json
import cv2

from utils.misc import get_o3d_box
from utils.misc import parser_autolabel_json, get_global_object_moving_status
from utils.calib_utils import get_intrisinc_from_transform, get_calibration
from utils.calib_utils import load_localpose_and_anchorpose_from_json
from utils.calib_utils import load_localpose_lidar_aligned
from utils.file_utils import timer, read_pcd


class LidarProcessor:
    def __init__(self, cfg):
        self.cfg = cfg        
        self.clip_path = Path(cfg.clip_path)
        
        self.calibrations = get_calibration(self.clip_path / "calib.json", self.cfg.target_lidar)
        self.transform_json = self.get_transform_json()
        self.sort_transforms_by_time()

        self.autolabel_json = parser_autolabel_json(
            self.clip_path / "autolabel_json", select_box_info=["detection_box_info", "autolabel_box_info"]
        )
        self.annotation_autolabel_box = json.load(open(self.clip_path / "annotation_for_train.json", "r"))
        self.images_roi = {}
        self._load_images_roi()

        self.obj_xyzs = {}
        self.obj_rgbs = {}
        self.background_pcds = {}
        self.point_cloud_background = None
        self.ground_mask_idx = None

    def process_lidar(self):
        self.read_all_pcds()
        self.concat_background_pcds()
        self.colorrize_background_pcds()
        self.save_background_pcds()
        self.colorrize_object_pcds()
        self.save_object_pcds()

    def process_object_lidar(self):
        self.read_all_pcds(filter_static_obj=False)
        self.colorrize_object_pcds()
        self.save_object_pcds()

    def get_transform_json(self):
        transform_path = self.clip_path / "transform.json"
        return json.load(open(transform_path, "r"))

    def get_camera2anchor_from_transform_json(self, transform_frame):
        return np.array(transform_frame["transform_matrix"])

    def sort_transforms_by_time(self):
        self.sorted_transforms = {}
        for transform in self.transform_json["frames"]:
            timestamp = transform["timestamp"]
            if timestamp not in self.sorted_transforms:
                self.sorted_transforms[timestamp] = []
            self.sorted_transforms[timestamp].append(transform)

    def _load_images_roi(self):
        for cam_name in self.transform_json['sensor_params']['camera_order']:
            roi_file_path = self.clip_path / f"misc/roi_{cam_name}.json"
            self.images_roi[cam_name] = json.load(open(roi_file_path, "r"))

    def _get_objects_one_frame(self, autolabel_one_frame, moving_gids, rig2anchor):
        obbs = []
        for object in autolabel_one_frame["objects"]:
            gid = object["gid"]
            if moving_gids.get(gid, False):  # only keep moving objects
                q = object["rotation"]
                rotation_matrix = R.from_quat([q[1], q[2], q[3], q[0]])
                trans_o2rig = object["translation"]
                rot_o2rig = rotation_matrix.as_matrix()
                o2rig = np.eye(4)
                o2rig[:3, :3] = rot_o2rig
                o2rig[:3, 3] = trans_o2rig
                o2anchor = rig2anchor @ o2rig
                rot_o2anchor = R.from_matrix(o2anchor[:3,:3]).as_quat()
                rot_o2anchor = [rot_o2anchor[3], rot_o2anchor[0], rot_o2anchor[1], rot_o2anchor[2]]
                trans_o2anchor = o2anchor[:3, 3]
                obj = {
                    'gid': gid,
                    'translation': trans_o2anchor,
                    'size': object["size"],
                    'rotation': o2anchor[:3, :3],
                }
        
                lwh = object["size"]
                obj['obb'] = get_o3d_box(rot_o2anchor, trans_o2anchor, lwh, scales=[1.5, 1.5, 1.5])
                obbs.append(obj)
        return obbs

    def _split_pcd(self, pcds, obbs, ego_obb, timestamp):
        for obj in obbs:
            obb = obj['obb']

            inliers_indices = obb.get_point_indices_within_bounding_box(pcds.points)
            inliers_pcd = pcds.select_by_index(inliers_indices, invert=False) # select inside points = cropped
            trans_o2anchor = obj['translation']
            rot_o2anchor = obj['rotation']
            o2w = np.eye(4)
            o2w[:3, :3] = rot_o2anchor
            o2w[:3, 3] = trans_o2anchor
            w2o = np.linalg.inv(o2w)
            pts = np.array(inliers_pcd.points)
            pts = np.hstack([pts , np.ones((pts.shape[0], 1))])
            pt_obj = w2o.astype("float32") @ pts.astype("float32").T
            division_row = pt_obj[3, :]
            pt_obj = pt_obj[:3,:] / division_row

            obj_gid = int(float(obj['gid']))
            if obj_gid not in self.obj_xyzs:
                self.obj_xyzs[obj_gid] = pt_obj.T
            else:
                self.obj_xyzs[obj_gid] = np.concatenate((self.obj_xyzs[obj_gid], pt_obj.T), axis=0)
            outliers_pcd = pcds.select_by_index(inliers_indices, invert=True) # select outside points
            pcds = outliers_pcd
        
        inliers_indices = ego_obb.get_point_indices_within_bounding_box(pcds.points)
        outliers_pcd = pcds.select_by_index(inliers_indices, invert=True) # select outside points
        return outliers_pcd
    
    def read_all_pcds(self, filter_static_obj=True):
        lidar_frames = self.transform_json["lidar_frames"]
        if filter_static_obj:
            anno_frames = self.annotation_autolabel_box["frames"]
            annotation_dict = {i['timestamp']: i for i in anno_frames}
            moving_gids = get_global_object_moving_status(annotation_dict)
        else:
            moving_gids = defaultdict(lambda: True)

        localpose_anchored, _ = load_localpose_and_anchorpose_from_json(self.clip_path)
        localpose_lidar_aligned = load_localpose_lidar_aligned(self.clip_path)

        for idx, lidar_frame in enumerate(lidar_frames):
            timestamp = str(lidar_frame["timestamp"])
            rig2anchor = localpose_anchored[timestamp]
            rig2anchor_lidar_aligned = localpose_lidar_aligned[timestamp]
            lidar2rig = self.calibrations._lidar2rig
            lidar2anchor = rig2anchor @ lidar2rig

            autolabel_found_dict = self.autolabel_json.get(str(lidar_frame["timestamp"]), None)

            if autolabel_found_dict is not None:
                obbs = self._get_objects_one_frame(autolabel_found_dict, moving_gids, rig2anchor_lidar_aligned)
            else:
                print(f"[INFO] Skipping {idx+1}/{len(lidar_frames)}, no objects found.")
                continue
                        
            ego_rotation = R.from_matrix(lidar2anchor[:3, :3]).as_quat()
            ego_rotation = [ego_rotation[3], ego_rotation[0], ego_rotation[1], ego_rotation[2]]
            ego_position = lidar2anchor[:3, 3]
            ego_lwh = [4.59979, 2.5, 2.5]
            ego_obb = get_o3d_box(ego_rotation, ego_position, ego_lwh, scales=[2, 2, 2])

            file_path = str(self.clip_path / "pcd" / Path(lidar_frame["file_path"]).name)
            pcds = read_pcd(file_path, rig2anchor_lidar_aligned, lidar2rig, self.cfg.processor.lidar_points_valid_range)
            pcds = self._split_pcd(pcds, obbs, ego_obb, timestamp)
            self.background_pcds[str(timestamp)] = pcds
            
            print(f"[INFO] Processed {idx+1}/{len(lidar_frames)}, found objects: {len(obbs)}, "\
                  f"timestamp {timestamp}, npcd: {len(self.background_pcds[str(timestamp)].points)}")

    def concat_background_pcds(self):
        background_xyzs = None
        background_time = None
        print(f"[INFO] Start to concat point cloud......")
        count2timestamp = {}
        count = 0
        for timestamp, pcds_origin in self.background_pcds.items():
            points_np = np.array(pcds_origin.points)
            points_time = np.ones((points_np.shape[0], 3)) * count / 10
            if background_xyzs is None:
                background_xyzs = points_np
                background_time = points_time
            else:
                background_xyzs = np.concatenate((background_xyzs, points_np), axis=0)
                background_time = np.concatenate((background_time, points_time), axis=0)
            count2timestamp[count] = timestamp
            count += 1

        point_cloud_background = o3d.geometry.PointCloud()
        point_cloud_background.points = o3d.utility.Vector3dVector(background_xyzs.astype(np.float32))
        point_cloud_background.colors = o3d.utility.Vector3dVector(background_time.astype(np.float32))
        downsample_voxel_size = min(self.cfg.processor.lidar_voxel_size_ground_init, self.cfg.processor.lidar_voxel_size_init)
        point_cloud_background = point_cloud_background.voxel_down_sample(downsample_voxel_size)
        self.point_cloud_background = point_cloud_background
        print(f"[INFO] Background points downsampled from {len(background_xyzs)} to {len(point_cloud_background.points)}.")
        ### save points timestamp to misc/points_time.npy and misc/points2timestamp.json
        new_background_time = np.round(np.array(point_cloud_background.colors)[:, 0] * 10).astype(int)
        np.save(self.clip_path / "misc/points_timestamp.npy", new_background_time)
        json.dump(count2timestamp, open(os.path.join(self.clip_path, "misc/points2timestamp.json"), 'w+'), indent=4)
        
    def colorrize_background_pcds(self):
        cam_order = ['cam2', 'cam0', 'cam3', 'cam4', 'cam5', 'cam6', 'cam7']
        if self.cfg.projection.proj_lidar_to_img:
            cam_order = self.cfg.projection.source_cam
        # use reverse sorted frames in time for each camera since the last frame is the closest to the far-away scene,
        # and this makes the filter out process automatically based on the distance to the camera in most cases
        # cam_transform = {i: [j for j in self.transform_json['frames'][::-1] if j['camera'] == i] for i in cam_order}
        transform_json_sorted = sorted(self.transform_json['frames'], key=lambda x: x['timestamp'], reverse=True)
        cam_transform = {i: [j for j in transform_json_sorted if j['camera'] == i] for i in cam_order}
        sorted_transforms = [cam_transform[i] for i in cam_order]
        
        points_np = np.array(self.point_cloud_background.points, dtype=np.float32)
        points_np = np.hstack([points_np , np.ones((points_np.shape[0], 1), dtype=np.float32)])
        points_timestamp = np.load(os.path.join(self.clip_path, "misc/points_timestamp.npy"))
        count2timestamp = json.load(open(os.path.join(self.clip_path, "misc/points2timestamp.json"), "r"))
        timestamp2count = dict()
        for k, v in count2timestamp.items():
            timestamp2count[v] = k
        rgb_result = np.zeros((points_np.shape[0], 3), dtype=np.uint8)
        rgb_mask_idx = np.array([i for i in range(points_np.shape[0])])

        if self.cfg.projection.proj_lidar_to_img:
            PROJ_AREA_CLASSES = self.cfg.projection.proj_area

        for i, transforms in enumerate(sorted_transforms):
            cam_name = cam_order[i]
            for idx, frame in enumerate(transforms):
                print(f'[INFO] Colorrize with cam {cam_name} frame: {idx}/{len(transforms)}. ' \
                      f'Rest points: {points_np.shape[0]}/{rgb_result.shape[0]}')
                if points_np.shape[0] < 10:
                    break

                camera2anchor = self.get_camera2anchor_from_transform_json(frame)
                anchor2camera = np.linalg.inv(camera2anchor).astype(np.float32)

                intrinsic_matrix, _1, _2 = get_intrisinc_from_transform(frame)
                # x, y = self.images_roi[cam_name]['x'], self.images_roi[cam_name]['y']
                # h, w = self.images_roi[cam_name]['h'], self.images_roi[cam_name]['w']
                rgb = cv2.imread(str(self.clip_path / frame["file_path"]))
                mask_img = cv2.imread(
                    str(self.clip_path / frame["file_path"].replace("images", "masks")), cv2.IMREAD_GRAYSCALE
                ).astype(bool)
                if self.cfg.projection.proj_lidar_to_img:
                    seg_path = str(self.clip_path / frame["file_path"].replace("images", "segs"))
                    if os.path.exists(seg_path):
                        seg_img = cv2.imread(seg_path, cv2.IMREAD_GRAYSCALE)
                        seg_area = np.isin(seg_img, PROJ_AREA_CLASSES)
                    else:
                        print(f"[WARNING] Segmentation file not found: {seg_path}")
                        continue

                x, y = 0, 0
                h, w = mask_img.shape
                camera_coordinates = anchor2camera @ points_np.T
                points_front_camera = camera_coordinates[2, :] > 0
                # only choose points corresponding to the current frame
                cur_frame_idx = int(timestamp2count[str(frame['timestamp'])])
                points_front_camera = points_front_camera & (points_timestamp == cur_frame_idx)
                filtered_points = points_np[points_front_camera]
                uv_homogeneous = intrinsic_matrix.astype(np.float32) @ camera_coordinates[:, points_front_camera]
                division_row = uv_homogeneous[2, :]
                cam_pcl = (uv_homogeneous[:2,:] / division_row).astype(int)
                mask = (cam_pcl[0, :] >= x) * (cam_pcl[0, :] < x+w) * \
                    (cam_pcl[1, :] >= y) * (cam_pcl[1, :] < y+h)
                pixels = cam_pcl[:, mask]
                if not self.cfg.projection.proj_lidar_to_img:
                    mask_point = mask_img[pixels[1, :], pixels[0, :]]
                else:
                    mask_point = mask_img[pixels[1, :], pixels[0, :]] & \
                        seg_area[pixels[1, :], pixels[0, :]]
                rgb_point = rgb[pixels[1, :], pixels[0, :]][mask_point]
                rgb_point[:, [0, 2]] = rgb_point[:, [2, 0]]  # BGR to RGB
                
                rgb_mask_idx_found = rgb_mask_idx[points_front_camera][mask][mask_point]
                rgb_result[rgb_mask_idx_found] = rgb_point

                # remove masked points and continue iteration for rest points
                points_front_camera[points_front_camera] &= mask
                points_front_camera[points_front_camera] &= mask_point
                points_np = points_np[~points_front_camera]
                points_timestamp = points_timestamp[~points_front_camera]
                rgb_mask_idx = rgb_mask_idx[~points_front_camera]

        if not self.cfg.projection.proj_lidar_to_img:
            self.point_cloud_background.colors = o3d.utility.Vector3dVector(rgb_result.astype(np.float32)/255.0)
        else:
            # only keep colorized pcds
            colored_mask = np.any(rgb_result != 0, axis=1)
            colored_points = np.array(self.point_cloud_background.points)[colored_mask]
            colored_rgb = rgb_result[colored_mask]

            self.point_cloud_background.points = o3d.utility.Vector3dVector(colored_points)
            self.point_cloud_background.colors = o3d.utility.Vector3dVector(colored_rgb.astype(np.float32) / 255.0)

    def colorrize_object_pcds(self):
        print("[WARNING] TODO: colorrize_object_pcds")

    def save_background_pcds(self):
        os.makedirs(str(self.clip_path / "misc"), exist_ok=True)
        if not self.cfg.projection.proj_lidar_to_img:
            o3d.io.write_point_cloud(str(self.clip_path / "misc/background.ply"), self.point_cloud_background)
        else:
            o3d.io.write_point_cloud(str(self.clip_path / "misc/background_filtered.ply"), self.point_cloud_background)
        np.save(self.clip_path / "misc/ground_mask_origin.npy", self.ground_mask_idx)

    def save_object_pcds(self):
        save_path = self.clip_path / "aggregate_lidar/dynamic_objects/"
        os.makedirs(str(save_path), exist_ok=True)

        for gid, xyz in self.obj_xyzs.items():
            if len(xyz) < 100:
                continue

            if gid in self.obj_rgbs:
                rgb = self.obj_rgbs[gid]
            else:
                rgb = np.random.rand(xyz.shape[0], 3)
            
            point_cloud = o3d.geometry.PointCloud()
            point_cloud.points = o3d.utility.Vector3dVector(xyz[:, :3])
            point_cloud.colors = o3d.utility.Vector3dVector(rgb)
            if len(xyz) > self.cfg.processor.object_downsample_threshold:
                point_cloud = point_cloud.voxel_down_sample(self.cfg.processor.object_voxel_size)
            print(f"[INFO] Saving object {gid} with {len(point_cloud.points)} points (original {len(xyz)} points).")
            o3d.io.write_point_cloud(str(save_path / f"{gid}.ply"), point_cloud)

    def process_lidar_projection(self):
        self.read_all_pcds()
        self.concat_background_pcds()
        self.colorrize_background_pcds()
        self.save_background_pcds()
        self.proj_lidar_to_img()

    def proj_lidar_to_img(self):
        cam_order = self.cfg.projection.target_cam
        transform_json_sorted = sorted(self.transform_json['frames'], key=lambda x: x['timestamp'], reverse=True)
        cam_transform = {i: [j for j in transform_json_sorted if j['camera'] == i] for i in cam_order}
        sorted_transforms = [cam_transform[i] for i in cam_order]

        self.point_cloud_background = o3d.io.read_point_cloud(str(self.clip_path / "misc/background_filtered.ply"))
        colored_points = np.array(self.point_cloud_background.points)
        colored_rgb = np.array(self.point_cloud_background.colors) * 255.0
        colored_points_np = np.hstack([colored_points, np.ones((colored_points.shape[0], 1), dtype=np.float32)])

        for i, transforms in enumerate(sorted_transforms):
            target_cam = cam_order[i]
            for idx, frame in enumerate(transforms):
                camera2anchor = self.get_camera2anchor_from_transform_json(frame)
                anchor2camera = np.linalg.inv(camera2anchor).astype(np.float32)
                intrinsic_matrix, _, _ = get_intrisinc_from_transform(frame)

                target_img_path = str(self.clip_path / frame["file_path"])
                target_img = cv2.imread(target_img_path)
                if target_img is None:
                    continue

                camera_coordinates = anchor2camera @ colored_points_np.T
                points_front_camera = camera_coordinates[2, :] > 0

                uv_homogeneous = intrinsic_matrix.astype(np.float32) @ camera_coordinates[:, points_front_camera]
                division_row = uv_homogeneous[2, :]
                cam_pcl = (uv_homogeneous[:2,:] / division_row).astype(int)

                h, w = target_img.shape[:2]
                mask = (cam_pcl[0, :] >= 0) & (cam_pcl[0, :] < w) & \
                    (cam_pcl[1, :] >= 0) & (cam_pcl[1, :] < h)

                pixels = cam_pcl[:, mask]
                colors_np = colored_rgb
                colors = colors_np[points_front_camera][mask]

                for (x, y), color in zip(pixels.T, colors):
                    cv2.circle(target_img, (x, y), radius=2,
                            color=color[[2,1,0]].astype(int).tolist(),  # RGB to BGR
                            thickness=-1)

                source_cam_str = "_".join(self.cfg.projection.source_cam)
                output_str = source_cam_str + "_to_" + target_cam
                output_dir = os.path.join(self.clip_path, "projection", output_str)
                os.makedirs(output_dir, exist_ok=True)
                output_path = os.path.join(output_dir,
                                        f"{os.path.basename(target_img_path).split('.')[0]}_{output_str}.png")
                cv2.imwrite(output_path, target_img)

                print(f"[INFO] Saved projected image to {output_path}")


if __name__ == "__main__":
    from settings.config import make_default_settings, make_case_specific_settings
    clip_ids = {
        # "c-66260c6e-65d2-3f8f-a2a5-029b885a87b3": "fm",
        # "c-c244e2f3-2464-3c67-acbe-045a7924f5a4": "fm",
        # "c-078f16e4-274f-37a2-97f5-9afe6aa542ed": "fm",
        # "c-10ce0565-ffaf-378d-bd9c-845893333d1d": "fm",
        # "c-b0661312-a728-3659-90fa-76088abf192e": "fm",
        ############## 
        "c-6a9b6fd7-d2b9-3155-a242-8c2331f8376a": "fm_new_pose",
    }
    for clip, folder in clip_ids.items():
        cfg = make_default_settings()
        cfg.ips_deploy = False
        cfg.dataset_name = "selected_clips_m1"
        cfg.root = f"/workspace/yangxh7@xiaopeng.com/datasets/xpeng/{folder}"
        cfg.clip_id = clip
        cfg = make_case_specific_settings(cfg)

        # lidar projection
        cfg.projection.proj_lidar_to_img = True
        cfg.projection.proj_area = [24] # proj road marker
        cfg.projection.source_cam = ['cam2'] # source lidar
        cfg.projection.target_cam = ['cam2'] # target image

        lidar_processor = LidarProcessor(cfg)
        # lidar_processor.process_lidar()
        lidar_processor.process_lidar_projection()