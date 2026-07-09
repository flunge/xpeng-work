import os
import numpy as np
import json
import cv2
import time
import torch
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

SUPPORTED_DEPTH_EXTS = ('.npy', '.pfm')


def load_pfm_map(pfm_path):
    def _next_non_comment_line(fobj):
        line = fobj.readline().decode('ascii', errors='ignore')
        while line and (line.strip().startswith('#') or len(line.strip()) == 0):
            line = fobj.readline().decode('ascii', errors='ignore')
        return line.strip()

    with open(pfm_path, 'rb') as f:
        header = f.readline().decode('ascii', errors='ignore').strip()
        if header not in ('PF', 'Pf'):
            raise ValueError(f'Unsupported PFM header "{header}" in {pfm_path}')
        dims_line = _next_non_comment_line(f)
        try:
            width, height = map(int, dims_line.split())
        except Exception as exc:
            raise ValueError(f'Invalid PFM dimensions line "{dims_line}" in {pfm_path}') from exc
        scale_line = _next_non_comment_line(f)
        scale = float(scale_line)
        endian = '<' if scale < 0 else '>'
        channels = 3 if header == 'PF' else 1
        data = np.fromfile(f, endian + 'f4')
        expected_size = width * height * channels
        if data.size != expected_size:
            raise ValueError(f'PFM data size mismatch for {pfm_path}: expected {expected_size}, got {data.size}')
        data = data.reshape((height, width, channels))
        data = np.flipud(data)
        if channels == 1:
            data = data[..., 0]
        full = data.astype(np.float32)
        mask = np.isfinite(full) & (full > 0)
        return full, mask


def load_map_auto(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == '.pfm':
        return load_pfm_map(path)
    raise ValueError(f'Unsupported depth/conf map format: {path}')


def parse_cam_txt(cam_txt_path):
    with open(cam_txt_path, 'r') as f:
        lines = [l.strip() for l in f.readlines() if len(l.strip()) > 0]

    # find headers
    try:
        extrinsic_idx = lines.index('extrinsic')
        intrinsic_idx = lines.index('intrinsic')
    except ValueError:
        raise Exception(f'Invalid camera file format: {cam_txt_path}')

    # parse extrinsic 4x4 (next 4 lines)
    E = []
    for i in range(extrinsic_idx + 1, extrinsic_idx + 5):
        E.append([float(x) for x in lines[i].split()])
    E = np.array(E, dtype=np.float64)

    # parse intrinsic 3x3 (next 3 lines)
    K = []
    for i in range(intrinsic_idx + 1, intrinsic_idx + 4):
        K.append([float(x) for x in lines[i].split()])
    K = np.array(K, dtype=np.float64)

    # optional distortion on the last line (4 floats), ignore if missing
    dist = np.array([0.0, 0.0, 0.0, 0.0], dtype=np.float64)
    if len(lines) >= intrinsic_idx + 5:
        last = [float(x) for x in lines[intrinsic_idx + 4].split()]
        if len(last) == 4:
            dist = np.array(last, dtype=np.float64)

    return K, E, dist


def _extract_from_dict(data, keys, name):
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    raise KeyError(f"Missing {name} (searched keys {keys}) in calibration info")


def _build_intrinsic_from_calib(calib_info, cam_name, depth_shape):
    if calib_info is None or cam_name is None:
        raise ValueError("calib_info and cam_name are required when camera txt is missing")
    if depth_shape is None:
        raise ValueError("depth_shape is required when camera txt is missing")
    if len(depth_shape) != 2:
        raise ValueError(f"depth_shape must be (H, W), got {depth_shape}")
    if cam_name not in calib_info:
        raise KeyError(f"Camera {cam_name} not found in calibration info")

    cam_cfg = calib_info[cam_name]
    intrinsic_cfg = cam_cfg.get('intrinsic', {})
    vision_rgb_wh = calib_info["cam_image_size"][cam_name]

    fx = float(_extract_from_dict(intrinsic_cfg, ['fx', 'focal_length_x', 'focal_length'], 'fx'))
    fy = float(_extract_from_dict(intrinsic_cfg, ['fy', 'focal_length_y', 'focal_length'], 'fy'))
    cx = float(_extract_from_dict(intrinsic_cfg, ['cx'], 'cx'))
    cy = float(_extract_from_dict(intrinsic_cfg, ['cy'], 'cy'))
    image_width = vision_rgb_wh[1]
    image_height = vision_rgb_wh[0]

    matching_height, matching_width = depth_shape
    matching_width = float(matching_width)
    matching_height = float(matching_height)

    K = torch.eye(4, dtype=torch.float32)
    K[0, 0] = fx
    K[1, 1] = fy
    K[0, 2] = cx
    K[1, 2] = cy

    K_matching = K.clone()
    K_matching[0] *= matching_width / image_width
    K_matching[1] *= matching_height / image_height

    return (
        K_matching[:3, :3].cpu().numpy().astype(np.float64),
        np.eye(4, dtype=np.float64),
        np.zeros(4, dtype=np.float64),
    )


def read_cam_for_npy(npy_path, cams_dir, cam_name=None, calib_info=None, depth_shape=None):
    stem = os.path.splitext(os.path.basename(npy_path))[0]
    cam_txt_path = os.path.join(cams_dir, f'{stem}_cam.txt')
    if os.path.exists(cam_txt_path):
        return parse_cam_txt(cam_txt_path)
    return _build_intrinsic_from_calib(calib_info, cam_name, depth_shape)


def reproject_to_new_intrinsics_torch(depth_img, conf_img, K_src, K_dst, out_size=None, device=None, K_src_inv_np=None):
    assert depth_img.ndim == 2, 'depth_img must be HxW'
    assert conf_img.ndim == 2, 'conf_img must be HxW'

    if device is None:
        device = 'cuda' if torch.cuda.is_available() else 'cpu'

    h, w = depth_img.shape
    if out_size is None:
        out_h, out_w = h, w
    else:
        out_w, out_h = int(out_size[0]), int(out_size[1])

    with torch.no_grad():
        # tensors
        depth_t = torch.from_numpy(depth_img.astype(np.float32)).to(device)
        conf_t = torch.from_numpy(conf_img.astype(np.float32)).to(device)
        # compute inverse on CPU to avoid CUDA lazy wrapper in multi-thread
        K_src_np = np.asarray(K_src, dtype=np.float32)
        K_dst_np = np.asarray(K_dst, dtype=np.float32)
        if K_src_inv_np is None:
            K_src_inv_np = np.linalg.inv(K_src_np)
        K_src_inv_t = torch.from_numpy(K_src_inv_np).to(device)
        K_dst_t = torch.from_numpy(K_dst_np).to(device)

        # valid
        valid_src = torch.isfinite(depth_t) & (depth_t > 0)
        ys, xs = torch.where(valid_src)
        if xs.numel() == 0:
            return (torch.zeros((out_h, out_w), device=device, dtype=torch.float32).cpu().numpy(),
                    torch.zeros((out_h, out_w), device=device, dtype=torch.float32).cpu().numpy(),
                    torch.zeros((out_h, out_w), device=device, dtype=torch.bool).cpu().numpy())

        zs = depth_t[ys, xs]  # (N)
        ones = torch.ones_like(zs)
        pixels = torch.stack([xs.float(), ys.float(), ones], dim=0)  # 3xN

        # back-project and project
        rays = K_src_inv_t @ pixels  # 3xN
        points = rays * zs  # 3xN
        proj = K_dst_t @ points
        us = proj[0, :] / (proj[2, :] + 1e-8)
        vs = proj[1, :] / (proj[2, :] + 1e-8)

        u_i = torch.round(us).long()
        v_i = torch.round(vs).long()

        inb = (u_i >= 0) & (u_i < out_w) & (v_i >= 0) & (v_i < out_h)
        if not inb.any():
            return (torch.zeros((out_h, out_w), device=device, dtype=torch.float32).cpu().numpy(),
                    torch.zeros((out_h, out_w), device=device, dtype=torch.float32).cpu().numpy(),
                    torch.zeros((out_h, out_w), device=device, dtype=torch.bool).cpu().numpy())

        u_i = u_i[inb]
        v_i = v_i[inb]
        zs = zs[inb]
        conf_vals = conf_t[ys[inb], xs[inb]]

        flat_idx = v_i * out_w + u_i  # (N)

        # depth min per pixel via scatter_reduce
        inf_val = torch.finfo(torch.float32).max
        depth_out_flat = torch.full((out_h * out_w,), inf_val, device=device, dtype=torch.float32)
        depth_out_flat.scatter_reduce_(0, flat_idx, zs, reduce='amin', include_self=True)
        mask_out_flat = depth_out_flat < inf_val

        # confidence corresponding to min depth: use amax on masked values
        neg_inf = -torch.finfo(torch.float32).max
        equal_min = torch.isclose(zs, depth_out_flat[flat_idx], rtol=0.0, atol=1e-6)
        conf_scatter_vals = torch.where(equal_min, conf_vals, torch.full_like(conf_vals, neg_inf))
        conf_out_flat = torch.full((out_h * out_w,), 0.0, device=device, dtype=torch.float32)
        conf_out_flat.scatter_reduce_(0, flat_idx, conf_scatter_vals, reduce='amax', include_self=True)
        # where not set (remain 0) but mask false doesn't matter

        depth_out = depth_out_flat.view(out_h, out_w).cpu().numpy()
        conf_out = conf_out_flat.view(out_h, out_w).cpu().numpy()
        mask_out = mask_out_flat.view(out_h, out_w).cpu().numpy()

        return depth_out, conf_out, mask_out


def _save_map_npy(out_path, full_map, mask):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    if full_map.ndim == 2:
        values = full_map[mask]
    elif full_map.ndim == 3:
        h, w, c = full_map.shape
        values = full_map[mask.reshape(h, w), :]
    else:
        raise Exception('full_map must be HxW or HxWxC')
    np.save(out_path, {'mask': mask, 'value': values})


def _resolve_timestamp(ts_map, cam_name, slice_index, default_name=None):
    # dict by cam -> (dict or list)
    if isinstance(ts_map, dict):
        cam_map = ts_map.get(cam_name, None)
        if cam_map is None:
            return default_name
        # dict with keys like 'slice0'
        if isinstance(cam_map, dict):
            key = f"slice{slice_index}"
            return cam_map.get(key, default_name)
        # list where index is slice_index
        if isinstance(cam_map, (list, tuple)):
            if 0 <= slice_index < len(cam_map):
                return cam_map[slice_index]
            return default_name
        return default_name
    # top-level list
    if isinstance(ts_map, (list, tuple)):
        if 0 <= slice_index < len(ts_map):
            return ts_map[slice_index]
        return default_name


def batch_reproject_dir(
        depth_dir, conf_dir, cams_dir, transform_json, slice_to_ts_map,
        out_depth_dir, out_conf_dir, n_jobs=8, max_gpu_workers=2,
        use_conf=True, calib_info=None
    ):
    sensor_params = transform_json['sensor_params']
    if use_conf and conf_dir is None:
        raise ValueError("conf_dir must be provided when use_conf=True")
    if use_conf and out_conf_dir is None:
        raise ValueError("out_conf_dir must be provided when use_conf=True")
    files = [
        f for f in os.listdir(depth_dir)
        if os.path.splitext(f)[1].lower() in SUPPORTED_DEPTH_EXTS
    ]
    files.sort()

    total = len(files)
    if total == 0:
        raise ValueError(f"No depth files found in {depth_dir}")

    # split files into 7 parts, assert 7 parts are equal
    if total % 7 == 0:
        cam_order = ['cam0', 'cam2', 'cam3', 'cam4', 'cam5', 'cam6', 'cam7']
    elif total % 6 == 0:
        cam_order = ['cam2', 'cam3', 'cam4', 'cam5', 'cam6', 'cam7']
    else:
        raise ValueError(f"Total number of files must be divisible by 7 or 6")

    num_cams = len(cam_order)
    chunk_size = total // num_cams
    chunk_starts = [i * chunk_size for i in range(num_cams)]

    def file_cam_index(idx):
        # map file index -> chunk index
        for j in range(num_cams):
            start = chunk_starts[j]
            end = start + chunk_size
            if start <= idx < end:
                return j
        return num_cams - 1

    # optional: load slice->timestamp map
    ts_map = None
    if isinstance(slice_to_ts_map, str):
        with open(slice_to_ts_map, 'r') as f:
            ts_map = json.load(f)
    else:
        ts_map = slice_to_ts_map

    # build tasks with assigned camera per file index
    tasks = []
    for idx, fname in enumerate(files):
        cam_name = cam_order[file_cam_index(idx)]
        if cam_name not in sensor_params:
            raise ValueError(f"[ERROR] Camera {cam_name} not in sensor_params, skip {fname}")
        tasks.append((idx, fname, cam_name))

    gpu_sem = threading.Semaphore(max(1, int(max_gpu_workers)))

    def process_one(idx, fname, cam_name):
        depth_path = os.path.join(depth_dir, fname)
        stem = os.path.splitext(fname)[0]
        cam_txt = os.path.join(cams_dir, f"{stem}_cam.txt")

        depth_img, _ = load_map_auto(depth_path)
        if use_conf:
            conf_path = os.path.join(conf_dir, fname)
            if not os.path.exists(conf_path):
                raise FileNotFoundError(f"Confidence file not found: {conf_path}")
            conf_img, _ = load_map_auto(conf_path)
        else:
            conf_img = np.ones_like(depth_img, dtype=np.float32)

        K_src, _, _ = read_cam_for_npy(
            depth_path,
            cams_dir,
            cam_name=cam_name,
            calib_info=calib_info,
            depth_shape=depth_img.shape,
        )
        K_src_inv_np = np.linalg.inv(np.asarray(K_src, dtype=np.float32))

        K_dst = np.array(sensor_params[cam_name]['camera_intrinsic'], dtype=np.float64)
        out_w = int(sensor_params[cam_name]['width'])
        out_h = int(sensor_params[cam_name]['height'])
        out_size = (out_w, out_h)

        with gpu_sem:
            depth_out, conf_out, mask_out = reproject_to_new_intrinsics_torch(
                depth_img, conf_img, K_src, K_dst, out_size=out_size, K_src_inv_np=K_src_inv_np
            )

        # decide output file name by timestamp if mapping provided
        cam_idx = file_cam_index(idx)
        local_index = idx - chunk_starts[cam_idx]
        ts_val = _resolve_timestamp(ts_map, cam_name, local_index, None) if ts_map is not None else None
        out_name = f"{ts_val}.npy" if ts_val is not None else fname

        out_depth_path = os.path.join(out_depth_dir, cam_name, out_name)
        _save_map_npy(out_depth_path, depth_out, mask_out)
        if use_conf:
            out_conf_path = os.path.join(out_conf_dir, cam_name, out_name)
            _save_map_npy(out_conf_path, conf_out, mask_out)
        return cam_name

    start_t = time.time()
    cam_last_log = None
    with ThreadPoolExecutor(max_workers=max(1, int(n_jobs))) as ex:
        futures = [ex.submit(process_one, idx, fname, cam_name) for (idx, fname, cam_name) in tasks]
        for fut in as_completed(futures):
            cam_name = fut.result()
            if cam_name != cam_last_log:
                if cam_last_log is not None:
                    print(f"[INFO] Switched from {cam_last_log} in {time.time() - start_t:.2f}s")
                cam_last_log = cam_name
                start_t = time.time()


if __name__ == "__main__":
    from depth_conf_visualize import (
        visualize_reprojected_batch,
        visualize_pngs_to_video,
    )
    base_dir = "/workspace/yangxh7@xiaopeng.com/datasets/xpeng/vision_depth/c-f2c458ae-51e7-3ca6-8738-fb5858651a80/"
    depth_dir = os.path.join(base_dir, "mvsnet_depth_est")
    conf_dir = os.path.join(base_dir, "confidence_npy")
    cams_dir = os.path.join(base_dir, "cams")
    
    transform_path = os.path.join(base_dir, "transform.json")
    transform_json = json.load(open(transform_path, "r"))

    calib_info = os.path.join(base_dir, "misc/mvsnet/mvsnet_calib.json")
    calib_info = json.load(open(calib_info, "r"))

    slice_to_ts_map = os.path.join(base_dir, "misc/mvsnet/mvsnet_image_timestamps.json")
    slice_to_ts_map = json.load(open(slice_to_ts_map, "r"))

    out_depth_dir = os.path.join(base_dir, "depth")
    out_conf_dir = os.path.join(base_dir, "conf")

    # batch_reproject_dir(
    #     depth_dir, conf_dir, cams_dir,
    #     transform_json, slice_to_ts_map, out_depth_dir, out_conf_dir,
    #     calib_info=calib_info, use_conf=False
    # )
    
    origin_img_root = os.path.join(base_dir, "images")
    out_png_root = os.path.join(base_dir, "reproject_images")
    # visualize_reprojected_batch(
    #     out_depth_dir, out_conf_dir, origin_img_root, out_png_root,
    #     cams=["cam2", "cam3", "cam4", "cam5", "cam6", "cam7"],
    #     use_conf=False,
    # )
    visualize_pngs_to_video(
        out_png_root,
        cams=["cam2", "cam3", "cam4", "cam5", "cam6", "cam7"],
        video_root=os.path.join(base_dir, "reproject_videos"),
    )

    
