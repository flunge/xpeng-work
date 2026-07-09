#
# Created on Thu Nov 28 2024
# Author: Wenkang Qin (wkqin@outlook.com)
#
# Copyright (c) 2024 GigaAI.
#
import torch
import os
import time
import tyro
import pickle
import PIL
from accelerate import Accelerator
from peft import LoraConfig
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

from utils import preprocess_conditions
from pipeline import GaussianRenderFixerPipeline

test_path = "/workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/lora_gaussian_render/test_1727055150413191405_cam0_rgb_half.png"

class GaussianFixerTrainer:
    def __init__(
        self,
        base_model_id: str,
        dataset_dict: Dict,
        mixed_precision: str = "fp16",
        lora_rank: int = 4,
        batch_size: int = 4,
        num_workers: int = 0,
        learning_rate: float = 5e-5,
        conditions: Optional[List] = None,
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
        self.conditions = ["input_image"] if conditions is None else conditions
        self.accelerator = Accelerator(mixed_precision=mixed_precision)

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
        self.unet.requires_grad_(False)
        self.unet.to(self.accelerator.device, dtype=self.weight_dtype)
        self.unet.enable_xformers_memory_efficient_attention()

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
        self.optimizer = torch.optim.AdamW(
            filter(lambda p: p.requires_grad, self.unet.parameters()),
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
        data_dict.update({
            "original_image_path": data_dict["input_image"],
            "original_gt_path": data_dict["edited_image"]
        })
        # ori_dataset = Dataset.from_dict(data_dict)
        dataset = Dataset.from_dict(data_dict).cast_column("edited_image", Image())
        transforms = torchvision.transforms.Compose(
            [
                torchvision.transforms.RandomHorizontalFlip(),
            ]
        )
        for condition in self.conditions:
            dataset = dataset.cast_column(condition, Image())

        # for idx, example in enumerate(dataset):
        #     example["original_image_path"] = ori_dataset[idx]["input_image"]
        #     example["original_gt_path"] = ori_dataset[idx]["edited_image"]

        # def original_path(example):
        #     example["original_image_path"] = ori_dataset["input_image"]
        #     example["original_gt_path"] = ori_dataset["edited_image"]
        #     return example
        # dataset = dataset.map(original_path)
        # import pdb; pdb.set_trace()
        dataset = dataset.with_transform(
            lambda x: preprocess_conditions(
                x, self.conditions, self.tokenizer, transforms
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

    def train_one_step(self, samples):
        import pdb;pdb.set_trace()
        condition_latent = []

        for condition in self.conditions:
            latent = self.vae.encode(
                samples[condition + "_pixel_values"].to(self.weight_dtype)
            ).latent_dist.mode()
            condition_latent.append(latent)
        edited_image_latents = self.vae.encode(
            samples["edited_image_pixel_values"]
        ).latent_dist.sample()
        edited_image_latents = edited_image_latents * self.vae.config.scaling_factor

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
        encoder_hidden_states = self.text_encoder(samples["input_ids"])[0]
        conditioned_noisy_lantents = torch.cat(
            [noisy_latents] + condition_latent, dim=1
        )
        model_pred = self.unet(
            conditioned_noisy_lantents,
            timesteps,
            encoder_hidden_states,
            return_dict=False,
        )[0]

        loss = F.mse_loss(model_pred.float(), noise.float(), reduction="mean")
        return loss

    def fit(self, num_epoch=1, log_every_step=10, infer_test_step=50, 
            max_step=3000, test_path="./test_1727055150413191405_cam0_rgb_half.png"):
        global_step = 0
        start_time = time.time()
        total_step = min(num_epoch * len(self.dataloader), max_step)
        print(f"dataloader length: {len(self.dataloader)}")
        print(f"total step: {total_step}")
        for epoch in range(num_epoch):
            for step, data in enumerate(self.dataloader):
                global_step += 1
                loss = self.train_one_step(data)
                self.accelerator.backward(loss)
                self.optimizer.step()
                self.optimizer.zero_grad()

                time_cosumed = time.time() - start_time
                progress = global_step / total_step
                left_time = time_cosumed / progress - time_cosumed
                if step % log_every_step == 0:
                    self.logger.warning(
                        f"epoch: {epoch}, step: {step}, loss: {loss.item()}, time: {time_cosumed} ({progress} eta: {left_time})."
                    )
                if step % infer_test_step == 0:
                    os.makedirs("test_lora_cam0_v8", exist_ok=True)
                    pipe = self.get_pipe()
                    pipe(
                        "the Xiaopeng Vehicle of CAM0 camera view.",
                        image=PIL.Image.open(test_path),
                        num_inference_steps=100,
                        image_guidance_scale=2.6,
                        guidance_scale=1.4,
                    ).images[0].save(f"test_lora_cam0_v8/test_epoch_{epoch}_iter{step}.png")
                # if step == 3000:
                #     self.save_lora_weights("test_lora_weights_cam0_only_")
                if global_step >= max_step:
                    self.logger.warning(f"trained {global_step} steps, break training.")
                    return

    def get_pipe(self):
        # pipe = GaussianRenderFixerPipeline.from_pretrained(
        #     "stable-diffusion-v1-5/stable-diffusion-v1-5",
        #     unet=self.accelerator.unwrap_model(self.unet),
        #     text_encoder=self.accelerator.unwrap_model(self.text_encoder),
        #     vae=self.accelerator.unwrap_model(self.vae),
        #     torch_dtype=self.weight_dtype,
        #     cache_dir="/workspace/wenkang.qin@gigaai.cc/pretrain_model"
        # )
        # pipe.to(self.accelerator.device)

        pipe = GaussianRenderFixerPipeline.from_pretrained(
            self.base_model_id,
            torch_dtype=torch.float16,
            unet=self.accelerator.unwrap_model(self.unet),
            text_encoder=self.accelerator.unwrap_model(self.text_encoder),
            vae=self.accelerator.unwrap_model(self.vae),
            safety_checker=None,
        )
        pipe = pipe.to("cuda")
        # unwrapped_unet = self.accelerator.unwrap_model(self.unet)
        # unet_lora_state_dict = convert_state_dict_to_diffusers(
        #     get_peft_model_state_dict(unwrapped_unet)
        # )
        # pipe.load_lora_weights(unet_lora_state_dict)

        return pipe

    def save_lora_weights(self, save_path):
        unwrapped_unet = self.accelerator.unwrap_model(self.unet)
        unet_lora_state_dict = convert_state_dict_to_diffusers(
            get_peft_model_state_dict(unwrapped_unet)
        )
        GaussianRenderFixerPipeline.save_lora_weights(
            save_directory=save_path,
            unet_lora_layers=unet_lora_state_dict,
            safe_serialization=True,
        )


def main(base_model_id: str, dataset_dict_path: str, max_step: int, save_dir: str, epoch: int):
    with open(dataset_dict_path, "rb") as f:
        dataset_dict = pickle.load(f)
    print(f"data_ dict length: {len(dataset_dict['input_image'])}")
    trainer = GaussianFixerTrainer(
        base_model_id=base_model_id, dataset_dict=dataset_dict
    )
    trainer.fit(num_epoch=epoch, max_step=max_step)
    trainer.save_lora_weights(save_dir)

    # # inference
    # pipe = trainer.get_pipe()
    # import PIL

    # pipe(
    #     "train",
    #     image=PIL.Image.open("pix2pix_data_shifting_all/000098_0_iter50000.png"),
    #     num_inference_steps=100,
    #     image_guidance_scale=2.6,
    #     guidance_scale=1.4,
    # ).images[0].save("train.png")


if __name__ == "__main__":
    tyro.cli(main)
