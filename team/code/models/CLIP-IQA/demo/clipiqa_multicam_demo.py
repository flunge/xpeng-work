# Copyright (c) OpenMMLab. All rights reserved.
"""
Multi-camera CLIP-IQA evaluation with optional before/after comparison.

Attribute names are read dynamically from the config's classnames.

--- Single mode (default) ---
python demo/clipiqa_multicam_demo.py \\
    --config configs/clipiqa/clipiqa_attribute_test_my.py \\
    --root_path /path/to/before \\
    --compare_path /path/to/after \\
    --output_csv results.csv

--- Batch mode (multiple clip_ids) ---
python demo/clipiqa_multicam_demo.py \\
    --batch \\
    --config configs/clipiqa/clipiqa_attribute_test_my.py \\
    --root_path /path/to/FID_model/ \\
    --compare_path /path/to/FID_output/v3_xxx/ \\
    --output_csv batch_results.csv

Batch directory layout assumed:
  base:    {root_path}/{clip_id}/simulator_render/{side}/redistort_rgb/{cam}/
  compare: {compare_path}/{clip_id}/{side}/{cam}/
"""
import argparse
import os
import re as _re
import tempfile
import json
import time
import hmac as hmac_mod
import hashlib
import requests

import torch
import numpy as np
import pandas as pd
from PIL import Image as _PILImage
from tqdm import tqdm

from mmedit.apis import init_model, restoration_inference


CAM_FOLDERS = ['cam0', 'cam2', 'cam3', 'cam4', 'cam5', 'cam6', 'cam7']
SIDES = ['left', 'right']
IMG_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}

# ──────────────────────────────────────────────
# CloudSim trigger time helper
# ──────────────────────────────────────────────
_SCENARIO_QUERY_URL = 'https://cloudsim.xiaopeng.link/simulation/scenario/query/'
_CLOUDSIM_ACCOUNT = 'cloudsim-engine@xiaopeng.com'
_CLOUDSIM_SECRET = '%mMFcTWlzJOe'
_trigger_time_cache: dict = {}


def _cloudsim_sign_header() -> dict:
    """生成 HMAC-SHA256 签名 header（与 cloudsim_request.py 一致）"""
    app_key = 'simulation-auth'
    version = '1.0'
    sign_message = '/'.join([app_key, version, _CLOUDSIM_ACCOUNT, str(int(time.time() * 1000))])
    hmac_key = _CLOUDSIM_SECRET.encode('utf-8')
    sign = hmac_mod.new(hmac_key, sign_message.encode('utf-8'), hashlib.sha256).hexdigest()
    return {'X-Sign': sign_message + '/' + sign}


def fetch_trigger_time(scenario_id: int) -> int:
    """获取 triggerTime = triggerTimestamp - 2e9，失败返回 0"""
    if scenario_id in _trigger_time_cache:
        return _trigger_time_cache[scenario_id]
    try:
        resp = requests.post(
            _SCENARIO_QUERY_URL,
            headers=_cloudsim_sign_header(),
            files={'id': (None, str(scenario_id))},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get('data', {})
        scenario_str = data.get('scenario', '')
        if not scenario_str:
            print(f'[warn] scenario {scenario_id}: scenario 字段为空，不过滤时间戳')
            return 0
        scenario_obj = json.loads(scenario_str)
        trigger_ts = scenario_obj.get('perfectControllerConfig', {}).get('triggerTimestamp')
        if trigger_ts is None:
            print(f'[warn] scenario {scenario_id}: triggerTimestamp 为空，不过滤')
            return 0
        result = int(trigger_ts) - 2 * 10 ** 9
        print(f'[info] scenario {scenario_id}: triggerTimestamp={trigger_ts}, triggerTime={result}')
        _trigger_time_cache[scenario_id] = result
        return result
    except Exception as e:
        print(f'[warn] 获取 triggerTime 失败 (scenario_id={scenario_id}): {e}')
        return 0


def resolve_trigger_time_from_name(name: str, fallback: int = 0) -> int:
    """如果 name 符合 S<id>-J<id>-T<id> 格式，自动获取 triggerTime；否则返回 fallback"""
    m = _re.match(r'^S(\d+)-J\d+-T\d+', name)
    if m:
        return fetch_trigger_time(int(m.group(1)))
    return fallback



def parse_args():
    parser = argparse.ArgumentParser(
        description='CLIP-IQA multi-camera image quality evaluation')
    parser.add_argument(
        '--config',
        default='configs/clipiqa/clipiqa_attribute_test_my.py',
        help='test config file path')
    parser.add_argument(
        '--checkpoint',
        default=None,
        help='checkpoint file (e.g. iter_80000.pth for CLIP-IQA+)')
    parser.add_argument(
        '--root_path',
        required=True,
        help='[single] before cam root  /  [batch] FID_model root  /  [range] clip_id root')
    parser.add_argument(
        '--compare_path',
        default=None,
        help='[single] after cam root  /  [batch] FID_output/{version} root')
    parser.add_argument(
        '--batch',
        action='store_true',
        help='enable batch mode: iterate all matching clip_ids under root_path')
    parser.add_argument(
        '--range',
        action='store_true',
        dest='range_mode',
        help='enable range mode: evaluate adaptive_shift_*m distance folders under root_path')
    parser.add_argument(
        '--base_subdir',
        default='',
        help='[batch] subdir inside clip_id for base path (default: empty = flat, no side subdir)')
    parser.add_argument(
        '--base_img_subdir',
        default='',
        help='[batch] subdir inside side for base images (default: empty = flat, no img subdir)')
    parser.add_argument(
        '--sides',
        nargs='+',
        default=SIDES,
        help='sides to process (default: left right)')
    parser.add_argument(
        '--output_csv',
        default='multicam_iqa_results.csv',
        help='path to save the full result CSV file')
    parser.add_argument(
        '--device',
        type=int,
        default=0,
        help='CUDA device id')
    parser.add_argument(
        '--num_shards',
        type=int,
        default=1,
        help='[batch] total number of parallel shards (default: 1 = no sharding)')
    parser.add_argument(
        '--shard_idx',
        type=int,
        default=0,
        help='[batch] index of this shard, 0-based (default: 0)')
    parser.add_argument(
        '--trigger_time',
        type=int,
        default=0,
        help='只评估时间戳大于此阈值的图片（0 表示不过滤）')
    parser.add_argument(
        '--case_id',
        type=str,
        default=None,
        help='自动从 CloudSim 获取 triggerTime，格式: S<scenario_id>-J<job_id>-T<task_id>')
    args = parser.parse_args()
    return args


def get_attribute_names(model):
    """Derive attribute names from the positive prompt in each classnames pair."""
    try:
        classnames = model.cfg.model.generator.classnames
        names = []
        for pair in classnames:
            label = pair[0].split(' photo.')[0].strip()
            names.append(label)
        return names
    except Exception:
        return [f'Attr{i}' for i in range(10)]


def collect_image_names(root_path, cam_folders, trigger_time: int = 0):
    """Collect the union of image filenames across all camera folders.

    If trigger_time > 0, only include images whose filename starts with a
    numeric timestamp > trigger_time (format: {ts}_{idx}.ext).
    """
    image_names = set()
    for cam in cam_folders:
        cam_dir = os.path.join(root_path, cam)
        if not os.path.isdir(cam_dir):
            continue
        for fname in os.listdir(cam_dir):
            if os.path.splitext(fname)[1].lower() not in IMG_EXTENSIONS:
                continue
            if trigger_time > 0:
                # 文件名格式: {timestamp}_{idx}.ext
                ts_part = fname.split('_')[0]
                if ts_part.isdigit() and int(ts_part) <= trigger_time:
                    continue
            image_names.add(fname)
    return sorted(image_names)


def eval_cam_path(model, root_path, available_cams, image_names, attribute_names,
                  tag, extra_cols=None):
    """Evaluate all images under root_path; return a DataFrame.
    extra_cols: dict of extra columns to add to every row (e.g. clip_id, side)
    """
    records = []
    for cam in available_cams:
        cam_dir = os.path.join(root_path, cam)
        if not os.path.isdir(cam_dir):
            continue
        # Only iterate images that actually exist in this camera's directory
        cam_image_names = [img for img in image_names
                           if os.path.isfile(os.path.join(cam_dir, img))]
        if not cam_image_names:
            continue
        for img_name in tqdm(cam_image_names, desc=f'{tag}/{cam}', leave=False):
            img_path = os.path.join(cam_dir, img_name)
            row = {'tag': tag, 'camera': cam, 'image': img_name}
            if extra_cols:
                row.update(extra_cols)
            if not os.path.isfile(img_path):
                for attr in attribute_names:
                    row[attr] = float('nan')
            else:
                try:
                    _, attributes = restoration_inference(
                        model, img_path, return_attributes=True)
                except Exception as e:
                    # Retry: some images (e.g. RGBA 4-channel) cause OpenCV
                    # arithm_op shape mismatch in the Normalize pipeline step.
                    # Convert to RGB via PIL and re-run on a temp file.
                    if 'Sizes of input arguments' in str(e) or 'arithm_op' in str(e):
                        try:
                            with _PILImage.open(img_path) as _pil:
                                _rgb = _pil.convert('RGB')
                            _fd, _tmp = tempfile.mkstemp(suffix='.png')
                            os.close(_fd)
                            _rgb.save(_tmp)
                            _, attributes = restoration_inference(
                                model, _tmp, return_attributes=True)
                            os.unlink(_tmp)
                        except Exception as e2:
                            print(f'  Warning (retry failed): {img_path}: {e2}')
                            for attr in attribute_names:
                                row[attr] = float('nan')
                            records.append(row)
                            continue
                    else:
                        print(f'  Warning: {img_path}: {e}')
                        for attr in attribute_names:
                            row[attr] = float('nan')
                        records.append(row)
                        continue
                try:
                    attrs = attributes.float().detach().cpu().numpy()
                    attrs = np.squeeze(attrs)
                    if attrs.ndim == 0:
                        attrs = attrs.reshape(1)
                    for i, attr in enumerate(attribute_names):
                        row[attr] = float(attrs[i]) * 100 if i < len(attrs) else float('nan')
                except Exception as e:
                    print(f'  Warning: {img_path}: {e}')
                    for attr in attribute_names:
                        row[attr] = float('nan')
            records.append(row)
    return pd.DataFrame(records)


def save_summary_csv(df_all, out_csv, attribute_names):
    """Save per-camera mean scores (no image column) to *_summary.csv.

    Groups by all metadata columns (everything except 'image' and attribute
    score columns), computes mean of each attribute, and writes to
    <out_csv_stem>_summary.csv alongside the full CSV.
    """
    if df_all.empty:
        return
    score_cols = [a for a in attribute_names if a in df_all.columns]
    group_cols = [c for c in df_all.columns if c not in score_cols and c != 'image']
    if not group_cols:
        return
    summary = df_all.groupby(group_cols, sort=False)[score_cols].mean().reset_index()
    stem, ext = os.path.splitext(out_csv)
    summary_csv = f'{stem}_summary{ext}'
    summary.to_csv(summary_csv, index=False)
    print(f'Summary (per-camera means) saved to {summary_csv}')


def print_summary(df, tag, cams, attribute_names, title=''):
    if df.empty or 'tag' not in df.columns:
        print(f'  [SKIP] No data for [{tag}] {title}')
        return
    col_w = max(14, max(len(a) for a in attribute_names) + 2)
    print(f'\n===== [{tag}] {title}Per-camera mean scores (0-100) =====')
    print(f'  Attributes: {attribute_names}')
    header = f'{"Camera":<8}' + ''.join(f'{a:>{col_w}}' for a in attribute_names)
    print(header)
    print('-' * len(header))
    for cam in cams:
        sub = df[(df['tag'] == tag) & (df['camera'] == cam)]
        if sub.empty:
            continue
        means = [sub[a].mean() for a in attribute_names]
        print(f'{cam:<8}' + ''.join(f'{m:>{col_w}.2f}' for m in means))


def print_delta(df_before, df_after, shared_cams, attribute_names, title=''):
    if df_before.empty or df_after.empty:
        print(f'  [SKIP] Insufficient data for delta {title}')
        return
    if 'camera' not in df_before.columns or 'camera' not in df_after.columns:
        return
    col_w = max(14, max(len(a) for a in attribute_names) + 3)
    print(f'\n===== Delta: after - before {title}(per-camera mean) =====')
    header = f'{"Camera":<8}' + ''.join(f'{"Δ"+a:>{col_w}}' for a in attribute_names)
    print(header)
    print('-' * len(header))
    for cam in shared_cams:
        b = df_before[df_before['camera'] == cam]
        a = df_after[df_after['camera'] == cam]
        deltas = [a[attr].mean() - b[attr].mean() for attr in attribute_names]
        print(f'{cam:<8}' + ''.join(
            f'{("+" if d >= 0 else "") + f"{d:.2f}":>{col_w}}' for d in deltas))


# ──────────────────────────────────────────────
# Single mode
# ──────────────────────────────────────────────
def run_single(args, model, attribute_names):
    available_cams = [
        cam for cam in CAM_FOLDERS
        if os.path.isdir(os.path.join(args.root_path, cam))
    ]
    if not available_cams:
        raise RuntimeError(
            f'No camera folders found under {args.root_path}. '
            f'Expected one or more of: {CAM_FOLDERS}')
    print(f'Found camera folders: {available_cams}')

    image_names = collect_image_names(args.root_path, available_cams, trigger_time=args.trigger_time)
    print(f'Total unique images per camera: {len(image_names)}')

    print(f'\n[before] Evaluating ...')
    df_before = eval_cam_path(model, args.root_path, available_cams,
                               image_names, attribute_names, tag='before')
    print_summary(df_before, 'before', available_cams, attribute_names)
    all_dfs = [df_before]

    if args.compare_path:
        compare_cams = [
            cam for cam in CAM_FOLDERS
            if os.path.isdir(os.path.join(args.compare_path, cam))
        ]
        print(f'\n[after] Evaluating ...')
        df_after = eval_cam_path(model, args.compare_path, compare_cams,
                                  image_names, attribute_names, tag='after')
        print_summary(df_after, 'after', compare_cams, attribute_names)
        all_dfs.append(df_after)

        shared_cams = [c for c in available_cams if c in compare_cams]
        print_delta(df_before, df_after, shared_cams, attribute_names)

    return pd.concat(all_dfs, ignore_index=True)


# ──────────────────────────────────────────────
# Batch mode
# ──────────────────────────────────────────────
def get_matching_clip_ids(base_root, compare_root=None):
    base_ids = sorted(
        d for d in os.listdir(base_root)
        if os.path.isdir(os.path.join(base_root, d)))
    print(f'Base clip_ids: {len(base_ids)}')
    if compare_root is None:
        return base_ids
    cmp_ids = {d for d in os.listdir(compare_root)
               if os.path.isdir(os.path.join(compare_root, d))}
    matched = sorted(d for d in base_ids if d in cmp_ids)
    print(f'Compare clip_ids: {len(cmp_ids)}')
    print(f'Matched:          {len(matched)}')
    return matched


def run_batch(args, model, attribute_names):
    # normalize empty string to None (e.g. when shell passes --compare_path '')
    compare_path = args.compare_path if args.compare_path else None
    clip_ids = get_matching_clip_ids(args.root_path, compare_path)

    # ── sharding: take every num_shards-th clip_id starting at shard_idx ──
    if args.num_shards > 1:
        clip_ids = clip_ids[args.shard_idx::args.num_shards]
        print(f'Shard {args.shard_idx}/{args.num_shards}: {len(clip_ids)} clip_ids')

    all_dfs = []
    has_compare = bool(compare_path)
    # flat mode: no side/subdir layers, cam* sits directly under clip_id/
    flat_mode = not args.base_subdir and not args.base_img_subdir

    for clip_id in clip_ids:
        if flat_mode:
            # {root_path}/{clip_id}/cam*/
            base_cam_root = os.path.join(args.root_path, clip_id)
            if not os.path.isdir(base_cam_root):
                print(f'  [SKIP] base not found: {base_cam_root}')
                continue
            available_cams = [
                cam for cam in CAM_FOLDERS
                if os.path.isdir(os.path.join(base_cam_root, cam))
            ]
            if not available_cams:
                continue
            _clip_trigger = resolve_trigger_time_from_name(clip_id, args.trigger_time)
            image_names = collect_image_names(base_cam_root, available_cams, trigger_time=_clip_trigger)
            if not image_names:
                print(f'  [SKIP] No images found in {base_cam_root}')
                continue
            extra = {'clip_id': clip_id}
            label = clip_id[:8]
            print(f'\n>>> {clip_id}  ({len(image_names)} imgs/cam, cams={available_cams})')
            df_b = eval_cam_path(model, base_cam_root, available_cams,
                                  image_names, attribute_names,
                                  tag='before', extra_cols=extra)
            print_summary(df_b, 'before', available_cams, attribute_names, title=f'{label} ')
            all_dfs.append(df_b)
            if has_compare:
                cmp_cam_root = os.path.join(compare_path, clip_id)
                if not os.path.isdir(cmp_cam_root):
                    print(f'  [SKIP] compare not found: {cmp_cam_root}')
                else:
                    df_a = eval_cam_path(model, cmp_cam_root, available_cams,
                                          image_names, attribute_names,
                                          tag='after', extra_cols=extra)
                    print_summary(df_a, 'after', available_cams, attribute_names, title=f'{label} ')
                    print_delta(df_b, df_a, available_cams, attribute_names, title=f'[{label}] ')
                    all_dfs.append(df_a)
            continue  # skip side loop below

        for side in args.sides:
            base_cam_root = os.path.join(
                args.root_path, clip_id, args.base_subdir, side, args.base_img_subdir)

            if not os.path.isdir(base_cam_root):
                print(f'  [SKIP] base not found: {base_cam_root}')
                continue

            base_cams = [
                cam for cam in CAM_FOLDERS
                if os.path.isdir(os.path.join(base_cam_root, cam))
            ]

            if has_compare:
                cmp_cam_root = os.path.join(compare_path, clip_id, side)
                if not os.path.isdir(cmp_cam_root):
                    print(f'  [SKIP] compare not found: {cmp_cam_root}')
                    continue
                cmp_cams = [
                    cam for cam in CAM_FOLDERS
                    if os.path.isdir(os.path.join(cmp_cam_root, cam))
                ]
                available_cams = sorted(set(base_cams) | set(cmp_cams))
            else:
                available_cams = base_cams

            if not available_cams:
                continue

            image_names = collect_image_names(base_cam_root, available_cams, trigger_time=resolve_trigger_time_from_name(clip_id, args.trigger_time))
            if not image_names:
                print(f'  [SKIP] No images found in {base_cam_root}')
                continue
            extra = {'clip_id': clip_id, 'side': side}
            label = f'{clip_id[:8]}/{side}'

            print(f'\n>>> {clip_id} / {side}  ({len(image_names)} imgs/cam, cams={available_cams})')

            df_b = eval_cam_path(model, base_cam_root, available_cams,
                                  image_names, attribute_names,
                                  tag='before', extra_cols=extra)
            print_summary(df_b, 'before', available_cams, attribute_names, title=f'{label} ')
            all_dfs.append(df_b)

            if has_compare:
                df_a = eval_cam_path(model, cmp_cam_root, available_cams,
                                      image_names, attribute_names,
                                      tag='after', extra_cols=extra)
                print_summary(df_a, 'after', available_cams, attribute_names, title=f'{label} ')
                print_delta(df_b, df_a, available_cams, attribute_names, title=f'[{label}] ')
                all_dfs.append(df_a)

    if not all_dfs:
        print('No data collected.')
        return pd.DataFrame()

    df_all = pd.concat(all_dfs, ignore_index=True)

    # Aggregate delta summary across all clip_ids (only when compare available)
    if has_compare:
        print('\n\n' + '='*60)
        print('BATCH SUMMARY: mean delta across all clip_ids & sides')
        print('='*60)
        col_w = max(14, max(len(a) for a in attribute_names) + 3)
        header = f'{"Camera":<8}' + ''.join(f'{"Δ"+a:>{col_w}}' for a in attribute_names)
        print(header)
        print('-' * len(header))
        for cam in CAM_FOLDERS:
            b = df_all[(df_all['tag'] == 'before') & (df_all['camera'] == cam)]
            a = df_all[(df_all['tag'] == 'after')  & (df_all['camera'] == cam)]
            if b.empty or a.empty:
                continue
            deltas = [a[attr].mean() - b[attr].mean() for attr in attribute_names]
            print(f'{cam:<8}' + ''.join(
                f'{("+" if d >= 0 else "") + f"{d:.2f}":>{col_w}}' for d in deltas))
    else:
        # No compare: print overall mean per camera
        print('\n\n' + '='*60)
        print('BATCH SUMMARY: mean scores across all clip_ids & sides')
        print('='*60)
        col_w = max(14, max(len(a) for a in attribute_names) + 2)
        header = f'{"Camera":<8}' + ''.join(f'{a:>{col_w}}' for a in attribute_names)
        print(header)
        print('-' * len(header))
        for cam in CAM_FOLDERS:
            sub = df_all[df_all['camera'] == cam]
            if sub.empty:
                continue
            means = [sub[attr].mean() for attr in attribute_names]
            print(f'{cam:<8}' + ''.join(f'{m:>{col_w}.2f}' for m in means))

    return df_all


# ──────────────────────────────────────────────
# Range mode
# ──────────────────────────────────────────────


def find_cam_root(side_dir):
    """Return the directory that directly contains cam* folders.

    First checks side_dir itself, then falls back to side_dir/redistort_rgb/.
    Returns None if no cam folder is found in either location.
    """
    cam_pattern = _re.compile(r'^cam\d+$')
    def has_cam_folders(d):
        try:
            return any(cam_pattern.match(e) and os.path.isdir(os.path.join(d, e))
                       for e in os.listdir(d))
        except OSError:
            return False

    if has_cam_folders(side_dir):
        return side_dir
    fallback = os.path.join(side_dir, 'redistort_rgb')
    if os.path.isdir(fallback) and has_cam_folders(fallback):
        return fallback
    return None


def discover_distance_folders(root_path):
    """Return sorted list of (distance_label, folder_path) for adaptive_shift_* dirs."""
    pattern = _re.compile(r'^adaptive_shift_(-?\d+(?:\.\d+)?m)$')
    results = []
    try:
        entries = os.listdir(root_path)
    except OSError:
        return results
    for entry in entries:
        m = pattern.match(entry)
        if m and os.path.isdir(os.path.join(root_path, entry)):
            results.append((m.group(1), os.path.join(root_path, entry)))
    # Sort numerically by the distance value
    def _key(item):
        try:
            return float(item[0].rstrip('m'))
        except ValueError:
            return 0.0
    results.sort(key=_key)
    return results


def run_range(args, model, attribute_names):
    """Range mode: evaluate adaptive_shift_*m distance folders under root_path.

    Directory layout:
      {root_path}/
        adaptive_shift_-1.0m/
          left/
            cam0/ ...          (or redistort_rgb/cam0/ ...)
          right/
            cam0/ ...
        adaptive_shift_-3.0m/
          ...

    Output CSV is named after clip_id and the parent group dir.
    """
    root_path = args.root_path.rstrip('/')
    clip_id = os.path.basename(root_path)
    group_name = os.path.basename(os.path.dirname(root_path))
    print(f'Range mode | group: {group_name} | clip_id: {clip_id}')

    distance_folders = discover_distance_folders(root_path)
    if not distance_folders:
        raise RuntimeError(
            f'No adaptive_shift_*m folders found under {root_path}')
    print(f'Distance folders found: {[d for d, _ in distance_folders]}')

    all_dfs = []

    for dist_label, dist_dir in distance_folders:
        for side in args.sides:
            side_dir = os.path.join(dist_dir, side)
            if not os.path.isdir(side_dir):
                print(f'  [SKIP] {dist_label}/{side}: directory not found')
                continue

            cam_root = find_cam_root(side_dir)
            if cam_root is None:
                print(f'  [SKIP] {dist_label}/{side}: no cam* folders found '
                      f'(checked {side_dir} and redistort_rgb/)')
                continue

            available_cams = [
                cam for cam in CAM_FOLDERS
                if os.path.isdir(os.path.join(cam_root, cam))
            ]
            if not available_cams:
                print(f'  [SKIP] {dist_label}/{side}: none of {CAM_FOLDERS} present in {cam_root}')
                continue

            image_names = collect_image_names(cam_root, available_cams, trigger_time=args.trigger_time)
            if not image_names:
                print(f'  [SKIP] {dist_label}/{side}: no images found')
                continue

            extra = {'group': group_name, 'clip_id': clip_id,
                     'distance': dist_label, 'side': side}
            tag = f'{dist_label}/{side}'
            print(f'\n>>> {dist_label} / {side}  cam_root={cam_root}  '
                  f'cams={available_cams}  imgs/cam={len(image_names)}')

            df = eval_cam_path(model, cam_root, available_cams,
                               image_names, attribute_names,
                               tag=tag, extra_cols=extra)
            print_summary(df, tag, available_cams, attribute_names,
                          title=f'{dist_label}/{side} ')
            all_dfs.append(df)

    if not all_dfs:
        print('No data collected.')
        return pd.DataFrame()

    df_all = pd.concat(all_dfs, ignore_index=True)

    # ── Pretty summary table: rows=distance, cols=camera×attribute ──
    for side in args.sides:
        side_df = df_all[df_all['side'] == side]
        if side_df.empty:
            continue
        print(f'\n\n{"="*70}')
        print(f'RANGE SUMMARY  [{side}]  group={group_name}  clip_id={clip_id}')
        print(f'{"="*70}')
        col_w = max(14, max(len(a) for a in attribute_names) + 2)
        dist_labels = [d for d, _ in distance_folders]
        for cam in CAM_FOLDERS:
            cam_df = side_df[side_df['camera'] == cam]
            if cam_df.empty:
                continue
            print(f'\n  Camera: {cam}')
            header = f'  {"Distance":<14}' + ''.join(f'{a:>{col_w}}' for a in attribute_names)
            print(header)
            print('  ' + '-' * (len(header) - 2))
            for dist_label in dist_labels:
                row_df = cam_df[cam_df['distance'] == dist_label]
                if row_df.empty:
                    continue
                means = [row_df[a].mean() for a in attribute_names]
                print(f'  {dist_label:<14}' +
                      ''.join(f'{m:>{col_w}.2f}' for m in means))

    # Auto-name output CSV if not overridden
    out_csv = args.output_csv
    if out_csv == 'multicam_iqa_results.csv':
        out_csv = f'range_{group_name}_{clip_id}.csv'

    df_all.to_csv(out_csv, index=False)
    print(f'\nFull results saved to {out_csv}')
    save_summary_csv(df_all, out_csv, attribute_names)
    return df_all


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
def main():
    args = parse_args()

    # 如果指定了 --case_id，自动获取 triggerTime（优先于 --trigger_time）
    if args.case_id and args.trigger_time == 0:
        m = _re.match(r'^S(\d+)', args.case_id)
        if m:
            args.trigger_time = fetch_trigger_time(int(m.group(1)))
        else:
            print(f'[warn] --case_id 格式无效，应为 S<id>-J<id>-T<id>')

    model = init_model(
        args.config,
        args.checkpoint,
        device=torch.device('cuda', args.device))

    attribute_names = get_attribute_names(model)
    print(f'Attributes (from config): {attribute_names}')

    if args.range_mode:
        df_all = run_range(args, model, attribute_names)
    elif args.batch:
        df_all = run_batch(args, model, attribute_names)
    else:
        df_all = run_single(args, model, attribute_names)

    if not args.range_mode:
        df_all.to_csv(args.output_csv, index=False)
        print(f'\nFull results saved to {args.output_csv}')
        save_summary_csv(df_all, args.output_csv, attribute_names)


if __name__ == '__main__':
    main()

