
import subprocess
import os
import shutil
import glob

import sys

_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
_ucp_dir = os.path.join(_repo_root, "pipeline", "ucp")
if _ucp_dir not in sys.path:
    sys.path.insert(0, _ucp_dir)
from download_file_from_oss2 import download_file_from_oss2


def parse_oss_path(oss_path):
    """
    解析OSS路径，返回bucket名称和object_key
    
    Args:
        oss_path (str): OSS路径，格式如 oss://bucket_name/object_key
        
    Returns:
        tuple: (bucket_name, object_key)
    """
    if oss_path.startswith("oss://"):
        oss_path = oss_path[6:]  # 移除 "oss://" 前缀
    
    parts = oss_path.split('/', 1)  # 分割为两部分
    bucket_name = parts[0]
    object_key = parts[1] if len(parts) > 1 else ""
    
    return bucket_name, object_key

def copy_calibration_file(target_vehicle: str, dds_path: str, output_dds_path: str, same_vehicle: bool, expected_calibration: str):
    """
    复制校准文件到输出目录
    
    Args:
        target_vehicle (str): 目标车辆类型
        dds_path (str): DDS数据路径
        output_dds_path (str): 输出DDS路径
        same_vehicle (bool): 是否是同车型
        expected_calibration (str): 期望的calibration OSS路径，用于获取文件名
    """
    calib_name = os.path.basename(expected_calibration)
    
    source_path = os.path.join(dds_path, calib_name) if same_vehicle else \
                  f"/workspace/group_share/adc-sim/users/multi_vehicle/calibs/{target_vehicle}/{calib_name}"
    target_path = os.path.join(output_dds_path, calib_name)
    
    print(f"    复制校准文件: {source_path} -> {target_path}")
    
    if os.path.isfile(source_path):
        shutil.copy(source_path, target_path)
    elif os.path.isdir(source_path):
        if os.path.exists(target_path):
            shutil.rmtree(target_path)
        shutil.copytree(source_path, target_path)
    else:
        raise FileNotFoundError(f"校准源文件不存在: {source_path}")
    
    print(f"    校准文件复制成功")


def compress_recordings(output_dds_path: str, expected_dds_paths: list):
    """
    根据期望的文件格式决定是否对recording文件进行lz4压缩
    
    Args:
        output_dds_path (str): 输出DDS路径
        expected_dds_paths (list): openloop_dds_result中的dds_paths列表，用于判断期望的格式
    """
    expected_filenames = [os.path.basename(p) for p in expected_dds_paths]
    
    recording_files = glob.glob(os.path.join(output_dds_path, "recording*"))
    
    for file_path in recording_files:
        if os.path.isfile(file_path) and not file_path.endswith('.lz4'):
            basename = os.path.basename(file_path)
            
            # 检查期望的文件名是否是 .lz4 格式
            expected_lz4 = basename + '.lz4'
            
            if expected_lz4 not in expected_filenames:
                # 期望的是原始格式（非lz4），跳过压缩
                print(f"    跳过压缩（期望原始格式）: {basename}")
                continue
            
            # 期望的是lz4格式，或者没有指定期望格式（使用旧逻辑）
            compressed_file = file_path + '.lz4'
            print(f"    压缩文件: {file_path} -> {compressed_file}")
            
            try:
                cmd = ['lz4', '-f', file_path, compressed_file]
                result = subprocess.run(cmd, check=True, capture_output=True, text=True)
                print(f"      压缩完成: {os.path.basename(compressed_file)}")
                os.remove(file_path)
                print(f"      删除原始文件: {os.path.basename(file_path)}")

            except subprocess.CalledProcessError as e:
                print(f"      压缩失败: {e}")
            except FileNotFoundError:
                print(f"      错误: lz4命令未找到，请先安装lz4工具")   


def download_file_from_oss(oss_path: str, local_path: str, need_decompress: bool = False, is_dir: bool = False) -> bool:
    """
    通用OSS文件/文件夹下载函数
    
    Args:
        oss_path (str): OSS路径，格式如 oss://bucket_name/object_key
        local_path (str): 本地保存路径
        need_decompress (bool): 是否需要解压lz4文件，默认False
        
    Returns:
        bool: 下载是否成功
    """
    if not oss_path:
        print(f"    警告: OSS路径为空，跳过下载")
        return False
    
    # 解析OSS路径
    bucket_name, object_key = parse_oss_path(oss_path)
    filename = os.path.basename(oss_path)
    
    if is_dir:
        cmd = f"ossutil64 -e http://oss-cn-wulanchabu-internal.aliyuncs.com -i OSS_ACCESS_KEY_ID_REDACTED -k OSS_ACCESS_KEY_SECRET_REDACTED cp -r 'oss://{bucket_name}/{object_key}' '{local_path}'"
    else:
        cmd = f"ossutil64 -e http://oss-cn-wulanchabu-internal.aliyuncs.com -i OSS_ACCESS_KEY_ID_REDACTED -k OSS_ACCESS_KEY_SECRET_REDACTED cp 'oss://{bucket_name}/{object_key}' '{local_path}'"
    print(f"  下载: {oss_path} -> {local_path}")
    
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"    错误: 下载失败 {oss_path}: {result.stderr}")
        raise Exception(f"下载失败 {oss_path}: {result.stderr}")    
    # 如果需要解压lz4文件
    if need_decompress and local_path.endswith('.lz4'):
        local_dat_file = local_path[:-4]
        print(f"  解压文件: {local_path} -> {local_dat_file}")
        subprocess.run(['lz4', '-d', '-f', local_path, local_dat_file], check=True, capture_output=True)
        print(f"  解压完成: {os.path.basename(local_dat_file)}")
    
    print(f"    下载成功: {filename}")
    return True


def download_and_extract_dds(event_path: str, dds_path: str, task_info: dict):
    """下载并解压dds数据
    
    Args:
        event_path (str): 事件文件夹路径
        dds_path (str): DDS文件夹路径
        task_info (dict): 任务信息，包含event_id和openloop_dds_result
    """
    event_id = task_info.get("event_id")
    
    if not event_id:
        print(f"警告 : 找不到 event_id ，跳过此条目")
        return False
    
    print(f"处理事件 ID: {event_id}")
    
    os.makedirs(event_path, exist_ok=True)
    print(f"  创建文件夹: {event_path}")
    
    # 获取 openloop_dds_result 中的信息
    openloop_dds_result = task_info.get("openloop_dds_result", {})
    
    # 创建 dds 子文件夹
    os.makedirs(dds_path, exist_ok=True)
    print(f"  创建 DDS 文件夹: {dds_path}")

    # 下载 metadata 文件
    metadata_oss_path = openloop_dds_result.get("metadata")
    if metadata_oss_path:
        local_path = os.path.join(dds_path, os.path.basename(metadata_oss_path))
        download_file_from_oss(metadata_oss_path, local_path)
    
    # 下载 discovery 文件
    discovery_oss_path = openloop_dds_result.get("discovery")
    if discovery_oss_path:
        local_path = os.path.join(dds_path, os.path.basename(discovery_oss_path))
        download_file_from_oss(discovery_oss_path, local_path)
    
    # 下载 calibration 文件
    calibration_oss_path = openloop_dds_result.get("calibration")
    if calibration_oss_path:
        local_path = os.path.join(dds_path, os.path.basename(calibration_oss_path))
        if local_path.endswith('.lz4') or local_path.endswith('.tar'):
            download_file_from_oss(calibration_oss_path, local_path)
        else:
            download_file_from_oss(calibration_oss_path, dds_path, is_dir = True) 
        
    
    # 下载 dds_paths 中的所有文件（需要解压）
    dds_paths = openloop_dds_result.get("dds_paths", [])
    for dds_path_item in dds_paths:
        local_path = os.path.join(dds_path, os.path.basename(dds_path_item))
        download_file_from_oss(dds_path_item, local_path, need_decompress=True)
    
    print(f"  完成事件 ID {event_id} 的文件下载")
    return True                