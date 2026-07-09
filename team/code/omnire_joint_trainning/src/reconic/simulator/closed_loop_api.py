"""Closed-loop simulation entrypoints (single-frame and multi-camera batch)."""

from __future__ import annotations

import os
import time

import numpy as np
import torch

from sim_interface.utils import _log_gpu_memory

from reconic.simulator.simulator_helpers import build_ego_pose_world
from reconic.simulator.render_strategy.strategies_factory import RenderStrategyFactory


def _attach_debug_gt(info, strategy, rendered_timestamp, camera, base_dir_env_key="REF_PATH"):
    if not hasattr(strategy, "get_reference_image"):
        return
    base_dir = os.environ.get(base_dir_env_key, "")
    if not base_dir:
        return
    image_path = strategy.get_real_car_image(int(rendered_timestamp), camera, base_dir)
    if image_path is None or not isinstance(image_path, str):
        return
    from PIL import Image

    ref_array = np.array(Image.open(image_path).convert("RGB"))
    info["image_gt"] = torch.from_numpy(ref_array).permute(2, 0, 1).to(torch.uint8).cuda()


def _frame_info(camera, rendered_timestamp, img_distort):
    height, width = img_distort.shape[0:2]
    return {
        "cam": camera,
        "time_stamp": rendered_timestamp,
        "width": width,
        "height": height,
        "image": img_distort.flatten(),
    }


def fun(
    simulator,
    rendered_timestamp,
    camera,
    ego_pose_arr,
    collision_info_arr=None,
    real_car_image=None,
    ego_pose_world=None,
    debug=False,
):
    collision_info_arr = collision_info_arr or []
    render_start_time = time.time()
    print(
        f"CP timestamp {rendered_timestamp} camera {camera} ego_pose_arr {ego_pose_arr}",
        flush=True,
    )
    if ego_pose_world is None:
        ego_pose_world = build_ego_pose_world(ego_pose_arr)
    print("ego_pose_world:", ego_pose_world)

    t1 = time.time()
    strategy = RenderStrategyFactory.create_strategy()
    _log_gpu_memory("before strategy.render", simulator.device, reset_peak_after=True)
    img_distort = strategy.render(
        simulator,
        camera,
        int(rendered_timestamp),
        ego_pose_world,
        collision_info_arr,
        real_car_image=real_car_image,
    )
    _log_gpu_memory("after strategy.render", simulator.device, report_peak=True)
    print(f"render cost {time.time() - t1}")

    if img_distort is None:
        return None

    info = _frame_info(camera, rendered_timestamp, img_distort)
    # CLIP-IQA 质量评分
    if hasattr(simulator, "apply_clipiqa_to_info"):
        simulator.apply_clipiqa_to_info(
            info, img_distort, camera, rendered_timestamp,
            real_car_image=real_car_image,
        )
    print(f"Rendering {camera} images done", flush=True)
    print(
        f"Rendering one frame cost time {time.time() - render_start_time:.2f} seconds",
        flush=True,
    )
    if debug:
        _attach_debug_gt(info, strategy, rendered_timestamp, camera)
    return info


def fun_one_frame(
    simulator,
    rendered_timestamp,
    cameras,
    ego_pose_arr,
    collision_info_arr=None,
    real_car_image_map=None,
    ego_pose_world=None,
    debug=False,
):
    collision_info_arr = collision_info_arr or []
    print(
        f"CP timestamp {rendered_timestamp} ego_pose_arr {ego_pose_arr} cameras {cameras}",
        flush=True,
    )
    if ego_pose_world is None:
        ego_pose_world = build_ego_pose_world(ego_pose_arr)
    print("ego_pose_world:", ego_pose_world)

    t1 = time.time()
    strategy = RenderStrategyFactory.create_strategy()
    _log_gpu_memory("before strategy.render", simulator.device, reset_peak_after=True)
    all_cam_result = strategy.render_batch(
        simulator,
        cameras,
        int(rendered_timestamp),
        ego_pose_world,
        collision_info_arr,
        real_car_image_map=real_car_image_map,
    )
    _log_gpu_memory("after strategy.render", simulator.device, report_peak=True)
    if all_cam_result is None:
        return None

    print(f"render cost {time.time() - t1}")
    print("prepare render info")

    all_render_info = {}
    for camera, img_distort in all_cam_result.items():
        info = _frame_info(camera, rendered_timestamp, img_distort)
        if debug and hasattr(strategy, "get_reference_image"):
            info["image_gt"] = strategy.get_reference_image(int(rendered_timestamp), camera)
        # CLIP-IQA 质量评分
        if hasattr(simulator, "apply_clipiqa_to_info"):
            ref_img_dict = real_car_image_map.get(camera) if real_car_image_map else None
            simulator.apply_clipiqa_to_info(
                info, img_distort, camera, rendered_timestamp,
                real_car_image=ref_img_dict,
            )
        all_render_info[camera] = info
        print(f"info of {camera}: {info}")
    return all_render_info
