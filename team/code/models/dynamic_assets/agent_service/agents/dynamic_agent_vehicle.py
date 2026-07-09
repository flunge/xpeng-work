import math
from agent import Agent, AgentLifeSpan
from dynamic_agent import DynamicAgent, VehicleLatState
from ego_state import EgoState

M_PI = math.pi
kLaneSearchRadius = 5.0
kLaneSearchTol1 = M_PI / 3
kLateralMoveUseKinematics = M_PI / 72
kLateralSpeedDefault = 3.6

class DynamicAgentVehicle(DynamicAgent):
    def __init__(self, agent_config):
        super().__init__(agent_config)

        self.current_s = 0.0  # 纵向位置
        self.current_l = 0.0  # 横向位置
        self.pre_time = 0
        self.trajectory_index = 0
        self.mileage = 0

    def init(self):
        super().init()

        ego_state = EgoState()
        self.pre_time = float(ego_state.timestamps[0]) - (float(ego_state.timestamps[1]) - float(ego_state.timestamps[0]))
        self.current_v_s = self.driver_param['target_speed']  # 初始横向速度

    def run_one_step(self, current_time):
        if self.replace_point_cloud:
            return
        self.run_in_driver_mode(current_time)

    def run_in_driver_mode(self, current_time):
        print(f"{self.id()} run_in_driver_mode start, now step trajectory_index={self.trajectory_index} x={self.pose2d['x']} ")
        ego_state = EgoState()
        ego_pos, _ = ego_state.get_nearest_ego_position([self.pose2d["x"], self.pose2d["y"]])
        real_x = ego_pos[0]
        real_y = ego_pos[1]
        # real_x, real_y, _, real_yaw = ego_state.real_vehicle_trajectory[self.trajectory_index]

        if self.life_span == AgentLifeSpan.DEAD:
            return
        if self.trajectory_index >= len(ego_state.real_vehicle_trajectory):
            self.life_span = AgentLifeSpan.DEAD
            return
        
        deltaT = (current_time - self.pre_time) / 1e9  # 时间单位是纳秒
        # 打印下面计算的关键数据
        print(f"{self.id()} run_in_driver_mode, now step trajectory_index={self.trajectory_index} x={self.pose2d['x']} "
            f"y={self.pose2d['y']} heading={self.pose2d['yaw']} vx={self.motion['vx']['mu']} vy={self.motion['vy']['mu']} "
            f"current_time={current_time} deltaT={deltaT} "
            f"current_s_={self.current_s} current_l={self.current_l} current_v_s={self.current_v_s} current_v_l={self.current_v_l}")

        self.pre_time = current_time
        pre_yaw = self.pose2d['yaw']

        
        # self.longitudinal_move_planning(deltaT)

        acc = 0
        if math.cos(pre_yaw) == 0:
            acc = self.motion['ax']['mu']
        else:
            acc = self.motion['ax']['mu'] / math.cos(pre_yaw)
        self.current_v_s = self.current_v_s + acc * deltaT
        self.current_v_s = max(self.current_v_s, 0.0)

        print(f"{self.id()} run_in_driver_mode2, now step trajectory_index={self.trajectory_index} x={self.pose2d['x']} "
            f"y={self.pose2d['y']} heading={self.pose2d['yaw']} vx={self.motion['vx']['mu']} vy={self.motion['vy']['mu']} "
            f"current_time={current_time} deltaT={deltaT} "
            f"current_s_={self.current_s} current_l={self.current_l} current_v_s={self.current_v_s} current_v_l={self.current_v_l}"
            f"acc={acc} a={self.motion['ax']['mu']}")

        # 横向运动规划
        if self.driver_param['lat_state'] == VehicleLatState.ChangeLane:
            self.lane_changing_lateral_move_planning(deltaT)
        elif self.driver_param['lat_state'] == VehicleLatState.KeepLane:
            self.lateral_move_planning(deltaT)

        print(f"{self.id()} run_in_driver_mode3, now step trajectory_index={self.trajectory_index} x={self.pose2d['x']} "
            f"y={self.pose2d['y']} heading={self.pose2d['yaw']} vx={self.motion['vx']['mu']} vy={self.motion['vy']['mu']} "
            f"current_time={current_time} deltaT={deltaT} "
            f"current_s_={self.current_s} current_l={self.current_l} current_v_s={self.current_v_s} current_v_l={self.current_v_l}")

        # 更新速度到 motion 字典
        self.motion['vx']['mu'] = self.current_v_s * math.cos(self.pose2d['yaw']) - self.current_v_l * math.sin(self.pose2d['yaw'])
        self.motion['vy']['mu'] = self.current_v_s * math.sin(self.pose2d['yaw']) + self.current_v_l * math.cos(self.pose2d['yaw'])

        print(f"{self.id()} run_in_driver_mode4, now step trajectory_index={self.trajectory_index} x={self.pose2d['x']} "
            f"y={self.pose2d['y']} heading={self.pose2d['yaw']} vx={self.motion['vx']['mu']} vy={self.motion['vy']['mu']} "
            f"current_time={current_time} deltaT={deltaT} "
            f"current_s_={self.current_s} current_l={self.current_l} current_v_s={self.current_v_s} current_v_l={self.current_v_l}")

        prev_x = self.pose2d['x']
        prev_y = self.pose2d['y']

        # 更新位置
        self.pose2d['x'] += self.motion['vx']['mu'] * deltaT
        self.pose2d['y'] += self.motion['vy']['mu'] * deltaT

        # 计算两点之间的距离
        curr_x = self.pose2d['x']
        curr_y = self.pose2d['y']
        distance = ((curr_x - prev_x)**2 + (curr_y - prev_y)**2)**0.5
        self.mileage += distance

        # 更新纵向和横向位置
        self.current_s += self.current_v_s * deltaT
        self.current_l += self.current_v_l * deltaT

        self.trajectory_index += 1

        # 输出结果
        # print(f"run_in_driver_mode, next step x={self.pose2d['x']} y={self.pose2d['y']} heading={self.pose2d['yaw']} vx={self.motion['vx']['mu']} vy={self.motion['vy']['mu']}")
        from result_collector import ResultCollector
        collector = ResultCollector()
        collector.add_result(self.id(), self.pose2d['x'], self.pose2d['y'], 1, self.pose2d['yaw'])

    def lateral_move_planning(self, deltaT):
        # print(f"{self.id()} lateral_move_planning")

        l_diff = self.driver_param["target_l"] - self.current_l
        ld_dirc = 1 if l_diff > 0 else -1
        ego_state = EgoState() 
        _, lane_yaw = ego_state.get_nearest_ego_position([self.pose2d["x"], self.pose2d["y"]])
        lane_yaw = self.get_agent_yaw(lane_yaw)
        dYaw = lane_yaw - self.pose2d["yaw"]
        # print(f"{self.id()} run_in_driver_mode,lateral_move_planning-> l_diff={l_diff} "
        #       f"ld_dirc={ld_dirc} dYaw={dYaw} lane_yaw={lane_yaw} "
        #       f"driver_param_.target_l={self.driver_param['target_l']}")

        if abs(dYaw) > kLateralMoveUseKinematics:
            p5 = min((self.driver_param["target_speed"] / (abs(self.current_v_s) + 1e-6)) ** 1, 1.0)
            p6 = dYaw / (M_PI / 6)
            _, lane_yaw_2 = ego_state.get_nearest_ego_position([self.current_s + self.current_v_s, self.current_l + self.current_v_l])
            lane_yaw_2 = self.get_agent_yaw(lane_yaw_2)
            p7 = 1.0 + min(0.5, abs(lane_yaw - lane_yaw_2) / (M_PI / 6))
            bpf = - p7 * p6 * p5 * M_PI / 6
            L1 = self.attributes.get("length", 0) / 2
            L2 = self.attributes.get("length", 0) / 2
            totalSpeed = math.sqrt(self.current_v_l ** 2 + self.current_v_s ** 2)
            lc_new_yaw = self.pose2d["yaw"] - totalSpeed * (math.tan(bpf)) / (L1 + L2) * deltaT
            dYaw = lane_yaw - lc_new_yaw
            self.current_v_l = - totalSpeed * math.sin(dYaw)
            self.current_v_s = totalSpeed * math.cos(dYaw)
            self.pose2d["yaw"] = lc_new_yaw

            # print(f"{self.id()} run_in_driver_mode,lateral_move_planning-> current_v_l={self.current_v_l} "
            #       f"current_v_s= {self.current_v_s} lc_new_yaw= {lc_new_yaw} "
            #       f"bpf={bpf} dYaw={dYaw}")
        # elif abs(l_diff) > 0.1:
        #     print(f"{self.id()} run_in_driver_mode,lateral_move_planning-> dYaw={dYaw} using geoModel, l_diff={l_diff}")
        #     target_next_l_speed = ld_dirc * self.current_v_s * 0.2 * (1.0 - ((max(3.5 - abs(l_diff), 0.0) / 3.5) ** 2))
        #     v_l_diff = target_next_l_speed - self.current_v_l
        #     vl_dirc = 1 if v_l_diff > 0 else -1
        #     acc_l = vl_dirc * self.driver_param["max_lateral_acc"] * ((abs(self.current_v_s) / self.driver_param["max_speed"]) ** 0.5)
        #     if abs(v_l_diff) <= 1e-6:
        #         acc_l = 0
        #     print(f"{self.id()} run_in_driver_mode,lateral_move_planning-> current_v_l={self.current_v_l} v_l_diff= {v_l_diff}")
        #     self.current_v_l = self.current_v_l + acc_l * deltaT

        #     if (vl_dirc > 0 and self.current_v_l > target_next_l_speed) or (vl_dirc < 0 and self.current_v_l < target_next_l_speed):
        #         print(f"{self.id()} run_in_driver_mode,lateral_move_planning-> fabs(current_v_l) > fabs(target_next_l_speed)")
        #         self.current_v_l = target_next_l_speed
        #     if abs(self.current_v_l) > self.driver_param["max_lateral_speed"]:
        #         print(f"{self.id()} run_in_driver_mode,lateral_move_planning-> fabs(current_v_l) > driver_param_.max_lateral_speed")
        #         self.current_v_l = self.current_v_l * self.driver_param["max_lateral_speed"] / abs(self.current_v_l)
        #     if abs(self.current_v_l) > self.current_v_s * 0.4:
        #         print(f"{self.id()} run_in_driver_mode,lateral_move_planning-> fabs(current_v_l) > current_v_s * 0.4")
        #         self.current_v_l = self.current_v_l * self.current_v_s * 0.4 / abs(self.current_v_l)

        #     # point = self.local_map["current_lane"]().lane_path_.GetPathPointByS(self.current_s_)
        #     _, ego_yaw = ego_state.get_nearest_ego_position([self.pose2d["x"], self.pose2d["y"]])
        #     heading = ego_yaw + math.atan2(self.current_v_l, self.current_v_s)
        #     # heading = point.get("heading", 0.0) + math.atan2(self.current_v_l, self.current_v_s)
        #     print(f"{self.id()} run_in_driver_mode,lateral_move_planning-> current_v_l={self.current_v_l} "
        #           f"target_next_l_speed={target_next_l_speed} acc_l={acc_l} heading={heading}")
        #     self.pose2d["yaw"] = heading
        else:
            # print(f"{self.id()} run_in_driver_mode,lateral_move_planning-> following lane path ")
            self.current_v_l = 0
            _, heading = ego_state.get_nearest_ego_position([self.pose2d["x"], self.pose2d["y"]])
            heading = self.get_agent_yaw(heading)
            self.pose2d["yaw"] = heading

    def lane_changing_lateral_move_planning(self, deltaT):
        # print(f"{id(self)} lane_changing_lateral_move_planning")

        # lane_yaw = self.local_map.current_lane.lane_path.GetPathPointByS(self.current_s_).heading
        ego_state = EgoState() 
        _, lane_yaw = ego_state.get_nearest_ego_position([self.pose2d["x"], self.pose2d["y"]])
        lane_yaw = self.get_agent_yaw(lane_yaw)
        dYaw = lane_yaw - self.pose2d["yaw"]
        target_l = self.driver_param.get("target_l", 0)
        print(f"{id(self)} run_in_driver_mode,lane_changing_lateral_move_planning-> "
              f" dYaw={dYaw} "
              f" lane_yaw={lane_yaw} "
              f" driver_param_.target_l={target_l}"
              f" self.current_l={self.current_l}")

        if abs(self.current_l) < abs(self.driver_param.get("target_l", 0)) * 0.5:
            # print(f"{id(self)} run_in_driver_mode,lane_changing_lateral_move_planning-> phase 1, current_l={self.current_l}")
            p4 = abs(self.current_l) / (abs(self.driver_param.get("target_l", 0)) / 2 + 1e-1)
            p5 = min((self.driver_param.get("target_speed", 0) / (abs(self.current_v_s) + 1e-6)) ** 2, 1.0)
            p6 = -1 if self.driver_param.get("target_l", 0) < 0 else 1
            p7 = min(self.driver_param.get("lc_duration_extra_param", 0), 1.5)
            bpf = (1 - p4) * p5 * p6 * p7 * M_PI / 6
            L1 = self.attributes.get("length", 0) / 2
            L2 = self.attributes.get("length", 0) / 2
            totalSpeed = math.sqrt(self.current_v_l ** 2 + self.current_v_s ** 2)
            lc_new_yaw = self.pose2d["yaw"] - totalSpeed * (math.tan(bpf)) / (L1 + L2) * deltaT
            dYaw = lane_yaw - lc_new_yaw
            self.current_v_l = - totalSpeed * math.sin(dYaw)
            self.current_v_s = totalSpeed * math.cos(dYaw)
            self.pose2d["yaw"] = lc_new_yaw
            # print(f"{id(self)} run_in_driver_mode,lane_changing_lateral_move_planning-> phase 1,-> current_v_l={self.current_v_l} "
            #       f" current_v_s= {self.current_v_s} "
            #       f" lc_new_yaw= {lc_new_yaw} "
            #       f" bpf={bpf} "
            #       f" dYaw={dYaw}")
        elif abs(self.current_l) < abs(self.driver_param.get("target_l", 0)) * 0.9:
            # print(f"{id(self)} run_in_driver_mode,lane_changing_lateral_move_planning-> phase 2, current_l={self.current_l}")
            p5 = min((self.driver_param.get("target_speed", 0) / (abs(self.current_v_s) + 1e-6)), 1.0)
            p6_1 = (abs(self.driver_param.get("target_l", 0)) - abs(self.current_l)) / abs(self.driver_param.get("target_l", 0))
            p6_dYaw = 0.0 if abs(dYaw) < 1e-6 else dYaw / abs(dYaw)
            p6_drc = p6_dYaw if abs(self.driver_param.get("target_l", 0)) - abs(self.current_l) < 1.75 else 0.0
            p6_2 = min(abs(dYaw) / (M_PI / 6), 1.0)
            p6 = p6_drc * max(p6_2, 0.2 * p6_1)
            p7 = min(self.driver_param.get("lc_duration_extra_param", 0), 1.5)
            bpf = - p6 * p5 * p7 * M_PI / 6
            L1 = self.attributes.get("length", 0) / 2
            L2 = self.attributes.get("length", 0) / 2
            totalSpeed = math.sqrt(self.current_v_l ** 2 + self.current_v_s ** 2)
            lc_new_yaw = self.pose2d["yaw"] - totalSpeed * (math.tan(bpf)) / (L1 + L2) * deltaT
            dYaw = lane_yaw - lc_new_yaw
            self.current_v_l = - totalSpeed * math.sin(dYaw)
            self.current_v_s = totalSpeed * math.cos(dYaw)
            self.pose2d["yaw"] = lc_new_yaw
            # print(f"{id(self)} run_in_driver_mode,lane_changing_lateral_move_planning-> phase 2,-> current_v_l={self.current_v_l} "
            #       f" current_v_s= {self.current_v_s} "
            #       f" lc_new_yaw= {lc_new_yaw} "
            #       f" bpf={bpf} "
            #       f" p5={p5} "
            #       f" p6={p6} "
            #       f" dYaw={dYaw}")
        else:
            # print(f"{id(self)} run_in_driver_mode,lane_changing_lateral_move_planning-> end lane change")
            # if not self.local_map.UpdateLocalMap():
            #     # 模拟车辆死亡状态
            #     pass
            # print(f"{id(self)} lane_changing_lateral_move_planning fin: current_lane_id={id(self.local_map.current_lane)} "
            #       f" current_s_={self.current_s_} current_l={self.current_l} "
            #       f" pose2d_.x()={self.pose2d.x} pose2d_.y()={self.pose2d.y}")
            self.driver_param["lat_state"] = VehicleLatState.KeepLane
            self.driver_param["target_l"] = 0.0


    def change_lane(self, force_change_to_ego_lane=False, target_lane_index=0, duration=1.0):
        if force_change_to_ego_lane:
            return False
        else:
            self.driver_param['target_l'] = self.current_l + target_lane_index * 1.5
            # print("change_lane: self.current_l: ", self.current_l, " target_l: ", self.driver_param['target_l'])
            self.driver_param['lat_state'] = VehicleLatState.ChangeLane
            # 避免除以零
            if abs(self.current_v_s) < 1e-6:
                self.driver_param['lc_duration_extra_param'] = 1.0
            else:
                duration = duration / 0.6
                self.driver_param['lc_duration_extra_param'] = (abs(self.driver_param['target_l'])) / (duration * abs(self.current_v_s) * math.sin(math.pi / 6))
            return True

    def get_agent_mileage(self):
        return self.mileage