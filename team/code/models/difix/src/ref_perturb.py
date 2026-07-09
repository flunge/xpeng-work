"""
ref_perturb.py — difix 训练时对 ref 图施加 "伪换车型" 几何扰动的工具.

设计目标:
  让 difix 在 ref 和 3DGS 渲染图 "高度对齐" 的样本上, ref 几何不能被模型当作
  真值复制过去. 解决方式: 用三种车型 (h93aes / e29 / f01es) cam0~cam7 的标定差异
  作为扰动幅度上限, 在训练时随机扰动 ref 图.

几何模型:
  - 旋转扰动 (Δroll/Δpitch/Δyaw): 旋转单应 H = K @ R @ K^-1 (精确, 无深度依赖)
  - 平移扰动 (Δx/Δy/Δz): 在代表性深度 Z (默认 15m) 下近似为图像平移 + 缩放
  - 内参扰动 (Δcx/Δcy/Δfx): 直接进 K
  - 各路相机扰动幅度上限来自三车实测 (max - min)/2, 可用 amp 放大

对外 API:
  perturb_pil_ref(pil_img, cam_id, amp=10.0, repr_depth=15.0, rng=None) -> PIL.Image
"""

import json
import math
import os
from functools import lru_cache
from typing import Dict, List, Optional

import cv2
import numpy as np
from PIL import Image


CALIB_FILES = (
    "/workspace/group_share/adc-sim/users/multi_vehicle/calibs/calib_h93aes.json",
    "/workspace/group_share/adc-sim/users/multi_vehicle/calibs/calib_e29.json",
    "/workspace/group_share/adc-sim/users/multi_vehicle/calibs/calib_f01es.json",
)
TARGET_CAMS = ("cam0", "cam2", "cam3", "cam4", "cam5", "cam6", "cam7")


# ---------- calibration loading (cached, lazy) ----------


@lru_cache(maxsize=1)
def _load_calibrations() -> Dict[str, List[dict]]:
    """读取三车标定, 返回 {cam_id: [entry_per_vehicle, ...]}; 出错时不抛出, 返回部分结果."""
    all_cams: Dict[str, List[dict]] = {}
    for fpath in CALIB_FILES:
        if not os.path.isfile(fpath):
            print(f"[ref_perturb] calib not found, skip: {fpath}")
            continue
        try:
            with open(fpath) as f:
                d = json.load(f)
        except Exception as e:
            print(f"[ref_perturb] failed to load {fpath}: {e}")
            continue
        for cam_id in TARGET_CAMS:
            if cam_id not in d:
                continue
            cam = d[cam_id]
            if "extrinsic" not in cam or "intrinsic" not in cam:
                continue
            extr = cam["extrinsic"]
            intr = cam["intrinsic"]
            props = cam.get("properties", {})
            if extr.get("x") is None:
                continue
            all_cams.setdefault(cam_id, []).append({
                "x": extr["x"], "y": extr["y"], "z": extr["z"],
                "roll": extr["roll"], "pitch": extr["pitch"], "yaw": extr["yaw"],
                "fx": intr["focal_length"], "cx": intr["cx"], "cy": intr["cy"],
                "W": props.get("width"), "H": props.get("height"),
            })
    return all_cams


@lru_cache(maxsize=16)
def _stats_for(cam_id: str) -> Optional[dict]:
    """统计某路相机跨车型每个字段的 (mean, half_range). 不足 2 辆车则返回 None."""
    entries = _load_calibrations().get(cam_id)
    if not entries or len(entries) < 2:
        return None
    fields = ("x", "y", "z", "roll", "pitch", "yaw", "fx", "cx", "cy")
    stats: Dict[str, dict] = {}
    for fd in fields:
        vals = [e[fd] for e in entries]
        vmin, vmax = min(vals), max(vals)
        stats[fd] = {"mean": sum(vals) / len(vals), "half_range": (vmax - vmin) / 2.0}
    stats["W_ref"] = entries[0]["W"]
    stats["H_ref"] = entries[0]["H"]
    return stats


def is_available_for_cam(cam_id: str) -> bool:
    """判断该路相机是否能做扰动 (标定齐全才可)."""
    return _stats_for(cam_id) is not None


# ---------- geometry ----------


def _euler_to_rotmat(roll_deg: float, pitch_deg: float, yaw_deg: float) -> np.ndarray:
    """OpenCV 相机系 (x=right, y=down, z=forward) 下的小角度旋转矩阵."""
    r = math.radians(roll_deg)
    p = math.radians(pitch_deg)
    y = math.radians(yaw_deg)
    Rx = np.array([[1, 0, 0], [0, math.cos(p), -math.sin(p)], [0, math.sin(p), math.cos(p)]])
    Ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    Rz = np.array([[math.cos(r), -math.sin(r), 0], [math.sin(r), math.cos(r), 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def _sample_homography(
    cam_id: str,
    W: int,
    H: int,
    amp: float,
    repr_depth: float,
    rng: np.random.Generator,
) -> Optional[np.ndarray]:
    stats = _stats_for(cam_id)
    if stats is None:
        return None
    W_ref = stats["W_ref"]
    H_ref = stats["H_ref"]
    fx_ref_mean = stats["fx"]["mean"]
    fx_img = fx_ref_mean * (W / W_ref)
    cx_img = W / 2.0
    cy_img = H / 2.0

    def s(field: str) -> float:
        return float(rng.uniform(-1.0, 1.0)) * stats[field]["half_range"] * amp

    d_roll = s("roll")
    d_pitch = s("pitch")
    d_yaw = s("yaw")
    d_x = s("x")
    d_y = s("y")
    d_z = s("z")
    d_fx_rel = (s("fx") / fx_ref_mean) if fx_ref_mean else 0.0
    d_cx_pix = s("cx") * (W / W_ref)
    d_cy_pix = s("cy") * (H / H_ref)

    ty_pix = fx_img * d_z / max(repr_depth, 1e-3)
    tx_pix = -fx_img * d_y / max(repr_depth, 1e-3)
    scale = 1.0 + (d_x / max(repr_depth, 1e-3)) * 0.3

    K = np.array(
        [[fx_img, 0, cx_img], [0, fx_img, cy_img], [0, 0, 1]],
        dtype=np.float64,
    )
    fx_new = fx_img * (1.0 + d_fx_rel) * scale
    K_new = np.array(
        [
            [fx_new, 0, cx_img + d_cx_pix + tx_pix],
            [0, fx_new, cy_img + d_cy_pix + ty_pix],
            [0, 0, 1],
        ],
        dtype=np.float64,
    )
    R = _euler_to_rotmat(d_roll, d_pitch, d_yaw)
    return K_new @ R @ np.linalg.inv(K)


# ---------- public API ----------


def perturb_pil_ref(
    ref_img_pil: Image.Image,
    cam_id: str,
    amp: float = 10.0,
    repr_depth: float = 15.0,
    rng: Optional[np.random.Generator] = None,
) -> Image.Image:
    """
    对 PIL ref 图做几何扰动. 失败 (标定缺失 / 不识别的 cam) 时原样返回.

    Args:
        ref_img_pil: 输入 ref 图 (PIL.Image)
        cam_id: "cam0" / "cam2" / ... / "cam7"
        amp: 幅度倍率, 1.0 = 三车实测半幅; 训练默认 10
        repr_depth: 代表性深度 (m), 把 Δx/Δy/Δz 近似为像素 shift+scale
        rng: 可选 np.random.Generator; 默认 np.random.default_rng()

    Returns:
        扰动后的 PIL.Image (RGB)
    """
    if ref_img_pil is None:
        return ref_img_pil
    if rng is None:
        rng = np.random.default_rng()
    W, H = ref_img_pil.size
    H_mat = _sample_homography(cam_id, W, H, amp=amp, repr_depth=repr_depth, rng=rng)
    if H_mat is None:
        return ref_img_pil
    arr_rgb = np.array(ref_img_pil.convert("RGB"))
    arr_bgr = arr_rgb[:, :, ::-1].copy()
    warped_bgr = cv2.warpPerspective(
        arr_bgr,
        H_mat,
        (W, H),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )
    warped_rgb = warped_bgr[:, :, ::-1]
    return Image.fromarray(warped_rgb)
