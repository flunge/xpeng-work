import csv
import os
current_dir = os.path.dirname(os.path.abspath(__file__))

def load_clip_configs(csv_path):
    """从CSV文件读取配置并转换为原有字典格式"""
    configs = {}
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            clip_id = row['clip_id'].strip()
            # 构建单个配置项（过滤空值）
            config_item = {
                'folder': row['folder'].strip(),
                'new_object': row['new_object'].strip(),
                'is_valid': row['is_valid'].strip().lower() == 'true',
            }
            # 处理可选的agent_service_config字段
            if row['agent_service_config'].strip():
                config_item['agent_service_config'] = row['agent_service_config'].strip()
            
            # 按clip_id分组（支持一个clip_id对应多个配置）
            if clip_id not in configs:
                configs[clip_id] = []
            configs[clip_id].append(config_item)
    return configs

def load_dynamic_obj_configs(csv_path):
    """从CSV文件读取动态对象配置"""
    dynamic_configs = {}
    with open(csv_path, 'r', encoding='utf-16') as f:
        reader = csv.DictReader(f)
        for row in reader:
            id = row['id'].strip()
            obj_name = row['obj_name'].strip()
            obj_path = row['obj_path'].strip()
            length = float(row['length'])
            width = float(row['width'])
            height = float(row['height'])
            type = row['config_sim_type'].strip()
            if id not in dynamic_configs:
                dynamic_configs[id] = {
                    'obj_name': obj_name,
                    'obj_path': obj_path,
                    'length': length,
                    'width': width,
                    'height': height,
                    'config_sim_type': type
                }
    return dynamic_configs

def load_agent_service_configs(csv_path):
    """从CSV文件读取agent_service配置"""
    agent_service_configs = {}
    with open(csv_path, 'r', encoding='utf-16') as f:
        reader = csv.DictReader(f)
        for row in reader:
            controller_name = row['controller_name'].strip()
            controller_config_name = row['controller_config_name'].strip()
            if controller_name not in agent_service_configs:
                agent_service_configs[controller_name] = {
                    'controller_config_name': controller_config_name,
                    'controller_config_path': os.path.join(current_dir, 'agent_service_configs', controller_config_name),
                }
    return agent_service_configs

# 从CSV加载配置
CLIP_3DGS_CONFIGS = load_clip_configs(os.path.join(current_dir, 'clips_config.csv'))
DYNAMIC_OBJECTS_CONFIGS = load_dynamic_obj_configs(os.path.join(current_dir, 'dynamic_obj_configs.csv'))
AGENT_SERVICE_CONFIGS = load_agent_service_configs(os.path.join(current_dir, 'agent_service_configs.csv'))

INCLUDE_DIRS = [
    "autolabel_json",
    "configs",
    "images",
    "point_cloud",
    "surfel_ground",
    "trained_model",
]

INCLUDE_FILES = [
    "LocalPoseTopic.json",
    "anchorpose.json",
    "annotation_for_train.json",
    "calib.json",
    "calib_origin.json",
    "cameras.json",
    "cfg_args",
    "ground_mask.npy",
    "input_background.ply",
    "input_ground.ply",
    "localpose.json",
    "metadata.json",
    "sky_latlong.png",
    "transform.json",
]
