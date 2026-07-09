from dynamic_agent_vehicle import DynamicAgentVehicle

# 实车轨迹信息
real_vehicle_trajectory = [
    (0, 0, 0, 0),
    (1, 0, 0, 0),
    (2, 0, 0, 0),
    (3, 0, 0, 0),
    (4, 0, 0, 0),
    (5, 0, 0, 0),
    (6, 0, 0, 0),
    (7, 0, 0, 0),
    (8, 0, 0, 0),
    (9, 0, 0, 0)
]

# 初始化车辆配置
agent_config = {
    'id': 'vehicle_1',
    'initial_x': -2.0,
    'initial_y': 0.0,
    'initial_yaw': 0.0,
    'initial_vx': 1.0,
    'initial_vy': 0.0,
    'target_speed': 2.0,
    'max_lateral_acc': 1.0,
    'max_lateral_speed': 3.0,
    'vehicle_length': 5.0
}

# 创建车辆实例
vehicle = DynamicAgentVehicle(agent_config, real_vehicle_trajectory)
vehicle.init()

# 模拟几帧数据
for i in range(len(real_vehicle_trajectory)):
    current_time = i * 1e9  # 假设每帧间隔 1 秒
    vehicle.run_one_step(current_time)
    print(f"Frame {i}: x={vehicle.pose2d['x']}, y={vehicle.pose2d['y']}, yaw={vehicle.pose2d['yaw']}")

# 尝试换道
if vehicle.change_lane(target_lane_index=1, duration=2.0):
    print("Lane change started.")
    for i in range(10):
        current_time = (i + len(real_vehicle_trajectory)) * 1e9
        vehicle.run_one_step(current_time)
        print(f"Frame {i + len(real_vehicle_trajectory)}: x={vehicle.pose2d['x']}, y={vehicle.pose2d['y']}, yaw={vehicle.pose2d['yaw']}")