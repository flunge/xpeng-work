from trigger_base import ActionBaseTrigger
import math

class LateralDistTrigger(ActionBaseTrigger):
    def __init__(self, trigger_config):
        super().__init__(trigger_config)
        self.spec_ = trigger_config.lateral_dist() if trigger_config.trigger_type() == proto.TriggerType.TRIGGER_LATERAL_DIST else None
        if not self.spec_:
            print("trigger type is not TRIGGER_LATERAL_DIST")

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
        yaw_diff = RelativeYawDiff(ego_yaw, ego_agent_connection.Angle())
        agent_lat_dist = ego_agent_connection.Length() * math.sin(yaw_diff)
        print(f"LateralDistTrigger::isTriggerActivated: agent_id = {agent_id}  cur lon dist =  {agent_lat_dist}, trigger dist upperbound{self.spec_.ego_agent_lateral_distance_upperbound()}, trigger dist lowbound{self.spec_.ego_agent_lateral_distance_lowbound()}")
        if agent_lat_dist <= self.spec_.ego_agent_lateral_distance_upperbound() and agent_lat_dist >= self.spec_.ego_agent_lateral_distance_lowbound():
            return True
        return False