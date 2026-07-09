#!/usr/bin/env python3
"""
提取 config_sim.yaml 中的大矩阵/列表数据到 .npz 文件，加速模型初始化。

使用方式:
    python extract_results_cache.py /path/to/model_dir/configs/config_sim.yaml
    # 或者传入 model 目录:
    python extract_results_cache.py /path/to/model_dir

输出:
    - results_cache.npz  (与 config_sim.yaml 同级目录)
      包含: ego_frame_poses, timestamps, anchor_pose, ego_cam_poses
    - config_sim_slim.yaml (与 config_sim.yaml 同级目录)
      去除大数组后的精简配置，OmegaConf.load 速度提升 100x+
"""

import os
import sys
import time
import json
import numpy as np

try:
    from omegaconf import OmegaConf
except ImportError:
    print("[ERROR] omegaconf not installed. Run: pip install omegaconf")
    sys.exit(1)


def find_config_sim_yaml(path):
    """从给定路径找到 config_sim.yaml"""
    if os.path.isfile(path) and path.endswith(".yaml"):
        return path
    # 尝试作为 model_dir
    candidate = os.path.join(path, "configs", "config_sim.yaml")
    if os.path.isfile(candidate):
        return candidate
    raise FileNotFoundError(
        f"Cannot find config_sim.yaml from path: {path}\n"
        f"Please provide either the yaml file path or the model directory."
    )


def extract_results_cache(yaml_path):
    """从 config_sim.yaml 提取大数组到 npz 文件（从磁盘加载 yaml）"""
    configs_dir = os.path.dirname(yaml_path)
    npz_path = os.path.join(configs_dir, "results_cache.npz")
    slim_yaml_path = os.path.join(configs_dir, "config_sim_slim.yaml")

    print(f"[INFO] Loading YAML: {yaml_path}")
    t0 = time.perf_counter()
    cfg = OmegaConf.load(yaml_path)
    t1 = time.perf_counter()
    print(f"[INFO] OmegaConf.load took {t1 - t0:.2f}s")

    _extract_from_cfg(cfg, npz_path, slim_yaml_path)

    print(f"\n[DONE] Total extraction time: {time.perf_counter() - t0:.2f}s")
    print(f"  - results_cache.npz: {npz_path}")
    print(f"  - config_sim_slim.yaml: {slim_yaml_path}")
    print(f"\n[TIP] 下次初始化时 init_parameters 将自动使用 npz + slim yaml，预计耗时 < 0.1s")


def extract_results_cache_from_cfg(cfg, saved_cfg_path):
    """从内存中的 OmegaConf 对象直接提取大数组到 npz（无需重新解析 yaml，训练时使用）"""
    configs_dir = os.path.dirname(saved_cfg_path)
    npz_path = os.path.join(configs_dir, "results_cache.npz")
    slim_yaml_path = os.path.join(configs_dir, "config_sim_slim.yaml")

    t0 = time.perf_counter()
    _extract_from_cfg(cfg, npz_path, slim_yaml_path)
    print(f"[INFO] extract_results_cache_from_cfg took {time.perf_counter() - t0:.3f}s")


def _extract_from_cfg(cfg, npz_path, slim_yaml_path):
    """从 OmegaConf cfg 对象提取大数组并保存"""
    if not hasattr(cfg, "results"):
        print("[ERROR] No 'results' section in the config.")
        return

    results = cfg.results

    # ---- 提取大数组 ---- #
    save_dict = {}

    # ego_frame_poses: (N, 4, 4) float64
    if hasattr(results, "ego_frame_poses") and results.ego_frame_poses is not None:
        t2 = time.perf_counter()
        ego_frame_poses = np.array(OmegaConf.to_container(results.ego_frame_poses, resolve=True))
        save_dict["ego_frame_poses"] = ego_frame_poses
        print(f"[INFO] ego_frame_poses: shape={ego_frame_poses.shape}, dtype={ego_frame_poses.dtype}, "
              f"took {time.perf_counter() - t2:.3f}s")

    # timestamps: (N,) int64
    if hasattr(results, "timestamps") and results.timestamps is not None:
        t2 = time.perf_counter()
        timestamps_raw = OmegaConf.to_container(results.timestamps, resolve=True)
        timestamps = np.array([int(t) for t in timestamps_raw], dtype=np.int64)
        save_dict["timestamps"] = timestamps
        print(f"[INFO] timestamps: shape={timestamps.shape}, took {time.perf_counter() - t2:.3f}s")

    # anchor_pose: (4, 4) float64
    if hasattr(results, "anchor_pose") and results.anchor_pose is not None:
        t2 = time.perf_counter()
        anchor_pose = np.array(OmegaConf.to_container(results.anchor_pose, resolve=True))
        save_dict["anchor_pose"] = anchor_pose
        print(f"[INFO] anchor_pose: shape={anchor_pose.shape}, took {time.perf_counter() - t2:.3f}s")

    # ego_cam_poses: (N, num_cams, 4, 4) float64 - 最大的数值数组
    if hasattr(results, "ego_cam_poses") and results.ego_cam_poses is not None:
        t2 = time.perf_counter()
        ego_cam_poses = np.array(OmegaConf.to_container(results.ego_cam_poses, resolve=True))
        save_dict["ego_cam_poses"] = ego_cam_poses
        print(f"[INFO] ego_cam_poses: shape={ego_cam_poses.shape}, dtype={ego_cam_poses.dtype}, "
              f"took {time.perf_counter() - t2:.3f}s")

    # intrinsics: (num_cams, 3, 3) float64
    if hasattr(results, "intrinsics") and results.intrinsics is not None:
        t2 = time.perf_counter()
        intrinsics = np.array(OmegaConf.to_container(results.intrinsics, resolve=True))
        save_dict["intrinsics"] = intrinsics
        print(f"[INFO] intrinsics: shape={intrinsics.shape}, took {time.perf_counter() - t2:.3f}s")

    # extrinsics: (num_cams, 4, 4) float64
    if hasattr(results, "extrinsics") and results.extrinsics is not None:
        t2 = time.perf_counter()
        extrinsics = np.array(OmegaConf.to_container(results.extrinsics, resolve=True))
        save_dict["extrinsics"] = extrinsics
        print(f"[INFO] extrinsics: shape={extrinsics.shape}, took {time.perf_counter() - t2:.3f}s")

    # ---- 保存 npz ---- #
    t2 = time.perf_counter()
    np.savez(npz_path, **save_dict)
    print(f"[INFO] Saved {npz_path} ({os.path.getsize(npz_path) / 1024:.1f} KB), took {time.perf_counter() - t2:.3f}s")

    # ---- 生成精简 YAML (去除大数组) ---- #
    # 将大数组字段替换为 null，保留其他字段不变
    keys_to_strip = ["ego_frame_poses", "ego_cam_poses", "timestamps", "anchor_pose",
                     "intrinsics", "extrinsics", "annotations", "calibrations"]

    for key in keys_to_strip:
        if hasattr(results, key) and getattr(results, key) is not None:
            OmegaConf.update(cfg, f"results.{key}", None)

    t2 = time.perf_counter()
    slim_yaml_content = OmegaConf.to_yaml(cfg)
    with open(slim_yaml_path, "w") as f:
        f.write(slim_yaml_content)
    print(f"[INFO] Saved slim YAML: {slim_yaml_path} "
          f"({os.path.getsize(slim_yaml_path) / 1024:.1f} KB), took {time.perf_counter() - t2:.3f}s")


def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <config_sim.yaml | model_dir>")
        print(f"       python {sys.argv[0]} /path/to/model/configs/config_sim.yaml")
        print(f"       python {sys.argv[0]} /path/to/model/")
        sys.exit(1)

    path = sys.argv[1]
    yaml_path = find_config_sim_yaml(path)
    extract_results_cache(yaml_path)


if __name__ == "__main__":
    main()
