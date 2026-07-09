from trigger_base import ActionBaseTrigger
import math

class LongtitudeDistTrigger(ActionBaseTrigger):
    def __init__(self, trigger_config):
        super().__init__(trigger_config)
        self.spec_ = trigger_config.longtitude_dist() if trigger_config.trigger_type() == proto.TriggerType.TRIGGER_LONGTITUDE_DIST else None
        if not self.spec_:
            print("trigger type is not TRIGGER_LONGTITUDE_DIST")

    def isTriggerActivated(self, agent_data):
        if not self.spec_:
            print("spec is invalid")
            return False
        if not agent_data:
            print("agent_data is nullptr")
            return False
        agent_id = self.spec_.agent_id()
        agent = agent_data.getAgent(agent_id)
        if not agent:
            print(f"cannot find agent {agent_id}")
            return False
        if not agent.IsInited():
            print(f"agent {agent_id} is not inited")
            return False
        loc = EgoState.Instance().GetCurrentLocalization()
        ego_x = loc.ego_motion().x()
        ego_y = loc.ego_motion().y()
        ego_yaw = loc.ego_motion().yaw()
        agent_x = agent.pose2d().x()
        agent_y = agent.pose2d().y()
        ego_agent_connection = Vec2d(agent_x - ego_x, agent_y - ego_y)
        yaw_diff = AbsoluteYawDiff(ego_yaw, ego_agent_connection.Angle())
        agent_lon_dist = ego_agent_connection.Length() * math.cos(yaw_diff)
        print(f"LongtitudeDistTrigger::isTriggerActivated: agent_id = {agent_id}  cur lon dist =  {agent_lon_dist}, trigger dist upperbound{self.spec_.ego_agent_longtitude_distance_upperbound()}, trigger dist lowbound{self.spec_.ego_agent_longtitude_distance_lowbound()}")
        if agent_lon_dist <= self.spec_.ego_agent_longtitude_distance_upperbound() and agent_lon_dist >= self.spec_.ego_agent_longtitude_distance_lowbound():
            print("LongtitudeDistTrigger::isTriggerActivated: activate!!!")
            return True
        return False