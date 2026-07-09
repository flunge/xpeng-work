#
# Created on Thu Nov 28 2024
#
# Copyright (c) 2024 GigaAI.
#
import logging
import threading
import time
import os
from typing import Dict, Optional, Tuple

import yaml

import numpy as np
import torch
import torch.nn.functional as F
from accelerate import Accelerator
from einops import rearrange
from torch import nn

from ...pipelines.pipeline_difix import DifixPipeline
from ...utils.model_utils import GroundingDINOPipeline, SAMPipeline

logger = logging.getLogger()


def log_worker(stop_event):
    while not stop_event.is_set():
        logger.info("Waiting for generative model pipeline!")
        time.sleep(10)
    logger.info("Log worker quit!")


class DifixModel(nn.Module):
    def __init__(
        self,
        base_model_id: str,
        num_condition: int = 1,
        training_batch_size: int = 4,
        inference_batch_size: int = 4,
        training_learning_rate: float = 5e-5,
        max_norm: Optional[float] = 1.0,
        random_flip_prob: float = 0.5,
        num_inference_steps: int = 20,
        image_guidance_scale: float = -1,
        guidance_scale: float = -1,
        condition_dropout_prob: float = 0.05,
        mixed_precision: str = "bf16",
        pretrained_unet_weights: Optional[str] = None,
        groundingdino_model_id: Optional[str] = None,
        sam_model_id: Optional[str] = None,
        use_8bit_optimizer: bool = False,
        dst_size: Optional[Tuple[int, int]] = None,
        generate_sky_mask: Optional[bool] = False,
        ckpt_path: Optional[str] = None,
        train_config: Optional[str] =  None,
    ):
        super().__init__()
        if mixed_precision == "fp16":
            weight_dtype = torch.float16
        elif mixed_precision == "bf16":
            weight_dtype = torch.bfloat16
        else:
            raise ValueError(f"unsupport mixed_precision {mixed_precision}")
        self.accelerator = Accelerator(mixed_precision=mixed_precision)
        self.device = self.accelerator.device
        self.base_model_id = base_model_id
        self.training_batch_size = training_batch_size
        self.inference_batch_size = inference_batch_size
        self.generate_sky_mask = generate_sky_mask

        if self.generate_sky_mask:
            self.groundingdino_pipe = GroundingDINOPipeline(
                groundingdino_model_id, self.accelerator.device, lazy_mode=False
            )
            self.sam_pipe = SAMPipeline(sam_model_id, self.accelerator.device, lazy_mode=False)

        self.pipe = None

        self.weight_dtype = weight_dtype
        self.dst_size = dst_size
        if dst_size == "None":
            self.dst_size = None

        self.image_guidance_scale = image_guidance_scale
        self.guidance_scale = guidance_scale

        self.guidance_scale = 0.0
        self.num_inference_steps = 1
        self.ckpt_path = ckpt_path
        self.enable_dual_resolution_bucket = False
        # Load train config YAML for timestep and resolution bucket settings
        if train_config is not None:
            train_cfg = self._load_train_config(train_config)
            self.timestep: int = train_cfg.get("timestep", 199)
            self.image_height: int = train_cfg.get("image_height", 576)
            self.image_width: int = train_cfg.get("image_width", 1024)
            self.enable_dual_resolution_bucket: bool = train_cfg.get("enable_dual_resolution_bucket", False)
            self.bucket_16_9_height: int = train_cfg.get("bucket_16_9_height", 576)
            self.bucket_16_9_width: int = train_cfg.get("bucket_16_9_width", 1024)
            self.bucket_5_4_height: int = train_cfg.get("bucket_5_4_height", 768)
            self.bucket_5_4_width: int = train_cfg.get("bucket_5_4_width", 960)

    @staticmethod
    def _load_train_config(train_config: Optional[str]) -> Dict:
        """Load training YAML config. Returns empty dict if path is None or file is missing."""
        if not train_config:
            return {}
        try:
            with open(train_config, "r") as f:
                cfg = yaml.safe_load(f)
            return cfg if isinstance(cfg, dict) else {}
        except Exception as e:
            logger.warning(f"Failed to load train_config '{train_config}': {e}. Using defaults.")
            return {}

    def _get_sample_height_width(self, input_width: int, input_height: int) -> Tuple[int, int]:
        """Return inference (height, width) for an image; selects dual-resolution bucket when enabled."""
        if not self.enable_dual_resolution_bucket:
            return self.image_height, self.image_width
        aspect = input_width / max(input_height, 1)
        aspect_16_9 = 16.0 / 9.0
        aspect_5_4 = 5.0 / 4.0
        if abs(aspect - aspect_16_9) <= abs(aspect - aspect_5_4):
            return self.bucket_16_9_height, self.bucket_16_9_width
        return self.bucket_5_4_height, self.bucket_5_4_width

    def modify_infer_batch_size(self, batch_size):
        self.inference_batch_size = batch_size

    def training_forward(self, batch):
        raise NotImplementedError("DifixModel does not support training")

    def inference_forward(self, batch_data, ref_data, masks, infos, indexes, prompts, ori_sizes):
        if self.pipe is None:
            self._get_pipe()
        result_list = []
        with torch.no_grad(), torch.autocast(self.accelerator.device.type):
            batch_data = batch_data.to(self.weight_dtype)
            ref_data = ref_data.to(self.weight_dtype)
            novel_view_data = []
            for i in range(len(batch_data)):
                novel_view_data.append(
                    self.pipe(
                        prompts[i : i + 1],
                        image=batch_data[i : i + 1],
                        ref_image=ref_data[i : i + 1],
                        num_inference_steps=self.num_inference_steps,
                        timesteps=[199] if not hasattr(self, 'timestep') else [self.timestep],
                        guidance_scale=self.guidance_scale,
                        decode_ref=False,
                        use_channels_last=True,
                        use_text_cache=True,
                    ).images[0]
                )
            assert len(novel_view_data) == len(infos)
            for degarded_image, novel_image, mask, info, index, ori_size in zip(
                batch_data, novel_view_data, masks, infos, indexes, ori_sizes
            ):
                novel_image = torch.from_numpy(np.array(novel_image)).float().to(self.device) / 255.0

                novel_image = rearrange(novel_image, "h w c -> c h w")

                if self.dst_size is not None and ori_size != self.dst_size:
                    novel_image = self._reverse_resize_image(novel_image, ori_size[0], ori_size[1])
                    degarded_image = self._reverse_resize_image(degarded_image, ori_size[0], ori_size[1])
                if novel_image.shape[1] != mask.shape[0] or novel_image.shape[2] != mask.shape[1]:
                    novel_image = F.interpolate(
                        novel_image.unsqueeze(0), size=(mask.shape[0], mask.shape[1]), mode="bilinear"
                    ).squeeze(0)
                    degarded_image = F.interpolate(
                        degarded_image.unsqueeze(0), size=(mask.shape[0], mask.shape[1]), mode="bilinear"
                    ).squeeze(0)

                novel_image = novel_image * mask.unsqueeze(0)

                if self.generate_sky_mask:
                    image_source = (novel_image.cpu().numpy() * 255).astype(np.uint8)
                    image_source = rearrange(image_source, "c h w -> h w c")

                    boxes = self.groundingdino_pipe(novel_image, caption="sky", box_threshold=0.3, text_threshold=0.25)
                    boxes_xyxy = []
                    if boxes.shape[0] != 0:
                        _, H, W = novel_image.shape
                        boxes_xyxy = boxes * torch.Tensor([W, H, W, H])

                    num_boxes = len(boxes_xyxy)
                    if num_boxes == 0:
                        sky_mask = np.zeros_like(image_source[..., 0])[None]
                        sky_mask = torch.from_numpy(sky_mask)
                    else:
                        masks = self.sam_pipe(image_source, boxes_xyxy)
                        torch.cuda.empty_cache()
                        mask_final = torch.zeros_like(masks[0, 0]).bool()
                        for sky_mask in masks[:, 0]:
                            mask_final = mask_final | sky_mask.bool()
                        sky_mask = mask_final[None]
                    sky_mask = sky_mask.squeeze(0).cpu()
                else:
                    sky_mask = None

                result_list.append((degarded_image, novel_image, sky_mask, info, index))
        return result_list

    def _resize_image(self, img, dst_height, dst_width, mode="bilinear"):
        channel, height, width = img.shape
        scale = min(dst_height / height, dst_width / width)
        new_height, new_width = int(height * scale), int(width * scale)
        resized_img = torch.zeros((channel, dst_height, dst_width), dtype=img.dtype, device=img.device)
        with torch.no_grad():
            resized_original = F.interpolate(img.unsqueeze(0), size=(new_height, new_width), mode=mode).squeeze(0)
        start_h = (dst_height - new_height) // 2
        start_w = (dst_width - new_width) // 2
        resized_img[:, start_h : start_h + new_height, start_w : start_w + new_width] = resized_original
        return resized_img

    def _reverse_resize_image(self, img, ori_height, ori_width, mode="bilinear"):
        _, dst_height, dst_width = img.shape
        scale = min(dst_height / ori_height, dst_width / ori_width)
        new_height, new_width = int(ori_height * scale), int(ori_width * scale)
        start_h = (dst_height - new_height) // 2
        start_w = (dst_width - new_width) // 2
        center_crop = img[:, start_h : start_h + new_height, start_w : start_w + new_width]
        with torch.no_grad():
            original_size_img = F.interpolate(
                center_crop.unsqueeze(0), size=(ori_height, ori_width), mode=mode
            ).squeeze(0)
        return original_size_img

    def get_infer_batch(self, batch_list):
        ori_sizes = [sample[0].shape[1:] for sample in batch_list]
        # Resize images if needed
        for i in range(len(batch_list)):
            if not self.enable_dual_resolution_bucket:
                if self.dst_size is None or batch_list[i][0].shape[1:] == self.dst_size:
                    continue
                else:
                    dst_height, dst_width = self.dst_size
            else:
                _, img_h, img_w = batch_list[i][0].shape
                dst_height, dst_width = self._get_sample_height_width(img_w, img_h)
            resized_data = self._resize_image(batch_list[i][0], dst_height, dst_width)
            resized_ref_data = None
            if batch_list[i][1] is not None:
                resized_ref_data = self._resize_image(batch_list[i][1], dst_height, dst_width)
            batch_list[i] = (resized_data, resized_ref_data) + batch_list[i][2:]
        batch_data = torch.stack([sample[0] for sample in batch_list])
        ref_data = None
        if batch_list[0][1] is not None:
            ref_data = torch.stack([sample[1] for sample in batch_list])
        masks = [sample[2] for sample in batch_list]
        infos = [sample[3] for sample in batch_list]
        normed_time = [sample[4] for sample in batch_list]
        prompts = [sample[5] for sample in batch_list]

        return batch_data, ref_data, masks, infos, normed_time, prompts, ori_sizes

    def _get_pipe(self):
        default_path = "/cpfs/batch_inference_models/3dgs_models/2025-08-08/pretrain_model"
        difix_model_path = os.path.join(
            os.environ.get("HF_HOME", default_path), 
            "hub"
        )
        if self.pipe is None:
            self.pipe = DifixPipeline.from_pretrained(
                self.base_model_id,
                torch_dtype=self.weight_dtype,
                trust_remote_code=True,
                local_files_only=True,
                cache_dir=difix_model_path
            )
            self.pipe.to(self.device)
            self.pipe.set_progress_bar_config(disable=True)
            if self.ckpt_path is not None:
                self._load_checkpoint_into_pipe()

    def _load_checkpoint_into_pipe(self):
        """Load custom checkpoint (model.pkl) weights into self.pipe.vae and self.pipe.unet."""
        ckpt_file = os.path.join(self.ckpt_path, "model.pkl")
        logger.info(f"Loading checkpoint from {ckpt_file}")
        sd = torch.load(ckpt_file, map_location="cpu")

        if "state_dict_vae" in sd:
            _sd_vae = self.pipe.vae.state_dict()
            for k in sd["state_dict_vae"]:
                _sd_vae[k] = sd["state_dict_vae"][k]
            self.pipe.vae.load_state_dict(_sd_vae)

        _sd_unet = self.pipe.unet.state_dict()
        for k in sd["state_dict_unet"]:
            _sd_unet[k] = sd["state_dict_unet"][k]
        self.pipe.unet.load_state_dict(_sd_unet)
        logger.info("Checkpoint loaded successfully.")

    def set_train(self):
        self.pipe = None

    def set_eval(self):
        if self.pipe is None:
            stop_event = threading.Event()
            # start up child thread
            t = threading.Thread(target=log_worker, args=(stop_event,))
            t.start()
            # compile generative model pipeline
            self._get_pipe()
            stop_event.set()
            t.join()
            logger.info("Generative model is ready!")

    def save_checkpoint(self, log_dir: str, step: int, is_final: bool = False):
        pass

    def resume_from_checkpoint(self, ckpt_path: str) -> None:
        pass
