import os
import cv2
import json
import numpy as np
from pathlib import Path
import math

from undistorter import Undistorter
from utils.calib_utils import get_calibration, get_localpose_and_anchorpose_from_calib
from utils.calib_utils import get_localpose_based_on_the_first_frame
from utils.misc import get_transform_json
from utils.static_recon_utils import get_localpose_from_static_recon_oss
from utils.annotation_utils import get_annotation_dynamic_xnet, get_annotation_autolabel
from utils.annotation_sf import get_annotation_from_sf
from utils.calib_utils import get_localpose_for_lidar_timestamp
from utils.match_pose_and_cam import run_target_directory as match_localpose_to_h265_images
from utils.match_pose_and_cam import rename_images_origin_to_pose_timestamp, update_calib_and_timestamp2slice_by_cam2_match


class JsonProcessor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.undistort_crop = cfg.processor.undistort_crop 
        self.undistorter = None

        self.cam_hw_dict = {}
        self.transform_json = None
        self.calibrations = None
        self.anchorpose = None
        self.annotation_for_train = None
        self.localpose_lidar = {}

    def process_input_json(self, info_dict=None):
        if self.cfg.use_h265_png:
            self.resample_png_images()

        self.check_timestamps()
        self.get_undistort_info()
        self.dump_new_clib_info()
        total_displacement = 0
        if self.cfg.steps_controller.source != "vision":
            self.get_lidar_scene_parameters()
        else:
            self.get_vision_scene_parameters()
            total_displacement = self.scene_length_check()
        self.dump_scene_json()
        interval = self.scene_data_filter()
        if info_dict is not None:
            info_dict["case_time"] = interval
            info_dict["case_distance"] = round(total_displacement / 1000.0, 2)

    def resample_png_images(self):
        # images_origin_path = os.path.join(self.cfg.clip_path, "images_origin")
        # cam_dirs = set(['cam0', 'cam2', 'cam3', 'cam4', 'cam5', 'cam6', 'cam7'])
        # if not os.path.exists(images_origin_path) or set(os.listdir(images_origin_path)) != cam_dirs:
        match_localpose_to_h265_images(Path(self.cfg.clip_path))
        rename_images_origin_to_pose_timestamp(Path(self.cfg.clip_path), dry_run=False)
        update_calib_and_timestamp2slice_by_cam2_match(Path(self.cfg.clip_path))

    def resample_png_images(self):
        images_origin_path = os.path.join(self.cfg.clip_path, "images_origin")
        cam_dirs = set(['cam0', 'cam2', 'cam3', 'cam4', 'cam5', 'cam6', 'cam7'])
        if not os.path.exists(images_origin_path) or set(os.listdir(images_origin_path)) != cam_dirs:
            match_localpose_to_h265_images(Path(self.cfg.clip_path))
            rename_images_origin_to_pose_timestamp(Path(self.cfg.clip_path), dry_run=False)
        update_calib_and_timestamp2slice_by_cam2_match(Path(self.cfg.clip_path))

    def check_timestamps(self):
        max_gap_nanoseconds = int(0.5 * 1e9) # max 0.5s
        root_dir = os.path.join(self.cfg.clip_path, "images_origin")

        for cam_name in os.listdir(root_dir):
            cam_path = os.path.join(root_dir, cam_name)

            png_files = [f for f in os.listdir(cam_path) if f.endswith('.png')]
            png_files = [os.path.join(cam_path, f) for f in png_files]
            if not png_files:
                continue

            timestamps_ns = []
            for file_path in png_files:
                file_name = os.path.basename(file_path)
                timestamp_str = file_name.replace(".png", "")
                ts_ns = int(timestamp_str)
                timestamps_ns.append(ts_ns)

            if len(timestamps_ns) < 2:
                continue

            timestamps_ns.sort()
            for i in range(1, len(timestamps_ns)):
                gap_ns = timestamps_ns[i] - timestamps_ns[i-1]
                if gap_ns > max_gap_nanoseconds:
                    gap_seconds = gap_ns / 1e9
                    raise ValueError(
                        f"Timestamp discontinuity in cam_name='{cam_name}': "
                        f"Adjacent timestamps {timestamps_ns[i-1]} "
                        f"and {timestamps_ns[i]} "
                        f"with gap {gap_seconds:.3f}s > 0.5s"
                    )
        return

    def get_undistort_info(self):
        self.undistorter = Undistorter(self.cfg)
        for cam_name in self.cfg.cam_list:
            image_list = [
                i for i in os.listdir(os.path.join(self.cfg.clip_path, "images_origin", cam_name)) if ".png" in i
            ]
            # loop each image only once
            for i, img_name in enumerate(image_list):
                img = cv2.imread(os.path.join(self.cfg.clip_path, "images_origin", cam_name, img_name))
                undistorted_img, _, roi = self.undistorter.undistort(img, cam_name, self.undistort_crop)
                self.cam_hw_dict[cam_name] = {"w": undistorted_img.shape[1], "h": undistorted_img.shape[0]}
                break

    def get_vision_scene_parameters(self):
        calib_path = os.path.join(self.cfg.clip_path, "calib.json")
        images_list = [i for i in os.listdir(os.path.join(self.cfg.clip_path, "images_origin", "cam2")) if ".png" in i]
        timestamp_list = [i.split(".")[0] for i in images_list]
        self.calibrations = get_calibration(calib_path, self.cfg.target_lidar, vision_mode=True)
        
        if self.cfg.steps_controller.vision_data_fetcher:
            localpose_new, anchorpose_new = get_localpose_from_static_recon_oss(self.cfg.root, self.cfg.clip_id, self.calibrations)
            localpose_valid = {t: v for t, v in localpose_new.items() if t in timestamp_list}
        else:
            localpose_valid, anchorpose_new = get_localpose_and_anchorpose_from_calib(calib_path)

        self.localpose, self.anchorpose = localpose_valid, anchorpose_new
        
        self.transform_json = get_transform_json(
            images_list, self.calibrations, self.cam_hw_dict, self.localpose, self.anchorpose, self.cfg.target_lidar, vision_mode=True
        )
        if self.cfg.processor.object_bbox_src == 'dxnet':
            self.annotation_for_train = get_annotation_dynamic_xnet(self.cfg.clip_path, self.localpose)
        else:
            self.annotation_for_train = get_annotation_from_sf(self.cfg.clip_path, self.localpose)
        
        if self.annotation_for_train is None:
            raise ValueError(f"[ERROR] No annotation {self.cfg.processor.object_bbox_src} found for vision clip {self.cfg.clip_id}!")

    def scene_length_check(self):
        _sort_key = lambda ts: (0, int(ts)) if int(ts) is not None else (1, str(ts))
        timestamps = sorted(self.localpose.keys(), key=_sort_key)
        if len(timestamps) < 2:
            raise ValueError("[ERROR] localpose帧数量不足")

        positions = []
        for ts in timestamps:
            pose = np.array(self.localpose[ts]).reshape(4, 4)
            positions.append(pose[:3, 3])
        positions = np.array(positions)

        deltas = positions[1:] - positions[:-1]
        total_displacement = float(np.linalg.norm(deltas, axis=1).sum())
        min_displacement = self.cfg.filter.min_localpose_traj_len

        if total_displacement < min_displacement:
            raise ValueError(
                f"[ERROR][QA] clip {self.cfg.clip_id} 的localpose总位移仅为 {total_displacement:.2f}m，小于阈值 {min_displacement:.2f}m！"
            )
        print(
            f"[INFO] clip {self.cfg.clip_id} 的localpose总位移为 {total_displacement:.2f}m，通过阈值 {min_displacement:.2f}m 校验。"
        )
        return total_displacement

    def get_lidar_scene_parameters(self):
        calib_path = os.path.join(self.cfg.clip_path, "calib.json")
        images_list = [i for i in os.listdir(os.path.join(self.cfg.clip_path, "images_origin", "cam2")) if ".png" in i]
        self.calibrations = get_calibration(calib_path, self.cfg.target_lidar)
        self.localpose_lidar = get_localpose_for_lidar_timestamp(
            self.cfg.clip_path,
            self.cfg.use_raw_localpose,
            raise_on_smooth_pose_error=self.cfg.filter.raise_on_smooth_pose_error,
        )
        self.localpose, self.anchorpose = get_localpose_and_anchorpose_from_calib(calib_path)
        self.transform_json = get_transform_json(
            images_list, self.calibrations, self.cam_hw_dict, self.localpose, self.anchorpose, self.cfg.target_lidar
        )
        self.annotation_for_train = get_annotation_autolabel(
            self.cfg.clip_path,
            self.cfg.use_raw_localpose,
            self.localpose,
            self.anchorpose,
            raise_on_smooth_pose_error=self.cfg.filter.raise_on_smooth_pose_error,
        )

    def dump_scene_json(self):
        self.dump_transform_json(name="transform.json")
        self.dump_annotation_json()
        self.dump_localpose_and_anchorpose()
        os.makedirs(os.path.join(self.cfg.clip_path, "aggregate_lidar/dynamic_objects/"), exist_ok=True)

    def scene_data_filter(self):
        Local_pose_topic_json_path = os.path.join(self.cfg.clip_path, "LocalPoseTopic.json")
        with open(Local_pose_topic_json_path) as f:
            Local_pose_topic_json = json.load(f)
        timestamps = [item['time_stamp']['nsec'] for item in Local_pose_topic_json]
        min_ts, max_ts = min(timestamps), max(timestamps)
        interval = (max_ts - min_ts) / 1e9
        if interval < self.cfg.filter.min_data_len:
            print("[ERROR] data too short for 3dgs!")
            raise ValueError("[ERROR] data too short for 3dgs!")
        return interval

    def dump_new_clib_info(self):
        self.undistorter.dump_new_clib_info()
        self.undistorter.dump_roi_info()

    def dump_transform_json(self, name):
        with open(os.path.join(self.cfg.clip_path, name), "w") as f:
            json.dump(self.transform_json, f, indent=4)
    
    def dump_annotation_json(self):
        with open(os.path.join(self.cfg.clip_path, "annotation_for_train.json"), "w") as f:
            json.dump(self.annotation_for_train, f, indent=4)

    def dump_localpose_and_anchorpose(self):
        with open(os.path.join(self.cfg.clip_path, "localpose.json"), "w") as f:
            json.dump(self.localpose, f, indent=4)
        with open(os.path.join(self.cfg.clip_path, "anchorpose.json"), "w") as f:
            json.dump(self.anchorpose.tolist(), f, indent=4)
        with open(os.path.join(self.cfg.clip_path, "localpose_lidar.json"), "w") as f:
            json.dump(self.localpose_lidar, f, indent=4)


if __name__ == "__main__":
    from settings.config import make_default_settings, make_case_specific_settings
    clip_ids = {
        "c-143f2430-dc86-39a5-a5a9-315c13c92da1": "subrun_timeline_test2",
    }
    for clip, folder in clip_ids.items():
        cfg = make_default_settings()
        cfg.ips_deploy = False
        cfg.use_h265_png = True
        cfg.dataset_name = "selected_clips_m1"
        cfg.root = f"/workspace/yangxh7@xiaopeng.com/datasets/xpeng/{folder}"
        # cfg.root = f"/workspace/group_share/adc-sim/users/yangxh7/datasets/{folder}"
        cfg.steps_controller.source = "vision"
        cfg.clip_id = clip
        cfg.use_raw_localpose = True
        cfg = make_case_specific_settings(cfg)

        json_processor = JsonProcessor(cfg)
        json_processor.process_input_json(info_dict=None)
        print(f"[INFO] JsonProcessor finish processing clip {cfg.clip_id} in {cfg.root}")
