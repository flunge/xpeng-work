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
import gc
import multiprocessing as mp
import subprocess

from download_file_from_oss2 import download_file_from_oss2
from upload2oss import (
    upload_train_model_to_oss,
    upload,
    compress_and_upload,
    compress_and_upload_fast,
    upload_train_model_to_oss_fast,
    upload_local_dir_to_oss,
)
from merge_slice_hil_dds_lib import run_merge_and_slice_abs
from ips_utils import (
    get_timestamps,
    get_subrun_adapted_start_timestamp,
    resolve_trigger_timestamp,
)
from post_process import post_process
from quality_check_utils import get_render_check_status
from ucp_xpeng_vision import _set_preprocess_specific_time_cost, _persist_pipeline_runtime_values, _load_pipeline_runtime_values, _get_and_increment_retry_count, _upload_extra_info_to_oss
from pipeline_error_codes import classify_error

_reconic_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "omnire_joint_trainning", "src")
if _reconic_path not in sys.path:
    sys.path.insert(0, _reconic_path)
from reconic.multi_vehicle_utils.cloudsim_request import cloudsim_request

def _cleanup_subprocess_and_cuda(logger=None):
    for proc in mp.active_children():
        try:
            if proc.is_alive():
                proc.terminate()
            proc.join(timeout=5)
        except Exception as exc:
            if logger is not None:
                logger.warning(f"[WARN] Failed to cleanup child process {proc.pid}: {exc}")

    try:
        import torch.distributed as dist

        if dist.is_available() and dist.is_initialized():
            dist.destroy_process_group()
    except Exception as exc:
        if logger is not None:
            logger.warning(f"[WARN] Failed to destroy process group: {exc}")

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()

def _notify_cloudsim_on_error(context: dict, status: str, error_message: str):
    if os.environ.get('REQUEST_JOB_TYPE') != 'cloudsim':
        return

    error_info = {
        'status': status,
        'error_message': error_message,
        "input_id_type": "subrun_id",
        **({"cloudsim_job_id": context["cloudsim_job_id"]} if "cloudsim_job_id" in context else {}),
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
    subrun_id = context["id"]
    subrun_id_task_info = task_response.get("data", {}).get(subrun_id)
    if subrun_id_task_info is None:
        raise RuntimeError(
            f"subrun_id {subrun_id} not found in cloudsim task response data, "
            f"available keys: {list(task_response.get('data', {}).keys())}"
        )
    if isinstance(subrun_id_task_info, list):
        if not subrun_id_task_info:
            raise RuntimeError(
                f"subrun_id {subrun_id} task info list is empty in cloudsim task response data"
            )
        subrun_id_task_info = subrun_id_task_info[0]
    
    print(f"[INFO] CloudSim task info: {task_response}")
    # 将 cloudsim 返回的任务参数中的关键字段写入 context["extra_info"]
    EXTRA_INFO_FIELDS = [
        "clip_ids", "scenario_slice_num", "dds_data_source",
        "end_timestamp", "scenario_id", "start_timestamp"
    ]
    if "extra_info" not in context:
        context["extra_info"] = {}
    for field in EXTRA_INFO_FIELDS:
        value = subrun_id_task_info.get(field)
        if value is not None:
            context["extra_info"][field] = value
    context["cloudsim_job_id"] = subrun_id_task_info.get("job_id", "")


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
    # ================================= ips args ======================================
    context["pipeline_start_time"] = time.time()
    subrun_id = context["id"]
    print(
        f"[SIMDIAG] [pre_processor_start] clip={subrun_id}",
        flush=True
    )
    upload_images_origin = kwargs.get('upload_images_origin', False)
    preprocess_config_name = kwargs.get('preprocess_config_name', 'run_preprocess_subrun.yaml')
    start_time = kwargs.get('start_time', None)
    end_time = kwargs.get('end_time', None)

    if start_time is None or end_time is None:
        start_time = context["extra_info"].get("start_timestamp")
        end_time = context["extra_info"].get("end_timestamp")

    target_clip_ids = context["extra_info"].get("clip_ids", None)
    if isinstance(target_clip_ids, str):
        # 上游可能传单个 clip_id 字符串；统一成 list，避免后续按字符拆分
        target_clip_ids = [target_clip_ids]
    elif target_clip_ids is not None and not isinstance(target_clip_ids, (list, tuple, set)):
        # 兜底：未知类型时不做过滤，保持向后兼容
        target_clip_ids = None

    print("=====start time===== ", start_time)
    print("=====end time===== ", end_time)
    print(f"=====delta time===== {(int(end_time) - int(start_time)) / 1_000_000} s")
    print(f"=====target clip_ids===== {target_clip_ids}")
    # =================================================================================
    
    ips_logger = context["logger"] 
    subrun_id = context["id"]
    root_path: str = context["root_path"]

    ips_logger.info(f"[INFO] Start preprocessor of {subrun_id} with root {root_path}.")
    # 将所需路径添加到 sys.path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    preprocess_path = os.path.join(current_dir, 'xpeng_data_process')
    sys.path.append(preprocess_path)
    
    ######################################### START #########################################
    from settings.config import make_default_settings, make_cfg, make_case_specific_settings
    from generate_dataset_data import dump_source_data
    import pipelines

    # config = make_default_settings()
    # prepare training config
    local_config_path = '/code/models/street_gaussians/configs/run_preprocess_subrun.yaml'
    remote_config_path = f'sim_engine/ips_configs/{preprocess_config_name}'
    os.makedirs(os.path.dirname(local_config_path), exist_ok=True)
    if not download_file_from_oss2(local_config_path, object_key=remote_config_path):
        raise UserWarning(f"[ERROR] download config run_preprocess_subrun.yaml from oss failed!\n")

    default_cfg = make_default_settings()
    cfg_list, current_cfg = make_cfg(local_config_path, default_cfg)
    config = cfg_list[0]

    config.root = root_path
    config.dataset_name = "ips_dataset"
    config.subrun_list = [subrun_id] 
    config.record_type = "SUBRUN_RECORD_TYPE"
    config.use_h265_png = True
    config = make_case_specific_settings(config)
    config['clip_path'] = os.path.join(root_path, subrun_id)

    dds_data_source = context["extra_info"].get("dds_data_source")
    if not dds_data_source:
        raise RuntimeError("dds_data_source not found in extra_info, cannot download DDS data")
    ips_logger.info(f"[INFO] Found dds_data_source in extra_info, processing DDS data...")
    processed_dds = process_dds_data(
        dds_data_source, config['clip_path'], start_time, end_time, ips_logger
    )

    ### dump source data
    clip_records = context["data_record"]
    ips_logger.info(f"[INFO] clip_records {clip_records}")
    loader = context["data_loader"]
    ips_logger.info(f"[INFO] loader {loader}")
    dataset = context["dataset"]
    dump_source_data(config, clip_records, loader, dataset, start_time=start_time, end_time=end_time, target_clip_ids=target_clip_ids)
    ips_logger.info(f"[INFO] {subrun_id} dump finished.") 

    ### preprocess cpu
    now = datetime.now()
    random_num = random.randint(1000000, 9999999)
    current_time = now.strftime("%Y%m%d_%H%M%S") + "_" + str(random_num)

    info_dict = {}
    time_cpu0 = time.time()
    pipelines.pipeline_vision_cpu(config, info_dict)
    time_cpu1 = time.time()
    cpu_preprocess_time_cost = time_cpu1 - time_cpu0
    context["cpu_preprocess_time_cost"] = cpu_preprocess_time_cost
    context["case_time"] = info_dict["case_time"]
    context["case_distance"] = info_dict["case_distance"]
    ips_logger.info(f"[INFO] {subrun_id} preprocessing finished.") 
    # START Compress origin images and Upload to OSS
    data_upload_t0 = time.time()
    if bool(upload_images_origin) and upload_images_origin != '0':
        result_path_oss = f'sim_engine/datasets/{subrun_id}/images_origin'
        temp_output_path = compress_and_upload_fast(
            os.path.join(config['clip_path'], 'images_origin'),
            result_path_oss,
            suffix=str(current_time),
        )
        ips_logger.info(
            f"[INFO] {subrun_id} upload images_origin ({temp_output_path}) finished."
        )
        os.system(f"rm -rf {temp_output_path}")
    data_upload_time_cost = time.time() - data_upload_t0

    print(
        f"[SIMDIAG] [pre_processor_done] clip={subrun_id}",
        flush=True
    )
    runtime_payload = {
        "pipeline_start_time": context.get("pipeline_start_time"),
        "cpu_preprocess_time_cost": context.get("cpu_preprocess_time_cost"),
        "case_time": context.get("case_time"),
        "case_distance": context.get("case_distance"),
        "data_upload_time_cost": data_upload_time_cost,
        "pre_processor_end_time": time.time(),
    }
    if processed_dds:
        runtime_payload["processed_dds"] = processed_dds
    _persist_pipeline_runtime_values(config["clip_path"], runtime_payload, ips_logger)


def _gpu_processor_impl(context: dict, **kwargs):
    # ================================= ips args ======================================
    clip_id = context["id"]
    context["gpu_processor_start_time"] = time.time()
    context["gpu_retry_count"] = _get_and_increment_retry_count(
        context["root_path"], clip_id
    )
    print(
        f"[SIMDIAG] [gpu_processor_start] clip={clip_id} retry={context['gpu_retry_count']}",
        flush=True
    )
    ips_oss_folder = kwargs.get('ips_oss_folder', 'ips_output_reconic')
    ips_model_suffix = kwargs.get('ips_model_suffix', '')
    oss_config_name = kwargs.get('oss_config_name', 'sim3dgs_v410.yaml')
    preprocess_config_name = kwargs.get('preprocess_config_name', 'sim3dgs_v410_preprocess.yaml')
    model_version_input = kwargs.get('model_version','sim3dgs_v410')
    model_version = model_version_input
    start_time = kwargs.get('start_time', None)
    end_time = kwargs.get('end_time', None)

    model_id = None
    if start_time is None or end_time is None:
        model_id = str(context["extra_info"].get("scenario_slice_num"))
        model_version += model_id

    clip_type = kwargs.get('clip_type','h265-clip-portal-latest')
    dataset_suffix = kwargs.get('dataset_suffix', '')
    ppu_run = kwargs.get('ppu_run', True)
    is_dynamic = kwargs.get('is_dynamic', True)
    is_reconic = kwargs.get('is_reconic', True)
    enable_post_process = kwargs.get('enable_post_process', True)  # Control whether to run post_process
    render_complete = kwargs.get('render_complete', False)  # Control image sampling
    enable_fid = kwargs.get('enable_fid', False)

    is_ppu_run = str(ppu_run).lower() == "true"

    is_fm = kwargs.get('is_fm', False)
    is_fm_bool = str(is_fm).lower() == "true"

    upload_dataset = kwargs.get('upload_dataset', False)
    upload_pose_and_pcd = kwargs.get('upload_pose_and_pcd', True)
    upload_processed_dds = kwargs.get('upload_processed_dds', True)

    num_workers = int(kwargs.get('num_workers', 4))
    prefetch_factor = int(kwargs.get('prefetch_factor', 4))
    fuyao_log_path = kwargs.get('fuyao_log_path', '/workspace/group_share/adc-sim/users/yangxh7/logs')
    # =================================================================================
    now = datetime.now()
    random_num = random.randint(1000000, 9999999)
    current_time = now.strftime("%Y%m%d_%H%M%S") + "_" + str(random_num)
    
    is_upload_success = False
    ips_logger = context["logger"] 
    clip_id = context["id"]
    root_path: str = context["root_path"]
    ips_logger.info(f"[INFO] Start gpu_processor of {clip_id} with root {root_path} with {kwargs}.")

    # 将所需路径添加到 sys.path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    preprocess_path = os.path.join(current_dir, 'xpeng_data_process')
    sys.path.append(preprocess_path)

    os.environ['TORCH_HOME'] = "/cpfs/batch_inference_models/3dgs_models/2025-08-08/torch_cache"
    os.environ['HF_HOME'] = '/cpfs/batch_inference_models/3dgs_models/2025-08-08/pretrain_model' 
    os.environ['LPIPS_MODEL_PATH']  = '/cpfs/batch_inference_models/lilps_alex-20250915210318000-lvy10/alex.pth'

    ######################################### START GPU Preprocess #########################################
    from settings.config import make_default_settings, make_cfg, make_case_specific_settings
    import pipelines

    # prepare training config
    local_config_path = f'/code/models/street_gaussians/configs/run_preprocess_{current_time}.yaml'
    remote_config_path = f'sim_engine/ips_configs/{preprocess_config_name}'
    os.makedirs(os.path.dirname(local_config_path), exist_ok=True)
    if not download_file_from_oss2(local_config_path, object_key=remote_config_path):
        raise UserWarning(f"[ERROR] download config run_preprocess.yaml from oss failed!\n")

    default_cfg = make_default_settings()
    cfg_list, current_cfg = make_cfg(local_config_path, default_cfg)
    config = cfg_list[0]
    config.root = root_path
    config.clip_id = clip_id
    config.use_h265_png = True
    config.dataset_name = "ips_dataset"
    # config.steps_controller.camopt_processor = True
    config.pretrained_model_path = "/root/recon_pretrained_models/"
    config = make_case_specific_settings(config)
    config.ppu_deploy = is_ppu_run
    # preprocess GPU
    ips_logger.info(f"[INFO] Start preprocess_main with config:\n")
    ips_logger.info(f"{config}")
    timing_dict = {}
    time_gpu0 = time.time()
    pipelines.pipeline_vision_gpu(config, timing_dict)
    time_gpu1 = time.time()
    context["gpu_preprocess_time_cost"] = time_gpu1 - time_gpu0
    _set_preprocess_specific_time_cost(context, timing_dict)

    log_file_path = os.path.join(root_path, clip_id, "ips_time_log.txt")
    try:
        with open(log_file_path, 'a', encoding='utf-8') as file:
            file.write(f'[ips time log] reconic gpu pipeline time cost {time_gpu1-time_gpu0} s, clip{clip_id}\n')  
        print(f"[ips debug log]success write time to log: {log_file_path}")
    except Exception as e:
        print(f"[ips debug log]error when write time to log: {e}")
    ips_logger.info(f"[TIMING] timing_dict: {timing_dict}")
    ips_logger.info(f"[INFO] Finish preprocess_main with config:\n")

    dataset_folder = 'datasets_vision' if dataset_suffix == '' else f'datasets_vision_{dataset_suffix}'

    # START Compress dataset and Upload to OSS
    dataset_upload_t0 = time.time()
    large_dirs = ('depth', 'images', 'images_vision', 'masks', 'masks_obj', 'segs', 'segs_vision', 'vision')
    if bool(upload_dataset) == True and upload_dataset != '0':
        # upload complete dataset
        dataset_main_folder = f'version_{ips_model_suffix}' if ips_model_suffix != '' else 'complete'
        result_path_oss = f'sim_engine/{dataset_folder}/{clip_id}/{dataset_main_folder}'
        temp_output_path = compress_and_upload_fast(
            config.clip_path, result_path_oss, tar_name='dataset.tgz',
            included_dirs=large_dirs
        )
        ips_logger.info(f"[INFO] {clip_id} upload dataset finished ({temp_output_path}).")
        os.system(f"rm -rf {temp_output_path}")

    if bool(upload_pose_and_pcd) == True and upload_pose_and_pcd != '0':
        # upload pose and pcd
        pose_and_pcd_folder = f'pose_and_pcd_{ips_model_suffix}' if ips_model_suffix != '' else f'pose_and_pcd_{model_version}'
        result_path_oss = f'sim_engine/{dataset_folder}/{clip_id}/{pose_and_pcd_folder}'
        temp_output_path = compress_and_upload_fast(
            config.clip_path, result_path_oss, tar_name='pose_and_pcd.tgz', 
            excluded_dirs=large_dirs
        )
        ips_logger.info(f"[INFO] {clip_id} upload pose_and_pcd finished ({temp_output_path}).")
        os.system(f"rm -rf {temp_output_path}")
    context["dataset_upload_time_cost"] = time.time() - dataset_upload_t0

    ######################################### START Train #########################################
    # prepare training config
    trained_model_folder = f'trained_model_{model_version}' if ips_model_suffix == '' else f'trained_model_{model_version}_{ips_model_suffix}'
    result_path_oss1 = f'sim_engine/{ips_oss_folder}/{clip_id}/{trained_model_folder}_1347'
    ips_logger.info(f"[INFO] Prepare training config for 1234567.")

    local_config_path = './default_config_oss.yaml'
    remote_config_path = f'sim_engine/ips_configs/{oss_config_name}'
    if not download_file_from_oss2(local_config_path, object_key=remote_config_path):
        raise UserWarning(f"[ERROR] download config {oss_config_name} from oss failed, use default config instead\n")

    default_train_config = yaml.load(open(local_config_path), Loader=yaml.FullLoader)
    default_train_config['data']["data_root"] = os.path.dirname(config.clip_path)
    default_train_config['data']['scene_idx'] = clip_id
    default_train_config['data']['num_workers'] = num_workers
    default_train_config['data']['prefetch_factor'] = prefetch_factor

    current_time_train = now.strftime("%Y%m%d_%H%M%S") + "_" + str(random_num)
    output_path_root = f"/code/driverstudio_output_{clip_id}_{current_time_train}"
    local_config_path = f"/code/omnire_joint_trainning/configs/default_{current_time_train}.yaml"
    os.makedirs(os.path.dirname(local_config_path), exist_ok=True)
    with open(local_config_path, 'w') as file:
        yaml.dump(default_train_config, file, default_flow_style=False)

    global cfg
    ips_logger.info(f"[INFO] Start training 1234567 with config:\n")
    ips_logger.info(f"{default_train_config}")
    
    time2 = time.time()
    model_output_path = ips_train_driverstudio(local_config_path, output_path_root)
    time3 = time.time()
    context["gpu_train_time_cost"] = time3 - time2
    ips_logger.info(f"[INFO] Finish change IPY 1234567")
    ips_logger.info(f'reconic train time cost {time3-time2} s, clip{clip_id}')
    log_files = [f for f in os.listdir(os.path.join(model_output_path, "logs")) if f.endswith('.txt')]
    if not log_files:
        print(f"[ips debug log]no log.txt")
    first_log_file = log_files[0]
    file_path = os.path.join(model_output_path, "logs", first_log_file)
    with open(os.path.join(root_path, clip_id, "ips_time_log.txt"), 'r', encoding='utf-8') as source_file:
        ips_time_log_content = source_file.read()
    try:
        with open(file_path, 'a', encoding='utf-8') as file:
            file.write(ips_time_log_content) 
            file.write(f'[ips debug log]reconic train time cost {time3-time2} s, clip{clip_id}\n')  
        print(f"[ips debug log]success write time to log: {first_log_file}")
    except Exception as e:
        print(f"[ips debug log]error when write time to log: {e}")
    os.makedirs(os.path.join(fuyao_log_path, model_version, clip_id), exist_ok=True)
    shutil.copy(file_path, os.path.join(fuyao_log_path, model_version, clip_id, "log.txt"))

    # ips_evaluation(result_path_oss1)
    ips_logger.info(f"[INFO] Finish training 1234567")
    start_timestamp, end_timestamp = get_timestamps(model_output_path)
    ips_logger.info(f"[INFO] start_timestamp {start_timestamp}")
    ips_logger.info(f"[INFO] end_timestamp {end_timestamp}")

    ######################################### Post-process #########################################
    evaluation_oss_url = None
    mean_metrics = {}
    if enable_post_process:
        ips_logger.info("Starting post-processing for 3DGS model evaluation")
        # Call post_process function directly with new signature
        post_process_kwargs = {
            'logger': ips_logger,
            'clip_id': clip_id,
            'model_source': model_output_path,  # Use trained model path directly
            'dataset_root': config.clip_path,  # Use config.clip_path directly
            'model_version': model_version,
            'enable_fid': enable_fid, 
            'render_complete': render_complete,
        }
        evaluation_t0 = time.time()
        evaluation_oss_url, mean_metrics = post_process(**post_process_kwargs)
        context["evaluation_time_cost"] = time.time() - evaluation_t0
        if mean_metrics is None:
            mean_metrics = {}
        ips_logger.info("Post-processing completed")
    else:
        ips_logger.info("Post-processing skipped (enable_post_process=False)")


    # START Compress Files and Upload to OSS
    model_upload_t0 = time.time()
    temp_output_path = upload_train_model_to_oss_fast(model_output_path, result_path_oss1, suffix=str(current_time))
    context["model_upload_time_cost"] = time.time() - model_upload_t0
    ips_logger.info(f"[INFO] {clip_id} upload train model finished ({temp_output_path}).")
    os.system(f"rm -rf {temp_output_path}")

    processed_dds_extra = {}
    if bool(upload_processed_dds) and str(upload_processed_dds).lower() != "false" and upload_processed_dds != "0":
        runtime_for_dds = _load_pipeline_runtime_values(config.clip_path, ips_logger)
        processed_dds_info = runtime_for_dds.get("processed_dds") or {}
        processed_dds_dir = processed_dds_info.get("processed_dds_dir")
        if processed_dds_dir and os.path.isdir(processed_dds_dir):
            oss_prefix = upload_processed_dds_to_oss(
                processed_dds_dir, clip_id, model_version, ips_logger
            )
            processed_dds_extra = {
                "processed_dds_oss_prefix": oss_prefix,
                "processed_dds_bucket": "cloudsim-ci-sh",
                "processed_dds_files": [
                    "metadata",
                    "discovery",
                    processed_dds_info.get("merged_dat_name"),
                ],
            }
            ips_logger.info(f"[INFO] {clip_id} uploaded processed DDS to {oss_prefix}")
        else:
            ips_logger.warning(
                f"[WARN] {clip_id} skip processed DDS upload: missing dir {processed_dds_dir}"
            )

    ######################################### Send Message to Cloudsim #########################################
    adapted_start_timestamp = get_subrun_adapted_start_timestamp(start_timestamp)
    adapted_end_timestamp = end_timestamp
    jira_relative_seconds = context.get("extra_info", {}).get("jira_relative_seconds")
    issue_description = context.get("extra_info", {}).get("issue_description")
    adapted_trigger_timestamp = resolve_trigger_timestamp(config.clip_path, adapted_start_timestamp, adapted_end_timestamp, jira_relative_seconds, issue_description, config.trigger_time_offset_map)

    data_record = context["data_record"]

    check_status = get_render_check_status(config.clip_path, mean_metrics)

    runtime_values = _load_pipeline_runtime_values(config.clip_path, ips_logger)
    pipeline_start_time = runtime_values.get("pipeline_start_time", 0)
    cpu_preprocess_time_cost = runtime_values.get("cpu_preprocess_time_cost", 0)
    data_upload_time_cost = runtime_values.get("data_upload_time_cost", 0)
    pre_processor_end_time = runtime_values.get("pre_processor_end_time", 0)
    case_time = runtime_values.get("case_time", 0)
    case_distance = runtime_values.get("case_distance", 0)

    if pipeline_start_time == 0:
        pipeline_time_cost = 0
    else:
        pipeline_time_cost = time.time() - pipeline_start_time

    # Calculate scheduling wait time
    gpu_processor_start_time = context.get("gpu_processor_start_time", 0)
    if pre_processor_end_time > 0 and gpu_processor_start_time > 0:
        scheduling_wait_time = gpu_processor_start_time - pre_processor_end_time
    else:
        scheduling_wait_time = 0
    effective_pipeline_time_cost = pipeline_time_cost - scheduling_wait_time

    # Total pre_processor time (includes dump + cpu_pipeline + data_upload)
    if pipeline_start_time > 0 and pre_processor_end_time > 0:
        pre_processor_time_cost = pre_processor_end_time - pipeline_start_time
    else:
        pre_processor_time_cost = 0

    print(f"pipeline_start_time: {pipeline_start_time}")
    print(f"cpu_preprocess_time_cost: {cpu_preprocess_time_cost}")
    print(f"case_time: {case_time}")
    print(f"case_distance: {case_distance}")
    print(f"pipeline_time_cost: {pipeline_time_cost}")
    print(f"scheduling_wait_time: {scheduling_wait_time}")

    extra_info = {
        'bucket': 'cloudsim-ci-sh',
        'trian_model_address1': result_path_oss1,
        # 'render_output_address': upload_render_directory,
        'note': 'helloworld',
        'status': 'test_information',
        "adapted_start_timestamp": int(adapted_start_timestamp),
        "adapted_trigger_timestamp": int(adapted_trigger_timestamp),
        "adapted_end_timestamp": int(adapted_end_timestamp),
        "model_version" : model_version_input,
        "is_fm" : is_fm_bool,
        "is_dynamic": is_dynamic,
        "is_reconic": is_reconic,
        "scenario_slice_num": int(model_id),
        "input_id_type": "subrun_id",
        "reconic_preprocess_time_cost": (
            (
                cpu_preprocess_time_cost + (context.get("gpu_preprocess_time_cost") or 0)
            )
            / 60.0
        ),
        "cpu_preprocess_time_cost": cpu_preprocess_time_cost / 60.0,
        "gpu_preprocess_time_cost": (context.get("gpu_preprocess_time_cost") or 0) / 60.0,
        "pre_processor_time_cost": pre_processor_time_cost / 60.0,
        "reconic_train_time_cost": (
            (context.get("gpu_train_time_cost") or 0) / 60.0
        ),
        "dataset_upload_time_cost": (context.get("dataset_upload_time_cost") or 0) / 60.0,
        "model_upload_time_cost": (context.get("model_upload_time_cost") or 0) / 60.0,
        "evaluation_time_cost": (context.get("evaluation_time_cost") or 0) / 60.0,
        "check_status": check_status,
        "preprocess_specific_time_cost": context.get("preprocess_specific_time_cost", {}),
        "reconic_pipeline_time_cost": pipeline_time_cost / 60.0,
        "reconic_effective_pipeline_time_cost": effective_pipeline_time_cost / 60.0,
        "scheduling_wait_time": scheduling_wait_time / 60.0,
        "data_upload_time_cost": data_upload_time_cost / 60.0,
        "case_time": case_time,
        "case_distance": case_distance,
        "mode": "normal",
        "gpu_retry_count": context.get("gpu_retry_count", 0),
        **({"job_id": context["cloudsim_job_id"]} if "cloudsim_job_id" in context else {}),
        **({"ucp_job_id": context["ucp_job_id"]} if context.get("ucp_job_id") else {}),
    }
    extra_info.update(processed_dds_extra)

    if evaluation_oss_url is not None:
        extra_info['evaluation_oss_address'] = evaluation_oss_url
        ips_logger.info(f"Added evaluation OSS URL to notification: {evaluation_oss_url}")

    data_record.notify_cloudsim_3dgs(
        is_user_label=True,
        extra_info=extra_info
    )
    _upload_extra_info_to_oss(extra_info, result_path_oss1, config.clip_path, ips_logger)

    data_record.save_tag(
        tag=str(model_version)
    )
    _cleanup_subprocess_and_cuda(ips_logger)
    print(
        f"[SIMDIAG] [gpu_processor_done] clip={clip_id}",
        flush=True
    )


def gpu_processor(context: dict, **kwargs):
    ips_logger = context.get("logger")
    try:
        ucp_job_id = os.environ.get('UCP_JOB_ID', '')
        context['ucp_job_id'] = ucp_job_id
        _fetch_cloudsim_task_info(context, **kwargs)
        _gpu_processor_impl(context, **kwargs)
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
        _cleanup_subprocess_and_cuda(ips_logger)


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
        opts=[]  
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
        shutil.copy(sim_config_path, os.path.join(output_path, os.path.join(model_path, "configs", "config_reconic.yaml")))
    else:
        print("[ips debug log]: cannot copy config for cloudsim! path ", sim_config_path, "not exist!")
    return model_path

def ips_train_official():
    import train_2stages
    import lib.config
    importlib.reload(train_2stages)
    importlib.reload(lib.config)
    from lib.utils.general_utils import safe_state
    safe_state(lib.config.cfg.train.quiet)
    torch.autograd.set_detect_anomaly(lib.config.cfg.train.detect_anomaly)
    train_2stages.training_xpeng()
    return lib.config.cfg


def ips_evaluation(result_path_oss):
    from sim_bridge.novel_eval import NovelEvaluator
    novel_eval = NovelEvaluator()
    novel_eval.generate_novel_views()
    json_path = novel_eval.evaluate(cfg.source_path)
    upload(
        json_path, 'evaluation_results.json', 
        bucket_name='cloudsim-ci-sh', oss_directory=result_path_oss
    )


def main():
    from xdata.dataset_v2.dataset_loader import DatasetLoader
    from xdata.dataset_v2.data_record import SENSOR_CLIP_RECORD_TYPE, SUBRUN_RECORD_TYPE
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
        "dataset_id": "wgq_3dgs_subrun",
        "limit": 10,
        "record_type": SUBRUN_RECORD_TYPE,
    }

    data_loader = DatasetLoader(data_loader_config)
    dataset = data_loader.load_dataset_v2(
        **xdataset_config,
    )

    target_id = "c-1c7e61ab-b020-312e-9a5b-3d9a19eb67a8"  # 指定你要查找的 ID 值
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
        "root_path": "/workspace/yangxh7@xiaopeng.com/datasets/xpeng/subrun/",
        "id": "c-1c7e61ab-b020-312e-9a5b-3d9a19eb67a8",
        "data_record": record,
        "dataset": dataset,
        "data_loader" : data_loader,
        "logger": logger
    }
 
    pre_processor(context)
    gpu_processor(context)
    post_processor(context)


def upload_processed_dds_to_oss(local_dir, clip_id, model_version, logger):
    """Upload merged DDS directory to sim_engine/processed_dds/{clip_id}/{model_version}/."""
    oss_prefix = f"sim_engine/processed_dds/{clip_id}/{model_version}"
    logger.info(f"[INFO] Uploading processed DDS from {local_dir} to oss://cloudsim-ci-sh/{oss_prefix}")
    if not upload_local_dir_to_oss(local_dir, oss_prefix):
        raise RuntimeError(f"Failed to upload processed DDS to {oss_prefix}")
    return oss_prefix


def process_dds_data(dds_data_source, clip_path, start_time, end_time, logger):
    """
    从 OSS 下载 DDS，解码原始视频，再按 start_time/end_time 合并切分并剔除 CameraVideoTopic。
    返回 processed_dds 元数据供 GPU 阶段上传 OSS。
    """
    bucket = dds_data_source.get("bucket")
    dds_files = dds_data_source.get("dds_files", [])

    if not bucket or not dds_files:
        logger.warning(f"[WARNING] Invalid ddsDataSource: bucket={bucket}, dds_files={dds_files}")
        return {}

    if start_time is None or end_time is None:
        raise RuntimeError("start_time and end_time are required for DDS merge/slice")

    start_timestamp = int(start_time)
    end_timestamp = int(end_time)
    if end_timestamp <= start_timestamp:
        raise ValueError(
            f"invalid DDS window: start={start_timestamp} end={end_timestamp}"
        )

    dds_data_path = os.path.join(clip_path, "dds_data")
    os.makedirs(dds_data_path, exist_ok=True)

    files_to_download = [dds_data_source.get("metadata"), dds_data_source.get("discovery")] + dds_files
    for file_key in files_to_download:
        if not file_key:
            continue
        local_path = os.path.join(dds_data_path, os.path.basename(file_key))
        logger.info(f"[INFO] Downloading: {file_key}")
        if not download_file_from_oss2(local_path, object_key=file_key, bucket_name=bucket):
            raise RuntimeError(f"Failed to download: {file_key}")

    for dds_file_key in dds_files:
        local_file = os.path.join(dds_data_path, os.path.basename(dds_file_key))
        if local_file.endswith(".lz4"):
            local_dat_file = local_file[:-4]
            logger.info(f"[INFO] Decompressing: {local_file}")
            subprocess.run(['lz4', '-d', '-f', local_file, local_dat_file], check=True, capture_output=True, timeout=1800)
            os.remove(local_file)

    logger.info("[INFO] Running camera_video_xp5_decoder on raw dds_data...")
    images_output_path = os.path.join(clip_path, "images_origin_all")
    os.makedirs(images_output_path, exist_ok=True)
    decoder_path = os.environ.get(
        "CAMERA_VIDEO_DECODER", "/usr/local/bin/camera_video_xp5_decoder"
    )
    cmd = [
        decoder_path,
        f"--input_path={os.path.join(dds_data_path, 'metadata')}",
        f"--output_path={images_output_path}",
        f"--start_timestamp={start_timestamp}",
        f"--end_timestamp={end_timestamp}",
    ]
    logger.info(f"[INFO] Executing: {' '.join(cmd)}")
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3600)
    logger.info(f"[INFO] DDS decode completed. Output: {images_output_path}")

    dds_merged_path = os.path.join(clip_path, "dds_merged")
    logger.info(
        f"[INFO] Merging/slicing DDS into {dds_merged_path} "
        f"window [{start_timestamp}, {end_timestamp}]"
    )
    merge_result = run_merge_and_slice_abs(
        dds_data_path,
        dds_merged_path,
        start_timestamp,
        end_timestamp,
    )
    logger.info(
        f"[INFO] DDS merge completed: {merge_result.merged_dat_path} "
        f"[{merge_result.min_timestamp}, {merge_result.max_timestamp}]"
    )
    return {
        "processed_dds_dir": dds_merged_path,
        "merged_dat_name": merge_result.out_dat_name,
        "min_timestamp": merge_result.min_timestamp,
        "max_timestamp": merge_result.max_timestamp,
    }


if __name__ == "__main__":
    main()