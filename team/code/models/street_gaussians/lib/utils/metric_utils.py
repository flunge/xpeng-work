import os
import cv2
import enum
import torch
import argparse
from PIL import Image
from pathlib import Path
import numpy as np
from typing import List
import torchvision.io as tvio
from lib.utils.loss_utils import psnr, ssim
from lib.utils.lpipsPyTorch import lpips
from lib.utils.xpeng_utils import get_mask_from_semantics, get_semantics_from_path
from lib.config.globals import SemanticType, DATASET_CLASSES_IN_SEMANTIC

import ssl
ssl._create_default_https_context = ssl._create_unverified_context


def save_metric_images(image, gt_image, viewpoint, save_img_folder):
    if not os.path.exists(save_img_folder):
        os.mkdir(save_img_folder)

    image = 255 * (image.detach().cpu().numpy())
    image = image.transpose(1, 2, 0).astype(np.uint8)
    image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

    gt_image = 255 * (gt_image.detach().cpu().numpy())
    gt_image = gt_image.transpose(1, 2, 0).astype(np.uint8)
    gt_image = cv2.cvtColor(gt_image, cv2.COLOR_RGB2BGR)

    cv2.imwrite(os.path.join(save_img_folder, viewpoint.meta['cam'] + "_" + viewpoint.image_name + "_render.png"), image)
    cv2.imwrite(os.path.join(save_img_folder, viewpoint.meta['cam'] + "_" + viewpoint.image_name + "_gt.png"), gt_image)
    return


def obtain_mask(source_data_folder, cam_name, timestamp, mask_sem):
    seg_folder = os.path.join(source_data_folder, "segs", cam_name)
    seg_img = get_semantics_from_path(os.path.join(seg_folder, f"{timestamp}.png"))
    grd_mask = get_mask_from_semantics(seg_img, mask_sem)
    return grd_mask


def metric_calculation(iteration, source_data_folder, model_folder, iter, ground_psnr = True, \
        mask_sky = True, cam_list = ["cam0", "cam2", "cam3", "cam4", "cam5", "cam6"]):
    save_debug_img = False
    folder_name = os.path.join(model_folder, str(iter))

    for cam_name in cam_list:
        sum_id = 0
        total_psnr = 0
        total_ssim = 0
        # total_lpips = 0
        img_list = os.listdir(folder_name)

        for img_name in img_list:
            if img_name.endswith("_gt.png"):
                curr_cam_name = img_name[0:4]
                if curr_cam_name != cam_name:
                    continue

                sum_id += 1
                timestamp = img_name.split("_")[1]
                gt_img = tvio.read_image(os.path.join(folder_name, img_name)) / 255.0
                render_img = tvio.read_image(os.path.join(folder_name, img_name[:-6] + "render.png")) / 255.0
                camera_mask = tvio.read_image(os.path.join(source_data_folder, "masks", curr_cam_name, timestamp + ".png"))
                camera_mask = camera_mask != 0

                grd_mask = obtain_mask(source_data_folder, curr_cam_name, timestamp, SemanticType.GROUND)
                grd_mask_3c = grd_mask.squeeze(-1).unsqueeze(0).expand(3, -1, -1)
                if ground_psnr:
                    gt_img[~grd_mask_3c] = 0
                    render_img[~grd_mask_3c] = 0
                else:
                    gt_img[grd_mask_3c] = 0
                    render_img[grd_mask_3c] = 0
                
                if mask_sky:
                    sky_mask = obtain_mask(source_data_folder, curr_cam_name, timestamp, SemanticType.SKY)
                    sky_mask_3c = sky_mask.squeeze(-1).unsqueeze(0).expand(3, -1, -1)
                    gt_img[sky_mask_3c] = 0
                    render_img[sky_mask_3c] = 0

                camera_mask_3c = camera_mask.expand(3, -1, -1)
                gt_img[~camera_mask_3c] = 0
                render_img[~camera_mask_3c] = 0

                if save_debug_img:
                    render_img_cv2 = (render_img.permute(1, 2, 0).numpy() * 255).astype(np.uint8)
                    gt_img_cv2 = (gt_img.permute(1, 2, 0).numpy() * 255).astype(np.uint8)
                    cv2.imwrite(curr_cam_name + "_" + timestamp + "_" + str(sum_id) + "_render.png", render_img_cv2)
                    cv2.imwrite(curr_cam_name + "_" + timestamp + "_" + str(sum_id) + "_gt.png", gt_img_cv2)

                curr_psnr = psnr(render_img, gt_img, None).mean().double()
                total_psnr += curr_psnr.item()

                curr_ssim = ssim(render_img, gt_img).double()
                total_ssim += curr_ssim.item()

                # curr_lpips = lpips(render_img, gt_img, net_type='alex').double()
                # total_lpips += curr_lpips.item()

        if sum_id > 0:
            avg_psnr = total_psnr / sum_id
            psnr_txt = os.path.join(model_folder, str(iteration) + "_" + cam_name + "_psnr.txt")
            with open(psnr_txt, 'a', encoding='utf-8') as f:
                f.write(str(avg_psnr) + "\n")

            avg_ssim = total_ssim / sum_id
            ssim_txt = os.path.join(model_folder, str(iteration) + "_" + cam_name + "_ssim.txt")
            with open(ssim_txt, 'a', encoding='utf-8') as f:
                f.write(str(avg_ssim) + "\n")

            # avg_lpips = total_lpips / sum_id
            # lpips_txt = os.path.join(model_folder, cam_name + "_lpips.txt")
            # with open(lpips_txt, 'a', encoding='utf-8') as f:
            #     f.write(str(avg_lpips) + "\n")
    return
