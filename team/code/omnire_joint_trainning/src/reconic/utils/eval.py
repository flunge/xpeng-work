import json
import logging
import os
import time
from typing import List, Optional

import torch
import wandb
from omegaconf import OmegaConf

from ..datasets.driving_dataset import DrivingDataset, NovelViewDatasetWrapper
from ..models.video_utils import render_images
from ..trainers import BasicTrainer

logger = logging.getLogger()
current_time = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())


@torch.no_grad()
def psnr(img1, img2, mask=None):
    '''
    img1, img2: (C, H, W)
    mask: (1, H, W)
    '''
    if mask is not None:
        mask = mask.bool()
        img1 = img1[mask]
        img2 = img2[mask]
    
    # mse = ((img1 - img2) ** 2).view(-1, img1.shape[-1]).mean(dim=0, keepdim=True)    
    mse = torch.mean((img1 - img2) ** 2)
    psnr = 20 * torch.log10(1.0 / torch.sqrt(mse))
    return psnr


@torch.no_grad()
def do_evaluation(
    step: int = 0,
    cfg: OmegaConf = None,
    trainer: BasicTrainer = None,
    dataset: DrivingDataset = None,
    render_keys: Optional[List[str]] = None,
    post_fix: str = "",
    log_metrics: bool = True,
):
    trainer.set_eval()
    logger.info("Evaluating Pixels...")

    if dataset.test_image_set is not None and cfg.render.render_test:
        logger.info("Evaluating Test Set Pixels...")
        video_output_path = f"{cfg.project_dir}/videos{post_fix}/test_set_{step}.mp4"
        save_videos_config = {
            "num_timestamps": dataset.num_img_timesteps,
            "num_cams": dataset.pixel_source.num_cams,
            "keys": render_keys,
            "fps": cfg.render.fps,
            "save_separate_video": cfg.logging.save_seperate_video,
            "save_images": cfg.render.get("with_image_output", False),
        }
        render_results = render_images(
            trainer=trainer,
            dataset=dataset.test_image_set,
            compute_metrics=cfg.render.compute_metrics,
            compute_error_map=cfg.render.vis_error,
            redistort_rgb=cfg.render.get("redistort_rgb", True),
            render_keys=render_keys,
            save_path=video_output_path,
            layout_fn=dataset.layout,
            save_videos_config=save_videos_config,
        )

        if log_metrics:
            eval_dict = {}
            for k, v in render_results.items():
                if k in [
                    "psnr",
                    "ssim",
                    "lpips",
                    "fid",
                    "occupied_psnr",
                    "occupied_ssim",
                    "masked_psnr",
                    "masked_ssim",
                    "human_psnr",
                    "human_ssim",
                    "vehicle_psnr",
                    "vehicle_ssim",
                ]:
                    eval_dict[f"image_metrics/test/{k}"] = v
            if cfg.visualizer.enable_wandb:
                wandb.log(eval_dict)
            test_metrics_file = f"{cfg.project_dir}/metrics{post_fix}/images_test_{current_time}.json"

            with open(test_metrics_file, "w") as f:
                json.dump(eval_dict, f)
            logger.info(f"Image evaluation metrics saved to {test_metrics_file}")

    if cfg.render.render_full:
        video_output_path = f"{cfg.project_dir}/videos{post_fix}/full_set_{step}.mp4"
        logger.info("Evaluating Full Set...")
        save_videos_config = {
            "num_timestamps": dataset.num_img_timesteps,
            "num_cams": dataset.pixel_source.num_cams,
            "keys": render_keys,
            "fps": cfg.render.fps,
            "save_separate_video": cfg.logging.save_seperate_video,
            "save_images": cfg.render.get("with_image_output", False),
        }
        render_results = render_images(
            trainer=trainer,
            dataset=dataset.full_image_set,
            compute_metrics=cfg.render.compute_metrics,
            compute_error_map=cfg.render.vis_error,
            redistort_rgb=cfg.render.get("redistort_rgb", True),
            render_keys=render_keys,
            save_path=video_output_path,
            layout_fn=dataset.layout,
            save_videos_config=save_videos_config,
        )

        if log_metrics:
            eval_dict = {}
            for k, v in render_results.items():
                if k in [
                    "psnr",
                    "ssim",
                    "lpips",
                    "fid",
                    "occupied_psnr",
                    "occupied_ssim",
                    "masked_psnr",
                    "masked_ssim",
                    "human_psnr",
                    "human_ssim",
                    "vehicle_psnr",
                    "vehicle_ssim",
                ]:
                    eval_dict[f"image_metrics/full/{k}"] = v
            if cfg.visualizer.enable_wandb:
                wandb.log(eval_dict)
            full_metrics_file = f"{cfg.project_dir}/metrics{post_fix}/images_full_{current_time}.json"
            with open(full_metrics_file, "w") as f:
                json.dump(eval_dict, f)
            logger.info(f"Image evaluation metrics saved to {full_metrics_file}")

    if "gt_rgbs" in render_keys:
        render_keys.remove("gt_rgbs")
    render_novel_cfg = cfg.render.get("render_novel", None)
    if render_novel_cfg is not None:
        is_render_novel = render_novel_cfg.get("render", False)
        if is_render_novel:
            logger.info("Rendering novel views...")
            render_traj = dataset.get_novel_render_traj(
                traj_types=render_novel_cfg.traj_types,
                target_frames=render_novel_cfg.get("frames", dataset.frame_num),
            )
            video_output_dir = f"{cfg.project_dir}/videos{post_fix}/novel_{step}"
            if not os.path.exists(video_output_dir):
                os.makedirs(video_output_dir)

            for traj_type_name, traj in render_traj.items():
                novel_view_dataset = NovelViewDatasetWrapper(dataset=dataset, traj=traj)

                save_path = os.path.join(video_output_dir, f"{traj_type_name}.mp4")
                save_videos_config = {
                    "num_timestamps": dataset.num_img_timesteps,
                    "num_cams": dataset.pixel_source.num_cams,
                    "keys": render_keys,
                    "fps": cfg.render.fps,
                    "save_separate_video": cfg.logging.save_seperate_video,
                    "save_images": cfg.render.get("with_image_output", False),
                }
                render_images(
                    trainer=trainer,
                    dataset=novel_view_dataset,
                    compute_metrics=cfg.render.compute_metrics,
                    compute_error_map=False,
                    redistort_rgb=cfg.render.get("redistort_rgb", True),
                    render_keys=render_keys,
                    save_path=save_path,
                    layout_fn=dataset.layout,
                    save_videos_config=save_videos_config,
                )

                logger.info(f"Saved novel view video for trajectory type: {traj_type_name} to {save_path}")
