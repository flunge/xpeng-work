# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
import lpips
import clip
import random
import numpy as np
import torch
import torch.nn.functional as F
import torch.utils.checkpoint
import torchvision
import transformers
from torchvision.transforms.functional import crop
from accelerate import Accelerator, DataLoaderConfiguration
from accelerate.utils import set_seed
from torchvision import transforms
from tqdm.auto import tqdm
from glob import glob
from torch.utils.tensorboard import SummaryWriter

import diffusers
from diffusers.utils.import_utils import is_xformers_available
from diffusers.optimization import get_scheduler

from pix2pix_turbo_nocond_cosmos_base_faster_tokenizer import (
    Pix2Pix_Turbo,
    load_ckpt_from_state_dict,
    save_ckpt,
)
from utils.training_utils import (
    CamGroupedBatchSampler,
    PairedDatasetV2,
    debug_collate_with_paths,
    parse_args_paired_training,
    save_config,
)
from utils.eval_utils import evaluate_test_psnr
from utils.style_loss import style_loss


def save_image_local(tensor, path):
    pil_img = transforms.ToPILImage()(tensor.float().cpu().clamp(-1, 1) * 0.5 + 0.5)
    pil_img.save(path)


def masked_mse_per_item(pred, tgt, mask):
    diff_sq = (pred - tgt) ** 2
    num_masked = mask.sum(dim=(1, 2, 3)).clamp(min=1)
    return (diff_sq * mask).sum(dim=(1, 2, 3)) / num_masked


def random_square_crop_size(height, width, min_size=128, max_size=512):
    upper = min(height, width, max_size)
    lower = min(min_size, upper)
    if upper <= 0:
        raise ValueError(f"Invalid crop size: height={height}, width={width}")
    if lower == upper:
        return upper
    return random.randint(lower, upper)


def unique_parameters(parameters):
    unique_params = []
    seen_ids = set()
    for param in parameters:
        param_id = id(param)
        if param_id in seen_ids:
            continue
        seen_ids.add(param_id)
        unique_params.append(param)
    return unique_params


def promote_trainable_modules_to_fp32(net_pix2pix, args):
    if args.train_full_unet:
        net_pix2pix.unet.dit.to(dtype=torch.float32)
        net_pix2pix.unet.precision = torch.float32
        net_pix2pix.unet.tensor_kwargs = {"device": "cuda", "dtype": torch.float32}
    if args.use_ref_cross_attn:
        net_pix2pix.ref_token_adapter.to(dtype=torch.float32)
    if args.use_ref_detail_adapter:
        net_pix2pix.ref_detail_adapter.to(dtype=torch.float32)
    if not args.freeze_vae:
        if args.freeze_vae_encoder:
            net_pix2pix.vae.decoder.to(dtype=torch.float32)
        else:
            net_pix2pix.vae.to(dtype=torch.float32)
        if hasattr(net_pix2pix.vae, "dtype"):
            net_pix2pix.vae.dtype = torch.float32


def main(args):
    os.makedirs(args.output_dir, exist_ok=True)
    output_path = os.path.join(args.output_dir, args.tracker_run_name) if args.tracker_run_name else args.output_dir
    dataloader_config = DataLoaderConfiguration(even_batches=False)
    accelerator = Accelerator(
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        mixed_precision=args.mixed_precision,
        dataloader_config=dataloader_config,
        log_with=args.report_to,
        project_dir=os.path.join(output_path, "tensorboard"),
    )

    if accelerator.is_local_main_process:
        transformers.utils.logging.set_verbosity_warning()
        diffusers.utils.logging.set_verbosity_info()
    else:
        transformers.utils.logging.set_verbosity_error()
        diffusers.utils.logging.set_verbosity_error()

    if args.seed is not None:
        set_seed(args.seed)

    if accelerator.is_main_process:
        os.makedirs(output_path, exist_ok=True)
        os.makedirs(os.path.join(output_path, "checkpoints"), exist_ok=True)
        os.makedirs(os.path.join(output_path, "eval"), exist_ok=True)
        os.makedirs(os.path.join(output_path, "viz"), exist_ok=True)
        save_config(output_path, args)
    accelerator.wait_for_everyone()

    net_pix2pix = Pix2Pix_Turbo(
        freeze_vae_encoder=args.freeze_vae_encoder,
        freeze_vae=args.freeze_vae,
        train_full_unet=args.train_full_unet,
        timestep=args.timestep,
        use_sched=args.use_sched,
        vae_skip_connection=args.vae_skip_connection,
        pretrained_path=args.pretrained_path,
        use_reference_image=args.use_reference_image,
        use_ref_cross_attn=args.use_ref_cross_attn,
        use_ref_detail_adapter=args.use_ref_detail_adapter,
        ref_token_count=args.ref_token_count,
    )
    net_pix2pix.set_train()
    promote_trainable_modules_to_fp32(net_pix2pix, args)

    if args.enable_xformers_memory_efficient_attention and not args.swinir:
        if is_xformers_available():
            net_pix2pix.unet.enable_xformers_memory_efficient_attention()
        else:
            raise ValueError("xformers is not available, please install it by running `pip install xformers`")

    if args.gradient_checkpointing:
        net_pix2pix.unet.enable_gradient_checkpointing()

    if args.allow_tf32:
        torch.backends.cuda.matmul.allow_tf32 = True

    net_lpips = lpips.LPIPS(net="vgg").cuda()
    net_lpips.requires_grad_(False)

    if args.lambda_clipsim > 0:
        net_clip, _ = clip.load("ViT-B/32", device="cuda")
        net_clip.requires_grad_(False)
        net_clip.eval()
    else:
        net_clip = None

    net_vgg = torchvision.models.vgg16(pretrained=True).features
    for param in net_vgg.parameters():
        param.requires_grad_(False)

    layers_to_opt = []
    if args.train_full_unet:
        print("=" * 50)
        print("adding unet parameters")
        print("=" * 50)
        layers_to_opt += list(net_pix2pix.unet.parameters())
    if not args.freeze_vae:
        if args.freeze_vae_encoder:
            print("=" * 50)
            print("adding vae decoder parameters")
            print("=" * 50)
            layers_to_opt += list(net_pix2pix.vae.decoder.parameters())
        else:
            print("=" * 50)
            print("adding whole vae parameters")
            print("=" * 50)
            layers_to_opt += list(net_pix2pix.vae.parameters())
    if args.use_ref_cross_attn:
        print("=" * 50)
        print("adding reference token adapter parameters")
        print("=" * 50)
        layers_to_opt += list(net_pix2pix.ref_token_adapter.parameters())
    if args.use_ref_detail_adapter:
        print("=" * 50)
        print("adding reference detail adapter parameters")
        print("=" * 50)
        layers_to_opt += list(net_pix2pix.ref_detail_adapter.parameters())
    layers_to_opt = unique_parameters(layers_to_opt)

    optimizer = torch.optim.AdamW(
        layers_to_opt,
        lr=args.learning_rate,
        betas=(args.adam_beta1, args.adam_beta2),
        weight_decay=args.adam_weight_decay,
        eps=args.adam_epsilon,
    )

    dataset_train = PairedDatasetV2(
        dataset_folder=args.dataset_folder,
        image_prep=args.train_image_prep,
        split="train",
        height=args.image_height,
        width=args.image_width,
        enable_dual_resolution_bucket=args.enable_dual_resolution_bucket,
        bucket_16_9_height=args.bucket_16_9_height,
        bucket_16_9_width=args.bucket_16_9_width,
        bucket_5_4_height=args.bucket_5_4_height,
        bucket_5_4_width=args.bucket_5_4_width,
    )
    batch_sampler = CamGroupedBatchSampler(
        dataset_train,
        batch_size=args.train_batch_size,
        drop_last=True,
    )
    dl_train = torch.utils.data.DataLoader(
        dataset_train,
        batch_sampler=batch_sampler,
        num_workers=args.dataloader_num_workers,
        collate_fn=debug_collate_with_paths,
    )

    dataset_val = PairedDatasetV2(
        dataset_folder=args.dataset_folder,
        image_prep=args.test_image_prep,
        split="test",
        height=args.image_height,
        width=args.image_width,
        enable_dual_resolution_bucket=args.enable_dual_resolution_bucket,
        bucket_16_9_height=args.bucket_16_9_height,
        bucket_16_9_width=args.bucket_16_9_width,
        bucket_5_4_height=args.bucket_5_4_height,
        bucket_5_4_width=args.bucket_5_4_width,
    )
    dl_val = torch.utils.data.DataLoader(
        dataset_val,
        batch_size=1,
        shuffle=False,
        num_workers=0,
        collate_fn=debug_collate_with_paths,
    )

    num_update_steps_per_epoch = len(dl_train)
    if args.max_steps_per_epoch > 0:
        num_update_steps_per_epoch = min(num_update_steps_per_epoch, args.max_steps_per_epoch)
    planned_total_steps = num_update_steps_per_epoch * args.num_training_epochs
    total_train_steps = args.max_train_steps if args.max_train_steps and args.max_train_steps > 0 else planned_total_steps

    lr_scheduler = get_scheduler(
        args.lr_scheduler,
        optimizer=optimizer,
        num_warmup_steps=args.lr_warmup_steps,
        num_training_steps=total_train_steps,
        num_cycles=args.lr_num_cycles,
        power=args.lr_power,
    )
    global_step = 0
    resume_info = {}
    if args.resume is not None:
        if os.path.isdir(args.resume):
            ckpt_files = glob(os.path.join(args.resume, "*.pkl"))
            assert len(ckpt_files) > 0, f"No checkpoint files found: {args.resume}"

            def _step_from_path(path):
                name = os.path.basename(path).replace(".pkl", "")
                if name == "model":
                    return 0
                return int(name.replace("model_", ""))

            ckpt_files = sorted(ckpt_files, key=_step_from_path)
            ckpt_path = ckpt_files[-1]
            print("=" * 50)
            print(f"Loading checkpoint from {ckpt_path}")
            print("=" * 50)
            net_pix2pix, optimizer, resume_info = load_ckpt_from_state_dict(
                net_pix2pix,
                optimizer,
                ckpt_path,
                lr_scheduler=lr_scheduler,
            )
            global_step = resume_info.get("global_step") or _step_from_path(ckpt_path)
        elif args.resume.endswith(".pkl"):
            print("=" * 50)
            print(f"Loading checkpoint from {args.resume}")
            print("=" * 50)
            net_pix2pix, optimizer, resume_info = load_ckpt_from_state_dict(
                net_pix2pix,
                optimizer,
                args.resume,
                lr_scheduler=lr_scheduler,
                load_optimizer=False,
            )
            global_step = resume_info.get("global_step")
            if global_step is None:
                try:
                    global_step = int(os.path.basename(args.resume).replace("model_", "").replace(".pkl", ""))
                except ValueError:
                    global_step = 0
        else:
            raise NotImplementedError(f"Invalid resume path: {args.resume}")
        print(f"Resume info: global_step={global_step}, resume_info={resume_info}")
    else:
        print("=" * 50)
        print("Training from scratch")
        print("=" * 50)

    weight_dtype = torch.float32
    if accelerator.mixed_precision == "fp16":
        weight_dtype = torch.float16
    elif accelerator.mixed_precision == "bf16":
        weight_dtype = torch.bfloat16

    net_pix2pix.to(accelerator.device)
    net_lpips.to(accelerator.device, dtype=weight_dtype)
    net_vgg.to(accelerator.device, dtype=weight_dtype)
    if net_clip is not None:
        net_clip.to(accelerator.device, dtype=weight_dtype)

    net_pix2pix, optimizer, dl_train, dl_val = accelerator.prepare(
        net_pix2pix,
        optimizer,
        dl_train,
        dl_val,
    )
    if net_clip is not None:
        net_clip = accelerator.prepare(net_clip)
    net_lpips, net_vgg = accelerator.prepare(net_lpips, net_vgg)

    t_clip_renorm = transforms.Normalize(
        mean=(0.48145466, 0.4578275, 0.40821073),
        std=(0.26862954, 0.26130258, 0.27577711),
    )
    t_vgg_renorm = transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225))

    start_epoch = 0
    if resume_info:
        if resume_info.get("epoch") is not None:
            start_epoch = int(resume_info["epoch"])
        elif num_update_steps_per_epoch > 0:
            start_epoch = int(global_step) // num_update_steps_per_epoch

    if accelerator.is_main_process:
        tracker_config = dict(vars(args))
        tracker_config.pop("_config_path", None)
        accelerator.init_trackers(args.tracker_project_name, config=tracker_config)
        global_batch_size = args.train_batch_size * accelerator.num_processes * args.gradient_accumulation_steps
        print(
            f"Distributed setup: world_size={accelerator.num_processes}, "
            f"per_device_batch={args.train_batch_size}, global_batch={global_batch_size}"
        )
        print(
            f"Scheduler total_train_steps={total_train_steps} "
            f"(steps_per_epoch={num_update_steps_per_epoch}, epochs={args.num_training_epochs})"
        )
        if start_epoch > 0:
            print(f"Resume: start_epoch={start_epoch}, global_step={global_step}")

    def _scalar_for_display(value):
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, (np.floating, np.integer)):
            return float(value)
        if hasattr(value, "item"):
            return value.item()
        return value

    def _write_tensorboard_images(step, x_src, x_tgt, x_tgt_pred, x_ref=None):
        for tracker in accelerator.trackers:
            if hasattr(tracker, "writer") and isinstance(tracker.writer, SummaryWriter):
                limit = min(x_src.shape[0], 4)
                for idx in range(limit):
                    tracker.writer.add_image(
                        f"train/source_{idx}",
                        (x_src[idx].float().detach().cpu() * 0.5 + 0.5).clamp(0, 1),
                        step,
                    )
                    tracker.writer.add_image(
                        f"train/target_{idx}",
                        (x_tgt[idx].float().detach().cpu() * 0.5 + 0.5).clamp(0, 1),
                        step,
                    )
                    tracker.writer.add_image(
                        f"train/model_output_{idx}",
                        (x_tgt_pred[idx].float().detach().cpu() * 0.5 + 0.5).clamp(0, 1),
                        step,
                    )
                    if x_ref is not None:
                        tracker.writer.add_image(
                            f"train/reference_{idx}",
                            (x_ref[idx].float().detach().cpu() * 0.5 + 0.5).clamp(0, 1),
                            step,
                        )
                break

    def _save_checkpoint(epoch_idx, current_global_step, is_final=False):
        if not accelerator.is_main_process:
            return
        if is_final:
            ckpt_dir = os.path.join(output_path, "checkpoints")
        else:
            ckpt_dir = os.path.join(
                output_path,
                f"checkpoints_epoch_{epoch_idx:04d}_step_{current_global_step}",
            )
        os.makedirs(ckpt_dir, exist_ok=True)
        save_ckpt(
            accelerator.unwrap_model(net_pix2pix),
            optimizer,
            os.path.join(ckpt_dir, "model.pkl"),
            train_full_unet=args.train_full_unet,
            freeze_vae=args.freeze_vae,
            epoch=epoch_idx,
            global_step=current_global_step,
            lr_scheduler=lr_scheduler,
        )
        save_config(ckpt_dir, args)

    def _evaluate_test_psnr():
        unwrapped_model = accelerator.unwrap_model(net_pix2pix)

        def _predict(batch_val):
            x_src_val = batch_val["conditioning_pixel_values"].to(accelerator.device, dtype=weight_dtype)
            x_ref_val = batch_val["reference_pixel_values"].to(accelerator.device, dtype=weight_dtype)
            ref_input_val = x_ref_val if args.use_reference_image else None
            return unwrapped_model(x_src_val, ref=ref_input_val)

        return evaluate_test_psnr(
            accelerator=accelerator,
            dataset_val=dataset_val,
            dl_val=dl_val,
            predict_fn=_predict,
            set_eval_fn=unwrapped_model.set_eval,
            set_train_fn=unwrapped_model.set_train,
        )

    if args.resume is None:
        accelerator.wait_for_everyone()
        _save_checkpoint(0, global_step)
        accelerator.wait_for_everyone()

    # if args.eval_freq > 0:
    #     accelerator.wait_for_everyone()
    #     init_eval_logs = _evaluate_test_psnr()
    #     accelerator.wait_for_everyone()
    #     if accelerator.is_main_process and len(init_eval_logs) > 0:
    #         init_eval_display = ", ".join(f"{k}={v:.4f}" for k, v in sorted(init_eval_logs.items()))
    #         print(f"[EVAL][INIT] step={global_step}: {init_eval_display}", flush=True)
    #         accelerator.log(init_eval_logs, step=global_step)

    for epoch in range(start_epoch, args.num_training_epochs):
        if hasattr(batch_sampler, "set_epoch"):
            batch_sampler.set_epoch(epoch)

        for step, batch in enumerate(dl_train):
            if args.max_steps_per_epoch > 0 and step >= args.max_steps_per_epoch:
                break
            if global_step >= total_train_steps:
                break

            l_acc = [net_pix2pix]
            with accelerator.accumulate(*l_acc):
                x_src = batch["conditioning_pixel_values"]
                x_tgt = batch["output_pixel_values"]
                x_ref = batch["reference_pixel_values"]
                x_mask = (batch["mask"] > 1).to(x_tgt.device).float()
                cam_names = batch["cam_name"]
                B, C, H, W = x_src.shape

                ref_input = x_ref if args.use_reference_image else None
                x_tgt_pred = net_pix2pix(x_src, ref=ref_input)

                loss_l2_per_sample = masked_mse_per_item(
                    x_tgt_pred.float(),
                    x_tgt.float(),
                    x_mask,
                ) * args.lambda_l2
                loss_l2 = loss_l2_per_sample.mean()

                x_tgt_masked = x_tgt.float() * x_mask
                x_tgt_pred_masked = x_tgt_pred.float() * x_mask

                crop_size = random_square_crop_size(H, W)
                top = 0 if H == crop_size else random.randint(0, H - crop_size)
                left = 0 if W == crop_size else random.randint(0, W - crop_size)
                loss_lpips_per_sample = net_lpips(
                    crop(x_tgt_pred_masked, top, left, crop_size, crop_size),
                    crop(x_tgt_masked, top, left, crop_size, crop_size),
                ).flatten() * args.lambda_lpips
                loss_lpips = loss_lpips_per_sample.mean()

                loss = loss_l2 + loss_lpips
                loss_total_per_sample = loss_l2_per_sample + loss_lpips_per_sample

                if args.lambda_gram > 0:
                    if global_step > args.gram_loss_warmup_steps:
                        gram_crop = min(H, W, 512)
                        gram_top = 0 if H == gram_crop else random.randint(0, H - gram_crop)
                        gram_left = 0 if W == gram_crop else random.randint(0, W - gram_crop)
                        x_tgt_pred_renorm = t_vgg_renorm(x_tgt_pred * 0.5 + 0.5)
                        x_tgt_pred_renorm = crop(x_tgt_pred_renorm, gram_top, gram_left, gram_crop, gram_crop)
                        x_tgt_renorm = t_vgg_renorm(x_tgt * 0.5 + 0.5)
                        x_tgt_renorm = crop(x_tgt_renorm, gram_top, gram_left, gram_crop, gram_crop)
                        x_mask_crop = crop(x_mask, gram_top, gram_left, gram_crop, gram_crop)
                        x_tgt_pred_renorm = (x_tgt_pred_renorm * x_mask_crop).to(weight_dtype)
                        x_tgt_renorm = (x_tgt_renorm * x_mask_crop).to(weight_dtype)
                        loss_gram = style_loss(
                            x_tgt_pred_renorm,
                            x_tgt_renorm,
                            net_vgg,
                        ) * args.lambda_gram
                        loss += loss_gram
                    else:
                        loss_gram = torch.tensor(0.0, device=accelerator.device, dtype=weight_dtype)
                else:
                    loss_gram = torch.tensor(0.0, device=accelerator.device, dtype=weight_dtype)

                if args.lambda_clipsim > 0:
                    x_tgt_pred_renorm = t_clip_renorm(x_tgt_pred * 0.5 + 0.5)
                    x_tgt_pred_renorm = F.interpolate(
                        x_tgt_pred_renorm,
                        (224, 224),
                        mode="bilinear",
                        align_corners=False,
                    )
                    caption_tokens = clip.tokenize(batch["caption"], truncate=True).to(x_tgt_pred.device)
                    clipsim, _ = net_clip(x_tgt_pred_renorm, caption_tokens)
                    loss_clipsim = 1 - clipsim.mean() / 100
                    loss += loss_clipsim * args.lambda_clipsim
                else:
                    loss_clipsim = torch.tensor(0.0, device=accelerator.device, dtype=weight_dtype)

                accelerator.backward(loss, retain_graph=False)
                if accelerator.sync_gradients:
                    accelerator.clip_grad_norm_(layers_to_opt, args.max_grad_norm)
                optimizer.step()
                lr_scheduler.step()
                optimizer.zero_grad(set_to_none=args.set_grads_to_none)

            if accelerator.sync_gradients:
                global_step += 1

                eval_logs = {}
                if args.eval_freq > 0 and global_step % args.eval_freq == 0:
                    accelerator.wait_for_everyone()
                    eval_logs = _evaluate_test_psnr()
                    accelerator.wait_for_everyone()

                if accelerator.is_main_process:
                    logs = {}
                    for cam in sorted(set(cam_names)):
                        idxs = [idx for idx, name in enumerate(cam_names) if name == cam]
                        if len(idxs) > 0:
                            logs[f"loss/cam_{cam}"] = loss_total_per_sample.detach()[idxs].mean().item()

                    logs["loss/total"] = loss.detach().item()
                    logs["loss_l2"] = loss_l2.detach().item()
                    logs["loss_lpips"] = loss_lpips.detach().item()
                    if args.lambda_gram > 0:
                        logs["loss_gram"] = loss_gram.detach().item()
                    if args.lambda_clipsim > 0:
                        logs["loss_clipsim"] = loss_clipsim.detach().item()

                    display_logs = {
                        key: _scalar_for_display(value)
                        for key, value in logs.items()
                    }
                    display_items = ", ".join(
                        f"{key}={value:.4g}" if isinstance(value, (int, float, np.floating, np.integer))
                        else f"{key}={value}"
                        for key, value in sorted(display_logs.items())
                    )
                    print(f"[EPOCH {epoch}] step={global_step}: {display_items}", flush=True)

                    if args.viz_freq > 0 and global_step % args.viz_freq == 0:
                        viz_dir = os.path.join(output_path, "viz", f"step_{global_step}")
                        os.makedirs(viz_dir, exist_ok=True)
                        for idx in range(min(B, 4)):
                            save_image_local(x_src[idx].detach(), os.path.join(viz_dir, f"source_{idx}.png"))
                            if args.use_reference_image:
                                save_image_local(x_ref[idx].detach(), os.path.join(viz_dir, f"reference_{idx}.png"))
                            save_image_local(x_tgt[idx].detach(), os.path.join(viz_dir, f"target_{idx}.png"))
                            save_image_local(x_tgt_pred[idx].detach(), os.path.join(viz_dir, f"output_{idx}.png"))
                        _write_tensorboard_images(global_step, x_src, x_tgt, x_tgt_pred, x_ref if args.use_reference_image else None)

                    if len(eval_logs) > 0:
                        logs.update(eval_logs)
                        eval_display = ", ".join(f"{k}={v:.4f}" for k, v in sorted(eval_logs.items()))
                        print(f"[EVAL][EPOCH {epoch}] step={global_step}: {eval_display}", flush=True)

                    accelerator.log(logs, step=global_step)

            if global_step >= total_train_steps:
                break

        if args.checkpointing_epoch > 0 and (epoch + 1) % args.checkpointing_epoch == 0:
            accelerator.wait_for_everyone()
            _save_checkpoint(epoch + 1, global_step)
            accelerator.wait_for_everyone()

        if global_step >= total_train_steps:
            break

    accelerator.wait_for_everyone()
    _save_checkpoint(args.num_training_epochs, global_step, is_final=True)
    accelerator.wait_for_everyone()


if __name__ == "__main__":
    args = parse_args_paired_training()
    main(args)
