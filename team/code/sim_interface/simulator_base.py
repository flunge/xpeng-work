from abc import abstractmethod
import torch 
from pathlib import Path
import os
import json
import shutil
import cv2
import numpy as np
import torchvision.io as io

from sim_interface.utils import get_expand_ratio, get_distortion_map, redistort, redistort_gpu
from sim_interface.utils import get_transferpose_from_dds_json, TransferposeIndex
from reconic.simulator.render_config_manager.render_config_manager import SimulatorConfigManager
from reconic.utils.car_switch_utils import get_transform_json
from reconic.multi_vehicle_utils.query_scenario_event import get_vehicle_from_scenario_config, VEHICLE_TYPE_2_ID


class BaseSimulator:
    def __init__(self, config, cp_simulation=False, iter=None, init_from_feedforward=False, vehicle_model=None):
        """
        @param cp_simulation: if True, CP simulation in loop; if False, just for render
        @param iter: iteration number
        @param vehicle_model: if provided, override the vehicle_model from metadata.json
        """
        self.model_path = None          # path to model output folder
        self.vehicle_model = None       # vehicle model
        self.cameras = None             # camera id, like [1,3,4,7]
        self.anchor_pose = None         # anchor pose used in the training
        self.cams2rig = None
        self.cam_far_plane = {
            0 : 200.0,
            2 : 100.0,
            3 : 25.0,
            4 : 25.0,
            5 : 25.0,
            6 : 25.0,
            7 : 100.0,
        }
        self.target_cam_names = []
        self.far_plane_list = []
        self.images_real, self.images_real_tensor = dict(), dict()
        self.distortion_maps, self.distortion_maps_tensor = dict(), dict()

        self.init_parameters(config, vehicle_model=vehicle_model)
        self._apply_scenario_overrides()
        self.simulator_config_manager = SimulatorConfigManager.get_instance(self.cfg.data.scene_idx)
        self.init_models(config)
        if init_from_feedforward:
            self.setup_feedforward_models(config)
        else:
            self.setup_models(config, iter)
        self.load_redistort_info()
        self.load_render_mask()
        self.cp_simulation = cp_simulation
        self.img_distort_dict = {}
        
        self.harmonization_evaluator = None
        try:
            from dynamic_assets.DCCF.scripts.camera_filter_smoother import CameraFilterSmoother
            self.camera_filter_smoother = CameraFilterSmoother()
        except ImportError:
            print("[WARNING] dynamic_assets.DCCF not found, harmonization evaluator and camera filter smoother will not be available.")
            self.camera_filter_smoother = None

        if self.cp_simulation:
            self.dds_localpose = None
            self.train_localpose = None
            self.convert_anchorpose_to_transferpose()     

    def convert_anchorpose_to_transferpose(self):
        sim_mflocalpose_json_path = os.path.join(self.model_path, "LocalPoseTopic.json")
        localpose_train = json.load(open(os.path.join(self.model_path, "localpose.json"), "r"))
        # for xpeng 3dgs, calc train localpose and dds localpose transmatrix
        transferposes, self.dds_localpose = get_transferpose_from_dds_json(
            sim_mflocalpose_json_path, localpose_train
        )
        self.anchor_pose = {
            k: np.linalg.inv(np.linalg.inv(self.anchor_pose) @ v)
            for k, v in transferposes.items()
        }
        self.transferpose_index = TransferposeIndex(self.anchor_pose)
        self.train_localpose = {
            k: np.asarray(v) for k, v in sorted(localpose_train.items())
        }

    def get_anchor_pose(self, ego_pose_world=None):
        if not self.cp_simulation:
            return self.anchor_pose
        else:
            _, anchor_pose = self.transferpose_index.find(ego_pose_world)
            return anchor_pose
    
    def _replace_cam2rig_with_origin_calib(self):
        print("[WARNING] Replacing cam2rig with inverse of origin calib extrinsics")
        calib_info_path = os.path.join(self.model_path, "calib_origin.json")
        if not os.path.exists(calib_info_path):
            print(f"[WARNING] Calibration file {calib_info_path} does not exist! Not replacing cam2rig.")
            return
        
        calib_data = json.load(open(calib_info_path, 'r'))
        inverse_matrices = []
        for cam_id in self.cameras:  # 确保按self.cameras顺序处理
            cam_name = self._label2camera[cam_id]
            if cam_name in calib_data:
                cam_info = calib_data[cam_name]
                extrinsic = cam_info["extrinsic"]
                tf_matrix = np.array(extrinsic["transformation_matrix"])
                if tf_matrix.shape != (4, 4):
                    tf_matrix = np.vstack([tf_matrix, [0, 0, 0, 1]])
                
                # 计算逆矩阵
                inverse_tf = np.linalg.inv(tf_matrix)
                inverse_matrices.append(inverse_tf)
            else:
                raise ValueError(f"[ERROR] Camera {cam_name} not found in calib_origin.json")
        
        self.cams2rig = np.array(inverse_matrices)
        print(f"[INFO] Updated {cam_name} extrinsics with inverses")

    def _load_scenario_config(self):
        """Load scenario.json from two levels up of model_path. Returns None if not found."""
        scenario_json_path = str(Path(self.model_path).parent.parent / "scenario.json")
        if not os.path.exists(scenario_json_path):
            print(f"[WARN]load_scenario_config scenario.json not found: {scenario_json_path}")
            return None
        try:
            return json.load(open(scenario_json_path, "r"))
        except Exception as e:
            print(f"[WARN] Failed to read scenario.json: {e}")
            return None

    def _override_vehicle_model(self, scenario):
        """Override self.vehicle_model from scenario's vehicle_name field."""
        try:
            vehicle_type = get_vehicle_from_scenario_config(scenario)
            scenario_vehicle_model = VEHICLE_TYPE_2_ID.get(vehicle_type.lower())
            if scenario_vehicle_model is not None:
                self.vehicle_model = scenario_vehicle_model
                print(f"[INFO] vehicle_model overridden from scenario: {vehicle_type} -> {scenario_vehicle_model}")
        except (ValueError, KeyError) as e:
            print(f"[WARN] Failed to get vehicle_model from scenario: {e}")

    def _download_calib_from_oss(self, oss_bucket: str, calib_oss_key: str) -> str:
        """Download calib file from OSS and return the local path.

        Args:
            oss_bucket: OSS bucket name, e.g. "cloudsim-ci-sh"
            calib_oss_key: OSS object key (relative path), e.g. "multi_vehicle/calibration/g01/calib.json"

        Returns:
            Local file path of the downloaded calib file.
        """
        import subprocess

        oss_path = f"oss://{oss_bucket}/{calib_oss_key}"
        local_calib_dir = os.path.join(self.model_path, "multi_vehicle_calib")
        os.makedirs(local_calib_dir, exist_ok=True)
        local_calib_path = os.path.join(local_calib_dir, os.path.basename(calib_oss_key))

        print(f"[INFO] Downloading calib from OSS: {oss_path} -> {local_calib_path}")
        cmd = [
            "ossutil64",
            "-e", "http://oss-cn-wulanchabu-internal.aliyuncs.com",
            "-i", "OSS_ACCESS_KEY_ID_REDACTED",
            "-k", "OSS_ACCESS_KEY_SECRET_REDACTED",
            "cp", oss_path, local_calib_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to download calib from OSS: {oss_path}, error: {result.stderr}")

        print(f"[INFO] Calib downloaded successfully: {local_calib_path}")
        return local_calib_path

    def _override_calib(self, new_calib_path):
        """Replace calib.json and regenerate transform.json from the given calib path."""
        if not os.path.exists(new_calib_path):
            print(f"[WARN] multi_vehicle_calib path does not exist: {new_calib_path}")
            return

        print(f"[INFO] Applying scenario calib override: {new_calib_path}")

        original_calib_path = os.path.join(self.model_path, "calib.json")
        original_transform_path = os.path.join(self.model_path, "transform.json")

        shutil.copy2(new_calib_path, original_calib_path)
        print(f"[INFO] copied new calib to: {original_calib_path}")

        new_calib = json.load(open(new_calib_path, "r"))

        original_transform_json = None
        if os.path.exists(original_transform_path):
            original_transform_json = json.load(open(original_transform_path, "r"))

        new_transform_json = get_transform_json(new_calib, original_transform_json)
        json.dump(
            new_transform_json,
            open(os.path.join(self.model_path, "transform.json"), "w"),
            indent=4,
        )
        print(f"[INFO] regenerated transform.json from scenario calib")

    def _apply_scenario_overrides(self):
        """Read scenario.json and apply all field overrides after init_parameters."""
        scenario = self._load_scenario_config()
        if scenario is None:
            return
        config_3dgs = scenario.get("3dgs_config") or {}
        calib_oss_key = config_3dgs.get("multi_vehicle_calib")
        if not calib_oss_key:
            return
        oss_bucket = config_3dgs.get("oss_bucket")
        if not oss_bucket:
            raise ValueError("multi_vehicle_calib is set but oss_bucket is not specified in 3dgs_config")
        local_calib_path = self._download_calib_from_oss(oss_bucket, calib_oss_key)
        self._override_vehicle_model(scenario)
        self._override_calib(local_calib_path)

    def init_parameters(self, config, vehicle_model=None):
        # init self parameters defined in the __init__ function
        raise NotImplementedError("init_parameters should be implemented in subclass")
    
    def init_models(self, config):
        # init gaussians models and renderer
        raise NotImplementedError("init_models should be implemented in subclass")

    def setup_models(self, config, iter=None):
        # load models from checkpoint
        raise NotImplementedError("setup_models should be implemented in subclass")

    def setup_feedforward_models(self, config):
        # load models from feedforward output
        raise NotImplementedError("setup_feedforward_models should be implemented in subclass")

    @property
    @abstractmethod
    def _label2camera(self):
        raise NotImplementedError("label2camera should be implemented in subclass")

    @property
    @abstractmethod
    def _camera2label(self):
        raise NotImplementedError("_camera2label should be implemented in subclass")

    def load_redistort_info(self):
        calib_info_path = os.path.join(self.model_path, "calib.json")
        with open(calib_info_path, "r") as fr:
            calib_info = json.load(fr)

        force_reset_expand_ratio = True if 'undistort_crop' in calib_info and calib_info['undistort_crop'] else False
        self.calib_info = get_expand_ratio(calib_info, force_reset_expand_ratio)
        ### load mask, origin images and distortion maps
        img_dir = os.path.join(self.model_path, "images")
        for cam_id in self.cameras:
            cam_name = self._label2camera[cam_id]
            undistorted_mask = cv2.imread(os.path.join(img_dir, f"{cam_name}_mask.png"), cv2.IMREAD_GRAYSCALE).astype(np.bool_)   
            image_size = list(i for i in undistorted_mask.shape[:2][::-1])
            self.distortion_maps[cam_name] = get_distortion_map(image_size, self.calib_info, cam_name)
            map_x, map_y = self.distortion_maps[cam_name]
            self.distortion_maps_tensor[cam_name] = torch.from_numpy(map_x).float().to('cuda'), torch.from_numpy(map_y).float().to('cuda')

    def load_render_mask(self):
        current_file_dir = os.path.dirname(__file__)
        mask_folder_mapping = {
            50: "assets/Vehicle_Mask_Render/F30",
            43: "assets/Vehicle_Mask_Render/E38A",
            21: "assets/Vehicle_Mask_Render/E28A",
            40: "assets/Vehicle_Mask_Render/E38",
            60: "assets/Vehicle_Mask_Render/H93",
            70: "assets/Vehicle_Mask_Render/F57",
            201: "assets/Vehicle_Mask_Render/XP5_201",
            205: "assets/Vehicle_Mask_Render/XP5_269",
            203: "assets/Vehicle_Mask_Render/E38B",
            206: "assets/Vehicle_Mask_Render/F30B",
            231: "assets/Vehicle_Mask_Render/H93AS",
            269: "assets/Vehicle_Mask_Render/XP5_269",
            247: "assets/Vehicle_Mask_Render/XP5_247",
            239: "assets/Vehicle_Mask_Render/XP5_239",
            229: "assets/Vehicle_Mask_Render/XP5_229",
            243: "assets/Vehicle_Mask_Render/XP5_243",
            238: "assets/Vehicle_Mask_Render/XP5_238",
            268: "assets/Vehicle_Mask_Render/XP5_268",
            245: "assets/Vehicle_Mask_Render/XP5_245",
            281: "assets/Vehicle_Mask_Render/XP5_281",
            284: "assets/Vehicle_Mask_Render/XP5_284",
            244: "assets/Vehicle_Mask_Render/XP5_244",
            283: "assets/Vehicle_Mask_Render/XP5_283",
            270: "assets/Vehicle_Mask_Render/XP5_270",
            304: "assets/Vehicle_Mask_Render/XP5_304",
            212: "assets/Vehicle_Mask_Render/D01M",
        }
        mask_dir = os.path.join(current_file_dir, mask_folder_mapping[self.vehicle_model])
        print(f"[INFO] Loading render mask from {mask_dir}")
        self.render_mask_dict, self.render_mask_dict_tensor, self.images_real, self.images_real_tensor \
            = dict(), dict(), dict(), dict()
        self._load_render_mask(mask_dir, mask_type="new")
        mask_dir_origin = os.path.join(current_file_dir, mask_folder_mapping[self.vehicle_model_origin])
        print(f"[INFO] Loading origin render mask from {mask_dir_origin}")
        self.render_mask_dict_origin, self.render_mask_dict_origin_tensor, self.images_real_origin, self.images_real_tensor_origin \
            = dict(), dict(), dict(), dict()
        self._load_render_mask(mask_dir_origin, mask_type="origin")

    def _load_render_mask(self, mask_dir, mask_type="origin"):
        for cam_id in self.cameras:
            cam_name = self._label2camera[cam_id]
            if cam_name in ["cam2", "cam3", "cam4", "cam5", "cam6"]:
                mask_file_name = f"_{cam_name}.png"
                mask_path = os.path.join(mask_dir, mask_file_name)
                images_origin_path = os.path.join(mask_dir, 'rgb' + mask_file_name)
                mask_render = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE).astype(np.bool_)
                images_origin_render = cv2.imread(images_origin_path, cv2.IMREAD_COLOR)
                # cv2 为 BGR; 3DGS / difix / 输出均为 RGB, 此处必须转换否则贴车身会偏色(如发白变黄)
                if images_origin_render is not None:
                    images_origin_render = cv2.cvtColor(images_origin_render, cv2.COLOR_BGR2RGB)
                if mask_type == "origin":
                    self.render_mask_dict_origin[cam_name] = mask_render
                    self.render_mask_dict_origin_tensor[cam_name] = torch.from_numpy(mask_render).bool().to('cuda')
                    self.images_real_origin[cam_name] = images_origin_render
                    self.images_real_tensor_origin[cam_name] = torch.from_numpy(images_origin_render).to('cuda').to(torch.uint8).permute(2, 0, 1)
                else:
                    self.render_mask_dict[cam_name] = mask_render
                    self.render_mask_dict_tensor[cam_name] = torch.from_numpy(mask_render).bool().to('cuda')
                    self.images_real[cam_name] = images_origin_render
                    self.images_real_tensor[cam_name] = torch.from_numpy(images_origin_render).to('cuda').to(torch.uint8).permute(2, 0, 1)

    def simulate_one_frame(self, timestamp: int, ego_pose_world):
        """
        [SIM-API] Simulate one frame at a given timestamp and ego_pose in the shape of [4, 4]
        """
        results = dict()
        for cam_id in self.cameras:
            cam_name = self._label2camera[cam_id]
            result, camera = self.render(cam_name, timestamp, ego_pose_world)
            rgb = torch.clamp((result["rgb"] * 255), 0, 255).permute(2, 0, 1).to(torch.uint8)
            img_distort = self.redistort_gpu(cam_name, rgb)
            self.img_distort_dict[cam_name] = img_distort
            results[self._label2camera[cam_id]] = img_distort
        return results

    def simulate_one_frame_batch(self, timestamp: int, ego_pose_world, use_sky_scale=False):
        """
        [SIM-API] Simulate one frame at a given timestamp and ego_pose in the shape of [4, 4]
        """
        results = dict()
        if not self.target_cam_names:
            for cam_id in self.cameras:
                self.target_cam_names.append(self._label2camera[cam_id])
                print(f"target_cam_name:{self._label2camera[cam_id]}")
                self.far_plane_list.append(self.cam_far_plane[cam_id])
        gs_results = self.render_multi_cam(
            self.target_cam_names, timestamp, ego_pose_world, self.far_plane_list, use_sky_scale=use_sky_scale
        )
        for cam_name, result in zip(self.target_cam_names, gs_results):
            rgb = torch.clamp((result["rgb"] * 255), 0, 255).permute(2, 0, 1).to(torch.uint8)
            img_distort = self.redistort_gpu(cam_name, rgb)
            results[cam_name] = img_distort
            self.img_distort_dict[cam_name] = img_distort
        return results


    def simulate_one_frame_stream(self, timestamp: int, ego_pose_world):
        """
        [SIM-API] Simulate one frame at a given timestamp and ego_pose in the shape of [4, 4]
        """
        results = dict()
        # 第一阶段：使用一组 stream 并行渲染，得到各相机的 rgb
        render_streams = [torch.cuda.Stream() for _ in self.cameras]
        rgb_dict = {}

        for cam_id, stream in zip(self.cameras, render_streams):
            cam_name = self._label2camera[cam_id]
            stream.wait_stream(torch.cuda.current_stream())
            with torch.cuda.stream(stream):
                result, camera = self.render_hil(cam_name, timestamp, ego_pose_world)
                rgb = torch.clamp((result["rgb"] * 255).to(torch.uint8), 0, 255).permute(2, 0, 1)
                rgb_dict[cam_name] = rgb

        # 等第一阶段全部完成，保证 redistort 阶段只在渲染结束后启动
        torch.cuda.synchronize()

        # 第二阶段：使用另一组 stream 并行执行 redistort
        redistort_streams = [torch.cuda.Stream() for _ in self.cameras]
        for cam_id, stream in zip(self.cameras, redistort_streams):
            cam_name = self._label2camera[cam_id]
            stream.wait_stream(torch.cuda.current_stream())
            with torch.cuda.stream(stream):
                img_distort = self.redistort_gpu(cam_name, rgb_dict[cam_name])
                self.img_distort_dict[cam_name] = img_distort
                results[cam_name] = img_distort

        # 等第二阶段全部完成
        torch.cuda.synchronize()
        return results
    
    def process_hil_res(self, result, camera_name, timestamp=None):  
        render_info = None     
        img_distort_tensor = self.img_distort_dict[camera_name]
        jpeg_bytes = io.encode_jpeg(
            img_distort_tensor,
            quality=95
        )
        img_data = jpeg_bytes.cpu().numpy().tobytes()
        img_data = np.frombuffer(img_data, dtype=np.uint8)
        height = img_distort_tensor.shape[1]
        width =  img_distort_tensor.shape[2]
        camera_name_to_id = {
            "cam0": 2,
            "cam2": 3,
            "cam3": 5,
            "cam4": 4,
            "cam5": 7,
            "cam6": 6,
            "cam7": 8,
            # 根据需要添加更多映射
        }
        camera_id = camera_name_to_id.get(camera_name)
        if camera_id is None:
            raise ValueError(f"No camera ID mapping found for {camera_name}")
        render_info = {
            'camera_id': camera_id,
            'width': width,
            'height': height,
            'size': len(img_data),
            'format': 4,
            'offset': 0,
            'data': img_data,
            'metadata': None
        }
        return render_info


    def render(self, cam_id, timestamp, ego_pose_world):
        camera = self.get_camera(cam_id, timestamp, ego_pose_world)
        with torch.no_grad():
            result = self.renderer.render(camera) 
        # result is dict which must contain a rgb image in the shape of [3, H, W] with key 'rgb'
        return result, camera

    def redistort(self, cam_name, img: torch.Tensor):
        img_255 = (img.detach().cpu().numpy().transpose(1, 2, 0))
        img_real = self.images_real.get(cam_name, None)
        mask_render = self.render_mask_dict.get(cam_name, None)
        img_distort = redistort(self.calib_info, cam_name, img_255, img_real, mask_render, self.distortion_maps[cam_name])
        return img_distort

    def redistort_gpu(self, cam_name: str, img: torch.Tensor):
        img_real = self.images_real_tensor.get(cam_name, None)
        mask_render = self.render_mask_dict_tensor.get(cam_name, None)
        img_distort = redistort_gpu(self.calib_info, cam_name, img, img_real, mask_render, self.distortion_maps_tensor[cam_name])
        return img_distort

    def redistort_gpu_without_mask(self, cam_name: str, img: torch.Tensor):
        img_distort = redistort_gpu(self.calib_info, cam_name, img, None, None, self.distortion_maps_tensor[cam_name])
        return img_distort

    def get_camera(self, cam_id, timestamp_sim, ego_pose_world):
        # get camera object for your renderer
        raise NotImplementedError("get_camera should be implemented in subclass")
