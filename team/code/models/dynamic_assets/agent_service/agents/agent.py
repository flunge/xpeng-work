import math
from ego_state import EgoState
from configs.config import DYNAMIC_OBJECTS_CONFIGS

class AgentLifeSpan:
    NOT_INIT = 0
    RUNNING = 1
    DEAD = 2

class Agent:
    def __init__(self, agent_config):
        self.start_time = 0
        self.pre_time = 0
        self.stop_time = 0
        self.bstart = False
        self.bend = False
        self.life_span = AgentLifeSpan.NOT_INIT
        self.bVisible = True
        self.dyaw = 0
        self.v_param = None
        self.replace_point_cloud = False # 只替换原有点云数据，不修改轨迹
        self.attributes = agent_config.get('agent_attributes', {})
        self.init_spec = agent_config.get('init_state_spec', {})
        self.pose2d = {
            'x': 0,
            'y': 0,
            'yaw': 0
        }

    def id(self):
        return self.attributes.get('id', 0)

    def is_dynamic(self):
        return True
        # agent_type = self.attributes.get('type', 0)
        # return agent_type < 100  # 假设STATIC_AGENT_CATEGORY_MASK为100

    def is_inited(self):
        return self.life_span != AgentLifeSpan.NOT_INIT

    def is_active(self):
        return self.life_span == AgentLifeSpan.RUNNING

    def is_end(self):
        return self.life_span == AgentLifeSpan.DEAD

    def is_visible(self):
        return self.bVisible

    def init(self):
        print(f"Agent Init: init_spec_={self.init_spec}")

        data_uid = self.attributes.get('data_uid', 0)
        obj_data = DYNAMIC_OBJECTS_CONFIGS.get(str(data_uid), {})
        self.attributes['length'] = obj_data.get('length', 4.5)
        self.attributes['width'] = obj_data.get('width', 1.7)
        self.attributes['height'] = obj_data.get('height', 1.9)

        x = 0.0
        y = 0.0
        heading = 0.0
        if self.init_spec.get('pos_type') == "RELATIVE_EGO_POS":
            pos = self.init_spec.get('relative_ego_pos', {})
            seconds = pos.get('seconds', 0)
            ds = pos.get('ds', 0)
            dl = pos.get('dl', 0)
            self.v_param = pos.get('v_param', None)
            dangle = pos.get('dangle', 0)
            self.dyaw = math.radians(dangle)
            ego_state = EgoState()
            start_timestamp = float(ego_state.timestamps[0])
            index_timestamp = start_timestamp + seconds * 1e9
            index = 0
            dif_timestamp = 60 * 1e9
            for i, timestamp in enumerate(ego_state.timestamps):
                cur_dif = abs(float(timestamp) - index_timestamp)
                if cur_dif < dif_timestamp:
                    dif_timestamp = cur_dif
                    index = i

            if ego_state.real_vehicle_trajectory and len(ego_state.real_vehicle_trajectory) >= index:
                ego_x, ego_y, _, ego_yaw = ego_state.real_vehicle_trajectory[index]
                x = ego_x + ds
                y = ego_y + dl
                heading = self.get_agent_yaw(ego_yaw)
            else:
                print("ego_state.real_vehicle_trajectory out of bounds, index: ", index)
            print(f"Agent Init: RELATIVE_EGO_POS: ds = {ds} dl = {dl} x = {x} y = {y}")
        elif self.init_spec.get('pos_type') == "RELATIVE_EGO_PATH_POS":
            pos = self.init_spec.get('relative_ego_path_pos', {})
            ds = pos.get('ds', 0)
            dl = pos.get('dl', 0)
            self.dv = pos.get('dv', 0)
            dangle = pos.get('dangle', 0)
            self.dyaw = math.radians(dangle)
            ego_state = EgoState()
            pre_ego_x, pre_ego_y, _, _ = ego_state.real_vehicle_trajectory[0]
            distance = 0
            for i in range(len(ego_state.real_vehicle_trajectory)):
                ego_x, ego_y, _, ego_yaw = ego_state.real_vehicle_trajectory[i]
                cur_distance = math.sqrt((ego_x - pre_ego_x) ** 2 + (ego_y - pre_ego_y) ** 2)
                pre_ego_x = ego_x
                pre_ego_y = ego_y
                distance += cur_distance
                if distance >= ds:
                    x = ego_x
                    y = ego_y + dl
                    heading = self.get_agent_yaw(ego_yaw)
                    break
            print(f"Agent Init: RELATIVE_EGO_PATH_POS: ds = {ds} dl = {dl} x = {x} y = {y}")
        elif self.init_spec.get('pos_type') == "REPLACE_POINT_CLOUD":
            self.replace_point_cloud = True

        self.life_span = AgentLifeSpan.RUNNING
        self.pre_time = 0  # 需要实现时间获取逻辑
        self.pose2d['x'] = x
        self.pose2d['y'] = y
        self.pose2d['yaw'] = heading

    def run_one_step(self, current_time, real_vehicle_trajectory):
        raise NotImplementedError("Subclasses should implement this!")

    def to_sf_static_obj(self, static_object):
        pass

    def to_sf_dynamic_obj(self, dynamic_object):
        pass

    def get_agent_yaw(self, yaw):
        # 0~90:左前  -90~0:右前
        heading = yaw + self.dyaw
        # 规范化所有角度到[-π, π]范围
        heading = (heading + math.pi) % (2 * math.pi) - math.pi
        return heading

    def get_agent_mileage(self):
        pass