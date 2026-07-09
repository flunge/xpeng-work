"""
从 dataset json 生成同时带 ref_image 和 test split 的新文件。

支持两种模式：
1. 生成模式：补 ref_image（已有非空 ref_image 的样本跳过），重建 test split，并保存新文件。
2. 检查模式：直接读取已有 json，只执行 check_ref_in_window。
"""
import bisect
import json
import os
import random
from typing import Dict, List, Tuple


def _iter_split_dicts(dataset: Dict):
    for split_name in ("train", "test"):
        split_data = dataset.get(split_name)
        if isinstance(split_data, dict):
            yield split_name, split_data


def _extract_cam_name(sample: Dict) -> str:
    image_path = sample.get("image")
    if isinstance(image_path, str) and image_path:
        return os.path.basename(os.path.dirname(image_path)) or "unknown_cam"
    cam_name = sample.get("cam_name")
    if isinstance(cam_name, str) and cam_name:
        return cam_name
    return "unknown_cam"


def build_index(dataset: Dict) -> Dict[Tuple[str, str], List[Tuple[int, str]]]:
    """(clip_id, cam_name) -> [(frame_id, target_image), ...]，按 frame_id 排序。"""
    index: Dict[Tuple[str, str], List[Tuple[int, str]]] = {}
    for _, split_data in _iter_split_dicts(dataset):
        for sample in split_data.values():
            clip_id = sample.get("clip_id")
            frame_id = sample.get("frame_id")
            target_image = sample.get("target_image")
            if clip_id is None or frame_id is None or not target_image:
                continue
            cam_name = _extract_cam_name(sample)
            index.setdefault((clip_id, cam_name), []).append((frame_id, target_image))

    for key in index:
        index[key].sort(key=lambda x: x[0])
    return index


def pick_ref_from_index(
    index: Dict[Tuple[str, str], List[Tuple[int, str]]],
    clip_id: str,
    cam_name: str,
    frame_id: int,
    window_ns: int,
    rng: random.Random,
    current_target_image: str = "",
    percent_use_current_target_image: float = 0.01,
) -> str:
    """
    同 clip 同 cam、时间戳在 [frame_id - window_ns, frame_id + window_ns] 内，
    且不为当前帧的随机一帧 target_image；1/100 概率直接用当前帧 target_image。
    """
    if current_target_image and rng.random() < percent_use_current_target_image:
        return current_target_image

    arr = index.get((clip_id, cam_name))
    if not arr:
        return ""

    low = frame_id - window_ns
    high = frame_id + window_ns
    lo = bisect.bisect_left(arr, (low, ""))
    hi = bisect.bisect_right(arr, (high + 1, ""))
    candidates = [(fid, path) for fid, path in arr[lo:hi] if fid != frame_id]
    if not candidates:
        return ""
    return rng.choice(candidates)[1]


def _has_ref_image(sample: Dict) -> bool:
    ref = sample.get("ref_image")
    return isinstance(ref, str) and bool(ref.strip())


def add_ref_to_dataset(
    dataset: Dict,
    window_ns: int,
    percent_use_current_target_image: float = 0.01,
    seed: int = 42,
) -> Tuple[int, int]:
    """
    为样本补充 ref_image。已有非空 ref_image 的样本跳过。

    Returns:
        (added_count, skipped_count)
    """
    index = build_index(dataset)
    rng = random.Random(seed)
    added_count = 0
    skipped_count = 0

    for _, split_data in _iter_split_dicts(dataset):
        for sample in split_data.values():
            if _has_ref_image(sample):
                skipped_count += 1
                continue

            frame_id = sample.get("frame_id")
            clip_id = sample.get("clip_id")
            cam_name = _extract_cam_name(sample if isinstance(sample, dict) else {})
            if frame_id is None or not clip_id:
                sample["ref_image"] = ""
                continue
            sample["ref_image"] = pick_ref_from_index(
                index=index,
                clip_id=clip_id,
                cam_name=cam_name,
                frame_id=frame_id,
                window_ns=window_ns,
                rng=rng,
                current_target_image=sample.get("target_image") or "",
                percent_use_current_target_image=percent_use_current_target_image,
            )
            added_count += 1

    print(f"ref_image: added={added_count}, skipped(existing)={skipped_count}")
    return added_count, skipped_count


def move_random_train_to_test_per_cam(
    dataset: Dict, n_per_cam: int = 200, seed: int = 42
) -> Tuple[int, Dict[str, int]]:
    """
    清空现有 test，并从 train 中按相机随机抽样移动到新的 test。

    Returns:
    - total moved count
    - moved count per camera
    """
    if "train" not in dataset or not isinstance(dataset["train"], dict):
        raise ValueError('dataset must contain dict field "train"')

    train_data: Dict = dataset["train"]
    dataset["test"] = {}
    test_data: Dict = dataset["test"]

    if not train_data:
        return 0, {}

    rng = random.Random(seed)
    n_per_cam = max(0, n_per_cam)

    cam_to_keys: Dict[str, List[str]] = {}
    for key, sample in train_data.items():
        cam_name = _extract_cam_name(sample if isinstance(sample, dict) else {})
        cam_to_keys.setdefault(cam_name, []).append(key)

    moved_total = 0
    moved_per_cam: Dict[str, int] = {}
    for cam_name, keys in cam_to_keys.items():
        move_count = min(n_per_cam, len(keys))
        if move_count <= 0:
            continue
        selected_keys = rng.sample(keys, move_count)
        for key in selected_keys:
            test_data[key] = train_data.pop(key)
        moved_per_cam[cam_name] = move_count
        moved_total += move_count

    return moved_total, moved_per_cam


def _timestamp_from_path(path: str):
    if not path:
        return None
    name = os.path.basename(path)
    stem, _ = os.path.splitext(name)
    try:
        return int(stem)
    except ValueError:
        return None


def _save_delta_histogram(
    deltas_sec: List[float], window_ns: int, dataset_name: str = ""
) -> str:
    if not deltas_sec:
        return ""

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("未安装 matplotlib，跳过柱状图绘制。")
        return ""

    if dataset_name:
        base_path = os.path.splitext(os.path.abspath(dataset_name))[0]
        output_path = base_path + "_ref_delta_hist.png"
    else:
        output_path = os.path.abspath("ref_delta_hist.png")

    window_sec = window_ns / 1e9
    plt.figure(figsize=(10, 6))
    plt.hist(deltas_sec, bins=50, range=(-window_sec, window_sec))
    plt.xlabel("ref_ts - target_ts (seconds)")
    plt.ylabel("Count")
    plt.title("Histogram of ref_ts - target_ts")
    plt.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()
    return output_path


def check_ref_in_window(dataset: Dict, window_ns: int, dataset_name: str = "") -> None:
    total = 0
    empty_ref = 0
    invalid_ts = 0
    same_frame = 0
    out_of_window = 0
    ok = 0
    deltas_ns: List[int] = []

    for split_name, split_data in _iter_split_dicts(dataset):
        for sample in split_data.values():
            total += 1
            ref_path = sample.get("ref_image") or ""
            target_path = sample.get("target_image") or ""
            if not ref_path:
                empty_ref += 1
                continue
            ref_ts = _timestamp_from_path(ref_path)
            target_ts = _timestamp_from_path(target_path)
            if ref_ts is None or target_ts is None:
                invalid_ts += 1
                continue
            if ref_ts == target_ts:
                same_frame += 1
                continue
            delta_ns = ref_ts - target_ts
            if abs(delta_ns) > window_ns:
                out_of_window += 1
                continue
            ok += 1
            deltas_ns.append(delta_ns)

    print(f"检查文件: {dataset_name or '<in-memory>'}")
    print(f"window_ns: ±{window_ns} (±{window_ns / 1e9:.2f} 秒)")
    print(f"总样本(train+test): {total}")
    print(f"  ref 为空: {empty_ref}")
    print(f"  文件名无法解析时间戳: {invalid_ts}")
    print(f"  ref 与 target 同帧: {same_frame}")
    print(f"  ref 超出时间窗口: {out_of_window}")
    print(f"  满足前后两秒内且不同帧: {ok}")
    if deltas_ns:
        deltas_sec = [delta / 1e9 for delta in deltas_ns]
        print(
            "时间差 ref_ts - target_ts 分布 (秒): "
            f"min={min(deltas_sec):.6f}, max={max(deltas_sec):.6f}, "
            f"mean={sum(deltas_sec) / len(deltas_sec):.6f}"
        )
        hist_path = _save_delta_histogram(deltas_sec, window_ns=window_ns, dataset_name=dataset_name)
        if hist_path:
            print(f"柱状图已保存: {hist_path}")
    else:
        print("无满足条件的样本，无法统计时间差分布。")


if __name__ == "__main__":
    ############################################
    check_only = False
    input_json = "/workspace/yangxh7@xiaopeng.com/difix3D_train/train_v6/output_dataset_car_switch.json"
    window_ns = 3 * 10**9     # 时间窗口2.5秒内随机选择ref_image
    num_move_per_cam = 200      # 每个相机移动200个样本到test
    random_seed = 21
    percent_use_current_target_image = 1   # 这个概率直接用当前帧target_image
    ############################################
    
    input_path = os.path.abspath(input_json)
    base_dir = os.path.dirname(input_path)
    name_no_ext, ext = os.path.splitext(os.path.basename(input_path))
    output_path = os.path.join(base_dir, name_no_ext + "_ref_test" + (ext or ".json"))

    if check_only:
        print(f"Checking only: {output_path}")
        check_path = os.path.abspath(output_path)
        with open(check_path, "r", encoding="utf-8") as f:
            dataset = json.load(f)
        check_ref_in_window(dataset, window_ns=window_ns, dataset_name=check_path)
    else:
        print(f"Generating ref_test: {input_json}")
        with open(input_path, "r", encoding="utf-8") as f:
            dataset = json.load(f)

        before_train = len(dataset.get("train", {})) if isinstance(dataset.get("train"), dict) else 0
        before_test = len(dataset.get("test", {})) if isinstance(dataset.get("test"), dict) else 0

        add_ref_to_dataset(
            dataset,
            window_ns=window_ns,
            seed=random_seed,
            percent_use_current_target_image=percent_use_current_target_image,
        )
        moved, moved_per_cam = move_random_train_to_test_per_cam(
            dataset, n_per_cam=num_move_per_cam, seed=random_seed
        )

        after_train = len(dataset.get("train", {})) if isinstance(dataset.get("train"), dict) else 0
        after_test = len(dataset.get("test", {})) if isinstance(dataset.get("test"), dict) else 0

        os.makedirs(base_dir, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(dataset, f, indent=2, ensure_ascii=False)

        print(f"saved: {output_path}")
        print(
            f"train: {before_train}->{after_train}, "
            f"test: {before_test}->{after_test}, "
            f"moved={moved}, seed={random_seed}"
        )
        print(f"per_cam_target={num_move_per_cam}, per_cam_moved={moved_per_cam}")
        check_ref_in_window(dataset, window_ns=window_ns, dataset_name=output_path)
