import os
import json
import argparse
from glob import glob
import random
import time
import imageio
import numpy as np
import torch
from PIL import Image
from tqdm import tqdm

from model import Difix, load_ckpt_from_state_dict
from pipeline_difix import DifixPipeline
from utils_difix import load_config as load_ckpt_config, calculate_psnr
from config_train import load_config as load_train_config


DEFAULT_PRETRAINED_PATH = "/workspace/group_share/adc-sim/users/led/ckpts/difix_ref"

def sorted_image_list(folder):
    if not os.path.isdir(folder):
        return []
    exts = ["*.png", "*.jpg", "*.jpeg", "*.bmp"]
    files = []
    for ext in exts:
        files.extend(glob(os.path.join(folder, ext)))
    files = sorted(files)
    return files


def parse_timestamp_ns_from_image_path(image_path):
    """
    从图片文件名中解析纳秒时间戳。
    例如: xxx/1771935789391096498.png -> 1771935789391096498
    """
    if image_path is None:
        return None
    stem = os.path.splitext(os.path.basename(image_path))[0]
    if stem.isdigit():
        return int(stem)
    return None


def _get_sample_height_width(input_width, input_height, config):
    """根据 config 与输入宽高返回推理用的 height, width；enable_dual_resolution_bucket 时按 16:9/5:4 选 bucket。"""
    if not config.get("enable_dual_resolution_bucket", False):
        return config.get("image_height", 576), config.get("image_width", 1024)
    aspect = input_width / max(input_height, 1)
    aspect_16_9 = 16.0 / 9.0
    aspect_5_4 = 5.0 / 4.0
    if abs(aspect - aspect_16_9) <= abs(aspect - aspect_5_4):
        return (
            config.get("bucket_16_9_height", 576),
            config.get("bucket_16_9_width", 1024),
        )
    return (
        config.get("bucket_5_4_height", 768),
        config.get("bucket_5_4_width", 960),
    )


def _get_all_bucket_sizes(config):
    if not config.get("enable_dual_resolution_bucket", False):
        return [(config.get("image_height", 576), config.get("image_width", 1024))]
    return [
        (config.get("bucket_16_9_height", 576), config.get("bucket_16_9_width", 1024)),
        (config.get("bucket_5_4_height", 768), config.get("bucket_5_4_width", 960)),
    ]


def _resolve_compile_cache_dir(cache_root):
    if cache_root is None or len(str(cache_root)) == 0:
        return None
    cache_root = os.path.abspath(cache_root)
    manifest_path = os.path.join(cache_root, "compile_manifest.json")
    if os.path.isfile(manifest_path):
        with open(manifest_path, "r") as f:
            manifest = json.load(f)
        manifest_cache_dir = manifest.get("cache_dir")
        if manifest_cache_dir and os.path.isdir(manifest_cache_dir):
            return manifest_cache_dir
    inductor_cache_dir = os.path.join(cache_root, "inductor_cache")
    if os.path.isdir(inductor_cache_dir):
        return inductor_cache_dir
    if os.path.isdir(cache_root):
        return cache_root
    return None


def _resolve_compile_cache_dir_from_ckpt(ckpt_path):
    if ckpt_path is None or len(str(ckpt_path)) == 0:
        return None
    ckpt_dir = os.path.abspath(ckpt_path)
    cache_root = os.path.join(ckpt_dir, "torch_compile_cache")
    return _resolve_compile_cache_dir(cache_root)


def run_inference_for_clip(
    model,
    config,
    clip_id,
    model_version,
    camera_name,
    input_root,
    gt_root,
    output_root,
    frame_step=2,
    max_frames_per_clip=-1,
    save_video=True,
    save_images=False,
    ref_image_mode=None,
    profile=False,
    enable_infer_optimizations=True,
    profile_warmup_frames=1,
):
    input_dir = os.path.join(
        input_root, clip_id, model_version,
        "simulator_render", "redistort_rgb", camera_name,
    )
    gt_dir = os.path.join(
        gt_root, clip_id,
        "images_origin", camera_name,
    )
    overwrite_prompt = config.get("overwrite_prompt", None)
    if isinstance(overwrite_prompt, str):
        overwrite_prompt = overwrite_prompt.strip()
    if overwrite_prompt == "":
        overwrite_prompt = None
    prompt_text = overwrite_prompt or f"Corrected rendering distortion for {camera_name.upper()} camera view."
    if not os.path.isdir(input_dir):
        print(f"[{clip_id}] input dir not found: {input_dir}, skip")
        return None
    if not os.path.isdir(gt_dir):
        print(f"[{clip_id}] gt dir not found: {gt_dir}, skip")
        return None

    input_images = sorted_image_list(input_dir)
    if len(input_images) == 0:
        print(f"[{clip_id}] no images in {input_dir}, skip")
        return None

    # 抽帧：排序后每间隔一张用一次
    indices = list(range(0, len(input_images), max(1, frame_step)))
    if max_frames_per_clip > 0:
        indices = indices[:max_frames_per_clip]

    input_images = [input_images[i] for i in indices]

    gt_images = []
    for p in input_images:
        name = os.path.basename(p)
        gt_path = os.path.join(gt_dir, name)
        if not os.path.exists(gt_path):
            print(f"[{clip_id}] gt image missing for {name}, skip this frame")
            gt_images.append(None)
        else:
            gt_images.append(gt_path)
    gt_timestamps_ns = [parse_timestamp_ns_from_image_path(p) for p in gt_images]

    os.makedirs(output_root, exist_ok=True)
    clip_out_dir = os.path.join(output_root, f"{clip_id}_{camera_name}")
    os.makedirs(clip_out_dir, exist_ok=True)

    output_images = []
    input_images_rgb = []
    gt_images_rgb = []
    psnr_results = []
    profile_results = []
    infer_call_count = 0

    for i, (inp_path, gt_path) in enumerate(
        tqdm(list(zip(input_images, gt_images)), desc=f"[{clip_id}] {camera_name}")
    ):
        if gt_path is None:
            continue

        gt_img = Image.open(gt_path).convert("RGB")
        in_img = Image.open(inp_path).convert("RGB")

        input_images_rgb.append(in_img)
        gt_images_rgb.append(gt_img)

        # enable_dual_resolution_bucket 时按输入宽高比选 bucket 的 height/width
        height, width = _get_sample_height_width(in_img.width, in_img.height, config)

        # 选择 ref image
        if ref_image_mode is None:
            ref_img = None
        elif abs(ref_image_mode) < 1e-6:
            # 使用当前帧 GT 作为 ref
            ref_img = gt_img
        else:
            # 在当前 clip 内，按时间窗口(秒)随机选择一帧 GT 作为 ref
            window_ns = int(float(ref_image_mode) * 1e9)
            cur_ts_ns = gt_timestamps_ns[i]
            candidates = [
                idx
                for idx, p in enumerate(gt_images)
                if (
                    p is not None
                    and idx != i
                    and cur_ts_ns is not None
                    and gt_timestamps_ns[idx] is not None
                    and abs(gt_timestamps_ns[idx] - cur_ts_ns) <= window_ns
                )
            ]
            if candidates:
                ref_idx = random.choice(candidates)
                ref_path = gt_images[ref_idx]
                ref_img = Image.open(ref_path).convert("RGB")
            else:
                ref_img = None

        in_tensor = torch.from_numpy(np.array(in_img)).permute(2, 0, 1).contiguous()
        ref_tensor = None
        if ref_img is not None:
            ref_tensor = torch.from_numpy(np.array(ref_img)).permute(2, 0, 1).contiguous()

        frame_profile = None
        if profile and infer_call_count >= max(0, profile_warmup_frames):
            out_tensor, frame_profile = model.sample_xpeng(
                in_tensor,
                height=height,
                width=width,
                ref_image=ref_tensor,
                prompt=prompt_text,
                profile=True,
                enable_infer_optimizations=enable_infer_optimizations,
            )
            profile_results.append(frame_profile)
        else:
            out_tensor = model.sample_xpeng(
                in_tensor,
                height=height,
                width=width,
                ref_image=ref_tensor,
                prompt=prompt_text,
                enable_infer_optimizations=enable_infer_optimizations,
            )
        infer_call_count += 1
        out_img = Image.fromarray(out_tensor.permute(1, 2, 0).cpu().numpy())
        output_images.append(out_img)

        psnr_value = calculate_psnr(out_img, gt_img)
        psnr_input = calculate_psnr(in_img, gt_img)

        rec = {
                "frame_index": i,
                "clip_id": clip_id,
                "camera_name": camera_name,
                "input_image": inp_path,
                "gt_image": gt_path,
                "output_image": os.path.join(
                    clip_out_dir, os.path.basename(inp_path)
                ),
                "psnr": float(psnr_value),
                "psnr_input": float(psnr_input),
                "delta_psnr": float(psnr_value - psnr_input),
            }
        if frame_profile is not None:
            rec["profile_ms"] = frame_profile
        psnr_results.append(rec)

    # 保存图片
    if save_images:
        for rec, out_img in zip(psnr_results, output_images):
            out_img.save(rec["output_image"])

    # 保存视频
    if save_video and len(output_images) > 0:
        video_out = os.path.join(clip_out_dir, "output.mp4")
        writer = imageio.get_writer(video_out, fps=6)
        for img in output_images:
            writer.append_data(np.array(img))
        writer.close()

        video_in = os.path.join(clip_out_dir, "input.mp4")
        writer = imageio.get_writer(video_in, fps=6)
        for img in input_images_rgb[: len(output_images)]:
            writer.append_data(np.array(img))
        writer.close()

        video_gt = os.path.join(clip_out_dir, "gt.mp4")
        writer = imageio.get_writer(video_gt, fps=6)
        for img in gt_images_rgb[: len(output_images)]:
            writer.append_data(np.array(img))
        writer.close()

    # 保存 clip 级别的 psnr 报告
    if len(psnr_results) > 0:
        psnrs = [r["psnr"] for r in psnr_results]
        psnrs_in = [r["psnr_input"] for r in psnr_results]
        report = {
            "clip_id": clip_id,
            "camera_name": camera_name,
            "model_version": model_version,
            "num_frames": len(psnr_results),
            "mean_psnr": float(np.mean(psnrs)),
            "mean_psnr_input": float(np.mean(psnrs_in)),
            "delta_psnr": float(np.mean(psnrs) - np.mean(psnrs_in)),
            "per_frame": psnr_results,
        }
        if profile and len(profile_results) > 0:
            mean_profile_ms = {
                k: float(np.mean([x[k] for x in profile_results if k in x]))
                for k in profile_results[0].keys()
            }
            total_ms = mean_profile_ms.get("sample_total_ms", 0.0)
            profile_ratio = {}
            if total_ms > 0:
                profile_ratio = {
                    k: float(v / total_ms)
                    for k, v in mean_profile_ms.items()
                    if k != "sample_total_ms"
                }
            report["profile_summary"] = {
                "profile_warmup_frames": int(max(0, profile_warmup_frames)),
                "num_profiled_frames": int(len(profile_results)),
                "mean_profile_ms": mean_profile_ms,
                "mean_profile_ratio": profile_ratio,
            }
            print(f"[{clip_id}] {camera_name} profile(ms): {mean_profile_ms}")
            print(f"[{clip_id}] {camera_name} profile(ratio): {profile_ratio}")
        elif profile:
            print(
                f"[{clip_id}] {camera_name} profile skipped: "
                f"num_profiled_frames=0 (warmup_frames={max(0, profile_warmup_frames)})"
            )
        with open(os.path.join(clip_out_dir, "psnr_report.json"), "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        return report

    return None


def _float_or_none(s):
    """Parse ref_image_mode: 'None'/'none' or empty -> None, otherwise float."""
    if s is None or (isinstance(s, str) and s.strip().lower() in ("", "none")):
        return None
    return float(s)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--train_data_json", type=str,
        default="/workspace/yangxh7@xiaopeng.com/codes/3dgs/models/difix/utils/eval_data_v1_0301/train_data_parts/train_data_part_0.json",
        help="Path to utils/train_data_res/train_data.json",
    )
    parser.add_argument("--ckpt_path", type=str,
        default="/workspace/yangxh7@xiaopeng.com/difix3D_train/train_v2/v2_0303_no_resume/checkpoints_epoch_0012_step_36000",
        help="Checkpoint directory (contains model.pkl and config.json)",
    )
    parser.add_argument("--use_origin_difix", action="store_true",
        help="If set, use original Difix (no ckpt) and save results to a sibling directory of ckpt_path",
    )
    parser.add_argument("--camera_names", type=str, nargs="+",
        default=["cam0", "cam2", "cam3", "cam4", "cam5", "cam6", "cam7"],
        help="Camera names, e.g. cam0 cam2 cam3 ...",
    )
    parser.add_argument("--frame_step", type=int,
        default=2,
        help="Use every N-th frame after sorting (>=1)",
    )
    parser.add_argument("--max_frames_per_clip", type=int,
        default=-1,
        help="Max frames per clip (-1 for no limit)",
    )
    parser.add_argument("--input_root", type=str,
        default="/workspace/group_share/adc-sim/users/cloudsim/difix/train_data",
        help="Root of simulator_render images",
    )
    parser.add_argument("--gt_root", type=str,
        default="/workspace/group_share/adc-sim/users/cloudsim/images_origin",
        help="Root of ground-truth images",
    )
    parser.add_argument("--save_images", action="store_true",
        help="Save per-frame output images",
    )
    parser.add_argument("--ref_image_mode", type=_float_or_none,
        default=0,
        help=(
            "Ref image mode: None(默认)=不使用ref；0=当前帧GT作为ref；"
            "N>0=在当前clip内前后N秒时间窗口内随机选一帧GT作为ref。传字符串 None 表示不使用"
        ),
    )
    parser.add_argument("--profile", action="store_true",
        help="Profile difix sampling pipeline and save per-component timing ratio.",
    )
    parser.add_argument("--disable_infer_optimizations", action="store_true",
        help="Disable inference optimizations (text cache + no-ref-decode + VAE channels_last/compile).",
    )
    parser.add_argument("--profile_warmup_frames", type=int, default=2,
        help="Number of warmup frames excluded from profile statistics (default: 1).",
    )

    args = parser.parse_args()
    with open(args.train_data_json, "r") as f:
        train_data = json.load(f)

    # 统一使用一个 ckpt 做评测；
    # 如果 use_origin_difix，则使用原始 Difix 配置（忽略 train_config）
    if args.use_origin_difix or len(args.ckpt_path) == 0:
        config = {
            "image_height": 576,
            "image_width": 1024,
            "lora_rank_vae": 4,
            "timestep": 199,
        }
    else:
        # 优先使用训练时的 YAML 配置，回退到 ckpt 目录下的 config.json（旧格式）
        train_config_path = os.path.join(args.ckpt_path, "train_config.yaml")
        train_cfg = load_train_config(train_config_path)
        if not isinstance(train_cfg, dict):
            raise ValueError(f"Invalid train_config yaml: {train_config_path}")
        config = {
            "image_height": train_cfg.get("image_height", 576),
            "image_width": train_cfg.get("image_width", 1024),
            "lora_rank_vae": train_cfg.get("lora_rank_vae", 4),
            "timestep": train_cfg.get("timestep", 199),
            "overwrite_prompt": train_cfg.get("overwrite_prompt", None),
            "enable_dual_resolution_bucket": train_cfg.get("enable_dual_resolution_bucket", False),
            "bucket_16_9_height": train_cfg.get("bucket_16_9_height", 576),
            "bucket_16_9_width": train_cfg.get("bucket_16_9_width", 1024),
            "bucket_5_4_height": train_cfg.get("bucket_5_4_height", 768),
            "bucket_5_4_width": train_cfg.get("bucket_5_4_width", 960),
        }
    if config.get("overwrite_prompt", None):
        print(f"[PROMPT] overwrite_prompt is enabled for all cameras: {config['overwrite_prompt']}")

    pipeline_name = DEFAULT_PRETRAINED_PATH.replace("difix_ref", "difix") if args.ref_image_mode is None else DEFAULT_PRETRAINED_PATH
    print(f"[NOTE] Using pipeline: {pipeline_name}")
    pipe = DifixPipeline.from_pretrained(
        pipeline_name,
        torch_dtype=torch.bfloat16,
        local_files_only=True,
    )
    model = Difix(
        pipe=pipe,
        timestep=config["timestep"],
        lora_rank_vae=config["lora_rank_vae"],
    )
    if (not args.use_origin_difix) and len(args.ckpt_path) > 0:
        print(f"Loading checkpoint from {args.ckpt_path}")
        model, _, _ = load_ckpt_from_state_dict(
            model, os.path.join(args.ckpt_path, "model.pkl")
        )
    else:
        print(f"Using original Difix configuration")
    model.to("cuda", dtype=torch.bfloat16)
    model.set_eval()

    # 先按所有 bucket 做一次 compile/内核预热，避免把这部分耗时算进正式推理
    enable_infer_optimizations = (not args.disable_infer_optimizations)
    # bucket_sizes = _get_all_bucket_sizes(config)
    # compile_cache_dir = None
    # if (not args.use_origin_difix) and len(args.ckpt_path) > 0:
    #     compile_cache_dir = _resolve_compile_cache_dir_from_ckpt(args.ckpt_path)
    # t1 = time.time()
    # if enable_infer_optimizations:
    #     if compile_cache_dir is not None:
    #         print(f"[NOTE] Load torch.compile cache from: {compile_cache_dir}", flush=True)
    #     else:
    #         print(f"[NOTE] compile cache not found under ckpt_path: {args.ckpt_path}, fallback to runtime compile", flush=True)
    #     model.prepare_inference_optimizations(compile_cache_dir=compile_cache_dir)
    #     print(
    #         f"[NOTE] Warmup compile for buckets: {bucket_sizes}, "
    #         f"use_ref={args.ref_image_mode is not None}"
    #         f"time for prepare_inference_optimizations: {time.time() - t1:.2f}s"
    #     , flush=True)
    # model.warmup_inference_compile_buckets(
    #     bucket_sizes=bucket_sizes,
    #     use_ref=(args.ref_image_mode is not None),
    #     camera_names=args.camera_names,
    #     enable_infer_optimizations=enable_infer_optimizations,
    # )
    # print(f"time for prepare&warmup compile: {time.time() - t1:.2f}s", flush=True)

    # 结果保存目录
    if args.use_origin_difix:
        if len(args.ckpt_path) > 0:
            ckpt_dir = args.ckpt_path.rstrip("/")
            parent_dir = os.path.dirname(ckpt_dir)
            output_root = os.path.join(parent_dir, f"inference_origin")
        else:
            output_root = "./inference_origin"
    else:
        output_root = args.ckpt_path.replace("checkpoints_", "inference_")
        if args.ref_image_mode is not None:
            output_root = output_root + f"_{args.ref_image_mode}"
    os.makedirs(output_root, exist_ok=True)

    for item in train_data:
        clip_id = item["clip_id"]
        model_version = item.get("model_version", "")
        if not item.get("images_origin_exist_in_oss", True):
            print(f"[{clip_id}] images_origin_exist_in_oss is False, skip")
            continue

        clip_cam_reports = []
        for cam in args.camera_names:
            clip_cam_report = run_inference_for_clip(
                model=model,
                config=config,
                clip_id=clip_id,
                model_version=model_version,
                camera_name=cam,
                input_root=args.input_root,
                gt_root=args.gt_root,
                output_root=output_root,
                frame_step=args.frame_step,
                max_frames_per_clip=args.max_frames_per_clip,
                save_video=True,
                save_images=args.save_images,
                ref_image_mode=args.ref_image_mode,
                profile=args.profile,
                enable_infer_optimizations=enable_infer_optimizations,
                profile_warmup_frames=args.profile_warmup_frames,
            )
            if clip_cam_report is not None:
                clip_cam_reports.append(clip_cam_report)

        # 所有 cam 平均的 PSNR
        mean_psnr_over_cams = float(np.mean([r["mean_psnr"] for r in clip_cam_reports])) if clip_cam_reports else None
        mean_psnr_input_over_cams = float(np.mean([r["mean_psnr_input"] for r in clip_cam_reports])) if clip_cam_reports else None

        clip_report = {
            "clip_id": clip_id,
            "camera_names": args.camera_names,
            "mean_psnr": mean_psnr_over_cams,
            "mean_psnr_input": mean_psnr_input_over_cams,
            "clip_cam_reports": clip_cam_reports,
        }
        with open(os.path.join(output_root, f"{clip_id}.json"), "w") as f:
            json.dump(clip_report, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    main()

