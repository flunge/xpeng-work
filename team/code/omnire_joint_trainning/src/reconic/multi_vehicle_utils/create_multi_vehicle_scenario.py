#!/usr/bin/env python3
"""
脚本功能：
1. 遍历task_info_list.json，获取event_id
2. 根据openloop_dds_result中的文件名，检查OSS上文件是否存在
3. 如果所有文件都存在，则发送Kafka消息通知cloudsim进行场景泛化
"""

import json
import os
import subprocess
import argparse
import time

def check_oss_file_exists(oss_url):
    """使用ossutil检查OSS上的文件是否存在"""
    print(f"Checking if file exists: {oss_url}")
    
    try:
        # 使用ossutil stat命令检查文件是否存在
        result = subprocess.run(['ossutil64', 'stat', oss_url], 
                                stdout=subprocess.DEVNULL, 
                                stderr=subprocess.DEVNULL, 
                                check=False)

        return result.returncode == 1
    except Exception as e:
        print(f"Error checking OSS file {oss_url} with ossutil: {str(e)}")
        return False


def construct_oss_path(vehicle, event_id, filename):
    """根据vehicle、event_id和文件名构建OSS路径"""
    return f"oss://data-pipeline-dds-quarantine/adc-sim/multi-vehicle-test/{vehicle}/{event_id}/{filename}"


def check_all_files_exist(task_item, vehicle):
    """检查单个任务项的所有文件是否存在"""
    event_id = task_item.get('event_id')
    
    # 从openloop_dds_result获取文件名（不含路径）
    openloop_dds_result = task_item.get('openloop_dds_result', {})
    
    # 从metadata路径中提取文件名
    metadata_full_path = openloop_dds_result.get('metadata')
    if metadata_full_path:
        metadata_filename = metadata_full_path.split('/')[-1]  # 获取文件名部分
        metadata_oss_path = construct_oss_path(vehicle, event_id, metadata_filename)
        if not check_oss_file_exists(metadata_oss_path):
            print(f"Metadata file does not exist: {metadata_oss_path}")
            return False
    
    # 从discovery路径中提取文件名
    discovery_full_path = openloop_dds_result.get('discovery')
    if discovery_full_path:
        discovery_filename = discovery_full_path.split('/')[-1]  # 获取文件名部分
        discovery_oss_path = construct_oss_path(vehicle, event_id, discovery_filename)
        if not check_oss_file_exists(discovery_oss_path):
            print(f"Discovery file does not exist: {discovery_oss_path}")
            return False
    
    # 从calibration路径中提取文件名
    calibration_full_path = openloop_dds_result.get('calibration')
    if calibration_full_path:
        calibration_filename = calibration_full_path.split('/')[-1]  # 获取文件名部分
        calibration_oss_path = construct_oss_path(vehicle, event_id, calibration_filename)
        if not check_oss_file_exists(calibration_oss_path):
            print(f"Calibration file does not exist: {calibration_oss_path}")
            return False
    
    # 从dds_paths中提取文件名
    dds_paths = openloop_dds_result.get('dds_paths', [])
    for dds_full_path in dds_paths:
        dds_filename = dds_full_path.split('/')[-1]  # 获取文件名部分
        dds_oss_path = construct_oss_path(vehicle, event_id, dds_filename)
        if not check_oss_file_exists(dds_oss_path):
            print(f"DDS file does not exist: {dds_oss_path}")
            return False
    
    return True


def _send_kafka(topic, message, scenario_id):
    """底层Kafka消息发送"""
    from ucp.tools.ucp_producer import UcpStreamingMsgProducer
    print(f"Kafka消息内容: {json.dumps(message, ensure_ascii=False)}")
    try:
        producer = UcpStreamingMsgProducer()
        producer.send_messages(topic, [message])
        print(f"Kafka消息发送成功, topic: {topic}, id: {scenario_id}")
    except Exception as e:
        print(f"Kafka消息发送失败: {type(e).__name__}: {e}")
        raise


def send_kafka_error_message(context, error_msg):
    """发送Kafka错误消息通知cloudsim场景泛化失败"""
    topic = "cloudsim_3dgs"
    original_scenario_id = context.get('openloop_scenario_id')
    message = {
        "job_type": "generalize",
        "id": str(original_scenario_id),
        "status": "error",
        "error_msg": error_msg,
        "extra_info": {
            "job_id": context.get('job_id', ''),
            "ucp_job_id": context.get('ucp_job_id', ''),
            "original_scenario_id": int(original_scenario_id) if original_scenario_id else None,
            "vehicle_name": context.get('target_vehicle', ''),
        }
    }
    _send_kafka(topic, message, original_scenario_id)


def build_success_message(context, task_item):
    """构建Kafka成功消息体

    将DDS路径映射、labels等信息组装为cloudsim回调所需的消息格式。
    """
    original_scenario_id = task_item.get('openloop_scenario_id')
    event_id = task_item.get('event_id')

    # 构建DDS路径映射（从原路径中提取文件名，然后按新的路径格式构建）
    openloop_dds_result = task_item.get('openloop_dds_result', {})
    vehicle_type_for_path = context.get("upload_vehicle_type", context.get("target_vehicle"))

    # 从原路径中提取文件名并构建新的OSS路径
    metadata_full_path = openloop_dds_result.get('metadata', '')
    if metadata_full_path:
        metadata_filename = metadata_full_path.split('/')[-1]
        metadata_path = f"adc-sim/multi-vehicle-test/{vehicle_type_for_path}/{event_id}/{metadata_filename}"
    else:
        metadata_path = ""

    discovery_full_path = openloop_dds_result.get('discovery', '')
    if discovery_full_path:
        discovery_filename = discovery_full_path.split('/')[-1]
        discovery_path = f"adc-sim/multi-vehicle-test/{vehicle_type_for_path}/{event_id}/{discovery_filename}"
    else:
        discovery_path = ""

    dds_full_paths = openloop_dds_result.get('dds_paths', [])
    dds_files = []
    for dds_full_path in dds_full_paths:
        dds_filename = dds_full_path.split('/')[-1]
        dds_file_path = f"adc-sim/multi-vehicle-test/{vehicle_type_for_path}/{event_id}/{dds_filename}"
        dds_files.append(dds_file_path)

    calibration_full_path = openloop_dds_result.get('calibration', '')
    if calibration_full_path:
        calibration_filename = calibration_full_path.split('/')[-1]
        calibration_path = f"adc-sim/multi-vehicle-test/{vehicle_type_for_path}/{event_id}/{calibration_filename}"
    else:
        calibration_path = ""

    # labels
    labels = []
    labels.append(context.get('default_label'))
    if context.get('custom_label'):
        labels.append(context.get('custom_label'))
    origin_openloop_scenario_label = "origin_openloop_scenario_" + str(original_scenario_id)
    labels.append(origin_openloop_scenario_label)

    origin_close_loop_scenario_label = "origin_close_loop_scenario_" + str(task_item.get('closeloop_scenario_id'))
    labels.append(origin_close_loop_scenario_label)

    vehicle_label = task_item.get('vehicle_type') + "_to_" + context.get('target_vehicle')
    labels.append(vehicle_label)

    return {
        "job_type": "generalize",
        "id": str(original_scenario_id),
        "status": "success",
        "extra_info": {
            "job_id": context.get('job_id', ''),
            "ucp_job_id": context.get('ucp_job_id', ''),
            "original_scenario_id": int(original_scenario_id),
            "labels": labels,
            "multi_vehicle_video_path": context.get('multi_vehicle_video_path'),
            "new_data": {
                "ddsDataSource": {
                    "bucket": "data-pipeline-dds-quarantine",
                    "dds_files": dds_files,
                    "metadata": metadata_path,
                    "calibration": calibration_path,
                    "discovery": discovery_path
                },
                "vehicle_name": context.get('target_vehicle', '')
            }
        }
    }




def main():
    json_file = 'e29_task_info_list.json'
    vehicle = 'origin'

    # 读取JSON文件
    with open(json_file, 'r', encoding='utf-8') as f:
        task_info_list = json.load(f)

    print(f"Loaded {len(task_info_list)} tasks from {json_file}")
    scenario_map = {}
    # 遍历每个任务项
    for idx, task_item in enumerate(task_info_list):
        print(f"\nProcessing task {idx + 1}/{len(task_info_list)}, event_id: {task_item.get('event_id')}")
        origin_scenario = task_item.get('openloop_scenario_id')
        # 检查所有相关文件是否存在于OSS上
        if not check_all_files_exist(task_item, vehicle):
            print(f"Skipping task {task_item.get('event_id')} due to missing files")
            continue

        print(f"All files exist for event_id: {task_item.get('event_id')}, proceeding with Kafka message...")

        # 发送Kafka消息
        context = {'vehicle_name': vehicle, 'default_label': 'multi_vehicle_test', 'custom_label': '', 'multi_vehicle_video_path': ''}
        message = build_success_message(context, task_item)
        _send_kafka("cloudsim_3dgs_dev", message, task_item.get('openloop_scenario_id'))
        scenario_map[origin_scenario] = "kafka_sent"
        time.sleep(1)
    for origin_scenario, status in scenario_map.items():
        print(f"{origin_scenario}: {status}")

if __name__ == "__main__":
    main()