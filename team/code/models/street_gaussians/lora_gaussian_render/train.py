#
# Created on Thu Nov 28 2024
# Author: Wenkang Qin (wkqin@outlook.com)
#
# Copyright (c) 2024 GigaAI.
#
import os
# import glob
import random
import torch
import time
import tyro
import pickle
from accelerate import Accelerator
from transformers import CLIPTextModel, CLIPTokenizer
from diffusers import AutoencoderKL, DDPMScheduler, UNet2DConditionModel
from datasets import Dataset, Image
from typing import Dict, List, Optional
import torchvision
import torch.nn.functional as F
from diffusers.utils import convert_state_dict_to_diffusers
from peft.utils import get_peft_model_state_dict
from diffusers.training_utils import cast_training_params
from accelerate.logging import get_logger
import PIL

from utils import preprocess_conditions, resize_with_padding, get_masks 
from pipeline import GaussianRenderFixerPipeline


class GaussianFixerTrainer:
    def __init__(
        self,
        base_model_id: str,
        dataset_dict: Dict,
        save_dir: str,
        #mask_path: str,
        mixed_precision: str = "fp16",
        lora_rank: int = 4,
        batch_size: int = 4,
        num_workers: int = 4,
        max_norm: Optional[float] = 1.0,
        learning_rate: float = 5e-5,
        conditions: Optional[List] = None,
        with_lora: bool = False,
        condition_dropout_prob: float = 0.0,
        seed: int = 123
    ):
        if mixed_precision == "fp16":
            weight_dtype = torch.float16
        elif mixed_precision == "bf16":
            weight_dtype = torch.bfloat16
        else:
            raise ValueError(f"unsupport mixed_precision {mixed_precision}")

        self.lora_rank = lora_rank
        self.learning_rate = learning_rate
        self.weight_dtype = weight_dtype
        self.batch_size = batch_size
        self.num_workers = num_workers
        self.base_model_id = base_model_id
        self.with_lora = with_lora
        self.save_dir = save_dir
        self.max_norm = max_norm
        self.conditions = ["input_image"] if conditions is None else conditions
        self.condition_dropout_prob = condition_dropout_prob
        self.seed = seed
        self.accelerator = Accelerator(mixed_precision=mixed_precision)
        self.generator = torch.Generator(device=self.accelerator.device).manual_seed(self.seed)

        self._build_modules(base_model_id)
        self._build_optimizer()
        self._build_dataloader(dataset_dict)
        self.unet, self.optimizer, self.dataloader = self.accelerator.prepare(
            self.unet, self.optimizer, self.dataloader
        )
        self.logger = get_logger(__name__, log_level="DEBUG")

    def _build_modules(self, base_model_id):
        self.noise_scheduler = DDPMScheduler.from_pretrained(
            base_model_id, subfolder="scheduler"
        )
        self.tokenizer = CLIPTokenizer.from_pretrained(
            base_model_id,
            subfolder="tokenizer",
        )
        self.text_encoder = CLIPTextModel.from_pretrained(
            base_model_id,
            subfolder="text_encoder",
        )
        self.vae = AutoencoderKL.from_pretrained(
            base_model_id,
            subfolder="vae",
        )
        self.unet = UNet2DConditionModel.from_pretrained(
            base_model_id,
            subfolder="unet",
        )

        self.vae.requires_grad_(False)
        self.vae.to(self.accelerator.device, dtype=self.weight_dtype)
        self.text_encoder.requires_grad_(False)
        self.text_encoder.to(self.accelerator.device, dtype=self.weight_dtype)
        self.unet.requires_grad_(not self.with_lora)
        self.unet.enable_xformers_memory_efficient_attention()

        if self.with_lora:
            self.unet.to(self.accelerator.device, dtype=self.weight_dtype)
            from peft import LoraConfig
            unet_lora_config = LoraConfig(
                r=self.lora_rank,
                lora_alpha=self.lora_rank,
                init_lora_weights="gaussian",
                target_modules=["to_k", "to_q", "to_v", "to_out.0"],
            )
            self.unet.add_adapter(unet_lora_config)
            if self.weight_dtype == torch.float16:
                cast_training_params(self.unet, dtype=torch.float32)

    def _build_optimizer(self):
        if self.with_lora:
            self.optimizer = torch.optim.AdamW(
                filter(lambda p: p.requires_grad, self.unet.parameters()),
                lr=self.learning_rate,
            )
        else:
            self.optimizer = torch.optim.AdamW(
                self.unet.parameters(),
                lr=self.learning_rate,
            )

    def _collate_fn(self, samples):
        new_samples = {}
        for condition in self.conditions + ["edited_image"]:
            k = condition + "_pixel_values"
            new_samples[k] = torch.stack([sample[k] for sample in samples]).to(
                memory_format=torch.contiguous_format,
                dtype=self.weight_dtype,
            )
        new_samples["input_ids"] = torch.stack(
            [sample["input_ids"] for sample in samples]
        )
        return new_samples

    def _build_dataloader(self, data_dict):
        dataset = Dataset.from_dict(data_dict).cast_column("edited_image", Image())
        transforms = torchvision.transforms.Compose(
            [
                torchvision.transforms.RandomHorizontalFlip(),
            ]
        )
        for condition in self.conditions:
            dataset = dataset.cast_column(condition, Image())
        dataset = dataset.with_transform(
            lambda x: preprocess_conditions(
                x, 
                self.conditions, 
                self.tokenizer, 
                transforms
            )
        )

        dataloader = torch.utils.data.DataLoader(
            dataset,
            shuffle=True,
            collate_fn=self._collate_fn,
            batch_size=self.batch_size,
            num_workers=self.num_workers,
        )
        self.dataloader = dataloader

    def mse_loss(self, model_pred, noise, masks):
        print("model_pred, noise", model_pred.shape, noise.shape)
        loss = F.mse_loss(model_pred.float(), noise.float(), reduction="none")
        masked_loss = loss * masks
        mean_loss = masked_loss.sum() / masks.sum()
        return mean_loss

    def train_one_step(self, samples):
        condition_latent = []
        for condition in self.conditions:
            latent = self.vae.encode(
                samples[condition + "_pixel_values"].to(self.weight_dtype)
            ).latent_dist.mode()
            condition_latent.append(latent)
        edited_image_latents = self.vae.encode(
            samples["edited_image_pixel_values"]
        ).latent_dist.mode()  # gt image
        edited_image_latents = edited_image_latents * self.vae.config.scaling_factor
        encoder_hidden_states = self.text_encoder(samples["input_ids"])[0]

        if self.condition_dropout_prob > 0.0:
            bsz = edited_image_latents.shape[0]
            random_p = torch.rand(bsz, 
                                  device=edited_image_latents.device, 
                                  generator=self.generator)
            # Sample masks for the edit prompts.
            prompt_mask = random_p < 2 * self.condition_dropout_prob
            prompt_mask = prompt_mask.reshape(bsz, 1, 1)
            # Final text conditioning.
            null_token = self.tokenizer([""], 
                                        max_length=self.tokenizer.model_max_length, 
                                        padding="max_length", 
                                        truncation=True, 
                                        return_tensors="pt").input_ids
            null_token = torch.Tensor(null_token).long().to(edited_image_latents.device)
            null_conditioning = self.text_encoder(null_token)[0]
            encoder_hidden_states = torch.where(prompt_mask, 
                                                null_conditioning, 
                                                encoder_hidden_states)

            # Sample masks for the original images.
            for idx in range(0, len(condition_latent)):
                image_mask_dtype = condition_latent[idx].dtype
                image_mask = 1 - (
                    (random_p >= self.condition_dropout_prob).to(image_mask_dtype)
                    * (random_p < 3 * self.condition_dropout_prob).to(image_mask_dtype)
                )
                image_mask = image_mask.reshape(bsz, 1, 1, 1)
                # Final image conditioning.
                condition_latent[idx] = image_mask * condition_latent[idx]

        noise = torch.randn_like(edited_image_latents)
        timesteps = torch.randint(
            0,
            self.noise_scheduler.config.num_train_timesteps,
            (noise.shape[0],),
            device="cuda",
        ).long()
        noisy_latents = self.noise_scheduler.add_noise(
            edited_image_latents, noise, timesteps
        )
        conditioned_noisy_lantents = torch.cat(
            [noisy_latents] + condition_latent, dim=1
        )
        model_pred = self.unet(
            conditioned_noisy_lantents,
            timesteps,
            encoder_hidden_states,
            return_dict=False,
        )[0]

        with self.accelerator.autocast():
            loss = F.mse_loss(model_pred.float(), noise.float(), reduction="mean")
        return loss

    def fit(self, num_epoch=1, 
            log_every_step=10, 
            max_step=3000, 
            valid_every_step=50, 
            start=4*4,
            image_size=(1920, 1280),
            valid_root_path="/root/workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/output/xpeng_test_leo/exp_c-fff8d69c-133d-304e-ae56-e3c9ece12679/train/ours_100000"):
        # validate_png_list = [f for f in os.listdir(valid_root_path) 
        #                             if os.path.splitext(f)[0].split("_")[-1] == "rgb"] 
        # validate_png_list = sorted(validate_png_list)
        validate_png_list=[]
        for cam in os.listdir(valid_root_path):
            for f in os.listdir(os.path.join(valid_root_path, cam)):        
                validate_png_list.append(f.replace(".png", "_" + cam + "_rgb.png"))
        validate_png_list = sorted(validate_png_list)
        # 确定中间帧的范围 (比如排除头尾各1帧)
        end = len(validate_png_list) - start 
        
        global_step = 0
        start_time = time.time()
        total_step = min(num_epoch * len(self.dataloader), max_step)
        for epoch in range(num_epoch):
            for step, data in enumerate(self.dataloader):
                global_step += 1
                loss = self.train_one_step(data)
                self.accelerator.backward(loss)
                if self.max_norm is not None:
                    self.accelerator.clip_grad_norm_(
                        self.unet.parameters(), max_norm=self.max_norm
                    )
                self.optimizer.step()
                self.optimizer.zero_grad()

                time_cosumed = time.time() - start_time
                progress = global_step / total_step
                left_time = time_cosumed / progress - time_cosumed

                if global_step % log_every_step == 0:
                    self.logger.warning(
                        f"epoch: {epoch}, step: {step}, loss: {loss.item()}, time: {time_cosumed} ({progress} eta: {left_time})."
                    )
                if global_step % valid_every_step == 0:
                    # 从中间帧范围中随机选取一帧
                    middle_index = random.randint(start, end - 1)
                    random_middle_frame = validate_png_list[middle_index]
                    valid_path = os.path.join(valid_root_path, random_middle_frame)
                    # inference
                    pipe = self.get_pipe()
                    validation_output_dir = os.path.join(self.save_dir, "validation")
                    os.makedirs(validation_output_dir, exist_ok=True)
                    image_name = os.path.basename(valid_path).split("_rgb")[0]
                    _, cam_type, _ = os.path.splitext(os.path.basename(valid_path))[0].split("_")
                    print(valid_path)
                    valid_path = valid_path.replace("_" + cam_type + "_rgb", "")
                    valid_path = valid_path.replace("rgb", "rgb/" + cam_type)
                    print(valid_path)
                    valid_img = PIL.Image.open(valid_path)
                    valid_img = resize_with_padding(valid_img, image_size)
                    pipe(
                        f"the Xiaopeng Vehicle of {cam_type.upper()} camera view.",
                        # "the Xiaopeng Vehicle of CAM0 camera view.",
                        image=valid_img,
                        num_inference_steps=50,
                        image_guidance_scale=2.6,
                        guidance_scale=1.4,
                    ).images[0].save(os.path.join(validation_output_dir, 
                                                  f"validation_{global_step}_{image_name}.png"))

                if global_step >= max_step:
                    self.logger.warning(f"trained {global_step} steps, break training.")
                    return

    def get_pipe(self):
        pipe = GaussianRenderFixerPipeline.from_pretrained(
            self.base_model_id,
            unet=self.accelerator.unwrap_model(self.unet),
            text_encoder=self.accelerator.unwrap_model(self.text_encoder),
            vae=self.accelerator.unwrap_model(self.vae),
            safety_checker=None,
            torch_dtype=self.weight_dtype,
        )
        pipe.to(self.accelerator.device)
        return pipe
    
    def save_weights(self):
        os.makedirs(self.save_dir, exist_ok=True)
        unwrapped_unet = self.accelerator.unwrap_model(self.unet)

        if self.with_lora:
            unet_lora_state_dict = convert_state_dict_to_diffusers(
                get_peft_model_state_dict(unwrapped_unet)
            )
            GaussianRenderFixerPipeline.save_lora_weights(
                save_directory=self.save_dir,
                unet_lora_layers=unet_lora_state_dict,
                safe_serialization=True,
            )
        else:
            weights_dir = os.path.join(self.save_dir, "unet_weights")
            os.makedirs(weights_dir)
            self.accelerator.save_state(weights_dir)


def main(
    base_model_id: str,
    dataset_dict_path: str,
    max_step: int,
    num_epoch: int,
    save_dir: str,
    log_every_step: int = 10,
    with_lora: bool = False,
    image_size: tuple = (1920, 1280),
    dropout_prob: float = 0.05
):
    with open(dataset_dict_path, "rb") as f:
        dataset_dict = pickle.load(f)

    iter_dir = os.path.dirname(dataset_dict["input_image"][0])
    data_dir = os.path.dirname(iter_dir)
    exp_dir = os.path.dirname(data_dir)
    search_dir = os.path.join(exp_dir, "train")
    matching_folders = [folder for folder in os.listdir(search_dir) 
                                    if "ours" in os.path.basename(folder)]
    valid_data_dir = os.path.join(exp_dir, "train", matching_folders[0])
    valid_data_dir = os.path.join(valid_data_dir, "rgb")
    
    trainer = GaussianFixerTrainer(base_model_id=base_model_id, 
                                   dataset_dict=dataset_dict, 
                                   with_lora=with_lora, 
                                   save_dir=save_dir, 
                                   condition_dropout_prob=dropout_prob 
    )
    trainer.fit(max_step=max_step, num_epoch=num_epoch, 
                log_every_step=log_every_step, 
                valid_root_path=valid_data_dir,
                image_size=image_size)
    trainer.save_weights()


if __name__ == "__main__":
    tyro.cli(main)
