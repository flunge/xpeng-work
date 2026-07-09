import os
import numpy as np
import cv2
import shutil
import subprocess


def load_npy_map(npy_path):
    npy_obj = np.load(npy_path, allow_pickle=True).tolist()
    mask = npy_obj['mask']
    values = npy_obj['value']
    if mask.ndim != 2:
        raise Exception('mask must be 2D')
    h, w = mask.shape
    full = np.zeros((h, w), dtype=np.float32)
    full[mask] = values.astype(np.float32)
    return full, mask


def visualize_reprojected_and_save(
        depth_npy_path,
        conf_npy_path,
        origin_img_path,
        out_png_path,
        depth_min_m=0.0,
        depth_max_m=100.0,
        alpha=0.8,
        colormap_depth='turbo',
        colormap_conf='jet',
        draw_colorbar=True,
        use_conf=True,
    ):
    depth_img, _ = load_npy_map(depth_npy_path)
    conf_img = None
    if use_conf:
        if conf_npy_path is None:
            raise ValueError("conf_npy_path must be provided when use_conf=True")
        conf_img, _ = load_npy_map(conf_npy_path)
    img = cv2.imread(origin_img_path, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"Failed to read origin image: {origin_img_path}")

    def overlay_depth(depth, base_img):
        valid = np.isfinite(depth)
        if not np.any(valid):
            normalized = np.zeros_like(depth, dtype=np.float32)
        else:
            dmin = float(depth_min_m)
            dmax = float(depth_max_m)
            denom = (dmax - dmin) if (dmax - dmin) > 1e-8 else 1.0
            normalized = (depth - dmin) / denom
            normalized = np.clip(normalized, 0.0, 1.0)
            normalized[~valid] = 0.0

        try:
            from matplotlib import cm
            cmap = cm.get_cmap(colormap_depth)
            colored = (cmap(normalized)[..., :3] * 255.0).astype(np.uint8)
            colored = cv2.cvtColor(colored, cv2.COLOR_RGB2BGR)
        except Exception:
            norm_8u = (normalized * 255.0).round().astype(np.uint8)
            cmap_map = {
                'turbo': getattr(cv2, 'COLORMAP_TURBO', cv2.COLORMAP_JET),
                'jet': cv2.COLORMAP_JET,
                'viridis': getattr(cv2, 'COLORMAP_VIRIDIS', cv2.COLORMAP_JET),
                'plasma': getattr(cv2, 'COLORMAP_PLASMA', cv2.COLORMAP_JET),
                'inferno': getattr(cv2, 'COLORMAP_INFERNO', cv2.COLORMAP_JET),
                'magma': getattr(cv2, 'COLORMAP_MAGMA', cv2.COLORMAP_JET),
            }
            colored = cv2.applyColorMap(norm_8u, cmap_map.get(colormap_depth, cmap_map['turbo']))

        if colored.shape[:2] != base_img.shape[:2]:
            colored = cv2.resize(colored, (base_img.shape[1], base_img.shape[0]))
        overlay = cv2.addWeighted(base_img, 1.0 - float(alpha), colored, float(alpha), 0)

        if draw_colorbar:
            pad = 10
            legend_w = min(256, overlay.shape[1] - 2 * pad)
            legend_h = 24
            x0 = overlay.shape[1] - legend_w - pad
            y0 = overlay.shape[0] - legend_h - pad

            roi = overlay[y0:y0 + legend_h, x0:x0 + legend_w].copy()
            bg = np.zeros_like(roi)
            blended_bg = cv2.addWeighted(roi, 0.4, bg, 0.6, 0)
            overlay[y0:y0 + legend_h, x0:x0 + legend_w] = blended_bg

            grad = np.linspace(0.0, 1.0, legend_w, dtype=np.float32)
            grad = np.tile(grad, (legend_h, 1))

            try:
                from matplotlib import cm
                cmap = cm.get_cmap(colormap_depth)
                legend_img = (cmap(grad)[..., :3] * 255.0).astype(np.uint8)
                legend_img = cv2.cvtColor(legend_img, cv2.COLOR_RGB2BGR)
            except Exception:
                grad_8u = (grad * 255.0).round().astype(np.uint8)
                cmap_map = {
                    'turbo': getattr(cv2, 'COLORMAP_TURBO', cv2.COLORMAP_JET),
                    'jet': cv2.COLORMAP_JET,
                    'viridis': getattr(cv2, 'COLORMAP_VIRIDIS', cv2.COLORMAP_JET),
                    'plasma': getattr(cv2, 'COLORMAP_PLASMA', cv2.COLORMAP_JET),
                    'inferno': getattr(cv2, 'COLORMAP_INFERNO', cv2.COLORMAP_JET),
                    'magma': getattr(cv2, 'COLORMAP_MAGMA', cv2.COLORMAP_JET),
                }
                legend_img = cv2.applyColorMap(grad_8u, cmap_map.get(colormap_depth, cmap_map['turbo']))

            overlay[y0:y0 + legend_h, x0:x0 + legend_w] = legend_img

            tick_color = (255, 255, 255)
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.4
            thickness = 1
            tick_values = [0.0, 0.5, 1.0]
            tick_labels = [
                f"{depth_min_m:.0f}m",
                f"{(depth_min_m + 0.5 * (depth_max_m - depth_min_m)):.0f}m",
                f"{depth_max_m:.0f}m",
            ]
            for t, txt in zip(tick_values, tick_labels):
                tx = x0 + int(t * (legend_w - 1))
                ty = y0 - 3
                cv2.line(overlay, (tx, y0 - 2), (tx, y0 - 6), tick_color, 1)
                (tw, _), _ = cv2.getTextSize(txt, font, font_scale, thickness)
                tx_text = min(max(tx - tw // 2, 0), overlay.shape[1] - tw)
                cv2.putText(overlay, txt, (tx_text, ty), font, font_scale, tick_color, thickness, cv2.LINE_AA)

        return overlay

    def overlay_conf(conf, base_img):
        conf = conf.astype(np.float32)
        conf = np.nan_to_num(conf, nan=0.0, posinf=0.0, neginf=0.0)
        normalized = np.clip(conf, 0.0, 1.0)
        try:
            from matplotlib import cm
            cmap = cm.get_cmap(colormap_conf)
            colored = (cmap(normalized)[..., :3] * 255.0).astype(np.uint8)
            colored = cv2.cvtColor(colored, cv2.COLOR_RGB2BGR)
        except Exception:
            norm_8u = (normalized * 255.0).round().astype(np.uint8)
            if colormap_conf.lower() == 'jet':
                colored = cv2.applyColorMap(norm_8u, cv2.COLORMAP_JET)
            else:
                colored = cv2.applyColorMap(norm_8u, cv2.COLORMAP_JET)

        if colored.shape[:2] != base_img.shape[:2]:
            colored = cv2.resize(colored, (base_img.shape[1], base_img.shape[0]))
        overlay = cv2.addWeighted(base_img, 1.0 - float(alpha), colored, float(alpha), 0)

        if draw_colorbar:
            pad = 10
            legend_w = min(256, overlay.shape[1] - 2 * pad)
            legend_h = 24
            x0 = overlay.shape[1] - legend_w - pad
            y0 = overlay.shape[0] - legend_h - pad

            roi = overlay[y0:y0 + legend_h, x0:x0 + legend_w].copy()
            bg = np.zeros_like(roi)
            blended_bg = cv2.addWeighted(roi, 0.4, bg, 0.6, 0)
            overlay[y0:y0 + legend_h, x0:x0 + legend_w] = blended_bg

            grad = np.linspace(0.0, 1.0, legend_w, dtype=np.float32)
            grad = np.tile(grad, (legend_h, 1))

            try:
                from matplotlib import cm
                cmap = cm.get_cmap(colormap_conf)
                legend_img = (cmap(grad)[..., :3] * 255.0).astype(np.uint8)
                legend_img = cv2.cvtColor(legend_img, cv2.COLOR_RGB2BGR)
            except Exception:
                grad_8u = (grad * 255.0).round().astype(np.uint8)
                legend_img = cv2.applyColorMap(grad_8u, cv2.COLORMAP_JET)

            overlay[y0:y0 + legend_h, x0:x0 + legend_w] = legend_img

            tick_color = (255, 255, 255)
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.4
            thickness = 1
            for t, txt in zip([0.0, 0.5, 1.0], ['0', '0.5', '1']):
                tx = x0 + int(t * (legend_w - 1))
                ty = y0 - 3
                cv2.line(overlay, (tx, y0 - 2), (tx, y0 - 6), tick_color, 1)
                (tw, _), _ = cv2.getTextSize(txt, font, font_scale, thickness)
                tx_text = min(max(tx - tw // 2, 0), overlay.shape[1] - tw)
                cv2.putText(overlay, txt, (tx_text, ty), font, font_scale, tick_color, thickness, cv2.LINE_AA)

        return overlay

    depth_overlay = overlay_depth(depth_img, img)
    overlays = [depth_overlay]
    if conf_img is not None:
        conf_overlay = overlay_conf(conf_img, img)
        overlays.append(conf_overlay)
        concat = np.concatenate(overlays, axis=1)
    else:
        concat = depth_overlay
    os.makedirs(os.path.dirname(out_png_path), exist_ok=True)
    cv2.imwrite(out_png_path, concat)


def visualize_reprojected_batch(
        depth_npy_root,
        conf_npy_root,
        origin_img_root,
        out_png_root,
        cams=("cam0", "cam2", "cam3", "cam4", "cam5", "cam6", "cam7"),
        depth_min_m=0.0,
        depth_max_m=100.0,
        alpha=0.8,
        colormap_depth='turbo',
        colormap_conf='jet',
        draw_colorbar=True,
        use_conf=True,
    ):
    if use_conf and conf_npy_root is None:
        raise ValueError("conf_npy_root must be provided when use_conf=True")

    for cam in cams:
        depth_cam_dir = os.path.join(depth_npy_root, cam)
        conf_cam_dir = os.path.join(conf_npy_root, cam) if (conf_npy_root is not None) else None
        if not os.path.isdir(depth_cam_dir):
            print(f"[WARN] Missing depth dir: {depth_cam_dir}, skip cam {cam}")
            continue
        if use_conf:
            if not os.path.isdir(conf_cam_dir):
                print(f"[WARN] Missing conf dir: {conf_cam_dir}, skip cam {cam}")
                continue
        else:
            conf_cam_dir = None

        out_cam_dir = os.path.join(out_png_root, cam)
        os.makedirs(out_cam_dir, exist_ok=True)

        npy_files = sorted([f for f in os.listdir(depth_cam_dir) if f.endswith('.npy')])
        for fname in npy_files:
            ts = os.path.splitext(fname)[0]
            depth_path = os.path.join(depth_cam_dir, fname)
            conf_path = os.path.join(conf_cam_dir, fname) if conf_cam_dir is not None else None
            origin_img_path = os.path.join(origin_img_root, cam, f"{ts}.png")
            out_png_path = os.path.join(out_cam_dir, f"{ts}.png")

            if use_conf and not os.path.exists(conf_path):
                print(f"[WARN] Missing conf file: {conf_path}, skip")
                continue
            if not os.path.exists(origin_img_path):
                print(f"[WARN] Missing origin image: {origin_img_path}, skip")
                continue

            try:
                visualize_reprojected_and_save(
                    depth_npy_path=depth_path,
                    conf_npy_path=conf_path,
                    origin_img_path=origin_img_path,
                    out_png_path=out_png_path,
                    depth_min_m=depth_min_m,
                    depth_max_m=depth_max_m,
                    alpha=alpha,
                    colormap_depth=colormap_depth,
                    colormap_conf=colormap_conf,
                    draw_colorbar=draw_colorbar,
                    use_conf=use_conf,
                )
            except Exception as e:
                print(f"[WARN] Failed to visualize {cam}/{ts}: {e}")


def visualize_pngs_to_video(
        out_png_root,
        cams=("cam0", "cam2", "cam3", "cam4", "cam5", "cam6", "cam7"),
        video_root=None,
        fps=10.0,
        codec=None,
    ):
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found in PATH, please install ffmpeg to create videos")

    if video_root is None:
        video_root = os.path.join(out_png_root, "videos")
    os.makedirs(video_root, exist_ok=True)

    for cam in cams:
        cam_png_dir = os.path.join(out_png_root, cam)
        if not os.path.isdir(cam_png_dir):
            print(f"[WARN] Missing visualization dir: {cam_png_dir}, skip cam {cam}")
            continue

        png_files = sorted([f for f in os.listdir(cam_png_dir) if f.lower().endswith('.png')])
        if not png_files:
            print(f"[WARN] No PNG files found for {cam} in {cam_png_dir}, skip")
            continue

        concat_list_path = os.path.join(video_root, f"{cam}_frames.txt")
        with open(concat_list_path, 'w') as f:
            for png_name in png_files:
                png_path = os.path.join(cam_png_dir, png_name)
                f.write(f"file '{png_path}'\n")

        video_path = os.path.join(video_root, f"{cam}.mp4")
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-r", str(fps),
            "-i", concat_list_path,
        ]
        # 如果未指定 codec，则让 ffmpeg 使用默认编码器，避免某些环境下不存在 libx264 报错
        if codec is not None:
            cmd += ["-c:v", codec]
        cmd += [
            "-pix_fmt", "yuv420p",
            video_path,
        ]
        try:
            subprocess.run(cmd, check=True)
            print(f"[INFO] Saved {cam} video to {video_path}")
        except subprocess.CalledProcessError as exc:
            print(f"[ERROR] ffmpeg failed for {cam}: {exc}")


