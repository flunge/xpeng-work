import os
import cv2
import json
import numpy as np
from pathlib import Path

from depth_processor import DepthProcessor
from utils.calib_utils import get_calibration, load_localpose_and_anchorpose_from_json
from utils.novel_utils import get_lateral_shifted_egoposes
from utils.misc import get_transform_json


class NovelProcessor:
    def __init__(self, cfg, shift=3.5):
        self.cfg = cfg
        self.shift = shift
        self.clip_path = Path(self.cfg.clip_path)
        calib_path = self.clip_path / "calib.json"
        self.calibrations = get_calibration(calib_path, self.cfg.target_lidar)
        self.localpose = json.load(open(self.clip_path / "localpose.json", "r"))
        self.anchorpose = json.load(open(self.clip_path / "anchorpose.json", "r"))
        self.transform_json = json.load(open(self.clip_path / "transform.json", "r"))
        self.load_origin_parameters()

    def load_origin_parameters(self):
        self.images_list = set()
        self.cam_hw_dict = dict()
        cam_list = set()
        for frame in self.transform_json['frames']:
            self.images_list.add(str(frame['timestamp']) + ".png")
            cam_list.add(frame['camera'])
        self.images_list = sorted(list(self.images_list))
        
        for cam_name in cam_list:
            self.cam_hw_dict[cam_name] = {
                'w': self.transform_json['sensor_params'][cam_name]['width'], 
                'h': self.transform_json['sensor_params'][cam_name]['height']}

    def dump_novel_parameters(self):
        localpose_sorted = sorted(self.localpose.items(), key=lambda x: x[0])
        localpose_sorted = np.array([np.array(i[1]).reshape(4, 4) for i in localpose_sorted])
        localpose_shifted = get_lateral_shifted_egoposes(localpose_sorted, self.shift)
        localpose_dump = {}
        self.localpose_anchored = {}
        self.localpose_shifted = {}
        self.localpose_shifted_anchored = {}
        world2anchor = np.linalg.inv(self.anchorpose)
        for i, timestamp in enumerate(self.localpose.keys()):
            self.localpose_shifted[timestamp] = localpose_shifted[i]
            self.localpose_shifted_anchored[timestamp] = world2anchor @ localpose_shifted[i]
            self.localpose_anchored[timestamp] = world2anchor @ np.array(self.localpose[timestamp])
            localpose_dump[timestamp] = localpose_shifted[i].tolist()
        
        novel_name = f"novel_localpose_{self.shift}.json"
        json.dump(localpose_dump, open(self.clip_path / novel_name, "w"), indent=4)

        self.transform_shifted = get_transform_json(
            self.images_list, self.calibrations, self.cam_hw_dict, self.localpose_shifted, self.anchorpose, self.cfg.target_lidar
        )
        self.transform_shifted['lidar_frames'] = self.transform_json['lidar_frames']
        novel_name = f"novel_transform_{self.shift}.json"
        json.dump(self.transform_shifted, open(self.clip_path / novel_name, "w"), indent=4)

    def generate_novel_depth(self):
        depth_processor = DepthProcessor(self.cfg)
        depth_processor.transform_json = self.transform_shifted
        depth_processor.generate_depth_from_lidar(folder_name=f"depth_pcd_{self.shift}")


if __name__ == "__main__":
    from settings.config import make_default_settings, make_case_specific_settings
    cfg = make_default_settings()
    cfg.dataset_name = "selected_clips_m1"
    cfg.root = "/workspace/yangxh7@xiaopeng.com/datasets/xpeng/subrun"

    cfg.clip_id = "c-480d958f-7f73-3b4b-b643-e46fe0c58b80"
    cfg.steps_controller.source = "lidar+vision"
    cfg = make_case_specific_settings(cfg)
    
    novel_processor = NovelProcessor(cfg, 3.5)
    novel_processor.dump_novel_parameters()
    novel_processor.generate_novel_depth()