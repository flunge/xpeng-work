#!/usr/bin/env python3
"""
在目标目录下读取 LocalPoseTopic.json 与 images_origin/<cam>/ 图片，按时间戳最近邻建立
pose ↔ 各相机图像 的对应关系。

目录约定:
  <target>/
    LocalPoseTopic.json    # DDS 列表；匹配优先用每项的 t_source(纳秒)，缺省则 t_reception，再 time_stamp.nsec
    images_origin/
      cam0/, cam2/, ...    # 图片文件名含整数时间戳(与 mv_png 一致)

默认输出到目标目录:
  h265_png_pcam2pose.json / h265_png_pose2cam.json
  h265_png_pose2cam_unmatched.json  # 某 pose 下存在任一相机 |pose_ts-image_ts|>=阈值(默认 0.05s) 的记录

统计: delta 仍为纳秒差 (pose_ts - image_ts)，展示时除以 1e9，单位为秒。
默认在输出目录生成各 cam 时间戳差距直方图(横轴秒，bin 宽默认 0.005 s；图中文字为英文)。
另生成 h265_png_timestamp_gap.png：横轴为 pose 时间(相对首帧秒)，纵轴为 pose_ts-image_ts(秒)，多 cam 同图。

仍支持单目录调试: --localpose + --cam-dir(写出单个 mapping 时需 --mapping-out)。

用法:
  python match_localpose_cam_images.py --target /path/to/clip_root
  python match_localpose_cam_images.py --target /path/to/clip_root --stats-out /tmp/stats.txt
  python match_localpose_cam_images.py --target /path/to/clip --hist-out /tmp/hist.png --hist-bin 0.005
  python match_localpose_cam_images.py --target /path/to/clip --no-hist
  python match_localpose_cam_images.py --target /path/to/clip --no-timeline
"""

from __future__ import annotations

import argparse
import bisect
import json
import os
import re
import shutil
import sys
import uuid
from collections import defaultdict
from pathlib import Path
from statistics import mean, median, stdev

try:
    # when running as package/module (recommended in project code)
    from utils.general_utils import lookup_pose
    from utils.calib_utils import get_ecef2enu, get_pose_buffer_from_localpose_topic
except ModuleNotFoundError:
    # when running as script: python utils/match_pose_and_cam.py
    _THIS_FILE = Path(__file__).resolve()
    _PARENT_DIR = str(_THIS_FILE.parents[1])
    if _PARENT_DIR not in sys.path:
        sys.path.insert(0, _PARENT_DIR)
    from utils.general_utils import lookup_pose
    from utils.calib_utils import get_ecef2enu, get_pose_buffer_from_localpose_topic


# LocalPoseTopic / 图像文件名均为纳秒时间戳；统计输出换算为秒
NSEC_PER_S = 1_000_000_000
# pose2cam_unmatched: 至少一路相机 |pose_ts-image_ts| >= 该秒数则记入
CAM2_MATCH_MAX_GAP_SEC = 0.005


def load_localpose_dict(path: str | Path) -> dict[int, list]:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    out: dict[int, list] = {}
    for k, v in raw.items():
        out[int(k)] = v
    return out


def _pose_nsec_from_local_pose_item(item: dict) -> int | None:
    """单条 LocalPoseTopic 记录对应的纳秒时间戳：优先 t_source(与图像对齐)，否则 t_reception，再 time_stamp.nsec。"""
    if "t_source" in item and item["t_source"] is not None:
        return int(item["t_source"])
    if "t_reception" in item and item["t_reception"] is not None:
        return int(item["t_reception"])
    ts_obj = item.get("time_stamp") or item.get("timestamp")
    if ts_obj is None:
        return None
    if isinstance(ts_obj, dict) and "nsec" in ts_obj:
        return int(ts_obj["nsec"])
    if isinstance(ts_obj, (int, float, str)):
        return int(ts_obj)
    return None


def load_local_pose_topic_timestamps(path: str | Path) -> list[int]:
    """从 LocalPoseTopic.json 解析 pose 时间戳列表(纳秒)，与图像匹配用 t_source。

    额外规则：丢弃最早 1 秒内的数据，仅保留 >= (min_ts + 1s) 的时间戳。
    """
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        out: list[int] = []
        skipped = 0
        for item in data:
            if not isinstance(item, dict):
                skipped += 1
                continue
            nsec = _pose_nsec_from_local_pose_item(item)
            if nsec is None:
                skipped += 1
                continue
            if "smooth_pose" in item and item["smooth_pose"].get("error_code", 0) != 0:
                skipped += 1
                continue
            out.append(nsec)
        if skipped:
            print(f"[WARN] LocalPoseTopic: 跳过 {skipped} 条(无可用时间戳或 smooth_pose.error_code!=0)")
        sorted_unique = sorted(set(out))
        if not sorted_unique:
            return []
        cutoff = sorted_unique[0] + NSEC_PER_S
        filtered = [ts for ts in sorted_unique if ts >= cutoff]
        dropped = len(sorted_unique) - len(filtered)
        if dropped > 0:
            print(f"[INFO] LocalPoseTopic: drop first 1s poses, removed {dropped} entries")
        return filtered

    if isinstance(data, dict):
        sorted_unique = sorted(int(k) for k in data.keys())
        if not sorted_unique:
            return []
        cutoff = sorted_unique[0] + NSEC_PER_S
        filtered = [ts for ts in sorted_unique if ts >= cutoff]
        dropped = len(sorted_unique) - len(filtered)
        if dropped > 0:
            print(f"[INFO] LocalPoseTopic(dict): drop first 1s poses, removed {dropped} entries")
        return filtered

    raise ValueError(f"无法解析 LocalPoseTopic.json 顶层类型: {type(data)}")


def _stem_int(name: str) -> int | None:
    stem = Path(name).stem
    if stem.isdigit():
        return int(stem)
    m = re.match(r"^(\d+)", stem)
    return int(m.group(1)) if m else None


def collect_image_timestamps(cam_dir: str | Path) -> list[tuple[int, str]]:
    """返回 (时间戳, 原始文件名)，仅包含能从文件名解析出整数时间戳的条目。"""
    cam_dir = Path(cam_dir)
    exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    items: list[tuple[int, str]] = []
    for name in sorted(os.listdir(cam_dir)):
        p = cam_dir / name
        if not p.is_file():
            continue
        if p.suffix.lower() not in exts:
            continue
        ts = _stem_int(name)
        if ts is None:
            continue
        items.append((ts, name))
    items.sort(key=lambda x: x[0])
    return items


def nearest_ts(sorted_ts: list[int], query: int) -> int:
    """在已排序时间戳列表中，返回与 query 最近的一个。"""
    if not sorted_ts:
        raise ValueError("时间戳列表为空")
    i = bisect.bisect_left(sorted_ts, query)
    if i <= 0:
        return sorted_ts[0]
    if i >= len(sorted_ts):
        return sorted_ts[-1]
    left, right = sorted_ts[i - 1], sorted_ts[i]
    return left if query - left <= right - query else right


def match_pose_to_images(
    pose_ts_list: list[int], image_entries: list[tuple[int, str]]
) -> list[tuple[int, str, int, int]]:
    """
    每个 pose 时间戳 -> 该相机目录下最近的图片。
    返回: (pose_ts, image_filename, image_ts, delta) delta = pose_ts - image_ts
    """
    if not image_entries:
        raise ValueError("该相机目录下没有可解析时间戳的图片")
    sorted_ts = [t for t, _ in image_entries]
    ts_to_names: dict[int, list[str]] = {}
    for t, fname in image_entries:
        ts_to_names.setdefault(t, []).append(fname)

    rows: list[tuple[int, str, int, int]] = []
    for p in sorted(pose_ts_list):
        it = nearest_ts(sorted_ts, p)
        fname = sorted(ts_to_names[it])[0]
        rows.append((p, fname, it, p - it))
    return rows


def collapse_image_to_best_pose(
    rows: list[tuple[int, str, int, int]],
) -> dict[str, int]:
    """
    同一文件名被多个 pose 选为最近邻时，保留 |pose_ts - image_ts| 最小的 pose_ts。
    返回: 图片文件名 -> pose_ts
    """
    best: dict[str, tuple[int, int]] = {}
    for pose_ts, fname, _img_ts, delta in rows:
        ad = abs(delta)
        if fname not in best or ad < best[fname][1]:
            best[fname] = (pose_ts, ad)
        elif ad == best[fname][1] and pose_ts < best[fname][0]:
            best[fname] = (pose_ts, ad)
    return {fname: pose_ts for fname, (pose_ts, _) in best.items()}


def match_all_images_to_nearest_pose(
    pose_ts_list: list[int], image_entries: list[tuple[int, str]]
) -> dict[str, int]:
    """每张图 -> 时间上最近的 pose 时间戳。"""
    if not pose_ts_list:
        raise ValueError("pose 时间戳列表为空")
    sorted_poses = sorted(pose_ts_list)
    out: dict[str, int] = {}
    for img_ts, fname in image_entries:
        p = nearest_ts(sorted_poses, img_ts)
        out[fname] = p
    return out


def summarize_deltas(deltas_nsec: list[int]) -> str:
    """deltas_nsec 为 camX_ts - cam2_ts(纳秒)；输出统计单位为秒。"""
    if not deltas_nsec:
        return "无数据"
    deltas_s = [d / NSEC_PER_S for d in deltas_nsec]
    abs_d = [abs(x) for x in deltas_s]
    lines = [
        f"样本数: {len(deltas_s)}",
        f"signed (camX_ts - cam2_ts), 单位 秒: min={min(deltas_s):.6f}, max={max(deltas_s):.6f}, "
        f"mean={mean(deltas_s):.6f}, median={median(deltas_s):.6f}",
    ]
    if len(deltas_s) >= 2:
        lines.append(f"signed stdev (秒): {stdev(deltas_s):.6f}")
    lines.append(
        f"|delta|, 单位 秒: min={min(abs_d):.6f}, max={max(abs_d):.6f}, "
        f"mean={mean(abs_d):.6f}, median={median(abs_d):.6f}"
    )
    if len(abs_d) >= 2:
        lines.append(f"|delta| stdev (秒): {stdev(abs_d):.6f}")
    return "\n".join(lines)


def _ts_key(t: int) -> str:
    return str(t)


def plot_timestamp_gap_vs_pose_time(
    cam_to_series: dict[str, list[tuple[int, float]]],
    out_path: Path,
) -> None:
    """
    One figure: x = cam2 time axis, y = camX_ts - cam2_ts (seconds).
    X-axis uses (cam2_ts - min_cam2_ts) / 1e9 for readable timeline; all cameras overlaid.
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("[WARN] matplotlib not installed; skip timestamp gap timeline (pip install matplotlib)")
        return

    cams = sorted(cam_to_series.keys())
    if not cams:
        return

    all_cam2_ts: list[int] = []
    for cam in cams:
        for cam2_ts, _ in cam_to_series[cam]:
            all_cam2_ts.append(cam2_ts)
    if not all_cam2_ts:
        return

    t0 = min(all_cam2_ts)
    fig, ax = plt.subplots(figsize=(14, 5))
    for cam in cams:
        series = cam_to_series[cam]
        if not series:
            continue
        xs = [(cam2_ts - t0) / NSEC_PER_S for cam2_ts, _ in series]
        ys = [g for _, g in series]
        ax.plot(xs, ys, label=f"{cam} (n={len(series)})", linewidth=1.0, alpha=0.88)

    ax.set_xlabel("cam2 time (s, offset from earliest cam2_ts in plot)")
    ax.set_ylabel("camX_ts - cam2_ts (s)")
    ax.set_title("Timestamp gap vs cam2 time (all cameras)")
    ax.legend(loc="best", fontsize=8, ncol=2)
    ax.grid(True, alpha=0.35)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Timeline plot saved: {out_path.resolve()}")


def keep_closest_gap_per_pose(series: list[tuple[int, float]]) -> list[tuple[int, float]]:
    """
    若同一个 cam2_ts 出现多条 gap，保留 |gap| 最小的一条。
    返回按 cam2_ts 升序排列后的序列。
    """
    best: dict[int, float] = {}
    for cam2_ts, gap_sec in series:
        if cam2_ts not in best or abs(gap_sec) < abs(best[cam2_ts]):
            best[cam2_ts] = gap_sec
    return sorted(best.items(), key=lambda x: x[0])


def build_cam2_strict_matches(
    cam2_to_cams: dict[str, dict[str, str]],
    all_cams: list[str],
    max_gap_sec: float = CAM2_MATCH_MAX_GAP_SEC,
) -> dict[str, dict[str, str]]:
    """
    从 cam2_to_cams 中筛选严格匹配：
    1) 每组里所有 cam 与 cam2 的 |gap| < max_gap_sec
    2) 全局一一绑定：每个 cam 的时间戳最多绑定一个 cam2
       若冲突，保留整体时间差(各 cam |gap| 之和)更小的组
    """
    non_cam2 = [c for c in all_cams if c != "cam2"]

    candidates: list[tuple[float, int, str, dict[str, str]]] = []
    # (score_sum_abs_gap, tie_break_max_abs_gap_nsec, cam2_ts_str, row)
    for cam2_ts_s, row in cam2_to_cams.items():
        cam2_ts = int(cam2_ts_s)
        valid = True
        total_abs_gap = 0.0
        max_abs_gap_nsec = 0
        for cam in non_cam2:
            cam_ts_s = row.get(cam)
            if cam_ts_s is None:
                valid = False
                break
            cam_ts = int(cam_ts_s)
            abs_gap = abs(cam_ts - cam2_ts) / NSEC_PER_S
            if abs_gap >= max_gap_sec:
                valid = False
                break
            total_abs_gap += abs_gap
            max_abs_gap_nsec = max(max_abs_gap_nsec, abs(cam_ts - cam2_ts))
        if valid:
            candidates.append((total_abs_gap, max_abs_gap_nsec, cam2_ts_s, row))

    # 按整体差值从小到大选，冲突时自然优先保留更小的
    candidates.sort(key=lambda x: (x[0], x[1], int(x[2])))
    used_cam_ts: dict[str, set[str]] = {cam: set() for cam in non_cam2}
    selected: dict[str, dict[str, str]] = {}
    for _score, _max_gap, cam2_ts_s, row in candidates:
        conflict = False
        for cam in non_cam2:
            cam_ts_s = row[cam]
            if cam_ts_s in used_cam_ts[cam]:
                conflict = True
                break
        if conflict:
            continue
        selected[cam2_ts_s] = dict(row)
        for cam in non_cam2:
            used_cam_ts[cam].add(row[cam])

    return dict(sorted(selected.items(), key=lambda x: int(x[0])))


def build_gap_series_from_cam2_groups(
    cam2_groups: dict[str, dict[str, str]],
) -> dict[str, list[tuple[int, float]]]:
    """
    从 cam2->cams 分组结果构建绘图数据:
      - cam -> [(cam2_ts, camX_ts - cam2_ts)]
    仅包含非 cam2 相机。
    """
    per_cam_pose_gap_series: dict[str, list[tuple[int, float]]] = defaultdict(list)

    for cam2_ts_s, row in sorted(cam2_groups.items(), key=lambda x: int(x[0])):
        cam2_ts = int(cam2_ts_s)
        for cam_name, cam_ts_s in sorted(row.items()):
            if cam_name == "cam2":
                continue
            cam_ts = int(cam_ts_s)
            gap_sec = (cam_ts - cam2_ts) / NSEC_PER_S
            per_cam_pose_gap_series[cam_name].append((cam2_ts, gap_sec))

    return dict(per_cam_pose_gap_series)


def discover_cam_dirs(images_origin: Path) -> list[tuple[str, Path]]:
    """返回 (cam_name, path)。优先匹配 cam0/cam2 形式；否则退回所有子目录。"""
    if not images_origin.is_dir():
        raise FileNotFoundError(f"缺少目录: {images_origin}")
    strict = [p for p in sorted(images_origin.iterdir()) if p.is_dir() and re.match(r"^cam\d+$", p.name, re.I)]
    if strict:
        return [(p.name, p) for p in strict]
    return [(p.name, p) for p in sorted(images_origin.iterdir()) if p.is_dir()]


def rename_images_origin_to_pose_timestamp(
    target_dir: str | Path,
    cam2pose_json_path: str | Path | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """
    根据 h265_png_cam2_to_cams_match.json，将 matched 组里的各相机图片
    统一重命名为 cam2_ts，并移动到新的 images_origin/<cam>/ 目录。

    - 输入映射格式: {cam2_ts: {cam2: cam2_ts, cam0: cam0_ts, cam3: cam3_ts, ...}}
    - 仅处理 matched 里出现的时间戳
    - 源目录: <target>/images_origin_all
    - 目标目录: <target>/images_origin
    - 若目标重名，自动追加 _dupN 后缀
    """
    target = Path(target_dir).resolve()
    src_images_origin = target / "images_origin_all"
    if not src_images_origin.is_dir():
        raise FileNotFoundError(f"missing directory: {src_images_origin}")
    dst_images_origin = target / "images_origin"
    if not dry_run:
        dst_images_origin.mkdir(parents=True, exist_ok=True)

    mapping_path = (
        Path(cam2pose_json_path).resolve()
        if cam2pose_json_path
        else (target / "h265_png_cam2_to_cams_match.json")
    )
    if not mapping_path.is_file():
        raise FileNotFoundError(f"missing cam2_to_cams_match json: {mapping_path}")

    with open(mapping_path, "r", encoding="utf-8") as f:
        cam2_match_raw = json.load(f)
    if not isinstance(cam2_match_raw, dict):
        raise ValueError(f"invalid cam2_to_cams_match json format: {mapping_path}")

    src_cam_dirs = {cam: path for cam, path in discover_cam_dirs(src_images_origin)}
    stats = {"moved": 0, "skipped": 0, "missing_mapping": 0, "collision_renamed": 0}

    # 构建查表: cam -> {timestamp_str: filename}
    ts_to_filename_by_cam: dict[str, dict[str, str]] = {}
    for cam, cam_dir in src_cam_dirs.items():
        entries = collect_image_timestamps(cam_dir)
        ts_to_filename_by_cam[cam] = {str(ts): name for ts, name in entries}

    used_dst_names: dict[str, set[str]] = defaultdict(set)

    for cam2_ts, row in sorted(cam2_match_raw.items(), key=lambda x: int(x[0])):
        if not isinstance(row, dict):
            continue
        for cam_name, cam_ts in sorted(row.items()):
            if cam_name not in ts_to_filename_by_cam:
                stats["missing_mapping"] += 1
                continue

            cam_ts_s = str(cam_ts)
            src_name = ts_to_filename_by_cam[cam_name].get(cam_ts_s)
            if src_name is None:
                stats["missing_mapping"] += 1
                continue

            src_path = src_cam_dirs[cam_name] / src_name
            if not src_path.exists():
                stats["missing_mapping"] += 1
                continue

            ext = src_path.suffix.lower()
            dst_cam_dir = dst_images_origin / cam_name
            if not dry_run:
                dst_cam_dir.mkdir(parents=True, exist_ok=True)

            dst_name = f"{cam2_ts}{ext}"
            dup_idx = 1
            while dst_name in used_dst_names[cam_name]:
                dst_name = f"{cam2_ts}_dup{dup_idx}{ext}"
                dup_idx += 1
            if dup_idx > 1:
                stats["collision_renamed"] += 1
            used_dst_names[cam_name].add(dst_name)
            dst_path = dst_cam_dir / dst_name

            if dry_run:
                # print(f"[DRY-RUN] {src_path} -> {dst_path}")
                stats["moved"] += 1
                continue

            src_path.rename(dst_path)
            stats["moved"] += 1

    # 源目录中可解析时间戳但未匹配到的文件统计为 skipped
    if not dry_run:
        for cam, mapping in ts_to_filename_by_cam.items():
            total = len(mapping)
            used = len(used_dst_names.get(cam, set()))
            if total > used:
                stats["skipped"] += total - used

    mode = "DRY-RUN" if dry_run else "DONE"
    print(
        f"[{mode}] rename summary: moved={stats['moved']}, "
        f"skipped={stats['skipped']}, missing_mapping={stats['missing_mapping']}, "
        f"collision_renamed={stats['collision_renamed']}"
    )
    return stats


def update_calib_and_timestamp2slice_by_cam2_match(
    target_dir: str | Path,
    match_json_path: str | Path | None = None,
    local_pose_lookup_interval: float = 0.1,
    global_pose_lookup_interval: float = 0.5,
) -> dict[str, int]:
    """
    基于 h265_png_cam2_to_cams_match.json 的 cam2 时间戳，重算并更新:
      - calib.json: local_pose / global_pose / id2timestamp
      - timestamp2slice.json

    同时备份原始文件为:
      - dataloader_calib.json
      - dataloader_timestamp2slice.json
    """
    target = Path(target_dir).resolve()
    calib_path = target / "calib.json"
    t2s_path = target / "timestamp2slice.json"
    if not calib_path.is_file():
        raise FileNotFoundError(f"missing file: {calib_path}")
    if not t2s_path.is_file():
        raise FileNotFoundError(f"missing file: {t2s_path}")

    match_path = (
        Path(match_json_path).resolve()
        if match_json_path
        else (target / "h265_png_cam2_to_cams_match.json")
    )
    if not match_path.is_file():
        raise FileNotFoundError(f"missing match json: {match_path}")

    # 备份 dataloader_*（每次覆盖为当前“原始”状态）
    dataloader_calib = target / "dataloader_calib.json"
    dataloader_t2s = target / "dataloader_timestamp2slice.json"
    shutil.copy2(calib_path, dataloader_calib)
    shutil.copy2(t2s_path, dataloader_t2s)

    calib = json.load(open(calib_path, "r", encoding="utf-8"))
    match_data = json.load(open(match_path, "r", encoding="utf-8"))
    if not isinstance(match_data, dict):
        raise ValueError(f"invalid match json format: {match_path}")

    local_pose_topic_path = target / "LocalPoseTopic.json"
    if not local_pose_topic_path.is_file():
        raise FileNotFoundError(f"missing file: {local_pose_topic_path}")
    local_pose_topic = json.load(open(local_pose_topic_path, "r", encoding="utf-8"))
    if not isinstance(local_pose_topic, list):
        raise ValueError("LocalPoseTopic.json format invalid: expected list")

    ecef2enu = get_ecef2enu()
    local_pose_buffer, global_pose_buffer = get_pose_buffer_from_localpose_topic(
        local_pose_topic, ecef2enu, str(target)
    )
    if not local_pose_buffer or not global_pose_buffer:
        raise ValueError("LocalPoseTopic.json parsed pose buffer is empty")

    cam2_ts_list = sorted(int(ts) for ts in match_data.keys())
    new_local_pose: dict[str, list] = {}
    new_global_pose: dict[str, list] = {}
    new_id2timestamp: dict[str, int] = {}
    new_timestamp2slice: dict[str, int] = {}

    valid_count = 0
    for cam2_ts in cam2_ts_list:
        curr_local_pose = lookup_pose(local_pose_buffer, cam2_ts, local_pose_lookup_interval)
        if curr_local_pose is None:
            raise ValueError(f"no local pose found for cam2_ts: {cam2_ts} in h265 image")
        curr_global_pose = lookup_pose(global_pose_buffer, cam2_ts, global_pose_lookup_interval)
        if curr_global_pose is None:
            raise ValueError(f"no global pose found for cam2_ts: {cam2_ts} in h265 image")

        ts_key = str(cam2_ts)
        new_local_pose[ts_key] = curr_local_pose.tolist()
        new_global_pose[ts_key] = curr_global_pose.tolist()
        new_id2timestamp[str(valid_count)] = cam2_ts
        new_timestamp2slice[ts_key] = valid_count
        valid_count += 1

    if valid_count == 0:
        raise ValueError("no valid matched cam2 timestamps after lookup_pose")

    calib["local_pose"] = new_local_pose
    calib["global_pose"] = new_global_pose
    calib["id2timestamp"] = new_id2timestamp

    new_slice_id = {ts: str(uuid.uuid4()) for ts in new_timestamp2slice.keys()}
    calib["slice_id"] = new_slice_id

    with open(calib_path, "w", encoding="utf-8") as f:
        json.dump(calib, f, indent=4, ensure_ascii=False)
    with open(t2s_path, "w", encoding="utf-8") as f:
        json.dump(new_timestamp2slice, f, indent=4, ensure_ascii=False)

    print(
        f"[INFO] updated calib/timestamp2slice by matched cam2 timestamps: "
        f"valid={valid_count}, total_matched={len(cam2_ts_list)}"
    )
    print(f"[INFO] backup created: {dataloader_calib}, {dataloader_t2s}")
    return {
        "total_matched": len(cam2_ts_list),
        "valid_updated": valid_count,
        "dropped": len(cam2_ts_list) - valid_count,
    }


def run_target_directory(
    target: Path,
    output_dir: Path | None = None,
    stats_out: str | None = None,
) -> None:
    """
    以 cam2 时间戳为基准，绑定每个 cam2 帧与其它相机最近时间戳。

    输出:
      - h265_png_cam2_to_cams.json: {cam2_ts: {cam2: cam2_ts, cam0: nearest_ts, ...}}
      - h265_png_cams_to_cam2.json: {camX: {camX_ts: cam2_ts, ...}, ...}
      - h265_png_timestamp_gap.png
    """
    target = target.resolve()
    out_root = (output_dir or target).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    images_origin = target / "images_origin_all"
    cam_dirs = discover_cam_dirs(images_origin)
    if not cam_dirs:
        raise FileNotFoundError(f"{images_origin} 下未找到相机子目录")

    cam_to_entries: dict[str, list[tuple[int, str]]] = {}
    for cam_name, cam_path in cam_dirs:
        entries = collect_image_timestamps(cam_path)
        if entries:
            cam_to_entries[cam_name] = entries
        else:
            print(f"[WARN] {cam_name}: 无有效时间戳图片，跳过")

    if "cam2" not in cam_to_entries:
        raise ValueError("未找到 cam2 或 cam2 下没有可解析时间戳的图片")

    cam2_entries = cam_to_entries["cam2"]
    cam2_timestamps = sorted(ts for ts, _ in cam2_entries)

    # cam2_ts -> {cam: nearest_ts}
    cam2_to_cams: dict[str, dict[str, str]] = {}
    # cam -> {cam_ts: cam2_ts}
    cams_to_cam2: dict[str, dict[str, str]] = defaultdict(dict)
    per_cam_deltas_sec: dict[str, list[float]] = defaultdict(list)
    per_cam_pose_gap_series: dict[str, list[tuple[int, float]]] = defaultdict(list)

    # cam2 本身不参与绘图统计（只作为基准）
    cams_to_cam2["cam2"] = {_ts_key(ts): _ts_key(ts) for ts in cam2_timestamps}

    for cam2_ts in cam2_timestamps:
        row: dict[str, str] = {"cam2": _ts_key(cam2_ts)}
        for cam_name, entries in sorted(cam_to_entries.items()):
            if cam_name == "cam2":
                continue
            ts_list = [t for t, _ in entries]
            nearest = nearest_ts(ts_list, cam2_ts)
            row[cam_name] = _ts_key(nearest)
            cams_to_cam2[cam_name][_ts_key(nearest)] = _ts_key(cam2_ts)
            gap_sec = (nearest - cam2_ts) / NSEC_PER_S  # camX - cam2
            per_cam_deltas_sec[cam_name].append(gap_sec)
            per_cam_pose_gap_series[cam_name].append((cam2_ts, gap_sec))
        cam2_to_cams[_ts_key(cam2_ts)] = row

    cam2_to_cams_sorted = {
        k: dict(sorted(v.items()))
        for k, v in sorted(cam2_to_cams.items(), key=lambda x: int(x[0]))
    }
    cams_to_cam2_sorted = {
        cam: dict(sorted(mapping.items(), key=lambda x: int(x[0])))
        for cam, mapping in sorted(cams_to_cam2.items())
    }

    cam2_to_cams_path = out_root / "h265_png_cam2_to_cams.json"
    cams_to_cam2_path = out_root / "h265_png_cams_to_cam2.json"
    with open(cam2_to_cams_path, "w", encoding="utf-8") as f:
        json.dump(cam2_to_cams_sorted, f, indent=2, ensure_ascii=False)
    with open(cams_to_cam2_path, "w", encoding="utf-8") as f:
        json.dump(cams_to_cam2_sorted, f, indent=2, ensure_ascii=False)
    print(f"已写入: {cam2_to_cams_path}\n已写入: {cams_to_cam2_path}")

    strict_match = build_cam2_strict_matches(
        cam2_to_cams=cam2_to_cams_sorted,
        all_cams=list(cam_to_entries.keys()),
        max_gap_sec=CAM2_MATCH_MAX_GAP_SEC,
    )
    strict_match_path = out_root / "h265_png_cam2_to_cams_match.json"
    with open(strict_match_path, "w", encoding="utf-8") as f:
        json.dump(strict_match, f, indent=2, ensure_ascii=False)
    print(
        f"已写入: {strict_match_path} "
        f"(groups={len(strict_match)}, abs_gap<{CAM2_MATCH_MAX_GAP_SEC}s, one-to-one)"
    )

    # 图像绘制仅使用 strict_match（matched）结果
    matched_pose_gap_series = build_gap_series_from_cam2_groups(strict_match)

    # 输出每个非 cam2 相机相对 cam2 的差值统计（全量）
    stat_lines = ["\n======== gap stats by camera (camX_ts - cam2_ts, seconds) ========"]
    for cam_name in sorted(per_cam_deltas_sec.keys()):
        if cam_name == "cam2":
            continue
        deltas_nsec = [int(round(v * NSEC_PER_S)) for v in per_cam_deltas_sec[cam_name]]
        stat_lines.append(f"\n--- {cam_name} ---\n{summarize_deltas(deltas_nsec)}")
    global_stats = "\n".join(stat_lines)
    print(global_stats)

    if stats_out:
        sp = Path(stats_out)
        sp.parent.mkdir(parents=True, exist_ok=True)
        with open(sp, "w", encoding="utf-8") as f:
            f.write(global_stats + "\n")
        print(f"已写入统计: {sp.resolve()}")

    if matched_pose_gap_series:
        matched_pose_gap_series = {
            cam: keep_closest_gap_per_pose(series)
            for cam, series in matched_pose_gap_series.items()
        }
        tl_path = out_root / "h265_png_timestamp_gap.png"
        plot_timestamp_gap_vs_pose_time(dict(matched_pose_gap_series), tl_path)


def match_localpose_to_h265_images() -> None:
    parser = argparse.ArgumentParser(
        description="LocalPoseTopic 与 images_origin 多相机图片时间戳对齐，生成 cam2pose.json / pose2cam.json"
    )
    parser.add_argument(
        "--target",
        type=str,
        default="/workspace/yangxh7@xiaopeng.com/datasets/xpeng/subrun_timeline_test3/c-143f2430-dc86-39a5-a5a9-315c13c92da1",
        help="目标目录(含 LocalPoseTopic.json 与 images_origin/)",
    )
    parser.add_argument(
        "--stats-out", type=str, default="", help="将统计写入文本文件(时间差为秒，由纳秒差/1e9)"
    )
    
    args = parser.parse_args()
    run_target_directory(
        Path(args.target),
        stats_out=args.stats_out or None,
    )
    return



if __name__ == "__main__":
    match_localpose_to_h265_images()
