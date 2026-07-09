import json
import os
import sys
import uuid
import requests
import subprocess
import tarfile
import shutil
from enum import Enum


class RenderMode(Enum):
    ORIGINAL = "original"      # 原车型重渲染模式
    NEW_VEHICLE = "new_vehicle"  # 新车型渲染模式


# 添加必要的路径到sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
simworld_dir = os.path.join(current_dir, "..", "..")
reconic_src_path = os.path.join(simworld_dir, "omnire_joint_trainning", "src")
sim_interface_path = simworld_dir

sys.path.insert(0, sim_interface_path)
sys.path.insert(0, reconic_src_path)
sys.path.insert(0, current_dir)


from reconic.multi_vehicle_utils.png_to_h265 import encode_from_dir
from reconic.multi_vehicle_utils.create_multi_vehicle_scenario import build_success_message, send_kafka_error_message, _send_kafka
from reconic.simulator.reconic_simulator import ReconicSimulator
from scripts.render_switch_car import render_switch_car, generate_new_calib_and_transform, restore_original_calib_and_transform
from reconic.multi_vehicle_utils.cloudsim_request import cloudsim_request
from reconic.multi_vehicle_utils.query_scenario_event import query_scenario_event, VEHICLE_TYPE_2_ID
from reconic.multi_vehicle_utils.encode_and_decode_utils import png_to_video, generate_timestamp_records, decode_h265_to_png, update_h265_results_to_dds
from reconic.multi_vehicle_utils.dds_file_utils import copy_calibration_file, compress_recordings, download_and_extract_dds, download_file_from_oss


PIPELINE_RECORD_FILENAME = "pipeline_record.json"


def persist_record(record: dict, root_path: str):
    """将record持久化到root_path下的JSON文件，供后续processor读取

    UCP框架串行调度三个processor为独立进程，
    每个进程的context只有调度平台传入的初始参数，
    无法传递pre_processor对record的修改。
    因此将record序列化写入共享路径，后续processor从文件加载。
    """
    record_path = os.path.join(root_path, PIPELINE_RECORD_FILENAME)
    # 过滤掉不可序列化的字段（如有）
    serializable_record = {
        k: v for k, v in record.items()
        if not callable(v) and not isinstance(v, type)
    }
    with open(record_path, "w", encoding="utf-8") as f:
        json.dump(serializable_record, f, ensure_ascii=False, indent=2)
    print(f"record已持久化到: {record_path}")


def load_record(root_path: str) -> dict:
    """从root_path下的JSON文件加载上一个processor持久化的record

    Returns:
        dict: 上一个processor保存的完整record上下文
    """
    record_path = os.path.join(root_path, PIPELINE_RECORD_FILENAME)
    if not os.path.exists(record_path):
        raise FileNotFoundError(
            f"未找到持久化的record文件: {record_path}\n"
            f"请确保pre_processor已成功执行并持久化record"
        )
    with open(record_path, "r", encoding="utf-8") as f:
        record = json.load(f)
    print(f"record已从持久化文件加载: {record_path}")
    return record


def should_use_new_calibration(context: dict) -> bool:
    """判断是否应该使用新的校准文件"""
    return context.get("render_mode") == RenderMode.NEW_VEHICLE.value


def get_upload_vehicle_type(context: dict) -> str:
    """获取上传到OSS时使用的车辆类型标识"""
    if context.get("render_mode") == RenderMode.ORIGINAL.value:
        return "origin"
    else:
        return context.get("target_vehicle", "unknown")


def initialize_paths(context: dict, task_info: dict):
    """初始化所有路径，统一管理"""
    event_path = context["event_path"]
    vehicle_name =  context.get("target_vehicle", "")
    calibration_filename = "calib"+ "_"+ vehicle_name+".json"
    # 初始化各种路径
    context["paths"] = {
        # DDS相关路径
        "dds_path": os.path.join(event_path, "dds"),
        "dds_metadata_path": os.path.join(event_path, "dds", "metadata"),
        "dds_discovery_path": os.path.join(event_path, "dds", "discovery"),
        "dds_calibration_path": os.path.join(event_path, "dds", "calibration"),

        # calib相关路径
        "target_vehicle_calib_path": os.path.join("/workspace/group_share/adc-sim/users/multi_vehicle/calibs", calibration_filename),
        
        # 图像相关路径
        "images_origin_path": os.path.join(event_path, "images_origin"),
        
        # 渲染相关路径
        "rendered_output_path": os.path.join(event_path, "rendered_output"),
        "rendered_redistort_rgb_path": os.path.join(event_path, "rendered_output", "redistort_rgb"),
        
        # 时间戳记录路径
        "timestamp_records_path": os.path.join(event_path, "timestamp_records.json"),
        
        # H265相关路径
        "output_h265_path": os.path.join(event_path, "output_h265"),
        
        # DDS输出路径
        "output_dds_path": os.path.join(event_path, "output_dds"),
        
        # 视频输出路径
        "output_video_path": os.path.join(event_path, "output_video"),
        
        # 模型下载路径
        "model_download_path": os.path.join(event_path, "3dgs_model.tgz"),
        
        # 其他路径
        "event_path": event_path
    }
    os.environ["REF_PATH"] = context["paths"]["images_origin_path"]
    return context



def render_multi_vehicle(context: dict, task_info: dict):
    """渲染多车型"""
    model_path = task_info.get("threedgs_model_path", "")
    if not model_path.startswith("oss://"):
        raise ValueError(f"模型路径不是OSS路径: {model_path}")
    
    download_path = context["paths"]["model_download_path"]
    event_path = context["paths"]["event_path"]
    # os.makedirs(download_path, exist_ok=True)
    
    # 下载模型文件
    print(f"正在下载模型文件: {model_path} -> {download_path}")
    download_file_from_oss(model_path, download_path)
    
    # 解压模型（静默模式，不输出详细日志）
    print(f"正在解压模型文件: {download_path} -> {event_path}")
    subprocess.run(['tar', '-xf', download_path, '-C', event_path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # 删除压缩文件
    os.remove(download_path)
    print(f"模型下载并解压完成: {event_path}")
    
    # 获取模型路径
    model_path = os.path.join(event_path, "model1")
    
    # 获取new_calib_path和new_img_timestamps_path
    # 这些可能需要从context或task_info中获取，或者使用默认值
    new_calib_path = context["paths"]["target_vehicle_calib_path"]
    new_img_timestamps_path = context["paths"]["timestamp_records_path"]
    
    backup_info = None
    try:
        # 生成新的calib和transform（如果有提供new_calib_path）
        # 只有在新车型渲染模式下才应用新的校准文件
        if should_use_new_calibration(context):
            if new_calib_path and os.path.exists(new_calib_path):
                print(f"正在生成新的calib和transform: {new_calib_path}")
                backup_info = generate_new_calib_and_transform(
                    model_path, 
                    new_calib_path, 
                    new_img_timestamps_path
                )
            else:
                raise ValueError("未提供new_calib_path")
        
        # 渲染
        config_path = os.path.join(model_path, "configs", "config_sim.yaml")
        
        # 确定vehicle_model：origin表示使用原始车型（从metadata.json读取），否则根据target_vehicle映射
        target_vehicle = context.get("target_vehicle", "")
        if target_vehicle == "origin":
            vehicle_model = None
        else:
            vehicle_model = VEHICLE_TYPE_2_ID.get(target_vehicle.lower())
            if vehicle_model is None:
                raise ValueError(f"未知的target_vehicle: {target_vehicle}，无法找到对应的vehicle_model")
        
        simulator = ReconicSimulator(config_path, cp_simulation=True, iter=None, init_from_feedforward=False, vehicle_model=vehicle_model)
        
        render_switch_car(
            simulator,
            context["paths"]["images_origin_path"],
            context["paths"]["timestamp_records_path"],
            context["paths"]["rendered_output_path"]
        )
        
        scenario_id = context.get("closeloop_scenario_id", "unknown")
        print(f"场景 {scenario_id} 的多车型渲染处理完成")
    except Exception as e:
        scenario_id = context.get("closeloop_scenario_id", "unknown")
        print(f"场景 {scenario_id} 的多车型渲染处理失败: {e}")
        raise        
    finally:
        # 恢复原始的calib和transform
        if backup_info is not None:
            print("正在恢复原始的calib和transform")
            restore_original_calib_and_transform(backup_info)
    

def convert_png_to_h265(context: dict, task_info: dict):
    """将渲染结果的png转为h265"""
    encode_from_dir(
        context["paths"]["rendered_redistort_rgb_path"],
        context["paths"]["output_h265_path"]
    )




def upload_to_oss(source_path: str, vehicle_type: str, event_id: str, oss_subpath: str = "", bucket_name: str = "data-pipeline-dds-quarantine") -> bool:
    """
    通用OSS上传函数（支持目录上传）
    
    Args:
        source_path: 本地源文件或目录路径
        vehicle_type: 车辆类型
        event_id: 事件ID
        oss_subpath: OSS子路径后缀
        bucket_name: OSS bucket名称
    
    Returns:
        上传是否成功
    """
    from upload2oss import upload, upload_directory_to_oss_fast
    
    oss_target_path = f"adc-sim/multi-vehicle-test/{vehicle_type}/{event_id}"
    if oss_subpath:
        oss_target_path = f"{oss_target_path}/{oss_subpath}"
    
    try:
        # 判断是文件还是目录
        if os.path.isdir(source_path):
            # 目录上传：使用ossutil64快速上传
            print(f"上传目录到OSS: {source_path} -> {oss_target_path}")
            success = upload_directory_to_oss_fast(
                local_directory=source_path,
                oss_directory=oss_target_path,
                var_endpoint='http://oss-cn-wulanchabu-internal.aliyuncs.com',
                var_access_key='OSS_ACCESS_KEY_ID_REDACTED',
                var_secret_key='OSS_ACCESS_KEY_SECRET_REDACTED',
                var_job_num=10,
                var_bucket_name=bucket_name
            )
        else:
            # 文件上传
            print(f"上传文件到OSS: {source_path} -> {oss_target_path}")
            upload(source_path, oss_target_path, bucket_name, "")
            success = True
        
        if success:
            print(f"上传成功: oss://{bucket_name}/{oss_target_path}")
        return success
    except Exception as e:
        print(f"上传失败: {e}")
        raise


def upload_video_to_oss(context: dict, task_info: dict) -> bool:
    """上传视频文件到OSS"""
    event_id = task_info.get("event_id")
    vehicle_type = get_upload_vehicle_type(context)
    
    success = upload_to_oss(
        source_path=context["paths"]["output_video_path"],
        vehicle_type=vehicle_type,
        event_id=event_id,
        oss_subpath="multi_vehicle_video"
    )
    
    context["multi_vehicle_video_path"] = f"oss://data-pipeline-dds-quarantine/adc-sim/multi-vehicle-test/{vehicle_type}/{event_id}/multi_vehicle_video"
    
    return success


def upload_dds_to_oss(context: dict, task_info: dict) -> bool:
    """上传DDS文件到OSS"""
    return upload_to_oss(
        source_path=context["paths"]["output_dds_path"],
        vehicle_type=get_upload_vehicle_type(context),
        event_id=task_info.get("event_id")
    )



def clean_up_tmp_data(context: dict):
    """清理临时数据"""
    target_path = context.get("root_path")

    if target_path and os.path.exists(target_path):
        os.system(f"rm -rf {target_path}")
        print(f"临时数据清理完成: {target_path}")
    else:
        print("未找到有效的临时数据路径，跳过清理")


def pre_processor(context: dict, **kwargs):
    """预处理器：查询场景信息、下载数据、解码视频"""

    records = context.get("records", {})
    record_id = next(iter(records.keys())) if records else ""
    record = next(iter(records.values())) if records else {}

    try:
        target_vehicle = context.get('target_vehicle', '')
        if not target_vehicle:
            raise ValueError("target_vehicle不能为空")

        # 设置渲染模式
        render_mode = RenderMode.ORIGINAL if target_vehicle == 'origin' else RenderMode.NEW_VEHICLE

        openloop_scenario_id = record.get("openloop_scenario_id")
        if not openloop_scenario_id:
            raise ValueError("未找到openloop_scenario_id")

        # 将关键信息写入record，后续以record作为上下文传参
        record["target_vehicle"] = target_vehicle
        record["render_mode"] = render_mode.value
        record["default_label"] = "cross_vehicle_3dgs_render"
        record["ucp_job_id"] = os.environ.get('UCP_JOB_ID', '')
        record["job_id"] = context.get('job_id', '')

        # 从context获取工作根目录
        root_path = context.get("root_path")
        if not root_path:
            raise ValueError("context中未找到root_path")

        print(f"场景工作目录: {root_path}")

        # 保存root_path供异常清理使用
        record["root_path"] = root_path

        # 查询场景信息，以record作为上下文传参
        task_info = query_scenario_event(record)
        record["closeloop_scenario_id"] = task_info.get("closeloop_scenario_id")
        record["task_info"] = task_info

        # 初始化路径，以record作为上下文传参
        record["event_path"] = os.path.join(root_path, task_info.get("event_id"))
        initialize_paths(record, task_info)

        # 下载并解压DDS数据
        download_and_extract_dds(
            event_path=record["event_path"],
            dds_path=record["paths"]["dds_path"],
            task_info=task_info
        )

        # 生成时间戳记录
        generate_timestamp_records(
            record['paths']['dds_metadata_path'],
            record['paths']['event_path']
        )

        # 解码H265为PNG
        decode_h265_to_png(
            record['paths']['dds_metadata_path'],
            record['paths']['images_origin_path']
        )

        persist_record(record, root_path)

        print(f"预处理器完成，任务信息: {task_info}")

        return [record_id], [], {}
    except Exception as e:
        send_kafka_error_message(record, error_msg=str(e))
        clean_up_tmp_data(record)
        raise


def gpu_processor(context: dict, **kwargs):
    """GPU处理器：渲染多车型、转换视频格式"""
    print("GPU处理器开始处理...")
    records = context.get("records", {})
    record_id = next(iter(records.keys())) if records else ""
    record = {}

    try:
        root_path = context.get("root_path")
        if not root_path:
            raise ValueError("context中未找到root_path")
        record = load_record(root_path)
        os.environ["REF_PATH"] = record.get("paths", {}).get("images_origin_path")
        task_info = record.get("task_info", {})

        render_multi_vehicle(record, task_info)
        convert_png_to_h265(record, task_info)

        paths = record["paths"]
        # 合成视频
        png_to_video(
            paths['images_origin_path'],
            paths['rendered_redistort_rgb_path'],
            paths['output_video_path']
        )

        print("GPU处理器完成")

        return [record_id], [], {}
    except Exception as e:
        send_kafka_error_message(record, error_msg=str(e))
        clean_up_tmp_data(record)
        raise


def post_processor(context: dict, **kwargs):
    """后处理器：DDS更新、文件上传、Kafka消息发送"""
    print("后处理器开始处理...")

    records = context.get("records", {})
    record_id = next(iter(records.keys())) if records else ""
    record = {}

    try:
        # 从持久化文件加载record（跨进程状态传递）
        root_path = context.get("root_path")
        if not root_path:
            raise ValueError("context中未找到root_path")
        record = load_record(root_path)
        task_info = record.get("task_info", {})
        paths = record["paths"]

        # 更新DDS结果
        update_h265_results_to_dds(
            paths['dds_metadata_path'],
            paths['output_dds_path'],
            paths['output_h265_path']
        )

        # 获取openloop_dds_result中的期望格式
        openloop_dds_result = task_info.get('openloop_dds_result', {})
        expected_dds_paths = openloop_dds_result.get('dds_paths', [])
        expected_calibration = openloop_dds_result.get('calibration', '')

        # 复制校准文件
        copy_calibration_file(
            target_vehicle=record["target_vehicle"],
            dds_path=paths["dds_path"],
            output_dds_path=paths["output_dds_path"],
            same_vehicle=not should_use_new_calibration(record),
            expected_calibration=expected_calibration
        )

        # 根据期望格式压缩DDS（仅当期望格式为.lz4时才压缩）
        compress_recordings(
            output_dds_path=paths["output_dds_path"],
            expected_dds_paths=expected_dds_paths
        )

        # 上传结果，以record作为上下文传参
        upload_dds_to_oss(record, task_info)
        upload_video_to_oss(record, task_info)

        # 构建并发送成功Kafka消息通知cloudsim场景泛化
        message = build_success_message(record, task_item=task_info)
        _send_kafka("cloudsim_3dgs", message, record.get('openloop_scenario_id'))

        print("后处理器完成, Kafka消息已发送")

        return [record_id], [], {}
    except Exception as e:
        send_kafka_error_message(record, error_msg=str(e))
        raise
    finally:
        clean_up_tmp_data(record)


def main():
    """
    主函数，用于测试 pre_processor, gpu_processor, post_processor 三个处理器
    """
    print("正在初始化测试环境...")

    # 创建测试上下文
    context = {
        "id": "test_scenario_id",  # 测试场景ID
        "job_root_path": "/tmp/test_job_root",  # 测试工作根路径
        "root_path": "/tmp/test_job_root/test_scenario_id",
        "target_vehicle": "E28",
        "records": {
            "test_openloop_id": {
                "openloop_scenario_id": "test_openloop_id"
            }
        }
    }

    result1 = pre_processor(context, target_vehicle="E28", custom_label="test_label")
    print(f"pre_processor result: {result1}")
    result2 = gpu_processor(context)
    print(f"gpu_processor result: {result2}")
    result3 = post_processor(context)
    print(f"post_processor result: {result3}")


if __name__ == "__main__":
    main()
    