import os
import shutil
import threading
import json
import yaml
import tarfile
import tempfile
import csv
from datetime import datetime
from queue import Queue
from downclip import download_file_from_oss2
from agent_service_main import AgentService, read_config, generate_new_config
from upload_model import create_temporary_structure, create_tgz_archive, upload_to_oss
from configs.config import CLIP_3DGS_CONFIGS, DYNAMIC_OBJECTS_CONFIGS, AGENT_SERVICE_CONFIGS, INCLUDE_DIRS, INCLUDE_FILES

current_dir = os.path.dirname(os.path.abspath(__file__))

RESULT_FILE_PATH = f"{current_dir}/pipeline_result.csv"

# 线程数量可配置
THREAD_COUNT = 5

def load_config_sim(config_sim_path):
    """加载YAML配置文件"""
    try:
        with open(config_sim_path, 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print(f"错误: 文件 {config_sim_path} 未找到")
        exit(1)
    except yaml.YAMLError as e:
        print(f"错误: 解析YAML文件时出错: {e}")
        exit(1)

# 下载clip数据
def download_clip(clip_id, config_params, local_root):
    data_type = "3dgs"
    object_root = "sim_engine/ips_output_clip_depth/"
    folder = config_params["folder"]
    local_file_path = os.path.join(local_root, "3dgs_model.tgz")
    object_key = os.path.join(object_root, f"{clip_id}/{folder}/3dgs_model.tgz")
    download_file_from_oss2(local_file_path, object_key)
    os.system(f"cd {local_root}; tar xf {local_file_path}")
    # 备份configs
    configs_path = os.path.join(local_root, "model1", "configs")
    bak_configs_path = os.path.join(local_root, "model1", "configs_bak")
    os.system(f"cp -r {configs_path} {bak_configs_path}")
    # 添加object
    controller_name = config_params.get("agent_service_config", None)
    if controller_name is None:
        print(f"警告: clip_id {clip_id} 中未配置 agent_service_config")
        return
    agent_service_config_path = AGENT_SERVICE_CONFIGS.get(controller_name, {}).get("controller_config_path", None)
    if agent_service_config_path is None:
        print(f"警告: clip_id {clip_id} 中的 agent_service_config_path {controller_name} 未找到")
        return
    agent_service_config = read_config(agent_service_config_path)
    config_sim_path = os.path.join(configs_path, "config_sim.yaml")
    config_sim_data = load_config_sim(config_sim_path)
    iterations_ground = config_sim_data['train_xpeng']['iterations_ground']
    point_cloud_path = os.path.join(local_root, "model1", "point_cloud", f"iteration_{iterations_ground}")
    for object in agent_service_config.get("objects", []):
        agent_config = object.get("agent_configs", {})
        agent_uid = str(agent_config.get("agent_attributes", {}).get("data_uid", None))
        gid = object.get("id", None)
        if agent_uid is None or gid is None:
            print(f"警告: clip_id {clip_id} 中的 data_uid/id 未找到")
            return
        new_obj_path = DYNAMIC_OBJECTS_CONFIGS.get(agent_uid, {}).get('obj_path', None)        
        file_name = os.path.basename(new_obj_path)
        file_ext = os.path.splitext(file_name)[1]
        dest_path = os.path.join(point_cloud_path, file_name)
        new_file_name = f"model_obj_{int(gid):09d}{file_ext}"
        new_file_path = os.path.join(point_cloud_path, new_file_name)
        os.system(f"cp {new_obj_path} {new_file_path}")


# 用agent_service_main修改clip数据中的config_sim.yaml文件
def modify_config(clip_id, config_params, local_root):

    config_sim_path = os.path.join(local_root, "model1", "configs_bak", "config_sim.yaml")

    # 运行agent_service_main.generate_new_config
    new_config_sim_path = os.path.join(local_root, "model1", "configs")
    controller_name = config_params.get("agent_service_config", None)
    if controller_name is None:
        print(f"警告: clip_id {clip_id} 中未配置 agent_service_config")
        return
    agent_service_config = AGENT_SERVICE_CONFIGS.get(controller_name, {}).get("controller_config_path", None)
    if agent_service_config is None:
        print(f"警告: clip_id {clip_id} 中的 agent_service_config {controller_name} 未找到")
        return

    # 判断输出目录是否存在
    if not os.path.exists(new_config_sim_path):
        os.makedirs(new_config_sim_path)
    output_path = os.path.join(new_config_sim_path, "config_sim.yaml")
    generate_new_config(agent_service_config, config_sim_path, output_path)

# 将修改后的clip数据通过upload_model重新打包上传至oss，并保存每一份上传数据的路径
def upload_clip(clip_id, local_root, config_params):
    TIMESTAMP = datetime.now().strftime("%Y%m%d%H%M")
    SOURCE_DIR = os.path.join(local_root, "model1")
    TGZ_NAME = "3dgs_model.tgz"
    OSS_PATH = f"sim_engine/artificially_created_scenes/{clip_id}/trained_model_{TIMESTAMP}/3dgs_model.tgz"
    CONFIG_LOCAL_PATH = os.path.join(SOURCE_DIR, "configs", "config_sim.yaml")
    CONFIG_OSS_PATH = f"sim_engine/artificially_created_scenes/{clip_id}/trained_model_{TIMESTAMP}/config_sim.yaml"

    controller_name = config_params.get("agent_service_config", None)
    if controller_name is None:
        print(f"警告: clip_id {clip_id} 中未配置 agent_service_config")
        return
    agent_service_config_path = AGENT_SERVICE_CONFIGS.get(controller_name, {}).get("controller_config_path", None)

    temp_dir = None
    tar_temp_dir = None
    try:
        temp_dir = create_temporary_structure(SOURCE_DIR, INCLUDE_DIRS, INCLUDE_FILES)
        tar_temp_dir = tempfile.mkdtemp()
        print("tar_temp_dir: ", tar_temp_dir)
        model_path = os.path.join(tar_temp_dir, TGZ_NAME)
        create_tgz_archive(temp_dir, model_path)
        uploaded = upload_to_oss(model_path, OSS_PATH)
        config_uploaded = upload_to_oss(CONFIG_LOCAL_PATH, CONFIG_OSS_PATH)
        if agent_service_config_path is not None:
            agent_service_config_name = os.path.basename(agent_service_config_path)
            agent_service_config_oss_path = f"sim_engine/artificially_created_scenes/{clip_id}/trained_model_{TIMESTAMP}/{agent_service_config_name}"
            agent_service_config_uploaded = upload_to_oss(agent_service_config_path, agent_service_config_oss_path)
            if not agent_service_config_uploaded:
                print("upload agent_service_config failed， clip_id: ", clip_id)
        if not config_uploaded:
            print("upload config_sim.yaml failed， clip_id: ", clip_id)
        if not uploaded:
            return "upload_clip error"
        return OSS_PATH
    finally:
        # 确保临时目录被删除，即使中间出现错误
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
            print(f"已清理临时结构目录: {temp_dir}")
        if tar_temp_dir and os.path.exists(tar_temp_dir):
            shutil.rmtree(tar_temp_dir, ignore_errors=True)
            print(f"已清理压缩临时目录: {tar_temp_dir}")

# 处理单个clip_id和配置
def process_clip_task(clip_id, config_params):
    local_root = f"/workspace/duanzx@xiaopeng.com/3dgs_data/online_data/3dgs/{clip_id}"
    os.makedirs(local_root, exist_ok=True)

    print("****start download_clip: ", clip_id)
    download_clip(clip_id, config_params, local_root)

    print("****start modify_config: ", clip_id)
    modify_config(clip_id, config_params, local_root)
    
    print("****start upload_clip: ", clip_id)
    oss_path = "None"
    oss_path = upload_clip(clip_id, local_root, config_params)
    # 写入指定文件（使用追加模式，确保多线程安全）
    # 准备日志内容
    log_message = f"Uploaded {clip_id} with config {config_params} to {oss_path}\n"
    
    # 打印到控制台
    print(log_message.strip())
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    file_exists = os.path.exists(RESULT_FILE_PATH)
    with open(RESULT_FILE_PATH, "a", encoding="utf-8", newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'timestamp', 'clip_id', 'config_params', 'oss_path'
        ])
        if not file_exists or os.path.getsize(RESULT_FILE_PATH) == 0:
            writer.writeheader()
        writer.writerow({
            'timestamp': current_time,
            'clip_id': clip_id,
            'config_params': json.dumps(config_params),  # 将字典转为JSON字符串
            'oss_path': oss_path,
        })
    return oss_path

# 线程工作函数
def worker(queue):
    while True:
        task = queue.get()
        if task is None:
            break
        clip_id, config_params = task
        process_clip_task(clip_id, config_params)
        queue.task_done()

def main():
    task_queue = Queue()
    threads = []

    # 计算实际需要的线程数（不超过任务数）
    total_tasks = 0
    for config_list in CLIP_3DGS_CONFIGS.values():
        for config in config_list:
            if config.get('is_valid', False):
                total_tasks += 1
    actual_thread_count = min(THREAD_COUNT, total_tasks) if total_tasks > 0 else 1

    # 创建线程
    for _ in range(actual_thread_count):
        t = threading.Thread(target=worker, args=(task_queue,))
        t.daemon = True  # 设置为守护线程，主程序退出时自动结束
        t.start()
        threads.append(t)

    # 添加任务到队列
    for clip_id, config_list in CLIP_3DGS_CONFIGS.items():
        for config_params in config_list:
            if not config_params.get('is_valid', False):
                continue
            task_queue.put((clip_id, config_params))

    # 等待所有任务完成
    task_queue.join()

    # 停止线程
    for _ in range(actual_thread_count):
        task_queue.put(None)
    
    # 等待所有线程结束
    for t in threads:
        t.join(timeout=5.0)  # 设置超时，防止无限等待

if __name__ == "__main__":
    main()