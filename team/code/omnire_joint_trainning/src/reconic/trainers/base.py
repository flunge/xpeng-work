import logging
import os
import time
from enum import IntEnum
from functools import partial
from typing import Dict, List, Tuple

import imageio
# import kornia
import nerfview
import numpy as np
import torch
import torch.nn as nn
import viser
from gsplat.rendering import rasterization
from omegaconf import OmegaConf
from pytorch_msssim import SSIM
from torchmetrics.image import PeakSignalNoiseRatio
from torchmetrics.image.lpip import LearnedPerceptualImagePatchSimilarity

from ..datasets.base.data_proto import CameraInfo, ImageInfo
from ..models.gaussians.basics import dataclass_camera, dataclass_gs
from .base_render import BasicTrainer_render

logger = logging.getLogger()

VISUALIZATION_DEBUG = False


def depth_to_rainbow_colors(normalized_depth: torch.Tensor) -> torch.Tensor:
    depth_colors = torch.zeros((*normalized_depth.shape, 3), device=normalized_depth.device)
    depth_colors[..., 0] = 1.0 - normalized_depth
    green_channel = torch.zeros_like(normalized_depth)
    mask_less_half = normalized_depth < 0.5
    mask_more_half = normalized_depth >= 0.5
    green_channel[mask_less_half] = normalized_depth[mask_less_half] * 2
    green_channel[mask_more_half] = 2 - normalized_depth[mask_more_half] * 2
    depth_colors[..., 1] = green_channel
    depth_colors[..., 2] = normalized_depth
    return depth_colors


class GSModelType(IntEnum):
    Background = 0
    RigidNodes = 1
    SMPLNodes = 2
    DeformableNodes = 3
    Ground = 4
    Trafficlight = 5
    DynamicAssets = 6
    RigidNodesLight = 7


def lr_scheduler_fn(cfg: OmegaConf, lr_init: float):
    if cfg.lr_final is None:
        lr_final = lr_init
    else:
        lr_final = cfg.lr_final

    def func(step):
        step = step - cfg.opt_after
        if step < 0:
            return 0.0

        if step < cfg.warmup_steps:
            if cfg.ramp == "cosine":
                lr = cfg.lr_pre_warmup + (lr_init - cfg.lr_pre_warmup) * np.sin(
                    0.5 * np.pi * np.clip(step / cfg.warmup_steps, 0, 1)
                )
            else:
                lr = cfg.lr_pre_warmup + (lr_init - cfg.lr_pre_warmup) * step / cfg.warmup_steps
        else:
            t = np.clip((step - cfg.warmup_steps) / (cfg.max_steps - cfg.warmup_steps), 0, 1)
            lr = np.exp(np.log(lr_init) * (1 - t) + np.log(lr_final) * t)
        return lr  # divided by lr_init because the multiplier is with the initial learning rate

    return func


class BasicTrainer(BasicTrainer_render):
    def __init__(self, **kwargs):
        BasicTrainer_render.__init__(self, **kwargs)

        # init losses fn
        self._init_losses()

        # metrics
        if not self.disable_metric:  # 使用 self.disable_metric，不是 disable_metric
            self.psnr = PeakSignalNoiseRatio(data_range=1.0).to(self.device)
            self.ssim = SSIM(data_range=1.0, size_average=True, channel=3).to(self.device)
            self.lpips = LearnedPerceptualImagePatchSimilarity(normalize=True).to(self.device)
            self.step = 0


    def set_train(self, step, fix_ground = False):
        for class_name, model in self.models.items():
            if class_name == "Ground":
                for param in model.parameters():
                    param.requires_grad = not fix_ground
            model.train()
        self.train()


    def _init_models(self) -> None:
        raise NotImplementedError("Please implement the _init_models function")

    def _init_losses(self) -> None:
        sky_opacity_loss_fn = None
        if "Sky" in self.models:
            if self.losses_dict.mask.opacity_loss_type == "bce":
                from ..models.losses import binary_cross_entropy

                sky_opacity_loss_fn = partial(binary_cross_entropy, reduction="mean")
            elif self.losses_dict.mask.opacity_loss_type == "safe_bce":
                from ..models.losses import safe_binary_cross_entropy

                sky_opacity_loss_fn = partial(safe_binary_cross_entropy, limit=0.1, reduction="mean")
        self.sky_opacity_loss_fn = sky_opacity_loss_fn

        depth_loss_fn = None
        depth_loss_cfg = self.losses_dict.get("depth", None)
        if depth_loss_cfg is not None:
            from ..models.losses import DepthLoss

            depth_loss_fn = DepthLoss(
                loss_type=depth_loss_cfg.loss_type,
                normalize=depth_loss_cfg.normalize,
                use_inverse_depth=depth_loss_cfg.inverse_depth,
                upper_bound=depth_loss_cfg.upper_bound,
                depth_error_percentile=depth_loss_cfg.depth_error_percentile,
            )
        self.depth_loss_fn = depth_loss_fn

    def optimizer_zero_grad(self) -> None:
        self.optimizer.zero_grad()

    def optimizer_step(self) -> None:
        # for params_name, optimizer in self.optimizers.items():
        #     class_name = params_name.split("#")[0]
        #     component_name = params_name.split("#")[1]
        #     max_norm = self.model_config[class_name]["optim"][component_name].get("max_norm", None)
        #     if max_norm is not None:
        #         self.grad_scaler.unscale_(optimizer)
        #         torch.nn.utils.clip_grad_norm_(self.param_groups[params_name], max_norm)
        #     if any(any(p.grad is not None for p in g["params"]) for g in optimizer.param_groups):
        #         self.grad_scaler.step(optimizer)
        self.optimizer.step()

    def preprocess_per_train_step(self, step: int) -> None:
        self.step = step
        for class_name in self.gaussian_classes.keys():
            self.models[class_name].preprocess_per_train_step(step)

        # viewer
        if self.viewer is not None:
            while self.viewer.state.status == "paused":
                time.sleep(0.01)
            self.viewer.lock.acquire()
            self.tic = time.time()

    def postprocess_per_train_step(self, step: int) -> None:
        radii = self.info["radii"]
        if self.render_cfg.absgrad:
            grads = self.info["means2d"].absgrad.clone()
        else:
            grads = self.info["means2d"].grad.clone()
        grads[..., 0] *= self.info["width"] / 2.0 * self.render_cfg.batch_size
        grads[..., 1] *= self.info["height"] / 2.0 * self.render_cfg.batch_size

        for class_name in self.gaussian_classes.keys():
            gaussian_mask = self.pts_labels == self.gaussian_classes[class_name]

            self.models[class_name].postprocess_per_train_step(
                step=step,
                optimizer=self.optimizer,
                radii=radii[0, gaussian_mask],
                xys_grad=grads[0, gaussian_mask],
                last_size=max(self.info["width"], self.info["height"]),
            )

        # viewer
        if self.viewer is not None:
            num_train_rays_per_step = self.render_cfg.batch_size * self.info["width"] * self.info["height"]
            self.viewer.lock.release()
            num_train_steps_per_sec = 1.0 / (time.time() - self.tic)
            num_train_rays_per_sec = num_train_rays_per_step * num_train_steps_per_sec
            # Update the viewer state.
            self.viewer.state.num_train_rays_per_sec = num_train_rays_per_sec
            # Update the scene.
            self.viewer.update(step, num_train_rays_per_step)

    def update_visibility_filter(self) -> None:
        for class_name in self.gaussian_classes.keys():
            gaussian_mask = self.pts_labels == self.gaussian_classes[class_name]
            self.models[class_name].cur_radii = self.info["radii"][0, gaussian_mask]

    def postprocess_cull_frozen_gaussians(
        self, image_info: ImageInfo, camera_info: CameraInfo, update_optimizer: bool = False
    ):
        if "Ground" not in self.gaussian_classes.keys():
            return

        processed_cam = self.process_camera(camera_info=camera_info, image_info=image_info)
        gs = self.models["Ground"].get_gaussians(processed_cam)
        gs = dataclass_gs(
            _means=gs["_means"],
            _scales=gs["_scales"],
            _quats=gs["_quats"],
            _rgbs=gs["_rgbs"],
            _opacities=gs["_opacities"],
            detach_keys=[],
            extras=None,
        )
        _ = self.render_gaussians(
            gs=gs,
            cam=processed_cam,
            near_plane=self.render_cfg.near_plane,
            far_plane=self.render_cfg.far_plane,
            render_mode="RGB+ED",
            radius_clip=self.render_cfg.get("radius_clip", 0.0),
        )

        self.models["Ground"].postprocess_cull_frozen_gaussians(
            radii=self.info["radii"][0],
            last_size=max(self.info["width"], self.info["height"]),
            optimizer=self.optimizer if update_optimizer else None,
        )

    def forward(
        self,
        image_info: ImageInfo,
        camera_info: CameraInfo,
        novel_view: bool = False,
    ) -> Dict[str, torch.Tensor]:
        """Forward pass of the model

        Args:
            image_info (ImageInfo): image and pixels information
            camera_info (CameraInfo): camera information
            novel_view: whether the view is novel, if True, disable the camera refinement

        Returns:
            Dict[str, torch.Tensor]: output of the model
        """

        # for evaluation
        for model in self.models.values():
            if hasattr(model, "in_test_set"):
                model.in_test_set = self.in_test_set

        # prapare data
        processed_cam = self.process_camera(
            camera_info=camera_info,
            image_info=image_info,
            novel_view=novel_view,
        )
        gs = self.collect_gaussians(cam=processed_cam, image_ids=image_info.image_index)

        # render gaussians
        outputs, _ = self.render_gaussians(
            gs=gs,
            cam=processed_cam,
            near_plane=self.render_cfg.near_plane,
            far_plane=self.render_cfg.far_plane,
            render_mode="RGB+ED",
            radius_clip=self.render_cfg.get("radius_clip", 0.0),
        )

        # render sky
        sky_model = self.models["Sky"]
        outputs["rgb_sky"] = sky_model(image_info, opacity=outputs["opacity"].detach())
        outputs["rgb_sky_blend"] = outputs["rgb_sky"] * (1.0 - outputs["opacity"])

        # affine transformation
        outputs["rgb"] = self.affine_transformation(
            outputs["rgb_gaussians"] + outputs["rgb_sky"] * (1.0 - outputs["opacity"]),
            image_info,
            camera_info,
        )

        return outputs

    def backward(self, loss_dict: Dict[str, torch.Tensor]) -> None:
        # ----------------- backward ----------------
        total_loss = sum(loss for loss in loss_dict.values())
        self.grad_scaler.scale(total_loss).backward()

        for group in self.optimizer.param_groups:
            if group["name"] in self.fix_params_dict:
                for param in group["params"]:
                    if param.grad is not None and self.fix_params_dict is not None:
                        params_status = self.fix_params_dict[group["name"]]
                        param.grad[~params_status] = 0

        self.optimizer_step()
        scale = self.grad_scaler.get_scale()
        self.grad_scaler.update()

        # If the gradient scaler is decreased, no optimization step is performed so we should not step the scheduler.
        if scale <= self.grad_scaler.get_scale():
            for group in self.optimizer.param_groups:
                if group["name"] in self.lr_schedulers:
                    new_lr = self.lr_schedulers[group["name"]](self.step)
                    group["lr"] = new_lr

    def compute_losses(
        self,
        outputs: Dict[str, torch.Tensor],
        image_info: ImageInfo,
        cam_info: CameraInfo,
        from_synthesis: bool = False,
    ) -> Dict[str, torch.Tensor]:
        # calculate loss
        loss_dict = {}

        if image_info.masks.egocar_mask is not None:
            valid_loss_mask = 1.0 - image_info.masks.egocar_mask.float()
        elif image_info.masks.sky_mask is not None:
            valid_loss_mask = 1.0 - image_info.masks.sky_mask.float()
        else:
            valid_loss_mask = torch.ones_like(image_info.pixels)[..., 0]

        valid_loss_mask_add_tfl_rgb_weight = valid_loss_mask.clone()
        if image_info.masks.tfl_mask is not None and image_info.masks.tfl_mask.shape == valid_loss_mask_add_tfl_rgb_weight.shape:
            valid_tfl_mask = image_info.masks.tfl_mask
            valid_loss_mask_add_tfl_rgb_weight[valid_tfl_mask] = self.losses_dict.trafficlight.get("rgb_weight", 5.0)
        gt_rgb = image_info.pixels * valid_loss_mask_add_tfl_rgb_weight[..., None]
        predicted_rgb = outputs["rgb"] * valid_loss_mask_add_tfl_rgb_weight[..., None]

        if VISUALIZATION_DEBUG and self.step % 10 == 0:
            # Create a directory for debugging images
            debug_dir = "debug_images"
            os.makedirs(debug_dir, exist_ok=True)
            # Save the predicted and ground truth RGB images
            source_str = "from_synthesis" if from_synthesis else "from_raw"
            predicted_rgb_path = os.path.join(debug_dir, f"step_{self.step}_predicted_rgb_{source_str}.png")
            imageio.imwrite(
                predicted_rgb_path, (torch.clamp(predicted_rgb, max=1.0) * 255).detach().cpu().numpy().astype(np.uint8)
            )
            # Save the ground truth RGB image
            gt_rgb_path = os.path.join(debug_dir, f"step_{self.step}_gt_rgb_{source_str}.png")
            imageio.imwrite(gt_rgb_path, (gt_rgb * 255).detach().cpu().numpy().astype(np.uint8))

        # rgb loss
        Ll1 = torch.abs(gt_rgb - predicted_rgb).mean()
        simloss = 1 - self.ssim(
            gt_rgb.permute(2, 0, 1)[None, ...],
            predicted_rgb.permute(2, 0, 1)[None, ...],
        )
        if from_synthesis:
            loss_dict.update(
                {
                    "rgb_loss": self.losses_dict.rgb.w * 0.2 * Ll1,
                    "ssim_loss": self.losses_dict.ssim.w * simloss,
                }
            )
        else:
            loss_dict.update(
                {
                    "rgb_loss": self.losses_dict.rgb.w * Ll1,
                    "ssim_loss": self.losses_dict.ssim.w * simloss,
                }
            )

        # mask loss
        if not from_synthesis and self.sky_opacity_loss_fn is not None:
            gt_occupied_mask = (1.0 - image_info.masks.sky_mask.float()) * valid_loss_mask
            pred_occupied_mask = outputs["opacity"].squeeze() * valid_loss_mask
            sky_loss_opacity = (
                self.sky_opacity_loss_fn(pred_occupied_mask, gt_occupied_mask, valid_loss_mask)
                * self.losses_dict.mask.w
            )
            loss_dict.update({"sky_loss_opacity": sky_loss_opacity})

            if self.gaussian_ctrl_general_cfg.get("opacity_loss", False):
                gt_background_occupied_mask = (1.0 - image_info.masks.sky_mask.float() - image_info.masks.ground_mask.float()) * valid_loss_mask
                pred_background_occupied_mask = outputs["Background_opacity"].squeeze() * valid_loss_mask
                background_loss_opacity = (
                    self.sky_opacity_loss_fn(pred_background_occupied_mask, gt_background_occupied_mask, valid_loss_mask)
                    * self.losses_dict.mask.w
                )
                loss_dict.update({"background_loss_opacity": background_loss_opacity})

                # gt_ground_occupied_mask = ( image_info.masks.ground_mask.float() ) * valid_loss_mask
                # pred_ground_occupied_mask = outputs["Ground_opacity"].squeeze() * valid_loss_mask
                # ground_loss_opacity = (
                #     self.sky_opacity_loss_fn(pred_ground_occupied_mask, gt_ground_occupied_mask, valid_loss_mask)
                #     * self.losses_dict.mask.w
                # )
                # loss_dict.update({"ground_loss_opacity": ground_loss_opacity})

            if VISUALIZATION_DEBUG and self.step % 10 == 0:
                debug_dir = "debug_opacities"
                os.makedirs(debug_dir, exist_ok=True)
                # Save the predicted and ground truth RGB images
                predicted_opacity_path = os.path.join(debug_dir, f"step_{self.step}_predicted_opacity_from_raw.png")
                imageio.imwrite(
                    predicted_opacity_path,
                    (torch.clamp(pred_occupied_mask, max=1.0) * 255).detach().cpu().numpy().astype(np.uint8),
                )
                # Save the ground truth RGB image
                gt_opacity_path = os.path.join(debug_dir, f"step_{self.step}_gt_opacity_from_raw.png")
                imageio.imwrite(gt_opacity_path, (gt_occupied_mask * 255).detach().cpu().numpy().astype(np.uint8))

        # depth loss
        if not from_synthesis and self.depth_loss_fn and image_info.depth_map is not None:
            gt_depth = image_info.depth_map
            lidar_hit_mask = (gt_depth > 0).float() * valid_loss_mask
            pred_depth = outputs["depth"]

            ground_depth_only = self.losses_dict.depth.get("ground_depth_only", False)
            if ground_depth_only:
                non_dynamic_mask = 1.0 - image_info.masks.dynamic_mask.float()
                ground_mask = image_info.masks.ground_mask.float()
                lidar_hit_mask = lidar_hit_mask * non_dynamic_mask * ground_mask

            exclude_dyn_sky = self.losses_dict.depth.get("exclude_dyn_sky", False)
            if exclude_dyn_sky:
                non_dynamic_mask = 1.0 - image_info.masks.dynamic_mask.float()
                if image_info.masks.sky_mask is not None:
                    non_sky_mask = 1.0 - image_info.masks.sky_mask.float()
                else:
                    non_sky_mask = torch.ones_like(image_info.masks.dynamic_mask.float())
                exclude_dyn_sky_mask = non_dynamic_mask * non_sky_mask
                lidar_hit_mask = lidar_hit_mask * exclude_dyn_sky_mask
            depth_loss = self.depth_loss_fn(pred_depth, gt_depth, lidar_hit_mask)

            lidar_w_decay = self.losses_dict.depth.get("lidar_w_decay", -1)
            if lidar_w_decay > 0:
                decay_weight = np.exp(-self.step / 8000 * lidar_w_decay)
            else:
                decay_weight = 1
            depth_loss = depth_loss * self.losses_dict.depth.w * decay_weight
            loss_dict.update({"depth_loss": depth_loss})

            if VISUALIZATION_DEBUG and self.step % 10 == 0:
                debug_dir = "debug_depths"
                os.makedirs(debug_dir, exist_ok=True)

                pred_depth = outputs["depth"].squeeze().detach().clone()
                valid_mask = (gt_depth > 0.01) & (gt_depth < 100.0) & (pred_depth > 0.0001) & lidar_hit_mask.bool()

                rgb_with_pred = gt_rgb.detach().clone()
                if valid_mask.any():
                    normalized_depth = torch.clamp(pred_depth / 100.0, 0, 1)
                    depth_colors = depth_to_rainbow_colors(normalized_depth)

                    rgb_with_pred[valid_mask] = depth_colors[valid_mask]
                imageio.imwrite(
                    os.path.join(debug_dir, f"step_{self.step}_predicted_depth_from_raw.png"),
                    (torch.clamp(rgb_with_pred, 0, 1) * 255).detach().cpu().numpy().astype(np.uint8),
                )

                gt_depth_squeeze = gt_depth.squeeze()
                rgb_with_gt = gt_rgb.detach().clone()
                if valid_mask.any():
                    normalized_gt_depth = torch.clamp(gt_depth_squeeze / 100.0, 0, 1)
                    gt_depth_colors = depth_to_rainbow_colors(normalized_gt_depth)
                    rgb_with_gt[valid_mask] = gt_depth_colors[valid_mask]
                imageio.imwrite(
                    os.path.join(debug_dir, f"step_{self.step}_gt_depth_from_raw.png"),
                    (torch.clamp(rgb_with_gt, 0, 1) * 255).detach().cpu().numpy().astype(np.uint8),
                )

        # ----- reg loss -----
        opacity_entropy_reg = self.losses_dict.get("opacity_entropy", None)
        if opacity_entropy_reg is not None:
            pred_opacity = torch.clamp(outputs["opacity"].squeeze(), 1e-6, 1 - 1e-6)
            loss_dict.update(
                {"opacity_entropy_loss": opacity_entropy_reg.w * (-pred_opacity * torch.log(pred_opacity)).mean()}
            )

        # # from pvg: https://github.com/fudan-zvg/PVG/blob/b4162a9135282e0f3c929054f16be1b3fbacd77a/train.py#L161
        # inverse_depth_smoothness_reg = self.losses_dict.get("inverse_depth_smoothness", None)
        # if inverse_depth_smoothness_reg is not None:
        #     inverse_depth = 1 / (outputs["depth"] + 1e-5)
        #     loss_inv_depth = kornia.losses.inverse_depth_smoothness_loss(
        #         inverse_depth[None].repeat(1, 1, 1, 3).permute(0, 3, 1, 2),
        #         image_info.pixels[None].permute(0, 3, 1, 2),
        #     )
        #     loss_dict.update({"inverse_depth_smoothness_loss": inverse_depth_smoothness_reg.w * loss_inv_depth})

        # affine reg loss
        affine_reg = self.losses_dict.get("affine", None)
        if not from_synthesis and affine_reg is not None and "Affine" in self.models:
            affine_trs = self.models["Affine"](image_info, cam_info)
            reg_mat = torch.eye(3, device=self.device)
            reg_shift = torch.zeros(3, device=self.device)
            loss_affine = (
                torch.abs(affine_trs[..., :3, :3] - reg_mat).mean()
                + torch.abs(affine_trs[..., :3, 3:] - reg_shift).mean()
            )
            loss_dict.update({"affine_loss": affine_reg.w * loss_affine})

        # dynamic region loss
        dynamic_region_weighted_losses = self.losses_dict.get("dynamic_region", None)
        if not from_synthesis and dynamic_region_weighted_losses is not None:
            weight_factor = dynamic_region_weighted_losses.get("w", 1.0)
            start_from = dynamic_region_weighted_losses.get("start_from", 0)
            if self.step >= start_from:
                self.render_dynamic_mask = True
            if self.step > start_from and "Dynamic_opacity" in outputs:
                dynamic_pred_mask = (outputs["Dynamic_opacity"].detach().data > 0.2).squeeze()
                dynamic_pred_mask = dynamic_pred_mask & valid_loss_mask.bool()

                if dynamic_pred_mask.sum() > 0:
                    Ll1 = torch.abs(gt_rgb[dynamic_pred_mask] - predicted_rgb[dynamic_pred_mask]).mean()
                    loss_dict.update(
                        {
                            "vehicle_region_rgb_loss": weight_factor * Ll1,
                        }
                    )

        # dynamic opacity loss
        dynamic_opacity_losses = self.losses_dict.get("dynamic_opacity", None)
        if not from_synthesis and dynamic_opacity_losses is not None:
            weight_factor = dynamic_opacity_losses.get("w", 1.0)
            start_from = dynamic_opacity_losses.get("start_from", 0)
            if self.step >= start_from:
                self.render_dynamic_mask = True
                self.use_grad_dynamic_opacity = True
            if self.step > start_from and "Dynamic_opacity" in outputs:
                obj_opacity = torch.clamp(outputs["Dynamic_opacity"].squeeze(), min=1e-6, max=1.0 - 1e-6)
                obj_opacity_loss = torch.where(
                    image_info.masks.dynamic_mask.bool(),
                    -(obj_opacity * torch.log(obj_opacity) + (1.0 - obj_opacity) * torch.log(1.0 - obj_opacity)),
                    -torch.log(1.0 - obj_opacity),
                ).mean()
                loss_dict.update({"dynamic_opacity_loss": weight_factor * obj_opacity_loss})

        # fake cam grd loss, grd opacity should be close to 1
        fake_downwards_cam = self.losses_dict.get("fake_downwards_cam", None)
        if not from_synthesis and fake_downwards_cam is not None and cam_info.camera_name == fake_downwards_cam.cam_name:
            novel_output = self.render_camera_downwards(cam_info, image_info)
            grd_opacity = novel_output["opacity"]
            novel_grd_acc_loss = (-torch.log(
                torch.clamp(grd_opacity, min=1e-6, max=1.-1e-6)
            )).mean()
            loss_dict.update(
                {"fake_downwards_cam": fake_downwards_cam.w * novel_grd_acc_loss}
            )

        # compute gaussian reg loss
        for class_name in self.gaussian_classes.keys():
            class_reg_loss = self.models[class_name].compute_reg_loss()
            for k, v in class_reg_loss.items():
                loss_dict[f"{class_name}_{k}"] = v
        return loss_dict

    def compute_metrics(self, outputs: Dict[str, torch.Tensor], image_info: ImageInfo) -> Dict[str, torch.Tensor]:
        metric_dict = {}
        psnr = self.psnr(outputs["rgb"], image_info.pixels)
        metric_dict.update({"psnr": psnr})
        return metric_dict

    def get_gaussian_count(self):
        num_dict = {}
        for class_name in self.gaussian_classes.keys():
            num_dict[class_name] = self.models[class_name].num_points
        return num_dict

    def save_checkpoint(self, log_dir: str, save_only_model: bool = True, is_final: bool = False) -> None:
        """
        Save model to checkpoint.
        """
        num_finished_step = self.step + 1
        if is_final:
            ckpt_path = os.path.join(log_dir, "checkpoint_final.pth")
        else:
            ckpt_path = os.path.join(log_dir, f"checkpoint_{(num_finished_step):05d}.pth")
        torch.save(self.state_dict(only_model=save_only_model), ckpt_path)
        logger.info(f"Saved a checkpoint to {ckpt_path}")

    def init_viewer(self, port: int = 8080):
        # a simple viewer for background ONLY visualization
        self.server = viser.ViserServer(port=port, verbose=False)
        self.viewer = nerfview.Viewer(
            server=self.server,
            render_fn=self._viewer_render_fn,
            mode="training",
        )

    @torch.no_grad()
    def _viewer_render_fn(self, camera_state: nerfview.CameraState, img_wh: Tuple[int, int]):
        """Callable function for the viewer."""
        W, H = img_wh
        c2w = camera_state.c2w
        K = camera_state.get_K(img_wh)
        c2w = torch.from_numpy(c2w).float().to(self.device)
        K = torch.from_numpy(K).float().to(self.device)

        camera_id = getattr(camera_state, "camera_id", 0)
        timestep_id = getattr(camera_state, "timestep_id", 0)
        novel_view = getattr(camera_state, "novel_view", False)

        cam = dataclass_camera(
            camera_id=camera_id,
            timestep_id=timestep_id,
            novel_view=novel_view,
            camtoworlds=c2w,
            camtoworlds_gt=c2w,
            Ks=K,
            H=H,
            W=W,
        )

        gs_dict = {
            "_means": [],
            "_scales": [],
            "_quats": [],
            "_rgbs": [],
            "_opacities": [],
        }
        for class_name in ["Background"]:
            gs = self.models[class_name].get_gaussians(cam)
            if gs is None:
                continue

            for k, _ in gs.items():
                gs_dict[k].append(gs[k])

        for k, v in gs_dict.items():
            gs_dict[k] = torch.cat(v, dim=0)

        gs = dataclass_gs(
            _means=gs_dict["_means"],
            _scales=gs_dict["_scales"],
            _quats=gs_dict["_quats"],
            _rgbs=gs_dict["_rgbs"],
            _opacities=gs_dict["_opacities"],
            detach_keys=[],
            extras=None,
        )

        render_colors, _, _ = rasterization(
            means=gs.means,
            quats=gs.quats,
            scales=gs.scales,
            opacities=gs.opacities.squeeze(),
            colors=gs.rgbs,
            viewmats=torch.linalg.inv(cam.camtoworlds)[None, ...],  # [C, 4, 4]
            Ks=cam.Ks[None, ...],  # [C, 3, 3]
            width=cam.W,
            height=cam.H,
            packed=self.render_cfg.packed,
            absgrad=self.render_cfg.absgrad,
            sparse_grad=self.render_cfg.sparse_grad,
            rasterize_mode="antialiased" if self.render_cfg.antialiased else "classic",
            radius_clip=4.0,  # skip GSs that have small image radius (in pixels)
        )
        return render_colors[0].cpu().numpy()