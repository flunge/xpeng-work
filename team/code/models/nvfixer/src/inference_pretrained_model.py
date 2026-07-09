# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sys
import warnings
from pix2pix_turbo_nocond_cosmos_base_faster_tokenizer import Pix2Pix_Turbo
from bisect import bisect_left

from tqdm import tqdm
import time
import yaml

import torch
import argparse
import transformer_engine as te #important
from glob import glob
import os
import argparse
import numpy as np
from PIL import Image
import torch
from torchvision import transforms
import torchvision.transforms.functional as F
from pathlib import Path

from natsort import natsorted

import imageio

# Suppress warnings
warnings.filterwarnings("ignore")
import logging
logging.getLogger("torch").setLevel(logging.ERROR)
logging.getLogger("torchvision").setLevel(logging.ERROR)

def save_folder2video(save_dir, remove_key = 0):
    if remove_key==0:
        video_file = os.path.join(save_dir,  save_dir.split('/')[-1] + "_video.mp4")
    else:
        video_file = os.path.join(save_dir,  "video_removekey_" + str(remove_key) + ".mp4")
    im_files = natsorted(glob(os.path.join(save_dir, "*.png")) + glob(os.path.join(save_dir, "*.jpg")))
    # Loads all images at once - can run out of memory if too many frames
    ims: list[np.ndarray] = [imageio.v2.imread(f) for f in im_files]

    # chop image if dimension not divisible by 2 to fix the ffmpeg error
    for i in range(len(ims)):
        if ims[i].shape[0] % 2 == 1:
            ims[i] = ims[i][:-1, :, :]
        if ims[i].shape[1] % 2 == 1:
            ims[i] = ims[i][:, :-1, :]

    # Results in an Array is not the same as ArrayLike annotation error, so we suppress it
    if remove_key!=0:
        ims = [ims[i] for i in range(len(ims)) if i % remove_key != 0]
        
    
    imageio.v2.mimwrite(video_file, ims, fps=30, macro_block_size=1)  # type: ignore
    imageio.v2.mimwrite(video_file.replace("video.mp4", "video_10fps.mp4"), 
                        ims[::3], fps=10, macro_block_size=1)  # type: ignore
    imageio.v2.mimwrite(video_file.replace("video.mp4", "video_15fps.mp4"), 
                        ims[::2], fps=15, macro_block_size=1)  # type: ignore


def encode_step(vae, batch_size: int, h: int, w: int, dtype: torch.dtype, device: torch.device):
    x = torch.randn(batch_size, 3, 1, h, w, dtype=dtype, device=device)
    with torch.autocast(device_type="cuda", dtype=dtype, enabled=True):
        #print('x.shape', x.shape)
        latent = vae.encode(x)
        

def diffuse_step(model, condition, sigma_B_T, batch_size: int, c: int, h: int, w: int, dtype: torch.dtype, device: torch.device):
    compression = 8
    x = torch.randn(batch_size, 16, 1, 
                    h // compression, w // compression,
                    dtype=dtype, device=device)
    
    
    with torch.autocast(device_type="cuda", dtype=dtype, enabled=True):
        output = model.denoise(xt_B_C_T_H_W = x, 
                               sigma = sigma_B_T,
                               condition = condition).x0


def decode_step(vae, batch_size: int, h: int, w: int, dtype: torch.dtype, device: torch.device):
    compression = 8
    latent = torch.randn(batch_size, 16, 1, h // compression, w // compression, dtype=dtype, device=device)
    with torch.autocast(device_type="cuda", dtype=dtype, enabled=True):
        y = vae.decode(latent)


def model_inference(model, batch_size: int, h: int, w: int, dtype: torch.dtype, device: torch.device,
                    x = None, ref = None):
    if x is None:
        x = torch.randn(batch_size, 3,  h, w, dtype=dtype, device=device)
    if ref is None and x is not None:
        ref = None
        
    with torch.autocast(device_type="cuda", dtype=dtype, enabled=True):
        output = model(x, ref=ref)
        return output


def warmup_model(model: torch.nn.Module, batch_size: int, h: int, w: int, 
                 dtype: torch.dtype, device: torch.device, n: int = 10) -> None:
    """Warmup the model with dummy inference runs.
    
    Args:
        model: The compiled model to warmup
        batch_size: Batch size for warmup
        h: Height dimension
        w: Width dimension  
        dtype: Data type
        device: Device to run on
        n: Number of warmup iterations (default: 10)
    """
    print(f"Warming up model with {n} iterations...")
    for i in tqdm(range(n), desc="Warmup", leave=False):
        model_inference(model, batch_size, h, w, dtype, device)


def speed_measure(
    model_path: str,
    timestep: int,
    vae_skip_connection: bool,
    batch_size: int,
    h: int,
    w: int,
    dtype: torch.dtype,
    device: torch.device,
    warmup_iters: int = 50,
    test_iters: int = 50
) -> float:
    """Measure inference speed by loading model and running benchmarks.
    
    Args:
        model_path: Path to model checkpoint
        timestep: Diffusion timestep
        vae_skip_connection: Whether to use VAE skip connections
        batch_size: Batch size for testing
        h: Height dimension
        w: Width dimension
        dtype: Data type
        device: Device to run on
        warmup_iters: Number of warmup iterations
        test_iters: Number of test iterations
        
    Returns:
        Average latency per sample in seconds
    """
    print("\n" + "=" * 70)
    print("⚡ SPEED MEASUREMENT")
    print("=" * 70)
    
    # Load and compile model
    print("Loading model for speed test...")
    model = load_and_compile_model(
        model_path=model_path,
        timestep=timestep,
        vae_skip_connection=vae_skip_connection,
        batch_size=batch_size,
        device=device,
        dtype=dtype,
        compile=True
    )
    
    # Warmup
    warmup_model(model, batch_size, h, w, dtype, device, n=warmup_iters)
    
    # Speed test
    print(f"Running speed test with {test_iters} iterations...")
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    
    with torch.no_grad():
        start_time = time.time()
    
        for i in tqdm(range(test_iters), desc="Speed test", leave=False):
            model_inference(model, batch_size, h, w, dtype, device)
    
        torch.cuda.synchronize()
        end_time = time.time()
    
    latency = (end_time - start_time) / test_iters / batch_size
    
    print()
    print("=" * 70)
    print("🚀 SPEED TEST RESULTS")
    print("=" * 70)
    print(f"  Batch Size:        {batch_size}")
    print(f"  Warmup Iterations: {warmup_iters}")
    print(f"  Test Iterations:   {test_iters}")
    print(f"  Latency:           {latency:.4f} s/sample")
    print(f"  Throughput:        {1/latency:.2f} samples/s")
    print("=" * 70)
    print()
    
    return latency


def get_resolution_size(resolution: int) -> tuple[int, int]:
    """Map resolution to (width, height) size tuple."""
    resolution_map = {
        960: (960, 544),
        1360: (1360, 768),
        704: (704, 384),
        512: (512, 288),
        256: (256, 144),
        1024: (1024, 576)
    }
    assert resolution in resolution_map, f"Resolution {resolution} not supported. Choose from {list(resolution_map.keys())}"
    return resolution_map[resolution]


def preprocess_image(img: Image.Image, device: torch.device, dtype: torch.dtype = torch.bfloat16) -> torch.Tensor:
    """Convert PIL image to normalized tensor."""
    c_t = transforms.ToTensor()(img)    
    c_t = transforms.Normalize([0.5], [0.5])(c_t).unsqueeze(0)
    return c_t.to(device=device, dtype=dtype)


def postprocess_output(output_tensor: torch.Tensor, target_size: tuple[int, int]) -> Image.Image:
    """Convert model output tensor to PIL image."""
    output_image = output_tensor.float()
    output_image = output_image[0].cpu() * 0.5 + 0.5
    output_image = torch.clamp(output_image, 0.0, 1.0)
    output_pil = transforms.ToPILImage()(output_image)
    output_pil = output_pil.resize(target_size, Image.BILINEAR)
    return output_pil


def load_and_compile_model(
    model_path: str, 
    timestep: int, 
    vae_skip_connection: bool, 
    use_reference_image: bool = False,
    use_ref_cross_attn: bool = False,
    use_ref_detail_adapter: bool = False,
    ref_token_count: int = 32,
    batch_size: int = 1,
    device: torch.device = None,
    dtype: torch.dtype = torch.bfloat16,
    compile: bool = True
) -> torch.nn.Module:
    """Initialize and optionally compile the model."""
    # If a checkpoint directory is given, resolve to the actual weights file inside it
    if os.path.isdir(model_path):
        candidate = os.path.join(model_path, 'model.pkl')
        if not os.path.exists(candidate):
            raise FileNotFoundError(
                f"model_path is a directory but no model.pkl found inside: {model_path}"
            )
        print(f"loading from {model_path}")
        model_path = candidate

    model = Pix2Pix_Turbo(
        pretrained_path=model_path, 
        timestep=timestep, 
        vae_skip_connection=vae_skip_connection, 
        batch_size=batch_size,
        use_reference_image=use_reference_image,
        use_ref_cross_attn=use_ref_cross_attn,
        use_ref_detail_adapter=use_ref_detail_adapter,
        ref_token_count=ref_token_count,
    ).to(device=device, dtype=dtype)
    
    if compile:
        model = torch.compile(model)
    
    return model


def process_single_image(
    model: torch.nn.Module,
    image_path: str,
    ref_image_path: str | None,
    resolution: int,
    batch_size: int,
    h: int,
    w: int,
    dtype: torch.dtype,
    device: torch.device
) -> tuple[Image.Image, str]:
    """Process a single image through the model.
    
    Returns:
        tuple: (output_pil_image, basename)
    """
    size = get_resolution_size(resolution)
    
    input_image = Image.open(image_path).convert('RGB')
    original_shape = input_image.size
    input_image = input_image.resize(size, Image.BILINEAR)
    ref_tensor = None
    if ref_image_path is not None and os.path.exists(ref_image_path):
        ref_image = Image.open(ref_image_path).convert('RGB')
        ref_image = ref_image.resize(size, Image.BILINEAR)
        ref_tensor = preprocess_image(ref_image, device, dtype)
    
    bname = os.path.basename(image_path)
    
    with torch.no_grad():
        c_t = preprocess_image(input_image, device, dtype)
        output_tensor = model_inference(model, batch_size, h, w, dtype, device, x=c_t, ref=ref_tensor)
        output_pil = postprocess_output(output_tensor, original_shape)
    
    return output_pil, bname


def get_image_paths(input_dir: str, max_frames: int = None, skip_frames: int = 1) -> list[str]:
    """Get sorted list of image paths from directory."""
    all_img_paths = glob(input_dir + '/*.png') + glob(input_dir + '/*.jpg') + glob(input_dir + '/*.jpeg')
    all_img_paths.sort()
    
    if max_frames is None:
        max_frames = len(all_img_paths)
    
    return all_img_paths[:max_frames][::skip_frames]


def _parse_timestamp_from_path(image_path: str) -> int | None:
    """Parse integer timestamp from image filename stem."""
    stem = Path(image_path).stem
    try:
        return int(stem)
    except ValueError:
        return None


def _delta_to_seconds(delta_raw: int, reference_ts: int) -> float:
    """Convert raw timestamp delta to seconds based on timestamp magnitude."""
    abs_ref = abs(reference_ts)
    if abs_ref >= 10**18:
        return delta_raw / 1e9
    if abs_ref >= 10**15:
        return delta_raw / 1e6
    if abs_ref >= 10**12:
        return delta_raw / 1e3
    return float(delta_raw)


def build_ref_timestamp_index(ref_folder: str) -> tuple[list[int], list[str]]:
    """Build sorted timestamp index for reference images in a folder."""
    ref_paths = glob(os.path.join(ref_folder, '*.png')) + glob(os.path.join(ref_folder, '*.jpg')) + glob(os.path.join(ref_folder, '*.jpeg'))
    pairs: list[tuple[int, str]] = []
    for p in ref_paths:
        ts = _parse_timestamp_from_path(p)
        if ts is not None:
            pairs.append((ts, p))
    pairs.sort(key=lambda x: x[0])
    if not pairs:
        return [], []
    ts_list = [x[0] for x in pairs]
    path_list = [x[1] for x in pairs]
    return ts_list, path_list


def find_nearest_ref_image(
    input_image_path: str,
    ref_timestamps: list[int],
    ref_paths: list[str],
) -> tuple[str | None, float | None]:
    """Find nearest timestamp ref image for one input image.

    Returns:
        (ref_image_path, abs_delta_seconds)
    """
    if not ref_timestamps:
        return None, None
    input_ts = _parse_timestamp_from_path(input_image_path)
    if input_ts is None:
        return None, None

    idx = bisect_left(ref_timestamps, input_ts)
    candidates: list[int] = []
    if idx < len(ref_timestamps):
        candidates.append(idx)
    if idx > 0:
        candidates.append(idx - 1)
    if not candidates:
        return None, None

    best_idx = min(candidates, key=lambda i: abs(ref_timestamps[i] - input_ts))
    delta_raw = abs(ref_timestamps[best_idx] - input_ts)
    delta_s = _delta_to_seconds(delta_raw, max(abs(input_ts), abs(ref_timestamps[best_idx])))
    return ref_paths[best_idx], delta_s


def get_subfolders(input_dir: str, folder_pattern: str = None) -> list[str]:
    """获取输入目录下的所有子文件夹
    
    Args:
        input_dir: 输入目录路径
        folder_pattern: 文件夹名称模式，如 "cam*" 只处理以 cam 开头的文件夹
        
    Returns:
        子文件夹路径列表
    """
    input_path = Path(input_dir)
    
    if not input_path.exists():
        raise ValueError(f"输入目录不存在: {input_dir}")
    
    # 获取所有子文件夹
    if folder_pattern:
        subfolders = list(input_path.glob(folder_pattern))
    else:
        subfolders = [f for f in input_path.iterdir() if f.is_dir()]
    
    # 过滤掉没有图片的文件夹
    valid_subfolders = []
    for folder in subfolders:
        img_files = list(folder.glob('*.png')) + list(folder.glob('*.jpg')) + list(folder.glob('*.jpeg'))
        if img_files:
            valid_subfolders.append(folder)
    
    # 按名称排序
    valid_subfolders.sort(key=lambda x: x.name)
    
    return [str(f) for f in valid_subfolders]


def inference(
    model_path: str,
    timestep: int,
    vae_skip_connection: bool,
    input_dir: str,
    output_dir: str,
    resolution: int,
    batch_size: int,
    h: int,
    w: int,
    dtype: torch.dtype,
    device: torch.device,
    max_frames: int = None,
    skip_frames: int = 1,
    save_video: bool = False,
    warmup_iters: int = 10
    ,
    ref_dir: str = None,
    use_reference_image: bool = False,
    use_ref_cross_attn: bool = False,
    use_ref_detail_adapter: bool = False,
    ref_token_count: int = 32,
):
    """Run inference on a directory of images.
    
    Args:
        model_path: Path to model checkpoint
        timestep: Diffusion timestep
        vae_skip_connection: Whether to use VAE skip connections
        input_dir: Directory containing input images
        output_dir: Directory to save outputs
        resolution: Target resolution
        batch_size: Batch size for inference
        h: Height dimension
        w: Width dimension
        dtype: Data type
        device: Device to run on
        max_frames: Maximum number of frames to process
        skip_frames: Frame skip interval
        save_video: Whether to save output as video
        warmup_iters: Number of warmup iterations
    """
    print("\n" + "=" * 70)
    print("🎨 INFERENCE MODE")
    print("=" * 70)
    
    # Load and compile model
    print("Loading model for inference...")
    model = load_and_compile_model(
        model_path=model_path,
        timestep=timestep,
        vae_skip_connection=vae_skip_connection,
        use_reference_image=use_reference_image,
        use_ref_cross_attn=use_ref_cross_attn,
        use_ref_detail_adapter=use_ref_detail_adapter,
        ref_token_count=ref_token_count,
        batch_size=batch_size,
        device=device,
        dtype=dtype,
        compile=True
    )
    
    # Warmup the model
    warmup_model(model, batch_size, h, w, dtype, device, n=warmup_iters)
    
    # Get image paths
    image_paths = get_image_paths(input_dir, max_frames=max_frames, skip_frames=skip_frames)
    
    print(f"\nProcessing {len(image_paths)} images...")
    print(f"Batch size: {batch_size}, Resolution: {resolution}\n")
    
    # Process images
    os.makedirs(output_dir, exist_ok=True)

    ref_timestamps: list[int] = []
    ref_paths: list[str] = []
    if ref_dir is not None:
        ref_timestamps, ref_paths = build_ref_timestamp_index(ref_dir)
        print(f"Reference images indexed: {len(ref_paths)} from {ref_dir}")
    
    for img_path in tqdm(image_paths, desc="Processing images"):
        ref_image_path = None
        if ref_dir is not None:
            ref_image_path, delta_s = find_nearest_ref_image(img_path, ref_timestamps, ref_paths)
            if ref_image_path is not None and delta_s is not None:
                print(
                    f"[RefMatch] input={Path(img_path).name} ref={Path(ref_image_path).name} "
                    f"dt={delta_s:.6f}s"
                )
        output_pil, bname = process_single_image(
            model, img_path, ref_image_path, resolution, batch_size, h, w, dtype, device
        )
        
        sv_path = os.path.join(output_dir, bname)
        output_pil.save(sv_path)
    
    print(f'\n✓ Processed {len(image_paths)} images -> {output_dir}')
    
    if save_video:
        save_folder2video(output_dir)
        print(f'✓ Video saved to {output_dir}')


def inference_batch_folders(
    model_path: str,
    timestep: int,
    vae_skip_connection: bool,
    input_dir: str,
    output_dir: str,
    resolution: int,
    batch_size: int,
    h: int,
    w: int,
    dtype: torch.dtype,
    device: torch.device,
    max_frames: int = None,
    skip_frames: int = 1,
    save_video: bool = False,
    warmup_iters: int = 10,
    folder_pattern: str = None,
    ref_dir: str = None,
    use_reference_image: bool = False,
    use_ref_cross_attn: bool = False,
    use_ref_detail_adapter: bool = False,
    ref_token_count: int = 32,
):
    """批量处理输入目录下所有子文件夹中的图片
    
    Args:
        model_path: 模型检查点路径
        timestep: 扩散时间步
        vae_skip_connection: 是否使用VAE跳跃连接
        input_dir: 包含多个子文件夹的输入目录
        output_dir: 输出根目录
        resolution: 目标分辨率
        batch_size: 批处理大小
        h: 高度维度
        w: 宽度维度
        dtype: 数据类型
        device: 运行设备
        max_frames: 每个文件夹最大处理帧数
        skip_frames: 帧跳过间隔
        save_video: 是否保存为视频
        warmup_iters: 预热迭代次数
        folder_pattern: 文件夹名称模式 (如 "cam*")
    """
    print("\n" + "=" * 70)
    print("🎨 BATCH FOLDER INFERENCE MODE")
    print("=" * 70)
    
    # 获取所有子文件夹
    subfolders = get_subfolders(input_dir, folder_pattern)
    
    if not subfolders:
        print(f"警告: 在 {input_dir} 中没有找到包含图片的子文件夹")
        return
    
    print(f"找到 {len(subfolders)} 个子文件夹:")
    for folder in subfolders:
        folder_name = Path(folder).name
        img_count = len(get_image_paths(folder))
        print(f"  - {folder_name}: {img_count} 张图片")
    
    # 加载并编译模型 (只加载一次)
    print("\nLoading model for inference...")
    model = load_and_compile_model(
        model_path=model_path,
        timestep=timestep,
        vae_skip_connection=vae_skip_connection,
        use_reference_image=use_reference_image,
        use_ref_cross_attn=use_ref_cross_attn,
        use_ref_detail_adapter=use_ref_detail_adapter,
        ref_token_count=ref_token_count,
        batch_size=batch_size,
        device=device,
        dtype=dtype,
        compile=True
    )
    
    # 预热模型 (只预热一次)
    warmup_model(model, batch_size, h, w, dtype, device, n=warmup_iters)
    
    # 创建输出根目录
    os.makedirs(output_dir, exist_ok=True)
    
    # 处理每个子文件夹
    total_images = 0
    for folder_idx, subfolder in enumerate(subfolders):
        folder_name = Path(subfolder).name
        sub_output_dir = os.path.join(output_dir, folder_name)
        ref_timestamps: list[int] = []
        ref_paths: list[str] = []
        if ref_dir is not None:
            ref_subfolder = os.path.join(ref_dir, folder_name)
            ref_timestamps, ref_paths = build_ref_timestamp_index(ref_subfolder)
            print(f"  参考图索引: {len(ref_paths)} 张 ({ref_subfolder})")
        
        print(f"\n{'='*50}")
        print(f"[{folder_idx + 1}/{len(subfolders)}] Processing folder: {folder_name}")
        print(f"{'='*50}")
        
        # 获取图片路径
        image_paths = get_image_paths(subfolder, max_frames=max_frames, skip_frames=skip_frames)
        
        if not image_paths:
            print(f"  跳过: 没有找到图片")
            continue
        
        print(f"  输入: {subfolder}")
        print(f"  输出: {sub_output_dir}")
        print(f"  图片数量: {len(image_paths)}")
        
        # 创建输出子目录
        os.makedirs(sub_output_dir, exist_ok=True)
        
        # 处理图片
        for img_path in tqdm(image_paths, desc=f"Processing {folder_name}"):
            ref_image_path = None
            if ref_dir is not None:
                ref_image_path, delta_s = find_nearest_ref_image(img_path, ref_timestamps, ref_paths)
                if ref_image_path is not None and delta_s is not None:
                    print(
                        f"[RefMatch] input={Path(img_path).name} ref={Path(ref_image_path).name} "
                        f"dt={delta_s:.6f}s"
                    )
            output_pil, bname = process_single_image(
                model, img_path, ref_image_path, resolution, batch_size, h, w, dtype, device
            )
            
            sv_path = os.path.join(sub_output_dir, bname)
            output_pil.save(sv_path)
        
        total_images += len(image_paths)
        print(f"  ✓ Completed: {len(image_paths)} images -> {sub_output_dir}")
        
        # 保存视频
        if save_video:
            save_folder2video(sub_output_dir)
            print(f"  ✓ Video saved to {sub_output_dir}")
    
    print("\n" + "=" * 70)
    print("🎉 BATCH PROCESSING COMPLETE")
    print("=" * 70)
    print(f"  Total folders processed: {len(subfolders)}")
    print(f"  Total images processed:  {total_images}")
    print(f"  Output directory:        {output_dir}")
    print("=" * 70)


def load_model_config_from_ckpt(ckpt_path: str) -> dict:
    """Read train_config.yaml from checkpoint directory and return model architecture params.

    Returns a dict with keys: use_reference_image, use_ref_cross_attn,
    use_ref_detail_adapter, ref_token_count, timestep, image_height, image_width.
    Returns an empty dict if the config file is not found.
    """
    config_path = os.path.join(ckpt_path, 'train_config.yaml')
    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"train_config.yaml not found in checkpoint directory: {config_path}"
        )

    with open(config_path, 'r') as f:
        raw = yaml.safe_load(f)

    keys = [
        'use_reference_image', 'use_ref_cross_attn', 'use_ref_detail_adapter',
        'ref_token_count', 'timestep', 'image_height', 'image_width',
    ]
    return {k: raw[k] for k in keys if k in raw}


def main():
    parser = argparse.ArgumentParser(description='Run inference on an image.')
    
    # Model arguments
    parser.add_argument('--model', type=str, default=None, help='path to a model checkpoint directory (train_config.yaml must exist inside it)')
    parser.add_argument('--vae_skip_connection', action='store_true', help='enable VAE skip connection (not read from config)')
    
    # Inference arguments
    parser.add_argument('--input', type=str, required=True, help='input directory (single folder or parent folder containing subfolders)')
    parser.add_argument('--ref_dir', type=str, default=None, help='optional reference directory with matching filenames')
    parser.add_argument('--resolution', type=int, default=1024)
    parser.add_argument('--output', type=str, default='output', help='output_dir')
    parser.add_argument('--save_video', action='store_true')
    parser.add_argument('--max_frames', type=int, default=3000000, help='max_frames per folder')
    parser.add_argument('--skip_frames', type=int, default=1, help='skip_frames')     
    parser.add_argument('--batch_size', type=int, default=8, help='batch_size')
    
    # Batch folder mode arguments
    parser.add_argument('--batch_folders', action='store_true', 
                        help='Process all subfolders in the input directory')
    parser.add_argument('--folder_pattern', type=str, default=None,
                        help='Pattern for subfolder names (e.g., "cam*" to only process cam0, cam2, etc.)')
    
    # Speed test arguments
    parser.add_argument('--test-speed', action='store_true', help='Run speed benchmark before inference')
    parser.add_argument('--speed-test-iters', type=int, default=50, help='Number of iterations for speed test')
    parser.add_argument('--warmup-iters', type=int, default=50, help='Number of warmup iterations')
    
    torch.set_grad_enabled(False)
    device = torch.device("cuda")
    dtype = torch.bfloat16
    
    print('dtype', dtype)
    
    args = parser.parse_args()

    h: int = 1024
    w: int = 576

    # Load model architecture config from checkpoint's train_config.yaml (mandatory)
    if args.model is None:
        raise ValueError("--model is required")
    ckpt_cfg = load_model_config_from_ckpt(args.model)
    print("\n[Config] Loaded model config from train_config.yaml:")
    for key in ('use_reference_image', 'use_ref_cross_attn',
                'use_ref_detail_adapter', 'ref_token_count', 'timestep'):
        if key in ckpt_cfg:
            setattr(args, key, ckpt_cfg[key])
            print(f"  {key} = {ckpt_cfg[key]}")
        else:
            raise KeyError(f"Missing required key '{key}' in train_config.yaml")
    if 'image_height' in ckpt_cfg:
        h = ckpt_cfg['image_height']
        print(f"  image_height (h) = {h}")
    if 'image_width' in ckpt_cfg:
        w = ckpt_cfg['image_width']
        print(f"  image_width  (w) = {w}")
    print()

    # Optional speed test (uses args.batch_size)
    if args.test_speed:
        speed_measure(
            model_path=args.model,
            timestep=args.timestep,
            vae_skip_connection=args.vae_skip_connection,
            use_reference_image=args.use_reference_image,
            use_ref_cross_attn=args.use_ref_cross_attn,
            use_ref_detail_adapter=args.use_ref_detail_adapter,
            ref_token_count=args.ref_token_count,
            batch_size=args.batch_size,
            h=h,
            w=w,
            dtype=dtype,
            device=device,
            warmup_iters=args.warmup_iters,
            test_iters=args.speed_test_iters
        )
    # Run inference
    else:
        if args.batch_folders:
            # 批量处理子文件夹模式
            inference_batch_folders(
                model_path=args.model,
                timestep=args.timestep,
                vae_skip_connection=args.vae_skip_connection,
                use_reference_image=args.use_reference_image,
                use_ref_cross_attn=args.use_ref_cross_attn,
                use_ref_detail_adapter=args.use_ref_detail_adapter,
                ref_token_count=args.ref_token_count,
                input_dir=args.input,
                output_dir=args.output,
                resolution=args.resolution,
                batch_size=1,
                h=h,
                w=w,
                dtype=dtype,
                device=device,
                max_frames=args.max_frames,
                skip_frames=args.skip_frames,
                save_video=args.save_video,
                warmup_iters=args.warmup_iters,
                folder_pattern=args.folder_pattern,
                ref_dir=args.ref_dir
            )
        else:
            # 单文件夹模式 (原有逻辑)
            inference(
                model_path=args.model,
                timestep=args.timestep,
                vae_skip_connection=args.vae_skip_connection,
                use_reference_image=args.use_reference_image,
                use_ref_cross_attn=args.use_ref_cross_attn,
                use_ref_detail_adapter=args.use_ref_detail_adapter,
                ref_token_count=args.ref_token_count,
                input_dir=args.input,
                output_dir=args.output,
                resolution=args.resolution,
                batch_size=1,
                h=h,
                w=w,
                dtype=dtype,
                device=device,
                max_frames=args.max_frames,
                skip_frames=args.skip_frames,
                save_video=args.save_video,
                warmup_iters=args.warmup_iters,
                ref_dir=args.ref_dir
            )


if __name__ == "__main__":
    main()