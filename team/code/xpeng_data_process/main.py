import os
import json
import time

import pipelines
from settings.config import get_config_list, make_case_specific_settings
from generate_dataset_data import dump_source_data
from utils.file_utils import cleanup_clip_folder


def main():
    cfg_list = get_config_list()
    for cfg in cfg_list:
        time0 = time.time()
        ################# Step 0: setup config for clip based on given cfg
        print("============================================================")
        print(f"######### [INFO] Start processing clip or subrun")

        cfg = make_case_specific_settings(cfg)
        if cfg.profile:
            import cProfile
            profiler = cProfile.Profile()
            profiler.enable() 

        ################# Step 1: download clip data 
        print("============================================================")
        print(f"######### [INFO] Start downloading clip data from dataloader")
        if not dump_source_data(cfg, start_time=None, end_time=None):
            raise Exception(f"[ERROR] Fail to dump clip data! dump_source_data return False!")

        ################# Step 2/3: preprocessing
        time1 = time.time() 
        cleanup_clip_folder(cfg.clip_path)
        timing_dict = {}
        if cfg.steps_controller.source == "lidar":
            pipelines.pipeline_m1_lidar_cpu(cfg, timing_dict)
            pipelines.pipeline_m1_lidar_gpu(cfg, timing_dict)
        elif cfg.steps_controller.source == "vision":
            pipelines.pipeline_vision_cpu(cfg, timing_dict)
            pipelines.pipeline_vision_gpu(cfg, timing_dict)
        else:
            raise ValueError(f"Unknown source: {cfg.steps_controller.source}")

        ################# Last step: summary, cleanup and upload to cloud
        print("============================================================")
        cleanup_clip_folder(cfg.clip_path)
        time2 = time.time()
        print(f"######### [INFO] Finish data dump {cfg.clip_id} in {(time1-time0)/60.:.2f}min")
        print(f"######### [INFO] Finish processing clip {cfg.clip_id} in {(time2-time1)/60.:.2f}min")
        if cfg.profile:
            profiler.disable()
            profiler.dump_stats(os.path.join(cfg.clip_path, "preprocess_profile.prof"))

        json.dump(timing_dict, open(os.path.join(cfg.clip_path, "timing.json"), 'w'), indent=4)
        

if __name__ == "__main__":
    main()