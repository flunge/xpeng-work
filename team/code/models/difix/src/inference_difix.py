import os
import imageio
import argparse
import numpy as np
import torch
import json
import time
from PIL import Image
from glob import glob
from tqdm import tqdm
from model import Difix, load_ckpt_from_state_dict
from pipeline_difix import DifixPipeline
from utils_difix import load_mask, load_config, calculate_psnr


if __name__ == "__main__":
    # Argument parser
    parser = argparse.ArgumentParser()
    parser.add_argument('--data_path', type=str, default='data', help='Path to the data')
    parser.add_argument('--ckpt_path', type=str, default='', help='Path to the checkpoint')
    parser.add_argument('--camera_name', type=str, default='cam0', help='Camera name')
    parser.add_argument('--output_dir', type=str, default='output', help='Directory to save the output')
    parser.add_argument('--seed', type=int, default=42, help='Random seed to be used')
    parser.add_argument('--timestep', type=int, default=199, help='Diffusion timestep')
    parser.add_argument('--save_video', action='store_true', default=True, help='If the input is a video')
    parser.add_argument('--save_images', action='store_true', default=False, help='If save the output video')
    args = parser.parse_args()

    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)

    # load the config
    if len(args.ckpt_path) == 0:
        config = {
            "image_height": 576,
            "image_width": 1024,
            "lora_rank_vae": 4,
            "timestep": 199,
        }
    else:
        config = load_config(args.ckpt_path)

    # Initialize the model
    pipe = DifixPipeline.from_pretrained(
        "nvidia/difix_ref",
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
        local_files_only=True,
    )
    model = Difix(
        pipe=pipe,
        timestep=config["timestep"],
        lora_rank_vae=config["lora_rank_vae"],
    )
    if len(args.ckpt_path) > 0:
        print(f"Loading checkpoint from {args.ckpt_path}")
        model, _, _ = load_ckpt_from_state_dict(model, os.path.join(args.ckpt_path, "model.pkl"))
    model.to("cuda", dtype=torch.bfloat16)
    model.set_eval()
    
    # read custom_data.json
    custom_data_json = args.data_path
    if os.path.exists(custom_data_json):
        with open(custom_data_json, "r") as f:
            custom_data = json.load(f)
    else:
        raise ValueError(f"dataset json file {args.data_path} not found")
    
    # Load input images
    input_images_path = []
    gt_images_path = []
    ref_images_path = []
    prompt = []
    for name, data in custom_data['train'].items():
        if args.camera_name.lower() in name.lower():
            input_images_path.append(data['image'])
            gt_images_path.append(data['target_image'])
            if 'ref_image' in data:
                ref_images_path.append(data['ref_image'])
            prompt.append(data['prompt'])
    print(f"input_images number: {len(input_images_path)}")
    
    # 加载mask（参考dataset.py），用于PSNR计算时排除mask为False的区域
    image_size = (config["image_height"], config["image_width"])
    mask = None
    if len(gt_images_path) > 0:
        mask = load_mask(custom_data['train'], [args.camera_name], image_size=image_size)
        mask = list(mask.values())[0][args.camera_name]
    
    # Process images
    input_images = []
    output_images = []
    gt_images = []
    psnr_results = []
    timing = []
    
    for i, input_image_path in enumerate(tqdm(input_images_path, desc="Processing images")):
        gt_img = Image.open(gt_images_path[i]).convert('RGB')
        gt_images.append(gt_img)
        input_image = Image.open(input_image_path).convert('RGB')
        input_images.append(input_image)
        ref_image = Image.open(ref_images_path[i]).convert('RGB') if len(ref_images_path) > 0 else None
        t1 = time.time()
        output_image = model.sample(
            input_image,
            height=config["image_height"],
            width=config["image_width"],
            ref_image=ref_image,
            prompt=prompt[i]
        )
        t2 = time.time()
        timing.append(t2 - t1)
        output_images.append(output_image)
        
        psnr_value = calculate_psnr(output_image, gt_img, mask=mask)
        psnr_value_input = calculate_psnr(input_image, gt_img, mask=mask)
        reference_type = "ground_truth"
        reference_path = gt_images_path[i]
        
        increased_percentage = (psnr_value - psnr_value_input) / psnr_value_input * 100 if psnr_value_input and not np.isnan(psnr_value_input) else 0.0
        
        psnr_results.append({
            "image_index": i,
            "input_image": input_image_path,
            "output_image": os.path.join(args.output_dir, os.path.basename(input_image_path)),
            "reference_type": reference_type,
            "reference_path": reference_path,
            "psnr": float(psnr_value),
            "psnr_input": float(psnr_value_input),
            "increased_percentage": float(increased_percentage)
        })
        
        print(f"  Image {i+1}/{len(input_images_path)}: PSNR = {psnr_value:.4f} dB "
                f"(input: {psnr_value_input:.4f}) "
                f"Increased percentage: {increased_percentage:.2f}%")
    
    print(f"Average inference time: {np.mean(timing):.4f} seconds")

    # Save outputs
    if args.save_video:
        # Save as video
        video_path = os.path.join(args.output_dir, "output.mp4")
        writer = imageio.get_writer(video_path, fps=6)
        for output_image in tqdm(output_images, desc="Saving video"):
            writer.append_data(np.array(output_image))
        writer.close()
        # Save input images as video
        input_video_path = os.path.join(args.output_dir, "input.mp4")
        writer = imageio.get_writer(input_video_path, fps=6)
        for input_image in tqdm(input_images, desc="Saving input video"):
            writer.append_data(np.array(input_image))
        writer.close()
        # Save gt images as video
        if len(gt_images) > 0:
            gt_video_path = os.path.join(args.output_dir, "gt.mp4")
            writer = imageio.get_writer(gt_video_path, fps=6)
            for gt_image in tqdm(gt_images, desc="Saving gt video"):
                writer.append_data(np.array(gt_image))
            writer.close()
    
    if args.save_images:
        # Save as individual images
        for i, output_image in enumerate(tqdm(output_images, desc="Saving images")):
            output_image.save(os.path.join(args.output_dir, os.path.basename(input_images_path[i])))
    
    # Generate and save PSNR report
    if len(psnr_results) > 0:
        psnr_values = [r["psnr"] for r in psnr_results]
        psnr_values_input = [r["psnr_input"] for r in psnr_results]
        psnr_mean = np.mean(psnr_values)
        psnr_mean_input = np.mean(psnr_values_input)
        psnr_std = np.std(psnr_values)
        psnr_min = np.min(psnr_values)
        psnr_max = np.max(psnr_values)
        
        psnr_increased_percentage = (psnr_mean - psnr_mean_input) / psnr_mean_input * 100
        
        report = {
            "ckpt_path": args.ckpt_path,
            "data_path": args.data_path,
            "camera_name": args.camera_name,
            "output_dir": args.output_dir,
            "total_images": len(psnr_results),
            "reference_type": psnr_results[0]["reference_type"] if psnr_results else None,
            "statistics": {
                "mean_psnr": float(psnr_mean),
                "mean_psnr_input": float(psnr_mean_input),
                "increased_percentage": float(psnr_increased_percentage),
                "std_psnr": float(psnr_std),
                "min_psnr": float(psnr_min),
                "max_psnr": float(psnr_max)
            },
            "per_image_results": psnr_results
        }
        
        report_path = os.path.join(args.output_dir, "psnr_report.json")
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        print(f"PSNR report saved to {report_path}")