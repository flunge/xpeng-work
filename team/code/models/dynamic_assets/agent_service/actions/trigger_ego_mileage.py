from trigger_base import ActionBaseTrigger
import os, sys
current_dir = os.path.dirname(os.path.abspath(__file__))
agents_dir = os.path.join(current_dir, '..', 'agents')
sys.path.append(agents_dir)

from ego_state import EgoState

class EgoMileageTrigger(ActionBaseTrigger):
    def __init__(self, trigger_config):
        super().__init__(trigger_config)
        self.mileage_ = sys.float_info.max
        if trigger_config.get("trigger_type") == "TRIGGER_EGO_MILEAGE":
            self.mileage_ = trigger_config.get("ego_mileage", {}).get("mileage")
        else:
            print("trigger type is not TRIGGER_EGO_MILEAGE")

    def is_trigger_activated(self, agent_data):
        if not agent_data:
            print("agent_data is nullptr")
            return False
        ego_state = EgoState()
        now_mileage = ego_state.get_ego_move_total_distance()
        print(f"EgoMileageTrigger::isTriggerActivated: now mileage = {now_mileage} target milage = {self.mileage_}")
        if now_mileage >= self.mileage_:
            return True
        return False