import argparse
import json
import os
import time

from pathlib import Path
from concurrent.futures import ProcessPoolExecutor

from PIL import Image


def is_valid_image(path: str) -> tuple[bool, str]:
    if not path:
        return False, "empty_path"
    if not os.path.exists(path):
        return False, "not_found"
    try:
        # Lightweight offline check: verify image file integrity without tensor conversion.
        with Image.open(path) as input_img:
            input_img.verify()
        return True, ""
    except Exception as exc:
        return False, f"decode_error:{type(exc).__name__}"


def build_output_path(dataset_path: str) -> str:
    p = Path(dataset_path)
    if p.suffix.lower() == ".json":
        return str(p.with_name(f"{p.stem}_valid.json"))
    return f"{dataset_path}_valid.json"


def validate_one_sample(item: tuple[str, dict]) -> tuple[str, bool, str]:
    sample_id, sample = item
    image_path = sample.get("image", "")
    target_image_path = sample.get("target_image", "")
    ref_image_path = sample.get("ref_image", None)

    ok, _ = is_valid_image(image_path)
    if not ok:
        return sample_id, False, "image"

    ok, _ = is_valid_image(target_image_path)
    if not ok:
        return sample_id, False, "target_image"

    if ref_image_path is not None:
        ok, _ = is_valid_image(ref_image_path)
        if not ok:
            return sample_id, False, "ref_image"

    return sample_id, True, ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset_path", type=str, required=True, help="Path to dataset json")
    parser.add_argument("--num_workers", type=int, default=32, help="Number of CPU workers for offline validation")
    args = parser.parse_args()

    with open(args.dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "train" not in data or not isinstance(data["train"], dict):
        raise ValueError("Invalid dataset json: missing dict field 'train'")

    train_data = data["train"]
    valid_train = {}
    invalid_reasons = {
        "image": 0,
        "target_image": 0,
        "ref_image": 0,
    }

    items = list(train_data.items())
    total = len(items)
    start_time = time.time()
    progress_interval = max(1000, total // 100) if total > 0 else 1
    next_report = progress_interval

    def consume_result(idx: int, result: tuple[str, bool, str]) -> None:
        nonlocal next_report
        sample_id, is_valid, reason = result
        if is_valid:
            valid_train[sample_id] = train_data[sample_id]
        else:
            invalid_reasons[reason] += 1

        if idx >= next_report or idx == total:
            elapsed = max(time.time() - start_time, 1e-6)
            speed = idx / elapsed
            percent = (idx / total) * 100 if total > 0 else 100.0
            print(f"[progress] {idx}/{total} ({percent:.1f}%), {speed:.1f} samples/s", flush=True)
            next_report += progress_interval

    if args.num_workers <= 1:
        for idx, result in enumerate(map(validate_one_sample, items), start=1):
            consume_result(idx, result)
    else:
        # Keep result consumption inside executor context for real-time progress updates.
        with ProcessPoolExecutor(max_workers=args.num_workers) as ex:
            for idx, result in enumerate(ex.map(validate_one_sample, items, chunksize=256), start=1):
                consume_result(idx, result)

    output_data = dict(data)
    output_data["train"] = valid_train

    output_path = build_output_path(args.dataset_path)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    total = len(train_data)
    valid = len(valid_train)
    invalid = total - valid

    print(f"Input : {args.dataset_path}")
    print(f"Output: {output_path}")
    print(f"num_workers={args.num_workers}")
    print(f"Train samples total={total}, valid={valid}, invalid={invalid}")
    print(
        "Invalid breakdown: "
        f"image={invalid_reasons['image']}, "
        f"target_image={invalid_reasons['target_image']}, "
        f"ref_image={invalid_reasons['ref_image']}"
    )


if __name__ == "__main__":
    main()
