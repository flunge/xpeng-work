#!/usr/bin/env python3
"""
Split a metadata.json into train and test subsets.

Val split is handled in-code by train.py (see data.val_split in the YAML config).
This script only carves out a held-out test set; the remainder becomes train_metadata.json.

Usage:
    python split_dataset.py <--input_json> [--test_split 0.05] [--seed 42]

Output (same directory as input):
    train_metadata.json  (~95%)
    test_metadata.json   (~5%)
"""
import argparse
import json
import random
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_json", default="./data/metadata.json")
    parser.add_argument("--test_split", type=float, default=0.05,
                        help="Fraction for test set (default: 0.05)")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    assert 0 < args.test_split < 1.0, "test_split must be between 0 and 1"

    input_path = Path(args.input_json)
    with open(input_path) as f:
        data = json.load(f)

    random.seed(args.seed)
    indices = list(range(len(data)))
    random.shuffle(indices)

    n_test  = max(1, round(len(indices) * args.test_split))
    test_idx  = indices[:n_test]
    train_idx = indices[n_test:]

    splits = {
        "test":  [data[i] for i in test_idx],
        "train": [data[i] for i in train_idx],
    }

    out_dir = input_path.parent
    for split, items in splits.items():
        out_path = out_dir / f"{split}_metadata.json"
        with open(out_path, "w") as f:
            json.dump(items, f, indent=2, ensure_ascii=False)
        print(f"{split:5s}: {len(items):6d} samples -> {out_path}")


if __name__ == "__main__":
    main()
