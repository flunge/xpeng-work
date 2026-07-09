import os
import re

import numpy as np
import requests
import torch
from torchvision.datasets.folder import IMG_EXTENSIONS
from torchvision.transforms import InterpolationMode
from torchvision.transforms.functional import resize
import decord
from einops import rearrange

VID_EXTENSIONS = (".mp4", ".avi", ".mov", ".mkv")



def read_frames(path):
    vr = decord.VideoReader(
        uri=path,
        height=-1,
        width=-1,
    )
    frames = vr.get_batch(range(len(vr)))
    frames = rearrange(frames, 'T H W C -> T C H W').contiguous().float() / 255.0
    return frames


def read_frames_at_fps(path, target_fps=10):
    vr = decord.VideoReader(uri=path, height=-1, width=-1)
    native_fps = vr.get_avg_fps()
    total = len(vr)
    if native_fps > 0 and abs(native_fps - target_fps) > 0.5:
        indices = np.arange(0, total, native_fps / target_fps).astype(int)
        indices = indices[indices < total]
    else:
        indices = list(range(total))
    frames = vr.get_batch(indices)  # T H W C, torch.Tensor on CPU (bridge='torch')
    frames = frames.permute(0, 3, 1, 2).float() / 255.0  # T C H W, [0,1]
    return frames


regex = re.compile(
    r"^(?:http|ftp)s?://"  # http:// or https://
    r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|"  # domain...
    r"localhost|"  # localhost...
    r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"  # ...or ip
    r"(?::\d+)?"  # optional port
    r"(?:/?|[/?]\S+)$",
    re.IGNORECASE,
)


def is_img(path):
    ext = os.path.splitext(path)[-1].lower()
    return ext in IMG_EXTENSIONS


def is_vid(path):
    ext = os.path.splitext(path)[-1].lower()
    return ext in VID_EXTENSIONS


def is_url(url):
    return re.match(regex, url) is not None


def download_url(input_path):
    output_dir = "cache"
    os.makedirs(output_dir, exist_ok=True)
    base_name = os.path.basename(input_path)
    output_path = os.path.join(output_dir, base_name)
    img_data = requests.get(input_path).content
    with open(output_path, "wb") as handler:
        handler.write(img_data)
    print(f"URL {input_path} downloaded to {output_path}")
    return output_path


def recursively_find(root_dir: str, ext: list = None, relative_path: str = None):
    all_fnames = [
        os.path.join(root, fname)
        for root, _dirs, files in os.walk(root_dir)
        for fname in files
    ]
    if relative_path is not None:
        all_fnames = [os.path.relpath(fname, relative_path) for fname in all_fnames]
    else:
        all_fnames = [os.path.abspath(fname) for fname in all_fnames]
    if ext is None:
        return all_fnames
    else:
        return [fname for fname in all_fnames if os.path.splitext(fname)[-1] in ext]


def get_crop_bbox(ori_h, ori_w, tgt_h, tgt_w):
    tgt_ar = tgt_h / tgt_w
    ori_ar = ori_h / ori_w
    if abs(ori_ar - tgt_ar) < 0.01:
        return 0, ori_h, 0, ori_w
    if ori_ar > tgt_ar:
        crop_h = int(tgt_ar * ori_w)
        y0 = (ori_h - crop_h) // 2
        y1 = y0 + crop_h
        return y0, y1, 0, ori_w
    else:
        crop_w = int(ori_h / tgt_ar)
        x0 = (ori_w - crop_w) // 2
        x1 = x0 + crop_w
        return 0, ori_h, x0, x1


def isotropic_crop_resize(frames: torch.Tensor, size: tuple, is_mask: bool = False):
    """
    frames: (T, C, H, W)
    size: (H, W)
    """
    ori_h, ori_w = frames.shape[2:]
    h, w = size
    y0, y1, x0, x1 = get_crop_bbox(ori_h, ori_w, h, w)
    cropped_frames = frames[:, :, y0:y1, x0:x1]

    # Use NEAREST interpolation for masks (no antialias), bicubic for frames
    if is_mask:
        interpolation_mode = InterpolationMode.NEAREST
        use_antialias = False
    else:
        interpolation_mode = InterpolationMode.BICUBIC
        use_antialias = True
    
    resized_frames = resize(
        cropped_frames, size, interpolation_mode, antialias=use_antialias
    )
    return resized_frames


def get_random_crop_bbox(
    ori_h, ori_w, crop_max_ratio: float, rnd_state: np.random.RandomState
):
    if crop_max_ratio >= 1:
        raise ValueError("crop_max_ratio should be smaller than 1")
    random_ratio = rnd_state.random((4,))
    h_crop_ratio = random_ratio[0] * crop_max_ratio
    w_crop_ratio = random_ratio[1] * crop_max_ratio
    new_h = round(ori_h * (1 - h_crop_ratio))
    new_w = round(ori_w * (1 - w_crop_ratio))
    y0 = round((ori_h - new_h) * random_ratio[2])
    x0 = round((ori_w - new_w) * random_ratio[3])
    return y0, y0 + new_h, x0, x0 + new_w


def random_crop(
    frames: torch.Tensor,
    crop_max_ratio: float,
    rnd_state: np.random.RandomState,
    return_crop_bbox: bool = False,
):
    """
    frames: (T, C, H, W)
    size: (H, W)
    """
    ori_h, ori_w = frames.shape[2:]
    y0, y1, x0, x1 = get_random_crop_bbox(ori_h, ori_w, crop_max_ratio, rnd_state)
    cropped_frames = frames[:, :, y0:y1, x0:x1]
    if not return_crop_bbox:
        return cropped_frames
    else:
        return cropped_frames, (y0, y1, x0, x1)


def read_txt(in_path):
    with open(in_path) as f:
        return f.read()