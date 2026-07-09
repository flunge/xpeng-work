import numpy as np
from typing import Dict, List, Any, Tuple, Optional
from threading import local

# 线程局部存储，用于隔离不同线程的单例实例
_thread_local = local()

class EgoState:
    _instance = None

    def __new__(cls):
        # 每个线程维护自己的实例
        if not hasattr(_thread_local, 'ego_state_instance'):
            _thread_local.ego_state_instance = super().__new__(cls)
            _thread_local.ego_state_instance.ego_positions = []  # 存储自车位置
            _thread_local.ego_state_instance.ego_rotations = []  # 存储自车旋转角度
            _thread_local.ego_state_instance.timestamps = []
            _thread_local.ego_state_instance.real_vehicle_trajectory = []
            _thread_local.ego_state_instance.current_index = 0
        return _thread_local.ego_state_instance
        
    def load_ego_config(self, ego_positions, ego_rotations, timestamps, real_vehicle_trajectory):
        if len(ego_positions) != len(ego_rotations) or len(ego_positions) != len(timestamps):
            print("错误: 时间戳数量与自车位置或旋转角度数量不匹配")
            exit(1)
        self.ego_positions = ego_positions
        self.ego_rotations = ego_rotations
        self.timestamps = timestamps
        self.real_vehicle_trajectory = real_vehicle_trajectory

    def update_index(self):
        self.current_index += 1

    def get_ego_move_total_distance(self):
        """计算从起点到指定index位置的累计行驶距离（基于x,y平面坐标）
        
        Args:
            index: 要计算到的位置索引
            
        Returns:
            float: 累计行驶距离（单位与坐标相同）
        """
        if self.current_index < 0 or self.current_index >= len(self.ego_positions):
            print("[EgoState] get_ego_move_total_distance index error", self.current_index, len(self.ego_positions))
            return 0.0
        
        if self.current_index == 0:
            return 0.0  # 起点距离为0
        
        total_distance = 0.0
        for i in range(1, self.current_index + 1):
            # 获取前一个点和当前点的x,y坐标
            prev_x, prev_y, _ = self.ego_positions[i-1]
            curr_x, curr_y, _ = self.ego_positions[i]
            
            # 计算两点之间的欧氏距离
            distance = ((curr_x - prev_x)**2 + (curr_y - prev_y)**2)**0.5
            total_distance += distance
        
        return total_distance
    
    # 获取最近的自车位置
    def get_nearest_ego_position(self, position: Tuple[float, float]) -> Tuple[float, float, float]:
        """获取最近的自车位置"""
        if not self.ego_positions:
            return (0.0, 0.0, 0.0)
        
        # 计算与所有自车位置的距离
        distances = [np.linalg.norm(np.array(pos[:2]) - np.array(position)) for pos in self.ego_positions]
        nearest_index = np.argmin(distances)
        return self.ego_positions[nearest_index][:3], self.ego_rotations[nearest_index]
    
    def get_current_ego_position(self):
        return self.ego_positions[self.current_index][:3]



    