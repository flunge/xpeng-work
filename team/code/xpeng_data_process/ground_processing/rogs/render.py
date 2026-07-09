import os
import argparse
import yaml
import subprocess

import cv2
import torch
import numpy as np
import addict
from tqdm import tqdm
from torch.utils.data import DataLoader
from diff_gaussian_rasterization_depthalpha.scene.cameras import PerspectiveCamera

# 兼容两种运行方式：
# 1) 作为包模块： python -m xpeng_data_process.ground_processing.rogs.render  （推荐）
# 2) 在 rogs 目录下直接运行： python render.py
try:
    # 包内相对导入（推荐）
    from .utils.logging import create_logger
    from .utils.render import render
    from .models.gaussian_model import GaussianModel2D
    from .models.exposure_model import ExposureModel
    from .models.affine_model import RoGSAffineModule
    from .datasets.xpeng import XpengDataset
    from .train import set_randomness
except ImportError:
    # 直接脚本运行时，__package__ 为空，退回到“xpeng_data_process”为根包，保证 utils/render.py
    # 里的相对导入（..models.gaussian_model 等）仍然有效。
    import sys

    this_dir = os.path.dirname(os.path.abspath(__file__))          # .../xpeng_data_process/ground_processing/rogs
    pkg_root = os.path.dirname(os.path.dirname(this_dir))          # .../xpeng_data_process
    project_root = os.path.dirname(pkg_root)                       # .../3dgs （包含 xpeng_data_process 的目录）

    if project_root not in sys.path:
        sys.path.append(project_root)

    from xpeng_data_process.ground_processing.rogs.utils.logging import create_logger
    from xpeng_data_process.ground_processing.rogs.utils.render import render
    from xpeng_data_process.ground_processing.rogs.models.gaussian_model import GaussianModel2D
    from xpeng_data_process.ground_processing.rogs.models.exposure_model import ExposureModel
    from xpeng_data_process.ground_processing.rogs.models.affine_model import RoGSAffineModule
    from xpeng_data_process.ground_processing.rogs.datasets.xpeng import XpengDataset
    from xpeng_data_process.ground_processing.rogs.train import set_randomness


def parse_args():
    parser = argparse.ArgumentParser(description="RoGS render script")
    parser.add_argument(
        "--config",
        type=str,
        default="configs/oss_rogs_config.yaml",
        help="RoGS 配置文件路径（通常为 oss_rogs_config.yaml 或 GroundProcessor 生成的 rogs_config.yaml）",
    )
    parser.add_argument(
        "--clip_path",
        type=str,
        default="/workspace/yangxh7@xiaopeng.com/datasets/xpeng/hil_251217/c-7ef3dca1-6ce6-3278-a970-11be6a6028be",
        help="Xpeng clip 根目录，参考 GroundProcessor.cfg.clip_path，用于自动更新 dataset.clip_path 和 output",
    )
    parser.add_argument(
        "--clip_id",
        type=str,
        default="c-7ef3dca1-6ce6-3278-a970-11be6a6028be",
        help="Xpeng clip_id，参考 GroundProcessor.cfg.clip_id，用于自动更新 dataset.clip_list（使用前 10 位）",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=10,
        help="输出视频帧率",
    )
    parser.add_argument(
        "--output_root",
        type=str,
        default=None,
        help="渲染结果输出根目录（默认使用 config 中的 output）",
    )
    args = parser.parse_args()
    return args


def _resolve_config_path(config_path: str) -> str:
    """优先使用绝对路径；否则尝试相对于当前文件目录解析（参考 GroundProcessor 中 rogs_path 的用法）"""
    if os.path.isabs(config_path):
        return config_path
    # 相对于当前工作目录
    if os.path.exists(config_path):
        return os.path.abspath(config_path)
    # 相对于 RoGS 模块目录
    this_dir = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.join(this_dir, config_path)
    if os.path.exists(candidate):
        return os.path.abspath(candidate)
    # 保底返回原始路径，让后续报出更明确的 FileNotFound
    return config_path


def load_configs(config_path: str, clip_path: str = None, clip_id: str = None, output_root_override: str = None):
    """
    加载 RoGS 配置，并参考 GroundProcessor.process_ground_with_rogs
    构建 dataset.clip_path / dataset.clip_list 以及 output 路径。

    - dataset.clip_path <- clip_path
    - dataset.clip_list <- [clip_id[:10]]
    - output <- output_root_override 或 os.path.join(clip_path, 'vision', 'recon', 'ground_output')
    """
    real_cfg_path = _resolve_config_path(config_path)
    if not os.path.exists(real_cfg_path):
        raise FileNotFoundError(f"配置文件不存在: {real_cfg_path}")

    with open(real_cfg_path, "r") as f:
        cfg = yaml.safe_load(f)

    # dataset 路径与 clip_list，参考 GroundProcessor.process_ground_with_rogs
    if clip_path is not None:
        cfg.setdefault("dataset", {})
        cfg["dataset"]["clip_path"] = clip_path
    if clip_id is not None:
        cfg.setdefault("dataset", {})
        cfg["dataset"]["clip_list"] = [clip_id[:10]]

    # output 目录：优先使用显式传入的 output_root_override，
    # 否则若提供 clip_path，则与 GroundProcessor 保持一致：
    #   out_dir = os.path.join(clip_path, "vision", "recon", "ground_output")
    if output_root_override is not None:
        cfg["output"] = output_root_override
    elif clip_path is not None:
        cfg["output"] = os.path.join(clip_path, "vision", "recon", "ground_output")

    # 用于日志记录的配置文件路径
    cfg["file"] = os.path.abspath(real_cfg_path)
    cfg = addict.Dict(cfg)
    return cfg


def load_models_and_data(configs, logger):
    dataset_cfg = configs.dataset
    model_cfg = configs.model
    pipe = configs.pipeline
    opt = configs.optimization
    affine_cfg = configs.get("affine", None)

    set_randomness(configs.seed)

    device = torch.device(configs["device"] if torch.cuda.is_available() else "cpu")
    logger.info(f"Use device: {device}")

    # ===== 数据集（与 train.py 一致的数据预处理） =====
    if dataset_cfg["dataset"] == "XpengDataset":
        Dataset = XpengDataset
    else:
        raise NotImplementedError("Dataset not implemented")

    dataset = Dataset(
        dataset_cfg,
        use_label=opt.seg_loss_weight > 0,
        use_depth=opt.depth_loss_weight > 0,
    )
    logger.info(f"Dataset cameras_extent: {dataset.cameras_extent} - size: {len(dataset)}")

    # ===== 加载 Gaussian 模型（优先从 ply，其次从 ckpt） =====
    gaussians = GaussianModel2D(model_cfg)
    output_root = configs.output
    ply_path = os.path.join(output_root, "ply", "final.ply")
    ckpt_path = os.path.join(output_root, "final.pth")

    if os.path.exists(ply_path):
        logger.info(f"Load Gaussian model from ply: {os.path.abspath(ply_path)}")
        gaussians.load_ply(ply_path)
    elif os.path.exists(ckpt_path):
        logger.info(f"Load Gaussian model from checkpoint: {os.path.abspath(ckpt_path)}")
        model_params = torch.load(ckpt_path, map_location=device)
        # 恢复时仍然需要 optimization 配置（内部会构建 optimizer，但这里只做推理不会继续训练）
        opt["position_lr_max_steps"] = len(dataset) * opt.epochs
        gaussians.restore(model_params, opt)
    else:
        raise FileNotFoundError(
            f"未找到训练好的模型文件，既没有 ply({ply_path}) 也没有 ckpt({ckpt_path})"
        )

    # ===== 可选：曝光模型 =====
    exposure_model = None
    if model_cfg.get("use_exposure", False):
        logger.info("Use exposure model")
        exposure_model = ExposureModel(num_camera=len(dataset.camera_names)).to(device)
        exposure_ckpt = os.path.join(output_root, "exposure.pth")
        if os.path.exists(exposure_ckpt):
            logger.info(f"Load exposure checkpoint: {os.path.abspath(exposure_ckpt)}")
            state_dict = torch.load(exposure_ckpt, map_location=device)
            exposure_model.load_state_dict(state_dict)
        else:
            logger.warning(
                f"use_exposure=True 但未找到曝光模型权重 {exposure_ckpt}，将不进行曝光校正"
            )
            exposure_model = None

    # ===== 可选：颜色仿射模块 =====
    affine_module = None
    if affine_cfg is not None:
        logger.info("Use affine color module")
        num_embeddings = getattr(dataset, "max_unique_img_idx", len(dataset) - 1) + 1
        affine_module = RoGSAffineModule(affine_cfg, num_embeddings, device, logger)
        affine_ckpt = os.path.join(output_root, "affine_transform.pth")
        if os.path.exists(affine_ckpt):
            logger.info(f"Load affine checkpoint: {os.path.abspath(affine_ckpt)}")
            state_dict = torch.load(affine_ckpt, map_location=device)
            affine_module.model.load_state_dict(state_dict)
        else:
            logger.warning(
                f"启用了 affine 配置但未找到权重 {affine_ckpt}，将使用随机/零初始化仿射"
            )

    # 背景颜色与渲染管线
    bg_color = [1, 1, 1] if model_cfg.white_background else [0, 0, 0]
    background = torch.tensor(bg_color, dtype=torch.float32, device=device)

    return {
        "dataset": dataset,
        "gaussians": gaussians,
        "pipe": pipe,
        "device": device,
        "background": background,
        "exposure_model": exposure_model,
        "affine_module": affine_module,
        "opt": opt,
    }


def render_all(configs, fps: int, output_root_override: str = None):
    # ===== 准备输出目录与日志 =====
    output_root = output_root_override or configs.output
    os.makedirs(output_root, exist_ok=True)

    log_path = os.path.join(output_root, "render.log")
    logger = create_logger("RoGS-Render", log_path)
    logger.info(f"Config file: {configs.file}")
    logger.info(f"Render output root: {os.path.abspath(output_root)}")

    models_and_data = load_models_and_data(configs, logger)
    dataset = models_and_data["dataset"]
    gaussians = models_and_data["gaussians"]
    pipe = models_and_data["pipe"]
    device = models_and_data["device"]
    background = models_and_data["background"]
    exposure_model = models_and_data["exposure_model"]
    affine_module = models_and_data["affine_module"]
    opt = models_and_data["opt"]

    # 渲染结果目录（逐帧图像与视频）
    frames_root = os.path.join(output_root, "render_frames")
    videos_root = os.path.join(output_root, "render_videos")
    os.makedirs(frames_root, exist_ok=True)
    os.makedirs(videos_root, exist_ok=True)

    logger.info(f"Save render frames to: {os.path.abspath(frames_root)}")
    logger.info(f"Save render videos to: {os.path.abspath(videos_root)}")

    # VideoWriter 按相机关联
    video_writers = {}
    video_paths = {}
    frame_counters = {name: 0 for name in dataset.camera_names}

    dataloader = DataLoader(
        dataset, batch_size=1, num_workers=4, shuffle=False, drop_last=False
    )

    NEAR, FAR = 1.0, 50.0

    for sample in tqdm(dataloader, desc="Rendering"):
        # ===== 与 train.py 一致的数据预处理 =====
        for key, value in sample.items():
            if key != "image_name":
                sample[key] = value[0].to(device)
            else:
                sample[key] = value[0]

        image_name = sample["image_name"]
        image_idx = sample["idx"].item()
        cam_idx = sample["cam_idx"].item()
        gt_image = sample["image"]  # 只是用来获取尺寸

        R, T = sample["R"], sample["T"]
        W, H = sample["W"], sample["H"]
        viewpoint_cam = PerspectiveCamera(
            R, T, sample["K"], W, H, NEAR, FAR, device
        )

        # 背景
        if opt.random_background:
            bg = torch.rand((3), device=device)
        else:
            bg = background

        # ===== 渲染 RGB =====
        render_pkg = render(viewpoint_cam, gaussians, pipe, bg)
        src_render_image = render_pkg["render"]  # (C, H, W)

        # 曝光校正
        if exposure_model is not None:
            render_image = exposure_model(cam_idx, src_render_image)
        else:
            render_image = src_render_image

        # (H, W, 3)
        render_image = render_image.permute(1, 2, 0)

        # 仿射颜色变换
        if affine_module is not None:
            render_image, _ = affine_module.apply(render_image, image_idx)

        # 转 numpy / BGR
        render_np = render_image.detach().cpu().numpy()
        render_np = np.clip(render_np, 0.0, 1.0)
        render_np = (render_np * 255).astype(np.uint8)
        render_np = cv2.cvtColor(render_np, cv2.COLOR_RGB2BGR)

        cam_name = dataset.camera_names[cam_idx]
        cam_frame_dir = os.path.join(frames_root, cam_name)
        os.makedirs(cam_frame_dir, exist_ok=True)

        frame_idx = frame_counters[cam_name]
        frame_counters[cam_name] += 1

        frame_filename = os.path.join(
            cam_frame_dir, f"{frame_idx:06d}_{image_name}.png"
        )
        cv2.imwrite(frame_filename, render_np)

        # ===== 写入视频（按相机分别生成） =====
        h, w, _ = render_np.shape
        if cam_name not in video_writers:
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            video_path = os.path.join(videos_root, f"{cam_name}.mp4")
            video_writers[cam_name] = cv2.VideoWriter(video_path, fourcc, fps, (w, h))
            video_paths[cam_name] = video_path

        video_writers[cam_name].write(render_np)

    # 释放 VideoWriter
    for writer in video_writers.values():
        writer.release()

    logger.info("Rendering finished.")
    for cam_name in dataset.camera_names:
        if frame_counters[cam_name] > 0:
            logger.info(
                f"Camera {cam_name}: {frame_counters[cam_name]} frames, "
                f"video saved to {os.path.join(videos_root, f'{cam_name}.mp4')}"
            )

    # ===== 使用 ffmpeg 将多个相机视频拼接成一个总视频 =====
    # 仅使用实际有帧的相机，且按 dataset.camera_names 的顺序排列
    concat_cams = [
        name
        for name in dataset.camera_names
        if frame_counters.get(name, 0) > 0 and name in video_paths
    ]
    if len(concat_cams) >= 2:
        output_all = os.path.join(videos_root, "all_cameras.mp4")
        logger.info(
            f"Try to concat {len(concat_cams)} camera videos into one: {output_all}"
        )

        # 构造 ffmpeg 命令：水平拼接（hstack），所有输入分辨率和 fps 一致
        cmd = ["ffmpeg", "-y"]
        for cam_name in concat_cams:
            cmd.extend(["-i", video_paths[cam_name]])
        # 例如 7 路输入：[0:v][1:v]...[6:v]hstack=inputs=7[v]
        inputs_n = len(concat_cams)
        filter_inputs = "".join([f"[{i}:v]" for i in range(inputs_n)])
        filter_str = f"{filter_inputs}hstack=inputs={inputs_n}[v]"
        cmd.extend(
            [
                "-filter_complex",
                filter_str,
                "-map",
                "[v]",
                "-c:v",
                "libx264",
                "-crf",
                "18",
                "-preset",
                "veryfast",
                output_all,
            ]
        )

        try:
            subprocess.run(cmd, check=True, timeout=3600)
            logger.info(f"All cameras video saved to {output_all}")
        except FileNotFoundError:
            logger.warning("ffmpeg 未安装或不可用，跳过多相机视频拼接")
        except subprocess.CalledProcessError as e:
            logger.warning(f"ffmpeg 拼接多相机视频失败，命令: {' '.join(cmd)}，错误: {e}")


def main():
    args = parse_args()
    configs = load_configs(
        args.config,
        clip_path=args.clip_path,
        clip_id=args.clip_id,
        output_root_override=args.output_root,
    )
    # render_all 内部会再次优先使用 output_root_override，其次使用 configs.output
    render_all(configs, fps=args.fps, output_root_override=args.output_root)


if __name__ == "__main__":
    main()


