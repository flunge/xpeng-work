import logging
import math
import os
from typing import Any, Callable, Dict, Iterator, List, Optional

import cv2
import imageio
import numpy as np
import torch
from skimage.metrics import structural_similarity as ssim
from torch import Tensor
from torch.nn import functional as F
from tqdm import tqdm

from ..datasets.base import IterableSplitWrapper
from ..metrics.metric_utils import compute_fid
from ..trainers.base import BasicTrainer
from ..utils.visualization import depth_visualizer, to8b

logger = logging.getLogger()


def get_numpy(x: Tensor) -> np.ndarray:
    return x.squeeze().cpu().numpy()


def non_zero_mean(x: Tensor) -> float:
    return sum(x) / len(x) if len(x) > 0 else -1


def compute_psnr(prediction: Tensor, target: Tensor) -> float:
    """
    Computes the Peak Signal-to-Noise Ratio (PSNR) between the prediction and target tensors.

    Args:
        prediction (torch.Tensor): The predicted tensor.
        target (torch.Tensor): The target tensor.

    Returns:
        float: The PSNR value between the prediction and target tensors.
    """
    if not isinstance(prediction, Tensor):
        prediction = Tensor(prediction)
    if not isinstance(target, Tensor):
        target = Tensor(target).to(prediction.device)
    return (-10 * torch.log10(F.mse_loss(prediction, target))).item()


class MetricsTracker:
    """Helper class to track and compute metrics across frames"""

    def __init__(self):
        self.metrics = {
            "psnr": [],
            "ssim": [],
            "lpips": [],
            "fid": [],
            "occupied_psnr": [],
            "occupied_ssim": [],
            "masked_psnr": [],
            "masked_ssim": [],
            "human_psnr": [],
            "human_ssim": [],
            "vehicle_psnr": [],
            "vehicle_ssim": [],
        }

    def update(self, metric_name: str, value: float):
        """Add a new metric value"""
        if metric_name in self.metrics:
            self.metrics[metric_name].append(value)

    def get_metric(self, metric_name: str) -> float:
        """Get mean value for a metric"""
        return non_zero_mean(self.metrics.get(metric_name, []))

    def get_all_metrics(self) -> Dict[str, float]:
        """Get all metrics as a dictionary"""
        return {k: non_zero_mean(v) for k, v in self.metrics.items()}


def get_cpu_memory_usage():
    """Get the CPU memory usage in MB."""
    import psutil

    return psutil.Process().memory_info().rss / 1024.0 / 1024.0 / 1024.0


def render_images(
    trainer: BasicTrainer,
    dataset: IterableSplitWrapper,
    compute_metrics: bool = False,
    redistort_rgb: bool = False,
    compute_error_map: bool = False,
    vis_indices: Optional[List[int]] = None,
    render_keys: Optional[List[str]] = None,
    save_path: Optional[str] = None,
    layout_fn: Optional[Callable] = None,
    save_videos_config: Optional[Dict] = None,
):
    """
    Render pixel-related outputs from a model with frame-by-frame processing to reduce memory usage.

    Args:
        trainer: The trainer that handles rendering operations
        dataset: Dataset containing images to render
        compute_metrics: Whether to compute quality metrics
        compute_error_map: Whether to compute error maps
        vis_indices: Specific indices to visualize, if None, use all images
        render_keys: Keys specifying which outputs to render
        save_path: Path to save video output (if None, only metrics will be reported)
        layout_fn: Function to layout frames for video output
        save_videos_config: Configuration for video saving
    """
    trainer.set_eval()

    # Initialize metric tracking
    if compute_metrics:
        metrics_tracker = MetricsTracker()

    # Set up frame generator
    frame_generator = render_frame_by_frame(
        dataset,
        trainer=trainer,
        compute_metrics=compute_metrics,
        compute_error_map=compute_error_map,
        redistort_rgb=redistort_rgb,
        vis_indices=vis_indices,
        render_keys=render_keys,
    )

    # If saving videos, process with streaming approach
    if save_path and layout_fn:
        if save_videos_config is None:
            save_videos_config = {}

        # Extract video configuration
        num_timestamps = save_videos_config.get(
            "num_timestamps", len(dataset) if vis_indices is None else len(vis_indices)
        )
        num_cams = save_videos_config.get("num_cams", 1)
        keys = save_videos_config.get("keys", ["rgbs"])
        fps = save_videos_config.get("fps", 10)
        save_separate = save_videos_config.get("save_separate_video", False)
        save_images = save_videos_config.get("save_images", False)

        # Save videos with streaming approach
        save_videos_streaming(
            frame_generator,
            save_path,
            layout_fn,
            num_timestamps=num_timestamps,
            num_cams=num_cams,
            keys=keys,
            save_separate_video=save_separate,
            save_images=save_images,
            fps=fps,
            metrics_tracker=metrics_tracker if compute_metrics else None,
        )
    else:
        # Just process all frames to compute metrics
        for _ in frame_generator:
            pass

    # Report metrics if computed
    if compute_metrics:
        num_samples = len(dataset) if vis_indices is None else len(vis_indices)
        logger.info(f"Eval over {num_samples} images:")
        logger.info(f"\t Full Image  PSNR: {metrics_tracker.get_metric('psnr'):.4f}")
        logger.info(f"\t Full Image  SSIM: {metrics_tracker.get_metric('ssim'):.4f}")
        logger.info(f"\t Full Image LPIPS: {metrics_tracker.get_metric('lpips'):.4f}")
        logger.info(f"\t Full Image  FID:  {metrics_tracker.get_metric('fid'):.4f}")
        logger.info(f"\t     Non-Sky PSNR: {metrics_tracker.get_metric('occupied_psnr'):.4f}")
        logger.info(f"\t     Non-Sky SSIM: {metrics_tracker.get_metric('occupied_ssim'):.4f}")
        logger.info(f"\tDynamic-Only PSNR: {metrics_tracker.get_metric('masked_psnr'):.4f}")
        logger.info(f"\tDynamic-Only SSIM: {metrics_tracker.get_metric('masked_ssim'):.4f}")
        logger.info(f"\t  Human-Only PSNR: {metrics_tracker.get_metric('human_psnr'):.4f}")
        logger.info(f"\t  Human-Only SSIM: {metrics_tracker.get_metric('human_ssim'):.4f}")
        logger.info(f"\tVehicle-Only PSNR: {metrics_tracker.get_metric('vehicle_psnr'):.4f}")
        logger.info(f"\tVehicle-Only SSIM: {metrics_tracker.get_metric('vehicle_ssim'):.4f}")

        return metrics_tracker.get_all_metrics()

    return {}


def render_frame_by_frame(
    dataset: IterableSplitWrapper,
    trainer: BasicTrainer = None,
    compute_metrics: bool = False,
    compute_error_map: bool = False,
    redistort_rgb: bool = False,
    vis_indices: Optional[List[int]] = None,
    render_keys: Optional[List[str]] = None,
) -> Iterator[Dict[str, Any]]:
    """
    Renders dataset frame by frame, yielding results for each frame to reduce memory usage.

    Args:
        dataset: Dataset to render
        trainer: Gaussian trainer with rendering functionality
        compute_metrics: Whether to compute and return metrics
        compute_error_map: Whether to compute and return error maps
        vis_indices: Specific indices to visualize (None = all)
        render_keys: Keys for specifying which outputs to render

    Yields:
        Dict containing render results for a timestamp (all cameras for that timestamp)
    """
    if render_keys is None:
        render_keys = []

    # Prepare index list
    indices = vis_indices if vis_indices is not None else range(len(dataset))

    # Calculate number of cameras per timestamp
    # This assumes the dataset is organized with consecutive frames belonging to the same timestamp
    # We need to determine this from the dataset structure
    # Process each frame
    with torch.no_grad():
        for frame_idx in tqdm(indices, desc=f"rendering {dataset.split}", dynamic_ncols=True):
            # print within tqdm in Xpeng fuyao platform
            print(f"rendering frame idx: {frame_idx}", flush=True)
            # Get image and camera info
            image_info, cam_info = dataset[frame_idx]
            image_info.to(torch.device("cuda"))
            cam_info.to(torch.device("cuda"))

            # Render the image
            results = trainer(image_info, cam_info)

            # Clip RGB values to valid range
            for k, v in results.items():
                if isinstance(v, Tensor) and "rgb" in k:
                    results[k] = v.clamp(0.0, 1.0)

            if image_info.pixels is not None:
                image_info.pixels = image_info.pixels.clamp(0.0, 1.0)

            # Process frame data
            frame_data = process_frame_data(
                dataset,
                results,
                image_info,
                cam_info,
                render_keys,
                compute_metrics,
                compute_error_map,
                redistort_rgb,
                trainer,
            )

            # Yield frame data
            yield frame_data

            # Explicitly clear large tensors
            del results, image_info, cam_info
            torch.cuda.empty_cache()


def process_frame_data(
    dataset: IterableSplitWrapper,
    results: Dict[str, Tensor],
    image_info: Any,
    cam_info: Any,
    render_keys: List[str],
    compute_metrics: bool,
    compute_error_map: bool,
    redistort_rgb: bool,
    trainer: BasicTrainer,
) -> Dict[str, Any]:
    """
    Process render results for a single frame.

    Args:
        results: Render results from trainer
        image_info: Image information
        cam_info: Camera information
        render_keys: Keys specifying which outputs to render
        compute_metrics: Whether to compute metrics
        compute_error_map: Whether to compute error map
        trainer: Trainer object for metrics computation

    Returns:
        Processed frame data
    """
    frame_data = {}

    # Store camera info
    frame_data["camera_name"] = cam_info.camera_name
    frame_data["camera_id"] = cam_info.camera_id

    # Process RGB output
    rgb = results["rgb"]
    frame_data["rgb"] = get_numpy(rgb)
    
    if image_info.masks is not None and image_info.masks.egocar_mask is not None:
        frame_data["rgb"] = frame_data["rgb"] * get_numpy(1.0 - image_info.masks.egocar_mask.float())[..., None]
    if redistort_rgb:
        expand_ratio = dataset.datasource.camera_data[cam_info.camera_id].expand_ratio
        distortion_map = dataset.datasource.camera_data[cam_info.camera_id].distortion_maps
        redistort_rgb = cv2.remap(
            frame_data["rgb"], distortion_map[0], distortion_map[1], interpolation=cv2.INTER_LINEAR
        )
        frame_data["rgb"] = redistort_rgb[
            : math.ceil(redistort_rgb.shape[0] / expand_ratio), : math.ceil(redistort_rgb.shape[1] / expand_ratio), :
        ]

    if image_info.pixels is not None:
        frame_data["gt_rgb"] = get_numpy(image_info.pixels)

    # Process component-specific outputs
    green_background = torch.tensor([0.0, 177, 64]) / 255.0
    green_background = green_background.to(rgb.device)

    component_types = ["Background", "Ground", "RigidNodes", "DeformableNodes", "SMPLNodes", "Dynamic"]

    for comp in component_types:
        if f"{comp}_rgb" in results and f"{comp}_rgbs" in render_keys:
            comp_rgb = results[f"{comp}_rgb"] * results[f"{comp}_opacity"] + green_background * (
                1 - results[f"{comp}_opacity"]
            )
            frame_data[f"{comp}_rgb"] = get_numpy(comp_rgb)

        if f"{comp}_depth" in results:
            if f"{comp}_depths" in render_keys:
                frame_data[f"{comp}_depth"] = get_numpy(results[f"{comp}_depth"])
            if f"{comp}_opacities" in render_keys:
                frame_data[f"{comp}_opacity"] = get_numpy(results[f"{comp}_opacity"])

    # Additional outputs
    if compute_error_map:
        error_map = (rgb - image_info.pixels) ** 2
        error_map = error_map.mean(dim=-1, keepdim=True)
        error_map = (error_map - error_map.min()) / (error_map.max() - error_map.min())
        error_map = error_map.repeat_interleave(3, dim=-1)
        frame_data["error_map"] = get_numpy(error_map)

    for key in ["rgb_sky_blend", "rgb_sky"]:
        if key in results and key in render_keys:
            frame_data[key] = get_numpy(results[key])

    if "depths" in render_keys:
        frame_data["depth"] = get_numpy(results["depth"])

    if "opacity" in results and "opacities" in render_keys:
        frame_data["opacity"] = get_numpy(results["opacity"])

    if image_info.masks.sky_mask is not None and "sky_masks" in render_keys:
        frame_data["sky_mask"] = get_numpy(image_info.masks.sky_mask)

    if image_info.depth_map is not None and "lidar_on_images" in render_keys:
        depth_map = image_info.depth_map
        depth_img = depth_map.cpu().numpy()
        depth_img = depth_visualizer(depth_img, depth_img > 0)
        mask = (depth_map.unsqueeze(-1) > 0).cpu().numpy()
        lidar_on_image = image_info.pixels.cpu().numpy() * (1 - mask) + depth_img * mask
        frame_data["lidar_on_image"] = lidar_on_image

    # Compute metrics if requested
    if compute_metrics:
        metrics = {}

        # Full image metrics
        metrics["psnr"] = compute_psnr(rgb, image_info.pixels)
        metrics["ssim"] = ssim(
            get_numpy(rgb),
            get_numpy(image_info.pixels),
            data_range=1.0,
            channel_axis=-1,
        )
        metrics["lpips"] = trainer.lpips(
            rgb[None, ...].permute(0, 3, 1, 2),
            image_info.pixels[None, ...].permute(0, 3, 1, 2),
        ).item()
        metrics["fid"] = compute_fid(
            rgb[None, ...].permute(0, 3, 1, 2), image_info.pixels[None, ...].permute(0, 3, 1, 2)
        )
        # Various masked metrics
        if image_info.masks.sky_mask is not None:
            occupied_mask = ~get_numpy(image_info.masks.sky_mask).astype(bool)
            if occupied_mask.sum() > 0:
                metrics["occupied_psnr"] = compute_psnr(rgb[occupied_mask], image_info.pixels[occupied_mask])
                metrics["occupied_ssim"] = ssim(
                    get_numpy(rgb),
                    get_numpy(image_info.pixels),
                    data_range=1.0,
                    channel_axis=-1,
                    full=True,
                )[1][occupied_mask].mean()

        if image_info.masks.dynamic_mask is not None:
            dynamic_mask = get_numpy(image_info.masks.dynamic_mask).astype(bool)
            if dynamic_mask.sum() > 0:
                metrics["masked_psnr"] = compute_psnr(rgb[dynamic_mask], image_info.pixels[dynamic_mask])
                metrics["masked_ssim"] = ssim(
                    get_numpy(rgb),
                    get_numpy(image_info.pixels),
                    data_range=1.0,
                    channel_axis=-1,
                    full=True,
                )[1][dynamic_mask].mean()

        if image_info.masks.human_mask is not None:
            human_mask = get_numpy(image_info.masks.human_mask).astype(bool)
            if human_mask.sum() > 0:
                metrics["human_psnr"] = compute_psnr(rgb[human_mask], image_info.pixels[human_mask])
                metrics["human_ssim"] = ssim(
                    get_numpy(rgb),
                    get_numpy(image_info.pixels),
                    data_range=1.0,
                    channel_axis=-1,
                    full=True,
                )[1][human_mask].mean()

        if image_info.masks.vehicle_mask is not None:
            vehicle_mask = get_numpy(image_info.masks.vehicle_mask).astype(bool)
            if vehicle_mask.sum() > 0:
                metrics["vehicle_psnr"] = compute_psnr(rgb[vehicle_mask], image_info.pixels[vehicle_mask])
                metrics["vehicle_ssim"] = ssim(
                    get_numpy(rgb),
                    get_numpy(image_info.pixels),
                    data_range=1.0,
                    channel_axis=-1,
                    full=True,
                )[1][vehicle_mask].mean()

        frame_data["metrics"] = metrics

    return frame_data


def save_videos_streaming(
    frame_generator: Iterator[Dict[str, Any]],
    save_pth: str,
    layout: Callable,
    num_timestamps: int,
    num_cams: int = 3,
    keys: List[str] = ["gt_rgbs", "rgbs", "depths"],
    save_separate_video: bool = False,
    save_images: bool = False,
    fps: int = 10,
    metrics_tracker: Optional[MetricsTracker] = None,
):
    """
    Save videos with streaming frame-by-frame processing to minimize memory usage.

    Args:
        frame_generator: Generator yielding frame data
        save_pth: Path to save the output
        layout: Function to layout frames
        num_timestamps: Number of timestamps in the sequence
        num_cams: Number of cameras per timestamp
        keys: Keys of data to include in the video
        save_separate_video: Whether to save each type in a separate video
        save_images: Whether to save individual image frames
        fps: Frames per second for the video
        metrics_tracker: Optional tracker for metrics across frames
    """
    # Determine if this is a single image or a video
    is_image = num_timestamps == 1

    # Setup for either separate videos or concatenated video
    if save_separate_video:
        video_writers = {}
        for key in keys:
            if (
                key in ["gt_rgbs", "rgbs", "depths"]
                or key.endswith("_rgbs")
                or key.endswith("_depths")
                or key in ["rgb_sky", "rgb_sky_blend"]
            ):
                # Remove trailing 's'
                output_key = key[:-1] if key.endswith("s") else key

                tmp_save_pth = save_pth.replace(".mp4", f"_{output_key}.mp4")
                tmp_save_pth = tmp_save_pth.replace(".png", f"_{output_key}.png")

                if is_image:
                    video_writers[key] = imageio.get_writer(tmp_save_pth, mode="I")
                else:
                    video_writers[key] = imageio.get_writer(tmp_save_pth, mode="I", fps=fps)
    else:
        # One combined video
        if is_image:
            video_writer = imageio.get_writer(save_pth, mode="I")
        else:
            video_writer = imageio.get_writer(save_pth, mode="I", fps=fps)

    # Process frames as they come in
    current_timestamp = 0
    frames_buffer = []
    cam_names_buffer = []

    try:
        for frame_data in frame_generator:
            # Track metrics if requested
            if metrics_tracker and "metrics" in frame_data:
                for metric_name, value in frame_data["metrics"].items():
                    metrics_tracker.update(metric_name, value)

            # Add frame to buffer
            frames_buffer.append(frame_data)
            cam_names_buffer.append(frame_data["camera_name"])

            # If we have collected all cameras for this timestamp, process and write
            if len(frames_buffer) == num_cams:
                if save_separate_video:
                    _process_timestamp_separate(
                        frames_buffer,
                        cam_names_buffer,
                        video_writers,
                        layout,
                        keys,
                        save_images,
                        save_pth,
                        current_timestamp,
                    )
                else:
                    _process_timestamp_concatenated(
                        frames_buffer, cam_names_buffer, video_writer, layout, keys, current_timestamp
                    )

                # Clear buffers and increment timestamp
                frames_buffer = []
                cam_names_buffer = []
                current_timestamp += 1
    finally:
        # Close all writers
        if save_separate_video:
            for writer in video_writers.values():
                writer.close()
        else:
            video_writer.close()


def _process_timestamp_separate(
    frames: List[Dict],
    cam_names: List[str],
    video_writers: Dict[str, Any],
    layout: Callable,
    keys: List[str],
    save_images: bool,
    save_pth: str,
    timestamp: int,
):
    """Process and write a timestamp for separate videos"""
    for key in keys:
        if key in video_writers:
            output_key = key[:-1] if key.endswith("s") else key
            # Extract frames for this key
            key_frames = []
            for frame in frames:
                frame_key = output_key if output_key in frame else key
                if frame_key in frame:
                    data = frame[frame_key]
                    # Handle special types
                    if "mask" in output_key:
                        data = np.stack([data, data, data], axis=-1)
                    elif "depth" in output_key:
                        opacity_key = output_key.replace("depth", "opacity")
                        if opacity_key in frame:
                            data = depth_visualizer(data, frame[opacity_key])
                    key_frames.append(data)

            # Skip if no valid frames
            if not key_frames:
                continue

            # Layout frames and write
            tiled_img = layout(key_frames, cam_names)

            # Save individual images if requested
            if save_images:
                img_dir = save_pth.replace(".mp4", f"_{output_key}")
                os.makedirs(img_dir, exist_ok=True)
                for j, frame in enumerate(key_frames):
                    imageio.imwrite(os.path.join(img_dir, f"{timestamp:03d}_{j:03d}.png"), to8b(frame))

            # Write to video
            video_writers[key].append_data(to8b(tiled_img))


def _process_timestamp_concatenated(
    frames: List[Dict], cam_names: List[str], video_writer: Any, layout: Callable, keys: List[str], timestamp: int
):
    """Process and write a timestamp for concatenated video"""
    merged_list = []

    for key in keys:
        output_key = key[:-1] if key.endswith("s") else key

        # Extract frames for this key
        key_frames = []
        for frame in frames:
            frame_key = output_key if output_key in frame else key
            if frame_key in frame:
                data = frame[frame_key]
                # Handle special types
                if "mask" in output_key:
                    data = np.stack([data, data, data], axis=-1)
                elif "depth" in output_key:
                    opacity_key = output_key.replace("depth", "opacity")
                    if opacity_key in frame:
                        data = depth_visualizer(data, frame[opacity_key])
                key_frames.append(data)

        # Skip if no valid frames
        if not key_frames:
            continue

        # Layout frames and add to list
        tiled_img = layout(key_frames, cam_names)
        merged_list.append(tiled_img)

    # Write concatenated frame
    if merged_list:
        merged_frame = to8b(np.concatenate(merged_list, axis=0))
        video_writer.append_data(merged_frame)
