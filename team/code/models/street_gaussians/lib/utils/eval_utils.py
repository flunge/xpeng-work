import os
import torch
from lib.utils.loss_utils import psnr


class EvaluatorInTrainer:
    def __init__(self):
        self.ema_loss_for_log = 0.0
        self.ema_psnr_for_log = 0.0
        self.loss_dict = {}
        self.psnr_dict = {}

    def update(self, loss, image, gt_image, mask, ground_mask_real, non_sky_area_real, cam_name):
        # check if loss is digit
        if not torch.isnan(loss) and not torch.isinf(loss):
            self.ema_loss_for_log = 0.4 * loss.item() + 0.6 * self.ema_loss_for_log
            self.ema_psnr_for_log = 0.4 * psnr(image, gt_image, mask).mean().float() + 0.6 * self.ema_psnr_for_log
        else:
            return False, self.ema_loss_for_log, self.ema_psnr_for_log, self.loss_dict, self.psnr_dict

        # update loss and psnr dict
        if cam_name not in self.psnr_dict:
            self.loss_dict[cam_name] = self.ema_loss_for_log
            self.psnr_dict[cam_name] = psnr(image, gt_image, mask).mean().float()
        else:
            self.loss_dict[cam_name] = 0.4 * self.ema_loss_for_log + 0.6 * self.loss_dict[cam_name]
            self.psnr_dict[cam_name] = 0.4 * psnr(image, gt_image, mask).mean().float() + 0.6 * self.psnr_dict[cam_name]
        
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

        return True, self.ema_loss_for_log, self.ema_psnr_for_log, self.loss_dict, self.psnr_dict