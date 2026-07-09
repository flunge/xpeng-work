import os
import sys
import shutil
import tarfile
import tempfile
import subprocess
import json

from omegaconf import OmegaConf


_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, "..", "..", ".."))
_UCP_DIR = os.path.join(_REPO_ROOT, "pipeline", "ucp")
if _UCP_DIR not in sys.path:
    sys.path.insert(0, _UCP_DIR)

from download_file_from_oss2 import download_file_from_oss2


def _safe_mkdir(path):
    os.makedirs(path, exist_ok=True)


def _assert_safe_root_path(path, label):
    abs_path = os.path.abspath(path)
    if abs_path in ("/", ""):
        raise RuntimeError(f"Unsafe {label}: {abs_path}")
    if not abs_path.startswith("/workspace/"):
        raise RuntimeError(f"Unsafe {label}, must be under /workspace: {abs_path}")
    return abs_path


def _prompt_text(label, default=None, required=False):
    while True:
        if default is None:
            raw = input(f"{label}: ").strip()
        else:
            raw = input(f"{label} [{default}]: ").strip()

        if raw:
            return raw
        if default is not None:
            return default
        if not required:
            return ""
        print("[WARN] This field is required.")


def _prompt_jobs(default_jobs):
    print("\n[INFO] Configure training jobs. Press Enter on clip_id to finish.")
    print("[INFO] One job fields: clip_id, train_yaml, cameras_id, priority")
    use_default = _prompt_text("Use default jobs? (y/n)", "y").lower() == "y"
    if use_default:
        return default_jobs

    jobs = {}
    while True:
        clip_id = _prompt_text("clip_id (empty to finish)", "")
        if clip_id == "":
            break

        train_yaml = _prompt_text("train_yaml", "sim3dgs_v416.yaml")
        cameras_id = _prompt_text("cameras_id", "1347")
        priority = _prompt_text("priority", "normal")

        jobs[clip_id] = {
            "train_yaml": train_yaml,
            "cameras_id": cameras_id,
            "priority": priority,
        }

    if not jobs:
        raise RuntimeError("No jobs configured.")
    return jobs


def _collect_settings():
    print("\n[INFO] Please input runtime settings.")

    data_save_root = _prompt_text(
        "data_save_root (preprocess data dir)",
        "/workspace/zhouf4@xiaopeng.com/dataset/xpeng/fm_vision/20",
    )
    train_output_root = _prompt_text(
        "train_output_root (training output dir)",
        "/workspace/zhouf4@xiaopeng.com/ips_output_reconic",
    )
    ips_model_version = _prompt_text("ips_model_version", "v415")
    bucket_name = _prompt_text("bucket_name", "cloudsim-ci-sh")

    data_save_root = _assert_safe_root_path(data_save_root, "data_save_root")
    train_output_root = _assert_safe_root_path(train_output_root, "train_output_root")

    default_jobs = {
        "c-20e28d7c-00bb-3751-9db3-5c88f7b004cd": {
            "train_yaml": "sim3dgs_v416.yaml",
            "cameras_id": "1347",
            "priority": "normal",
        },
    }
    jobs = _prompt_jobs(default_jobs)

    return data_save_root, train_output_root, ips_model_version, bucket_name, jobs


def _pick_extracted_root(extract_dir):
    model1_dir = os.path.join(extract_dir, "model1")
    if os.path.isdir(model1_dir):
        return model1_dir

    children = [
        os.path.join(extract_dir, name)
        for name in os.listdir(extract_dir)
        if name != "__MACOSX"
    ]
    dir_children = [p for p in children if os.path.isdir(p)]
    file_children = [p for p in children if os.path.isfile(p)]

    if len(dir_children) == 1 and len(file_children) == 0:
        return dir_children[0]
    return extract_dir


def _stage_data_to_clip_dir(src_root, clip_dir):
    _safe_mkdir(clip_dir)
    for name in os.listdir(src_root):
        src = os.path.join(src_root, name)
        dst = os.path.join(clip_dir, name)
        if os.path.exists(dst):
            raise RuntimeError(
                f"Refuse to overwrite existing path: {dst}. "
                "Please clean target dir manually if you want to replace data."
            )
        shutil.move(src, dst)


def _merge_data_to_clip_dir(src_root, clip_dir):
    """Merge data from src_root to clip_dir, skipping existing files without error."""
    _safe_mkdir(clip_dir)
    for name in os.listdir(src_root):
        src = os.path.join(src_root, name)
        dst = os.path.join(clip_dir, name)
        if os.path.exists(dst):
            print(f"[INFO] Skip existing: {dst}")
            continue
        shutil.move(src, dst)


def _write_pose_matrix_txt(matrix, out_path):
    if len(matrix) != 4 or any(len(row) != 4 for row in matrix):
        raise RuntimeError(f"Invalid pose matrix shape for {out_path}, expected 4x4")
    with open(out_path, "w", encoding="utf-8") as f:
        for row in matrix:
            f.write(" ".join(f"{float(v):.10f}" for v in row) + "\n")


def _ensure_pose_dirs(clip_dir):
    ego_dir = os.path.join(clip_dir, "ego_pose")
    lidar_dir = os.path.join(clip_dir, "lidar_pose")

    ego_ready = os.path.isdir(ego_dir) and any(name.endswith(".txt") for name in os.listdir(ego_dir))
    lidar_ready = os.path.isdir(lidar_dir) and any(name.endswith(".txt") for name in os.listdir(lidar_dir))
    if ego_ready and lidar_ready:
        return

    localpose_path = os.path.join(clip_dir, "localpose.json")
    if not os.path.isfile(localpose_path):
        raise RuntimeError(f"Missing localpose.json, cannot build pose directories: {localpose_path}")

    with open(localpose_path, "r", encoding="utf-8") as f:
        localpose = json.load(f)
    if not isinstance(localpose, dict) or not localpose:
        raise RuntimeError(f"localpose.json is empty or invalid: {localpose_path}")

    timestamps = sorted(localpose.keys(), key=lambda x: int(x))

    _safe_mkdir(ego_dir)
    _safe_mkdir(lidar_dir)

    localpose_lidar_path = os.path.join(clip_dir, "localpose_lidar.json")
    localpose_lidar = {}
    if os.path.isfile(localpose_lidar_path):
        with open(localpose_lidar_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            localpose_lidar = loaded

    for idx, ts in enumerate(timestamps):
        filename = f"{idx:03d}.txt"
        ego_out = os.path.join(ego_dir, filename)
        lidar_out = os.path.join(lidar_dir, filename)

        if not os.path.isfile(ego_out):
            _write_pose_matrix_txt(localpose[ts], ego_out)

        lidar_matrix = localpose_lidar.get(ts, localpose[ts])
        if not os.path.isfile(lidar_out):
            _write_pose_matrix_txt(lidar_matrix, lidar_out)

    print(f"[INFO] Pose dirs ready: {ego_dir}, {lidar_dir}")


def _extract_archive(local_pkg, target_dir):
    try:
        with tarfile.open(local_pkg, "r:*") as tar:
            tar.extractall(path=target_dir)
        return
    except tarfile.ReadError:
        pass

    # Some upstream artifacts are zstd-compressed tar streams.
    # Fallback to system tar with zstd support.
    try:
        subprocess.check_call(["tar", "--zstd", "-xf", local_pkg, "-C", target_dir])
    except Exception as exc:
        raise RuntimeError(f"Failed to extract archive: {local_pkg}") from exc


def _download_preprocess_data(clip_id, data_save_root, ips_model_version, bucket_name=None):
    clip_dir = os.path.join(data_save_root, clip_id)
    marker_file = os.path.join(clip_dir, "transform.json")
    if os.path.isfile(marker_file):
        _ensure_pose_dirs(clip_dir)
        print(f"[INFO] Skip download, preprocess data already exists: {clip_dir}")
        return clip_dir

    if os.path.isdir(clip_dir) and os.listdir(clip_dir):
        raise RuntimeError(
            f"Target clip dir is not empty and has no recognized marker file: {clip_dir}. "
            "Refusing to modify existing local data."
        )

    _safe_mkdir(clip_dir)

    object_key = os.path.join(
        "sim_engine",
        "datasets_vision",
        clip_id,
        f"pose_and_pcd_sim3dgs_{ips_model_version}",
        "pose_and_pcd.tgz",
    )
    local_pkg = os.path.join(data_save_root, f"{clip_id}_pose_and_pcd_sim3dgs_{ips_model_version}.tgz")
    ok = download_file_from_oss2(
        local_file_path=local_pkg,
        object_key=object_key,
        show_progress=True,
        bucket_name=bucket_name,
    )
    if not ok:
        raise RuntimeError(f"Failed to download preprocess package from OSS: {object_key}")

    print(f"[INFO] Downloaded preprocess package: {object_key}")

    with tempfile.TemporaryDirectory(prefix=f"extract_{clip_id}_", dir=data_save_root) as tmp_dir:
        _extract_archive(local_pkg, tmp_dir)
        src_root = _pick_extracted_root(tmp_dir)
        _stage_data_to_clip_dir(src_root, clip_dir)

    if os.path.exists(local_pkg):
        os.remove(local_pkg)

    # Download complete dataset package (images, masks, segs, depth, etc.)
    dataset_object_key = os.path.join(
        "sim_engine",
        "datasets_vision",
        clip_id,
        "complete",
        "dataset.tgz",
    )
    dataset_local_pkg = os.path.join(data_save_root, f"{clip_id}_dataset_complete.tgz")
    ok = download_file_from_oss2(
        local_file_path=dataset_local_pkg,
        object_key=dataset_object_key,
        show_progress=True,
        bucket_name=bucket_name,
    )
    if not ok:
        raise RuntimeError(f"Failed to download dataset package from OSS: {dataset_object_key}")

    print(f"[INFO] Downloaded dataset package: {dataset_object_key}")

    with tempfile.TemporaryDirectory(prefix=f"extract_dataset_{clip_id}_", dir=data_save_root) as tmp_dir:
        _extract_archive(dataset_local_pkg, tmp_dir)
        src_root = _pick_extracted_root(tmp_dir)
        _merge_data_to_clip_dir(src_root, clip_dir)

    if os.path.exists(dataset_local_pkg):
        os.remove(dataset_local_pkg)

    required = [
        "transform.json",
        "annotation_for_train.json",
        "localpose.json",
        "calib.json",
        "anchorpose.json",
        "ground_mask.npy",
        os.path.join("input_ply", "points3D_bkgd.ply"),
        # os.path.join("input_ply", "points3D_tfl.ply"),
    ]
    missing = [x for x in required if not os.path.exists(os.path.join(clip_dir, x))]
    if missing:
        raise RuntimeError(f"Preprocess data incomplete for {clip_id}, missing: {missing}")

    _ensure_pose_dirs(clip_dir)

    return clip_dir


def _prepare_train_config(base_config_path, out_config_path, data_root, clip_id):
    cfg = OmegaConf.load(base_config_path)
    cfg.data.data_root = data_root
    cfg.data.scene_idx = clip_id
    _safe_mkdir(os.path.dirname(out_config_path))
    OmegaConf.save(cfg, out_config_path)
    return out_config_path


def _run_training(config_path, clip_id, cameras_id, output_root, priority):
    deploy_reconic = os.path.join(_REPO_ROOT, "pipeline", "fuyao", "train_3dgs", "deploy_reconic.sh")
    cmd = [
        "bash",
        deploy_reconic,
        config_path,
        clip_id,
        cameras_id,
        output_root,
        priority,
    ]
    print(f"[INFO] Launch training: {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=_REPO_ROOT)


if __name__ == "__main__":
    (
        data_save_root,
        train_output_root,
        ips_model_version,
        bucket_name,
        jobs,
    ) = _collect_settings()

    cfg_repo_dir = os.path.join(_REPO_ROOT, "pipeline", "configs")
    cfg_work_dir = os.path.join(_REPO_ROOT, "pipeline", "fuyao", "train_3dgs", "generated_configs")
    _safe_mkdir(cfg_work_dir)

    for clip_id, job in jobs.items():
        train_yaml = job["train_yaml"]
        cameras_id = str(job["cameras_id"])
        priority = str(job.get("priority", "normal"))

        print("=" * 80)
        print(f"[INFO] Start job clip={clip_id}, ips_model_version={ips_model_version}, yaml={train_yaml}")

        clip_dir = _download_preprocess_data(
            clip_id=clip_id,
            data_save_root=data_save_root,
            ips_model_version=ips_model_version,
            bucket_name=bucket_name,
        )
        print(f"[INFO] Data ready: {clip_dir}")

        base_cfg = os.path.join(cfg_repo_dir, train_yaml)
        if not os.path.isfile(base_cfg):
            raise FileNotFoundError(f"Train yaml not found: {base_cfg}")

        run_cfg = os.path.join(cfg_work_dir, f"{clip_id}_{os.path.basename(train_yaml)}")
        _prepare_train_config(
            base_config_path=base_cfg,
            out_config_path=run_cfg,
            data_root=data_save_root,
            clip_id=clip_id,
        )
        print(f"[INFO] Generated train config: {run_cfg}")

        _run_training(
            config_path=run_cfg,
            clip_id=clip_id,
            cameras_id=cameras_id,
            output_root=train_output_root,
            priority=priority,
        )

    print("[INFO] All jobs done.")