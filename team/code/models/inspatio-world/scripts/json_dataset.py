import argparse
import json
import os
import re
from pathlib import Path


VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
_CAM_RE = re.compile(r"cam(\d+)", re.IGNORECASE)


def _scan_scene_directory(scene_dir: Path) -> list[tuple[Path, Path]]:
    """
    Scan a scene directory for GT/render pairs.
    Supports two structures:
      1. cam{N}_gt/rgb, cam{N}_render/rgb (or cam{N}_rgb/rgb) (with subdirs)
      2. cam{N}_gt.mp4, cam{N}_render.mp4 (or cam{N}_rgb.mp4) (flat files)
    Returns list of (gt_path, render_path) tuples.
    """
    gt_map: dict[str, Path] = {}
    render_map: dict[str, Path] = {}

    # Try to find cam{N}_gt and cam{N}_render (or cam{N}_rgb) directories or files
    for item in sorted(scene_dir.iterdir()):
        lower = item.name.lower()
        m = _CAM_RE.search(lower)
        if not m:
            continue
        cam_id = f"cam{m.group(1)}"

        if "gt" in lower:
            if item.is_dir():
                # Check for rgb subdirectory
                rgb_subdir = item / "rgb"
                if rgb_subdir.is_dir():
                    # Find first mp4 in rgb/ subdir
                    for f in sorted(rgb_subdir.iterdir()):
                        if f.suffix.lower() in VIDEO_EXTENSIONS:
                            gt_map[cam_id] = f
                            break
                else:
                    # Try direct mp4 in directory
                    for f in sorted(item.iterdir()):
                        if f.suffix.lower() in VIDEO_EXTENSIONS:
                            gt_map[cam_id] = f
                            break
            elif item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS:
                gt_map[cam_id] = item

        elif "render" in lower or "rgb" in lower:
            # Match both "render" and "rgb" naming
            if item.is_dir():
                # Check for rgb subdirectory
                rgb_subdir = item / "rgb"
                if rgb_subdir.is_dir():
                    for f in sorted(rgb_subdir.iterdir()):
                        if f.suffix.lower() in VIDEO_EXTENSIONS:
                            render_map[cam_id] = f
                            break
                else:
                    for f in sorted(item.iterdir()):
                        if f.suffix.lower() in VIDEO_EXTENSIONS:
                            render_map[cam_id] = f
                            break
            elif item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS:
                render_map[cam_id] = item

    pairs: list[tuple[Path, Path]] = []
    for cam_id in sorted(gt_map.keys() | render_map.keys()):
        gt_f = gt_map.get(cam_id)
        render_f = render_map.get(cam_id)
        if gt_f and render_f:
            pairs.append((gt_f, render_f))
        else:
            if not gt_f:
                print(f"[WARN] {scene_dir.name}/{cam_id}: missing GT video")
            if not render_f:
                print(f"[WARN] {scene_dir.name}/{cam_id}: missing render/rgb video")

    return pairs


def _is_dataset_scene_root(root_dir: Path) -> bool:
    """
    Check if root_dir is a dataset root (contains scene subdirectories).
    Look for subdirs that contain cam{N}_gt/render/rgb patterns.
    Returns True if subdirs contain cam patterns, False if they don't.
    """
    subdirs = [d for d in root_dir.iterdir() if d.is_dir()]
    if not subdirs:
        return False

    # Check if any subdir contains cam{N}_gt or cam{N}_(render|rgb) patterns
    for subdir in subdirs:
        for item in subdir.iterdir():
            lower = item.name.lower()
            if _CAM_RE.search(lower) and ("gt" in lower or "render" in lower or "rgb" in lower):
                return True
    return False


def _is_scene_directory(scene_dir: Path) -> bool:
    """
    Check if a directory is itself a scene (contains cam{N}_gt and cam{N}_(render|rgb) files/dirs).
    """
    for item in scene_dir.iterdir():
        lower = item.name.lower()
        if _CAM_RE.search(lower) and ("gt" in lower or "render" in lower or "rgb" in lower):
            return True
    return False


def parse_args():
    p = argparse.ArgumentParser(description="Build LoRA training JSON from dataset/scene structure")
    p.add_argument("--data_root", default="/workspace/group_share/adc-sim/users/jxr/inspatio_videos",
                   help="Root directory containing scene subdirectories with cam{N}_gt/render pairs")
    p.add_argument("--output", default="./data/metadata.json",
                   help="Output JSON path (default: ./data/metadata.json)")
    return p.parse_args()


def main():
    args = parse_args()
    root = Path(args.data_root).resolve()

    if not root.is_dir():
        raise FileNotFoundError(f"data_root not found: {root}")

    entries = []
    
    # Auto-detect: is data_root itself a scene, or a root containing scenes?
    if _is_scene_directory(root):
        # Mode 1: data_root is itself a scene directory
        print(f"[Mode: Single Scene] Processing: {root.name}")
        pairs = _scan_scene_directory(root)
        if pairs:
            for gt_path, render_path in pairs:
                entries.append({
                    "target_path": str(gt_path),
                    "render_path": str(render_path),
                    "ref_path": str(gt_path),
                })
        else:
            print(f"[WARN] No pairs found in {root.name}")
    
    elif _is_dataset_scene_root(root):
        # Mode 2: data_root contains scene subdirectories
        print(f"[Mode: Multi-Scene Root] Processing: {root}")
        scene_dirs = sorted(d for d in root.iterdir() if d.is_dir())
        
        for scene_dir in scene_dirs:
            pairs = _scan_scene_directory(scene_dir)
            if not pairs:
                print(f"[WARN] No pairs found in {scene_dir.name}, skipping.")
                continue

            for gt_path, render_path in pairs:
                entries.append({
                    "target_path": str(gt_path),
                    "render_path": str(render_path),
                    "ref_path": str(gt_path),
                })
    
    else:
        raise ValueError(
            f"data_root does not appear to be a scene or dataset root. "
            f"Expected either:\n"
            f"  - A scene directory (contains cam{{N}}_gt/render files/dirs)\n"
            f"  - A dataset root (subdirs contain cam{{N}}_gt/render files/dirs)"
        )

    if not entries:
        print("[ERROR] No valid pairs found; JSON not written.")
        return

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as fh:
        json.dump(entries, fh, indent=2, ensure_ascii=False)
    print(f"[SUCCESS] Saved {len(entries)} entries → {out_path}")


if __name__ == "__main__":
    main()
