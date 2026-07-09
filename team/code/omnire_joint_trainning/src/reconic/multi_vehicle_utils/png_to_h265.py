#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

CAMERA_NAME_MAP = {
    "cam0": "narrow",
    "cam2": "fisheye",
    "cam3": "side_front_left",
    "cam4": "side_front_right",
    "cam5": "side_rear_left",
    "cam6": "side_rear_right",
    "cam7": "rear",
}

CAMERA_RESOLUTION = {
    "cam0": (1920, 1080),
    "cam2": (1920, 1080),
    "cam3": (968, 774),
    "cam4": (968, 774),
    "cam5": (968, 774),
    "cam6": (968, 774),
    "cam7": (1920, 1080),
}

ENCODE_CAMERA_DIRS = {"cam0", "cam2", "cam3", "cam4", "cam5", "cam6", "cam7"}


def get_filename_without_extension(path):
    return os.path.splitext(os.path.basename(path))[0]


def encode_single_camera(input_files, output_prefix, camera):
    if camera not in CAMERA_NAME_MAP:
        print(f"Unknown camera: {camera}")
        return False

    camera_name = CAMERA_NAME_MAP[camera]
    width, height = CAMERA_RESOLUTION[camera]
    bitrate = width * height * 6 * 8

    for i, input_file in enumerate(input_files):
        suffix = os.path.splitext(input_file)[1].lower()
        if suffix != ".png":
            print(f"not a png picture, the file suffix is: {suffix}")
            return False

        frame_type = "3" if (i % 5 == 0) else "0"
        base_name = get_filename_without_extension(input_file)
        output_file = f"{output_prefix}{camera_name}-{base_name}-{frame_type}.h265"

        if os.path.exists(output_file):
            # print(f"Skipping: {input_file} -> {output_file} (already exists)")
            continue

        # 使用NVENC硬件编码器（hevc_nvenc）
        cmd = [
            "ffmpeg", "-y",
            "-i", input_file,
            "-c:v", "hevc_nvenc",  # NVIDIA NVENC HEVC编码器
            "-pix_fmt", "yuv420p",
            "-s", f"{width}x{height}",
            "-r", "4",
            "-g", "5",
            "-bf", "0",
            "-b:v", str(bitrate),
            "-preset", "p4",  # NVENC编码预设（p1-p7，平衡速度和质量）
            "-flags", "+cgop",
            "-frames:v", "1",
            output_file,
        ]

        # print(f"Encoding: {input_file} -> {output_file}")
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            print(f"ffmpeg encoding failed for {input_file}")
            print(result.stderr.decode("utf-8", errors="replace"))
            return False

    return True


def process_single_camera_task(camera_path, output_prefix, camera):
    """处理单个摄像头的编码任务"""
    png_files = [f for f in os.listdir(camera_path) if f.lower().endswith(".png")]
    png_files.sort()
    if not png_files:
        print(f"No PNG files found in {camera_path}, skipping.")
        return True, camera

    input_files = [os.path.join(camera_path, f) for f in png_files]
    success = encode_single_camera(input_files, output_prefix, camera)
    return success, camera


def encode_from_dir(input_dir, output_dir):
    if not os.path.isdir(input_dir):
        print(f"Input directory does not exist: {input_dir}")
        return False

    os.makedirs(output_dir, exist_ok=True)

    # 创建任务列表
    tasks = []
    for camera in ENCODE_CAMERA_DIRS:
        camera_path = os.path.join(input_dir, camera)
        if os.path.isdir(camera_path):
            tasks.append((camera_path, output_dir + "/", camera))

    # 使用线程池并发执行编码任务
    with ThreadPoolExecutor(max_workers=len(ENCODE_CAMERA_DIRS)) as executor:
        # 提交所有任务
        future_to_camera = {
            executor.submit(process_single_camera_task, task[0], task[1], task[2]): task[2] 
            for task in tasks
        }

        # 等待所有任务完成并检查结果
        all_success = True
        for future in as_completed(future_to_camera):
            success, camera = future.result()
            if not success:
                print(f"Encoding failed for camera: {camera}")
                all_success = False

    return all_success


def main():
    parser = argparse.ArgumentParser(description="Encode PNG files to H265 using ffmpeg")
    parser.add_argument("--input-files", nargs="+", default=None, help="Input PNG file paths (for single-camera mode)")
    parser.add_argument("--output-prefix", default=None, help="Output file path prefix (for single-camera mode)")
    parser.add_argument("--camera", default=None, help="Camera ID (e.g., cam0)")
    parser.add_argument("--input-dir", default=None, help="Input directory containing cam0/cam2/... subdirs (batch mode)")
    parser.add_argument("--output-dir", default=None, help="Output directory for batch mode (default: INPUT_DIR/output_h265)")
    args = parser.parse_args()

    if args.input_dir:
        output_dir = args.output_dir if args.output_dir else os.path.join(args.input_dir, "output_h265")
        success = encode_from_dir(args.input_dir, output_dir)
        sys.exit(0 if success else 1)
    elif args.input_files and args.output_prefix and args.camera:
        success = encode_single_camera(args.input_files, args.output_prefix, args.camera)
        sys.exit(0 if success else 1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    sys.exit(main())