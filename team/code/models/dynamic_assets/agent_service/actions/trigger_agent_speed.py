from trigger_base import ActionBaseTrigger

class AgentSpeedTrigger(ActionBaseTrigger):
    def __init__(self, trigger_config):
        super().__init__(trigger_config)
        self.spec_ = trigger_config.agent_speed() if trigger_config.trigger_type() == proto.TriggerType.TRIGGER_AGENT_SPEED else None
        if not self.spec_:
            print("trigger type is not TRIGGER_AGENT_SPEED")

    def is_trigger_activated(self, agent_data):
        if not self.spec_:
            print("spec is invalid")
            return False
        if not agent_data:
            print("agent_data is nullptr")
            return False
        agent_id = self.spec_.agent_id()
        agent = agent_data.getDynamicAgent(agent_id)
        if not agent:
            print(f"cannot find agent {agent_id}")
            return False
        if not agent.is_dynamic():
            print(f"{agent_id} only dynamic agent allow speed accel action")
            return False
        if not agent.is_inited():
            print(f"agent {agent_id} is not inited")
            return False
        dynamic_agent = agent if isinstance(agent, DynamicAgent) else None
        cur_speed = (dynamic_agent.motion().vx().mu() ** 2 + dynamic_agent.motion().vy().mu() ** 2) ** 0.5
        print(f"AgentSpeedTrigger::isTriggerActivated: {agent_id} cur_speed = {cur_speed} target speed = {self.spec_.speed_lowerbound()} {self.spec_.speed_upperbound()}")
        if self.spec_.compare_method() == -1:
            if cur_speed <= self.spec_.speed_upperbound() / 3.6:
                return True
        elif self.spec_.compare_method() == 1:
            if cur_speed >= self.spec_.speed_lowerbound() / 3.6:
                return True
        else:
            if cur_speed <= (self.spec_.speed_upperbound() / 3.6) and cur_speed >= (self.spec_.speed_lowerbound() / 3.6):
                return True
        return False