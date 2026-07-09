from action_base_delegate import ActionBaseDelegate, ActionLifeSpan
import os, sys
current_dir = os.path.dirname(os.path.abspath(__file__))
agents_dir = os.path.join(current_dir, '..', 'agents')
sys.path.append(agents_dir)

from agent_data_field import AgentDataField
from dynamic_agent_vehicle import DynamicAgentVehicle

class ChangeLaneDelegate(ActionBaseDelegate):
    def __init__(self, action_config):
        super().__init__(action_config)
        self.spec_ = action_config.get("action_change_lane_spec", None)
        self.spec_['agent_id'] = action_config['agent_id']

    def run_one_step(self):
        if self.life_span_ == ActionLifeSpan.FINISHED:
            return
        agent_data_field = AgentDataField()
        if not agent_data_field:
            print("agent_data is nullptr")
            return
        if not self.trigger_alive():
            self.life_span_ = ActionLifeSpan.FINISHED
            return
        if self.life_span_ == ActionLifeSpan.WAITING and self.should_trigger(agent_data_field):
            agent_id = self.spec_.get("agent_id")
            target_agent = agent_data_field.get_dynamic_agent(agent_id)
            if not target_agent:
                print(f"ChangeLaneDelegate: id={agent_id} target_agent is nullptr")
                return
            target_veh = target_agent if isinstance(target_agent, DynamicAgentVehicle) else None
            if not target_veh:
                print(f"ChangeLaneDelegate: id={agent_id} target_agent is not a vehicle")
                return
            _success = target_veh.change_lane(self.spec_.get("force_change_to_ego_lane"), self.spec_.get("target_lane_index"),
                                             self.spec_.get("lane_change_duration"))
            print(f"ChangeLaneDelegate::RunOneStep: agent {target_agent.id()} lane change ret {_success}")
            self.life_span_ = ActionLifeSpan.FINISHED