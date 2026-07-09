import argparse
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


FPS = 6
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp"}
CAM_RE = re.compile(r"^cam\d+$", re.IGNORECASE)
TIMESTAMP_RE = re.compile(r"\d+")


def collect_images(directory: Path) -> list[tuple[int, Path]]:
    if not directory.is_dir():
        return []

    images = []
    for path in directory.iterdir():
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            match = TIMESTAMP_RE.search(path.stem)
            if match:
                images.append((int(match.group()), path))

    return sorted(images)


def concat_quote(path: Path) -> str:
    return "'" + path.resolve().as_posix().replace("'", "'\\''") + "'"


def write_concat_list(paths: list[Path], list_path: Path) -> None:
    duration = 1 / FPS
    with list_path.open("w", encoding="utf-8", newline="\n") as f:
        for path in paths:
            f.write(f"file {concat_quote(path)}\n")
            f.write(f"duration {duration:.9f}\n")
        f.write(f"file {concat_quote(paths[-1])}\n")


def encode(list_path: Path, output_path: Path, frame_count: int, ffmpeg: str) -> str | None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
        "-frames:v",
        str(frame_count),
        "-r",
        str(FPS),
        "-c:v",
        "libx264",
        "-crf",
        "0",
        "-preset",
        "veryfast",
        "-level",
        "4.0",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        return result.stderr[-2000:]
    if not output_path.is_file() or output_path.stat().st_size == 0:
        return "ffmpeg finished but output file is empty"
    return None


def probe_duration(video: Path, ffprobe: str) -> float:
    if not video.is_file() or video.stat().st_size == 0:
        return 0.0
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=nokey=1:noprint_wrappers=1",
        str(video),
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        return 0.0
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def process_cam(
    scene: str,
    cam: str,
    gt_dir: Path,
    ff_dir: Path,
    output_dir: Path,
    tmp_dir: Path,
    ffmpeg: str,
) -> tuple[bool, str, int]:
    gt_images = collect_images(gt_dir)
    ff_images = collect_images(ff_dir)
    if not gt_images or not ff_images:
        return False, "missing GT or FF images", 0

    # FF and GT share timestamps (GT just has extra frames interleaved between
    # FF frames). Read each FF timestamp and grab the GT frame at the same
    # timestamp -- no resampling/alignment needed.
    gt_by_ts = dict(gt_images)
    gt_paths = []
    ff_paths = []
    for ts, ff_path in ff_images:
        gt_path = gt_by_ts.get(ts)
        if gt_path is not None:
            gt_paths.append(gt_path)
            ff_paths.append(ff_path)
    if not gt_paths:
        return False, "no matching timestamps between GT and FF", 0

    gt_list = tmp_dir / f"{scene}_{cam}_gt.txt"
    ff_list = tmp_dir / f"{scene}_{cam}_rgb.txt"
    write_concat_list(gt_paths, gt_list)
    write_concat_list(ff_paths, ff_list)

    scene_out = output_dir / scene
    gt_error = encode(gt_list, scene_out / f"{cam}_gt.mp4", len(gt_paths), ffmpeg)
    ff_error = encode(ff_list, scene_out / f"{cam}_rgb.mp4", len(ff_paths), ffmpeg)

    if gt_error or ff_error:
        return False, gt_error or ff_error or "ffmpeg failed", len(gt_paths)
    return True, "", len(gt_paths)


def discover_cams(data_root: Path, gt_name: str, ff_name: str) -> list[tuple[str, str, Path, Path]]:
    tasks = []
    for scene_dir in sorted(path for path in data_root.iterdir() if path.is_dir()):
        gt_root = scene_dir / gt_name
        ff_root = scene_dir / ff_name
        if not gt_root.is_dir() or not ff_root.is_dir():
            continue

        for ff_cam in sorted(path for path in ff_root.iterdir() if path.is_dir() and CAM_RE.match(path.name)):
            tasks.append((scene_dir.name, ff_cam.name, gt_root / ff_cam.name, ff_cam))
    return tasks


def scene_is_complete(
    scene_out: Path,
    cams: list[str],
    expected_cams: int,
    target_duration: float,
    duration_tol: float,
    ffprobe: str,
) -> bool:
    if not scene_out.is_dir():
        return False
    if expected_cams > 0 and len(cams) < expected_cams:
        return False
    for cam in cams:
        for suffix in ("gt", "rgb"):
            video = scene_out / f"{cam}_{suffix}.mp4"
            if abs(probe_duration(video, ffprobe) - target_duration) > duration_tol:
                return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_root", default="/workspace/group_share/adc-sim/users/dsc/xpeng_train_data_0401")
    parser.add_argument("--output_dir", default="/workspace/group_share/adc-sim/users/jxr/inspatio_videos")
    parser.add_argument("--gt_dir", default="images_origin")
    parser.add_argument("--ff_dir", default="feedforward_img_0320")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--expected_cams",
        type=int,
        default=7,
        help="Number of cameras required for a scene to count as complete; set to 0 to skip "
        "a scene once all discovered cameras have complete videos",
    )
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument(
        "--target_duration",
        type=float,
        default=29.0,
        help="Expected video length in seconds; a scene is skipped when every "
        "existing video is within --duration_tol of this value",
    )
    parser.add_argument("--duration_tol", type=float, default=1.0)
    args = parser.parse_args()

    # Force line-buffered stdout so progress shows up immediately even when the
    # output is redirected to a file or piped (default block buffering would
    # otherwise hide every print until the program exits).
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass

    data_root = Path(args.data_root).resolve()
    output_dir = Path(args.output_dir).resolve()
    if not data_root.is_dir():
        print(f"[ERROR] data_root does not exist: {data_root}")
        sys.exit(1)

    print(f"[INFO] scanning {data_root} ...")
    tasks = discover_cams(data_root, args.gt_dir, args.ff_dir)
    print(f"[INFO] discovered {len(tasks)} cam(s)")

    scene_cams: dict[str, list[str]] = defaultdict(list)
    for scene, cam, _gt_dir, _ff_dir in tasks:
        scene_cams[scene].append(cam)

    # A scene is skipped when every existing camera video is ~target_duration
    # seconds long. ffprobe reads the duration from container metadata (no
    # decode), so this stays fast; report progress while checking.
    print(f"[INFO] checking existing videos in {output_dir} (~{args.target_duration}s) ...")
    complete_scenes = set()
    scene_items = sorted(scene_cams.items())
    for checked, (scene, cams) in enumerate(scene_items, start=1):
        if scene_is_complete(
            output_dir / scene,
            cams,
            args.expected_cams,
            args.target_duration,
            args.duration_tol,
            args.ffprobe,
        ):
            complete_scenes.add(scene)
            print(f"[SKIP] {scene}: {len(cams)} cam(s) already complete")
        if checked % 20 == 0 or checked == len(scene_items):
            print(f"[CHECK] {checked}/{len(scene_items)} scene(s) checked")

    pending_tasks = [task for task in tasks if task[0] not in complete_scenes]
    skipped = len(tasks) - len(pending_tasks)
    print(
        f"[INFO] {len(pending_tasks)} cam(s) to encode, {skipped} skipped, "
        f"{FPS}Hz, H.264 yuv420p crf=0"
    )

    ok_count = 0
    with tempfile.TemporaryDirectory(prefix="ffmpeg_concat_") as tmp:
        tmp_dir = Path(tmp)
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {
                pool.submit(
                    process_cam,
                    scene,
                    cam,
                    gt_dir,
                    ff_dir,
                    output_dir,
                    tmp_dir,
                    args.ffmpeg,
                ): (scene, cam)
                for scene, cam, gt_dir, ff_dir in pending_tasks
            }
            for future in as_completed(futures):
                scene, cam = futures[future]
                try:
                    ok, error, frames = future.result()
                except Exception as exc:
                    ok, error, frames = False, repr(exc), 0
                if ok:
                    ok_count += 1
                    print(f"[OK] {scene}/{cam}: {frames} frames")
                else:
                    print(f"[FAIL] {scene}/{cam}: {error}")

    print(f"[DONE] {ok_count}/{len(pending_tasks)} cam(s), {skipped} skipped")


if __name__ == "__main__":
    main()
