import json
import logging
import os
import random
import threading
import time
import imageio
import numpy as np
import torch
from einops import rearrange

from ..datasets.base.data_proto import CameraInfo, ImageInfo
from ..utils.misc import import_str
from ..training_loop.training_loop_helper import TrainingLoopHelper

logger = logging.getLogger()

XPENG_CAR_HALF_WIDTH = 2.198 / 2
MAX_DIST_TO_ROAD_EDGE = 0.5

class GenerativeReconTrainingLoop(TrainingLoopHelper):
    def __init__(self, args):
        super().__init__(args)
        self.use_noncrop_intrinsics = self.cfg.generative_engine.get("use_noncrop_intrinsics", False)
        self.use_mask_in_novel_view = self.cfg.generative_engine.get("use_mask_in_novel_view", True)
        self.postprocess_cull_ground_gaussians = self.cfg.generative_engine.get("postprocess_cull_ground_gaussians", True)
        self.cfg.generative_engine.inference_batch_size += int(self.use_noncrop_intrinsics)
        self.use_half_novel_view = self.cfg.generative_engine.get("use_half_novel_view", False)
        
        # 1. setup the generative engine
        self.generative_scheduler = import_str(self.cfg.generative_engine.scheduler)(
            max_waiting_queue_size=self.cfg.generative_engine.max_waiting_queue_size
        )
        generative_engine = import_str(self.cfg.generative_engine.type)(
            base_model_id=self.cfg.generative_engine.base_model_id,
            pretrained_unet_weights=self.cfg.generative_engine.pretrained_unet_weights,
            groundingdino_model_id=self.cfg.generative_engine.groundingdino_model_id,
            sam_model_id=self.cfg.generative_engine.sam_model_id,
            inference_batch_size=self.cfg.generative_engine.inference_batch_size,
            training_batch_size=self.cfg.generative_engine.training_batch_size,
            use_8bit_optimizer=self.cfg.generative_engine.use_8bit_optimizer,
            dst_size=self.cfg.generative_engine.dst_size,
            num_inference_steps=self.cfg.generative_engine.num_inference_steps,
            image_guidance_scale=self.cfg.generative_engine.image_guidance_scale,
            guidance_scale=self.cfg.generative_engine.guidance_scale,
            condition_dropout_prob=self.cfg.generative_engine.condition_dropout_prob,
            generate_sky_mask=self.cfg.generative_engine.get("generate_sky_mask", False),
        )
        self.generative_scheduler.set_generative_engine(generative_engine)
        self.generative_scheduler.set_train()

        # 2. setup joint training logging paths
        # Set generative engine training data vis dirs
        self.train_vis_log_dir = os.path.join(self.cfg.project_dir, "vis_generative_engine_training")
        os.makedirs(self.train_vis_log_dir, exist_ok=True)

        # Set novel view data dirs
        self.novel_view_cache_dir = os.path.join(self.cfg.project_dir, "novel_view_data")
        os.makedirs(self.novel_view_cache_dir, exist_ok=True)

        # 3. setup joint training specific variables
        max_shift = self.cfg.joint_training_cfg.max_shift
        interval_step = self.cfg.joint_training_cfg.iterations_per_shift
        self.max_num = (self.recon_trainer.num_iters - self.cfg.joint_training_cfg.start_engine_infer_at) // interval_step
        self.delta_shift = max_shift / self.max_num

        start_update_step = self.cfg.joint_training_cfg.start_engine_infer_at
        self.update_steps = list(range(start_update_step, self.recon_trainer.num_iters, interval_step))

        self.current_shift_level = 0
        self.processed_image_indices = set()
        self.use_single_branch_size = self.cfg.joint_training_cfg.get("use_single_branch_size", False)

        # 4. setup novel view data storage thread
        self.store_thread = threading.Thread(target=self._store_worker, daemon=True)
        self.store_thread.start()

        metadata_path = os.path.join(self.cfg.project_dir, "training_metadata.json")
        if os.path.exists(metadata_path):
            # first try to resume
            with open(metadata_path, "r") as f:
                metadata = json.load(f)
            num_finished_step = metadata["next_step"]
            self.current_shift_level = metadata["current_shift_level"]
            self.processed_image_indices = set(metadata["processed_image_indices"])
            if num_finished_step >= self.cfg.joint_training_cfg.stop_engine_train_at:
                resume_from = os.path.join(self.cfg.project_dir, "engine_checkpoint_final.pth")
            else:
                resume_from = os.path.join(self.cfg.project_dir, f"engine_checkpoint_{(num_finished_step):05d}.pth")

            self.generative_scheduler.resume_from_checkpoint(ckpt_path=resume_from)
            logger.info(f"Resumed generative model from {resume_from}")

    def _forward_interval(self, all_image_info, all_cam_info, from_synthesis=False):
        all_image_info.to(self.device)
        all_cam_info.to(self.device)
        outputs = self.recon_trainer(all_image_info, all_cam_info, novel_view=from_synthesis)
        self.recon_trainer.update_visibility_filter()
        loss_dict = self.recon_trainer.compute_losses(
            outputs=outputs,
            image_info=all_image_info,
            cam_info=all_cam_info,
            from_synthesis=from_synthesis,
        )
        return outputs, loss_dict

    def run_before_train_step(self, step):
        super().run_before_train_step(step)

        if self._is_engine_inference_state(step) and step in self.update_steps:
            self.current_shift_level += 1
            self.processed_image_indices.clear()
            
    def forward_step(self, step, train_data):
        _, image_info, cam_info = train_data[:3]

        enable_novel_view_trianing_when_single_branch = len(train_data) > 3 and random.random() < 0.5
        # self.use_single_branch_size 为True，单次只训1个视角，为False单次训新旧2个视角

        if (self.use_single_branch_size and not enable_novel_view_trianing_when_single_branch) or \
           not self.use_single_branch_size :
            outputs, loss_dict = self._forward_interval(image_info, cam_info, from_synthesis=False)
        else :
            outputs = None
            loss_dict = {}

        if (self.use_single_branch_size and enable_novel_view_trianing_when_single_branch) or \
           (not self.use_single_branch_size and len(train_data) > 3) :
            novel_view_image_info, novel_view_cam_info = train_data[3:]
            novel_view_loss_dict = self._forward_interval(
                novel_view_image_info, novel_view_cam_info, from_synthesis=True
            )[1]
            for k, v in novel_view_loss_dict.items():
                if k not in loss_dict:
                    loss_dict[k] = 0
                loss_dict[k] += v

        return outputs, loss_dict

    def backward_step(self, step, outputs, loss_dict):
        self.recon_trainer.backward(loss_dict)

    def run_after_train_step(self, step, train_data, outputs, loss_dict):
        super().run_after_train_step(step, train_data, outputs, loss_dict)
        if (self._is_engine_training_state(step) == False and self._is_engine_inference_state(step) == False):
            return
            
        index, image_info, cam_info = train_data[:3]
        cam_index = ["cam0", "cam2", "cam3", "cam4", "cam5", "cam6","cam7"].index(cam_info.camera_name)
        if self.use_mask_in_novel_view and image_info.masks.egocar_mask is not None:   
            if abs(self.cfg.data.pixel_source.difix_downsample[cam_index]-1.0) > 1e-5:
                egocar_mask = 1.0 - image_info.masks_downsample.egocar_mask.float()
            else:
                egocar_mask = 1.0 - image_info.masks.egocar_mask.float()
        else:
            if abs(self.cfg.data.pixel_source.difix_downsample[cam_index]-1.0) > 1e-5:
                egocar_mask = torch.ones(image_info.pixels_downsample.shape[:2], device=image_info.pixels.device)
            else:
                egocar_mask = torch.ones(image_info.pixels.shape[:2], device=image_info.pixels.device)

        if self._is_engine_training_state(step):
            self._prepare_generative_engine_training_data(
                step, outputs["rgb"], image_info.pixels, valid_mask=egocar_mask, cam_type=cam_info.camera_id
            )
        if self._is_engine_inference_state(step) and self.current_shift_level > 0 and not (self.use_half_novel_view and image_info.frame_index.cpu().item() % 2 == 0):
            self._prepare_generative_engine_inference_data(index, image_info, cam_info, valid_mask=egocar_mask)

    def _save_generative_checkpoint_step(self, step):
        num_finished_step = step + 1
        do_save = num_finished_step > 0 and (
            num_finished_step % self.cfg.logging.saveckpt_freq == 0
            or (num_finished_step == self.cfg.joint_training_cfg.stop_engine_train_at)
        )
        if do_save:
            if num_finished_step <= self.cfg.joint_training_cfg.stop_engine_train_at:
                assert num_finished_step % self.cfg.generative_engine.training_batch_size == 0
                self.generative_scheduler.save_checkpoint(
                    log_dir=self.cfg.project_dir,
                    step=num_finished_step,
                    is_final=num_finished_step == self.cfg.joint_training_cfg.stop_engine_train_at,
                )

            # Override basic metadata
            metadata = {
                "next_step": int(num_finished_step),
                "current_shift_level": int(self.current_shift_level),
                "processed_image_indices": list(self.processed_image_indices),
            }
            with open(os.path.join(self.cfg.project_dir, "training_metadata.json"), "w") as f:
                json.dump(metadata, f)

    def _postprocess_cull_frozen_gaussians(self):
        if self.cfg.joint_training_cfg.get("decull_rate", 0) > 0:
            # with_decull
            # 获取数据集信息
            total_images = len(self.dataset.train_image_set)
            num_cams = self.dataset.pixel_source.num_cams  # 7个相机
            total_frames = total_images // num_cams
            
            # 抽样1/2的帧，但保留每帧的所有7个相机
            # sample_ratio = 0.5  # 1/2
            sample_ratio = self.cfg.joint_training_cfg.decull_rate
            num_sample_frames = max(1, int(total_frames * sample_ratio))
            
            # 均匀抽样帧索引
            frame_indices = np.linspace(0, total_frames - 1, num_sample_frames, dtype=int)
            
            logger.info(f"Postprocessing cull frozen gaussians: sampling {num_sample_frames}/{total_frames} frames "
                    f"({sample_ratio*100:.1f}%), processing {num_sample_frames * num_cams}/{total_images} images")
            
            for frame_idx in frame_indices:
                # 处理该帧的所有7个相机
                for cam_idx in range(num_cams):
                    image_idx = cam_idx + frame_idx * num_cams
                    if image_idx >= total_images:
                        continue
                        
                    image_info, cam_info = self.dataset.train_image_set[image_idx]
                    shift_value_names = self.dataset.novel_view_manager.get_all_novel_view_shift_value_name(image_idx)
                    for shift_value_name in shift_value_names:
                        novel_view_image_info, novel_view_cam_info = self.dataset.load_novel_view_data(
                            image_idx, image_info.detach(), cam_info.detach(), shift_value_name
                        )
                        self.recon_trainer.postprocess_cull_frozen_gaussians(
                            novel_view_image_info.to(self.device), novel_view_cam_info.to(self.device), update_optimizer=True
                        )
        else:
            # without_decull
            for index in range(len(self.dataset.train_image_set)):
                image_info, cam_info = self.dataset.train_image_set[index]
                shift_value_names = self.dataset.novel_view_manager.get_all_novel_view_shift_value_name(index)
                for shift_value_name in shift_value_names:
                    novel_view_image_info, novel_view_cam_info = self.dataset.load_novel_view_data(
                        index, image_info.detach(), cam_info.detach(), shift_value_name
                    )
                    self.recon_trainer.postprocess_cull_frozen_gaussians(
                        novel_view_image_info.to(self.device), novel_view_cam_info.to(self.device), update_optimizer=True
                    )

    def _log_total_training_time(self):
        """计算并打印总训练耗时"""
        end_time = time.time()
        total_time = end_time - self.start_time
        
        # 转换为小时、分钟、秒格式
        hours = int(total_time // 3600)
        minutes = int((total_time % 3600) // 60)
        seconds = int(total_time % 60)
        
        logger.info("=" * 80)
        logger.info(f"🎉 训练完成！总耗时: {hours:02d}:{minutes:02d}:{seconds:02d} ({total_time:.2f} 秒)")
        logger.info("=" * 80)


    def run_after_step_finished(self, step, train_data, outputs, loss_dict):
        num_finished_step = step + 1

        # 没用且耗时大
        # if num_finished_step == self.recon_trainer.num_iters and self.postprocess_cull_ground_gaussians:
        #     self._postprocess_cull_frozen_gaussians()

        super().run_after_step_finished(step, train_data, outputs, loss_dict)
        self._save_generative_checkpoint_step(step)

    def _is_engine_inference_state(self, step):
        if step == self.cfg.joint_training_cfg.start_engine_infer_at:
            self.generative_scheduler.set_eval()
        return step >= self.cfg.joint_training_cfg.start_engine_infer_at

    def _is_engine_training_state(self, step):
        return (
            step >= self.cfg.joint_training_cfg.start_engine_train_at
            and step < self.cfg.joint_training_cfg.stop_engine_train_at
        )

    def _prepare_generative_engine_training_data(self, step, render_image, gt_image, valid_mask, cam_type):
        render_image = render_image.clamp(0.0, 1.0).detach().clone()
        gt_image = gt_image.clamp(0.0, 1.0).detach().clone()
        valid_mask = valid_mask.detach().clone()
        render_image = render_image * valid_mask.unsqueeze(-1)
        gt_image = gt_image * valid_mask.unsqueeze(-1)
        if self.debug_mode and step % 1000 == 0:
            render_img = (render_image.cpu().numpy() * 255).astype(np.uint8)
            gt_img = (gt_image.cpu().numpy() * 255).astype(np.uint8)
            img = np.concatenate([render_img, gt_img], axis=1)
            imageio.imwrite(os.path.join(self.train_vis_log_dir, f"step_{step}_train_pair.png"), img)
        render_image = rearrange(render_image, "h w c -> c h w")
        gt_image = rearrange(gt_image, "h w c -> c h w")
        if hasattr(self.cfg.generative_engine, "prompts"):
            self.generative_scheduler.push_training_pairs(
                render_image=render_image,
                gt_image=gt_image,
                mask=valid_mask,
                prompt=self.cfg.generative_engine.prompts[cam_type],
            )
        else:
            self.generative_scheduler.push_training_pairs(render_image=render_image, gt_image=gt_image, mask=valid_mask)

    def _prepare_generative_engine_inference_data(
        self, index, image_info: ImageInfo, cam_info: CameraInfo, valid_mask: torch.Tensor
    ):
        shift = self.delta_shift * self.current_shift_level
        if index in self.processed_image_indices or index < self.cfg.joint_training_cfg.start_infer_image_index_at:
            return

        self.recon_trainer.set_eval()
        valid_mask = valid_mask.detach().clone()

        for shift_value in [shift, -shift]:
            if self.cfg.joint_training_cfg.use_max_shift_range:
                left_max_shift, right_max_shift = self.dataset.pixel_source.max_range_info[
                    image_info.frame_index.item()
                ]
                # print(f"The max shift range of frame {image_info.frame_index.item()}: [{left_max_shift}, {right_max_shift}]")
                if shift_value > 0 and shift_value > left_max_shift:
                    shift_value = left_max_shift / self.max_num * self.current_shift_level
                    if abs(shift_value) - XPENG_CAR_HALF_WIDTH < MAX_DIST_TO_ROAD_EDGE :
                        logger.info(f"wanted left shift value {shift_value} is too small, skip difix")
                        continue
                if shift_value < 0 and shift_value < right_max_shift:
                    shift_value = right_max_shift / self.max_num * self.current_shift_level
                    if abs(shift_value) - XPENG_CAR_HALF_WIDTH < MAX_DIST_TO_ROAD_EDGE :
                        logger.info(f"wanted right shift value {shift_value} is too small, skip difix")
                        continue
            
            novel_view_image_info = image_info.detach().clone()
            if novel_view_image_info.masks is not None and novel_view_image_info.masks.sky_mask is not None:
                novel_view_image_info.masks.sky_mask = None
            novel_view_cam_info = cam_info.detach().clone()
            cam_to_ego = novel_view_cam_info.camera_to_ego.clone()
            cam_to_ego[1, 3] += shift_value
            ego_to_world = novel_view_cam_info.ego_to_world
            c2w = ego_to_world @ cam_to_ego
            c2w = c2w.clone().to(self.device)
            novel_view_cam_info.camera_to_world = c2w
            cam_index = ["cam0", "cam2", "cam3", "cam4", "cam5", "cam6","cam7"].index(cam_info.camera_name)
            if abs(self.cfg.data.pixel_source.difix_downsample[cam_index]-1.0) > 1e-5:
                novel_view_image_info.rays = novel_view_image_info.rays_downsample
                novel_view_image_info.pixels = novel_view_image_info.pixels_downsample
                novel_view_image_info.pixel_coords = novel_view_image_info.pixel_coords_downsample
                novel_view_image_info.masks = novel_view_image_info.masks_downsample
                novel_view_cam_info.height, novel_view_cam_info.width = novel_view_image_info.pixels.shape[:2]
                novel_view_cam_info.intrinsic = novel_view_cam_info.intrinsic_downsample
            with torch.no_grad():
                results = self.recon_trainer(novel_view_image_info, novel_view_cam_info)
                novel_view_render_image = results["rgb"]

            novel_view_render_image = novel_view_render_image.clamp(0.0, 1.0).clone()
            novel_view_render_image = novel_view_render_image * valid_mask.unsqueeze(-1)
            novel_view_render_image = rearrange(novel_view_render_image, "h w c -> c h w")

            ref_image = None
            if not self.cfg.generative_engine.type == "reconic.models.generative_models.SD15_GaussianFixModel":
                if self.cfg.generative_engine.use_ref_image:      
                    if not all(abs(x - 1.0) < 1e-5 for x in self.cfg.data.pixel_source.difix_downsample):
                        ref_image = novel_view_image_info.pixels.clone().detach()
                    else:
                        ref_image = image_info.pixels.clone().detach()
                    ref_image = rearrange(ref_image, "h w c -> c h w")

            
            index_shift_pair = f"{index}_{shift_value:.1f}"
            if abs(self.cfg.data.pixel_source.difix_downsample[cam_index]-1.0) > 1e-5:
                index_shift_pair = f"{index}_{shift_value:.1f}-downsample"
            if not self.cfg.generative_engine.type == "reconic.models.generative_models.SD15_GaussianFixModel":
                self.generative_scheduler.push_inference_image(
                    novel_view_render_image, valid_mask, c2w, index_shift_pair, ref_image=ref_image
                )
            else:
                self.generative_scheduler.push_inference_image(
                    novel_view_render_image, valid_mask, c2w, index_shift_pair
                )
            # if self.cfg.joint_training_cfg.use_max_shift_range:
            #     print(f"The realistic shift value of frame {image_info.frame_index.item()}: {shift_value}")

        if self.use_noncrop_intrinsics:
            if cam_info.camera_name in ["cam2", "cam3", "cam4", "cam5", "cam6"]:
                novel_view_cam_info = cam_info.detach().clone()
                intrinsic_noncrop = novel_view_cam_info.intrinsic_noncrop
                novel_view_cam_info.intrinsic = intrinsic_noncrop
                novel_view_cam_info.intrinsic.to(self.device)

                novel_view_image_info = image_info.detach().clone()
                cam_index = ["cam0", "cam2", "cam3", "cam4", "cam5", "cam6","cam7"].index(cam_info.camera_name)
                if abs(self.cfg.data.pixel_source.difix_downsample[cam_index]-1.0) > 1e-5:
                    novel_view_image_info.rays = novel_view_image_info.rays_downsample
                    novel_view_image_info.pixels = novel_view_image_info.pixels_downsample
                    novel_view_image_info.pixel_coords = novel_view_image_info.pixel_coords_downsample
                    novel_view_image_info.masks = novel_view_image_info.masks_downsample
                    novel_view_cam_info.height, novel_view_cam_info.width = novel_view_image_info.pixels.shape[:2]
                if novel_view_image_info.masks is not None and novel_view_image_info.masks.sky_mask is not None:
                    novel_view_image_info.masks.sky_mask = None

                with torch.no_grad():
                    results = self.recon_trainer(novel_view_image_info, novel_view_cam_info)
                    novel_view_render_image = results["rgb"]
                novel_view_render_image = novel_view_render_image.clamp(0.0, 1.0).clone()
                novel_view_render_image = rearrange(novel_view_render_image, "h w c -> c h w")

                ref_image = None
                if self.cfg.generative_engine.use_ref_image:
                    if abs(self.cfg.data.pixel_source.difix_downsample[cam_index]-1.0) > 1e-5:
                        ref_image = novel_view_image_info.pixels.clone().detach()
                    else:
                        ref_image = image_info.pixels.clone().detach()
                    ref_image = rearrange(ref_image, "h w c -> c h w")
                
                if abs(self.cfg.data.pixel_source.difix_downsample[cam_index]-1.0) > 1e-5:
                    index_pair = f"{index}_noncrop-downsample"
                else:
                    index_pair = f"{index}_noncrop"
                self.generative_scheduler.push_inference_image(
                    novel_view_render_image, valid_mask, novel_view_cam_info.camera_to_world, 
                    index_pair, ref_image=ref_image
                )
            # else:
            #     self.generative_scheduler.push_inference_image(
            #         None, None, None, None, ref_image=None, infer_now=True
            #     )

        self.processed_image_indices.add(index)

    def _postprocess_generative_engine_inference_data(self):
        de_img, ref_image, ref_sky_mask, ref_c2w, index_shift_pair = self.generative_scheduler.get_novel_data()

        ref_image = rearrange(ref_image, "c h w -> h w c")
        de_img = rearrange(de_img, "c h w -> h w c")

        index, shift_value_name = index_shift_pair.split("_")
        self.dataset.save_novel_view_data(
            int(index),
            shift_value_name,
            novel_view_cam_extrinsic=ref_c2w,
            novel_view_render_image=de_img,
            novel_view_render_fix_image=ref_image,
            novel_view_sky_mask=ref_sky_mask,
        )

    def _store_worker(self):
        while True:
            if self.generative_scheduler.num_novel_data > 0:
                self._postprocess_generative_engine_inference_data()
            time.sleep(0.1)