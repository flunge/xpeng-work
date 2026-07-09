#
# Copyright (C) 2023, Inria
# GRAPHDECO research group, https://team.inria.fr/graphdeco
# All rights reserved.
#
# This software is free for non-commercial, research and evaluation use 
# under the terms of the LICENSE.md file.
#
# For inquiries contact  george.drettakis@inria.fr
#

import faiss 
import torch
import torch.nn.functional as F
from torch.autograd import Variable
from math import exp
from math import sqrt
import numpy as np


def l1_loss(network_output, gt, mask=None, weight=None):
    '''
    network_output, gt: (C, H, W)
    mask: (1, H, W) 
    '''

    network_output = network_output.permute(1, 2, 0) # [H, W, C]
    gt = gt.permute(1, 2, 0) # [H, W, C]

    if mask is not None:
        mask = mask.squeeze(0) # [H, W]
        network_output = network_output[mask]
        gt = gt[mask]
    
    if weight is not None:
        weight = weight.permute(1, 2, 0)
        weight = weight[mask]
        loss = ((torch.abs(network_output - gt) * weight)).mean()
    else:
        loss = ((torch.abs(network_output - gt))).mean()

    return loss

def l2_loss(network_output, gt, mask=None):
    '''
    network_output, gt: (C, H, W)
    mask: (1, H, W) 
    '''
    
    network_output = network_output.permute(1, 2, 0) # [H, W, C]
    gt = gt.permute(1, 2, 0) # [H, W, C]    
    
    if mask is not None:
        mask = mask.squeeze(0) # [H, W]
        network_output = network_output[mask]
        gt = gt[mask]

    loss =  (((network_output - gt) ** 2)).mean()

    return loss

    
def mse(img1, img2):
    return (((img1 - img2)) ** 2).view(img1.shape[0], -1).mean(1, keepdim=True)

def psnr(img1, img2, mask=None):
    '''
    img1, img2: (C, H, W)
    mask: (1, H, W)
    '''    
    
    img1 = img1.permute(1, 2, 0)
    img2 = img2.permute(1, 2, 0)
    
    if mask is not None:
        mask = mask.squeeze(0)
        img1 = img1[mask]
        img2 = img2[mask]
    
    # mse = ((img1 - img2) ** 2).view(-1, img1.shape[-1]).mean(dim=0, keepdim=True)    
    mse = torch.mean((img1 - img2) ** 2)
    psnr = 20 * torch.log10(1.0 / torch.sqrt(mse))
    return psnr
    
    
def gaussian(window_size, sigma):
    gauss = torch.Tensor([exp(-(x - window_size // 2) ** 2 / float(2 * sigma ** 2)) for x in range(window_size)])
    return gauss / gauss.sum()

def create_window(window_size, channel):
    _1D_window = gaussian(window_size, 1.5).unsqueeze(1)
    _2D_window = _1D_window.mm(_1D_window.t()).float().unsqueeze(0).unsqueeze(0)
    window = Variable(_2D_window.expand(channel, 1, window_size, window_size).contiguous())
    return window

def ssim(img1, img2, window_size=11, size_average=True, mask=None, weight=None):
    channel = img1.size(-3)
    window = create_window(window_size, channel)
    
    if mask is not None:
        img1 = torch.where(mask, img1, torch.zeros_like(img1))
        img2 = torch.where(mask, img2, torch.zeros_like(img2))
    
    if img1.is_cuda:
        window = window.cuda(img1.get_device())

    window = window.type_as(img1)

    return _ssim(img1, img2, window, window_size, channel, size_average, weight)

def _ssim(img1, img2, window, window_size, channel, size_average=True, weight=None):
    mu1 = F.conv2d(img1, window, padding=window_size // 2, groups=channel)
    mu2 = F.conv2d(img2, window, padding=window_size // 2, groups=channel)

    mu1_sq = mu1.pow(2)
    mu2_sq = mu2.pow(2)
    mu1_mu2 = mu1 * mu2

    sigma1_sq = F.conv2d(img1 * img1, window, padding=window_size // 2, groups=channel) - mu1_sq
    sigma2_sq = F.conv2d(img2 * img2, window, padding=window_size // 2, groups=channel) - mu2_sq
    sigma12 = F.conv2d(img1 * img2, window, padding=window_size // 2, groups=channel) - mu1_mu2

    C1 = 0.01 ** 2
    C2 = 0.03 ** 2

    ssim_map = ((2 * mu1_mu2 + C1) * (2 * sigma12 + C2)) / ((mu1_sq + mu2_sq + C1) * (sigma1_sq + sigma2_sq + C2))

    if weight is not None:
        ssim_map = ssim_map * weight
        if size_average:
            return ssim_map.sum() / (weight.sum() + 1e-6)
        else:
            return ssim_map.mean(1).mean(1).mean(1)
    else:
        if size_average:
            return ssim_map.mean()
        else:
            return ssim_map.mean(1).mean(1).mean(1)

def get_ground_gs_index(render_pkg, ground_mask):
    means2D = render_pkg['means2D_bkgd'].detach().cpu().numpy()
    x, y = means2D[:, 0].astype("int"), means2D[:, 1].astype("int")
    H, W = ground_mask.shape[1], ground_mask.shape[2]
    valid_index = (x >= 0) & (x < W) & (y >= 0) & (y < H)
    ground_mask_numpy = ground_mask.squeeze(0).detach().cpu().numpy()
    valid_ground_index = valid_index & ground_mask_numpy[y.clip(0, H - 1), x.clip(0, W - 1)]
    if valid_ground_index.sum() < 2:
        return None
    return valid_ground_index

def get_faiss_index(points_bkgd, points_gd, ego_traj):
    con_points = np.concatenate([points_bkgd.points[:, :3], points_gd.points[:, :3]], axis=0).astype(np.float32)
    bkgd_nlist = int(sqrt(len(con_points)))
    d = 3
    bkgd_faiss_quantizer = faiss.IndexFlatL2(d)  
    bkgd_faiss_index = faiss.IndexIVFFlat(bkgd_faiss_quantizer, d, bkgd_nlist)
    assert not bkgd_faiss_index.is_trained
    con_points = np.ascontiguousarray(con_points, dtype=np.float32)
    bkgd_faiss_index.train(con_points)
    assert bkgd_faiss_index.is_trained
    bkgd_faiss_index_gpu = faiss.index_cpu_to_all_gpus(bkgd_faiss_index)
    bkgd_faiss_index_gpu.add(con_points)    

    ego_nlist = int(sqrt(len(ego_traj)))
    ego_faiss_quantizer = faiss.IndexFlatL2(d)  
    ego_faiss_index = faiss.IndexIVFFlat(ego_faiss_quantizer, d, ego_nlist)
    assert not ego_faiss_index.is_trained
    ego_traj = np.ascontiguousarray(ego_traj, dtype=np.float32)
    ego_faiss_index.train(ego_traj)
    assert ego_faiss_index.is_trained
    ego_faiss_index_gpu = faiss.index_cpu_to_all_gpus(ego_faiss_index)
    ego_faiss_index_gpu.add(ego_traj)        
    return bkgd_faiss_index_gpu, ego_faiss_index_gpu