import sys
import os
import logging
import torch
import yaml
import importlib
import shutil
import random
import time
from datetime import datetime
import traceback
import psutil

# 添加 reconic 模块路径，以便导入 cloudsim_request
_reconic_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "omnire_joint_trainning", "src")
if _reconic_path not in sys.path:
    sys.path.insert(0, _reconic_path)
from reconic.multi_vehicle_utils.cloudsim_request import cloudsim_request

from post_process import post_process
from download_file_from_oss2 import download_file_from_oss2
from upload2oss import upload_train_model_to_oss_fast, upload, compress_and_upload_fast
from ips_utils import (
    get_timestamps,
    get_subrun_adapted_start_timestamp,
    resolve_trigger_timestamp,
)
from quality_check_utils import get_render_check_status
from pipeline_error_codes import classify_error

RUNTIME_TMP_DIR_BASE = "/tmp/3dgs_temp_data"


def _get_and_increment_retry_count(root_path, clip_id):
    """Read and increment the GPU retry count from pipeline_runtime_values.yaml. Returns current attempt number (0-based)."""
    clip_path = os.path.join(root_path, clip_id)
    values = _load_pipeline_runtime_values(clip_path)
    count = values.get("gpu_retry_count", 0)
    values["gpu_retry_count"] = count + 1
    _persist_pipeline_runtime_values(clip_path, values)
    return count


def _upload_extra_info_to_oss(extra_info, result_path_oss, clip_path, logger=None):
    """Dump extra_info to JSON in clip_path and upload to the same OSS path as the model."""
    import json
    retry_count = extra_info.get("gpu_retry_count", 0)
    filename = "extra_info.json" if retry_count == 0 else f"extra_info_{retry_count}.json"
    json_path = os.path.join(clip_path, filename)
    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(extra_info, f, ensure_ascii=False, indent=2)
        upload(json_path, filename, bucket_name='cloudsim-ci-sh', oss_directory=result_path_oss)
        if logger:
            logger.info(f"[INFO] Uploaded {filename} to {result_path_oss}")
    except Exception as e:
        print(f"[WARN] Failed to upload {filename}: {e}")


def _persist_pipeline_runtime_values(clip_path, values, logger=None):
    os.makedirs(clip_path, exist_ok=True)
    runtime_value_path = os.path.join(clip_path, "pipeline_runtime_values.yaml")
    with open(runtime_value_path, "w", encoding="utf-8") as fp:
        yaml.safe_dump(values, fp, allow_unicode=True)
    if logger is not None:
        logger.info(f"[INFO] Saved pipeline runtime values to {runtime_value_path}")


def _load_pipeline_runtime_values(clip_path, logger=None):
    runtime_value_path = os.path.join(clip_path, "pipeline_runtime_values.yaml")
    if not os.path.exists(runtime_value_path):
        if logger is not None:
            logger.warning(f"[WARN] Runtime values file not found: {runtime_value_path}")
        return {}
    with open(runtime_value_path, "r", encoding="utf-8") as fp:
        values = yaml.safe_load(fp) or {}
    if logger is not None:
        logger.info(f"[INFO] Loaded pipeline runtime values from {runtime_value_path}")
    return values


def _get_runtime_values_for_notify(context, clip_path, logger=None):
    runtime_values = _load_pipeline_runtime_values(clip_path, logger)
    pipeline_start_time = runtime_values.get("pipeline_start_time", 0)
    cpu_pipeline_time_cost = runtime_values.get("cpu_pipeline_time_cost", 0)
    data_upload_time_cost = runtime_values.get("data_upload_time_cost", 0)
    pre_processor_end_time = runtime_values.get("pre_processor_end_time", 0)
    case_time = runtime_values.get("case_time", 0)
    case_distance = runtime_values.get("case_distance", 0)
    print(f"pipeline_start_time: {pipeline_start_time}")
    print(f"cpu_pipeline_time_cost: {cpu_pipeline_time_cost}")
    print(f"data_upload_time_cost: {data_upload_time_cost}")
    print(f"case_time: {case_time}")
    print(f"case_distance: {case_distance}")

    if pipeline_start_time == 0:
        pipeline_time_cost = 0
    else:
        pipeline_time_cost = time.time() - pipeline_start_time

    # Calculate scheduling wait time between pre_processor and gpu_processor
    gpu_processor_start_time = context.get("gpu_processor_start_time", 0)
    if pre_processor_end_time > 0 and gpu_processor_start_time > 0:
        scheduling_wait_time = gpu_processor_start_time - pre_processor_end_time
    else:
        scheduling_wait_time = -1

    # Subtract scheduling wait from pipeline_time_cost
    effective_pipeline_time_cost = pipeline_time_cost - scheduling_wait_time if scheduling_wait_time >= 0 else -1

    # Total pre_processor time (includes dump + cpu_pipeline + data_upload)
    if pipeline_start_time > 0 and pre_processor_end_time > 0:
        pre_processor_time_cost = pre_processor_end_time - pipeline_start_time
    else:
        pre_processor_time_cost = -1

    return {
        "pipeline_time_cost": pipeline_time_cost,
        "effective_pipeline_time_cost": effective_pipeline_time_cost,
        "scheduling_wait_time": scheduling_wait_time,
        "cpu_pipeline_time_cost": cpu_pipeline_time_cost,
        "data_upload_time_cost": data_upload_time_cost,
        "pre_processor_time_cost": pre_processor_time_cost,
        "case_time": case_time,
        "case_distance": case_distance,
    }


def _as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "t", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "f", "no", "n", "off", ""}:
            return False
    return bool(value)


def _notify_cloudsim_on_error(context: dict, status: str, error_message: str):
    if os.environ.get('REQUEST_JOB_TYPE') != 'cloudsim':
        return

    error_info = {
        'status': status,
        'error_message': error_message,
        "input_id_type": "clip_id",
        **({"cloudsim_job_id": context["cloudsim_job_id"]} if context.get("cloudsim_job_id") else {}),
        **({"ucp_job_id": context["ucp_job_id"]} if context.get("ucp_job_id") else {}),
    }
    try:
        context["data_record"].notify_cloudsim_3dgs(
            is_user_label=True, extra_info=error_info
        )
    except Exception as notify_error:
        print(f"Failed to send error notification: {notify_error}")


def _fetch_cloudsim_task_info(context: dict, **kwargs):
    """仅在 cloudsim 模式下调用 CloudSim 接口获取任务信息"""
    if os.environ.get('REQUEST_JOB_TYPE') != 'cloudsim':
        return

    config_key = kwargs.get('config_key')
    if not config_key:
        raise ValueError("cloudsim config_key is required")
    url = "http://cloudsim.xiaopeng.link/simulation/threedgs/get_threedgs_task_params/"
    data = {"config_key": config_key}
    task_response = cloudsim_request(url, data)
    context["cloudsim_task_info"] = task_response
    # 解析返回数据，提取 job_id 和 jira_relative_seconds
    clip_id = context["id"]
    clip_task_info = task_response.get("data", {}).get(clip_id)
    if clip_task_info is None:
        print(f"[WARN] clip_id {clip_id} not found in cloudsim task response data")
        return
    context["cloudsim_job_id"] = clip_task_info.get("job_id", "")
    context["cloudsim_jira_relative_seconds"] = clip_task_info.get("jira_relative_seconds")
    context["cloudsim_issue_reason"] = clip_task_info.get("issue_reason")
    context["cloudsim_issue_description"] = clip_task_info.get("issue_description")
    print(f"[INFO] CloudSim task info: {task_response}")


def pre_processor(context: dict, **kwargs):
    try:
        ucp_job_id = os.environ.get('UCP_JOB_ID', '')
        context['ucp_job_id'] = ucp_job_id
        _fetch_cloudsim_task_info(context, **kwargs)
        _execute_pre_processor(context, **kwargs)
    except Exception as e:
        classified = classify_error(e)
        _notify_cloudsim_on_error(
            context,
            status='pre_processor_error',
            error_message=str(classified),
        )
        # 重新抛出结构化异常：后端记录的字符串即包含 错误类型/错误ID/完整详情。
        # 用 from None 抑制链式上下文，避免后端格式化 traceback 时原始栈出现两份
        # （完整原始栈已保存在 classified 的 error_detail 字段里）。
        raise classified from None


def _execute_pre_processor(context: dict, **kwargs):
    context["pipeline_start_time"] = time.time()
    clip_id = context["id"]
    print(
        f"[SIMDIAG] [pre_processor_start] clip={clip_id}",
        flush=True
    )
    # ================================= ips args ======================================
    upload_images_origin = kwargs.get('upload_images_origin', True)
    copy_images_origin_to_fuyao = kwargs.get('copy_images_origin_to_fuyao', False)
    preprocess_config_name = kwargs.get(
        'preprocess_config_name', 'sim3dgs_v410_preprocess.yaml'
    )
    pose_type = kwargs.get('pose_type', 'gxodips_posemapping')
    # =================================================================================

    ips_logger = context["logger"]
    clip_id = context["id"]
    root_path: str = context["root_path"]
    ips_logger.info(f"[INFO] Start preprocessor of {clip_id} with root {root_path}.")
    init_ips()
    # 将所需路径添加到 sys.path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    preprocess_path = os.path.join(current_dir, 'xpeng_data_process')
    sys.path.append(preprocess_path)

    now = datetime.now()
    random_num = random.randint(1000000, 9999999)
    current_time = now.strftime("%Y%m%d_%H%M%S") + "_" + str(random_num)

    ######################################### START #########################################
    from settings.config import (
        make_default_settings,
        make_cfg,
        make_case_specific_settings,
    )
    from generate_dataset_data import dump_one_clip, process_before_dump
    import pipelines

    # prepare training config
    local_config_path = (
        f'/code/models/street_gaussians/configs/run_preprocess_{current_time}.yaml'
    )
    remote_config_path = f'sim_engine/ips_configs/{preprocess_config_name}'
    if not download_file_from_oss2(local_config_path, object_key=remote_config_path):
        raise UserWarning(
            f"[ERROR] download config run_preprocess.yaml from oss failed!\n"
        )

    default_cfg = make_default_settings()
    cfg_list, current_cfg = make_cfg(local_config_path, default_cfg)
    config = cfg_list[0]
    config.root = root_path
    config.clip_id = clip_id
    config.dataset_name = "ips_dataset"
    # config.steps_controller.camopt_processor = True
    config = make_case_specific_settings(config)

    clip_record = context["data_record"]
    loader = context["data_loader"]

    clip_calib = process_before_dump(config, clip_record, loader)
    dump_one_clip(config, clip_record, clip_calib, pose_type)
    ips_logger.info(f"[INFO] {clip_id} dump finished.")

    time_cpu0 = time.time()
    info_dict = {}
    pipelines.pipeline_vision_cpu(config, info_dict)
    time_cpu1 = time.time()
    cpu_pipeline_time_cost = time_cpu1 - time_cpu0
    context["cpu_pipeline_time_cost"] = cpu_pipeline_time_cost
    context["case_time"] = info_dict["case_time"]
    context["case_distance"] = info_dict["case_distance"]

    data_upload_t0 = time.time()
    os.makedirs(os.path.join(root_path, clip_id), exist_ok=True)
    log_file_path = os.path.join(root_path, clip_id, "ips_time_log.txt")
    try:
        with open(log_file_path, 'a', encoding='utf-8') as file:
            file.write(
                f'[ips time log] reconic cpu pipeline time cost {cpu_pipeline_time_cost} s, clip{clip_id}\n'
            )
        print(f"[ips debug log]success write time to log: {log_file_path}")
    except Exception as e:
        print(f"[ips debug log]error when write time to log: {e}")
    ips_logger.info(f"[INFO] {clip_id} preprocessing finished.")

    _images_origin_to_fuyao_handler(copy_images_origin_to_fuyao, config, ips_logger)

    # START Compress origin images and Upload to OSS
    if _as_bool(upload_images_origin, default=True):
        result_path_oss = f'sim_engine/datasets/{clip_id}/images_origin'
        temp_output_path = compress_and_upload_fast(
            os.path.join(config['clip_path'], 'images_origin'),
            result_path_oss,
            suffix=str(current_time),
        )
        ips_logger.info(
            f"[INFO] {clip_id} upload images_origin ({temp_output_path}) finished."
        )
        os.system(f"rm -rf {temp_output_path}")
    data_upload_time_cost = time.time() - data_upload_t0

    print(
        f"[SIMDIAG] [pre_processor_done] clip={clip_id}",
        flush=True
    )
    _persist_pipeline_runtime_values(
        config["clip_path"],
        {
            "pipeline_start_time": context.get("pipeline_start_time"),
            "cpu_pipeline_time_cost": context.get("cpu_pipeline_time_cost"),
            "case_time": context.get("case_time"),
            "case_distance": context.get("case_distance"),
            "data_upload_time_cost": data_upload_time_cost,
            "pre_processor_end_time": time.time(),
        },
        ips_logger,
    )


def _images_origin_to_fuyao_handler(copy_images_origin_to_fuyao, config, logger):

    if not _as_bool(copy_images_origin_to_fuyao, default=False):
        return
    source_images_origin = os.path.join(config['clip_path'], 'images_origin')
    target_images_origin = f"/workspace/group_share/adc-sim/users/cloudsim/images_origin/{config.clip_id}/images_origin"
    print(f"simdebug source_images_origin = {source_images_origin}, target_images_origin = {target_images_origin}")
    if not os.path.exists(source_images_origin):
        error_msg = f"Source images_origin not found: {source_images_origin}"
        raise FileNotFoundError(error_msg)

    try:
        if os.path.exists(target_images_origin):
            logger.info(f"[INFO] existing target directory: {target_images_origin}")
            return 
        os.makedirs(os.path.dirname(target_images_origin), exist_ok=True)
        shutil.copytree(source_images_origin, target_images_origin)

        logger.info(
            f"[INFO] Copied images_origin to fuyao workspace: {target_images_origin}"
        )

    except Exception as e:
        error_msg = f"Failed to copy images_origin to fuyao workspace: {str(e)}"
        logger.error(f"[ERROR] {error_msg}")
        raise Exception(error_msg) from e


def gpu_processor(context: dict, **kwargs):
    try:
        ucp_job_id = os.environ.get('UCP_JOB_ID', '')
        context['ucp_job_id'] = ucp_job_id
        _fetch_cloudsim_task_info(context, **kwargs)
        _cleanup_stale_runtime_tmp_dirs()
        _init_tmp_dir(context)
        _execute_gpu_processor(context, **kwargs)
    except Exception as e:
        classified = classify_error(e)
        _notify_cloudsim_on_error(
            context,
            status='gpu_processor_error',
            error_message=str(classified),
        )
        # 重新抛出结构化异常：后端记录的字符串即包含 错误类型/错误ID/完整详情。
        # 用 from None 抑制链式上下文，避免后端格式化 traceback 时原始栈出现两份
        # （完整原始栈已保存在 classified 的 error_detail 字段里）。
        raise classified from None
    finally:
        _cleanup_tmp_dir(context)
        print("[INFO] Temporary directory cleaned up.")


def _execute_gpu_processor(context: dict, **kwargs):
    clip_id = context["id"]
    context["gpu_processor_start_time"] = time.time()
    context["gpu_retry_count"] = _get_and_increment_retry_count(
        context["root_path"], clip_id
    )
    print(
        f"[SIMDIAG] [gpu_processor_start] clip={clip_id} retry={context['gpu_retry_count']}",
        flush=True
    )
    # 创建配置上下文
    config_context = _create_config_context(context, kwargs)

    # Prepare training config
    config = _prepare_config(config_context)

    # Run GPU preprocess
    _run_gpu_preprocess(context, config, config_context)
    if config_context.fast_verification:
        print(f"[INFO] Fast verification is enabled, running feedforward postprocess.")
        feedforward_t0 = time.time()
        trained_model_folder = (
            f'trained_model_{config_context.model_version}'
            if config_context.ips_model_suffix == ''
            else f'trained_model_{config_context.model_version}_{config_context.ips_model_suffix}'
        )
        result_path_oss1 = (
            f'sim_engine/{config_context.ips_oss_folder}/{config_context.clip_id}/{trained_model_folder}_feedforward_1347'
        )
        output_path_root = (
            f"/code/driverstudio_output_{config_context.clip_id}_{config_context.current_time}_feedforward"
        )
        model_output_path = os.path.join(output_path_root, "drivestudio", "omnire")

        evaluation_oss_url = _run_feedforward_postprocess(
            config=config,
            config_context=config_context,
            model_output_path=model_output_path,
            output_path_root=output_path_root,
        )
        start_timestamp, end_timestamp = get_timestamps(model_output_path)
        temp_output_path = upload_train_model_to_oss_fast(
            model_output_path, result_path_oss1, suffix=str(config_context.current_time)
        )
        config_context.ips_logger.info(
            f"[INFO] {config_context.clip_id} upload train model finished ({temp_output_path})."
        )
        os.system(f"rm -rf {temp_output_path}")
        context["feedforward_postprocess_time_cost"] = time.time() - feedforward_t0

        _notify_cloudsim_feedforward(
            context=context,
            config_context=config_context,
            result_path_oss1=result_path_oss1,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            dataset_root=config.clip_path,
            evaluation_oss_url=evaluation_oss_url,
            config=config,
        )

    # Upload datasets if needed
    dataset_upload_t0 = time.time()
    _upload_datasets(config, config_context)
    context["dataset_upload_time_cost"] = time.time() - dataset_upload_t0

    # Train model
    train_stage_t0 = time.time()
    (
        result_path_oss1,
        model_output_path,
        temp_output_path,
        start_timestamp,
        end_timestamp,
        model_upload_time_cost,
    ) = _train_model(config, config_context)
    context["reconic_train_time_cost"] = time.time() - train_stage_t0 - model_upload_time_cost
    context["model_upload_time_cost"] = model_upload_time_cost

    # Send initial message to Cloudsim (training complete)
    _send_initial_cloudsim_message(
        context,
        start_timestamp,
        end_timestamp,
        result_path_oss1,
        config_context,
        config,
    )

    # Run post-process and send evaluation update
    _run_post_process_and_update_cloudsim(
        context, model_output_path, config, result_path_oss1, config_context
    )

    os.system(f"rm -rf {temp_output_path}")
    print(
        f"[SIMDIAG] [gpu_processor_done] clip={config_context.clip_id}",
        flush=True
    )


def _create_config_context(context, kwargs):
    class ConfigContext:
        def __init__(self, context, kwargs):
            # ips args
            self.ips_oss_folder = kwargs.get('ips_oss_folder', 'ips_output_reconic')
            self.ips_model_suffix = kwargs.get('ips_model_suffix', '')
            self.oss_config_name = kwargs.get('oss_config_name', 'sim3dgs_v410.yaml')
            self.preprocess_config_name = kwargs.get(
                'preprocess_config_name', 'sim3dgs_v410_preprocess.yaml'
            )
            self.model_version = kwargs.get('model_version', 'sim3dgs_v410')
            self.clip_type = kwargs.get('clip_type', 'h265-clip-portal-latest')
            self.dataset_suffix = kwargs.get('dataset_suffix', '')
            self.ppu_run = _as_bool(kwargs.get('ppu_run', True), default=True)
            self.is_dynamic = kwargs.get('is_dynamic', True)
            self.is_reconic = kwargs.get('is_reconic', True)
            self.enable_post_process = _as_bool(
                kwargs.get('enable_post_process', True), default=True
            )
            self.render_complete = _as_bool(
                kwargs.get('render_complete', False), default=False
            )
            self.enable_fid = _as_bool(kwargs.get('enable_fid', False), default=False)

            self.is_ppu_run = self.ppu_run
            self.is_fm = _as_bool(kwargs.get('is_fm', False), default=False)
            self.is_fm_bool = self.is_fm
            self.upload_dataset = _as_bool(
                kwargs.get('upload_dataset', False), default=False
            )
            self.fast_verification = _as_bool(
                kwargs.get('fast_verification', False), default=False
            )
            self.upload_pose_and_pcd = _as_bool(
                kwargs.get('upload_pose_and_pcd', True), default=True
            )
            self.num_workers = int(kwargs.get('num_workers', 4))
            self.prefetch_factor = int(kwargs.get('prefetch_factor', 4))
            self.fuyao_log_path = kwargs.get(
                'fuyao_log_path', '/workspace/group_share/adc-sim/users/yangxh7/logs'
            )

            self.now = datetime.now()
            self.random_num = random.randint(1000000, 9999999)
            self.current_time = (
                self.now.strftime("%Y%m%d_%H%M%S") + "_" + str(self.random_num)
            )

            self.ips_logger = context["logger"]
            self.clip_id = context["id"]
            self.root_path = context["root_path"]

            self.ips_logger.info(
                f"[INFO] Start gpu_processor of {self.clip_id} with root {self.root_path} with {kwargs}."
            )

    return ConfigContext(context, kwargs)


def _prepare_config(config_context):
    from settings.config import (
        make_default_settings,
        make_cfg,
        make_case_specific_settings,
    )

    local_config_path = f'/code/models/street_gaussians/configs/run_preprocess_{config_context.current_time}.yaml'
    remote_config_path = (
        f'sim_engine/ips_configs/{config_context.preprocess_config_name}'
    )

    os.makedirs(os.path.dirname(local_config_path), exist_ok=True)
    if not download_file_from_oss2(local_config_path, object_key=remote_config_path):
        raise UserWarning(
            f"[ERROR] download config run_preprocess.yaml from oss failed!\n"
        )

    default_cfg = make_default_settings()
    cfg_list, current_cfg = make_cfg(local_config_path, default_cfg)
    config = cfg_list[0]
    config.root = RUNTIME_TMP_DIR_BASE

    config.clip_id = config_context.clip_id
    config.dataset_name = "ips_dataset"
    config.pretrained_model_path = "/root/recon_pretrained_models/"
    config = make_case_specific_settings(config)
    config.ppu_deploy = config_context.is_ppu_run
    return config


def _set_preprocess_specific_time_cost(context, timing_dict):
    context["preprocess_specific_time_cost"] = {}
    context["preprocess_specific_time_cost"]["img_process"] = timing_dict["img"] / 60.0 if timing_dict["img"] is not None else 0
    context["preprocess_specific_time_cost"]["sam3d"] = timing_dict["sam3d"] / 60.0 if timing_dict["sam3d"] is not None else 0
    context["preprocess_specific_time_cost"]["mvsnet"] = timing_dict["mvsnet"] / 60.0 if timing_dict["mvsnet"] is not None else 0
    context["preprocess_specific_time_cost"]["ground"] = timing_dict["ground"] / 60.0 if timing_dict["ground"] is not None else 0
    context["preprocess_specific_time_cost"]["evolsplat"] = timing_dict["evolsplat"] / 60.0 if timing_dict["evolsplat"] is not None else 0
    context["preprocess_specific_time_cost"]["scube"] = timing_dict["scube"] / 60.0 if timing_dict["scube"] is not None else 0
    return

def _run_gpu_preprocess(context, config, config_context):
    # 将所需路径添加到 sys.path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    preprocess_path = os.path.join(current_dir, 'xpeng_data_process')
    sys.path.append(preprocess_path)

    os.environ['TORCH_HOME'] = (
        "/cpfs/batch_inference_models/3dgs_models/2025-08-08/torch_cache"
    )
    os.environ['HF_HOME'] = (
        '/cpfs/batch_inference_models/3dgs_models/2025-08-08/pretrain_model'
    )
    os.environ['LPIPS_MODEL_PATH'] = (
        '/cpfs/batch_inference_models/lilps_alex-20250915210318000-lvy10/alex.pth'
    )

    import pipelines

    config_context.ips_logger.info(f"[INFO] Start preprocess_main with config:\n")
    config_context.ips_logger.info(f"{config}")
    timing_dict = {}
    time_gpu0 = time.time()
    pipelines.pipeline_vision_gpu(config, timing_dict, fast_verification=config_context.fast_verification)
    time_gpu1 = time.time()
    gpu_pipeline_time_cost = time_gpu1 - time_gpu0
    context["gpu_pipeline_time_cost"] = gpu_pipeline_time_cost
    _set_preprocess_specific_time_cost(context, timing_dict)

    log_file_path = os.path.join(
        config_context.root_path, config_context.clip_id, "ips_time_log.txt"
    )
    try:
        with open(log_file_path, 'a', encoding='utf-8') as file:
            file.write(
                f'[ips time log] reconic gpu pipeline time cost {gpu_pipeline_time_cost} s, clip{config_context.clip_id}\n'
            )
        print(f"[ips debug log]success write time to log: {log_file_path}")
    except Exception as e:
        print(f"[ips debug log]error when write time to log: {e}")
    config_context.ips_logger.info(f"[TIMING] timing_dict: {timing_dict}")
    config_context.ips_logger.info(f"[INFO] Finish preprocess_main with config:\n")


def _upload_datasets(config, config_context):
    dataset_folder = (
        'datasets_vision'
        if config_context.dataset_suffix == ''
        else f'datasets_vision_{config_context.dataset_suffix}'
    )
    large_dirs = (
        'depth',
        'images',
        'images_vision',
        'masks',
        'masks_obj',
        'segs',
        'segs_vision',
        'vision',
    )

    if config_context.upload_dataset:
        dataset_main_folder = (
            f'version_{config_context.ips_model_suffix}'
            if config_context.ips_model_suffix != ''
            else 'complete'
        )
        result_path_oss = f'sim_engine/{dataset_folder}/{config_context.clip_id}/{dataset_main_folder}'
        temp_output_path = compress_and_upload_fast(
            config.clip_path,
            result_path_oss,
            tar_name='dataset.tgz',
            included_dirs=large_dirs,
        )
        config_context.ips_logger.info(
            f"[INFO] {config_context.clip_id} upload dataset finished ({temp_output_path})."
        )
        os.system(f"rm -rf {temp_output_path}")

    if config_context.upload_pose_and_pcd:
        pose_and_pcd_folder = (
            f'pose_and_pcd_{config_context.ips_model_suffix}'
            if config_context.ips_model_suffix != ''
            else f'pose_and_pcd_{config_context.model_version}'
        )
        result_path_oss = f'sim_engine/{dataset_folder}/{config_context.clip_id}/{pose_and_pcd_folder}'
        temp_output_path = compress_and_upload_fast(
            config.clip_path,
            result_path_oss,
            tar_name='pose_and_pcd.tgz',
            excluded_dirs=large_dirs,
        )
        config_context.ips_logger.info(
            f"[INFO] {config_context.clip_id} upload pose_and_pcd finished ({temp_output_path})."
        )
        os.system(f"rm -rf {temp_output_path}")


def _train_model(config, config_context):
    # prepare training config
    trained_model_folder = (
        f'trained_model_{config_context.model_version}'
        if config_context.ips_model_suffix == ''
        else f'trained_model_{config_context.model_version}_{config_context.ips_model_suffix}'
    )
    result_path_oss1 = f'sim_engine/{config_context.ips_oss_folder}/{config_context.clip_id}/{trained_model_folder}_1347'
    config_context.ips_logger.info(
        f"[INFO] Prepare training config for {config_context.clip_id}."
    )

    local_config_path_default = './default_config_oss.yaml'
    remote_config_path = f'sim_engine/ips_configs/{config_context.oss_config_name}'
    if not download_file_from_oss2(
        local_config_path_default, object_key=remote_config_path
    ):
        raise UserWarning(
            f"[ERROR] download config {config_context.oss_config_name} from oss failed, use default config instead\n"
        )

    default_train_config = yaml.load(
        open(local_config_path_default), Loader=yaml.FullLoader
    )
    default_train_config['data']["data_root"] = os.path.dirname(config.clip_path)
    default_train_config['data']['scene_idx'] = config_context.clip_id
    default_train_config['data']['num_workers'] = config_context.num_workers
    default_train_config['data']['prefetch_factor'] = config_context.prefetch_factor

    current_time_train = (
        config_context.now.strftime("%Y%m%d_%H%M%S")
        + "_"
        + str(config_context.random_num)
    )
    output_path_root = (
        f"/code/driverstudio_output_{config_context.clip_id}_{current_time_train}"
    )
    local_config_path = (
        f"/code/omnire_joint_trainning/configs/default_{current_time_train}.yaml"
    )
    os.makedirs(os.path.dirname(local_config_path), exist_ok=True)
    with open(local_config_path, 'w') as file:
        yaml.dump(default_train_config, file, default_flow_style=False)

    global cfg
    config_context.ips_logger.info(
        f"[INFO] Start training {config_context.clip_id} with config:\n"
    )
    config_context.ips_logger.info(f"{default_train_config}")

    time2 = time.time()
    model_output_path = ips_train_driverstudio(local_config_path, output_path_root)
    time3 = time.time()
    config_context.ips_logger.info(
        f'reconic train time cost {time3-time2} s, clip{config_context.clip_id}'
    )
    log_files = [
        f
        for f in os.listdir(os.path.join(model_output_path, "logs"))
        if f.endswith('.txt')
    ]
    if not log_files:
        print(f"[ips debug log]no log.txt")
    first_log_file = log_files[0]
    file_path = os.path.join(model_output_path, "logs", first_log_file)
    with open(
        os.path.join(
            config_context.root_path, config_context.clip_id, "ips_time_log.txt"
        ),
        'r',
        encoding='utf-8',
    ) as source_file:
        ips_time_log_content = source_file.read()
    try:
        with open(file_path, 'a', encoding='utf-8') as file:
            file.write(ips_time_log_content)
            file.write(
                f'[ips debug log]reconic train time cost {time3-time2} s, clip{config_context.clip_id}\n'
            )
        print(f"[ips debug log]success write time to log: {first_log_file}")
    except Exception as e:
        print(f"[ips debug log]error when write time to log: {e}")

    os.makedirs(
        os.path.join(
            config_context.fuyao_log_path,
            config_context.model_version,
            config_context.clip_id,
        ),
        exist_ok=True,
    )
    shutil.copy(
        file_path,
        os.path.join(
            config_context.fuyao_log_path,
            config_context.model_version,
            config_context.clip_id,
            "log.txt",
        ),
    )

    model_upload_t0 = time.time()
    temp_output_path = upload_train_model_to_oss_fast(
        model_output_path,
        result_path_oss1,
        suffix=str(config_context.current_time),
        move=False,
    )
    model_upload_time_cost = time.time() - model_upload_t0
    config_context.ips_logger.info(
        f"[INFO] {config_context.clip_id} upload train model finished ({temp_output_path})."
    )

    start_timestamp, end_timestamp = get_timestamps(model_output_path)

    # 将时间戳保存到 config_context 中，供后续使用
    # config_context.start_timestamp = start_timestamp
    config_context.end_timestamp = end_timestamp

    config_context.ips_logger.info(f"[INFO] start_timestamp {start_timestamp}")
    config_context.ips_logger.info(f"[INFO] end_timestamp {end_timestamp}")
    config_context.ips_logger.info(f"[INFO] Finish training {config_context.clip_id}")

    return (
        result_path_oss1,
        model_output_path,
        temp_output_path,
        start_timestamp,
        end_timestamp,
        model_upload_time_cost,
    )


def _send_initial_cloudsim_message(
    context, start_timestamp, end_timestamp, result_path_oss1, config_context, config
):
    adapted_start_timestamp = get_subrun_adapted_start_timestamp(start_timestamp)
    jira_relative_seconds = context.get("cloudsim_jira_relative_seconds")
    issue_description = context.get("cloudsim_issue_description")
    adapted_trigger_timestamp = resolve_trigger_timestamp(
        config.clip_path, adapted_start_timestamp, end_timestamp, jira_relative_seconds, issue_description, config.trigger_time_offset_map
    )
    config_context.start_timestamp = adapted_start_timestamp
    config_context.trigger_timestamp = adapted_trigger_timestamp
    adapted_end_timestamp = end_timestamp

    data_record = context["data_record"]
    initial_extra_info = {
        'bucket': 'cloudsim-ci-sh',
        'trian_model_address1': result_path_oss1,
        'note': 'helloworld',
        'status': 'model_trained_success',
        "adapted_start_timestamp": int(adapted_start_timestamp),
        "adapted_trigger_timestamp": int(adapted_trigger_timestamp),
        "adapted_end_timestamp": int(adapted_end_timestamp),
        "model_version": config_context.model_version,
        "es_index": config_context.clip_type,
        "is_fm": config_context.is_fm_bool,
        "is_dynamic": config_context.is_dynamic,
        "is_reconic": config_context.is_reconic,
        "input_id_type": "clip_id",
        **({"job_id": context["cloudsim_job_id"]} if context.get("cloudsim_job_id") else {}),
        **({"ucp_job_id": context["ucp_job_id"]} if context.get("ucp_job_id") else {}),
    }

    data_record.notify_cloudsim_3dgs(is_user_label=True, extra_info=initial_extra_info)

    data_record.save_tag(tag=str(config_context.model_version))


def _run_post_process_and_update_cloudsim(
    context, model_output_path, config, result_path_oss1, config_context
):
    evaluation_oss_url = None
    if config_context.enable_post_process:
        config_context.ips_logger.info(
            "Starting post-processing for 3DGS model evaluation"
        )

        # Call post_process function directly with new signature
        post_process_kwargs = {
            'logger': config_context.ips_logger,
            'clip_id': config_context.clip_id,
            'model_source': model_output_path,
            'dataset_root': config.clip_path,
            'model_version': config_context.model_version,
            'enable_fid': config_context.enable_fid,
            'render_complete': config_context.render_complete,
            'mode': 'normal',
        }
        evaluation_t0 = time.time()
        evaluation_oss_url, mean_metrics = post_process(**post_process_kwargs)
        context["evaluation_time_cost"] = time.time() - evaluation_t0
        if mean_metrics is None:
            mean_metrics = {}
        config_context.ips_logger.info("Post-processing completed")

        check_status = get_render_check_status(config.clip_path, mean_metrics)

        # 评测完成后发送更新消息
        if evaluation_oss_url is not None:
            runtime_values = _get_runtime_values_for_notify(
                context, config.clip_path, config_context.ips_logger
            )
            # 构建评测更新消息，包含初始消息的所有字段加上评测结果
            evaluation_update_info = {
                'bucket': 'cloudsim-ci-sh',
                'trian_model_address1': result_path_oss1,
                'note': 'helloworld',
                'status': 'evaluation_success',
                "adapted_start_timestamp": int(config_context.start_timestamp),
                "adapted_end_timestamp": int(config_context.end_timestamp),
                "adapted_trigger_timestamp": int(config_context.trigger_timestamp),
                "model_version": config_context.model_version,
                "es_index": config_context.clip_type,
                "is_fm": config_context.is_fm_bool,
                "is_dynamic": config_context.is_dynamic,
                "is_reconic": config_context.is_reconic,
                'evaluation_oss_address': evaluation_oss_url,
                "reconic_preprocess_time_cost": (
                    (
                        (runtime_values["cpu_pipeline_time_cost"] or 0)
                        + (context.get("gpu_pipeline_time_cost") or 0)
                    )
                    / 60.0
                ),
                "cpu_preprocess_time_cost": (runtime_values["cpu_pipeline_time_cost"] or 0) / 60.0,
                "gpu_preprocess_time_cost": (context.get("gpu_pipeline_time_cost") or 0) / 60.0,
                "pre_processor_time_cost": runtime_values["pre_processor_time_cost"] / 60.0,
                "reconic_train_time_cost": (
                    (context.get("reconic_train_time_cost") or 0) / 60.0
                ),
                "dataset_upload_time_cost": (context.get("dataset_upload_time_cost") or 0) / 60.0,
                "model_upload_time_cost": (context.get("model_upload_time_cost") or 0) / 60.0,
                "evaluation_time_cost": (context.get("evaluation_time_cost") or 0) / 60.0,
                "feedforward_postprocess_time_cost": (context.get("feedforward_postprocess_time_cost") or 0) / 60.0,
                "preprocess_specific_time_cost": context.get("preprocess_specific_time_cost", {}),
                "reconic_pipeline_time_cost": runtime_values["pipeline_time_cost"] / 60.0,
                "reconic_effective_pipeline_time_cost": runtime_values["effective_pipeline_time_cost"] / 60.0,
                "scheduling_wait_time": runtime_values["scheduling_wait_time"] / 60.0,
                "data_upload_time_cost": runtime_values["data_upload_time_cost"] / 60.0,
                "case_time": runtime_values["case_time"],
                "case_distance": runtime_values["case_distance"],
                "check_status": check_status,
                "mode": "normal",
                "input_id_type": "clip_id",
                **({"job_id": context["cloudsim_job_id"]} if context.get("cloudsim_job_id") else {}),
                **({"ucp_job_id": context["ucp_job_id"]} if context.get("ucp_job_id") else {}),
                "gpu_retry_count": context.get("gpu_retry_count", 0),
            }

            # 发送评测更新消息到CloudSim
            context["data_record"].notify_cloudsim_3dgs(
                is_user_label=True, extra_info=evaluation_update_info
            )
            config_context.ips_logger.info(
                f"Sent evaluation update to CloudSim: {evaluation_oss_url}"
            )
            _upload_extra_info_to_oss(evaluation_update_info, result_path_oss1, config.clip_path, config_context.ips_logger)
    else:
        config_context.ips_logger.info(
            "Post-processing skipped (enable_post_process=False)"
        )


def _run_feedforward_postprocess(config, config_context, model_output_path, output_path_root):
    evaluation_oss_url = None
    if config_context.enable_post_process:
        config_context.ips_logger.info("Starting post-processing for 3DGS model evaluation")
        from argparse import Namespace

        local_config_path = _ensure_feedforward_local_config(config, config_context)
        args = Namespace(
            config_file=local_config_path,
            resume=False,
            load_from=None,
            output_root=output_path_root,
            render_video_postfix=None,
            enable_wandb=False,
            entity="ziyc",
            project="drivestudio",
            run_name="omnire",
            enable_viewer=False,
            viewer_port=8080,
            opts=[],
        )
        post_process_kwargs = {
            'logger': config_context.ips_logger,
            'clip_id': config_context.clip_id,
            'model_source': model_output_path,
            'dataset_root': config.clip_path,
            'class_args': args,
            'model_version': config_context.model_version + "_feedforward",
            'enable_fid': config_context.enable_fid,
            'render_complete': config_context.render_complete,
            'mode': 'feedforward',
        }
        import torch.multiprocessing as mp
        mp.set_start_method('fork', force=True)
        torch.set_grad_enabled(True)

        evaluation_oss_url, _ = post_process(**post_process_kwargs)
        config_context.ips_logger.info("Post-processing completed")
    else:
        config_context.ips_logger.info("Post-processing skipped (enable_post_process=False)")
    return evaluation_oss_url


def _ensure_feedforward_local_config(config, config_context):
    local_config_path = (
        f"/code/omnire_joint_trainning/configs/default_{config_context.current_time}.yaml"
    )
    if os.path.exists(local_config_path):
        return local_config_path

    local_config_path_default = './default_config_oss.yaml'
    remote_config_path = f'sim_engine/ips_configs/{config_context.oss_config_name}'
    if not download_file_from_oss2(local_config_path_default, object_key=remote_config_path):
        raise UserWarning(
            f"[ERROR] download config {config_context.oss_config_name} from oss failed.\n"
        )

    default_train_config = yaml.load(open(local_config_path_default), Loader=yaml.FullLoader)
    default_train_config['data']["data_root"] = os.path.dirname(config.clip_path)
    default_train_config['data']['scene_idx'] = config_context.clip_id
    default_train_config['data']['num_workers'] = config_context.num_workers
    default_train_config['data']['prefetch_factor'] = config_context.prefetch_factor

    os.makedirs(os.path.dirname(local_config_path), exist_ok=True)
    with open(local_config_path, 'w') as file:
        yaml.dump(default_train_config, file, default_flow_style=False)
    config_context.ips_logger.info(
        f"[INFO] Created feedforward config: {local_config_path}"
    )
    return local_config_path


def _notify_cloudsim_feedforward(
    context,
    config_context,
    result_path_oss1,
    start_timestamp,
    end_timestamp,
    dataset_root,
    evaluation_oss_url,
    config=None,
):
    adapted_start_timestamp = get_subrun_adapted_start_timestamp(start_timestamp)
    adapted_end_timestamp = end_timestamp
    jira_relative_seconds = context.get("cloudsim_jira_relative_seconds")
    issue_description = context.get("cloudsim_issue_description")
    adapted_trigger_timestamp = resolve_trigger_timestamp(
        dataset_root, adapted_start_timestamp, end_timestamp, jira_relative_seconds, issue_description, config.trigger_time_offset_map
    )
    runtime_values = _get_runtime_values_for_notify(
        context, os.path.join(config_context.root_path, config_context.clip_id), config_context.ips_logger
    )
    extra_info = {
        'bucket': 'cloudsim-ci-sh',
        'trian_model_address1': result_path_oss1,
        'note': 'helloworld',
        'status': 'test_information',
        "adapted_start_timestamp": int(adapted_start_timestamp),
        "adapted_trigger_timestamp": int(adapted_trigger_timestamp),
        "adapted_end_timestamp": int(adapted_end_timestamp),
        "model_version": config_context.model_version + "_feedforward",
        "es_index": config_context.clip_type,
        "is_fm": config_context.is_fm_bool,
        "is_dynamic": config_context.is_dynamic,
        "is_reconic": config_context.is_reconic,
        "reconic_preprocess_time_cost": (
            (
                (runtime_values["cpu_pipeline_time_cost"] or 0)
                + (context.get("gpu_pipeline_time_cost") or 0)
            )
            / 60.0
        ),
        "cpu_preprocess_time_cost": (runtime_values["cpu_pipeline_time_cost"] or 0) / 60.0,
        "gpu_preprocess_time_cost": (context.get("gpu_pipeline_time_cost") or 0) / 60.0,
        "pre_processor_time_cost": runtime_values["pre_processor_time_cost"] / 60.0,
        "feedforward_postprocess_time_cost": (context.get("feedforward_postprocess_time_cost") or 0) / 60.0,
        "reconic_train_time_cost": 0,
        "preprocess_specific_time_cost": context.get("preprocess_specific_time_cost", {}),
        "reconic_pipeline_time_cost": runtime_values["pipeline_time_cost"] / 60.0,
        "reconic_effective_pipeline_time_cost": runtime_values["effective_pipeline_time_cost"] / 60.0,
        "scheduling_wait_time": runtime_values["scheduling_wait_time"] / 60.0,
        "data_upload_time_cost": runtime_values["data_upload_time_cost"] / 60.0,
        "case_time": runtime_values["case_time"],
        "case_distance": runtime_values["case_distance"],
        "mode": "feedforward",
        "input_id_type": "clip_id",
        **({"job_id": context["cloudsim_job_id"]} if context.get("cloudsim_job_id") else {}),
        **({"ucp_job_id": context["ucp_job_id"]} if context.get("ucp_job_id") else {}),
        "gpu_retry_count": context.get("gpu_retry_count", 0),
    }
    if evaluation_oss_url is not None:
        extra_info['evaluation_oss_address'] = evaluation_oss_url
        config_context.ips_logger.info(f"Added evaluation OSS URL to notification: {evaluation_oss_url}")

    context["data_record"].notify_cloudsim_3dgs(is_user_label=True, extra_info=extra_info)
    context["data_record"].save_tag(tag=str(config_context.model_version))
    _upload_extra_info_to_oss(extra_info, result_path_oss1, os.path.join(config_context.root_path, config_context.clip_id), config_context.ips_logger)


def _cleanup_stale_runtime_tmp_dirs():
    """清理RUNTIME_TMP_DIR_BASE下对应进程已不存在的临时目录"""
    try:
        if not os.path.isdir(RUNTIME_TMP_DIR_BASE):
            return

        for clip_id in os.listdir(RUNTIME_TMP_DIR_BASE):
            runtime_tmp_dir = os.path.join(RUNTIME_TMP_DIR_BASE, clip_id)
            print(f"[INFO] Checking runtime temporary directory: {runtime_tmp_dir}")
            if not os.path.isdir(runtime_tmp_dir):
                continue

            print(f"[INFO] Runtime temporary directory exists: {runtime_tmp_dir}")
            pid_file_path = os.path.join(runtime_tmp_dir, "pid")
            if not os.path.isfile(pid_file_path):
                shutil.rmtree(runtime_tmp_dir)
                print(f"[INFO] Removed stale temporary directory (missing pid file): {runtime_tmp_dir}")
                continue

            try:
                with open(pid_file_path, "r", encoding="utf-8") as pid_file:
                    pid = int(pid_file.read().strip())
            except (ValueError, OSError):
                shutil.rmtree(runtime_tmp_dir)
                print(f"[INFO] Removed stale temporary directory (invalid pid file): {runtime_tmp_dir}")
                continue

            if pid <= 0:
                shutil.rmtree(runtime_tmp_dir)
                print(f"[INFO] Removed stale temporary directory for dead pid {pid}: {runtime_tmp_dir}")
                continue

            # 优先使用 psutil 判断进程是否存活，不调用 kill 相关接口
            is_running = psutil.pid_exists(pid)

            if not is_running:
                shutil.rmtree(runtime_tmp_dir)
                print(f"[INFO] Removed stale temporary directory for dead pid {pid}: {runtime_tmp_dir}")
            else:
                print(f"[INFO] Process {pid} is running, keep temporary directory: {runtime_tmp_dir}")
    except Exception as e:
        print(f"[ERROR] Failed to cleanup stale temporary directories: {e}")
        raise


def _init_tmp_dir(context: dict):
    """创建临时目录"""
    try:
        clip_id = context["id"]
        root_path = context["root_path"]
        runtime_tmp_dir = os.path.join(RUNTIME_TMP_DIR_BASE, clip_id)
        os.makedirs(runtime_tmp_dir, exist_ok=True)
        pid_file_path = os.path.join(runtime_tmp_dir, "pid")
        pid_current = os.getpid()   # 获取当前进程ID
        with open(pid_file_path, "w", encoding="utf-8") as pid_file:
            pid_file.write(f"{pid_current}\n")
        print(f"[INFO] Created temporary directory: {runtime_tmp_dir}")
        print(f"[INFO] Wrote process pid to: {pid_file_path}, pid: {pid_current}")
        
        start_time = time.time()
        source_dir = os.path.join(root_path, clip_id)
        if not os.path.exists(source_dir):
            print(f"[WARNING] Source directory does not exist: {source_dir}")
            return

        for item in os.listdir(source_dir):
            source_item_path = os.path.join(source_dir, item)
            destination_item_path = os.path.join(runtime_tmp_dir, item)
            if os.path.isdir(source_item_path):
                shutil.copytree(source_item_path, destination_item_path, dirs_exist_ok=True)
            else:
                shutil.copy2(source_item_path, destination_item_path)
        end_time = time.time()
        print(f"[INFO] Copied all items from {source_dir} to {runtime_tmp_dir} in {end_time - start_time:.2f} seconds")    
        
    except Exception as e:
        print(f"[ERROR] Failed to create temporary directory: {e}")
        raise

def _cleanup_tmp_dir(context: dict):
    try:
        clip_id = context["id"]
        runtime_tmp_dir = os.path.join(RUNTIME_TMP_DIR_BASE, clip_id)
        
        if os.path.exists(runtime_tmp_dir):
            shutil.rmtree(runtime_tmp_dir)
            print(f"[INFO] Cleaned up temporary directory: {runtime_tmp_dir}")
    except Exception as e:
        print(f"[ERROR] Failed to clean up temporary directory: {e}")



def init_ips():
    try:
        ips_code_dir = os.environ.get('IPS_CODE_DIR', '/code')  # 修正：使用=而不是:

        if not ips_code_dir:
            print("IPS_CODE_DIR not set, cannot find user code.")
            raise SystemExit(1)  # 直接退出程序

        required_dirs = [
            "xpeng_data_process",
            "omnire_joint_trainning",
            "models/g3r",
            "sim_interface",
            "models/street_gaussians",
        ]

        for dir_name in required_dirs:
            dir_path = f"{ips_code_dir}/{dir_name}"
            if not os.path.exists(dir_path):
                print(f"Cannot find user {dir_name} code.")
                raise SystemExit(1)  # 直接退出程序

    except Exception as error:
        print(f"init ips error: {error}")
        raise SystemExit(1)  # 确保任何异常都导致程序退出


def ips_train():
    import train_xpeng
    import lib.config

    importlib.reload(train_xpeng)
    importlib.reload(lib.config)
    from lib.utils.general_utils import safe_state

    safe_state(lib.config.cfg.train.quiet)
    torch.autograd.set_detect_anomaly(lib.config.cfg.train.detect_anomaly)
    train_xpeng.training_xpeng()
    return lib.config.cfg


def ips_train_driverstudio(config_path, output_path):
    import torch.multiprocessing as mp

    mp.set_start_method('fork', force=True)

    torch.set_grad_enabled(True)

    import reconic.cli.train_cli
    from argparse import Namespace

    args = Namespace(
        config_file=config_path,
        resume=False,
        load_from=None,
        output_root=output_path,
        render_video_postfix=None,
        enable_wandb=False,
        entity="ziyc",
        project="drivestudio",
        run_name="omnire",
        enable_viewer=False,
        viewer_port=8080,
        opts=[],
    )
    print("config_path:", config_path, "output_path:", output_path)
    reconic.cli.train_cli.train(args)
    model_path = os.path.join(args.output_root, args.project, args.run_name)
    try:
        shutil.rmtree(os.path.join(model_path, "novel_view_data"))
    except FileNotFoundError:
        pass

    sim_config_path = os.path.join(model_path, "configs", "config_sim.yaml")
    if os.path.exists(sim_config_path):
        print("[ips debug log]: copy config for cloudsim!")
        shutil.copy(
            sim_config_path,
            os.path.join(
                output_path, os.path.join(model_path, "configs", "config_reconic.yaml")
            ),
        )
    else:
        print(
            "[ips debug log]: cannot copy config for cloudsim! path ",
            sim_config_path,
            "not exist!",
        )
    return model_path


def ips_evaluation(result_path_oss):
    from sim_bridge.novel_eval import NovelEvaluator

    novel_eval = NovelEvaluator()
    novel_eval.generate_novel_views()
    json_path = novel_eval.evaluate(cfg.source_path)
    upload(
        json_path,
        'evaluation_results.json',
        bucket_name='cloudsim-ci-sh',
        oss_directory=result_path_oss,
    )


def main():
    from xdata.dataset_v2.dataset_loader import DatasetLoader
    from xdata.dataset_v2.data_record import SENSOR_CLIP_RECORD_TYPE

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    data_loader_config = {
        "data_dir": "/dataset/downloader_v2/repository",
        "data_cache": "/dataset/xfoundation",
        "allow_use_cache_only": False,
        "log_level": "info",
        "endpoint_env": "public",
    }
    data_loader = DatasetLoader(data_loader_config)

    xdataset_config = {
        "dataset_id": "selected_clips_m1",
        "limit": 10,
        "record_type": SENSOR_CLIP_RECORD_TYPE,
    }

    data_loader = DatasetLoader(data_loader_config)
    dataset = data_loader.load_dataset_v2(
        **xdataset_config,
    )

    target_id = "c-fff9095c-176e-3bf0-8479-ddd0c8cf1819"  # 指定你要查找的 ID 值
    record = None  # 初始化 record 为 None

    # 遍历 dataset 中的每个记录
    for clip_record in dataset:  # 直接迭代 dataset
        print(clip_record.get_id())
        if clip_record.get_id() == target_id:  # 检查 ID 是否匹配
            record = clip_record  # 将匹配的记录赋值给 record
            print(f"[DEBUG] Found record with ID {target_id}:")
            print(record)  # 打印匹配的记录内容
            break  # 找到后退出循环

    print("Dataset:", dataset)
    print("record:", record)
    context = {
        "root_path": "/workspace/yangxh7@xiaopeng.com/datasets/xpeng/m1_test/",
        "id": "c-fff9095c-176e-3bf0-8479-ddd0c8cf1819",
        "data_record": record,
        "dataset": dataset,
        "data_loader": data_loader,
        "logger": logger,
    }

    # pre_processor(context)
    gpu_processor(context)
    post_processor(context)


if __name__ == "__main__":
    main()
