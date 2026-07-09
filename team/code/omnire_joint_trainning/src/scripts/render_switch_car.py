import argparse
import bisect
import os, sys
import cv2
import numpy as np
import torch
import time
import json  
import fcntl
import hashlib
import shutil
from datetime import datetime
 
# import from parent directory
current_dir = os.path.dirname(__file__) 
reconic_path = os.path.abspath(os.path.join(current_dir, ".."))
print(f"import reconic_path {reconic_path}")
# omnire_joint_trainning/src/scripts/render_switch_car.py
sim_interface_path = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
print(f"import sim_interface_path {sim_interface_path}")
sys.path.extend([reconic_path, sim_interface_path])
from sim_interface.utils import (
    quaternion_matrix,
)

from sim_interface.visualizers.xpeng_visualizer import XpengVisualizer
from reconic.simulator.reconic_simulator import ReconicSimulator
from reconic.simulator.reconic_simulator import fun as render_fun_single
from reconic.simulator.render_strategy.strategies_factory import RenderStrategyFactory
from reconic.utils.car_switch_utils import (
    build_pose_buffer_from_localpose,
    get_transform_json,
    lookup_pose,
)
from reconic.multi_vehicle_utils.query_scenario_event import VEHICLE_TYPE_2_ID


def _localpose_to_matrix(mflp):
    position = mflp["smooth_pose"]["pose"]["p"]
    rotation = mflp["smooth_pose"]["pose"]["q"]
    translation = np.array([position["x"], position["y"], position["z"]], dtype=np.float32)
    quaternion = np.array([rotation["w"], rotation["x"], rotation["y"], rotation["z"]], dtype=np.float32)
    ego_pose_world = quaternion_matrix(quaternion)
    ego_pose_world[:3, 3] = translation
    return ego_pose_world.astype(np.float32)


def render_switch_car(simulator, reference_png_dir, timestamp_records_path, save_path=''):
    visualizer = XpengVisualizer(save_path, save_img=True)
    target_vis = {
        'redistort_rgb': 'rgb', 
        'redistort_rgb_background': 'Background_rgb', 
        'redistort_rgb_ground': 'Ground_rgb', 
        'redistort_rgb_object': 'Dynamic_rgb'
    }

    localpose_path = os.path.join(simulator.model_path, "LocalPoseTopic.json")
    localpose_all = json.load(open(localpose_path, "r"))
    timestamp_records = json.load(open(timestamp_records_path, "r"))
    pose_buffer = build_pose_buffer_from_localpose(localpose_all)

    valid_cams = {simulator._label2camera[cam_id] for cam_id in simulator.cameras}
    rendered_cam_and_timestamps = [
        (item["sensor_id"], int(item["msg_timestamp_nsec"]))
        for item in timestamp_records
        if item.get("sensor_id") in valid_cams
    ]
    rendered_cam_and_timestamps.sort(key=lambda x: x[1])
    rendered_items = []

    for cam_name, timestamp in rendered_cam_and_timestamps:
        ego_pose_world = lookup_pose(pose_buffer, timestamp, max_interval=1.0)
        if ego_pose_world is None:
            continue
        rendered_items.append((cam_name, timestamp, ego_pose_world.astype(np.float32)))

    gt_timestamp_cache = {}
    print(f"simdebug simulator.cfg.data.data_root {simulator.cfg.data.data_root}")
    print(f"simdebug simulator.cfg.data.scene_idx {simulator.cfg.data.scene_idx}")
    print(f"simdebug len(rendered_items) {len(rendered_items)}")
    def _get_nearest_gt_path(cam_dir, target_ts):
        if not os.path.isdir(cam_dir):
            return None
        if cam_dir not in gt_timestamp_cache:
            ts_file_pairs = []
            for fname in os.listdir(cam_dir):
                if not fname.endswith(".png"):
                    continue
                stem = fname[:-4]
                if stem.isdigit():
                    ts_file_pairs.append((int(stem), fname))
            ts_file_pairs.sort(key=lambda x: x[0])
            gt_timestamp_cache[cam_dir] = ([x[0] for x in ts_file_pairs], ts_file_pairs)

        ts_list, ts_file_pairs = gt_timestamp_cache[cam_dir]
        if not ts_file_pairs:
            return None

        idx = bisect.bisect_left(ts_list, int(target_ts))
        cand_indices = []
        if idx < len(ts_file_pairs):
            cand_indices.append(idx)
        if idx > 0:
            cand_indices.append(idx - 1)
        best_idx = min(cand_indices, key=lambda i: abs(ts_file_pairs[i][0] - int(target_ts)))
        return os.path.join(cam_dir, ts_file_pairs[best_idx][1])

    idx = 0
    for cam_name, timestamp, ego_pose_world in rendered_items:
        idx += 1
        result = dict()
        result_redistort = dict()

        fun_res = render_fun_single(simulator, timestamp, cam_name, None, ego_pose_world=ego_pose_world, debug=True)
        h, w = fun_res['height'], fun_res['width']
        img_data = fun_res['image'].reshape(h, w, 3)
        result[cam_name] = {"rgb": img_data}
        result_redistort[cam_name] = {"redistort_rgb": img_data}
        if 'image_gt' in fun_res and fun_res['image_gt'] is not None:
            result_redistort[cam_name]['redistort_rgb_gt'] = fun_res['image_gt'].permute(1, 2, 0).cpu().numpy().astype(np.uint8)

        if 'redistort_rgb_gt' not in result_redistort[cam_name]:
            group_share_cam_dir = os.path.join(reference_png_dir, "images_origin", cam_name)
            group_share_path = _get_nearest_gt_path(group_share_cam_dir, timestamp)
            if group_share_path is not None and os.path.exists(group_share_path):
                result_redistort[cam_name]['redistort_rgb_gt'] = cv2.cvtColor(
                    cv2.imread(group_share_path), cv2.COLOR_BGR2RGB
                )
            elif 'redistort_rgb_gt' not in result_redistort[cam_name]:
                result_redistort[cam_name]['redistort_rgb_gt'] = None

        # redistort images
        for k, v in target_vis.items():
            if k not in result_redistort[cam_name]:
                if v in result[cam_name]:
                    result[cam_name][v] = torch.clamp(result[cam_name][v] * 255, 0, 255).permute(2, 0, 1)
                    result[cam_name][v] = result[cam_name][v].to(torch.uint8)
                    result_redistort[cam_name][k] = simulator.redistort_gpu(cam_name, result[cam_name][v])
                    # convert to numpy
                    result_redistort[cam_name][k] = (result_redistort[cam_name][k].permute(1, 2, 0).cpu().numpy()) 
                else:
                    result_redistort[cam_name][k] = None

        # fill in empty images
        for k in result_redistort[cam_name]:
            if result_redistort[cam_name][k] is None:
                result_redistort[cam_name][k] = np.zeros(result_redistort[cam_name]['redistort_rgb'].shape, dtype=np.uint8)

        image_name = timestamp
        visualizer.visualize_redistort(result_redistort[cam_name], cam_name, image_name)
        print(f"Rendering {cam_name} {idx}/{len(rendered_items)} done", flush=True)
        
        # 清理GPU显存，避免OOM
        del result, result_redistort, fun_res
        torch.cuda.empty_cache()

    visualizer.save_video_merged(mode="origin", fps=12)


def generate_new_calib_and_transform(model_path, new_calib_path, new_img_timestamps_path):
    # backup original calib and transform
    original_calib_path = os.path.join(model_path, "calib.json")
    original_transform_path = os.path.join(model_path, "transform.json")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_info = {
        "original_calib_path": original_calib_path,
        "original_transform_path": original_transform_path,
        "calib_existed": os.path.exists(original_calib_path),
        "transform_existed": os.path.exists(original_transform_path),
        "calib_backup_path": None,
        "transform_backup_path": None,
    }
    if os.path.exists(original_calib_path):
        calib_backup_path = f"{original_calib_path}.bak.{timestamp}"
        shutil.copy2(original_calib_path, calib_backup_path)
        backup_info["calib_backup_path"] = calib_backup_path
        print(f"[INFO] calib backup created: {calib_backup_path}")
    if os.path.exists(original_transform_path):
        transform_backup_path = f"{original_transform_path}.bak.{timestamp}"
        shutil.copy2(original_transform_path, transform_backup_path)
        backup_info["transform_backup_path"] = transform_backup_path
        print(f"[INFO] transform backup created: {transform_backup_path}")
    original_transform_json = json.load(open(original_transform_path, "r")) if os.path.exists(original_transform_path) else None

    # generate new calib
    same_calib_file = False
    try:
        if os.path.exists(new_calib_path) and os.path.exists(original_calib_path):
            same_calib_file = os.path.samefile(new_calib_path, original_calib_path)
    except OSError:
        same_calib_file = (
            os.path.abspath(new_calib_path) == os.path.abspath(original_calib_path)
        )

    if same_calib_file:
        print(f"[INFO] source equals target, backup kept and skip calib copy: {new_calib_path}")
    else:
        print(f"simdebug copy new calib: {new_calib_path} to {original_calib_path}")
        shutil.copy2(new_calib_path, original_calib_path)
        print(f"simdebug copy new calib done")

    # generate new transform
    new_img_timestamps = json.load(open(new_img_timestamps_path, "r"))
    print(f"new_img_timestamps length: {len(new_img_timestamps)}")

    new_calib = json.load(open(new_calib_path, "r"))
    new_transform_json = get_transform_json(new_calib, original_transform_json)
    json.dump(new_transform_json, open(os.path.join(model_path, "transform.json"), "w"), indent=4)
    return backup_info


def restore_original_calib_and_transform(backup_info):
    original_calib_path = backup_info["original_calib_path"]
    original_transform_path = backup_info["original_transform_path"]
    calib_backup_path = backup_info["calib_backup_path"]
    transform_backup_path = backup_info["transform_backup_path"]

    if calib_backup_path and os.path.exists(calib_backup_path):
        shutil.copy2(calib_backup_path, original_calib_path)
    elif not backup_info["calib_existed"] and os.path.exists(original_calib_path):
        os.remove(original_calib_path)

    if transform_backup_path and os.path.exists(transform_backup_path):
        shutil.copy2(transform_backup_path, original_transform_path)
    elif not backup_info["transform_existed"] and os.path.exists(original_transform_path):
        os.remove(original_transform_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser("3DGS Render Sim")
    parser.add_argument("--config", required=True, type=str, default="", help="reconic trained result config")
    parser.add_argument("--save_path", required=True, type=str, default="", help="reconic render result path")
    parser.add_argument("--new_calib_path", required=True, type=str, default="", help="new calib path")
    parser.add_argument("--new_img_timestamps_path", required=True, type=str, default="", help="new img timestamps path")
    parser.add_argument("--reference_png_dir", required=True, type=str, default="", help="reference_png_dir")
    args = parser.parse_args()

    model_path = os.path.dirname(os.path.dirname(args.config))
    lock_key = args.config
    lock_digest = hashlib.md5(lock_key.encode("utf-8")).hexdigest()
    lock_path = os.path.join(model_path, f".render_switch_car_{lock_digest}.lock")
    lock_fp = open(lock_path, "w", encoding="utf-8")
    try:
        fcntl.flock(lock_fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"[SKIP] same input is already running, lock: {lock_path}")
        lock_fp.close()
        sys.exit(0)
    lock_fp.write(str(os.getpid()))
    lock_fp.flush()

    backup_info = None
    try:
        backup_info = generate_new_calib_and_transform(model_path, args.new_calib_path, args.new_img_timestamps_path)
        target_vehicle = args.new_calib_path.split("/")[-1].split(".")[0].replace("calib_", "")
        vehicle_model = VEHICLE_TYPE_2_ID.get(target_vehicle.lower())
        simulator = ReconicSimulator(args.config, cp_simulation=True, iter=None, init_from_feedforward=False, vehicle_model=vehicle_model)
        t1 = time.time()
        # reference_png_dir 是包含 images_origin 目录的父目录
        reference_png_dir = os.path.dirname(model_path)
        render_switch_car(simulator, reference_png_dir, args.new_img_timestamps_path, args.save_path)
        t2 = time.time()
        print(f"Time cost: {t2 - t1} seconds")
    finally:
        if backup_info is not None:
            restore_original_calib_and_transform(backup_info)
        lock_fp.close()