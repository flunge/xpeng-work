from action_base_delegate import ActionBaseDelegate, ActionLifeSpan
import os, sys
current_dir = os.path.dirname(os.path.abspath(__file__))
agents_dir = os.path.join(current_dir, '..', 'agents')
sys.path.append(agents_dir)

from agent_data_field import AgentDataField
from dynamic_agent import DynamicAgent

class SpeedAccelDelegate(ActionBaseDelegate):
    def __init__(self, action):
        super().__init__(action)
        self.spec_ = action["speed_accel_spec"]
        self.spec_["agent_id"] = action["agent_id"]

    def run_one_step(self):
        if self.life_span_ == ActionLifeSpan.FINISHED:
            return
        agent_data = AgentDataField()
        if not agent_data:
            print("agent_data is nullptr")
            return
        agent_id = self.spec_["agent_id"]
        agent = agent_data.get_dynamic_agent(agent_id)
        if not agent:
            print(f"cannot find agent {agent_id}")
            return
        if not agent.is_dynamic():
            print("only dynamic agent allow speed accel action")
            return
        if self.should_trigger(agent_data):
            dynamic_agent = agent if isinstance(agent, DynamicAgent) else None
            auto_a = self.spec_["accel_property"].get("auto_a", None)
            a = self.spec_["accel_property"]["a"]
            if auto_a == "ENCOUNTER":
                dynamic_agent.set_encounter_v()
            else:
                dynamic_agent.adjust_accel(a)
            status = "finished" if self.life_span_ == ActionLifeSpan.FINISHED else "running"
            print(f"speed accel {a} action for agent {agent_id} is {status} with accel {a}")
            self.life_span_ = ActionLifeSpan.RUNNING
        if not self.trigger_alive():
            self.life_span_ = ActionLifeSpan.FINISHED