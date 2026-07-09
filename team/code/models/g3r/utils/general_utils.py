import os
import sys
import math
import yaml
import enum
import torch
import gsplat
import numpy as np
from PIL import Image
from typing import List
from pathlib import Path
from .loss_utils import psnr_metric

current_dir = os.path.dirname(__file__)
root_path = os.path.abspath(os.path.join(current_dir, "..", ".."))
sys.path.append(root_path)
from street_gaussians.lib.utils.lpipsPyTorch import lpips


DATASET_CLASSES_IN_SEMANTIC = {
    'GROUND': [7, 8, 13, 14, 23, 24, 41, 10, 36, 43],
    'SKY': [27],
    'VEHICLE': [52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65],
    'HUMAN': [0, 1, 19, 20, 21, 22],
    'ROADSIDE': [2, 3, 4, 5, 6, 9, 11, 12, 15, 16, 18, 26, 28]
}

class NetMode(enum.IntEnum):
    TRAIN = 0
    INFERENCE = 1

class SemanticType(enum.IntEnum):
    DEFAULT = 0
    GROUND = 1
    SKY = 2
    VEHICLE = 3
    HUMAN = 4
    ROADSIDE = 5

def get_semantics_from_path(filepath: Path, scale_factor: float = 1.0):
    pil_image = Image.open(filepath)
    if scale_factor != 1.0:
        width, height = pil_image.size
        newsize = (int(width * scale_factor), int(height * scale_factor))
        pil_image = pil_image.resize(newsize, resample=Image.NEAREST)
    image = np.array(pil_image, dtype="int32")
    if len(image.shape) == 3:
        image = image[:, :, 0]
    
    class_to_label = {
        SemanticType.VEHICLE.value: DATASET_CLASSES_IN_SEMANTIC['VEHICLE'],
        SemanticType.HUMAN.value: DATASET_CLASSES_IN_SEMANTIC['HUMAN'],
        SemanticType.GROUND.value: DATASET_CLASSES_IN_SEMANTIC['GROUND'],
        SemanticType.SKY.value: DATASET_CLASSES_IN_SEMANTIC['SKY'],
        SemanticType.ROADSIDE.value: DATASET_CLASSES_IN_SEMANTIC['ROADSIDE'],
    }
    semantics = np.zeros_like(image)
    for label, class_ids in class_to_label.items():
        semantics[np.isin(image, class_ids)] = label

    semantics = torch.from_numpy(semantics).unsqueeze(-1)
    return semantics.to(torch.uint8)

def get_mask_from_semantics(semantics, mask_indices):
    if isinstance(mask_indices, List):
        mask_indices = torch.tensor(mask_indices, dtype=torch.uint8).view(1, 1, -1).cuda()
    # return mask if semantics are in the mask indices
    mask = torch.sum(semantics == mask_indices, dim=-1, keepdim=True) == 1
    return mask

def depth_to_rgb(depth):
    min_depth = 0
    max_depth = 200
    normalized_depth = (depth - min_depth) / (max_depth - min_depth)
    r = int(normalized_depth * 255)
    g = 0
    b = int((1 - normalized_depth) * 255)
    return r, g, b

def load_yaml(config_path):
    with open(config_path, 'rb') as f:
        config = yaml.safe_load(f)
    return config

def get_cosine_schedule(num_train_timesteps, beta_start=0.0001, beta_end=0.02, s=0.008):
    timesteps = torch.arange(num_train_timesteps)
    return torch.cos((timesteps / num_train_timesteps + s) / (1 + s) * math.pi / 2) ** 2

def get_ddim_schedule(T, device):
    steps = torch.linspace(0, 1, T + 1)
    alphas_cumprod = torch.cos((steps * math.pi) / 2) ** 2
    alphas_cumprod = alphas_cumprod / alphas_cumprod[0]  # 非原地操作
    gammas = torch.sqrt(alphas_cumprod[1:] / alphas_cumprod[:-1])
    return gammas.to(device)

def convert_torch_img(torch_img):
    torch_img = (torch_img.clamp(0., 1.).detach().cpu().numpy() * 255).astype(np.uint8)
    if torch_img.shape[0] == 1 or torch_img.shape[0] == 3:
        torch_img = torch_img.transpose(1, 2, 0)
    if torch_img.shape[-1] == 1:
        torch_img = torch_img.squeeze(-1)
    img = Image.fromarray(torch_img)
    return img

def save_img_torch(gt_image, render_img, save_path):
    gt_image = convert_torch_img(gt_image)
    render_img = convert_torch_img(render_img)
    concat_image = Image.new(
        mode="RGB",
        size=(gt_image.width, gt_image.height * 2)
    )

    concat_image.paste(gt_image, (0, 0))
    concat_image.paste(render_img, (0, gt_image.height))
    concat_image.save(save_path)
    return

def metric_evaluation(total_cameras_info, gaussians, log_folder, save_img=False):
    metric_output = {}
    psnr_list = []
    lpips_list = []
    for cam_name, cam_info_list in total_cameras_info.items():
        curr_psnr_list = []
        curr_lpips_list = []
        for cam_info in cam_info_list:
            gt_images_stack = cam_info["images"].cuda()
            width = gt_images_stack[0].shape[2]
            height = gt_images_stack[0].shape[1]
            timestamps = cam_info["timestamps"]

            rendered_images, _, _ = gsplat.rasterization(
                means=gaussians['means'].cuda(),
                quats=gaussians['rotations'].cuda(),  # w x y z
                scales=gaussians['scales'].cuda(),
                opacities=gaussians['opacities'].cuda(),
                colors=gaussians['colors'].cuda(),
                viewmats=cam_info["extrinsics"].cuda(),
                Ks=cam_info["intrinsics"].cuda(),
                width=width,
                height=height,
                near_plane=0.01,
                far_plane=1e10,
                sparse_grad=False,
                rasterize_mode="antialiased",
                absgrad=True,
                packed=False
            )

            rendered_images = rendered_images.permute(0, 3, 1, 2)
            mask = (gt_images_stack == 0).all(dim = 1)
            mask = mask.unsqueeze(1).expand_as(rendered_images)
            rendered_images[mask] = 0
            psnr_val = psnr_metric(rendered_images, gt_images_stack, ~mask)
            lpips_val = lpips(rendered_images, gt_images_stack, net_type='alex')
            psnr_list.append(psnr_val.item())
            lpips_list.append(lpips_val.item())
            curr_psnr_list.append(psnr_val.item())
            curr_lpips_list.append(lpips_val.item())

            if save_img:
                for img_id in range(0, rendered_images.shape[0]):
                    save_path = os.path.join(log_folder, f"{cam_name}_{timestamps[img_id]}.png")
                    curr_render_img = rendered_images[img_id, ...]
                    curr_gt_img = gt_images_stack[img_id, ...]
                    save_img_torch(curr_gt_img, curr_render_img, save_path)

        if len(curr_psnr_list) > 0:
            metric_output[cam_name + "_psnr"] = sum(curr_psnr_list) / len(curr_psnr_list)
            metric_output[cam_name + "_lpips"] = sum(curr_lpips_list) / len(curr_lpips_list)
    metric_output["total_psnr"] = sum(psnr_list) / len(psnr_list)
    metric_output["total_lpips"] = sum(lpips_list) / len(lpips_list)
    return metric_output
