from agent import Agent
from dynamic_agent import DynamicAgent
from dynamic_agent_vehicle import DynamicAgentVehicle
from agent_data_field import AgentDataField
import json

import os, sys

# 获取当前脚本所在目录
current_dir = os.path.dirname(os.path.abspath(__file__))
# 构建相对路径，假设actions目录在agent_service目录下
actions_dir = os.path.join(current_dir, '..', 'actions')
# 将路径添加到系统路径
sys.path.append(actions_dir)

# sys.path.append('/home/xpeng/data/cloudsim/3dgs_test/agent_service/actions')
from action_generate_agent_delegate import GenerateAgentDelegate
from action_speed_accel_delegate import SpeedAccelDelegate
from action_change_lane_delegate import ChangeLaneDelegate
from action_remove_agent_delegate import RemoveAgentDelegate
from action_modify_driver_delegate import ModifyDriverDelegate
from action_base_delegate import ActionBaseDelegate

class AgentManager:
    def __init__(self):
        self.action_delegate_vec = []

    def create_agents(self, config):
        agent_data_field = AgentDataField()
        for object in config.get('objects', []):
            agent_id = object.get('id', None)
            agent_config = object.get('agent_configs', {})
            print("Agents cfg = ", json.dumps(agent_config))
            if not agent_id:
                print("Agents cfg id is None")
                continue
            agent_config['agent_attributes']['id'] = agent_id
            agent = DynamicAgentVehicle(agent_config)
            agent_data_field.add_dynamic_agent(agent)

    def create_actions(self, config):
        for object in config.get('objects', []):
            agent_id = object.get('id', None)
            if not agent_id:
                print("Action cfg agent_id is None")
                continue
            for action_config in object.get('action_configs', []):
                action_config['agent_id'] = agent_id
                print("Action cfg = ", json.dumps(action_config))
                action_type = action_config.get('action_type', 0)
                delegate = None
                if action_type == "ACTION_CHANGE_LANE":
                    delegate = ChangeLaneDelegate(action_config)
                elif action_type == "ACTION_AGENT_ACCEL":
                    delegate = SpeedAccelDelegate(action_config)
                else:
                    print(f"Unknown action type: {action_type}")
                if delegate:
                    self.action_delegate_vec.append(delegate)

    # def on_ego_updated(self, localization_info):
    def on_ego_updated(self, current_time):
        # 这里需要实现EgoState的Python版本
        # EgoState.Instance().UpdateLocalization(localization_info)
        agent_data_field = AgentDataField()
        # if EgoState.Instance().HasMoved():
        dynamic_agent_map = agent_data_field.mutable_dynamic_agent_map()
        agent_iter = list(dynamic_agent_map.items())
        for agent_id, agent in agent_iter:
            if agent.is_end():
                del dynamic_agent_map[agent_id]
            else:
                if not agent.is_inited():
                    agent.init()
                agent.run_one_step(current_time)
        static_agent_map = agent_data_field.mutable_static_agent_map()
        agent_iter = list(static_agent_map.items())
        for agent_id, agent in agent_iter:
            if agent.is_end():
                del static_agent_map[agent_id]
            else:
                if not agent.is_inited():
                    agent.init()
                agent.run_one_step()
        delegate_iter = list(self.action_delegate_vec)
        for delegate in delegate_iter:
            # print(f"Running action delegate: {delegate.__class__.__name__}")
            if delegate.is_finished():
                self.action_delegate_vec.remove(delegate)
            else:
                delegate.run_one_step()

    def create_sensor_fusion_output_info(self, sensor_fusion_input, sensor_fusion_output):
        agent_data_field = AgentDataField()
        dynamic_agent_map = agent_data_field.mutable_dynamic_agent_map()
        for agent_id, agent in dynamic_agent_map.items():
            if agent.is_active() and agent.is_visible():
                dynamic_object = {}
                agent.to_sf_dynamic_obj(dynamic_object)
                sensor_fusion_output['dynamic_objects'].append(dynamic_object)
        static_agent_map = agent_data_field.mutable_static_agent_map()
        for agent_id, agent in static_agent_map.items():
            if agent.is_active() and agent.is_visible():
                static_object = {}
                agent.to_sf_static_obj(static_object)
                sensor_fusion_output['static_objects'].append(static_object)
        # 需要实现EgoState的Python版本
        # sensor_fusion_output['ego_motion'] = EgoState.Instance().GetCurrentLocalization().ego_motion()
        # if sensor_fusion_input and sensor_fusion_output:
        #     collision_filtering_manager_.Process(sensor_fusion_input['ego_motion'], sensor_fusion_output)
        # else:
        #     fake_ego_motion = {}
        #     collision_filtering_manager_.Process(fake_ego_motion, sensor_fusion_output)
        # sensor_fusion_output['header']['user_header']['time_stamp']['nanosecond'] = 0  # 需要实现时间获取逻辑