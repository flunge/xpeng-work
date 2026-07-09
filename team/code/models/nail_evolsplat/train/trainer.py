from __future__ import annotations
import cv2
import functools
import os
import sys
import time
from pathlib import Path
from threading import Lock
from typing import DefaultDict, Dict, List, Literal, Optional, Tuple, Type, cast
import torch
import random
import numpy as np
from torch.cuda.amp.grad_scaler import GradScaler
from torch.utils.tensorboard import SummaryWriter
from torchmetrics.image import PeakSignalNoiseRatio
from pytorch_msssim import SSIM
import torchvision.utils as vutils
import json 
from nail_evolsplat.data_manager import Datamanager
from nail_evolsplat.train.optimizers import Optimizers
from nail_evolsplat.train.down_load_clip import down_training_data,cp_training_data
from nail_evolsplat.model.model import load_model
from nail_evolsplat.train.config import obtain_config
current_dir = os.path.dirname(__file__)
repo_root = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
_ucp_dir = os.path.join(repo_root, "pipeline", "ucp")
_models_dir = os.path.join(repo_root, "models")
for _p in (_ucp_dir, _models_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from download_file_from_oss2 import download_file_from_oss2


class Trainer:
    optimizers: Optimizers
    def __init__(self, config = None,local_rank: int = 0, world_size: int = 1) -> None:
        self.config = config
        self.ssim_lambda = self.config["ssim_lambda"]
        self.num_iterations = self.config["num_iterations"]
        self.root_data_folder = self.config["root_data_folder"]
        os.makedirs(self.root_data_folder, exist_ok=True)

        self.scenes = self.config["scenes"]
        self.eval_scenes = self.config["eval_scenes"]
        self.output_dir = self.config["output_dir"]
        self.weight_entropy_loss = self.config["weight_entropy_loss"]
        self.device= self.config["device"]
        self.optimizer_config = self.config["optimizer_config"]
        self.pth_path = os.path.join(self.root_data_folder, "evolsplat.ckpt")
        self.local_rank = local_rank
        self.world_size = world_size
        self._start_step: int = 0
        self.grad_scaler = GradScaler(enabled=False)
        self.step = 0
        self.psnr = PeakSignalNoiseRatio(data_range=1.0).to(self.device)
        self.ssim = SSIM(data_range=1.0, size_average=True, channel=3).to(self.device)
        
        self.tensorboard_dir = os.path.join(self.output_dir, "tensorboard")
        os.makedirs(self.tensorboard_dir, exist_ok=True)
        self.writer = SummaryWriter(log_dir=self.tensorboard_dir)
        
        self.image_log_freq = self.config.get("image_log_freq", 50)
        
        self.setup()
        
    def download_pth(self):
        t1 = time.time()
        if not os.path.exists(self.pth_path):
            download_file_from_oss2(self.pth_path, "sim_engine/evolsplat_pth/step-000253500.ckpt")
        t2 = time.time()
        print("[INFO] Download models/g3r pth time: ", t2 - t1)
        return
    
    def setup(self, test_mode: Literal["test", "val", "inference"] = "val") -> None:
        self.download_pth()
        self.model_train = load_model(ckpt_path = self.pth_path,train_mode = True)
        self.optimizers = self.setup_optimizers()

    def setup_optimizers(self) -> Optimizers:
        param_groups = self.model_train.get_param_groups()
        return Optimizers(self.optimizer_config, param_groups)

    def get_metrics_dict(self, outputs, batch) -> Dict[str, torch.Tensor]:
        gt_rgb = batch['target']["image"].squeeze(0)
        metrics_dict = {}
        predicted_rgb = outputs["rgb"]
        metrics_dict["psnr"] = self.psnr(predicted_rgb, gt_rgb)
        return metrics_dict
    
    def get_loss_dict(self, outputs, batch, metrics_dict=None) -> Dict[str, torch.Tensor]:
        gt_img = batch['target']["image"].squeeze(0)
        pred_img = outputs["rgb"]
        gt_img[pred_img == 0] = 0
       
        if self.step % 10 == 0:
            entorpy_loss =  self.weight_entropy_loss * (
                            - outputs['accumulation'] * torch.log(outputs['accumulation'] + 1e-10)
                            - (1 - outputs['accumulation']) * torch.log(1 - outputs['accumulation'] + 1e-10)
                            ).mean()
        else:
            entorpy_loss = torch.tensor(0.0).to(self.device)

        Ll1 = torch.abs(gt_img - pred_img).mean()
        simloss = 1 - self.ssim(gt_img.permute(2, 0, 1)[None, ...], pred_img.permute(2, 0, 1)[None, ...])

        loss_dict = {
            "main_loss": (1 - self.ssim_lambda) * Ll1 + self.ssim_lambda * simloss,
            "entorpy_loss": entorpy_loss,
        }

        return loss_dict


    def get_image_metrics_and_images(
        self, outputs, batch, camera
    ) -> Tuple[Dict[str, float], Dict[str, torch.Tensor]]:
        gt_rgb = batch['target']["image"].squeeze(0)# type: ignore
        predicted_rgb = outputs["rgb"]
        Ll1_loss = torch.abs(gt_rgb - predicted_rgb).mean()

        combined_rgb = torch.cat([gt_rgb, predicted_rgb], dim=1)
        gt_rgb = torch.moveaxis(gt_rgb, -1, 0)[None, ...]
        predicted_rgb = torch.moveaxis(predicted_rgb, -1, 0)[None, ...]
        gt_rgb = torch.clamp(gt_rgb, 0.0, 1.0)
        predicted_rgb = torch.clamp(predicted_rgb, 0.0, 1.0)
        psnr = self.psnr(gt_rgb, predicted_rgb)
        ssim = self.ssim(gt_rgb, predicted_rgb)
        simloss = 1 - ssim
        main_loss = (1 - self.ssim_lambda) * Ll1_loss + self.ssim_lambda * simloss
        metrics_dict = {
            f"{camera.camera_type[0][0]}_Ll1_loss": float(Ll1_loss.item()),\
            f"{camera.camera_type[0][0]}_ssimloss": float(simloss.item()),\
            f"{camera.camera_type[0][0]}_main_loss": float(main_loss.item()),\
            f"{camera.camera_type[0][0]}_psnr": float(psnr.item()),\
            f"{camera.camera_type[0][0]}_ssim": float(ssim)}
        images_dict = {"img": combined_rgb}
        return metrics_dict, images_dict


    def get_average_image_metrics(
        self,
        data_manager,
        image_prefix: int,
        output_path: Optional[Path] = None,
        get_std: bool = False,
    ):
        metrics_dict_list = []
        if output_path is not None:
            output_path.mkdir(exist_ok=True, parents=True)
        data_length = data_manager.get_data_length()
        for idx in (range(data_length)):
            camera, batch = data_manager.get_next_data(idx)
            inner_start = time.time()
            outputs = self.model_train.get_outputs(camera, batch)
            if outputs is None:
                continue
            metrics_dict, image_dict = self.get_image_metrics_and_images(outputs, batch, camera)
            if output_path is not None and idx%30==0:
                for key in image_dict.keys():
                    image = image_dict[key]
                    vutils.save_image(
                        image.permute(2, 0, 1).cpu(), output_path / f"{image_prefix}_{key}_{idx:04d}.png"
                    )
            metrics_dict_list.append(metrics_dict)
            idx = idx + 1

        metrics_dict = {}
        grouped_data = {}
        for item in metrics_dict_list:
            for key, value in item.items():
                if key not in grouped_data:
                    grouped_data[key] = []
                grouped_data[key].append(value)
        mean_results = {}
        for key, values in grouped_data.items():
            mean_results[key] = sum(values) / len(values)
        return mean_results

    def save_eval_metrics_to_file(self, json_file_path , eval_metrics_dict: Dict[str, Dict]) -> None:
        if not eval_metrics_dict:
            print("No evaluation metrics to save.")
            return
        json_metrics = {}
        for scene_id, metrics_dict in eval_metrics_dict.items():
            json_metrics[scene_id] = {}
            for metric_name, metric_value in metrics_dict.items():
                if isinstance(metric_value, torch.Tensor):
                    json_metrics[scene_id][metric_name] = metric_value.item()
                elif isinstance(metric_value, (list, tuple)):
                    json_metrics[scene_id][metric_name] = [
                        v.item() if isinstance(v, torch.Tensor) else v for v in metric_value
                    ]
                else:
                    json_metrics[scene_id][metric_name] = metric_value
        with open(json_file_path, 'w', encoding='utf-8') as f:
            json.dump(json_metrics, f, indent=2, ensure_ascii=False)





    def train(self) -> None:
        global_step = 0  # Global step counter for TensorBoard
        eval_step = 0
        eval_metrics_dict_list = {}
        try:
            for step in range(self._start_step, self._start_step + self.num_iterations):
                if True:
                    self.model_train.eval()
                    self.model_train.training = False
                    image_prefix = "eval_per"
                    name_num_step = f"{str(step)}"
                    for eval_scene_id in self.eval_scenes:
                        name_num=f"{name_num_step}_test_{eval_scene_id[:8]}"
                        download_status = down_training_data(self.root_data_folder, eval_scene_id)
                        if not download_status:
                            print("Case Download False")
                            continue
                        output_folder = os.path.join(self.output_dir, image_prefix, eval_scene_id)
                        os.makedirs(output_folder, exist_ok=True)
                        data_manager = Datamanager(eval_scene_id, self.root_data_folder, output_folder)
                        data_length = data_manager.get_data_length()
                        seed_points = data_manager.get_seed_points()
                        self.model_train.set_datas_init(data_length, seed_points ,output_folder)
                        self.model_train = self.model_train.to("cuda")
                        self.model_train.scene_gaussians = None
                        metrics_dict= self.get_average_image_metrics(
                                data_manager, name_num, Path(output_folder), get_std = False
                            )
                        eval_metrics_dict_list[name_num]=metrics_dict
                    json_file_path = os.path.join(self.output_dir, image_prefix, "eval.json")
                    self.save_eval_metrics_to_file(json_file_path , eval_metrics_dict_list)
                    self.save_checkpoint(global_step)
                for scene_id in self.scenes:
                    eval_step = eval_step+1
                    self.model_train.train()
                    self.model_train.training = True
                    download_status = down_training_data(self.root_data_folder, scene_id)
                    if not download_status:
                        print("Case Download False")
                        continue
                    
                    output_folder = os.path.join(self.output_dir, scene_id)
                    os.makedirs(output_folder, exist_ok=True)
                    data_manager = Datamanager(scene_id, self.root_data_folder, output_folder)
                    data_length = data_manager.get_data_length()
                    seed_points = data_manager.get_seed_points()
                    self.model_train.set_datas_init(data_length, seed_points ,output_folder)
                    self.model_train = self.model_train.to("cuda")
                    for idx in (range(data_length)):
                        camera, batch = data_manager.get_next_data(idx)
                        needs_zero = [
                            group for group in self.optimizers.parameters.keys()
                        ]
                        self.optimizers.zero_grad_some(needs_zero)
                        model_outputs = self.model_train.get_outputs(camera, batch)
                        if model_outputs is None:
                            print(f"scene_id {scene_id} idx {idx} is something wrong")
                            continue
                        original_gt = batch['target']["image"] 
                        gt_img = original_gt.squeeze(0)  
                        pred_img = model_outputs["rgb"]  
                        gt_img_masked = gt_img
                        gt_img_masked[pred_img == 0] = 0
                        batch['target']["image"] = gt_img_masked.unsqueeze(0)  # Restore to original shape (1, H, W, C)
                        metrics_dict = self.get_metrics_dict(model_outputs, batch)
                        loss_dict = self.get_loss_dict(model_outputs, batch, metrics_dict)
                        print("loss_dict ", loss_dict)
                        loss = functools.reduce(torch.add, loss_dict.values())
                        self.grad_scaler.scale(loss).backward()  # type: ignore
                        needs_step = [
                            group
                            for group in self.optimizers.parameters.keys()
                        ]
                        self.optimizers.optimizer_scaler_step_some(self.grad_scaler, needs_step)
                        scale = self.grad_scaler.get_scale()
                        self.grad_scaler.update()
                        if scale <= self.grad_scaler.get_scale():
                            self.optimizers.scheduler_step_all(global_step)
                            


                        if idx % self.image_log_freq == 0:
                            render_rgb = model_outputs["rgb"]
                            render_np = render_rgb.detach().cpu().numpy()
                            render_np = (render_np * 255).clip(0, 255).astype(np.uint8)
                            render_bgr = cv2.cvtColor(render_np, cv2.COLOR_RGB2BGR)
                            save_path = os.path.join(output_folder, f"render_{scene_id}_{step}_{global_step}.png")
                            cv2.imwrite(save_path, render_bgr)
                            self.writer.add_scalar("Loss/Total", loss.item(), global_step)
                            for loss_name, loss_value in loss_dict.items():
                                self.writer.add_scalar(f"Loss/{loss_name}", loss_value.item(), global_step)
                                self.writer.add_scalar(f"Loss_{step}_{scene_id}_{idx}/{loss_name}", loss_value.item(), global_step)
                            for metric_name, metric_value in metrics_dict.items():
                                if isinstance(metric_value, torch.Tensor):
                                    self.writer.add_scalar(f"Metrics/{metric_name}", metric_value.item(), global_step)
                                    self.writer.add_scalar(f"Metrics_{step}_{scene_id}_{idx}/{metric_name}", metric_value.item(), global_step)
                                else:
                                    self.writer.add_scalar(f"Metrics/{metric_name}", metric_value, global_step)
                                    self.writer.add_scalar(f"Metrics_{step}_{scene_id}_{idx}/{metric_name}", metric_value, global_step)
                            self.writer.add_scalar("Learning_Rate/Grad_Scale", self.grad_scaler.get_scale(), global_step)
                            gt_img_tb = gt_img.detach().cpu().clamp(0, 1).permute(2, 0, 1)
                            pred_img_tb = pred_img.detach().cpu().clamp(0, 1).permute(2, 0, 1)
                            cam_name = f'scene_{scene_id}_{step}_idx_{idx}_{camera.camera_type[0][0]}'
                            self.writer.add_image(f"Images/{cam_name}/Ground_Truth", gt_img_tb, global_step)
                            self.writer.add_image(f"Images/{cam_name}/Rendered", pred_img_tb, global_step)
                            comparison_img = torch.cat([gt_img_tb, pred_img_tb], dim=2)
                            self.writer.add_image(f"Images/{cam_name}/Comparison_GT_vs_Rendered", comparison_img, global_step)
                            for group_name, optimizer in self.optimizers.optimizers.items():
                                for param_group in optimizer.param_groups:
                                    self.writer.add_scalar(f"Learning_Rate/{group_name}", param_group["lr"], global_step)
                        global_step += 1

                            
                    if self.config.get("delete_origin_data", False):
                        print(f"rm -rf {os.path.join(self.root_data_folder, scene_id)}")
                        os.system(f"rm -rf {os.path.join(self.root_data_folder, scene_id)}")

            self.writer.close()
        except:
            print(f'[ERROR] failed to train ')
            self.save_checkpoint(global_step)

    def save_checkpoint(self, step: int) -> None:
        os.makedirs(self.output_dir, exist_ok=True)
        ckpt_path = Path(os.path.join(self.output_dir , f"step-{step:09d}.ckpt"))
        print("-------------ckpt_path-------------- ", ckpt_path)
        torch.save(self.model_train.state_dict(), ckpt_path)


if __name__ == "__main__":
    random.seed(42)
    np.random.seed(42)
    torch.manual_seed(42)
    torch.cuda.manual_seed_all(42)
    import argparse
    import yaml

    parser = argparse.ArgumentParser(description = "evosplat Train Pipeline")
    parser.add_argument("--config_path", type=str, required=False)
    args = parser.parse_args()
    with open(args.config_path, 'r') as f:
        config_yaml_info = yaml.load(f, Loader=yaml.FullLoader)

    config = obtain_config(config_yaml_info)


    trainer = Trainer(config)
    trainer.train()