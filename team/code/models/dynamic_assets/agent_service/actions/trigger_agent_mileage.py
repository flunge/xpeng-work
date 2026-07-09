from trigger_base import ActionBaseTrigger
import os, sys
current_dir = os.path.dirname(os.path.abspath(__file__))
agents_dir = os.path.join(current_dir, '..', 'agents')
sys.path.append(agents_dir)

from ego_state import EgoState

class AgentMileageTrigger(ActionBaseTrigger):
    def __init__(self, trigger_config):
        super().__init__(trigger_config)
        self.mileage_ = sys.float_info.max
        self.agent_id_ = None
        if trigger_config.get("trigger_type") == "TRIGGER_AGENT_MILEAGE":
            self.mileage_ = trigger_config.get("agent_mileage", {}).get("mileage")
            self.agent_id_ = trigger_config.get("agent_id", None)
        else:
            print("trigger type is not TRIGGER_AGENT_MILEAGE")

    def is_trigger_activated(self, agent_data):
        if not agent_data:
            print("agent_data is nullptr")
            return False

        agent_id = self.agent_id_
        agent = agent_data.get_dynamic_agent(agent_id)
        if not agent:
            print(f"cannot find agent {agent_id}")
            return False
        if not agent.is_inited():
            print(f"agent {agent_id} is not inited")
            return False
        
        now_mileage = agent.get_agent_mileage()
        print(f"AgentMileageTrigger::is_trigger_activated: now mileage = {now_mileage} target milage = {self.mileage_}")
        if now_mileage >= self.mileage_:
            return True
        return False