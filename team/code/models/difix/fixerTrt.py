import os
import random
import sys
from typing import Optional

import numpy as np
import torch

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
SRC_ROOT = os.path.join(PROJECT_ROOT, "src")
for candidate in (PROJECT_ROOT, SRC_ROOT):
    if candidate not in sys.path:
        sys.path.append(candidate)

try:
    from .src.inference_trt import DEFAULT_PRETRAINED_PATH, DifixTensorRT, configure_tensorrt_runtime
except ImportError:
    from src.inference_trt import DEFAULT_PRETRAINED_PATH, DifixTensorRT, configure_tensorrt_runtime


class DifixTrtFixer:
    def __init__(self, cfg):
        self.config = cfg

        self.seed = self._cfg_get("seed", 42)
        random.seed(self.seed)
        np.random.seed(self.seed)
        torch.manual_seed(self.seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed(self.seed)
            torch.cuda.manual_seed_all(self.seed)

        configure_tensorrt_runtime()

        self.pretrained_path = self._cfg_get("pretrained_path", DEFAULT_PRETRAINED_PATH)
        self.ckpt_path = self._cfg_get("ckpt_path", self._cfg_get("lora_ckpt_path", None))
        if not self.ckpt_path:
            raise ValueError("DifixTrtFixer requires cfg.ckpt_path or cfg.lora_ckpt_path.")

        self.train_config_path = self._cfg_get(
            "train_config",
            f"{self.ckpt_path}/train_config.yaml",
        )
        self.trt_root = self._cfg_get("trt_root", None)
        self.default_camera_name = self._cfg_get("camera_name", "cam0")

        print(f"[DIFIX_TRT] Loading TensorRT engines from {self.trt_root or (self.ckpt_path + '/vae_onnx_trt')}...")
        self.model = DifixTensorRT(
            ckpt_path=self.ckpt_path,
            train_config_path=self.train_config_path,
            pretrained_path=self.pretrained_path,
            trt_root=self.trt_root,
        )

    def _cfg_get(self, key, default=None):
        if isinstance(self.config, dict):
            return self.config.get(key, default)
        return getattr(self.config, key, default)

    def fix_image_xpeng(
        self,
        input_image: torch.Tensor,
        ref_img: Optional[torch.Tensor] = None,
        ref_mask: Optional[torch.Tensor] = None,
        camera_name: Optional[str] = None,
    ) -> torch.Tensor:
        if input_image.dim() != 3:
            raise ValueError(f"Expected input_image to be [C,H,W], got shape {tuple(input_image.shape)}")
        if ref_img is None:
            raise ValueError("DifixTrtFixer.fix_image_xpeng requires ref_img.")
        if ref_img.dim() != 3:
            raise ValueError(f"Expected ref_img to be [C,H,W], got shape {tuple(ref_img.shape)}")
        if ref_mask is not None:
            # TRT 引擎已固定计算图, 不支持运行时 ref_mask 屏蔽; 仅打印一次告警.
            if not getattr(self, "_warned_ref_mask_unsupported", False):
                print("[DifixTrtFixer] WARNING: ref_mask is not supported in TRT path; ignored.", flush=True)
                self._warned_ref_mask_unsupported = True

        resolved_camera_name = (camera_name or self.default_camera_name).lower()
        output_tensor = self.model.sample_xpeng(
            image_tensor=input_image,
            camera_name=resolved_camera_name,
            ref_image=ref_img,
            profile=False,
        )
        return output_tensor.to(input_image.device)
