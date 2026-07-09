from enum import Enum

from trigger_agent_speed import AgentSpeedTrigger
from trigger_ego_mileage import EgoMileageTrigger
from trigger_ego_in_small_road import EgoInSmallRoadTrigger
from trigger_base import ActionBaseTrigger
from trigger_relative_dist import RelativeDistTrigger
from trigger_longtitude_dist import LongtitudeDistTrigger
from trigger_lateral_dist import LateralDistTrigger
from trigger_ego_intersection import EgoIntersectionTrigger
from trigger_agent_mileage import AgentMileageTrigger
from trigger_ego_time import EgoTimeTrigger

class ActionLifeSpan(Enum):
    WAITING = 0
    RUNNING = 1
    FINISHED = 2

class ActionBaseDelegate:
    def __init__(self, action_config):
        self.action_type_ = action_config.get("action_type")
        self.life_span_ = ActionLifeSpan.WAITING
        self.agent_id_ = action_config.get("agent_id")
        self.bstart_ = False
        self.bend_ = False
        self.action_triggers_ = []

        for trigger_config in action_config.get("trigger_config"):
            trigger_config["agent_id"] = self.agent_id_
            trigger = None
            trigger_type = trigger_config.get("trigger_type")
            if trigger_type == "TRIGGER_EGO_MILEAGE":
                trigger = EgoMileageTrigger(trigger_config)
            elif trigger_type == "TRIGGER_RELATIVE_DIST":
                trigger = RelativeDistTrigger(trigger_config)
            elif trigger_type == "TRIGGER_AGENT_MILEAGE":
                trigger = AgentMileageTrigger(trigger_config)
            elif trigger_type == "TRIGGER_EGO_TIME":
                trigger = EgoTimeTrigger(trigger_config)
            if not trigger:
                print(f"trigger of type {trigger_type} is None")
            else:
                self.action_triggers_.append(trigger)

    def __del__(self):
        self.action_triggers_ = []

    def get_type(self):
        return self.action_type_

    def is_waiting(self):
        return self.life_span_ == ActionLifeSpan.WAITING

    def is_running(self):
        return self.life_span_ == ActionLifeSpan.RUNNING

    def is_finished(self):
        return self.life_span_ == ActionLifeSpan.FINISHED

    def should_trigger(self, agent_data):
        if not self.action_triggers_:
            return False
        for trigger in self.action_triggers_:
            if not trigger.alive() or not trigger.is_trigger_activated(agent_data):
                return False
        # fire triggers!
        for trigger in self.action_triggers_:
            trigger.set_triggered(True)
        return True

    def trigger_alive(self):
        if not self.action_triggers_:
            return False
        for trigger in self.action_triggers_:
            if not trigger.alive():
                return False
        return True

    def run_one_step(self):
        raise NotImplementedError("Subclasses should implement this method.")
