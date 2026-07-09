from trigger_base import ActionBaseTrigger
from ego_state import EgoState
import math

class RelativeDistTrigger(ActionBaseTrigger):
    def __init__(self, trigger_config):
        super().__init__(trigger_config)
        if trigger_config.get("trigger_type") == "TRIGGER_RELATIVE_DIST":
            self.spec_ = trigger_config.get("relative_dist", {})
            self.spec_["agent_id"] = trigger_config.get("agent_id", None)
        else:
            self.spec_ = None
        if not self.spec_:
            print("trigger type is not TRIGGER_RELATIVE_DIST")

    def is_trigger_activated(self, agent_data):
        if not self.spec_:
            print("spec is invalid")
            return False
        if not agent_data:
            print("agent_data is nullptr")
            return False
        agent_id = self.spec_["agent_id"]
        agent = agent_data.get_dynamic_agent(agent_id)
        if not agent:
            print(f"cannot find agent {agent_id}")
            return False
        if not agent.is_inited():
            print(f"agent {agent_id} is not inited")
            return False
        ego_state = EgoState()
        ego_pos = ego_state.get_current_ego_position()
        ego_x = ego_pos[0]
        ego_y = ego_pos[1]
        agent_x = agent.pose2d["x"]
        agent_y = agent.pose2d["y"]
        dist = math.hypot(ego_x - agent_x, ego_y - agent_y)
        ego_agent_distance_upperbound = self.spec_["ego_agent_distance_upperbound"]
        ego_agent_distance_lowbound = self.spec_["ego_agent_distance_lowbound"]
        print(f"agent_id = {agent_id} relative dist to ego = {dist}, trigger dist upperbound {ego_agent_distance_upperbound}, trigger dist lowbound {ego_agent_distance_lowbound}")
        if dist <= ego_agent_distance_upperbound and dist >= ego_agent_distance_lowbound:
            return True
        return False