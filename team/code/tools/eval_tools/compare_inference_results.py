import os
import json
import argparse
from collections import defaultdict

import imageio
import numpy as np
import cv2


def load_psnr_report(report_path):
    if not os.path.exists(report_path):
        return None
    try:
        with open(report_path, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Failed to load {report_path}: {e}")
        return None


def parse_clip_cam_from_dirname(dirname):
    # 目录名形如: c-xxxx_cam0
    if "_" not in dirname:
        return None, None
    clip_id, cam = dirname.rsplit("_", 1)
    return clip_id, cam


def concat_videos_2x2(gt_path, input_path, origin_path, ckpt_path, out_path, fps=6):
    """将 4 个视频按 2x2 格式拼接: 第一行 gt & input, 第二行 origin & ckpt。"""
    missing = [p for p in [gt_path, input_path, origin_path, ckpt_path] if not os.path.exists(p)]
    if missing:
        print(f"Skip concat, missing videos: {missing}")
        return None

    # 尝试打开 4 个视频，若有损坏无法读取，则跳过该 pair
    readers = []
    video_paths = [gt_path, input_path, origin_path, ckpt_path]
    try:
        for p in video_paths:
            try:
                readers.append(imageio.get_reader(p))
            except Exception as e:
                print(f"Skip concat for {out_path}, cannot open video {p}: {e}")
                # 关闭已打开的 reader
                for r in readers:
                    try:
                        r.close()
                    except Exception:
                        pass
                return None
    except Exception as e:
        print(f"Unexpected error when opening videos for {out_path}: {e}")
        for r in readers:
            try:
                r.close()
            except Exception:
                pass
        return None
    try:
        # 统一长度为最短视频长度
        lengths = []
        for r in readers:
            try:
                lengths.append(r.count_frames())
            except Exception:
                # 某些后端不支持 count_frames，退回为迭代计数
                lengths.append(10**9)
        max_frames = min(lengths)
        if max_frames == 0 or max_frames == 10**9:
            # 尝试用迭代方式估长度
            max_frames = 0
            tmp_frames = []
            for idx, r in enumerate(readers):
                c = 0
                for frame in r:
                    c += 1
                tmp_frames.append(c)
                r.close()
                readers[idx] = imageio.get_reader(
                    [gt_path, input_path, origin_path, ckpt_path][idx]
                )
            max_frames = min(tmp_frames)
        if max_frames <= 0:
            print(f"Skip concat for {out_path}, no frames.")
            return None

        writer = imageio.get_writer(out_path, fps=fps)
        try:
            for i in range(max_frames):
                try:
                    f_gt = readers[0].get_data(i)
                    f_in = readers[1].get_data(i)
                    f_or = readers[2].get_data(i)
                    f_ck = readers[3].get_data(i)
                except IndexError:
                    break

                # 统一分辨率
                h, w = f_gt.shape[:2]
                def _resize(frame):
                    if frame.shape[:2] != (h, w):
                        return cv2.resize(frame, (w, h))
                    return frame

                f_gt = _resize(f_gt)
                f_in = _resize(f_in)
                f_or = _resize(f_or)
                f_ck = _resize(f_ck)

                # 在每个子图上叠加标签
                def _add_label(img, text):
                    # 使用白色文字，黑色描边以保证可读性
                    font = cv2.FONT_HERSHEY_SIMPLEX
                    scale = 0.8
                    thickness = 2
                    color = (255, 255, 255)
                    shadow_color = (0, 0, 0)
                    x, y = 10, 30
                    # shadow
                    cv2.putText(img, text, (x + 1, y + 1), font, scale, shadow_color, thickness + 1, cv2.LINE_AA)
                    # main text
                    cv2.putText(img, text, (x, y), font, scale, color, thickness, cv2.LINE_AA)
                    return img

                f_gt = _add_label(f_gt, "GT")
                f_in = _add_label(f_in, "Input 3DGS")
                f_or = _add_label(f_or, "Origin Difix")
                f_ck = _add_label(f_ck, "Finetuned Difix")

                top = np.hstack([f_gt, f_in])
                bottom = np.hstack([f_or, f_ck])
                mosaic = np.vstack([top, bottom])
                writer.append_data(mosaic)
        finally:
            writer.close()
    finally:
        for r in readers:
            try:
                r.close()
            except Exception:
                pass

    return out_path


def main(ckpt_root, origin_root, given_clip_id, output_folder):
    # 输出目录放在 ckpt_result_dir 的同级目录下
    ckpt_root = ckpt_root.rstrip("/")
    out_folder_name = ckpt_root.split("/")[-2] + ckpt_root.split("/")[-1].replace("inference", "", 1)
    out_root = os.path.join(output_folder, "compare_inference_" + out_folder_name)
    os.makedirs(out_root, exist_ok=True)

    per_clip_cam = []
    all_names = sorted(os.listdir(ckpt_root))
    total = len(all_names)
    processed = 0

    print(f"Start comparing results: ckpt_root={ckpt_root}, origin_root={origin_root}")

    # 遍历 ckpt 结果目录，找出每个 clip_cam
    for idx, name in enumerate(all_names):
        ckpt_subdir = os.path.join(ckpt_root, name)
        if not os.path.isdir(ckpt_subdir):
            continue
        clip_id, cam = parse_clip_cam_from_dirname(name)
        if clip_id is None:
            continue
        if given_clip_id is not None and clip_id != given_clip_id:
            continue

        origin_subdir = os.path.join(origin_root, name)
        if not os.path.isdir(origin_subdir):
            print(f"Origin result not found for {name}, skip")
            continue

        ckpt_report_path = os.path.join(ckpt_subdir, "psnr_report.json")
        origin_report_path = os.path.join(origin_subdir, "psnr_report.json")
        ckpt_rep = load_psnr_report(ckpt_report_path)
        origin_rep = load_psnr_report(origin_report_path)
        if ckpt_rep is None or origin_rep is None:
            print(f"Missing psnr_report.json for {name}, skip")
            continue

        mean_psnr_ckpt = float(ckpt_rep.get("statistics", {}).get("mean_psnr", ckpt_rep.get("mean_psnr", 0.0)))
        mean_psnr_origin = float(origin_rep.get("statistics", {}).get("mean_psnr", origin_rep.get("mean_psnr", 0.0)))
        mean_psnr_input_ckpt = float(
            ckpt_rep.get("statistics", {}).get("mean_psnr_input", ckpt_rep.get("mean_psnr_input", 0.0))
        )
        mean_psnr_input_origin = float(
            origin_rep.get("statistics", {}).get("mean_psnr_input", origin_rep.get("mean_psnr_input", 0.0))
        )
        num_frames = int(ckpt_rep.get("num_frames", len(ckpt_rep.get("per_frame", []))))

        improvement = mean_psnr_ckpt - mean_psnr_origin

        # 拼接视频
        if given_clip_id is not None:
            gt_video = os.path.join(ckpt_subdir, "gt.mp4")
            input_video = os.path.join(ckpt_subdir, "input.mp4")
            origin_video = os.path.join(origin_subdir, "output.mp4")
            ckpt_video = os.path.join(ckpt_subdir, "output.mp4")
            concat_out = os.path.join(out_root, f"{name}_compare.mp4")
            concat_videos_2x2(
                gt_video,
                input_video,
                origin_video,
                ckpt_video,
                concat_out,
            )

        per_clip_cam.append(
            {
                "clip_id": clip_id,
                "camera_name": cam,
                "model_version": ckpt_rep.get("model_version"),
                "num_frames": num_frames,
                "mean_psnr_ckpt": mean_psnr_ckpt,
                "mean_psnr_origin": mean_psnr_origin,
                "mean_psnr_input_ckpt": mean_psnr_input_ckpt,
                "mean_psnr_input_origin": mean_psnr_input_origin,
                "improvement": improvement,
                "ckpt_psnr_report": ckpt_report_path,
                "origin_psnr_report": origin_report_path,
            }
        )
        processed += 1
        if processed % 7 == 0:
            print(f"Processed {processed} pairs (current: {name})")

    print(f"Done. Total valid pairs: {processed}")

    # 按 clip_id 分组，计算每个 clip 的平均 PSNR
    by_clip = defaultdict(list)
    for p in per_clip_cam:
        by_clip[p["clip_id"]].append(p)

    per_clip = {}
    for clip_id, cam_list in by_clip.items():
        per_clip[clip_id] = {
            "mean_psnr_ckpt": float(np.mean([x["mean_psnr_ckpt"] for x in cam_list])),
            "mean_psnr_origin": float(np.mean([x["mean_psnr_origin"] for x in cam_list])),
            "mean_improvement": float(np.mean([x["improvement"] for x in cam_list])),
            "mean_psnr_input_ckpt": float(np.mean([x["mean_psnr_input_ckpt"] for x in cam_list])),
            "mean_psnr_input_origin": float(np.mean([x["mean_psnr_input_origin"] for x in cam_list])),
            "num_cams": len(cam_list),
            "per_cam": cam_list,
        }

    # 统计整体提升
    summary = {
        "ckpt_result_dir": ckpt_root,
        "origin_result_dir": origin_root,
        "num_pairs": len(per_clip_cam),
        "num_clips": len(per_clip),
    }
    if per_clip_cam:
        mean_ckpt = np.mean([p["mean_psnr_ckpt"] for p in per_clip_cam])
        mean_origin = np.mean([p["mean_psnr_origin"] for p in per_clip_cam])
        mean_improve = np.mean([p["improvement"] for p in per_clip_cam])
        mean_input_ckpt = np.mean([p["mean_psnr_input_ckpt"] for p in per_clip_cam])
        mean_input_origin = np.mean([p["mean_psnr_input_origin"] for p in per_clip_cam])
        summary.update(
            {
                "mean_psnr_ckpt": float(mean_ckpt),
                "mean_psnr_origin": float(mean_origin),
                "mean_improvement": float(mean_improve),
                "mean_psnr_input_ckpt": float(mean_input_ckpt),
                "mean_psnr_input_origin": float(mean_input_origin),
            }
        )

    # JSON：summary + 以 clip_id 为 key 的 per_clip
    result = {
        "summary": summary,
        "per_clip": per_clip,
    }
    output_file = os.path.join(out_root, "compare_psnr.json")
    with open(output_file, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"Comparison json saved to {output_file}")


if __name__ == "__main__":
    ############################################################
    CWD = "/workspace/yangxh7@xiaopeng.com"
    # 原始 Difix 推理结果 (仅用于视频拼接)
    origin_root = os.path.join(CWD, "difix3D_train/eval/inference_origin") 
    # 训练ckpt推理结果
    ckpts_root = [
        "difix3D_train/train_v3_1w_b/v3_2buckets/inference_epoch_0029_step_174000_0.0",
        "difix3D_train/train_v3_1w_b/v3_2buckets/inference_epoch_0039_step_234000_0.0"
    ]
    # 指定 clip_id，若为 None，则对比所有 clip
    given_clip_id = None # "c-b44d1b27-143e-38ec-98f5-ba8b1715ef93"
    # 输出文件夹
    output_folder = os.path.join(CWD, "difix3D_train/eval") 
    ############################################################
    
    for ckpt_root in ckpts_root:
        ckpt_root = os.path.join(CWD, ckpt_root)
        main(ckpt_root, origin_root, given_clip_id, output_folder)

