#!/usr/bin/env python3
import argparse
import json
import os
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from typing import Any, Dict, Iterable, List, Set, Tuple

from PIL import Image
from tqdm import tqdm


def _is_entry_dict(value: Any) -> bool:
    return isinstance(value, dict) and any(k in value for k in ("image", "target_image", "ref_image"))


def _infer_json_layout(data: Dict[str, Any]) -> str:
    if not isinstance(data, dict):
        raise ValueError("Input JSON must be an object/dict.")
    if len(data) == 0:
        return "flat"

    first_value = next(iter(data.values()))
    if _is_entry_dict(first_value):
        return "flat"
    if isinstance(first_value, dict):
        return "split"
    raise ValueError("Unsupported JSON format. Expect flat entries or split->entries format.")


def _safe_camera_name(entry: Dict[str, Any]) -> str:
    target_path = entry.get("target_image")
    if isinstance(target_path, str) and target_path:
        return os.path.basename(os.path.dirname(target_path)) or "unknown"
    input_path = entry.get("image")
    if isinstance(input_path, str) and input_path:
        return os.path.basename(os.path.dirname(input_path)) or "unknown"
    return "unknown"


def _validate_image(path: str, key_name: str) -> str | None:
    if not isinstance(path, str) or path == "":
        return f"{key_name}: empty path"
    if not os.path.exists(path):
        return f"{key_name}: file not found: {path}"
    try:
        with Image.open(path) as img:
            img.load()
    except Exception as exc:  # noqa: BLE001
        return f"{key_name}: cannot load image: {path}; err={exc}"
    return None


def _validate_path_task(args: Tuple[str, str]) -> Tuple[str, str, str | None]:
    key_name, path = args
    return key_name, path, _validate_image(path, key_name)


def _iter_path_tasks(entries: Dict[str, Dict[str, Any]], fields: Tuple[str, ...]) -> Iterable[Tuple[str, str]]:
    seen: Set[Tuple[str, str]] = set()
    for entry in entries.values():
        for field in fields:
            path = entry.get(field)
            if not isinstance(path, str) or path == "":
                continue
            task = (field, path)
            if task in seen:
                continue
            seen.add(task)
            yield task


def _process_entries(
    entries: Dict[str, Dict[str, Any]],
    workers: int,
    backend: str,
    fields: Tuple[str, ...],
    chunksize: int,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, Dict[str, int]], Dict[str, List[str]]]:
    valid_entries: Dict[str, Dict[str, Any]] = {}
    invalid_entries: Dict[str, Dict[str, Any]] = {}
    errors_by_entry: Dict[str, List[str]] = {}
    stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "usable": 0, "unusable": 0})

    executor_cls = ThreadPoolExecutor if backend == "thread" else ProcessPoolExecutor
    path_tasks = list(_iter_path_tasks(entries, fields))
    total_paths = len(path_tasks)
    path_errors: Dict[Tuple[str, str], str] = {}
    checked_paths = 0
    next_progress_pct = 5

    with executor_cls(max_workers=workers) as executor:
        results = executor.map(_validate_path_task, path_tasks, chunksize=chunksize)
        for key_name, path, error in tqdm(results, total=total_paths, desc="Checking unique paths", ncols=120):
            checked_paths += 1
            if error is not None:
                path_errors[(key_name, path)] = error
            if total_paths > 0:
                progress_pct = checked_paths * 100.0 / total_paths
                while next_progress_pct <= 100 and progress_pct >= next_progress_pct:
                    print(
                        f"[progress] {next_progress_pct}% ({checked_paths}/{total_paths}) unique paths checked.",
                        flush=True,
                    )
                    next_progress_pct += 5

    for entry_id, entry in tqdm(entries.items(), total=len(entries), desc="Building output json", ncols=120):
        camera = _safe_camera_name(entry)
        stats[camera]["total"] += 1
        errors: List[str] = []
        for field in fields:
            path = entry.get(field)
            if not isinstance(path, str) or path == "":
                errors.append(f"{field}: empty path")
                continue
            error = path_errors.get((field, path))
            if error is not None:
                errors.append(error)
        if errors:
            invalid_entries[entry_id] = entry
            stats[camera]["unusable"] += 1
            errors_by_entry[entry_id] = errors
        else:
            valid_entries[entry_id] = entry
            stats[camera]["usable"] += 1

    return valid_entries, invalid_entries, stats, errors_by_entry


def _merge_stats(all_stats: Dict[str, Dict[str, int]], split_stats: Dict[str, Dict[str, int]]) -> None:
    for cam, values in split_stats.items():
        if cam not in all_stats:
            all_stats[cam] = {"total": 0, "usable": 0, "unusable": 0}
        for key in ("total", "usable", "unusable"):
            all_stats[cam][key] += values.get(key, 0)


def _print_stats(stats: Dict[str, Dict[str, int]]) -> None:
    print("\nPer-camera stats:")
    print(f"{'camera':<10} {'total':>10} {'usable':>10} {'unusable':>10}")
    print("-" * 44)
    for cam in sorted(stats.keys()):
        row = stats[cam]
        print(f"{cam:<10} {row['total']:>10} {row['usable']:>10} {row['unusable']:>10}")


def _save_json(path: str, data: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Split invalid image entries from dataset JSON with parallel checking.")
    parser.add_argument("--input-json", required=True, help="Input dataset JSON path.")
    parser.add_argument("--output-valid-json", required=True, help="Output JSON path for valid entries.")
    parser.add_argument("--output-invalid-json", required=True, help="Output JSON path for invalid entries.")
    parser.add_argument(
        "--splits",
        nargs="*",
        default=None,
        help="For split-format JSON, only process these splits (e.g. train test). Default: all splits.",
    )
    parser.add_argument("--workers", type=int, default=max(4, (os.cpu_count() or 8) // 2), help="Parallel workers.")
    parser.add_argument(
        "--backend",
        choices=("thread", "process"),
        default="thread",
        help="Parallel backend. IO-heavy workloads usually prefer thread.",
    )
    parser.add_argument(
        "--fields",
        nargs="+",
        choices=("image", "target_image", "ref_image"),
        default=("target_image",),
        help="Which image fields to validate. Default: target_image",
    )
    parser.add_argument("--chunksize", type=int, default=64, help="Chunksize for process/thread executor map.")
    parser.add_argument("--summary-json", default=None, help="Optional summary json output path.")
    parser.add_argument(
        "--errors-json",
        default=None,
        help="Optional output path for invalid-entry error reasons.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    fields = tuple(args.fields)

    with open(args.input_json, "r", encoding="utf-8") as f:
        input_data = json.load(f)

    layout = _infer_json_layout(input_data)

    valid_output: Dict[str, Any] = {}
    invalid_output: Dict[str, Any] = {}
    summary: Dict[str, Any] = {"per_camera": {}, "splits": {}}
    errors_output: Dict[str, Any] = {}

    if layout == "flat":
        valid_entries, invalid_entries, stats, errors = _process_entries(
            entries=input_data,
            workers=args.workers,
            backend=args.backend,
            fields=fields,
            chunksize=args.chunksize,
        )
        valid_output = valid_entries
        invalid_output = invalid_entries
        summary["splits"]["flat"] = {
            "total": len(input_data),
            "usable": len(valid_entries),
            "unusable": len(invalid_entries),
        }
        summary["per_camera"] = stats
        errors_output = errors
    else:
        all_stats: Dict[str, Dict[str, int]] = {}
        target_splits = set(args.splits) if args.splits else set(input_data.keys())
        for split_name, split_entries in input_data.items():
            if split_name not in target_splits:
                valid_output[split_name] = split_entries
                invalid_output[split_name] = {}
                continue
            if not isinstance(split_entries, dict):
                raise ValueError(f"Split '{split_name}' is not a dict of entries.")

            valid_entries, invalid_entries, split_stats, split_errors = _process_entries(
                entries=split_entries,
                workers=args.workers,
                backend=args.backend,
                fields=fields,
                chunksize=args.chunksize,
            )
            valid_output[split_name] = valid_entries
            invalid_output[split_name] = invalid_entries
            summary["splits"][split_name] = {
                "total": len(split_entries),
                "usable": len(valid_entries),
                "unusable": len(invalid_entries),
            }
            _merge_stats(all_stats, split_stats)
            errors_output[split_name] = split_errors

        summary["per_camera"] = all_stats

    _save_json(args.output_valid_json, valid_output)
    _save_json(args.output_invalid_json, invalid_output)
    if args.summary_json:
        _save_json(args.summary_json, summary)
    if args.errors_json:
        _save_json(args.errors_json, errors_output)

    _print_stats(summary["per_camera"])
    print("\nSplit stats:")
    for split_name in sorted(summary["splits"].keys()):
        row = summary["splits"][split_name]
        print(
            f"{split_name}: total={row['total']}, usable={row['usable']}, unusable={row['unusable']}"
        )
    print(f"\nValid JSON written to: {args.output_valid_json}")
    print(f"Invalid JSON written to: {args.output_invalid_json}")
    if args.summary_json:
        print(f"Summary JSON written to: {args.summary_json}")
    if args.errors_json:
        print(f"Errors JSON written to: {args.errors_json}")
    print(f"Validated fields: {', '.join(fields)}")


if __name__ == "__main__":
    main()


'''
nohup python filter_invalid_dataset_json.py \
  --input-json "/workspace/yangxh7@xiaopeng.com/difix3D_train/train_v5/output_dataset_interval1000_ref_test.valid.train.json" \
  --output-valid-json "/workspace/yangxh7@xiaopeng.com/difix3D_train/train_v5/train.valid.json" \
  --output-invalid-json "/workspace/yangxh7@xiaopeng.com/difix3D_train/train_v5/train.invalid.json" \
  --splits train \
  --workers 32 \
  --backend thread \
  --summary-json "/workspace/yangxh7@xiaopeng.com/difix3D_train/train_v5/train.summary.json" \
  --errors-json "/workspace/yangxh7@xiaopeng.com/difix3D_train/train_v5/train.errors.json" \
> run.log 2>&1 &
'''