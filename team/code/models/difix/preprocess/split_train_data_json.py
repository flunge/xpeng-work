import argparse
import json
import os
from pathlib import Path


def split_evenly(items, num_parts):
    total = len(items)
    base = total // num_parts
    remainder = total % num_parts

    parts = []
    start = 0
    for idx in range(num_parts):
        extra = 1 if idx < remainder else 0
        end = start + base + extra
        parts.append(items[start:end])
        start = end
    return parts


def load_train_data(path):
    """
    Support both:
    1) JSON array: [ {...}, {...} ]
    2) JSONL: one JSON object per line
    """
    with open(path, "r", encoding="utf-8") as f:
        content = f.read().strip()

    if not content:
        return []

    if content[0] == "[":
        return json.loads(content)

    data = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        data.append(json.loads(line))
    return data


def main():
    #############################  设置开始  ######################################
    input_folder = "/workspace/yangxh7@xiaopeng.com/codes/3dgs/models/difix/debug_utils/train_data_full_0304"
    input_json = os.path.join(input_folder, "train_data.json")
    num_parts = 20   # 设置为4，则把train_data.json分成4份
    #############################  设置结束  ######################################
    
    data = load_train_data(input_json)
    parts = split_evenly(data, num_parts)

    output_dir = Path(os.path.join(input_folder, "train_data_parts"))
    os.makedirs(output_dir, exist_ok=True)
    output_prefix = "train_data_part"
    for i, part in enumerate(parts, start=1):
        output_path = os.path.join(output_dir, f"{output_prefix}_{i}.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(part, f, indent=4, ensure_ascii=False)
        print(f"written: {output_path} ({len(part)} items)")


if __name__ == "__main__":
    main()
