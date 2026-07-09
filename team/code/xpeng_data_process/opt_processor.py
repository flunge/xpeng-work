import os
import json
import numpy as np
import cv2
import sys
import torch
import random
from copy import deepcopy
from itertools import chain
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from utils.file_utils import get_semantics_from_path, get_mask_from_semantics
from utils.calib_utils import interpolate_localpose_data, get_calibration
from utils.qa_pose import check_localpose_z_anomaly
from utils.general_utils import pq_pose_to_4x4
from utils.misc import get_transform_json
from utils.annotation_utils import get_annotation_dynamic_xnet, get_annotation_autolabel
from utils.annotation_sf import get_annotation_from_sf
from settings.globals import SemanticType

from evo.core.trajectory import PoseTrajectory3D
from optimization.camopt.run_campose_est import run_vslam
from optimization.camopt.dpvo.plot_utils import save_output_for_COLMAP
from optimization.lidaropt.process.align_campose import main as align_campose
from optimization.lidaropt.process.pose_to_transform import main as pose_to_transform
from optimization.posemapping.run_vslam_superglue import main as run_vslam_superglue

from optimization.lidaropt.process import gen_global_pcd
from optimization.lidaropt.lidar2cam_opt.submodules.Python_VO import main as superpoint_superglue_main
from optimization.lidaropt.lidar2cam_opt.geometry import main as geometry_main
from optimization.lidaropt.lidar2cam_opt.calibration import main as calibration_main


class OptProcessor:
    def __init__(self, cfg):
        self.auto_qa_passed = True
        self.cfg = cfg
        self.transform_name = "transform.json"
        self._set_lidar2cam_info()

    def _load_transform_json(self):
        self.transform_json = json.load(open(os.path.join(self.cfg.clip_path, self.transform_name), "r"))

    def _set_lidar2cam_info(self):
        self.seg_dir = os.path.join(self.cfg.clip_path, "segs")
        self.output_2dgs = os.path.join(self.cfg.clip_path, "output_lidar2cam")
        self.save_dir = self.cfg.clip_id.split("-")[1][:3] + "-0-t"

    def process_optimization(self):
        random.seed(42)
        np.random.seed(42)
        torch.manual_seed(42)
        self.backup_original_json()
        process_success = False

        if self.cfg.opt_processor.use_superglue:
            self._load_transform_json()
            process_success |= self.process_vslam_superglue()

        if self.cfg.opt_processor.use_dpvo:
            self._load_transform_json()
            process_success |= self.process_vslam_dpvo()

        if self.cfg.opt_processor.use_lidaropt:
            self.process_lidar2cam(self.cfg.lidaropt.num_pcd_cvt)

        if process_success:
            self.regenerate_transform_and_annotation_json()
            self.backup_unused_json()
        else:
            print(f"[ERROR] {self.cfg.clip_id} Pose optimization failed! Use origin pose")


    def process_vslam_dpvo(self):
        self.generate_dynamic_mask()
        self.run_camopt_auto_qa()
        if self.auto_qa_passed:
            print("[INFO] Auto QA passed, proceed with campose estimation...")
            self.run_campose_est()
            self.run_align_campose()
            self.run_pose_to_transform()
            if self.cfg.steps_controller.source != 'vision':
                self.interpolate_localpose_lidar()
            
            anomaly_info = check_localpose_z_anomaly(os.path.join(self.cfg.clip_path, 'localpose_ego_fix.json'), verbose=True)
            if len(anomaly_info) > 2:
                json.dump(anomaly_info, open(f"{self.cfg.clip_path}/pose_anomaly.json", "w"), indent=4)
                print("[ERROR] Pose优化失败！Anomaly detected, please check the pose_anomaly.json file. Use origin pose")
                return False
            else:
                self.dump_anchorpose_new_json()
                self.replace_json_with_ego_fixed()
                return True
        return False

    def run_camopt_auto_qa(self):
        cfg = self.cfg.camopt
        img_dir = os.path.join(self.cfg.clip_path, cfg.name, "cam0")
        img_exts = ["*.png", "*.jpeg", "*.jpg"]
        img_list = sorted(chain.from_iterable(Path(img_dir).glob(e) for e in img_exts))

        prev_mask = None
        ratio_dict = {}
        invalid_frames = []
        for ii, imfile in enumerate(img_list):
            curr_mask = cv2.imread(imfile, cv2.IMREAD_UNCHANGED)
            mask = cv2.bitwise_and(curr_mask, prev_mask) if prev_mask is not None else curr_mask
            h, w = mask.shape[:2]
            invalid_ratio = float(1.0 - np.sum(mask > 0) / (h * w))
            if invalid_ratio > cfg.qa_mask_ratio:
                if invalid_frames and ii == invalid_frames[-1][1] + 1:
                    invalid_frames[-1][1] = ii
                else:
                    invalid_frames.append([ii, ii])
            prev_mask = curr_mask
            ratio_dict[imfile.stem] = invalid_ratio

        # Continuous fail number check
        invalid_range_indices = []
        for ii, frame_range in enumerate(invalid_frames):
            start_idx, end_idx = frame_range
            continuous_fail_num = end_idx - start_idx + 1
            if continuous_fail_num >= cfg.qa_continuous_fail_num:
                invalid_range_indices.append(ii)

        if invalid_range_indices:
            self.auto_qa_passed = False
            ts_list = [imfile.stem for imfile in img_list]
            print(f"[ERROR] Auto QA failed for clip {self.cfg.clip_id}, invalid frame ranges:")
            for idx in invalid_range_indices:
                ii_s, ii_e = invalid_frames[idx]
                print(f"  {ts_list[ii_s]} to {ts_list[ii_e]} have over {cfg.qa_mask_ratio} mask of {ii_e - ii_s + 1} frames")

        qa_result = {
            "auto_qa_passed": self.auto_qa_passed,
            "invalid_frames": invalid_frames,
            "ratio_range:": [min(ratio_dict.values()), max(ratio_dict.values())],
            "ratio_dict": ratio_dict,
        }
        with open(os.path.join(self.cfg.clip_path, self.cfg.camopt.name, "qa_result.json"), "w") as f:
            json.dump(qa_result, f, indent=4)

    def process_lidar2cam(self, num_pcd_cvt=50):
        self.run_data_preparation("cam0", num_pcd_cvt)
        self.feature_extraction()
        self.run_2dgs()
        self.run_calibration()
        self.gen_data_for_lidar2cam("cam2", num_pcd_cvt)
        self.replace_calib_json_with_lidar_fixed()

    def _process_single_frame(self, transform_frame):
        """处理单个帧的动态掩码生成"""
        segs_path = os.path.join(self.cfg.clip_path, "segs")
        target_cam_name = 'cam0'
        target_dir = "dyn_mask"

        cam_name = transform_frame["camera"]
        if cam_name == target_cam_name:
            img_name = transform_frame["file_path"].split("/")[-1]

            # 读取图像
            img_path = os.path.join(self.cfg.clip_path, "images", cam_name, img_name)
            if not os.path.exists(img_path):
                raise FileNotFoundError(f"Image file not found: {img_path}")

            img = cv2.imread(img_path)
            if img is None:
                raise ValueError(f"Failed to read image: {img_path}")

            # 获取语义分割
            seg_path = os.path.join(segs_path, cam_name, img_name)
            if not os.path.exists(seg_path):
                raise FileNotFoundError(f"Segmentation file not found: {seg_path}")

            semantics = get_semantics_from_path(Path(seg_path))
            mask_hum = get_mask_from_semantics(semantics, SemanticType.HUMAN).reshape(img.shape[0], img.shape[1], 1)
            mask_veh = get_mask_from_semantics(semantics, SemanticType.VEHICLE).reshape(img.shape[0], img.shape[1], 1)

            # 应用掩码
            masked_img = img * mask_hum * mask_veh

            # 保存结果
            output_path = os.path.join(self.cfg.clip_path, target_dir, img_name)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            cv2.imwrite(output_path, masked_img)

            mask_path = os.path.join(self.cfg.clip_path, self.cfg.camopt.name, target_cam_name, img_name)
            cv2.imwrite(mask_path, mask_hum * mask_veh * 255)

            # print(f"[INFO] Generated dynamic mask for {cam_name}/{img_name}")

    def generate_dynamic_mask(self):
        """使用多线程生成动态掩码"""
        if self.transform_json is None:
            raise ValueError("Transform JSON not loaded. Call _load_transform_json() first.")

        # 创建输出目录
        target_dir = os.path.join(self.cfg.clip_path, "dyn_mask")
        os.makedirs(target_dir, exist_ok=True)

        # 过滤出目标相机的帧
        target_cam_name = 'cam0'
        target_frames = [frame for frame in self.transform_json["frames"]
                        if frame["camera"] == target_cam_name]

        if not target_frames:
            print(f"[WARNING] No frames found for camera {target_cam_name}")
            return

        target_mask_path = os.path.join(self.cfg.clip_path, self.cfg.camopt.name, target_cam_name)
        if os.path.exists(target_mask_path) and len(os.listdir(target_mask_path)) > 0:
            print(f"[INFO] Dynamic mask already exists for {target_cam_name}, skipping generation")
            return
        os.makedirs(target_mask_path, exist_ok=True)

        print(f"[INFO] Processing {len(target_frames)} frames for camera {target_cam_name}")

        # 使用多线程处理
        num_workers = min(8, len(target_frames))  # 限制最大线程数
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            # 提交所有任务并等待完成
            list(executor.map(self._process_single_frame, target_frames))

        print(f"[INFO] Completed dynamic mask generation for {len(target_frames)} frames")

    def run_campose_est(self):
        cfg = self.cfg.camopt
        save_path = os.path.join(self.cfg.clip_path, cfg.name)
        (poses, tstamps), (points, colors, calib) = run_vslam(cfg, cfg.network, self.cfg.clip_path, self.transform_name, cfg.stride, cfg.skip)
        xyz = poses[:,:3]
        print(f"[INFO][DPVO] xyz mean/max/min: {np.mean(xyz, axis=0).round(3)} {np.max(xyz, axis=0).round(3)} {np.min(xyz, axis=0).round(3)}")
        trajectory = PoseTrajectory3D(positions_xyz=poses[:,:3], orientations_quat_wxyz=poses[:, [6, 3, 4, 5]], timestamps=tstamps)
        save_output_for_COLMAP(save_path, trajectory, points, colors, *calib)

    def run_align_campose(self):
        campose_dir = os.path.join(self.cfg.clip_path, "campose")
        align_campose(self.cfg.clip_path, campose_dir, self.cfg.camopt.num_align, self.transform_name)

    def run_pose_to_transform(self):
        pose_to_transform(self.cfg.clip_path, self.transform_name)

    def interpolate_localpose_lidar(self):
        localpose_path = os.path.join(self.cfg.clip_path, "localpose_ego_fix.json")
        localpose_data = json.load(open(localpose_path, "r"))
        localpose_lidar = json.load(open(os.path.join(self.cfg.clip_path, "localpose_lidar.json"), "r"))
        lidar_timestamp = sorted([int(i) for i in localpose_lidar.keys()])
        localpose_data_interpolated = interpolate_localpose_data(localpose_data, lidar_timestamp)
        with open(os.path.join(self.cfg.clip_path, "localpose_lidar_ego_fix.json"), "w") as f:
            json.dump(localpose_data_interpolated, f, indent=4)

    def dump_anchorpose_new_json(self):
        if self.cfg.steps_controller.source != 'vision':
            localpose_new = json.load(open(os.path.join(self.cfg.clip_path, "localpose_lidar_ego_fix.json"), "r"))
        else:
            localpose_new = json.load(open(os.path.join(self.cfg.clip_path, "localpose_ego_fix.json"), "r"))
        min_timestamp = min(localpose_new.keys())
        anchorpose_new = localpose_new[min_timestamp]
        with open(os.path.join(self.cfg.clip_path, "anchorpose_ego_fix.json"), "w") as f:
            json.dump(anchorpose_new, f, indent=4)

    def replace_json_with_ego_fixed(self):
        to_replace_json_list = [
            "localpose.json",
            "anchorpose.json",
        ]
        if self.cfg.steps_controller.source != 'vision':
            to_replace_json_list.append("localpose_lidar.json")
        for json_name in to_replace_json_list:
            backup_path = os.path.join(self.cfg.clip_path, json_name.replace(".json", "") + '_origin.json')
            if not os.path.exists(backup_path):
                os.system(f"cp {os.path.join(self.cfg.clip_path, json_name)} {backup_path}")
            new_json_name = json_name.replace(".json", "") + "_ego_fix.json"
            json_data = json.load(open(os.path.join(self.cfg.clip_path, new_json_name), "r"))
            with open(os.path.join(self.cfg.clip_path, json_name), "w") as f:
                json.dump(json_data, f, indent=4)

    def run_data_preparation(self, cam0, num_pcd_cvt):
        print("[Step 1/5]: 进行lidar2cam数据准备...")
        gen_global_pcd.gen_data_for_lidar2cam(
            data_root=self.cfg.clip_path,
            seg_dir=self.seg_dir,
            cam=cam0,
            num_pcd_cvt=num_pcd_cvt,
            apply_delta_lidar2ego=False
        )

    def feature_extraction(self):
        print("[Step 2/5]: 运行SuperPoint & SuperGlue...")
        data_path = os.path.join(self.cfg.clip_path, 'pcd_cvt_0')
        superpoint_superglue_main.run_superpoint_superglue(data_root=data_path, model_path=self.cfg.lidaropt.model_path)

    def run_2dgs(self):
        print("[Step 3/5]: 运行2DGS...")
        data_path = os.path.join(self.cfg.clip_path, 'pcd_cvt_0')
        geometry_main.run_2dgs(
            data_path=data_path,
            output_dir=self.output_2dgs,
            save_dir=self.save_dir
        )

    def run_calibration(self):
        import shutil
        print("[Step 4/5]: 运行calibration...")
        data_path = os.path.join(self.cfg.clip_path, 'pcd_cvt_0')
        calibration_main.run_calibration(
            data_path=data_path,
            output_dir=self.output_2dgs,
            save_dir=self.save_dir,
            render=True
        )

        res_json_src = os.path.join(self.output_2dgs, self.save_dir, "res.json")
        res_json_dst = os.path.join(data_path, "res.json")

        if os.path.exists(res_json_src):
            shutil.copy2(res_json_src, res_json_dst)

    def gen_data_for_lidar2cam(self, cam2, num_pcd_cvt):
        print("[Step 5/5]: 运行lidar外参转换...")
        gen_global_pcd.gen_data_for_lidar2cam(
            data_root=self.cfg.clip_path,
            seg_dir=self.seg_dir,
            cam=cam2,
            num_pcd_cvt=num_pcd_cvt,
            apply_delta_lidar2ego=True
        )

    def replace_calib_json_with_lidar_fixed(self):
        calib_path = os.path.join(self.cfg.clip_path, "calib.json")
        delta_lidar2ego_path = os.path.join(self.cfg.clip_path, "delta_lidar2ego2.txt")
        delta_lidar2rig = np.loadtxt(delta_lidar2ego_path)

        json_data = json.load(open(calib_path, "r"))
        backup_path = os.path.join(self.cfg.clip_path, 'calib_origin.json')
        if not os.path.exists(backup_path):
            os.system(f"cp {os.path.join(self.cfg.clip_path, 'calib.json')} {backup_path}")

        for lidar_name in self.cfg.lidar_list:
            if not json_data[lidar_name]:
                print(f"[ERROR] fail to check {lidar_name} in calib.json")
                return False
            lidar_extrinsic = json_data[lidar_name]['extrinsic']['transformation_matrix']
            lidar_extrinsic = np.array(lidar_extrinsic).reshape(4, 4)
            json_data[lidar_name]['extrinsic']['transformation_matrix'] = np.linalg.inv(delta_lidar2rig @ np.linalg.inv(lidar_extrinsic)).tolist()

        new_calib_path = os.path.join(self.cfg.clip_path, "calib_lidar_fix.json")
        with open(new_calib_path, 'w') as f:
            json.dump(json_data, f, indent=4)
        with open(calib_path, 'w') as f:
            json.dump(json_data, f, indent=4)

    def regenerate_transform_and_annotation_json(self):
        cam_hw_dict = {}
        for cam_name in self.transform_json['sensor_params']['camera_order']:
            cam_hw_dict[cam_name] = {
                "w": self.transform_json['sensor_params'][cam_name]['width'],
                "h": self.transform_json['sensor_params'][cam_name]['height'],
            }

        images_list = set([frame['file_path'].split("/")[-1] for frame in self.transform_json['frames']])
        images_list = sorted(list(images_list))

        vision_mode = self.cfg.steps_controller.source == 'vision'
        calib_path = os.path.join(self.cfg.clip_path, "calib.json")
        calibrations = get_calibration(calib_path, self.cfg.target_lidar, vision_mode=vision_mode)
        localpose = json.load(open(os.path.join(self.cfg.clip_path, "localpose.json"), "r"))
        anchorpose = json.load(open(os.path.join(self.cfg.clip_path, "anchorpose.json"), "r"))
        # 1. get transform json
        transform_json = get_transform_json(
            images_list, calibrations, cam_hw_dict, localpose, anchorpose, self.cfg.target_lidar, vision_mode=vision_mode
        )
        # 2. get annotation json
        if vision_mode:
            if self.cfg.processor.object_bbox_src == 'dxnet':
                annotation_json = get_annotation_dynamic_xnet(self.cfg.clip_path, localpose)
            else:
                annotation_json = get_annotation_from_sf(self.cfg.clip_path, localpose)
        else:
            annotation_json = get_annotation_autolabel(
                self.cfg.clip_path,
                self.cfg.use_raw_localpose,
                localpose,
                anchorpose,
                raise_on_smooth_pose_error=self.cfg.filter.raise_on_smooth_pose_error,
            )

        # 3. dump json
        os.system(f"cp {os.path.join(self.cfg.clip_path, 'transform.json')} \
            {os.path.join(self.cfg.clip_path, 'transform_origin.json')}")
        os.system(f"cp {os.path.join(self.cfg.clip_path, 'annotation_for_train.json')} \
            {os.path.join(self.cfg.clip_path, 'annotation_for_train_origin.json')}")
        json.dump(transform_json, open(os.path.join(self.cfg.clip_path, "transform.json"), "w"), indent=4)
        json.dump(annotation_json, open(os.path.join(self.cfg.clip_path, "annotation_for_train.json"), "w"), indent=4)

    def backup_unused_json(self):
        to_backup_json_list = ['localpose', 'anchorpose', 'transform', 'annotation_for_train', 'calib']
        prefix = ['_origin', '_ego_fix']
        if self.cfg.steps_controller.source != 'vision':
            to_backup_json_list.append("localpose_lidar")
            prefix.append("_lidar_fix")
        backup_dir = os.path.join(self.cfg.clip_path, 'backup_unused_json')
        os.makedirs(backup_dir, exist_ok=True)
        for json_name in to_backup_json_list:
            for p in prefix:
                backup_path = os.path.join(self.cfg.clip_path, json_name + p + '.json')
                if os.path.exists(backup_path):
                    os.system(f"mv {backup_path} {backup_dir}")

    def backup_original_json(self):
        to_backup_json_list = ['localpose', 'anchorpose', 'transform', 'annotation_for_train', 'calib']
        if self.cfg.steps_controller.source != 'vision':
            to_backup_json_list.append("localpose_lidar")
        backup_dir = os.path.join(self.cfg.clip_path, 'backup_original_json')
        os.makedirs(backup_dir, exist_ok=True)
        for json_name in to_backup_json_list:
            backup_path = os.path.join(self.cfg.clip_path, json_name + '.json')
            if os.path.exists(backup_path):
                os.system(f"cp {backup_path} {backup_dir}")

    def process_vslam_superglue(self):
        run_vslam_superglue(self.cfg.clip_path, self.cfg.camopt.name, model_path=self.cfg.lidaropt.model_path)
        self.update_calib_with_superglue()
        self.update_localpose_with_superglue()
        if self.cfg.steps_controller.source != 'vision':
            self.interpolate_localpose_lidar()
        self.dump_anchorpose_new_json()
        self.dump_transform_ego_fix_json()
        self.replace_json_with_ego_fixed()
        return True

    def update_calib_with_superglue(self):
        # Backup the original calib file
        calib_path = os.path.join(self.cfg.clip_path, "calib.json")
        with open(calib_path, "r") as f:
            json_data = json.load(f)
        backup_path = os.path.join(self.cfg.clip_path, 'calib_bef_visss.json')
        if not os.path.exists(backup_path):
            os.system(f"cp {os.path.join(self.cfg.clip_path, 'calib.json')} {backup_path}")

        # Load the new extrinsic and local pose from the vslam output
        with open(os.path.join(self.cfg.clip_path, self.cfg.camopt.name, "calib_opt.json"), 'r') as f:
            json_data_opt = json.load(f)

        # Update the extrinsic and local pose
        for cam in self.cfg.cam_list:
            if cam in json_data and cam in json_data_opt:
                json_data[cam]['extrinsic'] = json_data_opt[cam]['extrinsic']

        with open(calib_path, 'w') as f:
            json.dump(json_data, f, indent=4)

    def update_localpose_with_superglue(self):
        with open(os.path.join(self.cfg.clip_path, "localpose.json"), 'r') as f:
            localpose_data = json.load(f)
        with open(os.path.join(self.cfg.clip_path, self.cfg.camopt.name, "poses_opt.json"), 'r') as f:
            localpose_data_opt = json.load(f)

        localpose_timestamp = sorted([int(i) for i in localpose_data.keys()])
        localpose_opt_dict = {str(pose["time_stamp"]["nsec"]): pq_pose_to_4x4(pose["smooth_pose_info"]["local_pose"])
                              for pose in localpose_data_opt["cam_pose_list"]}
        localpose_opt = interpolate_localpose_data(localpose_opt_dict, localpose_timestamp)
        with open(os.path.join(self.cfg.clip_path, "localpose_ego_fix.json"), 'w') as f:
            json.dump(localpose_opt, f, indent=4)

    def dump_transform_ego_fix_json(self):
        with open(os.path.join(self.cfg.clip_path, "calib.json"), 'r') as f:
            calib_data = json.load(f)
        with open(os.path.join(self.cfg.clip_path, "localpose_ego_fix.json"), 'r') as f:
            localpose_data = json.load(f)

        # Duplicate the original transform_json to avoid modifying it directly
        transform_json = deepcopy(self.transform_json)

        # Update the extrinsic matrices
        for cam_name, cam_param in transform_json['sensor_params'].items():
            if cam_name not in calib_data:
                print(f"[WARNING] {cam_name} not in calib.json, skipping...")
                continue
            cam_param["extrinsic"] = np.linalg.inv(calib_data[cam_name]['extrinsic']['transformation_matrix']).tolist()

        # Update the camera frames pose, surposing the timestamp is the same
        for frame in transform_json["frames"]:
            cam_to_ego = np.array(transform_json["sensor_params"][frame["camera"]]["extrinsic"])
            cam_to_wrd = np.array(localpose_data[str(frame["timestamp"])]) @ cam_to_ego
            frame["transform_matrix"] = cam_to_wrd.tolist()

        with open(os.path.join(self.cfg.clip_path, "transform_ego_fix.json"), 'w') as f:
            json.dump(transform_json, f, indent=4)
        with open(os.path.join(self.cfg.clip_path, "transform.json"), 'w') as f:
            json.dump(transform_json, f, indent=4)


if __name__ == "__main__":
    from settings.config import make_default_settings, make_case_specific_settings
    torch.manual_seed(42)
    np.random.seed(42)
    random.seed(42)
    torch.cuda.manual_seed(42)
    torch.cuda.manual_seed_all(42)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    clip_ids = {
        "c-e76de66e-4e1b-3e9d-9f37-8812526cfe48": "vision_sf_testsets_251208",
    }
    for clip, folder in clip_ids.items():
        cfg = make_default_settings()
        cfg.ips_deploy = False
        cfg.dataset_name = "xxx"
        cfg.root = f"/workspace/yangxh7@xiaopeng.com/datasets/xpeng/{folder}"
        cfg.steps_controller.source = "vision"
        cfg.use_raw_localpose = True
        cfg.steps_controller.opt_processor = True
        cfg.opt_processor.use_dpvo = True
        cfg.clip_id = clip
        cfg = make_case_specific_settings(cfg)

        opt_processor = OptProcessor(cfg)
        opt_processor.process_optimization()
