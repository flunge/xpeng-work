from typing import Any, Dict
import os
from pathlib import Path
import cv2
import numpy as np
from typing import Optional


CAM_QUALITY_THRESHOLDS_DAY = {
    "cam0": {"psnr_min": 23.0, "ssim_min": 0.78, "lpips_max": 0.35},
    "cam2": {"psnr_min": 20.0, "ssim_min": 0.65, "lpips_max": 0.5},
    "cam3": {"psnr_min": 20.5, "ssim_min": 0.70, "lpips_max": 0.45},
    "cam4": {"psnr_min": 20.5, "ssim_min": 0.70, "lpips_max": 0.45},
    "cam5": {"psnr_min": 20.5, "ssim_min": 0.70, "lpips_max": 0.45},
    "cam6": {"psnr_min": 20.5, "ssim_min": 0.70, "lpips_max": 0.45},
    "cam7": {"psnr_min": 20.0, "ssim_min": 0.60, "lpips_max": 0.6},
}

CAM_QUALITY_THRESHOLDS_NIGHT = {
    "cam0": {"psnr_min": 23.5, "ssim_min": 0.80, "lpips_max": 0.3},
    "cam2": {"psnr_min": 21.0, "ssim_min": 0.70, "lpips_max": 0.45},
    "cam3": {"psnr_min": 22.5, "ssim_min": 0.75, "lpips_max": 0.4},
    "cam4": {"psnr_min": 22.5, "ssim_min": 0.75, "lpips_max": 0.4},
    "cam5": {"psnr_min": 22.5, "ssim_min": 0.75, "lpips_max": 0.4},
    "cam6": {"psnr_min": 22.5, "ssim_min": 0.75, "lpips_max": 0.4},
    "cam7": {"psnr_min": 21.0, "ssim_min": 0.60, "lpips_max": 0.55},
}

def classify_scene(
    clip_path: str,
    sky_v_day_min: Optional[float] = None,
    full_v_day_min: Optional[float] = None,
) -> str:
    _sky_label = 27
    _min_sky_pixels = 500
    _default_sky_thr = 70.0
    _default_full_thr = 55.0

    sky_thr = sky_v_day_min if sky_v_day_min is not None else _default_sky_thr
    full_thr = full_v_day_min if full_v_day_min is not None else _default_full_thr

    def _pick_first_png(folder: Path) -> Optional[Path]:
        if not folder.is_dir():
            return None
        names = sorted(
            f for f in os.listdir(folder) if f.endswith(".png")
        )
        if not names:
            return None
        return folder / names[0]

    def _read_rgb(path: Path) -> np.ndarray:
        bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if bgr is None:
            raise FileNotFoundError(str(path))
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    def _read_seg(path: Path) -> np.ndarray:
        s = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if s is None:
            raise FileNotFoundError(str(path))
        if s.ndim == 3:
            s = s[..., 0]
        return np.asarray(s)

    def _value_channel(rgb: np.ndarray) -> np.ndarray:
        return np.max(rgb.astype(np.float32), axis=-1)

    case_dir = Path(clip_path).resolve()
    img_dir = case_dir / "images/cam0"
    seg_dir = case_dir / "segs/cam0"

    img_path: Optional[Path] = None
    seg_path: Optional[Path] = None
    stem: Optional[str] = None

    cand_img = _pick_first_png(img_dir)
    if cand_img is not None:
        img_path = cand_img
        stem = img_path.stem
        cand_seg = seg_dir / f"{stem}.png"
        if cand_seg.is_file():
            seg_path = cand_seg

    if img_path is None:
        seg_only = _pick_first_png(seg_dir)
        if seg_only is not None:
            stem = seg_only.stem
            cand_img2 = img_dir / f"{stem}.png"
            if cand_img2.is_file():
                img_path = cand_img2
                seg_path = seg_only

    if img_path is None or not img_path.is_file():
        print("Warning: No image found in the clip path in classify scene")
        return "day"

    rgb = _read_rgb(img_path)
    v = _value_channel(rgb)
    full_mean_v = float(v.mean())

    sky_mean_v: Optional[float] = None

    if seg_path is not None and seg_path.is_file():
        try:
            seg = _read_seg(seg_path)
            if seg.shape[:2] == rgb.shape[:2]:
                sky = seg == _sky_label
                if int(sky.sum()) >= _min_sky_pixels:
                    sky_mean_v = float(v[sky].mean())
        except OSError:
            pass

    if sky_mean_v is not None:
        return "day" if sky_mean_v >= sky_thr else "night"

    return "day" if full_mean_v >= full_thr else "night"


def get_render_check_status(clip_path: str, mean_metrics: Dict[str, Dict[str, Any]]) -> str:
    scene_res = classify_scene(clip_path)
    print("====Scene Result====", scene_res)

    if scene_res == "day":
        cam_quality_thresholds = CAM_QUALITY_THRESHOLDS_DAY
    elif scene_res == "night":
        cam_quality_thresholds = CAM_QUALITY_THRESHOLDS_NIGHT
    else:
        print("====False Scene Result====")
        cam_quality_thresholds = CAM_QUALITY_THRESHOLDS_DAY

    threshold_miss_count_per_cam = {}
    for cam, metrics in mean_metrics.items():
        if cam not in cam_quality_thresholds:
            continue
        miss_count = 0
        thresholds = cam_quality_thresholds[cam]
        psnr = metrics.get("psnr_mean")
        ssim = metrics.get("ssim_mean")
        lpips = metrics.get("lpips_mean")
        if psnr is not None and psnr < thresholds["psnr_min"]:
            miss_count += 1
        if ssim is not None and ssim < thresholds["ssim_min"]:
            miss_count += 1
        if lpips is not None and lpips > thresholds["lpips_max"]:
            miss_count += 1
        threshold_miss_count_per_cam[cam] = miss_count

    print("====Threshold Miss Count Per Cam====", threshold_miss_count_per_cam)
    cams_with_2_miss = [cam for cam, miss in threshold_miss_count_per_cam.items() if miss >= 2]
    print("====Cams with 2 miss====", cams_with_2_miss)
    if len(cams_with_2_miss) >= 3:
        return "FAIL"
    return "PASS"
