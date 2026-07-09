# SPDX-FileCopyrightText: Copyright (c) <year> NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import sys
import cv2
import random
import shutil
import argparse
import json
import torch
from PIL import Image
from torchvision import transforms
import torchvision.transforms.functional as F
from torch.utils.data._utils.collate import default_collate
from glob import glob
from io import BytesIO
from packaging import version as pver
import numpy as np
from einops import rearrange, repeat
from tqdm import tqdm


PAIRED_TRAINING_CONFIG_DEFAULTS = {
    "lambda_lpips": 5.0,
    "lambda_reg": 10.0,
    "lambda_l2": 1.0,
    "lambda_clipsim": 5.0,
    "lambda_gram": 1.0,
    "lambda_tv": 1.0,
    "N_resize": 2.0,
    "gram_loss_warmup_steps": 2000,
    "dataset_folder": None,
    "train_image_prep": "resized_crop_512",
    "test_image_prep": "resized_crop_512",
    "prompt": None,
    "eval_freq": 100,
    "track_val_fid": False,
    "viz_freq": 100,
    "tracker_project_name": "train_pix2pix_turbo",
    "tracker_run_name": None,
    "pretrained_model_name_or_path": None,
    "revision": None,
    "variant": None,
    "tokenizer_name": None,
    "lora_rank_unet": 8,
    "lora_rank_vae": 4,
    "freeze_vae_encoder": False,
    "freeze_vae": False,
    "add_noise": False,
    "pretrained_path": None,
    "train_full_unet": False,
    "unet_in_channels": 4,
    "timestep": 999,
    "output_dir": None,
    "cache_dir": None,
    "seed": None,
    "resolution": 512,
    "image_height": 576,
    "image_width": 1024,
    "enable_dual_resolution_bucket": False,
    "bucket_16_9_height": 576,
    "bucket_16_9_width": 1024,
    "bucket_5_4_height": 768,
    "bucket_5_4_width": 960,
    "train_batch_size": 4,
    "num_training_epochs": 10,
    "max_train_steps": 0,
    "checkpointing_epoch": 1,
    "gradient_accumulation_steps": 1,
    "gradient_checkpointing": False,
    "learning_rate": 5e-6,
    "lr_scheduler": "constant",
    "lr_warmup_steps": 500,
    "lr_num_cycles": 1,
    "lr_power": 1.0,
    "dataloader_num_workers": 0,
    "adam_beta1": 0.9,
    "adam_beta2": 0.999,
    "adam_weight_decay": 1e-2,
    "adam_epsilon": 1e-8,
    "max_grad_norm": 1.0,
    "allow_tf32": False,
    "report_to": "tensorboard",
    "hf_path": "Efficient-Large-Model/Sana_600M_1024px_diffusers",
    "experiment_name": "official_runs_t2i_fast_205_stage3_0p6b_1024res_synthrealmix_1_1_filtered_with_alpamayo",
    "s3_checkpoint_dir": "None",
    "av_model_path": "",
    "mixed_precision": None,
    "enable_xformers_memory_efficient_attention": False,
    "set_grads_to_none": False,
    "resume": None,
    "swinir": False,
    "unetscratch": False,
    "use_sched": False,
    "use_large_postnet": False,
    "vae_skip_connection": False,
    "fix_deconv": False,
    "max_steps_per_epoch": 4000,
    "use_reference_image": False,
    "use_ref_cross_attn": False,
    "use_ref_detail_adapter": False,
    "ref_token_count": 32,
}


def _load_yaml_config(path):
    try:
        import yaml
    except ImportError as exc:
        raise ImportError("需要安装 PyYAML: pip install pyyaml") from exc
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg if cfg else {}


def save_config(output_dir, args):
    config = dict(vars(args))
    config.pop("_config_path", None)
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    try:
        import yaml
    except ImportError:
        yaml = None

    config_path = getattr(args, "_config_path", None)
    if config_path and os.path.isfile(config_path):
        backup_path = os.path.join(output_dir, os.path.basename(config_path))
        shutil.copy2(config_path, backup_path)
        shutil.copy2(config_path, os.path.join(output_dir, "train_config.yaml"))
    elif yaml is not None:
        with open(os.path.join(output_dir, "train_config.yaml"), "w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, allow_unicode=False, sort_keys=False)

def parse_args_paired_training(input_args=None):
    """
    Parses command-line arguments used for configuring an paired session (pix2pix-Turbo).
    This function sets up an argument parser to handle various training options.

    Returns:
    argparse.Namespace: The parsed command-line arguments.
   """
    raw_args = list(input_args) if input_args is not None else sys.argv[1:]
    config_parser = argparse.ArgumentParser(add_help=False)
    config_parser.add_argument("--config", type=str, default=None)
    config_args, _ = config_parser.parse_known_args(raw_args)
    if config_args.config is not None:
        config_path = config_args.config
        if not os.path.isfile(config_path):
            raise FileNotFoundError(f"Config file not found: {config_path}")
        cfg = _load_yaml_config(config_path)
        allowed = set(PAIRED_TRAINING_CONFIG_DEFAULTS)
        filtered_cfg = {
            key: value for key, value in cfg.items()
            if key in allowed and value is not None
        }
        merged = {**PAIRED_TRAINING_CONFIG_DEFAULTS, **filtered_cfg}
        if merged["output_dir"] is None or merged["dataset_folder"] is None:
            raise ValueError("config 中必须提供 output_dir 和 dataset_folder")
        if merged["tracker_run_name"] is None:
            merged["tracker_run_name"] = os.path.splitext(
                os.path.basename(str(merged["dataset_folder"]).split(",")[0].rstrip("/"))
            )[0]
        if merged["tracker_project_name"] is None:
            merged["tracker_project_name"] = os.path.basename(
                os.path.normpath(merged["output_dir"])
            )
        args = argparse.Namespace(**merged)
        args._config_path = config_path
        return args

    parser = argparse.ArgumentParser()
    # args for the loss function
    parser.add_argument("--lambda_lpips", default=5, type=float)
    parser.add_argument("--lambda_reg", default=10, type=float)
    parser.add_argument("--lambda_l2", default=1.0, type=float)
    parser.add_argument("--lambda_clipsim", default=5.0, type=float)
    parser.add_argument("--lambda_gram", default=1.0, type=float)
    parser.add_argument("--lambda_tv", default=1.0, type=float)
    parser.add_argument("--N_resize", default=2.0, type=float)
    parser.add_argument("--gram_loss_warmup_steps", default=2000, type=int)

    # dataset options
    parser.add_argument("--dataset_folder", required=True, type=str)
    parser.add_argument("--train_image_prep", default="resized_crop_512", type=str)
    parser.add_argument("--test_image_prep", default="resized_crop_512", type=str)
    parser.add_argument("--prompt", default=None, type=str)
    parser.add_argument("--image_height", type=int, default=576)
    parser.add_argument("--image_width", type=int, default=1024)
    parser.add_argument("--enable_dual_resolution_bucket", action="store_true")
    parser.add_argument("--bucket_16_9_height", type=int, default=576)
    parser.add_argument("--bucket_16_9_width", type=int, default=1024)
    parser.add_argument("--bucket_5_4_height", type=int, default=768)
    parser.add_argument("--bucket_5_4_width", type=int, default=960)

    # validation eval args
    parser.add_argument("--eval_freq", default=100, type=int)
    parser.add_argument("--track_val_fid", default=False, action="store_true")

    parser.add_argument("--viz_freq", type=int, default=100, help="Frequency of visualizing the outputs.")
    parser.add_argument("--tracker_project_name", type=str, default="train_pix2pix_turbo", help="The name of the wandb project to log to.")
    parser.add_argument("--tracker_run_name", type=str, required=True)

    # details about the model architecture
    parser.add_argument("--pretrained_model_name_or_path")
    parser.add_argument("--revision", type=str, default=None,)
    parser.add_argument("--variant", type=str, default=None,)
    parser.add_argument("--tokenizer_name", type=str, default=None)
    parser.add_argument("--lora_rank_unet", default=8, type=int)
    parser.add_argument("--lora_rank_vae", default=4, type=int)
    parser.add_argument("--freeze_vae_encoder", action="store_true")
    parser.add_argument("--freeze_vae", action="store_true")
    parser.add_argument("--add_noise", action="store_true")
    parser.add_argument("--pretrained_path", type=str, default=None,)
    parser.add_argument("--train_full_unet", action="store_true")
    parser.add_argument("--unet_in_channels", default=4, type=int)
    parser.add_argument("--timestep", default=999, type=int)

    # training details
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--cache_dir", default=None,)
    parser.add_argument("--seed", type=int, default=None, help="A seed for reproducible training.")
    parser.add_argument("--resolution", type=int, default=512,)
    parser.add_argument("--train_batch_size", type=int, default=4, help="Batch size (per device) for the training dataloader.")
    parser.add_argument("--num_training_epochs", type=int, default=10)
    parser.add_argument("--max_train_steps", type=int, default=10_000,)
    parser.add_argument("--checkpointing_epoch", type=int, default=1)
    parser.add_argument("--max_steps_per_epoch", type=int, default=4000)
    parser.add_argument("--gradient_accumulation_steps", type=int, default=1, help="Number of updates steps to accumulate before performing a backward/update pass.",)
    parser.add_argument("--gradient_checkpointing", action="store_true",)
    parser.add_argument("--learning_rate", type=float, default=5e-6)
    parser.add_argument("--lr_scheduler", type=str, default="constant",
        help=(
            'The scheduler type to use. Choose between ["linear", "cosine", "cosine_with_restarts", "polynomial",'
            ' "constant", "constant_with_warmup"]'
        ),
    )
    parser.add_argument("--lr_warmup_steps", type=int, default=500, help="Number of steps for the warmup in the lr scheduler.")
    parser.add_argument("--lr_num_cycles", type=int, default=1,
        help="Number of hard resets of the lr in cosine_with_restarts scheduler.",
    )
    parser.add_argument("--lr_power", type=float, default=1.0, help="Power factor of the polynomial scheduler.")

    parser.add_argument("--dataloader_num_workers", type=int, default=0,)
    parser.add_argument("--adam_beta1", type=float, default=0.9, help="The beta1 parameter for the Adam optimizer.")
    parser.add_argument("--adam_beta2", type=float, default=0.999, help="The beta2 parameter for the Adam optimizer.")
    parser.add_argument("--adam_weight_decay", type=float, default=1e-2, help="Weight decay to use.")
    parser.add_argument("--adam_epsilon", type=float, default=1e-08, help="Epsilon value for the Adam optimizer")
    parser.add_argument("--max_grad_norm", default=1.0, type=float, help="Max gradient norm.")
    parser.add_argument("--allow_tf32", action="store_true",
        help=(
            "Whether or not to allow TF32 on Ampere GPUs. Can be used to speed up training. For more information, see"
            " https://pytorch.org/docs/stable/notes/cuda.html#tensorfloat-32-tf32-on-ampere-devices"
        ),
    )
    parser.add_argument("--report_to", type=str, default="tensorboard",
        help=(
            'The integration to report the results and logs to. Supported platforms are `"tensorboard"`'
            ' (default), `"wandb"` and `"comet_ml"`. Use `"all"` to report to all integrations.'
        ),
    )

    parser.add_argument("--hf_path", type=str, default="Efficient-Large-Model/Sana_600M_1024px_diffusers")
    
    # cosmos parameters
    parser.add_argument("--experiment_name", type=str, default="official_runs_t2i_fast_205_stage3_0p6b_1024res_synthrealmix_1_1_filtered_with_alpamayo")
    parser.add_argument("--s3_checkpoint_dir", type=str, default="None")
    
    parser.add_argument("--av_model_path", type=str, default="")
    parser.add_argument("--mixed_precision", type=str, default=None, choices=["no", "fp16", "bf16"],)
    parser.add_argument("--enable_xformers_memory_efficient_attention", action="store_true", help="Whether or not to use xformers.")
    parser.add_argument("--set_grads_to_none", action="store_true",)
    
    # resume
    parser.add_argument("--resume", default=None, type=str)
    parser.add_argument("--swinir", default=False, action="store_true")
    parser.add_argument("--unetscratch", default=False, action="store_true")
    parser.add_argument("--use_sched", action="store_true")
    parser.add_argument("--use_large_postnet", action="store_true")
    parser.add_argument("--vae_skip_connection", action="store_true")
    parser.add_argument("--fix_deconv", action="store_true")
    parser.add_argument("--use_reference_image", action="store_true")
    parser.add_argument("--use_ref_cross_attn", action="store_true")
    parser.add_argument("--use_ref_detail_adapter", action="store_true")
    parser.add_argument("--ref_token_count", type=int, default=32)

    if input_args is not None:
        args = parser.parse_args(input_args)
    else:
        args = parser.parse_args()

    return args


def parse_args_unpaired_training():
    """
    Parses command-line arguments used for configuring an unpaired session (CycleGAN-Turbo).
    This function sets up an argument parser to handle various training options.

    Returns:
    argparse.Namespace: The parsed command-line arguments.
   """

    parser = argparse.ArgumentParser(description="Simple example of a ControlNet training script.")

    # fixed random seed
    parser.add_argument("--seed", type=int, default=42, help="A seed for reproducible training.")

    # args for the loss function
    parser.add_argument("--gan_disc_type", default="vagan_clip")
    parser.add_argument("--gan_loss_type", default="multilevel_sigmoid")
    parser.add_argument("--lambda_gan", default=0.5, type=float)
    parser.add_argument("--lambda_idt", default=1, type=float)
    parser.add_argument("--lambda_cycle", default=1, type=float)
    parser.add_argument("--lambda_cycle_lpips", default=10.0, type=float)
    parser.add_argument("--lambda_idt_lpips", default=1.0, type=float)
    parser.add_argument("--lambda_paired_l2", default=1.0, type=float)
    parser.add_argument("--lambda_paired_lpips", default=5.0, type=float)

    # args for dataset and dataloader options
    parser.add_argument("--dataset_folder", required=True, type=str)
    parser.add_argument("--train_img_prep", required=True)
    parser.add_argument("--val_img_prep", required=True)
    parser.add_argument("--dataloader_num_workers", type=int, default=0)
    parser.add_argument("--train_batch_size", type=int, default=4, help="Batch size (per device) for the training dataloader.")
    parser.add_argument("--max_train_epochs", type=int, default=100)
    parser.add_argument("--max_train_steps", type=int, default=None)
    parser.add_argument("--scene_id", type=str, default=None)
    parser.add_argument("--paired_ratio", type=float, default=0.5)

    # args for the model
    parser.add_argument("--pretrained_model_name_or_path", default="stabilityai/sd-turbo")
    parser.add_argument("--revision", default=None, type=str)
    parser.add_argument("--variant", default=None, type=str)
    parser.add_argument("--lora_rank_unet", default=128, type=int)
    parser.add_argument("--lora_rank_vae", default=4, type=int)

    # args for validation and logging
    parser.add_argument("--viz_freq", type=int, default=20)
    parser.add_argument("--output_dir", type=str, required=True)
    parser.add_argument("--report_to", type=str, default="wandb")
    parser.add_argument("--tracker_project_name", type=str, required=True)
    parser.add_argument("--tracker_run_name", type=str, required=True)
    parser.add_argument("--tracker_run_id", type=str, default=None)
    parser.add_argument("--validation_steps", type=int, default=500,)
    parser.add_argument("--validation_num_images", type=int, default=-1, help="Number of images to use for validation. -1 to use all images.")

    # args for the optimization options
    parser.add_argument("--learning_rate", type=float, default=5e-6,)
    parser.add_argument("--adam_beta1", type=float, default=0.9, help="The beta1 parameter for the Adam optimizer.")
    parser.add_argument("--adam_beta2", type=float, default=0.999, help="The beta2 parameter for the Adam optimizer.")
    parser.add_argument("--adam_weight_decay", type=float, default=1e-2, help="Weight decay to use.")
    parser.add_argument("--adam_epsilon", type=float, default=1e-08, help="Epsilon value for the Adam optimizer")
    parser.add_argument("--max_grad_norm", default=10.0, type=float, help="Max gradient norm.")
    parser.add_argument("--lr_scheduler", type=str, default="constant", help=(
        'The scheduler type to use. Choose between ["linear", "cosine", "cosine_with_restarts", "polynomial",'
        ' "constant", "constant_with_warmup"]'
        ),
    )
    parser.add_argument("--lr_warmup_steps", type=int, default=500, help="Number of steps for the warmup in the lr scheduler.")
    parser.add_argument("--lr_num_cycles", type=int, default=1, help="Number of hard resets of the lr in cosine_with_restarts scheduler.",)
    parser.add_argument("--lr_power", type=float, default=1.0, help="Power factor of the polynomial scheduler.")
    parser.add_argument("--gradient_accumulation_steps", type=int, default=1)

    # memory saving options
    parser.add_argument("--allow_tf32", action="store_true",
        help=(
            "Whether or not to allow TF32 on Ampere GPUs. Can be used to speed up training. For more information, see"
            " https://pytorch.org/docs/stable/notes/cuda.html#tensorfloat-32-tf32-on-ampere-devices"
        ),
    )
    parser.add_argument("--gradient_checkpointing", action="store_true",
        help="Whether or not to use gradient checkpointing to save memory at the expense of slower backward pass.")
    parser.add_argument("--mixed_precision", type=str, default=None, choices=["no", "fp16", "bf16"],)
    parser.add_argument("--enable_xformers_memory_efficient_attention", action="store_true", help="Whether or not to use xformers.")

    # resume
    parser.add_argument("--resume", default=None, type=str)
    
    args = parser.parse_args()
    return args


def build_transform(image_prep, interpolation = Image.LANCZOS):
    """
    Constructs a transformation pipeline based on the specified image preparation method.

    Parameters:
    - image_prep (str): A string describing the desired image preparation

    Returns:
    - torchvision.transforms.Compose: A composable sequence of transformations to be applied to images.
    """
    if image_prep == "resized_crop_512":
        T = transforms.Compose([
            transforms.Resize(512, interpolation=transforms.InterpolationMode.LANCZOS),
            transforms.CenterCrop(512),
        ])
    elif image_prep == "resized_random_crop_512":
        T = transforms.Compose([
            transforms.Resize(512, interpolation=transforms.InterpolationMode.LANCZOS),
            transforms.RandomCrop((512, 512)),
        ])
    elif image_prep == "resize_286_randomcrop_256x256_hflip":
        T = transforms.Compose([
            transforms.Resize((286, 286), interpolation=interpolation),
            transforms.RandomCrop((256, 256)),
            transforms.RandomHorizontalFlip(),
        ])
    elif image_prep in ["resize_256", "resize_256x256"]:
        T = transforms.Compose([
            transforms.Resize((256, 256), interpolation=interpolation)
        ])
    elif image_prep in ["resize_512", "resize_512x512"]:
        T = transforms.Compose([
            transforms.Resize((512, 512), interpolation=interpolation)
        ])
    elif image_prep == "resize_576x1024":
        T = transforms.Compose([
            transforms.Resize((576, 1024), interpolation=interpolation),
        ])
    elif image_prep == "resize_288x512":
        T = transforms.Compose([
            transforms.Resize((288, 512), interpolation=interpolation),
        ])
    elif image_prep == "resize_384x704":
        T = transforms.Compose([
            transforms.Resize((384, 704), interpolation=interpolation),
        ])
    elif image_prep == "resize_448x832":
        T = transforms.Compose([
            transforms.Resize((448, 832), interpolation=interpolation),
        ])        
    elif image_prep == "resize_200x360":
        T = transforms.Compose([
            transforms.Resize((200, 360), interpolation=interpolation),
        ])
    elif image_prep == "resize_544x960":
        T = transforms.Compose([
            transforms.Resize((544, 960), interpolation=interpolation),
        ])
    elif image_prep == "resize_384x672":
        T = transforms.Compose([
            transforms.Resize((384, 672), interpolation=interpolation),
        ])
    elif image_prep == "resize_768x1360":
        T = transforms.Compose([
            transforms.Resize((768, 1360), interpolation=interpolation),
        ])
    elif image_prep == "resize_416x736":
        T = transforms.Compose([
            transforms.Resize((416, 736), interpolation=interpolation),
        ])
    elif image_prep == "resize_1088x1920":
        T = transforms.Compose([
            transforms.Resize((1088, 1920), interpolation=interpolation),
        ])
    elif image_prep == "resize_2176x3840":
        T = transforms.Compose([
            transforms.Resize((2176, 3840), interpolation=interpolation),
        ])
    elif image_prep == "resize_576x1024_cropcar":
        T = transforms.Compose([
            transforms.Resize((576, 1024), interpolation=interpolation),
            transforms.Lambda(lambda img: F.crop(img, 0, 0, 416, 1024)),    # crop out the car
        ])
    elif image_prep == "resize_576x1024_cropcar_randomcrop_400x400":
        T = transforms.Compose([
            transforms.Resize((576, 1024), interpolation=interpolation),
            transforms.Lambda(lambda img: F.crop(img, 0, 0, 416, 1024)),    # crop out the car
            transforms.RandomCrop((400, 400)),
        ])
    elif image_prep == "resize_1024x576":
        T = transforms.Compose([
            transforms.Resize((1024, 576), interpolation=interpolation),
        ])
    elif image_prep == "no_resize":
        T = transforms.Lambda(lambda x: x)
    return T

MASK_FOLDER_MAPPING = {
    50: "xpeng_data_process/assets/Vehicle_Mask/F30_Masks",
    43: "xpeng_data_process/assets/Vehicle_Mask/E38A_Masks",
    21: "xpeng_data_process/assets/Vehicle_Mask/E28A_Masks",
    40: "xpeng_data_process/assets/Vehicle_Mask/E38_Masks",
    60: "xpeng_data_process/assets/Vehicle_Mask/H93_Masks",
    70: "xpeng_data_process/assets/Vehicle_Mask/F57_Masks",
    201: "xpeng_data_process/assets/Vehicle_Mask/XP5_201_Masks",
    205: "xpeng_data_process/assets/Vehicle_Mask/XP5_269_Masks",
    203: "xpeng_data_process/assets/Vehicle_Mask/E38B_Masks",
    206: "xpeng_data_process/assets/Vehicle_Mask/F30B_Masks",
    231: "xpeng_data_process/assets/Vehicle_Mask/H93AS_Masks",
    269: "xpeng_data_process/assets/Vehicle_Mask/XP5_269_Masks",
}


def calculate_psnr(img1, img2, mask=None):
    if isinstance(img1, Image.Image):
        img1 = np.array(img1)
    if isinstance(img2, Image.Image):
        img2 = np.array(img2)
    if img1.shape != img2.shape:
        img2_pil = Image.fromarray(img2)
        img2_pil = img2_pil.resize((img1.shape[1], img1.shape[0]), Image.Resampling.LANCZOS)
        img2 = np.array(img2_pil)

    img1 = img1.astype(np.float32) / 255.0
    img2 = img2.astype(np.float32) / 255.0
    if mask is not None:
        if mask.shape[:2] != img1.shape[:2]:
            mask = cv2.resize(mask, (img1.shape[1], img1.shape[0]), interpolation=cv2.INTER_NEAREST)
        valid_mask = mask > 0
        if img1.ndim == 3:
            valid_mask = np.broadcast_to(valid_mask[:, :, np.newaxis], img1.shape)
        if not np.any(valid_mask):
            return float("nan")
        mse = np.mean((img1[valid_mask] - img2[valid_mask]) ** 2)
    else:
        mse = np.mean((img1 - img2) ** 2)

    if mse == 0:
        return float("inf")
    return float(20 * np.log10(1.0 / np.sqrt(mse)))


def get_cam_name_from_img_id(data, img_id):
    output_img_path = data[img_id]["target_image"]
    return output_img_path.split("/")[-2]


def debug_collate_with_paths(batch):
    try:
        return default_collate(batch)
    except Exception as exc:
        print("[debug_collate_with_paths] Failed to collate batch.", file=sys.stderr, flush=True)
        print(f"[debug_collate_with_paths] Exception: {exc}", file=sys.stderr, flush=True)
        for idx, sample in enumerate(batch):
            if not isinstance(sample, dict):
                print(
                    f"[debug_collate_with_paths] sample[{idx}] type={type(sample)} value={sample}",
                    file=sys.stderr,
                    flush=True,
                )
                continue
            print(
                "[debug_collate_with_paths] "
                f"sample[{idx}] cam={sample.get('cam_name')} "
                f"input={sample.get('conditioning_image_path')} "
                f"target={sample.get('output_image_path')} "
                f"ref={sample.get('reference_image_path')}",
                file=sys.stderr,
                flush=True,
            )
            for key in ("conditioning_pixel_values", "output_pixel_values", "reference_pixel_values", "mask"):
                value = sample.get(key)
                if isinstance(value, torch.Tensor):
                    print(
                        f"[debug_collate_with_paths] sample[{idx}] {key}.shape={tuple(value.shape)}",
                        file=sys.stderr,
                        flush=True,
                    )
                elif isinstance(value, np.ndarray):
                    print(
                        f"[debug_collate_with_paths] sample[{idx}] {key}.shape={tuple(value.shape)}",
                        file=sys.stderr,
                        flush=True,
                    )
        raise


class CamGroupedBatchSampler(torch.utils.data.Sampler):
    def __init__(self, dataset, batch_size, drop_last=False, seed=42):
        self.dataset = dataset
        self.batch_size = batch_size
        self.drop_last = drop_last
        self.seed = seed
        self.epoch = 0
        self.cam_to_indices = {}
        for idx in range(len(dataset)):
            img_id = dataset.img_names[idx]
            cam_name = get_cam_name_from_img_id(dataset.data, img_id)
            self.cam_to_indices.setdefault(cam_name, []).append(idx)
        self._all_batches = []
        self._cursor = 0
        self._rebuild_batches()

    def set_epoch(self, epoch):
        self.epoch = int(epoch)
        self._rebuild_batches()
        if len(self._all_batches) > 0:
            self._cursor = (self.epoch * 9973) % len(self._all_batches)

    def _rebuild_batches(self):
        rng = random.Random(self.seed + self.epoch)
        all_batches = []
        for indices in self.cam_to_indices.values():
            shuffled = indices.copy()
            rng.shuffle(shuffled)
            for i in range(0, len(shuffled), self.batch_size):
                batch = shuffled[i:i + self.batch_size]
                if len(batch) == self.batch_size or not self.drop_last:
                    all_batches.append(batch)
        rng.shuffle(all_batches)
        self._all_batches = all_batches
        self._cursor = 0

    def __iter__(self):
        total = len(self._all_batches)
        if total == 0:
            return
        for _ in range(total):
            idx = self._cursor % total
            yield self._all_batches[idx]
            self._cursor = (self._cursor + 1) % total

    def __len__(self):
        total = 0
        for indices in self.cam_to_indices.values():
            if self.drop_last:
                total += len(indices) // self.batch_size
            else:
                total += (len(indices) + self.batch_size - 1) // self.batch_size
        return total


class PairedDatasetV2(torch.utils.data.Dataset):
    @staticmethod
    def _align_to_multiple(value, multiple=16):
        aligned = (int(value) // multiple) * multiple
        return max(aligned, multiple)

    @staticmethod
    def _load_from_json(json_path, split):
        """Load data from JSON file"""
        with open(json_path, "r") as f:
            json_data = json.load(f)[split]
        return json_data, list(json_data.keys())
        
    @staticmethod    
    def _load_from_directory(dir_path, split):
        """Load data from directory structure"""
        input_dir = os.path.join(dir_path, f'{split}_A')
        output_dir = os.path.join(dir_path, f'{split}_B')
        caption_file = os.path.join(dir_path, f'{split}_prompts.json')

        with open(caption_file, "r") as f:
            captions = json.load(f)
        input_files = list(captions.keys())

        new_data = {}
        for img_file in tqdm(input_files, desc=f"Loading {split} from {os.path.basename(dir_path)}"):
            new_data[img_file] = {
                "image": os.path.join(input_dir, img_file),
                "target_image": os.path.join(output_dir, img_file),
                "prompt": captions[img_file] # Empty string if no caption exists
            }
        
        return new_data, input_files
            
    def __init__(
        self,
        dataset_folder,
        split,
        image_prep=None,
        tokenizer=None,
        cam_names=("cam0", "cam2", "cam3", "cam4", "cam5", "cam6", "cam7"),
        height=576,
        width=1024,
        enable_dual_resolution_bucket=False,
        bucket_16_9_height=576,
        bucket_16_9_width=1024,
        bucket_5_4_height=768,
        bucket_5_4_width=960,
    ):
        super().__init__()
        self.data = {}
        self.img_names = []
        
        # Split the dataset_folder string into individual paths
        data_sources = [source.strip() for source in dataset_folder.split(',')]
        
        for source in data_sources:
            if source.endswith('.json'):
                data, file_names = self._load_from_json(source, split)
            else:
                data, file_names = self._load_from_directory(source, split)

            self.data.update(data)
            self.img_names.extend(file_names)

        self.image_prep = image_prep
        self.T = build_transform(image_prep) if image_prep is not None else None
        self.tokenizer = tokenizer
        self.mask_dict = {}
        self.image_size = (height, width)
        self.enable_dual_resolution_bucket = enable_dual_resolution_bucket
        self.bucket_16_9_size = (bucket_16_9_height, bucket_16_9_width)
        self.bucket_5_4_size = (bucket_5_4_height, bucket_5_4_width)
        self.cam_names = cam_names
        self.code_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        # 车型级缓存：key=vehicle_model, value={cam_name: mask}
        self.vehicle_mask_cache = {}
        # clip -> vehicle_model（int 或 None）
        self.clip_vehicle_model_cache = {}

    def _select_image_size(self, origin_input_width, origin_input_height):
        if origin_input_height <= 0:
            w, h = self.image_size[1], self.image_size[0]
            return self._align_to_multiple(w), self._align_to_multiple(h)
        if self.enable_dual_resolution_bucket:
            aspect = origin_input_width / origin_input_height
            aspect_16_9 = 16.0 / 9.0
            aspect_5_4 = 5.0 / 4.0
            if abs(aspect - aspect_16_9) <= abs(aspect - aspect_5_4):
                w, h = self.bucket_16_9_size[1], self.bucket_16_9_size[0]
            else:
                w, h = self.bucket_5_4_size[1], self.bucket_5_4_size[0]
            return self._align_to_multiple(w), self._align_to_multiple(h)
        if self.image_size[0] == 0 and self.image_size[1] == 0:
            w = origin_input_width - origin_input_width % 8
            h = origin_input_height - origin_input_height % 8
            return self._align_to_multiple(w), self._align_to_multiple(h)
        w, h = self.image_size[1], self.image_size[0]
        return self._align_to_multiple(w), self._align_to_multiple(h)

    def _resolve_vehicle_model(self, img_id, clip_id):
        if clip_id in self.clip_vehicle_model_cache:
            return self.clip_vehicle_model_cache[clip_id]

        input_img_path = self.data[img_id]["image"]
        src_img_path = "/".join(input_img_path.split("/")[:-4])
        metadata_path = os.path.join(src_img_path, "metadata.json")

        vehicle_model = None
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, "r") as f:
                    metadata = json.load(f)
                vehicle_model = metadata.get("vehicle_model", None)
            except Exception as e:
                print(f"Failed to read metadata: {metadata_path}, error: {e}")
        else:
            print(f"Metadata file not found: {metadata_path}")

        self.clip_vehicle_model_cache[clip_id] = vehicle_model
        return vehicle_model

    def _build_vehicle_masks(self, vehicle_model, target_height, target_width):
        cache_key = (vehicle_model, target_height, target_width)
        if cache_key in self.vehicle_mask_cache:
            return self.vehicle_mask_cache[cache_key]

        mask_dict = {}
        mask_folder = MASK_FOLDER_MAPPING.get(vehicle_model, None)
        if mask_folder is not None:
            mask_folder = f"{mask_folder}_Origin"

        for cam_name in self.cam_names:
            mask = None
            if mask_folder is not None:
                mask_file_name = f"_{cam_name}_mask.png"
                mask_path = os.path.join(self.code_dir, mask_folder, mask_file_name)
                if os.path.exists(mask_path):
                    mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
                    if target_height > 0 and target_width > 0:
                        mask = cv2.resize(
                            mask,
                            (target_width, target_height),
                            interpolation=cv2.INTER_NEAREST
                        )
                else:
                    if target_height > 0 and target_width > 0:
                        mask = np.ones((target_height, target_width), dtype=np.uint8) * 255
                    else:
                        mask = None
            if mask is not None:
                mask = np.expand_dims(mask, axis=0)
            mask_dict[cam_name] = mask

        self.vehicle_mask_cache[cache_key] = mask_dict
        return mask_dict
    
    def __len__(self):
        """
        Returns:
        int: The total number of items in the dataset.
        """
        return len(self.img_names)

    def preprocess_image(self, input_img, target_height, target_width):
        if target_height > 0 and target_width > 0:
            input_img = input_img.resize((target_width, target_height), Image.LANCZOS)
        elif self.T is not None:
            input_img = self.T(input_img)
        img_t = F.to_tensor(input_img)
        img_t = F.normalize(img_t, mean=[0.5], std=[0.5])
        return img_t

    
    def __getitem__(self, idx):

        num_samples = len(self.img_names)
        if num_samples == 0:
            raise RuntimeError("Dataset is empty.")

        idx = int(idx) % num_samples
        last_err = None
        for offset in range(num_samples):
            cur_idx = (idx + offset) % num_samples
            img_name = self.img_names[cur_idx]

            input_img_path = self.data[img_name]["image"]
            output_img_path = self.data[img_name]["target_image"]
            ref_img_path = self.data[img_name].get("ref_image")
            caption = self.data[img_name].get("prompt", "")
            clip_id = self.data[img_name].get("clip_id", os.path.dirname(input_img_path))
            try:
                input_img = Image.open(input_img_path).convert("RGB")
                output_img = Image.open(output_img_path).convert("RGB")
                ref_img = Image.open(ref_img_path).convert("RGB") if ref_img_path else None
                origin_input_width, origin_input_height = input_img.size
                break
            except Exception as exc:
                last_err = exc
                print(f"Error loading image pair, skip sample idx={cur_idx}: {input_img_path}, {output_img_path}; err={exc}")
        else:
            raise RuntimeError(
                f"Failed to load any valid sample after trying {num_samples} items; last_err={last_err}"
            )

        new_width, new_height = self._select_image_size(origin_input_width, origin_input_height)
        img_t = self.preprocess_image(input_img, new_height, new_width)
        output_t = self.preprocess_image(output_img, new_height, new_width)
        ref_t = self.preprocess_image(ref_img, new_height, new_width) if ref_img is not None else img_t.clone()

        cam_name = output_img_path.split("/")[-2]
        vehicle_model = self._resolve_vehicle_model(img_name, clip_id)
        mask_dict = self._build_vehicle_masks(vehicle_model, new_height, new_width)
        mask = mask_dict[cam_name]
        if mask is None:
            mask = np.ones((1, new_height, new_width), dtype=np.uint8) * 255
        elif mask.shape[-2:] != (new_height, new_width):
            # mask is numpy array, use cv2 to resize
            mask = cv2.resize(mask[0], (new_width, new_height), interpolation=cv2.INTER_NEAREST)
            mask = mask[np.newaxis, :, :]

        out = {
            "output_pixel_values": output_t,
            "conditioning_pixel_values": img_t,
            "reference_pixel_values": ref_t,
            "caption": caption,
            "mask": mask,
            "cam_name": cam_name,
            "conditioning_image_path": input_img_path,
            "output_image_path": output_img_path,
            "reference_image_path": ref_img_path,
            "origin_input_width": origin_input_width,
            "origin_input_height": origin_input_height,
        }
        if self.tokenizer is not None:
            input_ids = self.tokenizer(
                caption,
                max_length=self.tokenizer.model_max_length,
                padding="max_length",
                truncation=True,
                return_tensors="pt",
            ).input_ids
            out["input_ids"] = input_ids
        return out
