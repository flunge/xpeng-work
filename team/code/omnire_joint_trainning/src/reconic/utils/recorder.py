import torch
import os
from torch.utils.tensorboard import SummaryWriter

from reconic.utils.eval import psnr


class Recorder:
    """
    description: A class to evaluate the model during training. 
    Logging with exponential moving average (EMA) for loss and PSNR.
    """
    def __init__(self, cfg, args):
        record_path = os.path.join(cfg.xpeng_trainer.record_dir, args.project, args.run_name)
        self.tb_writer = SummaryWriter(record_path)
        self.record_interval = cfg.xpeng_trainer.record_interval
        self.ema_loss_for_log = 0.0
        self.ema_psnr_for_log = 0.0
        self.loss_dict = {}
        self.psnr_dict = {}

    @torch.no_grad()
    def update(self, iteration, train_data, outputs, loss_dict_step, trainer):
        cam_name = train_data[2].camera_name
        image_info = train_data[1]
        image = outputs['rgb']
        gt_image = image_info.pixels
        mask = 1 - image_info.masks.egocar_mask             # black area to be masked
        ground_mask = image_info.masks.ground_mask          # white area is ground
        non_sky_area = (1. - image_info.masks.sky_mask) * mask
        self.update_metrics(loss_dict_step, image, gt_image, mask, ground_mask, non_sky_area, cam_name)
        if iteration % self.record_interval == 0:
            self.update_report(iteration, trainer)
    
    def update_metrics(self, loss_dict_step, image, gt_image, mask, ground_mask_real, non_sky_area_real, cam_name):
        # check if loss is digit
        loss = loss_dict_step['rgb_loss']
        if not torch.isnan(loss) and not torch.isinf(loss):
            self.ema_loss_for_log = 0.4 * loss.item() + 0.6 * self.ema_loss_for_log
            self.ema_psnr_for_log = 0.4 * psnr(image, gt_image, mask).mean().float() + 0.6 * self.ema_psnr_for_log
        else:
            # return False if metric is not updated
            return False
        
        # update loss 
        for key, value in loss_dict_step.items():
            self.loss_dict[cam_name + "_" + key] = value.item()
        
        # update psnr dict
        if ground_mask_real is not None:
            if f'{cam_name}_ground' not in self.psnr_dict:
                self.psnr_dict[f'{cam_name}_ground'] = psnr(image, gt_image, ground_mask_real).mean().float()
            else:
                self.psnr_dict[f'{cam_name}_ground'] = 0.4 * psnr(image, gt_image, ground_mask_real).mean().float() + \
                    0.6 * self.psnr_dict[f'{cam_name}_ground']

        if non_sky_area_real is not None:
            if f'{cam_name}_non_sky' not in self.psnr_dict:
                self.psnr_dict[f'{cam_name}_non_sky'] = psnr(image, gt_image, non_sky_area_real).mean().float()
            else:
                self.psnr_dict[f'{cam_name}_non_sky'] = 0.4 * psnr(image, gt_image, non_sky_area_real).mean().float() + \
                    0.6 * self.psnr_dict[f'{cam_name}_non_sky']

        return True
    
    def update_report(self, iteration, trainer):
        # Update
        scalar_dict = {}
        for key, value in trainer.models.items():
            if hasattr(value, 'num_points'):
                scalar_dict[f"number_{key}"] = value.num_points
        scalar_dict['ema_loss'] = self.ema_loss_for_log
        scalar_dict['ema_psnr'] = self.ema_psnr_for_log
        for key, value in self.psnr_dict.items():
            scalar_dict['psnr_' + key] = value.item()
        for key, value in self.loss_dict.items():
            scalar_dict['loss_' + key] = value
            
        for key, value in scalar_dict.items():
            self.tb_writer.add_scalar('train/' + key, value, iteration)
                
        