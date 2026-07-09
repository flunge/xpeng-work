import argparse
import ctypes
import json
import os
import random
import sys
import time
import zipfile
from dataclasses import dataclass
from glob import glob
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import imageio
import numpy as np
import torch
import torchvision.transforms.functional as F
from diffusers import DDPMScheduler
from PIL import Image
from tqdm import tqdm

try:
    from .config_train import load_config as load_train_config
    from .utils_difix import calculate_psnr
except ImportError:
    from config_train import load_config as load_train_config
    from utils_difix import calculate_psnr

DEFAULT_PRETRAINED_PATH = "/workspace/group_share/adc-sim/users/led/ckpts/difix_ref"
TENSORRT_ROOT = Path("/workspace/group_share/adc-sim/users/cloudsim/TensorRT-10.13.3.9")
TENSORRT_LIB_DIR = TENSORRT_ROOT / "lib"
TENSORRT_PYTHON_DIR = TENSORRT_ROOT / "python"
TENSORRT_PYTHON_CACHE_DIR = Path.home() / ".cache" / "difix" / "tensorrt_python"
CAMERA_GROUPS = {
    "bucket_16_9": ["cam0", "cam2", "cam7"],
    "bucket_5_4": ["cam3", "cam4", "cam5", "cam6"],
}


@dataclass(frozen=True)
class Bucket:
    height: int
    width: int

    @property
    def tag(self) -> str:
        return f"{self.width}x{self.height}"


def sorted_image_list(folder):
    if not os.path.isdir(folder):
        return []
    exts = ["*.png", "*.jpg", "*.jpeg", "*.bmp"]
    files = []
    for ext in exts:
        files.extend(glob(os.path.join(folder, ext)))
    return sorted(files)


def parse_timestamp_ns_from_image_path(image_path):
    if image_path is None:
        return None
    stem = os.path.splitext(os.path.basename(image_path))[0]
    if stem.isdigit():
        return int(stem)
    return None


def _float_or_none(s):
    if s is None or (isinstance(s, str) and s.strip().lower() in ("", "none")):
        return None
    return float(s)


def _normalize_overwrite_prompt(prompt) -> str:
    if prompt is None:
        return ""
    return str(prompt).strip()


def _validate_bucket(w: int, h: int) -> Bucket:
    if w <= 0 or h <= 0:
        raise ValueError(f"Invalid bucket {w}x{h}, width/height must be > 0")
    if (w % 8) != 0 or (h % 8) != 0:
        raise ValueError(f"Invalid bucket {w}x{h}, width/height must be divisible by 8")
    return Bucket(height=h, width=w)


def build_buckets_from_train_config(train_cfg: dict) -> List[Bucket]:
    if train_cfg.get("enable_dual_resolution_bucket", False):
        b1 = _validate_bucket(
            int(train_cfg.get("bucket_16_9_width", 1024)),
            int(train_cfg.get("bucket_16_9_height", 576)),
        )
        b2 = _validate_bucket(
            int(train_cfg.get("bucket_5_4_width", 960)),
            int(train_cfg.get("bucket_5_4_height", 768)),
        )
        if b1 == b2:
            return [b1]
        return [b1, b2]
    return [
        _validate_bucket(
            int(train_cfg.get("image_width", 1024)),
            int(train_cfg.get("image_height", 576)),
        )
    ]


def build_bucket_camera_map_from_train_config(train_cfg: dict) -> Dict[str, List[str]]:
    if train_cfg.get("enable_dual_resolution_bucket", False):
        bucket_16_9 = _validate_bucket(
            int(train_cfg.get("bucket_16_9_width", 1024)),
            int(train_cfg.get("bucket_16_9_height", 576)),
        )
        bucket_5_4 = _validate_bucket(
            int(train_cfg.get("bucket_5_4_width", 960)),
            int(train_cfg.get("bucket_5_4_height", 768)),
        )
        bucket_camera_map: Dict[str, List[str]] = {
            bucket_16_9.tag: list(CAMERA_GROUPS["bucket_16_9"])
        }
        if bucket_5_4.tag == bucket_16_9.tag:
            bucket_camera_map[bucket_16_9.tag].extend(CAMERA_GROUPS["bucket_5_4"])
        else:
            bucket_camera_map[bucket_5_4.tag] = list(CAMERA_GROUPS["bucket_5_4"])
        return bucket_camera_map

    single_bucket = _validate_bucket(
        int(train_cfg.get("image_width", 1024)),
        int(train_cfg.get("image_height", 576)),
    )
    all_cameras = list(CAMERA_GROUPS["bucket_16_9"]) + list(CAMERA_GROUPS["bucket_5_4"])
    return {single_bucket.tag: all_cameras}


def build_camera_bucket_map(bucket_camera_map: Dict[str, List[str]]) -> Dict[str, str]:
    camera_bucket_map: Dict[str, str] = {}
    for bucket_tag, camera_names in bucket_camera_map.items():
        for camera_name in camera_names:
            camera_bucket_map[str(camera_name).lower()] = bucket_tag
    return camera_bucket_map


def load_infer_config(train_cfg: dict) -> dict:
    return {
        "image_height": train_cfg.get("image_height", 576),
        "image_width": train_cfg.get("image_width", 1024),
        "timestep": int(train_cfg.get("timestep", 199)),
        "overwrite_prompt": train_cfg.get("overwrite_prompt", None),
        "enable_dual_resolution_bucket": train_cfg.get("enable_dual_resolution_bucket", False),
        "bucket_16_9_height": train_cfg.get("bucket_16_9_height", 576),
        "bucket_16_9_width": train_cfg.get("bucket_16_9_width", 1024),
        "bucket_5_4_height": train_cfg.get("bucket_5_4_height", 768),
        "bucket_5_4_width": train_cfg.get("bucket_5_4_width", 960),
    }


def load_vae_scaling_factor(pretrained_path: str) -> float:
    vae_cfg_path = Path(pretrained_path) / "vae" / "config.json"
    if not vae_cfg_path.exists():
        raise FileNotFoundError(f"VAE config not found: {vae_cfg_path}")
    with open(vae_cfg_path, "r") as f:
        vae_cfg = json.load(f)
    return float(vae_cfg.get("scaling_factor", 0.18215))


def _ensure_extracted_wheel(wheel_path: Path) -> Path:
    extract_dir = TENSORRT_PYTHON_CACHE_DIR / wheel_path.stem
    complete_flag = extract_dir / ".extract_complete"
    if not complete_flag.exists():
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(wheel_path, "r") as zf:
            zf.extractall(extract_dir)
        complete_flag.write_text("ok")
    return extract_dir


def configure_tensorrt_runtime():
    if not TENSORRT_ROOT.exists():
        raise FileNotFoundError(f"TensorRT root not found: {TENSORRT_ROOT}")

    if TENSORRT_LIB_DIR.is_dir():
        trt_lib_dir = str(TENSORRT_LIB_DIR)
        ld_library_path = os.environ.get("LD_LIBRARY_PATH", "")
        ld_parts = [item for item in ld_library_path.split(":") if item]
        if trt_lib_dir not in ld_parts:
            os.environ["LD_LIBRARY_PATH"] = (
                f"{trt_lib_dir}:{ld_library_path}" if ld_library_path else trt_lib_dir
            )

        preload_patterns = [
            "libnvinfer.so",
            "libnvinfer_plugin.so",
            "libnvonnxparser.so",
            "libnvinfer_dispatch.so",
            "libnvinfer_lean.so",
            "libnvinfer_vc_plugin.so",
            "libtensorrt_shim.so",
            "libnvinfer_builder_resource.so*",
        ]
        for pattern in preload_patterns:
            matches = sorted(TENSORRT_LIB_DIR.glob(pattern))
            if matches:
                ctypes.CDLL(str(matches[0]), mode=ctypes.RTLD_GLOBAL)

    python_tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
    wheel_patterns = [
        f"tensorrt_dispatch-10.13.3.9-{python_tag}-none-linux_x86_64.whl",
        f"tensorrt_lean-10.13.3.9-{python_tag}-none-linux_x86_64.whl",
        f"tensorrt-10.13.3.9-{python_tag}-none-linux_x86_64.whl",
    ]
    matched_wheels = []
    for pattern in wheel_patterns:
        matched_wheels.extend(sorted(TENSORRT_PYTHON_DIR.glob(pattern)))

    if not matched_wheels:
        raise FileNotFoundError(
            f"No TensorRT Python wheel found for Python {python_tag} in {TENSORRT_PYTHON_DIR}"
        )

    for wheel_path in matched_wheels:
        extracted_dir = _ensure_extracted_wheel(wheel_path)
        extracted_dir_str = str(extracted_dir)
        if extracted_dir_str not in sys.path:
            sys.path.insert(0, extracted_dir_str)


configure_tensorrt_runtime()


class TensorRTEngine:
    def __init__(self, engine_path: str):
        try:
            import tensorrt as trt  # type: ignore[import-not-found]
        except ImportError as e:
            raise ImportError("TensorRT Python package is required to run inference_trt.py") from e

        self.trt = trt
        self.engine_path = engine_path
        self.logger = trt.Logger(trt.Logger.ERROR)
        trt.init_libnvinfer_plugins(self.logger, "")
        self.runtime = trt.Runtime(self.logger)
        with open(engine_path, "rb") as f:
            self.engine = self.runtime.deserialize_cuda_engine(f.read())
        if self.engine is None:
            raise RuntimeError(f"Failed to deserialize TensorRT engine: {engine_path}")
        self.context = self.engine.create_execution_context()
        if self.context is None:
            raise RuntimeError(f"Failed to create TensorRT execution context: {engine_path}")
        self._tensor_name_to_index: Dict[str, int] = {}
        self._input_tensor_names: List[str] = []
        self._output_tensor_names: List[str] = []
        self._last_tensor_refs: Dict[str, torch.Tensor] = {}
        for i in range(self.engine.num_io_tensors):
            name = self.engine.get_tensor_name(i)
            self._tensor_name_to_index[name] = i
            if self.engine.get_tensor_mode(name) == trt.TensorIOMode.INPUT:
                self._input_tensor_names.append(name)
            else:
                self._output_tensor_names.append(name)

    def get_binding_dtype(self, name: str) -> torch.dtype:
        return self._trt_dtype_to_torch(self.engine.get_tensor_dtype(name))

    def infer(self, feeds: Dict[str, torch.Tensor]) -> Dict[str, torch.Tensor]:
        device = torch.device("cuda")
        tensor_refs: Dict[str, torch.Tensor] = {}
        stream_handle = torch.cuda.current_stream().cuda_stream
        input_meta = {}

        for name, tensor in feeds.items():
            if name not in self._tensor_name_to_index:
                raise KeyError(f"Input binding not found in {self.engine_path}: {name}")
            tensor = tensor.contiguous()
            if tensor.device.type != "cuda":
                tensor = tensor.to(device=device)
            engine_shape = tuple(self.engine.get_tensor_shape(name))
            if -1 in engine_shape:
                self.context.set_input_shape(name, tuple(tensor.shape))
            self.context.set_tensor_address(name, int(tensor.data_ptr()))
            tensor_refs[name] = tensor
            input_meta[name] = {
                "shape": tuple(tensor.shape),
                "dtype": str(tensor.dtype),
                "device": str(tensor.device),
            }

        outputs: Dict[str, torch.Tensor] = {}
        for name in self._output_tensor_names:
            shape = tuple(self.context.get_tensor_shape(name))
            dtype = self._trt_dtype_to_torch(self.engine.get_tensor_dtype(name))
            if any(dim < 0 for dim in shape):
                raise RuntimeError(
                    f"Failed to resolve output shape for {name}: {shape}"
                )
            out = torch.empty(
                shape,
                device=device,
                dtype=dtype,
            )
            outputs[name] = out
            tensor_refs[name] = out
            self.context.set_tensor_address(name, int(out.data_ptr()))

        ok = self.context.execute_async_v3(stream_handle=stream_handle)
        if not ok:
            free_mem_mb = None
            total_mem_mb = None
            sync_error = None
            if torch.cuda.is_available():
                free_mem, total_mem = torch.cuda.mem_get_info()
                free_mem_mb = free_mem / (1024 ** 2)
                total_mem_mb = total_mem / (1024 ** 2)
                try:
                    torch.cuda.synchronize()
                except Exception as e:
                    sync_error = repr(e)
            raise RuntimeError(
                "TensorRT execute_async_v3 failed: "
                f"{self.engine_path}, inputs={input_meta}, "
                f"cuda_free_mem_mb={free_mem_mb}, cuda_total_mem_mb={total_mem_mb}, "
                f"sync_error={sync_error}"
            )
        self._last_tensor_refs = tensor_refs
        return outputs

    def _trt_dtype_to_torch(self, trt_dtype):
        trt = self.trt
        mapping = {
            trt.float32: torch.float32,
            trt.float16: torch.float16,
            trt.int32: torch.int32,
            trt.int8: torch.int8,
            trt.bool: torch.bool,
        }
        if trt_dtype not in mapping:
            raise TypeError(f"Unsupported TensorRT dtype: {trt_dtype}")
        return mapping[trt_dtype]


class DifixTensorRT:
    def __init__(self, ckpt_path: str, train_config_path: str, pretrained_path: str, trt_root: Optional[str] = None):
        self.ckpt_path = ckpt_path
        self.train_cfg = load_train_config(train_config_path)
        if not isinstance(self.train_cfg, dict):
            raise ValueError(f"Invalid train_config yaml: {train_config_path}")
        self.config = load_infer_config(self.train_cfg)
        self.buckets = build_buckets_from_train_config(self.train_cfg)
        self.bucket_camera_map = build_bucket_camera_map_from_train_config(self.train_cfg)
        self.camera_bucket_map = build_camera_bucket_map(self.bucket_camera_map)
        self.pretrained_path = pretrained_path
        self.trt_root = trt_root or os.path.join(ckpt_path, "vae_onnx_trt")
        self.scaling_factor = load_vae_scaling_factor(pretrained_path)
        self.timesteps = torch.tensor([int(self.config["timestep"])], device="cuda").long()
        self.overwrite_prompt = _normalize_overwrite_prompt(self.train_cfg.get("overwrite_prompt", None))
        self.share_unet_engine = self.overwrite_prompt != ""

        self.scheduler = DDPMScheduler.from_pretrained(
            pretrained_path,
            subfolder="scheduler",
            local_files_only=True,
        )
        self.scheduler.set_timesteps(1, device="cuda")
        self.scheduler.alphas_cumprod = self.scheduler.alphas_cumprod.cuda()

        self._encoder_engines: Dict[str, TensorRTEngine] = {}
        self._decoder_engines: Dict[str, TensorRTEngine] = {}
        self._unet_engines: Dict[Tuple[str, str], TensorRTEngine] = {}
        print(
            f"[TRT] UNet engine mode: "
            f"{'shared_per_bucket' if self.share_unet_engine else 'per_camera'}",
            flush=True,
        )

    def _bucket_for_camera(self, camera_name: str) -> Bucket:
        bucket_tag = self.camera_bucket_map.get(str(camera_name).lower())
        if bucket_tag is None:
            raise ValueError(
                f"Camera {camera_name} is not configured in bucket map: {self.bucket_camera_map}"
            )
        for bucket in self.buckets:
            if bucket.tag == bucket_tag:
                return bucket
        raise ValueError(f"Bucket tag {bucket_tag} not found in buckets={self.buckets}")

    def _engine_dir(self, bucket: Bucket) -> str:
        return os.path.join(self.trt_root, f"bucket_{bucket.tag}")

    def _load_bucket_engines(self, bucket: Bucket):
        if bucket.tag not in self._encoder_engines:
            bucket_dir = self._engine_dir(bucket)
            enc_path = os.path.join(bucket_dir, "vae_encoder.engine")
            dec_path = os.path.join(bucket_dir, "vae_decoder.engine")
            if not os.path.isfile(enc_path):
                raise FileNotFoundError(f"VAE encoder engine not found: {enc_path}")
            if not os.path.isfile(dec_path):
                raise FileNotFoundError(f"VAE decoder engine not found: {dec_path}")
            self._encoder_engines[bucket.tag] = TensorRTEngine(enc_path)
            self._decoder_engines[bucket.tag] = TensorRTEngine(dec_path)

    def _load_unet_engine(self, bucket: Bucket, camera_name: str):
        bucket_dir = self._engine_dir(bucket)
        camera_name_lower = camera_name.lower()
        shared_unet_path = os.path.join(bucket_dir, "unet.engine")
        camera_unet_path = os.path.join(bucket_dir, f"unet_{camera_name_lower}.engine")

        if self.share_unet_engine:
            preferred_paths = [shared_unet_path, camera_unet_path]
            cache_key = (bucket.tag, "__shared__")
        else:
            preferred_paths = [camera_unet_path, shared_unet_path]
            cache_key = (bucket.tag, camera_name_lower)

        if cache_key not in self._unet_engines:
            unet_path = None
            for p in preferred_paths:
                if os.path.isfile(p):
                    unet_path = p
                    break
            if unet_path is None:
                raise FileNotFoundError(
                    f"UNet engine not found for bucket={bucket.tag}, camera={camera_name}. "
                    f"Tried: {preferred_paths}"
                )
            self._unet_engines[cache_key] = TensorRTEngine(unet_path)
        return self._unet_engines[cache_key]

    def _sample_posterior(self, moments: torch.Tensor) -> torch.Tensor:
        mean, logvar = torch.chunk(moments, 2, dim=1)
        logvar = torch.clamp(logvar, -30.0, 20.0)
        std = torch.exp(0.5 * logvar)
        return mean + std * torch.randn_like(mean)

    @staticmethod
    def _sync_cuda():
        if torch.cuda.is_available():
            torch.cuda.synchronize()

    def sample_xpeng(
        self,
        image_tensor: torch.Tensor,
        camera_name: str,
        ref_image: torch.Tensor,
        profile: bool = False,
    ):
        bucket = self._bucket_for_camera(camera_name)
        self._load_bucket_engines(bucket)
        unet_engine = self._load_unet_engine(bucket, camera_name)
        enc_engine = self._encoder_engines[bucket.tag]
        dec_engine = self._decoder_engines[bucket.tag]

        _, input_height, input_width = image_tensor.shape
        sample_profile = {}
        if profile:
            self._sync_cuda()
            t_sample_start = time.perf_counter()
            t_pre_start = time.perf_counter()

        model_dtype = enc_engine.get_binding_dtype("image")
        img_float = image_tensor.float() / 255.0
        x_main = F.resize(img_float, (bucket.height, bucket.width), interpolation=F.InterpolationMode.BICUBIC)
        x_main = ((x_main - 0.5) / 0.5).unsqueeze(0).to(device="cuda", dtype=model_dtype)

        if ref_image is None:
            raise ValueError("ref_image is required for TensorRT inference.")

        ref_float = ref_image.float() / 255.0
        ref_tensor = F.resize(ref_float, (bucket.height, bucket.width), interpolation=F.InterpolationMode.BICUBIC)
        ref_tensor = ((ref_tensor - 0.5) / 0.5).unsqueeze(0).to(device="cuda", dtype=model_dtype)
        x = torch.cat([x_main, ref_tensor], dim=0).contiguous()

        if profile:
            self._sync_cuda()
            sample_profile["preprocess_ms"] = (time.perf_counter() - t_pre_start) * 1000.0

        with torch.inference_mode():
            if profile:
                self._sync_cuda()
                t_vae_encode_start = time.perf_counter()
            enc_out = enc_engine.infer({"image": x})
            if profile:
                self._sync_cuda()
                sample_profile["vae_encode_ms"] = (time.perf_counter() - t_vae_encode_start) * 1000.0

            moments = enc_out["moments"]
            skip0 = enc_out["skip0"]
            skip1 = enc_out["skip1"]
            skip2 = enc_out["skip2"]
            skip3 = enc_out["skip3"]

            z = self._sample_posterior(moments) * self.scaling_factor

            if profile:
                self._sync_cuda()
                t_unet_start = time.perf_counter()
            model_pred = unet_engine.infer({"latent": z})["sample"]
            if profile:
                self._sync_cuda()
                sample_profile["unet_ms"] = (time.perf_counter() - t_unet_start) * 1000.0

            if profile:
                self._sync_cuda()
                t_scheduler_start = time.perf_counter()
            z_denoised = self.scheduler.step(
                model_pred.float(),
                self.timesteps,
                z.float(),
                return_dict=True,
            ).prev_sample
            if profile:
                self._sync_cuda()
                sample_profile["scheduler_ms"] = (time.perf_counter() - t_scheduler_start) * 1000.0

            dec_dtype = dec_engine.get_binding_dtype("z")
            # Match model.py decode_ref=False: only decode the target view (index 0),
            # while the reference view is used only to provide encoder/UNet context.
            decode_inputs = {
                "z": (z_denoised[:1] / self.scaling_factor).to(dtype=dec_dtype).contiguous(),
                "skip0": skip0[:1].to(dtype=dec_engine.get_binding_dtype("skip0")).contiguous(),
                "skip1": skip1[:1].to(dtype=dec_engine.get_binding_dtype("skip1")).contiguous(),
                "skip2": skip2[:1].to(dtype=dec_engine.get_binding_dtype("skip2")).contiguous(),
                "skip3": skip3[:1].to(dtype=dec_engine.get_binding_dtype("skip3")).contiguous(),
            }
            if profile:
                self._sync_cuda()
                t_vae_decode_start = time.perf_counter()
            output_image = dec_engine.infer(decode_inputs)["image"].clamp(-1, 1)
            if profile:
                self._sync_cuda()
                sample_profile["vae_decode_ms"] = (time.perf_counter() - t_vae_decode_start) * 1000.0

        if profile:
            self._sync_cuda()
            t_post_start = time.perf_counter()
        img = output_image[0].float() * 0.5 + 0.5
        img = F.resize(img, (input_height, input_width), interpolation=F.InterpolationMode.BICUBIC)
        output_tensor = (img * 255).clamp(0, 255).to(torch.uint8).cpu()
        if profile:
            self._sync_cuda()
            sample_profile["postprocess_ms"] = (time.perf_counter() - t_post_start) * 1000.0
            sample_profile["sample_total_ms"] = (time.perf_counter() - t_sample_start) * 1000.0
            return output_tensor, sample_profile
        return output_tensor


def run_inference_for_clip(
    model: DifixTensorRT,
    config: dict,
    clip_id,
    model_version,
    camera_name,
    input_root,
    gt_root,
    output_root,
    frame_step=2,
    max_frames_per_clip=-1,
    save_video=True,
    save_images=False,
    ref_image_mode=None,
    profile=False,
    profile_warmup_frames=1,
):
    input_dir = os.path.join(
        input_root, clip_id, model_version,
        "simulator_render", "redistort_rgb", camera_name,
    )
    gt_dir = os.path.join(
        gt_root, clip_id,
        "images_origin", camera_name,
    )
    if not os.path.isdir(input_dir):
        print(f"[{clip_id}] input dir not found: {input_dir}, skip")
        return None
    if not os.path.isdir(gt_dir):
        print(f"[{clip_id}] gt dir not found: {gt_dir}, skip")
        return None

    input_images = sorted_image_list(input_dir)
    if len(input_images) == 0:
        print(f"[{clip_id}] no images in {input_dir}, skip")
        return None

    indices = list(range(0, len(input_images), max(1, frame_step)))
    if max_frames_per_clip > 0:
        indices = indices[:max_frames_per_clip]
    input_images = [input_images[i] for i in indices]

    gt_images = []
    for p in input_images:
        name = os.path.basename(p)
        gt_path = os.path.join(gt_dir, name)
        gt_images.append(gt_path if os.path.exists(gt_path) else None)
    gt_timestamps_ns = [parse_timestamp_ns_from_image_path(p) for p in gt_images]

    os.makedirs(output_root, exist_ok=True)
    clip_out_dir = os.path.join(output_root, f"{clip_id}_{camera_name}")
    os.makedirs(clip_out_dir, exist_ok=True)

    output_images = []
    input_images_rgb = []
    gt_images_rgb = []
    psnr_results = []
    profile_results = []
    infer_call_count = 0

    for i, (inp_path, gt_path) in enumerate(
        tqdm(list(zip(input_images, gt_images)), desc=f"[{clip_id}] {camera_name}")
    ):
        if gt_path is None:
            continue

        gt_img = Image.open(gt_path).convert("RGB")
        in_img = Image.open(inp_path).convert("RGB")
        input_images_rgb.append(in_img)
        gt_images_rgb.append(gt_img)

        if ref_image_mode is None:
            raise ValueError("ref_image_mode is required for TensorRT inference.")
        if abs(ref_image_mode) < 1e-6:
            ref_img = gt_img
        else:
            window_ns = int(float(ref_image_mode) * 1e9)
            cur_ts_ns = gt_timestamps_ns[i]
            candidates = [
                idx
                for idx, p in enumerate(gt_images)
                if (
                    p is not None
                    and idx != i
                    and cur_ts_ns is not None
                    and gt_timestamps_ns[idx] is not None
                    and abs(gt_timestamps_ns[idx] - cur_ts_ns) <= window_ns
                )
            ]
            if not candidates:
                raise ValueError(
                    f"[{clip_id}] no ref image found for {camera_name} frame={inp_path} "
                    f"within {float(ref_image_mode):.3f}s window."
                )
            ref_img = Image.open(gt_images[random.choice(candidates)]).convert("RGB")

        in_tensor = torch.from_numpy(np.array(in_img)).permute(2, 0, 1).contiguous()
        ref_tensor = torch.from_numpy(np.array(ref_img)).permute(2, 0, 1).contiguous()

        frame_profile = None
        if profile and infer_call_count >= max(0, profile_warmup_frames):
            out_tensor, frame_profile = model.sample_xpeng(
                in_tensor,
                camera_name=camera_name,
                ref_image=ref_tensor,
                profile=True,
            )
            profile_results.append(frame_profile)
        else:
            out_tensor = model.sample_xpeng(
                in_tensor,
                camera_name=camera_name,
                ref_image=ref_tensor,
                profile=False,
            )
        infer_call_count += 1

        out_img = Image.fromarray(out_tensor.permute(1, 2, 0).numpy())
        output_images.append(out_img)

        psnr_value = calculate_psnr(out_img, gt_img)
        psnr_input = calculate_psnr(in_img, gt_img)
        rec = {
            "frame_index": i,
            "clip_id": clip_id,
            "camera_name": camera_name,
            "input_image": inp_path,
            "gt_image": gt_path,
            "output_image": os.path.join(clip_out_dir, os.path.basename(inp_path)),
            "psnr": float(psnr_value),
            "psnr_input": float(psnr_input),
            "delta_psnr": float(psnr_value - psnr_input),
        }
        if frame_profile is not None:
            rec["profile_ms"] = frame_profile
        psnr_results.append(rec)

    if save_images:
        for rec, out_img in zip(psnr_results, output_images):
            out_img.save(rec["output_image"])

    if save_video and len(output_images) > 0:
        for name, imgs in [
            ("output.mp4", output_images),
            ("input.mp4", input_images_rgb[: len(output_images)]),
            ("gt.mp4", gt_images_rgb[: len(output_images)]),
        ]:
            writer = imageio.get_writer(os.path.join(clip_out_dir, name), fps=6)
            for img in imgs:
                writer.append_data(np.array(img))
            writer.close()

    if len(psnr_results) == 0:
        return None

    psnrs = [r["psnr"] for r in psnr_results]
    psnrs_in = [r["psnr_input"] for r in psnr_results]
    report = {
        "clip_id": clip_id,
        "camera_name": camera_name,
        "model_version": model_version,
        "num_frames": len(psnr_results),
        "mean_psnr": float(np.mean(psnrs)),
        "mean_psnr_input": float(np.mean(psnrs_in)),
        "delta_psnr": float(np.mean(psnrs) - np.mean(psnrs_in)),
        "per_frame": psnr_results,
    }
    if profile and len(profile_results) > 0:
        mean_profile_ms = {
            k: float(np.mean([x[k] for x in profile_results if k in x]))
            for k in profile_results[0].keys()
        }
        total_ms = mean_profile_ms.get("sample_total_ms", 0.0)
        profile_ratio = {}
        if total_ms > 0:
            profile_ratio = {
                k: float(v / total_ms)
                for k, v in mean_profile_ms.items()
                if k != "sample_total_ms"
            }
        report["profile_summary"] = {
            "profile_warmup_frames": int(max(0, profile_warmup_frames)),
            "num_profiled_frames": int(len(profile_results)),
            "mean_profile_ms": mean_profile_ms,
            "mean_profile_ratio": profile_ratio,
        }
    with open(os.path.join(clip_out_dir, "psnr_report.json"), "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--train_data_json",
        type=str,
        default="/workspace/yangxh7@xiaopeng.com/codes/3dgs/models/difix/utils/eval_data_v1_0301/train_data_parts/train_data_part_0.json",
        help="Path to eval clip json",
    )
    parser.add_argument(
        "--ckpt_path",
        type=str,
        required=True,
        help="Checkpoint directory that contains train_config.yaml and vae_onnx_trt/",
    )
    parser.add_argument(
        "--pretrained_path",
        type=str,
        default=DEFAULT_PRETRAINED_PATH,
        help="Pretrained Difix pipeline path used to load scheduler and VAE config.",
    )
    parser.add_argument(
        "--trt_root",
        type=str,
        default="",
        help="Directory that contains bucket_*/ TensorRT engines. Defaults to ckpt_path/vae_onnx_trt.",
    )
    parser.add_argument(
        "--camera_names",
        type=str,
        nargs="+",
        default=["cam0", "cam2", "cam3", "cam4", "cam5", "cam6", "cam7"],
        help="Camera names, e.g. cam0 cam2 cam3 ...",
    )
    parser.add_argument("--frame_step", type=int, default=2, help="Use every N-th frame after sorting (>=1)")
    parser.add_argument("--max_frames_per_clip", type=int, default=-1, help="Max frames per clip (-1 for no limit)")
    parser.add_argument(
        "--input_root",
        type=str,
        default="/workspace/group_share/adc-sim/users/cloudsim/difix/train_data",
        help="Root of simulator_render images",
    )
    parser.add_argument(
        "--gt_root",
        type=str,
        default="/workspace/group_share/adc-sim/users/cloudsim/images_origin",
        help="Root of ground-truth images",
    )
    parser.add_argument("--save_images", action="store_true", help="Save per-frame output images")
    parser.add_argument(
        "--ref_image_mode",
        type=_float_or_none,
        default=0,
        help=(
            "Ref image mode: 0=当前帧GT作为ref；"
            "N>0=在当前clip内前后N秒时间窗口内随机选一帧GT作为ref。"
        ),
    )
    parser.add_argument("--profile", action="store_true", help="Profile TensorRT sampling pipeline.")
    parser.add_argument("--profile_warmup_frames", type=int, default=2, help="Warmup frames excluded from profile.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed used for latent sampling.")
    args = parser.parse_args()
    if args.ref_image_mode is None:
        raise ValueError("--ref_image_mode is required and must be 0 or >0.")

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)

    with open(args.train_data_json, "r") as f:
        train_data = json.load(f)

    train_config_path = os.path.join(args.ckpt_path, "train_config.yaml")
    if not os.path.isfile(train_config_path):
        raise FileNotFoundError(f"train_config.yaml not found: {train_config_path}")
    train_cfg = load_train_config(train_config_path)
    config = load_infer_config(train_cfg)
    if config.get("overwrite_prompt", None):
        print(
            "[PROMPT] overwrite_prompt is set in train config. "
            "TensorRT UNet uses fixed prompt embeddings baked into engines; "
            "please ensure exported TRT engines were built with this overwrite prompt.",
            flush=True,
        )
        print(f"[PROMPT] overwrite_prompt={config['overwrite_prompt']}", flush=True)

    model = DifixTensorRT(
        ckpt_path=args.ckpt_path,
        train_config_path=train_config_path,
        pretrained_path=args.pretrained_path,
        trt_root=(args.trt_root or None),
    )

    output_root = args.ckpt_path.replace("checkpoints_", "inference_trt_")
    if args.ref_image_mode is not None:
        output_root = output_root + f"_{args.ref_image_mode}"
    os.makedirs(output_root, exist_ok=True)

    for item in train_data:
        clip_id = item["clip_id"]
        model_version = item.get("model_version", "")
        if not item.get("images_origin_exist_in_oss", True):
            print(f"[{clip_id}] images_origin_exist_in_oss is False, skip")
            continue

        clip_cam_reports = []
        for cam in args.camera_names:
            clip_cam_report = run_inference_for_clip(
                model=model,
                config=config,
                clip_id=clip_id,
                model_version=model_version,
                camera_name=cam,
                input_root=args.input_root,
                gt_root=args.gt_root,
                output_root=output_root,
                frame_step=args.frame_step,
                max_frames_per_clip=args.max_frames_per_clip,
                save_video=True,
                save_images=args.save_images,
                ref_image_mode=args.ref_image_mode,
                profile=args.profile,
                profile_warmup_frames=args.profile_warmup_frames,
            )
            if clip_cam_report is not None:
                clip_cam_reports.append(clip_cam_report)

        mean_psnr_over_cams = float(np.mean([r["mean_psnr"] for r in clip_cam_reports])) if clip_cam_reports else None
        mean_psnr_input_over_cams = (
            float(np.mean([r["mean_psnr_input"] for r in clip_cam_reports])) if clip_cam_reports else None
        )
        clip_report = {
            "clip_id": clip_id,
            "camera_names": args.camera_names,
            "overwrite_prompt": config.get("overwrite_prompt", None),
            "mean_psnr": mean_psnr_over_cams,
            "mean_psnr_input": mean_psnr_input_over_cams,
            "clip_cam_reports": clip_cam_reports,
        }
        with open(os.path.join(output_root, f"{clip_id}.json"), "w") as f:
            json.dump(clip_report, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
