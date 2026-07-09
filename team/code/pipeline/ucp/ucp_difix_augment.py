import json
import os
import shutil
import sys
from download_file_from_oss2 import download_file_from_oss2


DIFIX_TRAIN_IMAGES_ORIGIN_ROOT = "/workspace/group_share/adc-sim/users/difix_train/images_origin"
MULTI_VEHICLE_CALIB_ROOT = "/workspace/group_share/adc-sim/users/multi_vehicle/calibs"
DEFAULT_TRAIN_DATA_JSON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "difix/utils/train_data_415_0421/train_data.json",
)

VEHICLE_CONFIGS = [
    ("h93aes", os.path.join(MULTI_VEHICLE_CALIB_ROOT, "calib_h93aes.json")),
    ("e29", os.path.join(MULTI_VEHICLE_CALIB_ROOT, "calib_e29.json")),
    ("f01es", os.path.join(MULTI_VEHICLE_CALIB_ROOT, "calib_f01es.json")),
]

DIFIX_ENV_DEFAULTS = {
    "USE_DIFIX": "true",
    "USE_DIFIX_MODE": "true",
    "USE_DIFIX_REFERENCE": "false",
    "USE_DIFIX_FINETUNED": "true",
    "CKPT": "/workspace/group_share/adc-sim/users/cloudsim/difix/ckpt_finetuned/default/",
    "TORCH_HOME": "/workspace/yangxh7@xiaopeng.com/torch_cache",
    "HF_HOME": "/workspace/yangxh7@xiaopeng.com/pretrain_model",
}


def setup_difix_env(clip_id):
    """设置 difix 渲染所需环境变量，与 tools/debug_reconic/1_render.sh 保持一致。"""
    os.environ["USE_DIFIX"] = DIFIX_ENV_DEFAULTS["USE_DIFIX"]
    os.environ["USE_DIFIX_MODE"] = DIFIX_ENV_DEFAULTS["USE_DIFIX_MODE"]
    os.environ["USE_DIFIX_FINETUNED"] = DIFIX_ENV_DEFAULTS["USE_DIFIX_FINETUNED"]
    os.environ["USE_DIFIX_REFERENCE"] = DIFIX_ENV_DEFAULTS["USE_DIFIX_REFERENCE"]
    os.environ["SCENE_IDX"] = clip_id
    os.environ["REF_PATH"] = os.path.join(
        DIFIX_TRAIN_IMAGES_ORIGIN_ROOT, clip_id, "images_origin/"
    )
    os.environ["CKPT"] = DIFIX_ENV_DEFAULTS["CKPT"]
    os.environ["TORCH_HOME"] = DIFIX_ENV_DEFAULTS["TORCH_HOME"]
    os.environ["HF_HOME"] = DIFIX_ENV_DEFAULTS["HF_HOME"]
    print(
        f"[INFO] difix env: SCENE_IDX={clip_id}, REF_PATH={os.environ['REF_PATH']}, "
        f"CKPT={os.environ['CKPT']}"
    )


def load_train_records(json_path, limit=None):
    """从 JSONL 格式的 train_data.json 加载记录。"""
    records = []
    with open(json_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i < 5:
                continue
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
            if limit is not None and len(records) >= limit:
                break
    return records


def filter_records_with_images(records, need_count, min_frames_per_cam=1, required_cams=None):
    """筛选 difix_train/images_origin 中确有 GT 图片的 clip。"""
    if required_cams is None:
        required_cams = ["cam0"]
    valid = []
    for rec in records:
        base = os.path.join(DIFIX_TRAIN_IMAGES_ORIGIN_ROOT, rec["clip_id"], "images_origin")
        if not os.path.isdir(base):
            continue
        ok = True
        for cam_name in required_cams:
            cam_dir = os.path.join(base, cam_name)
            if not os.path.isdir(cam_dir):
                ok = False
                break
            png_count = sum(1 for f in os.listdir(cam_dir) if f.endswith(".png"))
            if png_count < min_frames_per_cam:
                ok = False
                break
        if ok:
            valid.append(rec)
        if len(valid) >= need_count:
            break
    return valid


def pre_processor(context: dict, **kwargs):
    # ================================= ips args ======================================
    print("SKIP pre_processor")
    print("[INFO] pre_processor")
    print("[INFO] context:")
    print(context)
    print("[INFO] kwargs:")
    print(kwargs)
    return


def subsample_timestamp_records(records, max_per_cam=None):
    """按相机限制帧数，用于测试加速。"""
    if not max_per_cam:
        return records
    per_cam = {}
    for item in records:
        cam = item["sensor_id"]
        per_cam.setdefault(cam, []).append(item)
    out = []
    for cam in sorted(per_cam):
        out.extend(per_cam[cam][:max_per_cam])
    out.sort(key=lambda x: (x["msg_timestamp_nsec"], x["sensor_id"]))
    return out


def build_timestamp_records_from_images_origin(images_origin_base, max_per_cam=None):
    """从 images_origin 子目录名(cam)和 png 文件名(timestamp)构建 timestamp records。"""
    records = []
    if not os.path.isdir(images_origin_base):
        print(f"[WARN] images_origin base not found: {images_origin_base}")
        return records

    for cam_name in sorted(os.listdir(images_origin_base)):
        cam_dir = os.path.join(images_origin_base, cam_name)
        if not os.path.isdir(cam_dir) or not cam_name.startswith("cam"):
            continue
        for fname in os.listdir(cam_dir):
            if not fname.endswith(".png"):
                continue
            stem = fname[:-4]
            if not stem.isdigit():
                continue
            records.append({
                "sensor_id": cam_name,
                "msg_timestamp_nsec": int(stem),
            })
    records.sort(key=lambda x: (x["msg_timestamp_nsec"], x["sensor_id"]))
    records = subsample_timestamp_records(records, max_per_cam)
    print(f"[INFO] built {len(records)} timestamp records from {images_origin_base}")
    return records


def overwrite_calib_transform_from_src(src_dir, dst_dir):
    """用 OSS 解压目录中的 calib.json / transform.json 覆盖目标目录。"""
    for name in ("calib.json", "transform.json"):
        src = os.path.join(src_dir, name)
        dst = os.path.join(dst_dir, name)
        if os.path.isfile(src):
            shutil.copy2(src, dst)
            print(f"[INFO] overwritten {dst} from {src}")


def merge_extracted_model(extracted_dir, model_base):
    """合并 OSS 解压出的 model，并强制覆盖 calib / transform。"""
    os.system(f"cd '{extracted_dir}' && cp -rn . '{model_base}/'")
    overwrite_calib_transform_from_src(extracted_dir, model_base)


def ensure_model_ready(train_data_path, model_base, clip_id, model_version):
    """确保 config 与 checkpoint 可用；修复 model1 未合并的残留目录。"""
    config_file = os.path.join(model_base, "configs/config_sim.yaml")
    ckpt_path = os.path.join(model_base, "trained_model", "checkpoint_final.pth")

    inner_model1 = os.path.join(model_base, "model1")
    if os.path.isdir(inner_model1):
        print(f"[INFO] merging nested model1 into {model_base}")
        merge_extracted_model(inner_model1, model_base)
        os.system(f"rm -rf '{inner_model1}'")

    if os.path.exists(config_file) and os.path.exists(ckpt_path):
        return config_file

    train_data_tar = os.path.join(train_data_path, f"3dgs_model_{model_version}.tgz")
    os.makedirs(train_data_path, exist_ok=True)
    print(f"[INFO] downloading model from oss: {train_data_tar}")
    download_file_from_oss2(
        train_data_tar,
        os.path.join("sim_engine/ips_output_reconic", clip_id, model_version, "3dgs_model.tgz"),
        show_progress=False,
    )
    os.system(f"cd '{train_data_path}' && tar xf '{train_data_tar}'")
    extracted_model1 = os.path.join(train_data_path, "model1")
    if os.path.isdir(extracted_model1):
        if os.path.isdir(model_base):
            merge_extracted_model(extracted_model1, model_base)
            os.system(f"rm -rf '{extracted_model1}'")
        else:
            os.system(f"cd '{train_data_path}' && mv model1 '{model_version}'")
    if os.path.exists(train_data_tar):
        os.system(f"rm -f '{train_data_tar}'")
    return config_file


def write_timestamp_records_json(records, output_path):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)
    return output_path


def _get_vehicle_configs(vehicle_names=None):
    if not vehicle_names:
        return VEHICLE_CONFIGS
    name_set = set(vehicle_names)
    return [(n, p) for n, p in VEHICLE_CONFIGS if n in name_set]


def gpu_processor(context: dict, **kwargs):
    print(f"[GPU] ================================== GPU processor ==================================")
    overwrite = str(kwargs.get('overwrite', False)).lower() == 'true' or int(kwargs.get('overwrite', True)) == 1
    vehicle_names = kwargs.get("vehicle_names")
    max_per_cam = kwargs.get("max_per_cam")

    # 将所需路径添加到 sys.path
    simworld_path = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    omnire_path = os.path.join(simworld_path, 'omnire_joint_trainning', 'src')
    sys.path.extend([omnire_path, simworld_path])
    
    from reconic.simulator.reconic_simulator import ReconicSimulator
    from scripts.render_switch_car import (
        render_switch_car,
        generate_new_calib_and_transform,
        restore_original_calib_and_transform,
    )
    from reconic.multi_vehicle_utils.query_scenario_event import VEHICLE_TYPE_2_ID

    print(f"[GPU] context:")
    print(context)
    print(f"[GPU] kwargs:")
    print(kwargs)
    print(f"[GPU] ================================== GPU processor ==================================")

    vehicle_configs = _get_vehicle_configs(vehicle_names)
    
    for item in context['records']:
        clip_id = item["clip_id"]
        model_version = item["model_version"]
        setup_difix_env(clip_id)
        print(f"[INFO] processing clip {clip_id}")
        
        difix_images_origin_base = os.path.join(
            DIFIX_TRAIN_IMAGES_ORIGIN_ROOT, clip_id, "images_origin"
        )
        timestamp_records = build_timestamp_records_from_images_origin(
            difix_images_origin_base, max_per_cam=max_per_cam
        )
        if not timestamp_records:
            print(f"[WARN] skip clip {clip_id}: no timestamp records from {difix_images_origin_base}")
            continue

        # download model and render model from oss
        train_data_path = f"/workspace/group_share/adc-sim/users/cloudsim/difix/train_data/{clip_id}"
        model_base = os.path.join(train_data_path, model_version)
        renders_needed = []
        for vehicle_name, calib_path in vehicle_configs:
            target_render_path = os.path.join(model_base, f"simulator_render_{vehicle_name}")
            if not os.path.exists(target_render_path) or overwrite:
                renders_needed.append((vehicle_name, calib_path, target_render_path))

        render_success_count = 0

        if not renders_needed:
            print(f"[INFO] all vehicle renders already exist for clip {clip_id}")
        else:
            config_file = ensure_model_ready(
                train_data_path, model_base, clip_id, model_version
            )

            timestamp_records_path = os.path.join(
                model_base, "switch_car_timestamp_records.json"
            )
            write_timestamp_records_json(timestamp_records, timestamp_records_path)

            for vehicle_name, calib_path, target_render_path in renders_needed:
                print(f"[INFO] rendering clip {clip_id} with vehicle {vehicle_name}")

                vehicle_model = VEHICLE_TYPE_2_ID.get(vehicle_name.lower())
                if vehicle_model is None:
                    raise ValueError(f"未知的target_vehicle: {vehicle_name}，无法找到对应的vehicle_model")
                        
                backup_info = None
                backup_info = generate_new_calib_and_transform(
                    model_base, calib_path, timestamp_records_path
                )
                simulator = ReconicSimulator(
                    config_file,
                    cp_simulation=True,
                    iter=None,
                    init_from_feedforward=False,
                    vehicle_model=vehicle_model,
                )

                render_switch_car(
                    simulator, "", timestamp_records_path, save_path=target_render_path
                )
                print(f"[INFO] render clip {clip_id} vehicle {vehicle_name} done: {target_render_path}")
                render_success_count += 1

                if backup_info is not None:
                    restore_original_calib_and_transform(backup_info)

            for path in [
                os.path.join(model_base, "trained_model", "checkpoint_final.pth"),
                os.path.join(model_base, "segs"),
                os.path.join(model_base, "input_ply"),
            ]:
                if os.path.exists(path):
                    os.system(f"rm -rf '{path}'")

        # check if images_origin and render files are identical for each vehicle
        for vehicle_name, _ in vehicle_configs:
            src_images_path = os.path.join(difix_images_origin_base, "cam0")
            src_render_path = os.path.join(
                train_data_path,
                model_version,
                f"simulator_render_{vehicle_name}",
                "redistort_rgb",
                "cam0",
            )
            if os.path.exists(src_images_path) and os.path.exists(src_render_path):
                src_images_files = [x for x in os.listdir(src_images_path) if x.endswith('.png')]
                src_render_files = [x for x in os.listdir(src_render_path) if x.endswith('.png')]
                if len(src_images_files) != len(src_render_files):
                    print(
                        f"[INFO] images_origin and render files are not identical for "
                        f"clip {clip_id} vehicle {vehicle_name}"
                    )
                    continue
                src_images_files_set = set(src_images_files)
                src_render_files_set = set(src_render_files)
                identical_count = len(src_images_files_set & src_render_files_set)
                print(
                    f"[INFO] {vehicle_name}: {identical_count} / {len(src_images_files)} "
                    f"file names are identical"
                )
            else:
                print(
                    f"[INFO] images_origin or render files do not exist for "
                    f"clip {clip_id} vehicle {vehicle_name}"
                )


def main():
    records = load_train_records(DEFAULT_TRAIN_DATA_JSON, limit=2)
    print(f"[TEST] using first {len(records)} records from {DEFAULT_TRAIN_DATA_JSON}")
    for i, rec in enumerate(records):
        print(f"[TEST] record[{i}]: clip_id={rec['clip_id']}, model_version={rec['model_version']}")

    context = {"records": records}
    # 测试：每相机 2 帧、h93aes 车型；正式跑去掉 max_per_cam / vehicle_names 限制
    gpu_processor(
        context,
        overwrite=True,
        vehicle_names=["e29", "f01es", "h93aes"],
        max_per_cam=10,
    )


if __name__ == "__main__":
    main()
