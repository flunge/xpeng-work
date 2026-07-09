import argparse
import json
import os
import random
import re
from typing import Dict, List, Optional, Tuple

AUGMENTED_VEHICLE_NAMES = ["h93aes", "e29", "f01es"]


def parse_frame_id(file_name: str) -> Optional[int]:
    stem, ext = os.path.splitext(file_name)
    if ext.lower() != ".png":
        return None

    if stem.isdigit():
        return int(stem)

    match = re.search(r"(\d+)$", stem)
    if match is None:
        return None
    return int(match.group(1))


def get_sorted_frame_files(cam_dir: str) -> List[Tuple[int, str]]:
    frame_files: List[Tuple[int, str]] = []
    for name in os.listdir(cam_dir):
        frame_id = parse_frame_id(name)
        if frame_id is None:
            continue
        frame_files.append((frame_id, name))

    frame_files.sort(key=lambda x: (x[0], x[1]))
    return frame_files


def build_dataset_samples(
    train_data: List[Dict],
    data_root: str,
    target_root: str,
    timestamp_interval_seconds: float,
) -> Tuple[Dict[str, Dict], int]:
    """收集 base 样本：image 来自 simulator_render/。"""
    samples: Dict[str, Dict] = {}
    total_clips = 0
    total_samples = 0
    timestamp_interval_ns = int(timestamp_interval_seconds * 1_000_000_000)
    label = "base"

    for item in train_data:
        clip_id = item.get("clip_id")
        model_version = item.get("model_version")
        if not clip_id or not model_version:
            print(f"[WARN][{label}] skip invalid item: {item}")
            continue

        image_root = os.path.join(
            data_root,
            clip_id,
            model_version,
            "simulator_render",
            "redistort_rgb",
        )
        gt_root = os.path.join(target_root, clip_id, "images_origin")

        if not os.path.isdir(image_root):
            print(f"[WARN][{label}] image_root not found: {image_root}")
            continue
        if not os.path.isdir(gt_root):
            print(f"[WARN][{label}] gt_root not found: {gt_root}")
            continue

        total_clips += 1

        for cam_name in sorted(os.listdir(image_root)):
            cam_dir = os.path.join(image_root, cam_name)
            if not os.path.isdir(cam_dir):
                continue

            gt_cam_dir = os.path.join(gt_root, cam_name)
            if not os.path.isdir(gt_cam_dir):
                print(f"[WARN][{label}] gt cam dir not found: {gt_cam_dir}")
                continue

            cam_upper = cam_name.upper()
            frame_files = get_sorted_frame_files(cam_dir)
            last_kept_timestamp_ns: Optional[int] = None
            for frame_id, file_name in frame_files:
                if (
                    last_kept_timestamp_ns is not None
                    and frame_id - last_kept_timestamp_ns < timestamp_interval_ns
                ):
                    continue

                image_path = os.path.join(cam_dir, file_name)
                target_image_path = os.path.join(gt_cam_dir, file_name)
                if not os.path.exists(target_image_path):
                    print(f"[WARN][{label}] missing GT: {target_image_path}")
                    continue

                key = f"{clip_id}_{cam_name}_{frame_id}"
                sample = {
                    "image": image_path,
                    "target_image": target_image_path,
                    "prompt": f"Corrected rendering distortion for {cam_upper} camera view.",
                    "clip_id": clip_id,
                    "model_version": model_version,
                    "frame_id": frame_id,
                }

                samples[key] = sample
                total_samples += 1
                last_kept_timestamp_ns = frame_id

    print(f"[{label}] valid clips: {total_clips}, total samples: {total_samples}")
    return samples, total_clips


def build_augmented_dataset_samples(
    train_data: List[Dict],
    data_root: str,
    target_root: str,
    timestamp_interval_seconds: float,
    vehicle_name: str,
) -> Tuple[Dict[str, Dict], int]:
    """
    augmented 样本：
    - image: simulator_render/（原车型渲染）
    - ref_image: simulator_render_{vehicle}/（换车型渲染，作 ref）
    - target_image: difix_train/images_origin/（GT，逻辑不变）
    """
    samples: Dict[str, Dict] = {}
    total_clips = 0
    total_samples = 0
    timestamp_interval_ns = int(timestamp_interval_seconds * 1_000_000_000)
    label = vehicle_name

    for item in train_data:
        clip_id = item.get("clip_id")
        model_version = item.get("model_version")
        if not clip_id or not model_version:
            print(f"[WARN][{label}] skip invalid item: {item}")
            continue

        image_root = os.path.join(
            data_root,
            clip_id,
            model_version,
            "simulator_render",
            "redistort_rgb",
        )
        ref_root = os.path.join(
            data_root,
            clip_id,
            model_version,
            f"simulator_render_{vehicle_name}",
            "redistort_rgb",
        )
        gt_root = os.path.join(target_root, clip_id, "images_origin")

        if not os.path.isdir(image_root):
            print(f"[WARN][{label}] image_root not found: {image_root}")
            continue
        if not os.path.isdir(ref_root):
            print(f"[WARN][{label}] ref_root not found: {ref_root}")
            continue
        if not os.path.isdir(gt_root):
            print(f"[WARN][{label}] gt_root not found: {gt_root}")
            continue

        total_clips += 1

        for cam_name in sorted(os.listdir(image_root)):
            cam_dir = os.path.join(image_root, cam_name)
            if not os.path.isdir(cam_dir):
                continue

            ref_cam_dir = os.path.join(ref_root, cam_name)
            if not os.path.isdir(ref_cam_dir):
                print(f"[WARN][{label}] ref cam dir not found: {ref_cam_dir}")
                continue

            gt_cam_dir = os.path.join(gt_root, cam_name)
            if not os.path.isdir(gt_cam_dir):
                print(f"[WARN][{label}] gt cam dir not found: {gt_cam_dir}")
                continue

            cam_upper = cam_name.upper()
            frame_files = get_sorted_frame_files(cam_dir)
            last_kept_timestamp_ns: Optional[int] = None
            for frame_id, file_name in frame_files:
                if (
                    last_kept_timestamp_ns is not None
                    and frame_id - last_kept_timestamp_ns < timestamp_interval_ns
                ):
                    continue

                image_path = os.path.join(cam_dir, file_name)
                ref_image_path = os.path.join(ref_cam_dir, file_name)
                target_image_path = os.path.join(gt_cam_dir, file_name)

                if not os.path.exists(ref_image_path):
                    print(f"[WARN][{label}] missing ref_image: {ref_image_path}")
                    continue
                if not os.path.exists(target_image_path):
                    print(f"[WARN][{label}] missing GT: {target_image_path}")
                    continue

                key = f"{clip_id}_{vehicle_name}_{cam_name}_{frame_id}"
                sample = {
                    "image": image_path,
                    "ref_image": ref_image_path,
                    "target_image": target_image_path,
                    "prompt": f"Corrected rendering distortion for {cam_upper} camera view.",
                    "clip_id": clip_id,
                    "model_version": model_version,
                    "frame_id": frame_id,
                    "vehicle_type": vehicle_name,
                    "augmented": True,
                }

                samples[key] = sample
                total_samples += 1
                last_kept_timestamp_ns = frame_id

    print(f"[{label}] valid clips: {total_clips}, total samples: {total_samples}")
    return samples, total_clips


def build_dataset(
    train_data: List[Dict],
    data_root: str,
    target_root: str,
    timestamp_interval_seconds: float,
) -> Dict[str, Dict]:
    samples, _ = build_dataset_samples(
        train_data=train_data,
        data_root=data_root,
        target_root=target_root,
        timestamp_interval_seconds=timestamp_interval_seconds,
    )
    return {"train": samples, "test": {}}


def build_augmented_dataset(
    train_data: List[Dict],
    data_root: str,
    target_root: str,
    timestamp_interval_seconds: float,
    vehicle_names: Optional[List[str]] = None,
) -> Dict[str, Dict]:
    """augmented：image=simulator_render，ref_image=simulator_render_{vehicle}，target=GT。"""
    vehicles = vehicle_names or AUGMENTED_VEHICLE_NAMES
    all_samples: Dict[str, Dict] = {}
    for vehicle_name in vehicles:
        samples, _ = build_augmented_dataset_samples(
            train_data=train_data,
            data_root=data_root,
            target_root=target_root,
            timestamp_interval_seconds=timestamp_interval_seconds,
            vehicle_name=vehicle_name,
        )
        all_samples.update(samples)
    return {"train": all_samples, "test": {}}


def limit_train_data_clips(
    train_data: List[Dict],
    max_clip: Optional[int],
    label: str,
    seed: int = 42,
) -> List[Dict]:
    """从 train_data 中随机抽取至多 max_clip 条 clip。"""
    if max_clip is None or max_clip >= len(train_data):
        print(f"[{label}] clips: {len(train_data)} (no limit)")
        return train_data

    rng = random.Random(seed)
    picked = rng.sample(train_data, max_clip)
    print(f"[{label}] clips: {len(picked)} / {len(train_data)} (max={max_clip})")
    return picked


def load_train_data(input_path: str) -> List[Dict]:
    with open(input_path, "r", encoding="utf-8") as f:
        content = f.read()

    try:
        data = json.loads(content)
        if not isinstance(data, list):
            raise ValueError(f"Expected a JSON array in {input_path}.")
        return data
    except json.JSONDecodeError:
        pass

    train_data: List[Dict] = []
    for line_idx, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            item = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid JSONL at line {line_idx} in {input_path}: {exc}"
            ) from exc
        if not isinstance(item, dict):
            raise ValueError(
                f"Expected JSON object in JSONL at line {line_idx} in {input_path}."
            )
        train_data.append(item)

    if not train_data:
        raise ValueError(f"No valid records found in {input_path}.")
    return train_data


def main():
    parser = argparse.ArgumentParser(
        description="Generate custom_data.json from train_data.json with timestamp interval sampling."
    )
    parser.add_argument(
        "--input-json",
        default="/workspace/yangxh7@xiaopeng.com/codes/3dgs/models/difix/utils/train_data_415_0421/train_data.json",
        help="Path to train_data.json.",
    )
    parser.add_argument(
        "--augmented-json",
        default="/workspace/yangxh7@xiaopeng.com/codes/3dgs/models/difix/utils/train_data_415_0421/train_data_aug.json",
        help="Optional JSON/JSONL. image=simulator_render, ref_image=simulator_render_{vehicle} (3 types).",
    )
    parser.add_argument(
        "--output-json",
        default="/workspace/yangxh7@xiaopeng.com/nvfixer/train_v6/output_dataset_car_switch.json",
        help="Path to output dataset json.",
    )
    parser.add_argument(
        "--data-root",
        default="/workspace/group_share/adc-sim/users/cloudsim/difix/train_data",
        help="Root dir of difix training data.",
    )
    parser.add_argument(
        "--target-root",
        default="/workspace/group_share/adc-sim/users/difix_train/images_origin/",
        help="Root dir of target images.",
    )
    parser.add_argument(
        "--timestamp-interval-seconds",
        type=float,
        default=1.0,
        help="Keep one frame every N seconds based on nanosecond timestamps in image names.",
    )
    parser.add_argument(
        "--max-input-clip",
        type=int,
        default=2400,
        help="Max clips randomly picked from input-json (e.g. 3600 from 12000).",
    )
    parser.add_argument(
        "--max-augmented-clip",
        type=int,
        default=1200,
        help="Max clips from augmented-json; each clip adds h93aes/e29/f01es (3 vehicle dirs).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for clip subsampling.",
    )
    args = parser.parse_args()

    if args.timestamp_interval_seconds <= 0:
        raise ValueError("--timestamp-interval-seconds must be positive.")

    train_data = limit_train_data_clips(
        load_train_data(args.input_json),
        max_clip=args.max_input_clip,
        label="input",
        seed=args.seed,
    )
    base_dataset = build_dataset(
        train_data=train_data,
        data_root=args.data_root,
        target_root=args.target_root,
        timestamp_interval_seconds=args.timestamp_interval_seconds,
    )

    if args.augmented_json:
        aug_train_data = limit_train_data_clips(
            load_train_data(args.augmented_json),
            max_clip=args.max_augmented_clip,
            label="augmented",
            seed=args.seed,
        )
        aug_dataset = build_augmented_dataset(
            train_data=aug_train_data,
            data_root=args.data_root,
            target_root=args.target_root,
            timestamp_interval_seconds=args.timestamp_interval_seconds,
        )
        merged_train = dict(base_dataset["train"])
        merged_train.update(aug_dataset["train"])
        print(
            f"[merge] input samples: {len(base_dataset['train'])}, "
            f"augmented samples: {len(aug_dataset['train'])}, "
            f"total: {len(merged_train)}"
        )
        dataset = {"train": merged_train, "test": {}}
    else:
        dataset = base_dataset

    output_dir = os.path.dirname(args.output_json)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)

    print(f"saved json: {args.output_json}, train samples: {len(dataset['train'])}")


if __name__ == "__main__":
    main()
