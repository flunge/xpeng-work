import torch
import numpy as np
import argparse
import pytorch_lightning as pl
import omegaconf
import importlib
import os

from loguru import logger 
from fvdb import GridBatch
from omegaconf import OmegaConf

def _torch_load_supports_weights_only():
    try:
        return "weights_only" in torch.load.__code__.co_varnames
    except Exception:
        return False

def _torch_load_unpickle_full(path, map_location="cpu"):
    if _torch_load_supports_weights_only():
        return torch.load(path, map_location=map_location, weights_only=False)
    return torch.load(path, map_location=map_location)

def _load_lightning_ckpt_trusted(model_cls, ckpt_path, strict=False):
    # pytorch-lightning internally calls torch.load without weights_only arg.
    # On torch>=2.6 default is True; patch it to False for trusted checkpoints.
    if not _torch_load_supports_weights_only():
        return model_cls.load_from_checkpoint(ckpt_path, strict=strict)

    orig_torch_load = torch.load
    def _patched_torch_load(*args, **kwargs):
        kwargs.setdefault("weights_only", False)
        return orig_torch_load(*args, **kwargs)

    torch.load = _patched_torch_load
    try:
        return model_cls.load_from_checkpoint(ckpt_path, strict=strict)
    finally:
        torch.load = orig_torch_load

def batch2device(batch, device):
    """Send a batch to GPU"""
    if batch is None:
        return None
    for k, v in batch.items():
        if isinstance(v, list) and isinstance(v[0], torch.Tensor):
            batch[k] = [v[i].to(device) for i in range(len(v))]
        elif isinstance(v, GridBatch):
            batch[k] = v.to(device)
        elif isinstance(v, dict):
            batch[k] = batch2device(v, device)
    return batch

def get_default_parser():
    default_parser = argparse.ArgumentParser(add_help=False)
    default_parser = pl.Trainer.add_argparse_args(default_parser)
    return default_parser

def create_model_from_args(ckpt_path, model_name, parser, ckpt_name=None, hparam_update=None):
    args = parser.parse_args()
    if hasattr(args, 'nosync'):
        os.environ['NO_SYNC'] = '1'

    print("------ckpt_path------ ", ckpt_path)
    net_module = importlib.import_module("scube.models." + model_name).Model
    net_model = _load_lightning_ckpt_trusted(net_module, ckpt_path, strict=False)

    # get net_state_dict
    net_state_dict = _torch_load_unpickle_full(ckpt_path, map_location="cpu")
    # get global_step
    global_step = net_state_dict["global_step"]

    return net_model.eval(), global_step

def merge_images_in_folder(image_folder):
    """
    image folder: str,
        several images in the folder, it's name follows
            {frame_id}_{view}.jpg

    We should open all the images as tensors, [N, C, H, W]
    downsample the resolution to 1/4, 
    save in one image use torchvision.utils.save_image, with nrow=num_view
    """
    from PIL import Image
    import torch.nn.functional as F
    import torchvision

    image_files = os.listdir(image_folder)
    image_files = [x for x in image_files if x.endswith(".jpg")] + [x for x in image_files if x.endswith(".png")]
    image_files.sort()

    num_view = len(set([x.split("_")[1] for x in image_files]))
    num_frame = len(image_files) // num_view

    if num_view == 3:
        reorder = [1,0,2]
    elif num_view == 5:
        reorder = [3,1,0,2,4]

    images = []
    for image_file in image_files:
        image = Image.open(os.path.join(image_folder, image_file))
        image = torch.tensor(np.array(image)).permute(2, 0, 1).float() / 255 # [C, H, W]
        images.append(image)

    images = torch.stack(images, dim=0)
    images = F.interpolate(images, scale_factor=1/4, mode='bilinear', antialias=True).clamp(0,1) # [N_frame*N_view, C, H, W]

    # reorder the images
    images = torch.cat([x[reorder] for x in torch.chunk(images, num_frame, dim=0)], dim=0)
    
    torchvision.utils.save_image(images, os.path.join(image_folder, "merged.jpg"), nrow=num_view)

def mask_image_patches(images: torch.Tensor, P: int, p_mask: float) -> torch.Tensor:
    """
    Masks patches of images with a specified probability.

    Parameters:
        images (torch.Tensor): Input tensor of shape [B, N, H, W, 1].
        P (int): Size of each patch.
        p_mask (float): Probability of masking each patch.

    Returns:
        torch.Tensor: Masked images of the same shape as input.
    """
    B, N, H, W, _ = images.shape
    
    # Calculate number of patches in height and width
    num_patches_h = H // P
    num_patches_w = W // P

    # Create a random mask for patches
    # Shape [B, N, num_patches_h * num_patches_w]
    random_mask = (torch.rand(B, N, num_patches_h, num_patches_w) < p_mask)
    random_mask = torch.repeat_interleave(random_mask, P, dim=2)
    random_mask = torch.repeat_interleave(random_mask, P, dim=3)
    random_mask = random_mask.unsqueeze(-1)
    
    return images * random_mask.to(images.device)