import json
import sys
import yaml
import argparse
import os
import numpy as np
import pandas as pd
current_dir = os.path.dirname(os.path.abspath(__file__))
agents_dir = os.path.join(current_dir, 'agents')
# 将路径添加到系统路径
sys.path.append(agents_dir)
from agent_manager import AgentManager
from ego_state import EgoState
from result_collector import ResultCollector

class AgentService:
    def __init__(self, config, config_sim_path):
        self.init_finish = False
        
        self.config_sim_path = config_sim_path
        self.ego_positions = []  # 存储自车位置
        self.ego_rotations = []  # 存储自车旋转角度
        self.real_vehicle_trajectory = []  # 存储实车轨迹 (x, y, z, yaw)
        self.anchor_matrix = np.eye(4)  # 锚点变换矩阵
        self.config_sim_data = self.__load_config_sim()
        self.__parse_ego_poses()
        self.frame_count = len(self.config_sim_data['results']['timestamps'])
        self.timestamps = self.config_sim_data['results']['timestamps']

        if len(self.timestamps) != len(self.ego_positions) or len(self.timestamps) != len(self.ego_rotations):
            print("错误: 时间戳数量与自车位置或旋转角度数量不匹配")
            exit(1)

        self.agent_manager = AgentManager()
        self.agent_manager.create_agents(config)
        self.agent_manager.create_actions(config)

        self.init_finish = True

    def on_step(self, current_time):
        self.agent_manager.on_ego_updated(current_time)

    # def create_sensor_fusion_output_info(self, sensor_fusion_input, sensor_fusion_output):
    #     self.agent_manager.create_sensor_fusion_output_info(sensor_fusion_input, sensor_fusion_output)

    # def process_local_info(self, localization_info):
    #     self.agent_manager.on_ego_updated(localization_info)

    def process_planning_debug_info(self, planning_debug_info):
        pass

    def __load_config_sim(self):
        """加载YAML配置文件"""
        try:
            with open(self.config_sim_path, 'r') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            print(f"错误: 文件 {self.config_sim_path} 未找到")
            exit(1)
        except yaml.YAMLError as e:
            print(f"错误: 解析YAML文件时出错: {e}")
            exit(1)

    def __parse_ego_poses(self):
        """解析自车的位姿数据，并应用锚点变换"""
        if 'ego_frame_poses' not in self.config_sim_data['results']:
            print("警告: YAML文件中未找到自车轨迹数据(ego_frame_poses)")
            return

        ego_poses = self.config_sim_data['results']['ego_frame_poses']
        if not ego_poses:
            print("警告: 自车轨迹数据(ego_frame_poses)为空")
            return
        for pose_matrix in ego_poses:
            # 从YAML数据构建4x4变换矩阵
            ego_matrix = np.array(pose_matrix)
            
            # 应用锚点变换：全局坐标 = 锚点变换 × 自车局部坐标
            global_matrix = np.dot(self.anchor_matrix, ego_matrix)
            
            # 提取平移向量（第四列的前三个元素）
            translation = [global_matrix[0, 3], global_matrix[1, 3], global_matrix[2, 3]]
            self.ego_positions.append(translation)
            
            # 提取旋转矩阵（前3x3子矩阵）
            rotation_matrix = global_matrix[:3, :3]
            
            # 计算偏航角(yaw) - 假设主要绕z轴旋转
            yaw = np.arctan2(rotation_matrix[1, 0], rotation_matrix[0, 0])
            self.ego_rotations.append(yaw)

            self.real_vehicle_trajectory.append((translation[0], translation[1], translation[2], yaw))
        print(f"解析完成: {len(self.ego_positions)} 个自车位置， {len(self.ego_rotations)} 个自车旋转角度， {len(self.real_vehicle_trajectory)} 个实车轨迹点")

def read_config(file_path):
    with open(file_path, 'r') as f:
        return json.load(f)

def read_csv_config(file_path):
    try:
        df = pd.read_csv(file_path, encoding='utf-8')
    except UnicodeDecodeError:
        df = pd.read_csv(file_path, encoding='utf-16')
    return df

def _merge_dynamic_dataset_into_global(dynamic_dataset_config):
    """将 dynamic_dataset_config (DataFrame) 合并到全局 DYNAMIC_OBJECTS_CONFIGS，
    使 Agent 初始化时能通过 data_uid 查到正确的尺寸。"""
    from configs.config import DYNAMIC_OBJECTS_CONFIGS
    if dynamic_dataset_config is None:
        return
    for _, row in dynamic_dataset_config.iterrows():
        uid_str = str(int(row['id']))
        if uid_str not in DYNAMIC_OBJECTS_CONFIGS:
            DYNAMIC_OBJECTS_CONFIGS[uid_str] = {
                'obj_name': str(row.get('obj_name', '')).strip(),
                'obj_path': str(row.get('obj_path', '')).strip(),
                'length': float(row.get('length', 4.5)),
                'width': float(row.get('width', 1.7)),
                'height': float(row.get('height', 2.0)),
                'config_sim_type': str(row.get('config_sim_type', 'car')).strip(),
            }

def generate_new_config(agent_config_path, config_sim_path, new_config_sim_path, dynamic_dataset_config_path=None):
    # config = read_config('agent_service_config.json')
    config = read_config(agent_config_path)
    dynamic_dataset_config = None
    if dynamic_dataset_config_path is not None and os.path.exists(dynamic_dataset_config_path):
        dynamic_dataset_config = read_csv_config(dynamic_dataset_config_path)
    _merge_dynamic_dataset_into_global(dynamic_dataset_config)
    agent_service = AgentService(config, config_sim_path)

    collector = ResultCollector()
    collector.set_config_data(agent_service.config_sim_data, config, agent_service.ego_positions, dynamic_dataset_config)

    ego_state = EgoState()
    ego_state.load_ego_config(agent_service.ego_positions, agent_service.ego_rotations, agent_service.timestamps, agent_service.real_vehicle_trajectory)

    while not agent_service.init_finish:
        print("Waiting for agent service to finish initialization...")
        # 这里可以添加适当的等待逻辑，例如 sleep
        import time
        time.sleep(1)

    for timestamp in agent_service.timestamps:
        agent_service.on_step(float(timestamp))
        ego_state.update_index()

    collector.output_result(new_config_sim_path)

    collector.__clear__()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='轨迹数据可视化工具')
    parser.add_argument('--agent_config_path', type=str, help='agent_config配置文件路径')
    parser.add_argument('--config_sim_path', type=str, help='源config_sim配置文件路径')
    parser.add_argument('--new_config_sim_path', type=str, help='新config_sim配置文件路径')
    parser.add_argument('--dynamic_dataset_config_path', type=str, default=None, help='动态数据集配置文件路径（可选）')

    args = parser.parse_args()
    generate_new_config(args.agent_config_path, args.config_sim_path, args.new_config_sim_path, args.dynamic_dataset_config_path)