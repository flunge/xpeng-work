import sys
import os
import numpy as np
import cv2
import open3d as o3d
import json
import time
import shutil
from pathlib import Path
import torch

from utils.projection import Projection
from utils.images2video import images2video
from utils.depth_visualizer import render_depth_mosaic, export_depth_videos
from utils.calib_utils import get_calibration, load_localpose_lidar_aligned
from utils.file_utils import read_pcd, get_semantics_from_path, get_mask_from_semantics
from settings.globals import SemanticType
from utils.depth_conf_reproject import batch_reproject_dir


class DepthProcessor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.clip_path = Path(cfg.clip_path)
        self.transform_path = self.clip_path / "transform.json"
        self.transform_json = json.load(open(self.transform_path, "r"))
        self.used_cams = ["cam0", "cam2", "cam3", "cam4", "cam5", "cam6", "cam7"]

        self.xyzs = None
        self.images_roi = dict()
        self.projection = Projection()
        if self.cfg.steps_controller.source != "vision":
            self.localpose_lidar_aligned = load_localpose_lidar_aligned(self.clip_path)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._load_images_roi()

    def process_depth_vision(self):
        t1 = time.time()
        print(f"[INFO] Start depth reproject processing of clip {self.cfg.clip_id} from {self.cfg.depth_processor.depth_source}")
        if self.cfg.depth_processor.depth_source == "complete":
            self._load_input_points(voxel_size=0.)
            self.generate_depth_enhanced()
        else:
            self.generate_depth_reproject()
        t2 = time.time()
        print(f"[INFO] Finish depth reproject processing in {t2 - t1:.2f}s of clip {self.cfg.clip_id}")

    def process_depth(self):
        t1 = time.time()
        print(f"[INFO] Start depth processing of clip {self.cfg.clip_id}")
        self._load_input_points()
        self.generate_depth_complete()
        t2 = time.time()
        print(f"[INFO] Finish depth processing in {t2 - t1:.2f}s of clip {self.cfg.clip_id}")

    def process_enhanced_depth(self):
        t1 = time.time()
        print(f"[INFO] Start enhanced depth processing of clip {self.cfg.clip_id}")
        self._load_input_points()
        self.generate_depth_enhanced()
        t2 = time.time()
        print(f"[INFO] Finish enhanced depth processing in {t2 - t1:.2f}s of clip {self.cfg.clip_id}")

    def process_depth_lidar(self):
        t1 = time.time()
        print(f"[INFO] Start depth processing of clip {self.cfg.clip_id}")
        self._load_input_points()
        self.generate_depth_from_lidar()
        t2 = time.time()
        print(f"[INFO] Finish depth processing in {t2 - t1:.2f}s of clip {self.cfg.clip_id}")

    def generate_depth_reproject(self):
        base_dir = self.clip_path / "misc/mvsnet"
        depth_dir = os.path.join(base_dir, "mvsnet_depth_est")
        conf_dir = os.path.join(base_dir, "mvsnet_depth_confidence")
        cams_dir = os.path.join(base_dir, "mvsnet_cams")
        
        calib_mvsnet = os.path.join(base_dir, "mvsnet_calib.json")
        calib_mvsnet = json.load(open(calib_mvsnet, "r"))
        
        slice_to_ts_map = os.path.join(base_dir, "mvsnet_image_timestamps.json")
        slice_to_ts_map = json.load(open(slice_to_ts_map, "r"))

        out_depth_dir = os.path.join(self.clip_path, "depth")
        out_conf_dir = os.path.join(self.clip_path, "conf")

        batch_reproject_dir(
            depth_dir, conf_dir, cams_dir, self.transform_json, slice_to_ts_map,
            out_depth_dir, out_conf_dir, calib_info=calib_mvsnet, use_conf=False
        )
        
        if self.cfg.ips_deploy:
            # shutil.rmtree(depth_dir, ignore_errors=True)
            shutil.rmtree(conf_dir, ignore_errors=True)
            shutil.rmtree(cams_dir, ignore_errors=True)

    def generate_depth_complete(self):
        frame_groups = self._group_frames_by_timestamp()

        os.makedirs(self.clip_path / "depth", exist_ok=True)

        for timestamp, frames in frame_groups.items():
            camera2anchor = [np.array(frame["transform_matrix"]) for frame in frames]
            anchor2camera_torch = torch.from_numpy(np.linalg.inv(np.stack(camera2anchor))).float().to(self.device)
            in_params_torch = torch.from_numpy(np.stack([self.transform_json["sensor_params"][frame["camera"]]["camera_intrinsic"] for frame in frames])).float().to(self.device)
            lidar_points_cam = self.projection.lidar_points_to_camera(self.xyzs, anchor2camera_torch, device=self.device)
            lidar_points_image = self.projection.points_camera_to_image(lidar_points_cam, in_params_torch, device=self.device).round().int()

            for frame in frames:
                cam_name = frame["camera"]
                res_w = self.transform_json["sensor_params"][cam_name]["width"]
                res_h = self.transform_json["sensor_params"][cam_name]["height"]
                x, y = self.images_roi[cam_name]['x'], self.images_roi[cam_name]['y']
                w, h = self.images_roi[cam_name]['w'], self.images_roi[cam_name]['h']

                depth_image = torch.full((res_h, res_w), torch.finfo(torch.float32).max, device=self.device)
                cur_lidar_points_cam = lidar_points_cam[self.used_cams.index(cam_name)]
                cur_lidar_points_image = lidar_points_image[self.used_cams.index(cam_name)]

                mask = ((cur_lidar_points_image[0] > x) & (cur_lidar_points_image[0] < x + w) &
                        (cur_lidar_points_image[1]  > y) & (cur_lidar_points_image[1] < y + h) &
                        (cur_lidar_points_cam[2] > 0.0))
                valid_points = cur_lidar_points_image[:, mask]
                valid_depths = cur_lidar_points_cam[2, mask]

                indices = valid_points[1] * res_w + valid_points[0]
                indices = indices.long()
                depth_image.view(-1).scatter_reduce_(0, indices, valid_depths, "amin")
                depth_image = depth_image.cpu().numpy()

                depth_image_mask = self._depth_valid_mask(depth_image)
                depth_file_name = frame['file_path'].replace('images/', 'depth/')[:-4] + ".npy"
                self._save_depth_and_normal_to_npy(depth_file_name, depth_image, depth_image_mask)
                print(f"[INFO] Save depth image for {frame['file_path']} " \
                        f"with valid percentage {depth_image_mask.sum() / depth_image.size}")

            del anchor2camera_torch, in_params_torch
            torch.cuda.empty_cache()

    def generate_depth_enhanced(self):
        import torch.nn.functional as F
        pts_xyz = self.xyzs.to(self.device)
        # ones = torch.ones((1, pts_xyz.shape[1]), device=self.device)
        # pts_xyz = torch.cat([pts_xyz, ones], dim=0)
        valid_mask = torch.zeros_like(pts_xyz[:, 0]).bool()
        # project lidar points to the image plane
        for cam in self.used_cams:
            os.makedirs(os.path.join(self.clip_path, "depth"), exist_ok=True) 
            depth_bg_dir = os.path.join(self.clip_path, "depth", cam)
            os.makedirs(depth_bg_dir, exist_ok=True)

        frame_groups = self._group_frames_by_timestamp()

        frame_idx = 0
        for timestamp, frames in frame_groups.items():
            print(f"[INFO] processing enhanced depth for frame {frame_idx}/{len(frame_groups)}")
            for frame in frames:
                # gen ref_depthmap_s
                with torch.no_grad():
                    cam_intrinsic = torch.from_numpy(np.array(self.transform_json["sensor_params"][frame["camera"]]["camera_intrinsic"])).float().to(self.device)
                    cam_to_world = torch.from_numpy(np.array(frame["transform_matrix"])).float().to(self.device)
                cam_name = frame["camera"]
                res_w = self.transform_json["sensor_params"][cam_name]["width"]
                res_h = self.transform_json["sensor_params"][cam_name]["height"]
                
                intrinsic_4x4s = torch.nn.functional.pad(0.25 * cam_intrinsic, (0, 1, 0, 1))
                intrinsic_4x4s[2, 2] = 1.0
                intrinsic_4x4s[3, 3] = 1.0
                lidar2img_s = intrinsic_4x4s @ cam_to_world.inverse()
                projected_points_s = (lidar2img_s[:3, :3] @ pts_xyz + lidar2img_s[:3, 3:4]).T
                depth_s = projected_points_s[:, 2]
                cam_points_s = projected_points_s[:, :2] / (depth_s.unsqueeze(-1) + 1e-6)
                
                valid_mask_s = (
                    (cam_points_s[:, 0] >= 0)
                    & (cam_points_s[:, 0] <= ( round(0.25*float(res_w)) -1))
                    & (cam_points_s[:, 1] >= 0)
                    & (cam_points_s[:, 1] <= ( round(0.25*float(res_h)) -1))
                    & (depth_s > 0 )
                    & (depth_s < 100) # 100
                )  # (num_pts, )

                if not torch.any(valid_mask_s):
                    depth_bg_s_t = torch.zeros((round(0.25*float(res_h)), round(0.25*float(res_w))), device=self.device, dtype=torch.float32)
                    depth_bg_ref_t = F.interpolate(depth_bg_s_t.unsqueeze(0).unsqueeze(0), size=(res_h, res_w), mode='nearest').squeeze(0).squeeze(0)
                    depth_bg_s = depth_bg_s_t.cpu().numpy()
                    depth_bg_ref = depth_bg_ref_t.cpu().numpy()
                    depth_bg = np.zeros((res_h, res_w), dtype=np.float32)
                else:
                    depth_s_v = depth_s[valid_mask_s]
                    _cam_points_s = cam_points_s[valid_mask_s]
                    h_s = round(0.25*float(res_h))
                    w_s = round(0.25*float(res_w))
                    # scatter amin to get nearest depth per pixel
                    flat_idx_s = (_cam_points_s[:,1].long() * w_s + _cam_points_s[:,0].long())
                    inf_val = torch.finfo(torch.float32).max
                    depth_map_bg_s = torch.full((h_s*w_s,), inf_val, device=self.device, dtype=torch.float32)
                    depth_map_bg_s.scatter_reduce_(0, flat_idx_s, depth_s_v.float(), reduce='amin', include_self=True)
                    depth_map_bg_s = depth_map_bg_s.view(h_s, w_s)
                    depth_bg_ref_t = F.interpolate(depth_map_bg_s.unsqueeze(0).unsqueeze(0), size=(res_h, res_w), mode='nearest').squeeze(0).squeeze(0)
                    depth_bg_s = depth_map_bg_s.cpu().numpy()
                    depth_bg_ref = depth_bg_ref_t.cpu().numpy()
                    
                    # project points on original resolution image
                    intrinsic_4x4 = torch.nn.functional.pad(cam_intrinsic, (0, 1, 0, 1))
                    intrinsic_4x4[3, 3] = 1.0
                    lidar2img = intrinsic_4x4 @ cam_to_world.inverse()
                    projected_points = (lidar2img[:3, :3] @ pts_xyz + lidar2img[:3, 3:4]).T
                    depth = projected_points[:, 2]
                    cam_points = projected_points[:, :2] / (depth.unsqueeze(-1) + 1e-6)
                    
                    valid_mask = (
                        (cam_points[:, 0] >= 0)
                        & (cam_points[:, 0] <= (res_w-1))
                        & (cam_points[:, 1] >= 0)
                        & (cam_points[:, 1] <= (res_h-1))
                        & (depth > 0 )
                        & (depth < 100) # 100
                    )  # (num_pts, )
                    depth_v = depth[valid_mask].float()
                    _cam_points_v = cam_points[valid_mask]
                    flat_idx = (_cam_points_v[:,1].long() * res_w + _cam_points_v[:,0].long())
                    inf_val = torch.finfo(torch.float32).max
                    depth_map_bg = torch.full((res_h*res_w,), inf_val, device=self.device, dtype=torch.float32)
                    depth_map_bg.scatter_reduce_(0, flat_idx, depth_v, reduce='amin', include_self=True)
                    depth_map_bg = depth_map_bg.view(res_h, res_w)
                    depth_bg = depth_map_bg.cpu().numpy()

                semantics = get_semantics_from_path(self.clip_path / frame["file_path"].replace("images", "segs"))
                # ground_mask = np.squeeze(get_mask_from_semantics(semantics, SemanticType.GROUND), axis=-1)
                human_mask = get_mask_from_semantics(semantics, SemanticType.HUMAN)
                vehicle_mask = get_mask_from_semantics(semantics, SemanticType.VEHICLE)
                # use diff_ratio to filter points 
                diff_ratio= np.abs(depth_bg- depth_bg_ref) / (depth_bg_ref + 1e-6)
                th_diff_ratio=0.2
                depth_bg[diff_ratio>th_diff_ratio]=0
                depth_bg[human_mask==0]=0
                depth_bg[vehicle_mask==0]=0
                # 保存为统一字典格式
                depth_mask = self._depth_valid_mask(depth_bg)
                depth_file_name = frame['file_path'].replace('images/', 'depth/')[:-4] + ".npy"
                self._save_depth_and_normal_to_npy(depth_file_name, depth_bg, depth_mask)

            frame_idx = frame_idx + 1

    def generate_depth_from_lidar(self, folder_name="depth_pcd"):
        # get transform dict as key=timestamp and value=[transform_cam0, transform_cam2, ...]
        sorted_transforms = {}
        for i in self.transform_json['frames']:
            timestamp = i['timestamp']
            if timestamp not in sorted_transforms:
                sorted_transforms[timestamp] = []
            sorted_transforms[timestamp].append(i)
        sorted_transforms = dict(sorted(sorted_transforms.items()))

        # get transform dict as key=timestamp and value=transform_lidar
        pcd_transforms = {}
        for i in self.transform_json['lidar_frames']:
            timestamp = i['timestamp']
            pcd_transforms[timestamp] = i
        
        # generate depth from pcd of each timestamp
        calibrations = get_calibration(self.clip_path / "calib.json", self.cfg.target_lidar)
        for i, (timestamp, transforms) in enumerate(sorted_transforms.items()):
            pcd_path = os.path.join(self.clip_path, pcd_transforms[timestamp]['file_path'])
            rig2anchor = self.localpose_lidar_aligned[str(timestamp)]
            lidar2rig = calibrations._lidar2rig
            pcds = read_pcd(pcd_path, rig2anchor, lidar2rig)
            # compute normal from pcd
            # pcds.estimate_normals(search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=0.1, max_nn=20))
            # pcds.orient_normals_consistent_tangent_plane(10)
            # loop through all cams in this timestmap
            self.generate_pcd_one_frame(pcds, transforms, folder_name)
            print(f"[INFO][{i}/{len(sorted_transforms)}] Save depth/normal images for timestamp {timestamp}.")
            
    def generate_pcd_one_frame(self, pcds, transform_frames, folder_name):
        for i, transform_frame in enumerate(transform_frames):
            xyzs = np.array(pcds.points).astype(np.float32).transpose((1, 0))
            # normals = np.array(pcds.normals).astype(np.float32).transpose((1, 0)) 
            cam_name = transform_frame["camera"]
            if cam_name not in self.used_cams:
                continue
            in_params_cam = self.transform_json["sensor_params"][cam_name]["camera_intrinsic"]
            res_w = self.transform_json["sensor_params"][cam_name]["width"]
            res_h = self.transform_json["sensor_params"][cam_name]["height"]
            x, y = 0, 0
            h, w = res_h, res_w

            camera2anchor = np.array(transform_frame["transform_matrix"])
            anchor2camera = np.linalg.inv(camera2anchor).astype(np.float32)
            lidar_points_cam = self.projection.lidar_points_to_camera(xyzs, anchor2camera)
            lidar_points_image = self.projection.points_camera_to_image(lidar_points_cam, in_params_cam)
            # lidar_normals_cam = self.projection.transform_normals_to_camera(normals, anchor2camera)

            lidar_points_image = lidar_points_image.transpose((1, 0))
            lidar_points_cam = lidar_points_cam.transpose((1, 0))
            # lidar_normals_cam = lidar_normals_cam.transpose((1, 0))

            lidar_points_image = lidar_points_image.round().astype(np.int32)
            mask = ((lidar_points_image[:, 0] > x) & (lidar_points_image[:, 0] < x+w) & 
                    (lidar_points_image[:, 1] > y) & (lidar_points_image[:, 1] < y+h) & 
                    (lidar_points_cam[:, 2] > 0.0))

            lidar_points_image = lidar_points_image[mask]
            lidar_points_cam = lidar_points_cam[mask]
            # lidar_normals_cam = lidar_normals_cam[mask]

            points_depth = lidar_points_cam[:, 2]
            depth_image = (np.ones((res_h, res_w)) * np.finfo(np.float32).max).astype(np.float32)
            # normal_image = np.zeros((res_h, res_w, 3), dtype=np.float32) 
            for idx in range(points_depth.shape[0]):
                w = lidar_points_image[idx, 0]
                h = lidar_points_image[idx, 1]
                d = points_depth[idx]
                if d < depth_image[h, w]:
                    depth_image[h, w] = d
                    # normal_image[h, w] = lidar_normals_cam[idx]

            depth_image_mask = (depth_image >= 0) & (depth_image <= self.cfg.depth_processor.depth_max_distance)
            # normal_image_mask = (depth_image >= 0) & (depth_image <= self.cfg.depth_processor.normal_max_distance)
            depth_file_name = transform_frame['file_path'].replace('images/', f'{folder_name}/')[:-4] + ".npy"
            # normal_file_name = transform_frame['file_path'].replace('images/', 'normal_pcd/')[:-4] + ".npy"
            self._save_depth_and_normal_to_npy(depth_file_name, depth_image, depth_image_mask)
            # self._save_depth_and_normal_to_npy(normal_file_name, normal_image, normal_image_mask)            

    def _save_depth_and_normal_to_npy(self, file_name, dimg, dimg_mask):
        file_path = self.clip_path / file_name
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        npy_file = dict()
        npy_file['mask'] = dimg_mask
        npy_file['value'] = dimg[dimg_mask]
        np.save(file_path, npy_file)

    def _load_input_points(self, voxel_size=None):
        if not self.cfg.steps_controller.mvsnet_processor:
            bkgd_pcd_path = str(self.clip_path / "input_ply/points3D_bkgd.ply")
        else:
            bkgd_pcd_path = str(self.clip_path / "misc/mvsnet/mvsnet_final.ply")

        bkgd_pcd = o3d.io.read_point_cloud(bkgd_pcd_path)
        voxel_size = voxel_size if voxel_size is not None else self.cfg.depth_processor.depth_generator_voxel_size
        if voxel_size > 0:
            bkgd_pcd = bkgd_pcd.voxel_down_sample(voxel_size=voxel_size)

        points = np.array(bkgd_pcd.points).astype(np.float32)
        self.xyzs = torch.from_numpy(points.transpose((1, 0))).float().share_memory_().to(self.device)
        print(f"[INFO] Load point cloud with {self.xyzs.shape[1]} points after filtering")

    def _load_images_roi(self):
        for cam_name in self.transform_json['sensor_params']['camera_order']:
            roi_file_path = self.clip_path / f"misc/roi_{cam_name}.json"
            self.images_roi[cam_name] = json.load(open(roi_file_path, "r"))

    def _group_frames_by_timestamp(self):
        frame_groups = {}
        for transform_frame in self.transform_json["frames"]:
            cam_name = transform_frame["camera"]
            if cam_name not in self.used_cams:
                continue
            timestamp = transform_frame["timestamp"]
            frame_groups.setdefault(timestamp, []).append(transform_frame)
        return frame_groups

    def _depth_valid_mask(self, dimg):
        return (dimg > 0) & (dimg <= self.cfg.depth_processor.depth_max_distance)

    def save_visual_dimg(self, folder_name, output_folder, axis=1):
        render_depth_mosaic(
            self.clip_path, self.transform_json, self.used_cams, folder_name, output_folder, 
            axis=axis, stride=3, scale=0.6, use_cuda=True, n_jobs=8
        )

    def save_visual_images(self, depth_folder="depth", output_folder="depth_vis"):
        self.save_visual_dimg(depth_folder, output_folder)
        export_depth_videos(self.cfg.clip_path, folders=[output_folder], dst_suffix="_video")


if __name__ == '__main__':
    from settings.config import make_default_settings, make_case_specific_settings
    clip_ids = {
        "c-53f6a003-bc38-3a96-ae44-adc7fb383ff0": "vision_407",
    }
    for clip, folder in clip_ids.items():
        cfg = make_default_settings()
        cfg.ips_deploy = False
        cfg.dataset_name = "vision_407"
        cfg.root = f"/workspace/yangxh7@xiaopeng.com/datasets/xpeng/{folder}/"
        cfg.steps_controller.source = "vision"
        cfg.clip_id = clip
        cfg.use_raw_localpose = True
        cfg.steps_controller.mvsnet_processor = True
        cfg.depth_processor.depth_source = "reproj"
        cfg.depth_processor.reproj_conf_min = 0.6
        cfg = make_case_specific_settings(cfg)

        depth_processor = DepthProcessor(cfg)
        depth_processor.process_depth_vision()
        # depth_processor.save_visual_images('depth/', 'depth_vis/')
