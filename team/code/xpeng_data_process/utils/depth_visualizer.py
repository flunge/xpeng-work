import os
import numpy as np
import cv2
from pathlib import Path
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from utils.projection import Projection
from utils.images2video import images2video
from utils.file_utils import get_semantics_from_path, get_mask_from_semantics
from settings.globals import SemanticType


def _load_depth_map_and_mask(npy_path, res_h, res_w, axis=1):
    dimg = np.zeros((res_h, res_w))
    valid = None
    if not os.path.exists(npy_path):
        return dimg, valid
    npy_raw = np.load(npy_path, allow_pickle=True)
    if isinstance(npy_raw, np.ndarray) and npy_raw.dtype == object:
        obj = npy_raw.tolist()
        if isinstance(obj, dict):
            if len(obj['value'].shape) == 1:
                dimg[obj['mask']] = obj['value']
            else:
                dimg[obj['mask']] = obj['value'][:, axis]
                dimg = (dimg + 1) * 50
            valid = obj['mask']
        else:
            arr = np.array(obj)
            if arr.ndim == 2:
                dimg = arr
                valid = (dimg > 0)
    else:
        if isinstance(npy_raw, np.ndarray):
            if npy_raw.ndim == 2:
                dimg = npy_raw
            elif npy_raw.ndim == 3:
                ch = min(axis, npy_raw.shape[2] - 1)
                dimg = npy_raw[:, :, ch]
        valid = (dimg > 0)
    return dimg, valid


def _resize_to_height(img, target_h):
    if img is None or img.size == 0:
        return img
    h, w = img.shape[:2]
    if h == target_h:
        return img
    new_w = max(1, int(round(w * (target_h / float(h)))))
    return cv2.resize(img, (new_w, target_h))


def _pad_to_width(img, target_w):
    h, w = img.shape[:2]
    if w == target_w:
        return img
    pad = max(0, target_w - w)
    return cv2.copyMakeBorder(img, 0, 0, 0, pad, cv2.BORDER_CONSTANT, value=(0, 0, 0))


def render_depth_mosaic(clip_path, transform_json, used_cams, folder_name, output_folder, axis=1, n_jobs=None, log_every=10, stride=1, scale=1.0, use_cuda=False):
    clip_path = Path(clip_path)
    os.makedirs(clip_path / output_folder, exist_ok=True)

    # 1) 根据 transform_json 建立 cam->(ts->frame) 映射
    cam_ts_to_frame = {cam: {} for cam in used_cams}
    for tf in transform_json["frames"]:
        cam = tf.get("camera")
        if cam not in used_cams:
            continue
        ts = str(tf.get("timestamp"))
        cam_ts_to_frame[cam][ts] = tf

    # 2) 扫描 depth npy 获取实际存在的时间戳（子集）
    depth_root = clip_path / folder_name
    ts_set = set()
    for cam in used_cams:
        cam_dir = depth_root / cam
        if not cam_dir.is_dir():
            continue
        for f in os.listdir(cam_dir):
            if f.lower().endswith('.npy'):
                ts_set.add(os.path.splitext(f)[0])

    # 3) 排序并应用 stride
    def _safe_int(x):
        try:
            return int(x)
        except Exception:
            return x
    ts_list_all = sorted(ts_set, key=_safe_int)
    stride = max(1, int(stride))
    ts_list = ts_list_all[::stride]

    total = len(ts_list)
    if n_jobs is None:
        # 默认使用 CPU 核心数，至少 1
        try:
            n_jobs = max(1, int(os.cpu_count() or 4))
        except Exception:
            n_jobs = 4

    scale = float(scale) if scale is not None else 1.0
    if scale <= 0:
        scale = 1.0

    # detect cuda availability lazily
    cuda_ok = False
    if use_cuda:
        try:
            cuda_ok = cv2.cuda.getCudaEnabledDeviceCount() > 0
        except Exception:
            cuda_ok = False

    print(f"[INFO] render_depth_mosaic: total_ts={len(ts_list_all)}, stride={stride} -> run_ts={total}, scale={scale:.2f}, n_jobs={n_jobs}, cuda={cuda_ok}")

    def _resize_img(img, out_w, out_h, is_mask=False):
        if img is None:
            return None
        if img.shape[0] == out_h and img.shape[1] == out_w:
            return img
        interp = cv2.INTER_NEAREST if is_mask else (cv2.INTER_AREA if out_w < img.shape[1] or out_h < img.shape[0] else cv2.INTER_LINEAR)
        if cuda_ok:
            try:
                gpu = cv2.cuda_GpuMat()
                if is_mask and img.dtype != np.uint8:
                    src = (img.astype(np.uint8) * 255) if img.dtype == bool else img.astype(np.uint8)
                else:
                    src = img
                gpu.upload(src)
                resized_gpu = cv2.cuda.resize(gpu, (out_w, out_h), interpolation=interp)
                out = resized_gpu.download()
                if is_mask:
                    out = out > 127
                return out
            except Exception:
                pass
        return cv2.resize(img, (out_w, out_h), interpolation=interp)

    def process_one(ts):
        projection = Projection()
        cam_to_img = {}
        for cam in used_cams:
            res_w = transform_json["sensor_params"][cam]["width"]
            res_h = transform_json["sensor_params"][cam]["height"]
            out_w = max(1, int(round(res_w * scale)))
            out_h = max(1, int(round(res_h * scale)))
            # depth 路径：depth/<cam>/<ts>.npy
            cam_frame = cam_ts_to_frame[cam].get(str(ts), None)
            cam_depth_path = depth_root / cam / f"{ts}.npy"
            if not cam_depth_path.exists():
                cam_to_img[cam] = np.zeros((out_h, out_w, 3), dtype=np.uint8)
                continue
            # 加载深度
            dimage, valid_mask = _load_depth_map_and_mask(str(cam_depth_path), res_h, res_w, axis=axis)
            # 找原图
            if cam_frame is not None:
                origin_image = cv2.imread(str(clip_path / cam_frame['file_path']))
            else:
                origin_image = None
            if origin_image is None:
                origin_image = np.zeros((res_h, res_w, 3), dtype=np.uint8)
            # 语义分割过滤：天空 + 动态障碍（人、车辆）不绘制
            seg_valid_mask = None
            if cam_frame is not None:
                seg_path = clip_path / cam_frame['file_path'].replace('images', 'segs')
                if seg_path.exists():
                    try:
                        semantics = get_semantics_from_path(seg_path)
                        mask_sky = get_mask_from_semantics(semantics, SemanticType.SKY).astype(np.uint8)
                        mask_human = get_mask_from_semantics(semantics, SemanticType.HUMAN).astype(np.uint8)
                        mask_vehicle = get_mask_from_semantics(semantics, SemanticType.VEHICLE).astype(np.uint8)
                        seg_valid_mask = (mask_sky & mask_human & mask_vehicle).astype(bool)
                    except Exception:
                        seg_valid_mask = None
            # downscale for performance
            if scale != 1.0:
                dimage = _resize_img(dimage, out_w, out_h, is_mask=False)
                if valid_mask is None:
                    valid_mask = dimage > 0
                else:
                    valid_mask = _resize_img(valid_mask.astype(np.uint8), out_w, out_h, is_mask=True)
                    valid_mask = valid_mask.astype(bool)
                if seg_valid_mask is not None:
                    seg_valid_mask = _resize_img(seg_valid_mask.astype(np.uint8), out_w, out_h, is_mask=True)
                    seg_valid_mask = seg_valid_mask.astype(bool)
                origin_image = _resize_img(origin_image, out_w, out_h, is_mask=False)
            # 合并语义掩码
            if seg_valid_mask is not None:
                if valid_mask is None:
                    valid_mask = seg_valid_mask
                else:
                    valid_mask = valid_mask & seg_valid_mask
            point_size = 1
            projection.draw_depth_image(origin_image, dimage, point_size, valid_mask=valid_mask)
            cam_to_img[cam] = origin_image

        top_imgs = [cam_to_img.get("cam0"), cam_to_img.get("cam2"), cam_to_img.get("cam7")]
        bot_imgs = [cam_to_img.get("cam3"), cam_to_img.get("cam4"), cam_to_img.get("cam5"), cam_to_img.get("cam6")]

        top_h = max(img.shape[0] for img in top_imgs if img is not None)
        bot_h = max(img.shape[0] for img in bot_imgs if img is not None)
        top_imgs_resized = [_resize_to_height(img, top_h) for img in top_imgs]
        bot_imgs_resized = [_resize_to_height(img, bot_h) for img in bot_imgs]

        row_top = cv2.hconcat(top_imgs_resized)
        row_bot = cv2.hconcat(bot_imgs_resized)

        target_w = max(row_top.shape[1], row_bot.shape[1])
        row_top = _pad_to_width(row_top, target_w)
        row_bot = _pad_to_width(row_bot, target_w)

        mosaic = cv2.vconcat([row_top, row_bot])
        out_name = f"{ts}.png"
        out_path = clip_path / output_folder / out_name
        cv2.imwrite(str(out_path), mosaic)
        return ts

    start_t = time.time()
    processed = 0
    last_log_t = start_t
    with ThreadPoolExecutor(max_workers=max(1, int(n_jobs))) as ex:
        futures = [ex.submit(process_one, ts) for ts in ts_list]
        for fut in as_completed(futures):
            _ = fut.result()
            processed += 1
            if (processed % max(1, int(log_every))) == 0 or processed == total:
                now = time.time()
                dt = now - last_log_t
                overall = now - start_t
                print(f"[INFO] render_depth_mosaic: {processed}/{total} done, last {dt:.2f}s, total {overall:.2f}s")
                last_log_t = now

    print(f"[INFO] Save mosaic images to {clip_path / output_folder} (total {total})")


def export_depth_videos(clip_path, folders=("depth_vis",), dst_suffix="_video", fps=5):
    for folder in folders:
        src_path = os.path.join(clip_path, folder)
        # 情况1：目录结构为 cam*/image.png，使用现有 images2video
        has_cam_dirs = any(("cam" in d and os.path.isdir(os.path.join(src_path, d))) for d in os.listdir(src_path)) if os.path.isdir(src_path) else False
        if has_cam_dirs:
            images2video(src_path, dst_folder=f"{folder}{dst_suffix}", log=False)
            continue

        # 情况2：平铺的 mosaics（*.png）
        out_dir = os.path.join(os.path.dirname(src_path), f"{folder}{dst_suffix}")
        os.makedirs(out_dir, exist_ok=True)
        temp_dir = os.path.join(out_dir, "temp")
        os.makedirs(temp_dir, exist_ok=True)

        files = [f for f in os.listdir(src_path) if f.lower().endswith('.png')]
        if not files:
            print(f"[WARN] export_depth_videos: no png files in {src_path}")
            continue
        # 尝试按数字时间戳排序
        try:
            files_sorted = sorted(files, key=lambda x: int(os.path.splitext(x)[0]))
        except Exception:
            files_sorted = sorted(files)

        # 链接/拷贝为 image-%08d.png 序列
        import shutil
        for i, fname in enumerate(files_sorted):
            dst_name = f"image-{i:08d}.png"
            shutil.copyfile(os.path.join(src_path, fname), os.path.join(temp_dir, dst_name))

        video_name = f"video_mosaic.mp4"
        output_video = os.path.join(clip_path, video_name)
        os.system(f"ffmpeg -y -framerate {int(fps)} -i {temp_dir}/image-%08d.png -c:v mpeg4 -q:v 2 -b:v 5M -pix_fmt yuv420p {output_video}")
        print(f"[DEBUG] Generating {output_video} complete")
        shutil.rmtree(temp_dir)

