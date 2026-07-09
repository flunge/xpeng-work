#!/usr/bin/env python3
import json
import re
import os

# 导入cloudsim_request
from reconic.multi_vehicle_utils.cloudsim_request import cloudsim_request


def extract_event_id(labels):
    """从 labels 中提取纯数字的 event id。"""
    if not labels:
        return None

    for item in labels:
        if isinstance(item, str) and item.isdigit():
            return item
        if isinstance(item, dict):
            for key in ("label", "name", "id", "value"):
                val = item.get(key)
                if isinstance(val, str) and val.isdigit():
                    return val
                if isinstance(val, int):
                    return str(val)

    return None

def query_scenario(scenario_id):
    url = "https://cloudsim.xiaopeng.link/simulation/scenario/query/"

    # 使用cloudsim_request函数发送请求
    data = {
        "id": scenario_id
    }
    
    try:
        response = cloudsim_request(url, data)
        return response
    except Exception as e:
        print(f"Error querying scenario: {e}")
        raise

def query_paginate_aio(event_id, mode='close loop'):
    mtype = 48 if mode == 'close loop' else 54
    url = "https://cloudsim.xiaopeng.link/simulation/scenario/paginate_query_aio/"

    # 使用cloudsim_request函数发送请求
    data = {
        "page": 1,
        "size": 10,
        "status": -1,
        "userName": 'cloudsim-engine@xiaopeng.com',
        "type": mtype,
        "search_labels": f"({event_id})"
    }
    
    try:
        response = cloudsim_request(url, data)
        data_list = response.get("data", None)
        print(f"event_id: {event_id}, data_list: {len(data_list) if data_list else 0}")
        if data_list:
            return data_list
        return []
    except Exception as e:
        print(f"Error querying paginate aio: {e}")
        raise            


# ============ ucp_multi_vehicle 场景查询封装 ============

vehicle_name_suffixes = ["_test_vehicle", "_prod_vehicle"]

VEHICLE_TYPE_2_ID = {
    "e28": 20,
    "e28a": 21,
    "e29": 201,
    "e38": 40,
    "e38a": 43,
    "e38b": 203,
    "f01": 205,
    "f30": 50,
    "f30b": 206,
    "f57": 70,
    "h93": 60,
    "h93a": 210,
    "f01xccp": 269,
    "h93aes": 231,
    "f57aes": 229,
    "d01m": 212,
    "e29 xp5": 213,
    "f01 xp5": 232,
    "f30bes": 238,
    "e38be": 243,
    "f01es": 247,
    "d01axm": 256,
    "d03esxm": 281,
    "g01": 239,
    "g01es": 239,
    "d01a": 212,
    "d03es": 281,
}


def parse_oss_path(scenario_info):
    """解析场景信息中的OSS数据源路径"""
    dds_data_source = scenario_info.get("ddsDataSource")
    if not dds_data_source:
        return {}
    
    bucket = dds_data_source.get("bucket")
    return {
        "metadata": f"oss://{bucket}/{dds_data_source.get('metadata')}",
        "discovery": f"oss://{bucket}/{dds_data_source.get('discovery')}",
        "calibration": f"oss://{bucket}/{dds_data_source.get('calibration')}",
        "dds_paths": [f"oss://{bucket}/{item}" for item in dds_data_source.get("dds_files", [])]
    }    


def get_vehicle_from_scenario_config(scenario_config):
    """从场景配置中提取车辆类型"""
    vehicle_name = scenario_config.get("vehicle_name")
    if not vehicle_name:
        raise ValueError("Vehicle Name Not Found in Scenario Config")
    
    vehicle_name_lower = vehicle_name.lower().strip()
    for vehicle_type in VEHICLE_TYPE_2_ID:
        for suffix in vehicle_name_suffixes:
            if f"{vehicle_type.lower()}{suffix}" == vehicle_name_lower:
                return vehicle_type
    
    raise ValueError(f"Vehicle Name Not Match: {vehicle_name_lower}")


def _build_vehicle_info(openloop_scenario_info, context):
    """从场景信息中提取车辆类型并构造目标车型全名"""
    vehicle_type = get_vehicle_from_scenario_config(openloop_scenario_info)
    original_vehicle_name = openloop_scenario_info.get("vehicle_name", "")
    if context.get("target_vehicle") == 'origin':
        target_vehicle_full_name = original_vehicle_name
    else:
        target_vehicle_full_name = original_vehicle_name.replace(vehicle_type, context.get("target_vehicle", ""))
    return vehicle_type, target_vehicle_full_name


def _query_with_both_ids(context):
    """两者都存在，使用原有逻辑：直接查询closeloop"""
    closeloop_scenario_id = context["closeloop_scenario_id"]
    openloop_scenario_id = context["openloop_scenario_id"]

    data = query_scenario(closeloop_scenario_id).get("data")
    if not data:
        raise ValueError(f"{closeloop_scenario_id}: 无法获取场景数据")
    
    closeloop_scenario_info = json.loads(data.get("scenario"))

    event_id = data.get("extra_info", {}).get("event_id")
    if not event_id:
        raise ValueError(f"{closeloop_scenario_id}: event_id为空")
    
    # 获取3DGS模型路径
    threedgs_config = closeloop_scenario_info.get("3dgs_config")
    if not threedgs_config:
        raise ValueError(f"{closeloop_scenario_id}: 未找到3dgs_config字段")
    
    threedgs_model_path = f"oss://{threedgs_config.get('oss_bucket')}/{threedgs_config.get('oss_path1')}"
    
    # 查询openloop场景
    openloop_data = query_scenario(openloop_scenario_id).get("data")
    openloop_scenario_info = json.loads(openloop_data.get("scenario"))
    vehicle_type, target_vehicle_full_name = _build_vehicle_info(openloop_scenario_info, context)
    
    return {
        "closeloop_scenario_id": closeloop_scenario_id,
        "event_id": event_id,
        "threedgs_model_path": threedgs_model_path,
        "openloop_dds_result": parse_oss_path(openloop_scenario_info),
        "openloop_scenario_id": str(openloop_scenario_id),
        "vehicle_type": vehicle_type,
        "target_vehicle_full_name": target_vehicle_full_name
    }


def _query_with_openloop_only(context):
    """只有openloop，使用新逻辑：通过openloop查event_id，再查closeloop"""
    openloop_scenario_id = context["openloop_scenario_id"]

    data = query_scenario(openloop_scenario_id).get("data")
    if not data:
        raise ValueError(f"{openloop_scenario_id}: 无法获取场景数据")
    
    openloop_scenario_info = json.loads(data.get("scenario"))

    event_id = data.get("extra_info", {}).get("event_id")
    if not event_id:
        raise ValueError(f"{openloop_scenario_id}: event_id为空")
    
    # 根据event_id查询closeloop场景列表
    aio_data_list = query_paginate_aio(event_id, mode='open loop')
    if not aio_data_list:
        raise ValueError(f"{openloop_scenario_id}: 无法查询到对应的closeloop场景")
    
    # 筛选有效的closeloop场景
    valid_aio_data_list = []
    for item in aio_data_list:
        try:
            scenario_info = json.loads(item.get("scenario", "{}"))
            threedgs_config = scenario_info.get("3dgs_config")
            if not threedgs_config:
                continue
            threedgs_model_path_check = f"oss://{threedgs_config.get('oss_bucket')}/{threedgs_config.get('oss_path1')}"
            model_ver = threedgs_model_path_check.split("/")[-2].replace("trained_model_", "").replace("_1347", "")
            if re.match(r"^sim3dgs_v\d{3}[a-zA-Z]?$", model_ver):
                item["_parsed_model_version"] = model_ver
                valid_aio_data_list.append(item)
        except Exception:
            continue
    
    if not valid_aio_data_list:
        raise ValueError(f"{openloop_scenario_id}: 未找到有效的closeloop场景")
    
    # 选择create_time最大的
    aio_data = max(valid_aio_data_list, key=lambda item: item.get("create_time") or "")
    
    closeloop_scenario_info = json.loads(aio_data.get("scenario"))
    closeloop_scenario_id = str(aio_data.get("id"))
    
    threedgs_config = closeloop_scenario_info.get("3dgs_config")
    if not threedgs_config:
        raise ValueError(f"{closeloop_scenario_id}: 未找到3dgs_config字段")
    
    threedgs_model_path = f"oss://{threedgs_config.get('oss_bucket')}/{threedgs_config.get('oss_path1')}"
    
    vehicle_type, target_vehicle_full_name = _build_vehicle_info(openloop_scenario_info, context)
    
    return {
        "closeloop_scenario_id": closeloop_scenario_id,
        "event_id": event_id,
        "threedgs_model_path": threedgs_model_path,
        "openloop_dds_result": parse_oss_path(openloop_scenario_info),
        "openloop_scenario_id": str(openloop_scenario_id),
        "vehicle_type": vehicle_type,
        "target_vehicle_full_name": target_vehicle_full_name
    }


def query_scenario_event(context):
    """查询场景事件信息

    根据context中是否存在closeloop_scenario_id，自动选择查询策略：
    - 两者都存在：直接查询closeloop和openloop
    - 只有openloop：先查openloop获取event_id，再通过event_id查询closeloop
    """
    closeloop_scenario_id = context.get("closeloop_scenario_id")
    openloop_scenario_id = context.get("openloop_scenario_id")

    if not openloop_scenario_id:
        raise ValueError("未找到openloop_scenario_id")

    if closeloop_scenario_id and openloop_scenario_id:
        return _query_with_both_ids(context)
    else:
        return _query_with_openloop_only(context)
