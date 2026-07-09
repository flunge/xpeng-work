import bisect
import glob
import json
import logging
import math
import os
import shutil
import subprocess
import tarfile
import tempfile
from unittest.mock import patch

def convert_to_json_serializable(obj):
    """
    Convert numpy and torch types to Python native types for JSON serialization.
    This function handles the common types that cause JSON serialization errors.
    """
    if hasattr(obj, 'item'):  # torch tensor
        return obj.item()
    elif hasattr(obj, 'dtype'):  # numpy array or scalar
        if obj.dtype == np.float32 or obj.dtype == np.float64:
            return float(obj)
        elif obj.dtype == np.int32 or obj.dtype == np.int64:
            return int(obj)
        else:
            return obj
    elif isinstance(obj, dict):
        return {k: convert_to_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_to_json_serializable(v) for v in obj]
    else:
        return obj
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import cv2
import imageio_ffmpeg
import numpy as np
import torch
import torch.nn.functional as F
from download_file_from_oss2 import download_file_from_oss2
from PIL import Image
from scipy.spatial.transform import Rotation
from torch.autograd import Variable

DATASET_CLASSES_IN_SEMANTIC = {
    "VEHICLE": [52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65],
    "HUMAN": [0, 1, 19, 20, 21, 22],
    "GROUND": [7, 8, 13, 14, 23, 24, 41, 10],
    "SKY": [27],
}

CAM2NAME = {
    "front_narrow": "cam0",
    "front_fisheye": "cam2",
    "front_left": "cam3",
    "front_right": "cam4",
    "rear_left": "cam5",
    "rear_right": "cam6",
    "rear_main": "cam7",
}

EXCLUDED_CAMERAS = ["rear_main"]

CAM2ID = {
    "front_narrow": 1,
    "front_fisheye": 2,
    "front_left": 3,
    "front_right": 4,
    "rear_left": 5,
    "rear_right": 6,
    "rear_main": 7,
}

CAMS = (
    "front_narrow",
    "front_fisheye",
    "front_right",
    "front_left",
    "rear_left",
    "rear_right",
)

LOGGER = logging.getLogger(__name__)

def bytes_to_numpy_array(image_bytes, shape):
    return np.frombuffer(image_bytes, dtype=np.uint8).reshape(shape)

class TimeCounter:
    def __init__(self, name):
        self.name = name
        self.start_time = None

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    def stop(self):
        elapsed_time = time.perf_counter() - self.start_time
        print(f"TimeCounter: {self.name} took {elapsed_time:.2f} seconds")
        return elapsed_time

class EvaluateMetric:
    def __init__(self):
        pass

    def __call__(self, camera, time_stamp, modify_image, base_image, **kwargs):
        pass

    def name(self) -> str:
        pass

    def save_result(self, output):
        pass

    def result(self):
        pass

class PSNRMetric(EvaluateMetric):
    def __init__(self):
        self.__name = "psnr"
        self.__result = {}
        self.__skymask_result = {}
        self.__obj_result = {}

    def name(self):
        return self.__name

    def result(self):
        return self.__result

    def save_result(self, output):
        for cam in self.__result:
            converted_result = convert_to_json_serializable(self.__result[cam])
            with open(os.path.join(output, f"{self.__name}_{cam}.json"), "w") as f:
                json.dump(converted_result, f)
        for cam in self.__skymask_result:
            converted_result = convert_to_json_serializable(self.__skymask_result[cam])
            with open(os.path.join(output, f"{self.__name}_nosky_{cam}.json"), "w") as f:
                json.dump(converted_result, f)
        for cam in self.__obj_result:
            converted_result = convert_to_json_serializable(self.__obj_result[cam])
            with open(os.path.join(output, f"{self.__name}_obj_{cam}.json"), "w") as f:
                json.dump(converted_result, f)

    def psnr(self, img1, img2, mask_np=None):
        # 与 evaluate_gs.py 对齐：在有效像素(~mask_np)上计算 MSE 再转 PSNR
        img1_np = np.asarray(img1, dtype=np.float32) / 255.0
        img2_np = np.asarray(img2, dtype=np.float32) / 255.0

        if mask_np is not None:
            valid_mask = ~mask_np  # True = 有效像素
            rendered_valid = img1_np[valid_mask]
            gt_valid = img2_np[valid_mask]
            mse_valid = np.mean((rendered_valid - gt_valid) ** 2) if np.any(valid_mask) else 0.0
            return float(10.0 * np.log10(1.0 / max(mse_valid, 1e-10)))

        mse = np.mean((img1_np - img2_np) ** 2)
        if mse == 0:
            return float("inf")
        return float(20 * np.log10(1 / np.sqrt(mse)))

    def __call__(self, camera, time_stamp, modify_image, base_image, **kwargs):
        assert modify_image.shape == base_image.shape
        modify_image = modify_image.astype(np.float32)
        base_image = base_image.astype(np.float32)

        nomask_psnr = self.psnr(modify_image, base_image, mask_np=kwargs.get("mask_np"))
        if camera not in self.__result:
            self.__result[camera] = {}
        self.__result[camera][time_stamp] = nomask_psnr
        return nomask_psnr



class SSIMMetric(EvaluateMetric):
    def __init__(self, window_size: int = 11, size_average: bool = True):
        self.__name = "ssim"
        self.__result = {}
        self.__skymask_result = {}
        self.__obj_result = {}
        self.__window_size = window_size
        self.__size_average = size_average

    def ssim(self, img1, img2, **kwargs):
        # 与 tools/metric/evaluate_gs.py::_compute_ssim_map_np 保持一致：
        # 1) RGB 转灰度亮度图
        # 2) 高斯模糊计算局部统计量
        # 3) 由局部 SSIM 图求全图平均

        img1_np = np.asarray(img1)
        img2_np = np.asarray(img2)
        if img1_np.shape != img2_np.shape:
            raise ValueError(f"ssim input shape mismatch: {img1_np.shape} vs {img2_np.shape}")

        # 输入来自 cv2.imread，为 BGR uint8；先转 RGB，再归一化到 [0,1]
        if img1_np.ndim == 3 and img1_np.shape[2] == 3:
            img1_rgb = img1_np[:, :, ::-1].astype(np.float32) / 255.0
            img2_rgb = img2_np[:, :, ::-1].astype(np.float32) / 255.0
        else:
            img1_rgb = img1_np.astype(np.float32)
            img2_rgb = img2_np.astype(np.float32)
            if img1_rgb.max() > 1.0 or img2_rgb.max() > 1.0:
                img1_rgb = img1_rgb / 255.0
                img2_rgb = img2_rgb / 255.0

        C1 = 0.01 ** 2
        C2 = 0.03 ** 2
        luma_weights = np.array([0.299, 0.587, 0.114], dtype=np.float32)

        if img1_rgb.ndim == 3:
            img1_gray = np.dot(img1_rgb, luma_weights).astype(np.float32)
            img2_gray = np.dot(img2_rgb, luma_weights).astype(np.float32)
        else:
            img1_gray = img1_rgb.astype(np.float32)
            img2_gray = img2_rgb.astype(np.float32)

        gaussian_ksize = (self.__window_size, self.__window_size)
        gaussian_sigma = 1.5
        mu1 = cv2.GaussianBlur(img1_gray, gaussian_ksize, gaussian_sigma)
        mu2 = cv2.GaussianBlur(img2_gray, gaussian_ksize, gaussian_sigma)

        mu1_sq = mu1 ** 2
        mu2_sq = mu2 ** 2
        mu1_mu2 = mu1 * mu2

        sigma1_sq = cv2.GaussianBlur(img1_gray ** 2, gaussian_ksize, gaussian_sigma) - mu1_sq
        sigma2_sq = cv2.GaussianBlur(img2_gray ** 2, gaussian_ksize, gaussian_sigma) - mu2_sq
        sigma12 = cv2.GaussianBlur(img1_gray * img2_gray, gaussian_ksize, gaussian_sigma) - mu1_mu2

        ssim_map_raw = ((2 * mu1_mu2 + C1) * (2 * sigma12 + C2)) / (
            (mu1_sq + mu2_sq + C1) * (sigma1_sq + sigma2_sq + C2)
        )
        # 与 evaluate_gs.py 完全对齐：
        # ssim_error = clip(1 - ssim_map_raw, 0, 1)
        # ssim_map = 1 - ssim_error
        ssim_error_map = np.clip(1.0 - ssim_map_raw, 0.0, 1.0)
        ssim_map = 1.0 - ssim_error_map
        mask_np = kwargs.get("mask_np", None)
        if mask_np is not None:
            # 与 evaluate_gs.py 一致：mask=True 表示剔除区域，仅在有效像素(~mask)上求平均
            valid_pixels = ~mask_np
            return float(np.mean(ssim_map[valid_pixels])) if np.any(valid_pixels) else 0.0
        return float(np.mean(ssim_map))

    def __call__(self, camera, time_stamp, modify_image, base_image, **kwargs):
        assert modify_image.shape == base_image.shape

        r = self.ssim(modify_image, base_image)
        if camera not in self.__result:
            self.__result[camera] = {}
        self.__result[camera][time_stamp] = r
        return r

    def name(self):
        return self.__name

    def result(self):
        return self.__result

    def save_result(self, output):
        for cam in self.__result:
            converted_result = convert_to_json_serializable(self.__result[cam])
            with open(os.path.join(output, f"{self.__name}_{cam}.json"), "w") as f:
                json.dump(converted_result, f)
        for cam in self.__skymask_result:
            converted_result = convert_to_json_serializable(self.__skymask_result[cam])
            with open(os.path.join(output, f"{self.__name}_nosky_{cam}.json"), "w") as f:
                json.dump(converted_result, f)
        for cam in self.__obj_result:
            converted_result = convert_to_json_serializable(self.__obj_result[cam])
            with open(os.path.join(output, f"{self.__name}_obj_{cam}.json"), "w") as f:
                json.dump(converted_result, f)

    def __ssim_helper(self, img1, img2, window, window_size, channel, size_average=True):
        mu1 = F.conv2d(img1, window, padding=window_size // 2, groups=channel)
        mu2 = F.conv2d(img2, window, padding=window_size // 2, groups=channel)

        mu1_sq = mu1.pow(2)
        mu2_sq = mu2.pow(2)
        mu1_mu2 = mu1 * mu2

        sigma1_sq = (
            F.conv2d(img1 * img1, window, padding=window_size // 2, groups=channel)
            - mu1_sq
        )
        sigma2_sq = (
            F.conv2d(img2 * img2, window, padding=window_size // 2, groups=channel)
            - mu2_sq
        )
        sigma12 = (
            F.conv2d(img1 * img2, window, padding=window_size // 2, groups=channel)
            - mu1_mu2
        )

        C1 = 0.01**2
        C2 = 0.03**2

        ssim_map = ((2 * mu1_mu2 + C1) * (2 * sigma12 + C2)) / (
            (mu1_sq + mu2_sq + C1) * (sigma1_sq + sigma2_sq + C2)
        )

        if size_average:
            return ssim_map.mean()
        else:
            return ssim_map.mean(1).mean(1).mean(1)

    def __create_window(self, window_size, channel):
        def gaussian(window_size, sigma):
            gauss = torch.Tensor(
                [
                    math.exp(-((x - window_size // 2) ** 2) / float(2 * sigma**2))
                    for x in range(window_size)
                ]
            )
            return gauss / gauss.sum()

        __1D_window = gaussian(window_size, 1.5).unsqueeze(1)
        __2D_window = __1D_window.mm(__1D_window.t()).float().unsqueeze(0).unsqueeze(0)
        window = Variable(
            __2D_window.expand(channel, 1, window_size, window_size).contiguous()
        )
        return window

class LPIPSMetric(EvaluateMetric):
    def __init__(self):
        self.__name = "lpips"
        self.__result = {}
        self.__skymask_result = {}
        self.__obj_result = {}
        self.__model = None
        self.__device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        try:
            import lpips
            self.__model = lpips.LPIPS(net='alex', spatial=True).to(self.__device)
            self.__model.eval()
        except ImportError:
            LOGGER.warning("lpips not available, LPIPS metric will be disabled")
            self.__model = None

    def name(self):
        return self.__name

    def result(self):
        return self.__result

    def save_result(self, output):
        for cam in self.__result:
            converted_result = convert_to_json_serializable(self.__result[cam])
            with open(os.path.join(output, f"{self.__name}_{cam}.json"), "w") as f:
                json.dump(converted_result, f)
        for cam in self.__skymask_result:
            converted_result = convert_to_json_serializable(self.__skymask_result[cam])
            with open(os.path.join(output, f"{self.__name}_nosky_{cam}.json"), "w") as f:
                json.dump(converted_result, f)
        for cam in self.__obj_result:
            converted_result = convert_to_json_serializable(self.__obj_result[cam])
            with open(os.path.join(output, f"{self.__name}_obj_{cam}.json"), "w") as f:
                json.dump(converted_result, f)

    def lpips(self, img1, img2, **kwargs):
        if self.__model is None:
            return 0.0

        img1_np = np.asarray(img1, dtype=np.float32)
        img2_np = np.asarray(img2, dtype=np.float32)
        if img1_np.shape != img2_np.shape:
            raise ValueError(f"lpips input shape mismatch: {img1_np.shape} vs {img2_np.shape}")

        # 输入来自 cv2.imread，为 BGR uint8；先转 RGB 再归一化到 [0, 1]
        if img1_np.ndim == 3 and img1_np.shape[2] == 3:
            rendered_np = img1_np[:, :, ::-1] / 255.0
            gt_np = img2_np[:, :, ::-1] / 255.0
        else:
            rendered_np = img1_np
            gt_np = img2_np
            if rendered_np.max() > 1.0 or gt_np.max() > 1.0:
                rendered_np = rendered_np / 255.0
                gt_np = gt_np / 255.0

        h, w = rendered_np.shape[:2]
        mask_np = kwargs.get("mask_np", None)
        rendered_lpips_np = rendered_np.copy()
        gt_lpips_np = gt_np.copy()
        if mask_np is not None:
            rendered_lpips_np[mask_np] = 0.0
            gt_lpips_np[mask_np] = 0.0

        rendered_lpips = (
            torch.from_numpy(rendered_lpips_np)
            .permute(2, 0, 1)
            .unsqueeze(0)
            .to(self.__device) * 2 - 1
        )
        gt_lpips = (
            torch.from_numpy(gt_lpips_np)
            .permute(2, 0, 1)
            .unsqueeze(0)
            .to(self.__device) * 2 - 1
        )

        with torch.no_grad():
            lpips_map_tensor = self.__model(rendered_lpips, gt_lpips)
            lpips_spatial_map_lowres = lpips_map_tensor.squeeze().detach().cpu().numpy()
            lpips_spatial_map = cv2.resize(lpips_spatial_map_lowres, (w, h), interpolation=cv2.INTER_LINEAR)
            if mask_np is not None:
                valid_pixels = ~mask_np
                return float(lpips_spatial_map[valid_pixels].mean()) if np.any(valid_pixels) else 0.0
            return float(lpips_spatial_map.mean())

    def __call__(self, camera, time_stamp, modify_image, base_image, **kwargs):
        assert modify_image.shape == base_image.shape

        mask_np = kwargs.get("mask_np", None)
        r = self.lpips(modify_image, base_image, mask_np=mask_np)
        if camera not in self.__result:
            self.__result[camera] = {}
        self.__result[camera][time_stamp] = r

        if mask_np is not None:
            if camera not in self.__skymask_result:
                self.__skymask_result[camera] = {}
            self.__skymask_result[camera][time_stamp] = self.lpips(
                modify_image, base_image, mask_np=mask_np
            )
        return r

class FIDMetric(EvaluateMetric):
    def __init__(self, fid_model_path, name):
        self.__fid_model_path = fid_model_path
        self.__name = "fid"
        self.__extra_info = name
        self.__result = {}

        self.__image_size = (3, 640, 960)
        try:
            from torchvision import transforms
            self.__transform = transforms.Compose(
                [
                    transforms.Resize(self.__image_size[1:]),
                    transforms.ToTensor(),
                    transforms.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5]),
                ]
            )
        except ImportError:
            self.__transform = None
            LOGGER.warning("torchvision not available, FID metric may not work properly")

        self.__gt_image_tensors = {}
        self.__novel_image_tensors = {}

    def name(self):
        return self.__name

    def result(self):
        return self.__result

    def save_result(self, output):
        for cam in self.__result:
            novel_image_tensors = self.__novel_image_tensors[cam]
            gt_image_tensors = self.__gt_image_tensors[cam]
            fid = self.compute_fid(novel_image_tensors, gt_image_tensors)
            self.__result[cam]["frechet_inception_distance"] = fid

        for cam in self.__result:
            converted_result = convert_to_json_serializable(self.__result[cam])
            with open(
                os.path.join(output, f"{self.__name}_{cam}_{self.__extra_info}.json"),
                "w",
            ) as f:
                json.dump(converted_result, f)

    def compute_fid(self, novel_image_tensors, gt_image_tensors):
        try:
            if self.__transform is None:
                LOGGER.warning("Transform not available, cannot compute FID")
                return 0.0

            from torchmetrics.image.fid import FrechetInceptionDistance
            inception_model = FrechetInceptionDistance(
                reset_real_features=False,
                input_img_size=self.__image_size,
                feature_extractor_weights_path=self.__fid_model_path,
                normalize=True
            ).cuda()
            novel_image_tensors = [self.__transform(v).cuda() for _, v in novel_image_tensors.items()]
            gt_image_tensors = [self.__transform(v).cuda() for _, v in gt_image_tensors.items()]

            gt_image_tensors = gt_image_tensors[::2]
            novel_image_tensors = novel_image_tensors[::2]
            gt_image_tensors = torch.stack(gt_image_tensors, dim=0)
            novel_image_tensors = torch.stack(novel_image_tensors, dim=0)

            inception_model.update(gt_image_tensors, real=True)
            inception_model.update(novel_image_tensors, real=False)
            fid_value = inception_model.compute()

            return fid_value.item()
        except Exception as e:
            LOGGER.warning(f"FID computation failed: {e}")
            return 0.0

    def __call__(self, camera, time_stamp, modify_image, base_image, **kwargs):
        if camera not in self.__result:
            self.__gt_image_tensors[camera] = {}
            self.__novel_image_tensors[camera] = {}
            self.__result[camera] = {}

        self.__gt_image_tensors[camera].update({time_stamp: base_image})
        self.__novel_image_tensors[camera].update({time_stamp: modify_image})

def download_model_from_oss(oss_path: str, local_dir: str) -> bool:
    return download_file_from_oss2(local_dir, oss_path)

def extract_model(tar_path: str, extract_dir: str) -> bool:
    with tarfile.open(tar_path, 'r:*') as tar:
        tar.extractall(extract_dir)
    return True

def prepare_model(model_source: str, temp_dir: str):
    model_dir = None

    if model_source.startswith('oss://'):
        oss_path = model_source[5:]
        model_dir = os.path.join(temp_dir, "downloaded_model")
        os.makedirs(model_dir, exist_ok=True)

        if not download_model_from_oss(oss_path, model_dir):
            return None

    elif model_source.endswith('.tar') or model_source.endswith('.tar.gz') or model_source.endswith('.tgz'):
        model_dir = os.path.join(temp_dir, "extracted_model")
        os.makedirs(model_dir, exist_ok=True)

        if not extract_model(model_source, model_dir):
            return None

    else:
        model_dir = model_source
        if not os.path.exists(model_dir):
            LOGGER.error(f"Model directory does not exist: {model_dir}")
            return None

    config_files = []
    for root, dirs, files in os.walk(model_dir):
        for file in files:
            if file == 'config_sim.yaml':
                config_files.append(os.path.join(root, file))

    if not config_files:
        LOGGER.error("No config_sim.yaml found in model directory")
        return None

    return os.path.dirname(config_files[0])

def detect_model_type(model_path):
    config_sim_path = Path(model_path) / "configs/config_reconic.yaml"
    return "reconic" if config_sim_path.exists() else "street_gaussian"

def get_mask_path(cam, timestamp, model_path):
    camname = CAM2NAME[cam]
    seg_dir = os.path.join(model_path, "segs", camname)
    if not os.path.exists(seg_dir):
        return None

    mask_files = glob.glob(os.path.join(seg_dir, "*.png"))
    if not mask_files:
        return None
    mask_timestamps = [int(Path(f).stem) for f in mask_files if Path(f).stem.isdigit()]
    if not mask_timestamps:
        return None

    closest_ts = min(mask_timestamps, key=lambda x: abs(x - int(timestamp)))
    mask_path = os.path.join(seg_dir, f"{closest_ts}.png")
    return mask_path if os.path.exists(mask_path) else None

def find_closest_msg(timestamp, msgs):
    closest_msg = None
    if msgs is None or len(msgs) == 0:
        return closest_msg
    sorted_keys = sorted(msgs.keys())
    pos = bisect.bisect_left(sorted_keys, timestamp)
    if pos == 0:
        closest_key = sorted_keys[0]
    elif pos == len(sorted_keys):
        closest_key = sorted_keys[-1]
    else:
        before = sorted_keys[pos - 1]
        after = sorted_keys[pos]
        closest_key = (
            before if abs(before - timestamp) <= abs(after - timestamp) else after
        )
    return msgs[closest_key]

class Evaluator:
    def __init__(
        self,
        simulator,
        camera_base_path: str,
        output_dir: str,
        enable_fid: bool = False,
        fid_model_path: str = "",
        render_complete: bool = False,
        model_type: str = "reconic",
    ):
        self.simulator_obj = simulator
        self.camera_base_path = camera_base_path
        self.output_dir = output_dir
        self.enable_fid = enable_fid
        self.fid_model_path = fid_model_path
        self.render_complete = render_complete
        self.model_type = model_type

        LOGGER.info(f"Evaluator initialized with model type: {self.model_type}")

        # Load LocalPoseTopic.json once during initialization
        self._load_local_poses()

        # Import render function based on model type
        self._import_render_function()

        # Initialize metrics (like model_evaluate.py)
        self.image_evaluator_methods = {}
        self.image_evaluator_methods.update({
            "psnr": PSNRMetric(),
        })
        self.image_evaluator_methods.update({
            "ssim": SSIMMetric(),
        })
        self.image_evaluator_methods.update({
            "lpips": LPIPSMetric(),
        })

        self.novel_evaluator_methods = {}
        if enable_fid:
            self.novel_evaluator_methods.update({
                3.5: FIDMetric(fid_model_path, "lane_change") if fid_model_path else None
            })

        self.novel_evaluator_methods = {
            k: v for k, v in self.novel_evaluator_methods.items() if v is not None
        }

        self.mean_metrics = {}

    def _load_local_poses(self):
        local_pose_path = os.path.join(
            self.simulator_obj.model_path, "LocalPoseTopic.json"
        )

        with open(local_pose_path, 'r') as f:
            lp_data = json.load(f)

        self.lp_msgs = {msg["time_stamp"]["nsec"]: msg for msg in lp_data}

        self.local_poses = []
        self.local_timestamps = sorted(self.lp_msgs.keys())

        for ts in self.local_timestamps:
            lp = self.lp_msgs[ts]
            egopose = np.array([
                lp["smooth_pose"]["pose"]["q"]["w"],
                lp["smooth_pose"]["pose"]["q"]["x"],
                lp["smooth_pose"]["pose"]["q"]["y"],
                lp["smooth_pose"]["pose"]["q"]["z"],
                lp["smooth_pose"]["pose"]["p"]["x"],
                lp["smooth_pose"]["pose"]["p"]["y"],
                lp["smooth_pose"]["pose"]["p"]["z"],
            ])
            self.local_poses.append(egopose)

        LOGGER.info(f"Loaded {len(self.local_poses)} poses from LocalPoseTopic.json")

    def _import_render_function(self):
        if self.model_type == "reconic":
            from reconic.simulator.reconic_simulator import fun as render
        else:
            from sim_bridge.simulator import fun as render

        self.render = render
        LOGGER.info(f"Imported render function for {self.model_type} model type")

    def lp_lane_change(self, egopose, distance):
        p = egopose[4:7]
        q = egopose[0:4]
        rotation_matrix = Rotation.from_quat([q[1], q[2], q[3], q[0]]).as_matrix()
        rotation_matrix = np.array(rotation_matrix)
        local_right = np.array([0, distance, 0])
        global_right = rotation_matrix @ local_right
        new_point = np.array(p) + global_right
        return (q[0], q[1], q[2], q[3], new_point[0], new_point[1], new_point[2])

    def run_render(self):
        LOGGER.info("Starting rendering phase")

        camera_images = self.load_images("dds_raw_images")

        if not camera_images:
            LOGGER.error("No real images found in dds_raw_images")
            return

        self.run_original_render(camera_images)
        self.run_lane_change_render(camera_images)

        LOGGER.info("Rendering phase completed")

    def run_original_render(self, camera_images):
        LOGGER.info("Starting original viewpoint rendering")

        origin_render_dir = os.path.join(self.output_dir, "origin_image_render")
        os.makedirs(origin_render_dir, exist_ok=True)

        for cam in CAMS:
            cam_dir = os.path.join(origin_render_dir, cam)
            os.makedirs(cam_dir, exist_ok=True)

        image_save_queue = []

        for cam, camera_images in camera_images.items():
            if cam in EXCLUDED_CAMERAS or CAM2ID[cam] not in self.simulator_obj.cameras:
                continue
            
            timestamps = camera_images.keys()
            LOGGER.info(f"Rendering camera {CAM2NAME[cam]} ({cam}): {len(timestamps)} frames")

            for timestamp in timestamps:
                lp = find_closest_msg(int(timestamp), self.lp_msgs)

                if lp is not None:
                    egopose = np.array([
                        lp["smooth_pose"]["pose"]["q"]["w"],
                        lp["smooth_pose"]["pose"]["q"]["x"],
                        lp["smooth_pose"]["pose"]["q"]["y"],
                        lp["smooth_pose"]["pose"]["q"]["z"],
                        lp["smooth_pose"]["pose"]["p"]["x"],
                        lp["smooth_pose"]["pose"]["p"]["y"],
                        lp["smooth_pose"]["pose"]["p"]["z"],
                    ])

                    render_image_info = self.render(self.simulator_obj, timestamp, CAM2NAME[cam], egopose)

                    if render_image_info:
                        render_cam_path = os.path.join(origin_render_dir, cam)
                        image_save_queue.append((render_image_info, timestamp, render_cam_path))

        with ThreadPoolExecutor() as executor:
            executor.map(
                lambda args: self._save_render_image(*args),
                image_save_queue,
            )

        LOGGER.info("Original viewpoint rendering completed")

    def run_lane_change_render(self, camera_images):
        LOGGER.info("Starting lane change rendering")

        quick_test = os.environ.get('QUICK_TEST', 'false').lower() == 'true'

        if quick_test:
            LOGGER.info("[QUICK TEST] Skipping lane change rendering")
            return

        lane_change_dir = os.path.join(self.output_dir, "lane_change_image_render")
        os.makedirs(lane_change_dir, exist_ok=True)

        for cam in CAMS:
            cam_dir = os.path.join(lane_change_dir, cam)
            os.makedirs(cam_dir, exist_ok=True)

        lane_change_save_queue = []

        for cam, real_images in camera_images.items():
            if CAM2ID[cam] not in self.simulator_obj.cameras:
                continue

            render_cam_path = os.path.join(lane_change_dir, cam)

            for timestamp in real_images.keys():
                lp = find_closest_msg(int(timestamp), self.lp_msgs)

                if lp is not None:
                    original_pose = np.array([
                        lp["smooth_pose"]["pose"]["q"]["w"],
                        lp["smooth_pose"]["pose"]["q"]["x"],
                        lp["smooth_pose"]["pose"]["q"]["y"],
                        lp["smooth_pose"]["pose"]["q"]["z"],
                        lp["smooth_pose"]["pose"]["p"]["x"],
                        lp["smooth_pose"]["pose"]["p"]["y"],
                        lp["smooth_pose"]["pose"]["p"]["z"],
                    ])

                    pose_idx = bisect.bisect_left(self.local_timestamps, int(timestamp))
                    normalized_pos = pose_idx / max(len(self.local_timestamps) - 1, 1)
                    lateral_offset = 3.5 * math.sin(2 * math.pi * normalized_pos)

                    ego_pose_shifted = self.lp_lane_change(original_pose, lateral_offset)

                    render_image_info = self.render(self.simulator_obj, timestamp, CAM2NAME[cam], ego_pose_shifted)
                    if render_image_info:
                        lane_change_save_queue.append((render_image_info, timestamp, render_cam_path))

        with ThreadPoolExecutor() as executor:
            executor.map(
                lambda args: self._save_render_image(*args),
                lane_change_save_queue,
            )

        LOGGER.info("Lane change rendering completed")

    def run_origin_evaluate(self):
        LOGGER.info("Starting origin evaluation")

        dds_images = self.load_images("dds_raw_images")
        origin_render_images = self.load_images("origin_image_render")

        for cam, cam_origin_render_images in origin_render_images.items():
            if cam in EXCLUDED_CAMERAS or CAM2ID[cam] not in self.simulator_obj.cameras or cam not in dds_images:
                continue

            dds_camera_images = dds_images[cam]
            LOGGER.info(f"Evaluating origin render {cam} image")

            for idx, cam_origin_render_image_path in cam_origin_render_images.items():
                for k_, c in self.image_evaluator_methods.items():
                    if idx not in dds_camera_images:
                        continue

                    origin_image = cv2.imread(dds_camera_images[idx])
                    render_image = cv2.imread(cam_origin_render_image_path)

                    if origin_image is not None and render_image is not None:
                        h, w = origin_image.shape[:2]
                        mask_np = None
                        mask_path = os.path.join(self.simulator_obj.model_path, "images", f"{CAM2NAME[cam]}_mask.png")
                        if os.path.exists(mask_path):
                            mask_img = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
                            if mask_img is not None:
                                if mask_img.shape[:2] != (h, w):
                                    mask_img = cv2.resize(mask_img, (w, h), interpolation=cv2.INTER_NEAREST)
                                mask_np = mask_img <= 127  # 黑色区域为 True（剔除）

                        if mask_np is None:
                            print("Warning: mask_np is None")

                        c(
                            cam,
                            idx,
                            origin_image,
                            render_image,
                            mask=mask_path if mask_np is not None else None,
                            mask_np=mask_np,
                        )

        # 汇总每个相机在 origin 评测下的 psnr/ssim/lpips 均值
        self.mean_metrics = {}
        metric_key_to_mean_name = {
            "psnr": "psnr_mean",
            "ssim": "ssim_mean",
            "lpips": "lpips_mean",
        }

        for metric_key, mean_name in metric_key_to_mean_name.items():
            metric_obj = self.image_evaluator_methods.get(metric_key)
            if metric_obj is None:
                continue

            try:
                metric_result = metric_obj.result()
            except Exception as e:
                LOGGER.warning(f"Failed to get {metric_key} result for mean aggregation: {e}")
                continue

            if not isinstance(metric_result, dict):
                continue

            for cam, ts_values in metric_result.items():
                if not isinstance(ts_values, dict) or not ts_values:
                    continue

                valid_values = []
                for v in ts_values.values():
                    try:
                        v_float = float(v)
                    except (TypeError, ValueError):
                        continue
                    if np.isfinite(v_float):
                        valid_values.append(v_float)

                if not valid_values:
                    continue

                cam_name = CAM2NAME[cam]
                if cam_name not in self.mean_metrics:
                    self.mean_metrics[cam_name] = {}
                self.mean_metrics[cam_name][mean_name] = float(np.mean(valid_values))

        LOGGER.info(f"Origin mean metrics per camera: {self.mean_metrics}")
        LOGGER.info("Origin evaluation completed")

    def run_novel_evaluate(self):
        LOGGER.info("Starting novel evaluation")

        dds_images = self.load_images("dds_raw_images")

        for cam, dds_camera_images in dds_images.items():
            if cam in EXCLUDED_CAMERAS or CAM2ID[cam] not in self.simulator_obj.cameras:
                continue

            LOGGER.info(f"Evaluating novel {cam} image")

            for n, c in self.novel_evaluator_methods.items():
                novel_render_images = self.load_images("lane_change_image_render")

                for cam, cam_render_images in novel_render_images.items():
                    if cam not in dds_images:
                        continue

                    for idx, cam_render_image_path in cam_render_images.items():
                        if idx not in dds_camera_images:
                            continue

                        origin_image = cv2.imread(dds_camera_images[idx])
                        render_image = cv2.imread(cam_render_image_path)

                        if origin_image is not None and render_image is not None:
                            origin_image = self._cv2_to_pil(origin_image)
                            render_image = self._cv2_to_pil(render_image)
                            c(cam, idx, origin_image, render_image)

        LOGGER.info("Novel evaluation completed")

    def save_result(self):
        output_dir = os.path.join(self.output_dir, "image_evaluator")
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        for _, c in self.image_evaluator_methods.items():
            c.save_result(output_dir)
        for _, c in self.novel_evaluator_methods.items():
            c.save_result(output_dir)
        LOGGER.info("image evaluator result save to {}".format(output_dir))

    def run_merge_camera_images(self):
        for lane_change_type in [
            "dds_raw_images",
            "origin_image_render",
            "lane_change_image_render",
        ]:
            render_images = self.load_images(lane_change_type)
            for cam, cam_render_images in render_images.items():
                timestamps = list(cam_render_images.keys())
                print(f"merge origin render {cam} image to video")
                output_dir = os.path.join(
                    self.output_dir,
                    "render_video",
                    "lane_change_image_render_all"
                    if lane_change_type == "lane_change_image_render"
                    else lane_change_type,
                    cam,
                )
                if not os.path.exists(output_dir):
                    os.makedirs(output_dir)

                if len(timestamps) > 0:
                    images_to_video_v2(
                        cam_render_images.values(),
                        (timestamps[-1] - timestamps[0]) / 1e9 + 0.01,
                        os.path.join(output_dir, "video.mp4"),
                    )

        output_dir = os.path.join(self.output_dir, "merge_render_video")
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        ioput = [
            (
                os.path.join(output_dir, "origin_merge_video.mp4"),
                os.path.join(self.output_dir, "render_video/origin_image_render"),
            ),
            (
                os.path.join(output_dir, "dds_raw_images.mp4"),
                os.path.join(self.output_dir, "render_video/dds_raw_images"),
            ),
            (
                os.path.join(output_dir, "lane_change_image_render_all.mp4"),
                os.path.join(self.output_dir, "render_video/lane_change_image_render_all"),
            ),
        ]

        for output_path, base_path in ioput:
            if not os.path.exists(base_path):
                continue
            save_merge_render_videos(base_path, output_path)

    def _save_render_image(self, render_image_info, timestamp, render_path):
        render_image = bytes_to_numpy_array(
            render_image_info["image"],
            shape=(render_image_info["height"], render_image_info["width"], 3),
        )
        image_save_path = os.path.join(render_path, f"{timestamp}.png")
        Image.fromarray(render_image).save(image_save_path, compress_level=0)

    def copy_real_images(self):
        LOGGER.info("Copying real images to dds_raw_images format")

        dds_raw_images_path = os.path.join(self.output_dir, "dds_raw_images")
        os.makedirs(dds_raw_images_path, exist_ok=True)

        if not os.path.exists(self.camera_base_path):
            LOGGER.warning(f"Camera base path does not exist: {self.camera_base_path}")
            return

        LOGGER.info(f"DEBUG: Camera base path: {self.camera_base_path}")
        available_dirs = os.listdir(self.camera_base_path)
        LOGGER.info(f"DEBUG: Available directories in camera_base_path: {available_dirs}")

        for cam_name, cam in CAM2NAME.items():
            LOGGER.info(f"DEBUG: Processing cam_name='{cam_name}', cam='{cam}'")
            if cam_name in EXCLUDED_CAMERAS:
                continue

            source_cam_path = os.path.join(self.camera_base_path, cam)
            if not os.path.exists(source_cam_path):
                continue

            target_cam_path = os.path.join(dds_raw_images_path, cam_name)
            os.makedirs(target_cam_path, exist_ok=True)

            images = glob.glob(os.path.join(source_cam_path, "*.png"))
            if not images:
                continue

            images.sort()
            # Sample images based on render_complete setting
            total_images = len(images) if self.render_complete else len(images) // 2
            # Evenly sample images across the sequence
            step_ = len(images) / total_images
            sampled_indices = [int(i * step_) for i in range(total_images)]
            sampled_images = [images[i] for i in sampled_indices]
            LOGGER.info(
                f"Sampled {total_images} images from {len(images)} available images for camera {cam}"
            )

            for img_path in sampled_images:
                target_img_path = os.path.join(target_cam_path, os.path.basename(img_path))
                shutil.copy2(img_path, target_img_path)

    def merge_render_video(self, base_path: str, output_path: str):
        camera_video_paths = [
            os.path.join(base_path, cam, "video.mp4")
            for cam in CAMS
            if os.path.exists(os.path.join(base_path, cam, "video.mp4"))
        ]

        if merge_videos_to_one(
            camera_video_paths,
            output_path,
        ):
            LOGGER.info(f"merge video success, output: {output_path}")
        return True

    def load_images(self, type_):
        camera_images = {}
        base_path = os.path.join(self.output_dir, type_)

        if not os.path.exists(base_path):
            LOGGER.warning(f"Path does not exist: {base_path}")
            return camera_images

        for cam in CAMS:
            if cam in EXCLUDED_CAMERAS or CAM2ID[cam] not in self.simulator_obj.cameras:
                continue

            camera_image_path = os.path.join(base_path, cam)
            if not os.path.exists(camera_image_path):
                continue

            images = glob.glob(os.path.join(camera_image_path, "*.png"))
            if images:
                image_dict = {int(Path(img).stem): img for img in images}
                camera_images[cam] = {k: image_dict[k] for k in sorted(image_dict)}

        return camera_images

    def _cv2_to_pil(self, image):
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        return Image.fromarray(image_rgb)

def images_to_video_v2(image_paths, evaluate_time_length, output_path, crf=22, pix_fmt="yuv420p", codec="libx264"):
    image_paths = tuple(image_paths)
    assert len(image_paths) > 0, "No images provided"

    fps = len(image_paths) / evaluate_time_length

    with tempfile.TemporaryDirectory() as tmpdir:
        for idx, src_path in enumerate(image_paths):
            dst_path = os.path.join(tmpdir, f"{idx:05d}{os.path.splitext(src_path)[-1]}")
            os.symlink(os.path.abspath(src_path), dst_path)

        input_pattern = os.path.join(tmpdir, "%05d" + os.path.splitext(image_paths[0])[-1])
        cmd = [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-loglevel", "quiet", "-y",
            "-framerate", str(fps),
            "-i", input_pattern,
            "-c:v", codec,
            "-crf", str(crf),
            "-pix_fmt", pix_fmt,
            output_path,
        ]

        LOGGER.info(f"Running: {' '.join(cmd)}")
        r = subprocess.run(cmd, capture_output=True, timeout=3600)

        if r.returncode != 0:
            LOGGER.info(f"Images to video failed, reason: {r.stderr.decode()}")

def save_merge_render_videos(base_path: str, output_path: str):
    camera_video_paths = [
        os.path.join(base_path, cam, "video.mp4")
        for cam in CAMS
        if os.path.exists(os.path.join(base_path, cam, "video.mp4"))
    ]
    if merge_videos_to_one(camera_video_paths, output_path):
        LOGGER.info(f"merge video success, output: {output_path}")
    return True

def merge_videos_to_one(video_paths: List[str], output: str) -> bool:
    video_paths.sort(key=lambda x: CAM2ID[Path(x).parent.stem])
    cmd = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-y", "-loglevel", "info",
    ]
    cmd += (*sum([["-i", path] for path in video_paths], []),)
    cmd += ["-filter_complex"]
    cmd += [
        "nullsrc=size=3840x1854 [base]; \
        [base][0:v] overlay=shortest=1:x=0:y=0 [tmp1]; \
        [tmp1][1:v] overlay=shortest=1:x=1920:y=0 [tmp2]; \
        [tmp2][2:v] overlay=shortest=1:x=0:y=1080 [tmp3]; \
        [tmp3][3:v] overlay=shortest=1:x=968:y=1080 [tmp4]; \
        [tmp4][4:v] overlay=shortest=1:x=1936:y=1080 [tmp5]; \
        [tmp5][5:v] overlay=shortest=1:x=2904:y=1080"
    ]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22", output]
    LOGGER.info(f"Execute ffmpeg cmd: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, timeout=3600)
    if result.returncode != 0:
        LOGGER.error(f"Merge video failed, reason: {result.stderr.decode()}")
        return False
    return True

def upload_results_to_oss(results_dir: str, clip_id: str, model_version: str, timestamp: str) -> tuple[bool, str]:
    oss_base_path = f"sim_engine/evaluation_results/{clip_id}/{model_version}/{timestamp}"

    var_endpoint = 'http://oss-cn-wulanchabu-internal.aliyuncs.com'
    var_access_key = 'OSS_ACCESS_KEY_ID_REDACTED'
    var_secret_key = 'OSS_ACCESS_KEY_SECRET_REDACTED'
    var_bucket_name = 'cloudsim-ci-sh'

    import oss2
    auth = oss2.Auth(var_access_key, var_secret_key)
    bucket = oss2.Bucket(auth, var_endpoint.replace('http://', 'https://'), var_bucket_name)

    file_count = 0
    for root, dirs, files in os.walk(results_dir):
        for file in files:
            local_file_path = os.path.join(root, file)
            relative_path = os.path.relpath(local_file_path, results_dir)
            oss_object_key = f"{oss_base_path}/{relative_path}"

            bucket.put_object_from_file(oss_object_key, local_file_path)
            file_count += 1
            LOGGER.info(f"Uploaded: {oss_object_key}")

    oss_url = f"oss://{var_bucket_name}/{oss_base_path}"
    LOGGER.info(f"Successfully uploaded {file_count} files to OSS: {oss_url}")
    return True, oss_url

def post_process(
    logger,
    clip_id,
    model_source,
    dataset_root,
    model_version='sim3dgs_v310',
    enable_fid=False,
    render_complete=False,
    mode="normal",
    class_args=None,
):
    ips_logger = logger
    fid_model_path = ''
    images_origin_path = os.path.join(dataset_root, 'images_origin')

    if mode == "normal" and not os.path.exists(model_source):
        ips_logger.error(f"model_source does not exist locally: {model_source}")
        return None, None

    if not os.path.exists(images_origin_path):
        ips_logger.error(f"origin images does not exist locally: {images_origin_path}")
        return None, None

    ips_logger.info(f"[INFO] Using local model source: {model_source}")
    quick_test = os.environ.get('QUICK_TEST', 'false').lower() == 'true'

    if enable_fid:
        fid_model_path = "/root/.cache/torch/hub/checkpoints/weights-inception-2015-12-05-6726825d.pth"
        if os.path.exists(fid_model_path):
            ips_logger.info(f"Using local FID model: {fid_model_path}")
        else:
            ips_logger.warning(f"FID model not found at {fid_model_path}, FID evaluation will be disabled")
            fid_model_path = ""
            enable_fid = False

    ips_logger.info(f"Starting post_process for {clip_id}")
    ips_logger.info(f"Model source: {model_source}")
    ips_logger.info(f"Dataset root: {dataset_root}")
    ips_logger.info(f"Model version: {model_version}")
    ips_logger.info(f"FID enabled: {enable_fid}")
    ips_logger.info(f"Post-process mode: {mode}")

    with tempfile.TemporaryDirectory() as temp_dir:
        model_type = "reconic"
        if mode == "normal":
            ips_logger.info("Preparing model...")
            model_dir = prepare_model(model_source, temp_dir)
            if not model_dir:
                ips_logger.error("Failed to prepare model")
                return None, None

            model_config_path = os.path.join(model_dir, 'config_sim.yaml')
            if not os.path.exists(model_config_path):
                ips_logger.error(f"Model config not found: {model_config_path}")
                return None, None

            model_type = detect_model_type(model_source)
            ips_logger.info(f"Detected model type: {model_type}")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = os.path.join(temp_dir, "evaluation_results")
        os.makedirs(output_dir, exist_ok=True)

        if mode == "feedforward":
            CAM2ID["front_narrow"] = 0
            from reconic.simulator.reconic_simulator import ReconicSimulator
            simulator = ReconicSimulator(
                class_args, cp_simulation=True, init_from_feedforward=True
            )
            model_type = "reconic"
        elif model_type == "reconic":
            CAM2ID["front_narrow"] = 0
            from reconic.simulator.reconic_simulator import ReconicSimulator
            config_file = os.path.join(model_source, "configs", "config_sim.yaml")
            simulator = ReconicSimulator(config_file, cp_simulation=True)
        elif model_type == "street_gaussian":
            from lib.config import cfg
            from lib.config.config import make_cfg
            from sim_bridge.simulator import StreetGaussianSimulator

            class Args:
                def __init__(self):
                    self.config = os.path.join(model_source, "configs", "config_sim.yaml")
                    self.print_cfg = False

            args = Args()
            cfg = make_cfg(cfg, args)
            cfg.mode = "render"
            cfg.model_path = model_source
            simulator = StreetGaussianSimulator(cfg, True)
        else:
            ips_logger.error(f"Unsupported model type: {model_type}")
            return None, None

        evaluator = Evaluator(
            simulator=simulator,
            camera_base_path=images_origin_path,
            output_dir=output_dir,
            enable_fid=enable_fid,
            fid_model_path=fid_model_path,
            render_complete=render_complete,
            model_type=model_type
        )

        ips_logger.info("Starting rendering and evaluation...")
        with TimeCounter("rendering_evaluation"):
            evaluator.copy_real_images()

            evaluator.run_render()
            evaluator.run_origin_evaluate()

            if not quick_test:
                evaluator.run_novel_evaluate()

            evaluator.save_result()
            evaluator.run_merge_camera_images()

        ips_logger.info(f"Evaluation completed. Results saved to {output_dir}")

        ips_logger.info("Uploading results to OSS...")
        success, result_info = upload_results_to_oss(output_dir, clip_id, model_version, timestamp)
        if success:
            ips_logger.info("Results uploaded successfully!")
            ips_logger.info(f"OSS URL: {result_info}")
            ips_logger.info(f"Post-processing completed for {clip_id}")
            return result_info, evaluator.mean_metrics
        else:
            ips_logger.error(f"Failed to upload results: {result_info}")
            return None, None

def test_run_origin_evaluate(
    output_dir: str,
    model_path: str,
    camera_name: str = "front_narrow",
):
    """
    自测 run_origin_evaluate。目录需已按 Evaluator 约定摆好：

    - output_dir：含 dds_raw_images/{camera}/、origin_image_render/{camera}/（png stem 为数字时间戳）
    - model_path：含 images/{camera}_mask.png

    会 patch LocalPose 与 reconic render，仅跑 PSNR/SSIM。
    """
    class _FakeSim:
        def __init__(self, mp: str):
            self.model_path = os.path.abspath(mp)
            self.cameras = {0, 1, 2, 3, 4, 5, 6}

    def _noop_pose(self):
        self.lp_msgs = {}
        self.local_poses = []
        self.local_timestamps = []

    def _noop_render_import(self):
        self.render = lambda *a, **k: None

    output_dir = os.path.abspath(output_dir)
    model_path = os.path.abspath(model_path)
    mask_file = os.path.join(model_path, "all/images", f"{camera_name}_mask.png")
    if not os.path.isfile(mask_file):
        raise FileNotFoundError(f"未找到 mask: {mask_file}")

    sim = _FakeSim(model_path)
    with patch.object(Evaluator, "_load_local_poses", _noop_pose), patch.object(
        Evaluator, "_import_render_function", _noop_render_import
    ):
        ev = Evaluator(
            simulator=sim,
            camera_base_path=os.path.join(output_dir, "_unused_images_origin"),
            output_dir=output_dir,
            enable_fid=False,
            model_type="reconic",
        )
        ev.image_evaluator_methods = {
            "psnr": PSNRMetric(),
            "ssim": SSIMMetric(),
            "lpips": LPIPSMetric(),
        }

    ev.run_origin_evaluate()
    ev.save_result()
    return ev

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description="自测 run_origin_evaluate（目录已按约定整理好）")
    parser.add_argument(
        "--output_dir",
        required=True,
        help="评估根目录，含 dds_raw_images/、origin_image_render/",
    )
    parser.add_argument(
        "--model_path",
        required=True,
        help="模型根目录，含 images/{camera}_mask.png",
    )
    parser.add_argument("--camera", default="front_narrow")
    args = parser.parse_args()

    ev = test_run_origin_evaluate(args.output_dir, args.model_path, camera_name=args.camera)
    print("PSNR cameras:", list(ev.image_evaluator_methods["psnr"].result().keys()))
    print("SSIM cameras:", list(ev.image_evaluator_methods["ssim"].result().keys()))
    print("ok")
