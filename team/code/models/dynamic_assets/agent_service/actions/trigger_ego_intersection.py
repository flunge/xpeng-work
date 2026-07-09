from trigger_base import ActionBaseTrigger

class EgoIntersectionTrigger(ActionBaseTrigger):
    def __init__(self, trigger_config):
        super().__init__(trigger_config)
        self.spec_ = trigger_config.ego_intersection() if trigger_config.trigger_type() == proto.TriggerType.TRIGGER_EGO_INTERSECTION else None
        if not self.spec_:
            print("trigger type is not TRIGGER_EGO_INTERSECTION")

    def isTriggerActivated(self, agent_data):
        if not self.spec_:
            print("spec is invalid")
            return False
        if not agent_data:
            print("agent_data is nullptr")
            return False
        ego_loc = EgoState.Instance().GetCurrentLocalization()
        ego_x = ego_loc.ego_motion().x()
        ego_y = ego_loc.ego_motion().y()
        ego_yaw = ego_loc.ego_motion().yaw()
        xmap = acm.map.MapProvider.Instance().xmap()
        ego_intersection = xmap.GetNearestIntersection(ego_x, ego_y)
        s = 0.0
        l = 0.0
        ego_lane = xmap.GetNearestLaneWithHeading(ego_x, ego_y, ego_yaw, 5.0, math.pi / 3, s, l)
        if not ego_intersection:
            print("EgoIntersectionTrigger: ego is not near intersection")
            return False
        dis = s + self.spec_.ego_near_distance()
        target_lane = ego_lane
        print(f"EgoIntersectionTrigger: ego near intersection:{ego_intersection.id()} dis:{dis} ego_lane:{target_lane.id()}")
        print("EgoIntersectionTrigger: ego_intersection->enter_lane_id():")
        for lane_id in ego_intersection.enter_lane_id():
            print(lane_id)
        if target_lane.id() in ego_intersection.enter_lane_id():
            if dis > target_lane.length():
                print("EgoIntersectionTrigger: active!")
                return True
        while dis > target_lane.length():
            if not target_lane.successor_lane_id():
                return False
            dis -= target_lane.length()
            target_lane_id = target_lane.successor_lane_id()[0]
            target_lane = xmap.GetLaneById(target_lane_id)
            if target_lane_id in ego_intersection.enter_lane_id():
                if dis > target_lane.length():
                    print("EgoIntersectionTrigger: active!")
                    return True
        while dis < 0:
            if not target_lane.predecessor_lane_id():
                return False
            target_lane_id = target_lane.predecessor_lane_id()[0]
            target_lane = xmap.GetLaneById(target_lane_id)
            dis += target_lane.length()
            if target_lane_id in ego_intersection.enter_lane_id():
                if dis > target_lane.length() - 1.0:
                    print("EgoIntersectionTrigger: active!")
                    return True
        return False