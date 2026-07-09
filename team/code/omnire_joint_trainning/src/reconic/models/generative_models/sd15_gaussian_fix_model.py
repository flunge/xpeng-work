#
# Created on Thu Nov 28 2024
#
# Copyright (c) 2024 GigaAI.
#
import logging
import os
import time
import threading
from typing import List, Optional, Tuple

import numpy as np
import torch
import torch.nn.functional as F
from accelerate import Accelerator
from diffusers import AutoencoderKL, DDPMScheduler, UNet2DConditionModel
from diffusers.utils.torch_utils import is_compiled_module
from einops import rearrange
from safetensors.torch import load_file
from torch import nn
from transformers import CLIPTextModel, CLIPTokenizer

from ...pipelines.pipeline_gaussian_render_fixer import GaussianRenderFixerPipeline
from ...utils.model_utils import GroundingDINOPipeline, SAMPipeline

logger = logging.getLogger()

def log_worker(stop_event):
    while not stop_event.is_set():
        logger.info("Waiting for generative model pipeline!")
        time.sleep(10)
    logger.info("Log worker quit!")

class SD15_GaussianFixModel(nn.Module):
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
        mixed_precision: str = "fp16",
        pretrained_unet_weights: Optional[str] = None,
        groundingdino_model_id: Optional[str] = None,
        sam_model_id: Optional[str] = None,
        use_8bit_optimizer: bool = False,
        dst_size: Optional[Tuple[int, int]] = None,
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
        self.noise_scheduler = DDPMScheduler.from_pretrained(base_model_id, subfolder="scheduler")
        self.tokenizer = CLIPTokenizer.from_pretrained(base_model_id, subfolder="tokenizer")
        self.text_encoder = CLIPTextModel.from_pretrained(base_model_id, subfolder="text_encoder")
        self.vae = AutoencoderKL.from_pretrained(base_model_id, subfolder="vae")
        self.unet = UNet2DConditionModel.from_pretrained(base_model_id, subfolder="unet")
        in_channels = (num_condition + 1) * self.unet.conv_in.in_channels
        self.unet.register_to_config(in_channels=in_channels)
        with torch.no_grad():
            new_conv_in = nn.Conv2d(
                in_channels,
                self.unet.conv_in.out_channels,
                self.unet.conv_in.kernel_size,
                self.unet.conv_in.stride,
                self.unet.conv_in.padding,
            )
            new_conv_in.weight.zero_()
            new_conv_in.weight[:, :4, :, :].copy_(self.unet.conv_in.weight)
            self.unet.conv_in = new_conv_in
        self.vae.requires_grad_(False)
        self.text_encoder.requires_grad_(False)
        if pretrained_unet_weights is not None:
            self.unet.load_state_dict(load_file(pretrained_unet_weights))
        self.unet.enable_xformers_memory_efficient_attention()
        self.vae.to(self.accelerator.device, dtype=weight_dtype)
        self.text_encoder.to(self.accelerator.device, dtype=weight_dtype)

        self.groundingdino_pipe = GroundingDINOPipeline(
            groundingdino_model_id, self.accelerator.device, lazy_mode=False
        )
        self.sam_pipe = SAMPipeline(sam_model_id, self.accelerator.device, lazy_mode=False)

        if use_8bit_optimizer:
            import bitsandbytes as bnb

            optimizer_cls = bnb.optim.AdamW8bit
        else:
            optimizer_cls = torch.optim.AdamW
        self.optimizer = optimizer_cls(
            self.unet.parameters(),
            lr=training_learning_rate,
        )
        self.unet, self.optimizer = self.accelerator.prepare(self.unet, self.optimizer)
        self.pipe = None

        self.weight_dtype = weight_dtype
        self.max_norm = max_norm
        self.training_batch_size = training_batch_size
        self.inference_batch_size = inference_batch_size
        self.dst_size = dst_size

        self.random_flip_prob = random_flip_prob
        self.num_inference_steps = num_inference_steps
        self.image_guidance_scale = image_guidance_scale
        self.guidance_scale = guidance_scale
        self.condition_dropout_prob = condition_dropout_prob

        self.prompt_embeds_cache = dict({})

    def training_forward(self, batch):
        loss = self._training_forward_step(*batch)
        self.accelerator.backward(loss)
        if self.max_norm is not None:
            self.accelerator.clip_grad_norm_(self.unet.parameters(), max_norm=self.max_norm)
        self.optimizer.step()
        self.optimizer.zero_grad()

    def inference_forward(self, batch_data, masks, infos, indexes, prompts, ori_sizes):
        if self.pipe is None:
            self._get_pipe()
        result_list = []
        with torch.no_grad(), torch.autocast(self.accelerator.device.type):
            assert batch_data.is_cuda
            if not (0.0 <= batch_data.mean().item() <= 1.0):
                logger.warning(
                    f"CUDA scheduler warning: batch_data: {batch_data.device}, "
                    f"batch_data.mean(): {batch_data.mean()}, "
                    f"current_indexes: {indexes}. Run cuda sync."
                )
                torch.cuda.synchronize()
            novel_view_data = self.pipe(
                prompts,
                image=batch_data,
                num_inference_steps=self.num_inference_steps,
                image_guidance_scale=self.image_guidance_scale,
                guidance_scale=self.guidance_scale,
                output_type="pt",
            ).images
            assert novel_view_data.shape[0] == len(infos)
            for degarded_image, novel_image, mask, info, index, ori_size in zip(
                batch_data, novel_view_data, masks, infos, indexes, ori_sizes
            ):
                if self.dst_size is not None and ori_size != self.dst_size:
                    novel_image = self._reverse_resize_image(novel_image, ori_size[0], ori_size[1])
                    degarded_image = self._reverse_resize_image(degarded_image, ori_size[0], ori_size[1])

                novel_image = novel_image * mask.unsqueeze(0)

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

    def get_batch(self, batch_list):
        # Resize images if needed
        for i in range(len(batch_list)):
            if self.dst_size is None or batch_list[i][0].shape[1:] == self.dst_size:
                continue
            dst_height, dst_width = self.dst_size
            resized_data = self._resize_image(batch_list[i][0], dst_height, dst_width)
            resized_gt = self._resize_image(batch_list[i][1], dst_height, dst_width)
            resized_mask = self._resize_image(
                batch_list[i][2].unsqueeze(0), dst_height, dst_width, mode="nearest"
            ).squeeze(0)
            batch_list[i] = (resized_data, resized_gt, resized_mask) + batch_list[i][3:]

        batch_data = 2 * torch.stack([sample[0] for sample in batch_list]) - 1
        batch_gt = 2 * torch.stack([sample[1] for sample in batch_list]) - 1
        batch_mask = torch.stack([sample[2] for sample in batch_list])
        prompts = [sample[3] for sample in batch_list]
        return batch_data, batch_gt, batch_mask, prompts

    def get_infer_batch(self, batch_list):
        ori_sizes = [sample[0].shape[1:] for sample in batch_list]
        # Resize images if needed
        for i in range(len(batch_list)):
            if self.dst_size is None or batch_list[i][0].shape[1:] == self.dst_size:
                continue
            dst_height, dst_width = self.dst_size
            resized_data = self._resize_image(batch_list[i][0], dst_height, dst_width)
            batch_list[i] = (resized_data,) + batch_list[i][1:]
        batch_data = torch.stack([sample[0] for sample in batch_list])
        masks = [sample[1] for sample in batch_list]
        infos = [sample[2] for sample in batch_list]
        normed_time = [sample[3] for sample in batch_list]
        prompts = [sample[4] for sample in batch_list]

        return batch_data, masks, infos, normed_time, prompts, ori_sizes

    def _prompt_transform(self, prompts: List[str]):
        text_embeds = []
        for prompt in prompts:
            if prompt in self.prompt_embeds_cache:
                text_embeds.append(self.prompt_embeds_cache[prompt])
                continue

            prompt_token = self.tokenizer(
                prompt,
                max_length=self.tokenizer.model_max_length,
                padding="max_length",
                truncation=True,
                return_tensors="pt",
            ).input_ids.to(self.device)
            text_embeds.append(self.text_encoder(prompt_token)[0])
            self.prompt_embeds_cache[prompt] = text_embeds[-1].clone()
        text_embeds = torch.cat(text_embeds, dim=0)
        return text_embeds

    def _training_forward_step(self, batch_input_data, batch_gt, batch_mask, prompts: List[str]):
        batch_input_data, batch_gt, batch_mask = self._do_data_augmentation(batch_input_data, batch_gt, batch_mask)

        image_embeds = self.vae.encode(batch_input_data.to(self.weight_dtype)).latent_dist.mode()
        latents = self.vae.encode(batch_gt.to(self.weight_dtype)).latent_dist.mode()
        latents = latents * self.vae.config.scaling_factor

        noise = torch.randn_like(latents)

        timesteps = torch.randint(
            0,
            self.noise_scheduler.config.num_train_timesteps,
            (self.training_batch_size,),
            device=self.device,
        ).long()
        noisy_latents = self.noise_scheduler.add_noise(latents, noise, timesteps)

        text_embeds = self._prompt_transform(prompts)
        
        if self.condition_dropout_prob > 0.0:
            bsz = image_embeds.shape[0]
            random_p = torch.rand(bsz, 
                                  device=self.device)
            # Sample masks for the edit prompts.
            prompt_mask = random_p < 2 * self.condition_dropout_prob
            prompt_mask = prompt_mask.reshape(bsz, 1, 1)
            # Final text conditioning.
            null_conditioning = self._prompt_transform([""])
            text_embeds = torch.where(prompt_mask, 
                                      null_conditioning, 
                                      text_embeds)
            # Sample masks for the original images.
            image_mask_dtype = image_embeds.dtype
            image_mask = 1 - (
                    (random_p >= self.condition_dropout_prob).to(image_mask_dtype)
                    * (random_p < 3 * self.condition_dropout_prob).to(image_mask_dtype)
            )
            image_mask = image_mask.reshape(bsz, 1, 1, 1)
            # Final image conditioning.
            image_embeds = image_mask * image_embeds

        conditioned_noisy_lantents = torch.cat(
            [noisy_latents, image_embeds],
            dim=1,
        )
        noise_pred = self.unet(conditioned_noisy_lantents, timesteps, text_embeds, return_dict=False)[0]

        mask_weights = F.max_pool2d(batch_mask.unsqueeze(1), kernel_size=(8, 8))
        noise_pred = noise_pred * mask_weights
        noise = noise * mask_weights
        loss = F.mse_loss(noise_pred.float(), noise.float(), reduction="mean")
        return loss

    def _do_data_augmentation(self, batch_input_data, batch_gt, batch_mask):
        # Note: batch_input_data and batch_gt are in GPU memory and the value range is [-1, 1]
        for i in range(batch_input_data.size(0)):
            if torch.rand(1).item() < self.random_flip_prob:
                batch_input_data[i] = torch.flip(batch_input_data[i], dims=[-1])
                batch_gt[i] = torch.flip(batch_gt[i], dims=[-1])
                batch_mask[i] = torch.flip(batch_mask[i], dims=[-1])

        return batch_input_data, batch_gt, batch_mask

    def _get_pipe(self):
        def unwrap_model(model):
            model = self.accelerator.unwrap_model(model)
            model = model._orig_mod if is_compiled_module(model) else model
            return model

        if self.pipe is None:
            self.pipe = GaussianRenderFixerPipeline.from_pretrained(
                self.base_model_id,
                unet=unwrap_model(self.unet),
                text_encoder=unwrap_model(self.text_encoder),
                vae=unwrap_model(self.vae),
                torch_dtype=self.weight_dtype,
            )
            self.pipe.to(self.device)
            self.pipe.set_progress_bar_config(disable=True)

    def set_train(self):
        self.unet.train()
        self.text_encoder.eval()
        self.vae.eval()
        self.pipe = None

    def set_eval(self):
        self.unet.eval()
        self.text_encoder.eval()
        self.vae.eval()
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
        if is_final:
            ckpt_path = os.path.join(log_dir, "engine_checkpoint_final.pth")
        else:
            ckpt_path = os.path.join(log_dir, f"engine_checkpoint_{step:05d}.pth")

        # Get generative model state
        unwrapped_unet = self.accelerator.unwrap_model(self.unet)
        unet_state_dict = unwrapped_unet.state_dict()
        optimizer_state_dict = self.optimizer.state_dict()
        checkpoint = {
            "unet_state_dict": unet_state_dict,
            "optimizer_state_dict": optimizer_state_dict,
        }
        torch.save(checkpoint, ckpt_path)

    def resume_from_checkpoint(self, ckpt_path: str) -> None:
        """
        Load model from checkpoint.
        """
        checkpoint = torch.load(ckpt_path, map_location=self.device)
        unwrapped_unet = self.accelerator.unwrap_model(self.unet)
        unwrapped_unet.load_state_dict(checkpoint["unet_state_dict"])
        self.optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
