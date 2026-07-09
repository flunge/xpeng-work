import torch
from math import exp
import torch.nn.functional as F
from torch.autograd import Variable

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

def psnr_metric(img1, img2, mask=None):
    if img1.dim() == 3:
        img1 = img1.unsqueeze(0)
        img2 = img2.unsqueeze(0)
    assert img1.shape == img2.shape, "Input tensors must have the same shape"

    diff = (img1 - img2) ** 2
    if mask is None:
        mse = torch.mean(diff, dim=[1, 2, 3])
    else:
        masked_diff = diff * mask
        mse = torch.sum(masked_diff, dim=[1, 2, 3]) / (torch.sum(mask, dim=[1, 2, 3]) + 1e-10)
        del masked_diff
    psnr = 20 * torch.log10(1.0 / torch.sqrt(mse + 1e-10))
    if psnr.shape[0] == 1:
        return psnr.squeeze(0)
    return psnr.mean()

