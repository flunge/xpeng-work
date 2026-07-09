import os
import sys
import numpy as np
import torch
import random
from PIL import Image

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from .src.pipeline_difix import DifixPipeline
from typing import Optional

torch._inductor.config.conv_1x1_as_mm = True
torch._inductor.config.coordinate_descent_tuning = True
torch._inductor.config.epilogue_fusion = False
torch._inductor.config.coordinate_descent_check_all_directions = True

from .src.model import Difix, load_ckpt_from_state_dict
from .src.config_train import load_config as load_yaml_config


class DifixFixer:
    def __init__(self, cfg):
        self.config = cfg

        self.seed = getattr(self.config, "seed", 42)
        random.seed(self.seed)
        np.random.seed(self.seed)
        torch.manual_seed(self.seed)
        torch.cuda.manual_seed(self.seed)
        torch.cuda.manual_seed_all(self.seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False

        print(f"[DIFIX] Loading Difix model from {self.config.pretrained_path}...")
        pipe = DifixPipeline.from_pretrained(
            self.config.pretrained_path,
            torch_dtype=torch.bfloat16,
            # trust_remote_code=True,
            local_files_only=True,
        )
        pipe.to("cuda")

        model = None
        lora_ckpt_path = getattr(self.config, "lora_ckpt_path", None)
        self.config["difix_train_config"] = {}
        if lora_ckpt_path is not None and os.path.exists(lora_ckpt_path):
            try:
                print(f"[DIFIX] Loading pretrained model from {lora_ckpt_path}...")
                # 读 ckpt 目录下的训练配置 train_config.yaml
                train_config_yaml = os.path.join(lora_ckpt_path, "train_config.yaml")
                train_config = load_yaml_config(train_config_yaml)
                model = Difix(
                    pipe=pipe,
                    timestep=train_config["timestep"],
                    lora_rank_vae=train_config["lora_rank_vae"],
                )
                model, _, _ = load_ckpt_from_state_dict(model, os.path.join(lora_ckpt_path, "model.pkl"))
                default_height, default_width = train_config["image_height"], train_config["image_width"]
                self.config["difix_train_config"] = train_config
            except Exception as e:
                print(f"Error loading model checkpoint from {lora_ckpt_path}: {e}")
        else:
            print(f"[DIFIX] No fine-tuned model loaded, using default model...")
        
        if model is None:
            model = Difix(
                pipe=pipe,
                timestep=199,
                lora_rank_vae=4,
            )
            default_height, default_width = 576, 1024
            
        model.to("cuda", dtype=torch.bfloat16)
        model.set_eval()
        # self._warmup_inference_compile(model)
        self.model = model
        self.default_height = default_height
        self.default_width = default_width
        self.prompt = getattr(self.config, "prompt", "Corrected rendering distortion for CAM0 camera view.")

    def _cfg_get(self, key, default=None):
        if isinstance(self.config["difix_train_config"], dict):
            return self.config["difix_train_config"].get(key, default)
        return getattr(self.config["difix_train_config"], key, default)

    def _get_all_bucket_sizes(self):
        if not self._cfg_get("enable_dual_resolution_bucket", False):
            return [(self.default_height, self.default_width)]
        return [
            (
                self._cfg_get("bucket_16_9_height", 576),
                self._cfg_get("bucket_16_9_width", 1024),
            ),
            (
                self._cfg_get("bucket_5_4_height", 768),
                self._cfg_get("bucket_5_4_width", 960),
            ),
        ]

    def _warmup_inference_compile(self, model):
        warmup_on_init = bool(self._cfg_get("warmup_compile_on_init", True))
        enable_infer_optimizations = bool(self._cfg_get("enable_infer_optimizations", True))
        if (not warmup_on_init) or (not enable_infer_optimizations):
            return

        bucket_sizes = self._get_all_bucket_sizes()
        use_ref = bool(self._cfg_get("warmup_use_ref", True))
        camera_names = self._cfg_get("camera_names", ["cam0", "cam2", "cam3", "cam4", "cam5", "cam6", "cam7"])
        print(f"[DIFIX] Warmup compile buckets={bucket_sizes}, use_ref={use_ref}")
        model.warmup_inference_compile_buckets(
            bucket_sizes=bucket_sizes,
            use_ref=use_ref,
            camera_names=camera_names,
            enable_infer_optimizations=enable_infer_optimizations,
        )

    def _get_sample_height_width(self, input_height: int, input_width: int):
        """根据 self.config['difix_train_config'] 与输入宽高，返回推理用的 height, width。"""
        try:
            train_config = self.config["difix_train_config"]
        except (KeyError, TypeError):
            train_config = {}
        if not train_config.get("enable_dual_resolution_bucket", False):
            return self.default_height, self.default_width
        aspect = input_width / max(input_height, 1)
        aspect_16_9 = 16.0 / 9.0
        aspect_5_4 = 5.0 / 4.0
        if abs(aspect - aspect_16_9) <= abs(aspect - aspect_5_4):
            return (
                train_config.get("bucket_16_9_height", 576),
                train_config.get("bucket_16_9_width", 1024),
            )
        return (
            train_config.get("bucket_5_4_height", 768),
            train_config.get("bucket_5_4_width", 960),
        )

    def fix_image(self, input_image: torch.Tensor, reference_image: Optional[torch.Tensor]=None, camera_name: Optional[str]=None):
        prompt = self.prompt
        if camera_name is not None:
            prompt = f"Corrected rendering distortion for {camera_name.upper()} camera view."
        
        if input_image.dim() == 3:
            input_array = input_image.permute(1, 2, 0).cpu().numpy()
            input_pil = Image.fromarray(input_array).convert('RGB')
        else:
            raise ValueError(f"Expected input_image to be [C,H,W], got shape {input_image.shape}")
        
        ref_pil = None
        if reference_image is not None:
            if reference_image.dim() == 3:
                ref_array = reference_image.permute(1, 2, 0).cpu().numpy()
                ref_pil = Image.fromarray(ref_array).convert('RGB')
            else:
                raise ValueError(f"Expected reference_image to be [C,H,W], got shape {reference_image.shape}")

        with torch.no_grad():
            output_pil = self.model.sample(
                image=input_pil,
                width=self.default_width,
                height=self.default_height,
                ref_image=ref_pil,
                prompt=prompt
            )

        output_array = np.array(output_pil)
        output_tensor = torch.from_numpy(output_array).permute(2, 0, 1).to(input_image.device).to(torch.uint8)
        
        return output_tensor

    def fix_image_xpeng(self, input_image: torch.Tensor, ref_img: Optional[torch.Tensor]=None, ref_mask: Optional[torch.Tensor]=None, camera_name: Optional[str]=None):
        """
        Args:
            ref_mask: 可选, [H,W] / [1,H,W] / [1,1,H,W]; >0.5 = 屏蔽 ref 在 attn1 中该位置.
                      仅当 ref_img 不为 None 时生效.
        """
        prompt = self.prompt
        if camera_name is not None:
            prompt = f"Corrected rendering distortion for {camera_name.upper()} camera view."
        
        # 根据训练配置与输入尺寸决定推理宽高（enable_dual_resolution_bucket 时按 16:9 / 5:4 选 bucket）
        h, w = input_image.shape[1], input_image.shape[2]
        height, width = self._get_sample_height_width(h, w)

        with torch.no_grad():
            print(f"[DIFIX] Sampling with width: {width}, height: {height}")
            output_pil_xpeng = self.model.sample_xpeng(
                image_tensor=input_image,
                width=width,
                height=height,
                ref_image=ref_img,
                ref_mask=ref_mask,
                prompt=prompt
            )

        return output_pil_xpeng
