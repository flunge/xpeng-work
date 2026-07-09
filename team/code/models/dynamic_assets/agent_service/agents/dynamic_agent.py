import math
from agent import Agent
from ego_state import EgoState

kAccSpeedEnginePowerParmSedan = 7.4

class VehicleLatState:
    KeepLane = 0
    ChangeLane = 1

class DynamicAgent(Agent):
    def __init__(self, agent_config):
        super().__init__(agent_config)
        self.signal_light = 0  # 假设UNKNOWN_SIGNAL为0
        self.brake_light = 0  # 假设UNKNOWN_LIGHT为0
        self.motion_status = 0  # 假设UNKNOWN_MOTION为0
        self.track_straddle_status = 0  # 假设UNKNOWN_STRADDLE为0
        self.driver_model = agent_config.get('agent_attributes', {}).get('driver_model', {})
        self.current_v_s = 0.0  # 纵向速度
        self.current_v_l = 0.0  # 横向速度
        self.driver_param = {
            'max_speed': 20.0,
            'max_acc': 4.0,
            'max_dcc': -4.0,
            'max_lateral_acc': 1.8,
            'max_lateral_speed': 3.6,
            'target_speed': 12,
            'target_l': 0.0,
            # 'lc_target_lane_id': "",
            'lc_duration_extra_param': 1.0,
            'lat_state': VehicleLatState.KeepLane,
        }

    def init(self):
        super().init()
        ego_state = EgoState()
        v = 0.0
        if self.init_spec.get('pos_type') == "RELATIVE_EGO_POS":
            pos = self.init_spec.get('relative_ego_pos', {})
            velocity = pos.get('velocity', None)
            if velocity is not None:
                v = pos.get('velocity', 0) / 3.6
            else:
                real_x0, real_y0, _, _ = ego_state.real_vehicle_trajectory[0]
                real_x1, real_y1, _, _ = ego_state.real_vehicle_trajectory[1]
                delta_t = (float(ego_state.timestamps[1]) - float(ego_state.timestamps[0])) / 1e9  # 时间单位转换为秒
                distance = math.sqrt((real_x1 - real_x0) ** 2 + (real_y1 - real_y0) ** 2)
                v = distance / delta_t
                if self.v_param is not None:
                    v = v * self.v_param
        elif self.init_spec.get('pos_type') == "RELATIVE_EGO_PATH_POS":
            pos = self.init_spec.get('relative_ego_path_pos', {})
            velocity = pos.get('velocity', None)
            if velocity is not None:
                v = pos.get('velocity', 0) / 3.6
            else:
                real_x0, real_y0, _, _ = ego_state.real_vehicle_trajectory[0]
                real_x1, real_y1, _, _ = ego_state.real_vehicle_trajectory[1]
                delta_t = (float(ego_state.timestamps[1]) - float(ego_state.timestamps[0])) / 1e9  # 时间单位转换为秒
                distance = math.sqrt((real_x1 - real_x0) ** 2 + (real_y1 - real_y0) ** 2)
                v = distance / delta_t
                if self.v_param is not None:
                    v = v * self.v_param

        self.driver_param['target_speed'] = v
        heading = self.pose2d['yaw']
        self.motion = {
            'vx': {
                'mu': v * math.cos(heading),
                'sigma': 0.0
            },
            'vy': {
                'mu': v * math.sin(heading),
                'sigma': 0.0
            },
            'ax': {
                'mu': 0.0,
                'sigma': 0.0
            },
            'ay': {
                'mu': 0.0,
                'sigma': 0.0
            }
        }

    def longitudinal_move_planning(self, deltaT):
        print(f"{self.id()} longitudinal_move_planning, deltaT={deltaT}")
        vx = self.motion['vx']['mu']
        vy = self.motion['vy']['mu']
        v = math.hypot(vx, vy)
        p_acc = v * 0.75 < self.driver_param['target_speed'] and self.driver_param['max_acc'] or -self.driver_param['max_dcc']
        acc = (1.0 - ((v + 1e-6) / (self.driver_param['target_speed'] + 1e-6)) ** 2) * p_acc
        max_acc = self.driver_param['max_acc']
        if v > kAccSpeedEnginePowerParmSedan:
            max_acc *= kAccSpeedEnginePowerParmSedan / v
        print(f"{self.id()} longitudinal_move_planning, acc={acc} v={v} target_speed={self.driver_param['target_speed']} max_acc={max_acc}",
              f"vx:{vx}, vy:{vy}, yaw:{self.pose2d['yaw']}")
        if v > self.driver_param['max_speed'] or abs(self.driver_param['target_speed'] - v) < 1e-2:
            acc = 0.0
        elif acc < self.driver_param['max_dcc']:
            acc = self.driver_param['max_dcc']
        elif acc > max_acc:
            acc = max_acc
        print(f"{self.id()} longitudinal_move_planning, adjust_accel acc={acc}")
        self.adjust_accel(acc)

    def adjust_accel(self, acc):
        yaw = self.pose2d['yaw']
        print(f"adjust_accel acc:{acc}, cos(yaw):{math.cos(yaw)}, sin(yaw):{math.sin(yaw)}")
        self.motion['ax']['mu'] = acc * math.cos(yaw)
        self.motion['ay']['mu'] = acc * math.sin(yaw)

    def adjust_target_speed(self, speed):
        self.driver_param['target_speed'] = speed
        self.driver_model['driver_type'] = 0  # 假设DRIVER_MODEL_IDM为0

    def adjust_max_acc(self, max_acc):
        self.driver_param['max_acc'] = max_acc

    def adjust_max_dcc(self, max_dcc):
        self.driver_param['max_dcc'] = max_dcc

    def go_straightly(self):
        current_time = 0  # 需要实现时间获取逻辑
        deltaT = (current_time - self.pre_time) / 1e9
        self.pre_time = current_time
        if self.driver_model.get('driver_type') == 0:  # 假设DRIVER_MODEL_IDM为0
            self.longitudinal_move_planning(deltaT)
        vx = self.motion['vx']['mu']
        vy = self.motion['vy']['mu']
        yaw = self.pose2d['yaw']
        acc = 0
        if math.cos(yaw) == 0:
            acc = self.motion['ay']['mu']
        else:
            acc = self.motion['ax']['mu'] / math.cos(yaw)
        v = math.hypot(vx, vy) + acc * deltaT
        v = max(0.0, v)
        vx = v * math.cos(yaw)
        vy = v * math.sin(yaw)
        x = self.pose2d['x'] + vx * deltaT
        y = self.pose2d['y'] + vy * deltaT
        self.pose2d['x'] = x
        self.pose2d['y'] = y
        print(f"{self.id()} GoStraightly, next step x={x} y={y} heading={yaw} v={v} acc={acc}")
        self.motion['vx']['mu'] = vx
        self.motion['vx']['sigma'] = 0
        self.motion['vy']['mu'] = vy
        self.motion['vy']['sigma'] = 0
        self.motion['ax']['mu'] = acc * math.cos(yaw)
        self.motion['ax']['sigma'] = 0
        self.motion['ay']['mu'] = acc * math.sin(yaw)
        self.motion['ay']['sigma'] = 0

    def run_in_acc_mode(self):
        current_time = 0  # 需要实现时间获取逻辑
        deltaT = (current_time - self.pre_time) / 1e9
        self.pre_time = current_time
        if self.driver_model.get('driver_type') == 0:  # 假设DRIVER_MODEL_IDM为0
            self.longitudinal_move_planning(deltaT)
        vx = self.motion['vx']['mu']
        vy = self.motion['vy']['mu']
        yaw = self.pose2d['yaw']
        acc = 0
        if math.cos(yaw) == 0:
            acc = self.motion['ay']['mu']
        else:
            acc = self.motion['ax']['mu'] / math.cos(yaw)
        v = math.hypot(vx, vy) + acc * deltaT
        v = max(0.0, v)
        vx = v * math.cos(yaw)
        vy = v * math.sin(yaw)
        x = self.pose2d['x'] + vx * deltaT
        y = self.pose2d['y'] + vy * deltaT
        self.pose2d['x'] = x
        self.pose2d['y'] = y
        # 需要实现MapProvider的Python版本
        # xmap = MapProvider.Instance().xmap()
        # s = 0.0
        # l = 0.0
        # lane = xmap.GetNearestLane(x, y, s, l)
        # path = lane.DiscretizedCenterLine()
        # point = path.GetPathPointByS(s)
        # heading = point.heading()
        # if self.driver_model.get('follow_type') == 2:  # 假设DRIVER_FOLLOW_RTM_RETROGRADE为2
        #     heading += math.pi
        # self.pose2d['yaw'] = heading
        self.motion['vx']['mu'] = vx
        self.motion['vx']['sigma'] = 0
        self.motion['vy']['mu'] = vy
        self.motion['vy']['sigma'] = 0
        self.motion['ax']['mu'] = acc * math.cos(yaw)
        self.motion['ax']['sigma'] = 0
        self.motion['ay']['mu'] = acc * math.sin(yaw)
        self.motion['ay']['sigma'] = 0

    def run_one_step(self, current_time):
        if self.replace_point_cloud:
            return
        if self.driver_model.get('follow_type') in [1, 2]:  # 假设DRIVER_FOLLOW_RTM为1，DRIVER_FOLLOW_RTM_RETROGRADE为2
            print(f"{self.id()} RunOneStep, RunInACCMode")
            self.run_in_acc_mode()
        else:
            print(f"{self.id()} RunOneStep, GoStraightly")
            self.go_straightly()

    def to_sf_dynamic_obj(self, dynamic_object):
        dynamic_object['track_id'] = self.id()
        dynamic_object['size']['length'] = self.attributes.get('length', 0)
        dynamic_object['size']['width'] = self.attributes.get('width', 0)
        dynamic_object['size']['height'] = self.attributes.get('height', 0)
        dynamic_object['type'] = self.attributes.get('type', 0)
        dynamic_object['direction'] = 0  # 假设SAME为0
        dynamic_object['signallight_status'] = self.signal_light
        dynamic_object['brakelight_status'] = self.brake_light
        dynamic_object['straddle_info']['straddle_status'] = self.track_straddle_status
        dynamic_object['pose'] = self.pose2d
        dynamic_object['motion'] = self.motion

    def line_segment_intersection(self, agent_start, dir_vec, seg_p1, seg_p2):
        """
        计算Agent射线与Ego线段的交点
        参数：
            agent_start：Agent起点 (x0,y0)
            dir_vec：Agent射线方向向量 (dx,dy)
            seg_p1：Ego线段起点 (x1,y1)
            seg_p2：Ego线段终点 (x2,y2)
        返回：
            交点坐标 (x,y) 或 None（不相交）
        """
        x0, y0 = agent_start
        dx, dy = dir_vec
        x1, y1 = seg_p1
        x2, y2 = seg_p2
        
        # Ego线段方向向量
        seg_dx = x2 - x1
        seg_dy = y2 - y1
        
        # 行列式（判断是否平行）
        det = dx * seg_dy - dy * seg_dx
        if abs(det) < 1e-6:  # 平行或共线
            return None
        
        # 求解参数 t（Agent直线上的参数，t≥0表示沿运动方向）
        # 和 s（Ego线段上的参数，0≤s≤1表示在线段内）
        t_numerator = (x1 - x0) * seg_dy - (y1 - y0) * seg_dx
        t = t_numerator / det
        if t < -1e-6:  # 交点在Agent起点后方（不考虑）
            return None
        
        s_numerator = (x1 - x0) * dy - (y1 - y0) * dx
        s = s_numerator / det
        if not (0 - 1e-6 <= s <= 1 + 1e-6):  # 交点不在Ego线段内
            return None
        
        # 计算交点坐标
        intersect_x = x0 + t * dx
        intersect_y = y0 + t * dy
        return (intersect_x, intersect_y)

    def get_encounter_v(self):
        ego_state = EgoState()
        agent_start_x = self.pose2d['x']
        agent_start_y = self.pose2d['y']
        agent_yaw = self.pose2d['yaw']
        # 直线方向向量（基于yaw角）
        dir_x = math.cos(agent_yaw)  # x方向分量
        dir_y = math.sin(agent_yaw)  # y方向分量
        print(f"Agent直线参数：起点({agent_start_x:.2f},{agent_start_y:.2f})，方向角{agent_yaw:.2f}rad，方向向量({dir_x:.2f},{dir_y:.2f})")
        
        # 检查Ego轨迹数据有效性
        if not hasattr(ego_state, 'real_vehicle_trajectory') or len(ego_state.real_vehicle_trajectory) < 2:
            print("Ego轨迹点不足（至少需要2个点），无法计算交点")
            return None
        # 提取Ego轨迹点（x,y）
        ego_points = [
            (traj[0], traj[1])  # traj格式：(x, y, ...)
            for traj in ego_state.real_vehicle_trajectory
        ]
        # 生成Ego轨迹线段（相邻点组成线段）
        ego_segments = [
            (ego_points[i], ego_points[i+1]) 
            for i in range(len(ego_points)-1)
        ]

        # 遍历所有Ego线段，寻找交点
        intersections = []
        for i, (seg_p1, seg_p2) in enumerate(ego_segments):
            intersect = self.line_segment_intersection(
                agent_start=(agent_start_x, agent_start_y),
                dir_vec=(dir_x, dir_y),
                seg_p1=seg_p1,
                seg_p2=seg_p2
            )
            if intersect:
                intersections.append({
                    'point': intersect,
                    'segment_idx': i,  # 属于第i条Ego线段
                    'distance_from_agent_start': math.hypot(
                        intersect[0] - agent_start_x,
                        intersect[1] - agent_start_y
                    )
                })
                print(f"检测到交点：线段{i} -> {intersect}，距Agent起点{intersections[-1]['distance_from_agent_start']:.2f}米")
        
        if not intersections:
            print("未检测到Agent直线与Ego轨迹的交点")
            return None
        
        # 选择沿Agent运动方向最近的交点（t最小，即距离起点最近）
        # 按距离Agent起点的距离排序
        intersections.sort(key=lambda x: x['distance_from_agent_start'])
        best_intersect = intersections[0]
        intersect_point = best_intersect['point']
        start_to_intersect_dist = best_intersect['distance_from_agent_start']

        # 输出结果
        print(f"\n===== 轨迹相交分析结果 =====")
        print(f"Agent起点: ({agent_start_x:.2f}, {agent_start_y:.2f})")
        print(f"Ego轨迹与Agent直线的交点: ({intersect_point[0]:.2f}, {intersect_point[1]:.2f})")
        print(f"交点位于Ego第{best_intersect['segment_idx']}条线段")
        print(f"Agent起点到交点的距离: {start_to_intersect_dist:.2f}米")
        print(f"===========================\n")
        
        # 计算Agent初速度
        timestamp_idx = best_intersect['segment_idx'] - 1
        current_index = ego_state.current_index
        if current_index >= timestamp_idx:
            print("ENCOUNTER: current_index : ", current_index, " timestamp_idx: ", timestamp_idx)
            return None
        delta_t = (float(ego_state.timestamps[timestamp_idx]) - float(ego_state.timestamps[current_index])) / 1e9  # 时间单位转换为秒
        if delta_t > 0:
            v = start_to_intersect_dist / delta_t
            print("ENCOUNTER: start_to_intersect_dist: ", start_to_intersect_dist, " delta_t: ", delta_t, " v: ", v)
            return v
         
    def set_encounter_v(self):
        print("ENCOUNTER: ")
        encounter_v = self.get_encounter_v()
        if encounter_v is not None and encounter_v > 0:
            self.driver_param['target_speed'] = encounter_v
            self.current_v_s = self.driver_param['target_speed']
            heading = self.pose2d['yaw']
            self.motion = {
                'vx': {
                    'mu': encounter_v * math.cos(heading),
                    'sigma': 0.0
                },
                'vy': {
                    'mu': encounter_v * math.sin(heading),
                    'sigma': 0.0
                },
                'ax': {
                    'mu': 0.0,
                    'sigma': 0.0
                },
                'ay': {
                    'mu': 0.0,
                    'sigma': 0.0
                }
            }
