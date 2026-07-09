from trigger_base import ActionBaseTrigger

class EgoInSmallRoadTrigger(ActionBaseTrigger):
    def __init__(self, trigger_config):
        super().__init__(trigger_config)
        self.spec_ = trigger_config.ego_in_small_road() if trigger_config.trigger_type() == proto.TriggerType.TRIGGER_EGO_IN_SMALL_ROAD else None
        if not self.spec_:
            print("trigger type is not TRIGGER_EGO_IN_SMALL_ROAD")

    def is_trigger_activated(self, agent_data):
        if not agent_data:
            print("agent_data is nullptr")
            return False
        in_small_road = EgoState.Instance().IsInSmallRoadMode()
        print(f"EgoInSmallRoadTrigger::isTriggerActivated: in_small_road  = {in_small_road}")
        if in_small_road:
            print("EgoInSmallRoadTrigger:: Activate!")
            return True
        return False