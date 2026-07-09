from trigger_base import ActionBaseTrigger
import os, sys
current_dir = os.path.dirname(os.path.abspath(__file__))
agents_dir = os.path.join(current_dir, '..', 'agents')
sys.path.append(agents_dir)

from ego_state import EgoState

class EgoTimeTrigger(ActionBaseTrigger):
    def __init__(self, trigger_config):
        super().__init__(trigger_config)
        self.seconds_ = sys.float_info.max
        if trigger_config.get("trigger_type") == "TRIGGER_EGO_TIME":
            self.seconds_ = trigger_config.get("ego_time", {}).get("seconds")
        else:
            print("trigger type is not TRIGGER_EGO_TIME")

    def is_trigger_activated(self, agent_data):
        if not agent_data:
            print("agent_data is nullptr")
            return False
        ego_state = EgoState()
        current_index = ego_state.current_index
        start_timestamp = ego_state.timestamps[0]
        print(f"EgoTimeTrigger::is_trigger_activated: current_index = {current_index}, ego timestamps size = {len(ego_state.timestamps)}")
        if current_index >= len(ego_state.timestamps):
            print("EgoTimeTrigger::is_trigger_activated: current_index exceed timestamps size")
            return False
        
        current_timestamp = ego_state.timestamps[current_index]
        seconds = (float(current_timestamp) - float(start_timestamp)) / 1e9
        print(f"EgoTimeTrigger::is_trigger_activated: now seconds = {seconds} target seconds = {self.seconds_}")
        if seconds >= self.seconds_:
            return True
        return False