import yaml
import os
import time
import numpy as np
from typing import Dict, List, Any, Tuple, Optional
from threading import Lock
from threading import local
from configs.config import DYNAMIC_OBJECTS_CONFIGS

# 线程局部存储，用于隔离不同线程的单例实例
_thread_local = local()

FIXED_Z = 1

class ResultCollector:
    _instance = None
    _lock = Lock()  # 用于线程安全的锁

    def __new__(cls):
        # 每个线程维护自己的实例
        if not hasattr(_thread_local, 'result_collector_instance'):
            _thread_local.result_collector_instance = super().__new__(cls)
            _thread_local.result_collector_instance._initialized = False
        return _thread_local.result_collector_instance

    def __init__(self):
        if not self._initialized:
            self._results = {}  # 存储所有结果
            self._initialized = True
            self.data = {}  # 存储YAML数据
            self.agent_service_config = {}
            self.keep_original_objects = False
            self.ego_positions = []  # 存储自车位置
            self.dynamic_dataset_config = {}

    def __clear__(self):
        """清除所有存储的结果"""
        with self._lock:
            self._results.clear()
            self.data = {}
            self.agent_service_config = {}
            self.keep_original_objects = False
            self.ego_positions = []
            self.dynamic_dataset_config = {}


    def set_config_data(self, data, agent_service_config, ego_positions, dynamic_dataset_config):
        """设置配置数据和帧数据"""
        with self._lock:
            self.data = data
            self.agent_service_config = agent_service_config
            self.ego_positions = ego_positions
            self.keep_original_objects = self.agent_service_config.get('keep_original_objects', False)
            self.dynamic_dataset_config = dynamic_dataset_config

    def add_result(self, gid, x, y, z, yaw):
        """添加中间结果"""
        with self._lock:
            if gid not in self._results:
                self._results[gid] = []
            self._results[gid].append({'x': x, 'y': y, 'z': z, 'yaw': yaw})

    # 获取最近的自车位置
    def _get_nearest_ego_position(self, position: Tuple[float, float]) -> Tuple[float, float, float]:
        """获取最近的自车位置"""
        if not self.ego_positions:
            return (0.0, 0.0, 0.0)
        
        # 计算与所有自车位置的距离
        distances = [np.linalg.norm(np.array(pos[:2]) - np.array(position)) for pos in self.ego_positions]
        nearest_index = np.argmin(distances)
        return self.ego_positions[nearest_index][:3]

    def get_obj_config(self, data_uid: int):
        import pandas as pd
        if self.dynamic_dataset_config is not None and isinstance(self.dynamic_dataset_config, pd.DataFrame):
            for _, row in self.dynamic_dataset_config.iterrows():
                if int(row['id']) == int(data_uid):
                    return {
                        'length': float(row.get('length', 4.5)),
                        'width': float(row.get('width', 1.7)),
                        'height': float(row.get('height', 2.0)),
                        'config_sim_type': str(row.get('config_sim_type', 'car')).strip(),
                        'obj_path': str(row.get('obj_path', '')).strip(),
                        'obj_name': str(row.get('obj_name', '')).strip(),
                    }
        obj_cfg = DYNAMIC_OBJECTS_CONFIGS.get(str(data_uid), {})
        return obj_cfg

    def save_frame_data(self, update_gid: int, add_object: bool, new_config_path: str) -> None:
        """将帧数据保存为YAML文件"""
        output_path = new_config_path
        results = self._results.get(update_gid, [])
        if not results:
            print("没有可用的帧数据")
            return
        
        if not self.data:
            print("没有有效的YAML数据，请先加载配置文件")
            return
        
        new_data = self.data.copy()

        update_obj_gid = update_gid
        
        # 获取对象的size
        agent_configs_map = {}
        for object in self.agent_service_config.get("objects", []):
            gid = object.get("id", None)
            agent_configs_map[str(gid)] = object.get("agent_configs", {})

        if 'model' in new_data and 'gaussian' in new_data['model']:
            new_data['model']['gaussian']['fourier_scale'] = 0.0
        
        frames = new_data['results']['annotations']['frames']

        for i, frame in enumerate(frames):
            new_frame_data = results[i]
            new_obj = {}
            data_uid = agent_configs_map.get(str(update_obj_gid), {}).get("agent_attributes", {}).get("data_uid", None)
            if data_uid is None:
                print("save_frame_data: agent_configs_map data_uid is None")
                continue
            obj_cfg = self.get_obj_config(data_uid)
            length = obj_cfg.get("length", 4.5)
            width = obj_cfg.get("width", 1.7)
            height = obj_cfg.get("height", 2.0)
            nearest_ego_position = self._get_nearest_ego_position([float(new_frame_data['x']), float(new_frame_data['y'])])
            new_obj['translation'] = [float(new_frame_data['x']), float(new_frame_data['y']), float(nearest_ego_position[2] + height/2)]
            # 修改 rotation
            yaw = new_frame_data['yaw']
            # 转换为四元数
            qw = float(np.cos(yaw/2))
            qx = 0.0
            qy = 0.0
            qz = float(np.sin(yaw/2))
            new_obj['rotation'] = [qw, qx, qy, qz]
            # 这里需要根据实际情况调整对象的属性
            type = obj_cfg.get("config_sim_type", "car")
            new_obj['size'] = [float(length), float(width), float(height)]
            new_obj['is_moving'] = True  # 假设所有对象都是移动的
            new_obj['gid'] = update_obj_gid  # 确保GID一致
            new_obj['type'] = type

            if frame.get('objects', None) is None:
                frame['objects'] = []
            objects = []
            for object in frame['objects']:
                if object['gid'] == update_obj_gid:
                    continue
                objects.append(object)
            frame['objects'] = objects
            frame['objects'].append(new_obj)
        
        # 保存到YAML文件
        try:
            with open(output_path, 'w') as f:
                yaml.dump(
                    new_data,
                    f,
                    default_flow_style=False,
                    indent=2,
                    sort_keys=False,
                    allow_unicode=True,
                )
            print(f"成功保存{len(results)}帧数据到 {output_path}")
        except Exception as e:
            print(f"保存文件时出错: {e}")

    def save_frame_data_with_new_config(self, update_gid: int, add_object: bool, new_config_path: str) -> None:
        """创建一个全新的 YAML 文件，仅包含指定对象在各帧的位姿和属性（不保留原始 self.data 内容）"""
        results = self._results.get(update_gid, [])
        if not results:
            print("没有可用的帧数据")
            return

        # 获取 agent_configs 映射
        agent_configs_map = {}
        for obj in self.agent_service_config.get("objects", []):
            gid = obj.get("id", None)
            if gid is not None:
                agent_configs_map[str(gid)] = obj.get("agent_configs", {})

        # 获取对象属性（尺寸、类型等）
        data_uid = agent_configs_map.get(str(update_gid), {}).get("agent_attributes", {}).get("data_uid", None)
        if data_uid is None:
            print("save_frame_data: agent_configs_map data_uid is None")
            return

        obj_cfg = self.get_obj_config(data_uid)
        length = obj_cfg.get("length", 4.5)
        width = obj_cfg.get("width", 1.7)
        height = obj_cfg.get("height", 2.0)
        obj_type = obj_cfg.get("config_sim_type", "car")

        # 构建全新的数据结构
        new_data = {
            "results": {
                "annotations": {
                    "frames": []
                }
            }
        }

        # 填充每一帧
        for i, frame_data in enumerate(results):
            nearest_ego_position = self._get_nearest_ego_position([
                float(frame_data['x']),
                float(frame_data['y'])
            ])
            translation = [
                float(frame_data['x']),
                float(frame_data['y']),
                float(nearest_ego_position[2] + height / 2)
            ]

            yaw = frame_data['yaw']
            qw = float(np.cos(yaw / 2))
            qz = float(np.sin(yaw / 2))
            rotation = [qw, 0.0, 0.0, qz]  # [w, x, y, z]

            new_obj = {
                "translation": translation,
                "rotation": rotation,
                "size": [float(length), float(width), float(height)],
                "is_moving": True,
                "gid": update_gid,
                "type": obj_type
            }

            new_frame = {
                "objects": [new_obj]
            }
            new_data["results"]["annotations"]["frames"].append(new_frame)

        # 保存为 YAML
        try:
            with open(new_config_path, 'w') as f:
                yaml.dump(
                    new_data,
                    f,
                    default_flow_style=False,
                    indent=2,
                    sort_keys=False,
                    allow_unicode=True,
                )
            print(f"成功保存 {len(results)} 帧数据（仅对象 gid={update_gid}）到 {new_config_path}")
        except Exception as e:
            print(f"保存文件时出错: {e}")

    def output_result(self, new_config_path):
        """输出指定ID的结果"""
        with self._lock:
            if not self.keep_original_objects:
                print("keep_original_objects is: ", self.keep_original_objects)
                frames = self.data['results']['annotations']['frames']
                for i, frame in enumerate(frames):
                    frame['objects'] = []
            for gid, results in self._results.items():
                print(f"ID: {gid}")
                self.save_frame_data_with_new_config(gid, True, new_config_path)
                visualize_new_config_path = new_config_path.replace(".yaml", "_vis.yaml")
                self.save_frame_data(gid, False, visualize_new_config_path)


# 使用示例
if __name__ == "__main__":
    # 获取单例实例
    collector1 = ResultCollector()
    collector2 = ResultCollector()
    
    print(collector1 is collector2)  # 输出 True，确认是同一个实例

    # 添加一些数据
    collector1.add_result("start_time", "2023-01-01 10:00:00")
    collector1.add_result("initial_config", {"param1": 1.0, "param2": "test"})
    
    # 批量添加数据
    collector2.update_results({
        "step1_result": 42,
        "intermediate_values": [1.2, 3.4, 5.6]
    })

    # 保存到文件
    collector1.save_to_yaml("results.yaml")
    
    # 查看当前结果
    print(collector1.get_results())