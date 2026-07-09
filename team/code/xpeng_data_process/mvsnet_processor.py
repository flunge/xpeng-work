import os
import json
import yaml
import subprocess
import torch
import shutil

class MvsnetProcessor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.clip_path = self.cfg.clip_path
        self.mode = self.cfg.mvsnet_processor.mode
        cur_path = os.path.abspath(__file__)
        code_dir = os.path.dirname(cur_path)
        self.config_template = os.path.join(code_dir, "mvsnet/mvsa/configs/base/recon.yaml")
        self.current_dir = os.path.dirname(os.path.abspath(__file__))

    def process_mvsnet(self):
        self.prepare_configs()
        
        # Prepare workspace and data
        self.prepare_workspace()
        
        # Run MVSNet inference
        self.run_mvsnet_inference()
        
        # Backup results
        self.backup_results()

    def prepare_configs(self):
        print("*********** Preparing configurations ***********")
        config = yaml.safe_load(open(self.config_template))
        config["ips"] = True
        config["dump_clip_data"] = True
        config["use_avm_cam"] = False
        config["scene"] = self.mode
        config["base_dir"] = os.path.join(self.clip_path, "vision/data")
        config["exp_dir"] = os.path.join(self.clip_path, "vision/recon")
        os.makedirs(config["base_dir"], exist_ok=True)
        os.makedirs(config["exp_dir"], exist_ok=True)
        
        config["clip_id"] = self.cfg.clip_id
        GPU_PER_NODE = int(str(subprocess.check_output(["nvidia-smi", "-L"])).count("UUID"))
        WORLD_SIZE = torch.cuda.device_count()
        os.environ['CUDA_VISIBLE_DEVICES'] = ','.join([str(i) for i in range(GPU_PER_NODE)])
        config['gpu_per_node'] = GPU_PER_NODE
        config['world_size'] = WORLD_SIZE
        config["recon_for_mvsnet"] = True
        config["cutoff_radius"] = 500.0
        config["dump_data_threads"] = 8
        config["sp_batch_size"] = 6
        if self.mode == "parking":
            config["slice_distance_diff_threshold"] = 0.5
            config["bev_resolution_for_parking"] = 0.02
        if 'lr' in config and isinstance(config['lr'], dict):
            config['lr'].pop('rotations', None)
            config['lr'].pop('translations', None)
        from mvsnet.mvsa.configs.base.parser import load_common_config
        config = load_common_config(config, self.cfg.pretrained_model_path)
        config_file = os.path.join(config["exp_dir"], "config.yaml")
        with open(config_file, "w") as f:
            yaml.dump(config, f, sort_keys=False)
        self.config = config

        if self.cfg.mvsnet_processor.method == "mvsa":
            import sys
            import mvsnet.mvsa.src.mvsanywhere as mvsanywhere_module
            import mvsnet.mvsa.src.mvsanywhere.options as mvsanywhere_options
            sys.modules['mvsanywhere'] = mvsanywhere_module
            sys.modules['mvsanywhere.options'] = mvsanywhere_options
            
            mvsa_config_dir = os.path.join(self.current_dir, 'mvsnet', 'mvsa', 'configs')
            data_config_path = os.path.join(mvsa_config_dir, 'data', 'xpeng_dense.yaml')
            model_config_path = os.path.join(mvsa_config_dir, 'models', 'mvsanywhere_model.yaml')
            run_config_path = os.path.join(mvsa_config_dir, 'run', 'xpeng_run_config.yaml')
            
            from mvsnet.mvsa.src.mvsanywhere.options import OptionsHandler
            option_handler = OptionsHandler()
            
            config_filepaths = [model_config_path, run_config_path]
            option_handler.parse_and_merge_options(
                config_filepaths=config_filepaths,
                ignore_cl_args=True
            )
            # update run_config
            option_handler.options.output_base_path = os.path.join(config["exp_dir"], "mvsnet_output")
            option_handler.options.scan_parent_directory = config["exp_dir"]
            if option_handler.options.load_weights_from_checkpoint is None:
                option_handler.options.load_weights_from_checkpoint = os.path.join(self.current_dir, 'mvsnet', 'mvsa', 'weights', 'mvsanywhere_hero.ckpt')
            
            data_config = OptionsHandler.load_options_from_yaml(data_config_path)
            # update data_config
            data_config.dataset_path = config["exp_dir"]
            data_config.tuple_info_file_location = os.path.join(config["exp_dir"], "mvsnet_metadata")
            # data_config.high_res_image_width = 1920
            # data_config.high_res_image_height = 899
            option_handler.options.datasets = [data_config]
            
            self.mvsa_config = option_handler.options 
        else:
            raise ValueError(f"Unsupported mvsnet method: {self.cfg.mvsnet_processor.method}")

    def verify_mvsnet_config(self, mvsnet_config):
        mvsnet_config.remove_elevated_point = False
        mvsnet_config.point_height = [-5, 500000]
        mvsnet_config.cam2_max_depth = 80
        mvsnet_config.cam_side_max_depth = 50
        mvsnet_config.cam_back_max_depth = 50
        mvsnet_config.save_unfiltered_pcd = True
        mvsnet_config.cam0_max_depth = 80
        mvsnet_config.cam234567_max_depth = 50
        mvsnet_config.batch_size = 2  # Avoid GPU OOM
        return mvsnet_config

    def prepare_workspace(self):
        print("*********** Preparing workspace ***********")
        from mvsnet.utils import generate_data
        generate_data.prepare_workspace(self.config)
        trip_path = os.path.join(self.config["exp_dir"], "image")
        metadata_dir = os.path.join(self.config["exp_dir"], "mvsnet_metadata")
        os.makedirs(metadata_dir, exist_ok=True)

        if self.cfg.mvsnet_processor.method == "mvsa":
            print("*********** Generating MVSA metadata ***********")
            from mvsnet.mvsa.scripts.data_scripts.generate_mvsnet_test_val_data import generate_mvsnet_metadata, output_view_list, convert_to_capture_format
            trip_metadata = generate_mvsnet_metadata(trip_path, mode="test")
            txt_output_path = os.path.join(metadata_dir, 'test_xpeng_tuple.txt')
            output_view_list(trip_metadata, txt_output_path)
            capture_output_path = os.path.join(metadata_dir, 'capture.json')
            convert_to_capture_format(trip_metadata, capture_output_path)
        else:
            raise ValueError(f"Unsupported mvsnet method: {self.cfg.mvsnet_processor.method}")

        metadata_file = os.path.join(metadata_dir, "metadata.json")
        with open(metadata_file, "w") as f:
            json.dump(trip_metadata, f, indent=4)

    def run_mvsnet_inference(self):
        if self.cfg.mvsnet_processor.method == "mvsa":
            from mvsnet.mvsa.src.mvsanywhere.test_xpeng import main as mvsa_inference
            print("*********** Running MVSA inference ***********")
            mvsa_inference(self.mvsa_config)
            print("*********** MVSA inference finished ***********")
        else:
            raise ValueError(f"Unsupported mvsnet method: {self.cfg.mvsnet_processor.method}")

    def backup_results(self):
        backup_dir = os.path.join(self.clip_path, "misc/mvsnet")
        os.makedirs(backup_dir, exist_ok=True)
        if self.cfg.mvsnet_processor.method == "mvsa":
            backup_files = {
                "vision/recon/mvsnet_output/meshes/xpeng.ply": "mvsnet_final.ply",
                "vision/recon/mvsnet_metadata/metadata.json": "mvsnet_metadata.json",
                "vision/recon/original_image_mapping.json": "mvsnet_original_image_mapping.json",
                "vision/recon/image/image_slice_ids.json": "mvsnet_image_slice_ids.json",
                "vision/recon/image/image_timestamps.json": "mvsnet_image_timestamps.json",
                "vision/recon/image/calib.json": "mvsnet_calib.json",
            }
            backup_dirs = {
                "vision/recon/mvsnet_output/depth_pred": "mvsnet_depth_est"
            }
        else:
            print(f"Unsupported mvsnet method: {self.cfg.mvsnet_processor.method}")
            return
        for src_rel_path, dst_name in backup_files.items():
            src_path = os.path.join(self.clip_path, src_rel_path)
            dst_path = os.path.join(backup_dir, dst_name)
            if os.path.exists(src_path):
                if os.path.exists(dst_path):
                    os.remove(dst_path)
                shutil.move(src_path, dst_path)
                print(f"[INFO] Move file: {src_rel_path} -> {dst_name}")
            else:
                print(f"[WARNING] Source file not found: {src_path}")
        
        for src_rel_path, dst_name in backup_dirs.items():
            src_path = os.path.join(self.clip_path, src_rel_path)
            dst_path = os.path.join(backup_dir, dst_name)
            if os.path.exists(src_path):
                if os.path.exists(dst_path):
                    shutil.rmtree(dst_path)
                shutil.move(src_path, dst_path)
                print(f"[INFO] Move directory: {src_rel_path} -> {dst_name}")
            else:
                print(f"[WARNING] Source directory not found: {src_path}")

if __name__ == "__main__":
    from settings.config import make_default_settings, make_case_specific_settings
    clip_ids = {
        "c-53f6a003-bc38-3a96-ae44-adc7fb383ff0": "vision_407",
    }
    for clip, folder in clip_ids.items():
        cfg = make_default_settings()
        cfg.ips_deploy = False
        cfg.dataset_name = "vision_dataset_1112"
        cfg.root = f"/workspace/group_share/adc-sim/users/yangxh7/datasets/{folder}/"
        cfg.steps_controller.source = "vision"
        cfg.steps_controller.vision_data_fetcher = False
        cfg.steps_controller.pcd_fusion_processor = True
        cfg.steps_controller.ground_processor = True
        cfg.steps_controller.mvsnet_processor = True
        cfg.steps_controller.opt_processor = True
        cfg.clip_id = clip
        cfg.use_raw_localpose = True
        cfg.processor.undistort_crop = True
        cfg.processor.expand_ratio.cam0 = 1.
        cfg.processor.expand_ratio.cam2 = 1.
        cfg.processor.expand_ratio.cam3 = 1.
        cfg.processor.expand_ratio.cam4 = 1.
        cfg.processor.expand_ratio.cam5 = 1.
        cfg.processor.expand_ratio.cam6 = 1.
        cfg.processor.expand_ratio.cam7 = 1.
        cfg = make_case_specific_settings(cfg)

        mvsnet_processor = MvsnetProcessor(cfg)
        mvsnet_processor.process_mvsnet()
        print(f"[INFO] MvsnetProcessor finish processing clip {cfg.clip_id} in {cfg.root}")
