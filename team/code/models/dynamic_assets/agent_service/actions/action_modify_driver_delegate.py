from action_base_delegate import ActionBaseDelegate

class ModifyDriverDelegate(ActionBaseDelegate):
    def __init__(self, action):
        super().__init__(action)
        self.spec_ = action.action_modify_driver_parm_spec()

    def RunOneStep(self):
        if self.life_span_ == ActionLifeSpan.FINISHED:
            return
        agent_data = AgentDataField.Instance()
        if not agent_data:
            print("agent_data is nullptr")
            return
        agent_id = self.spec_.agent_id()
        agent = agent_data.getDynamicAgent(agent_id)
        if not agent:
            print(f"cannot find agent {agent_id}")
            return
        if not agent.IsDynamic():
            print("only dynamic agent allow speed accel action")
            return
        if self.ShouldTrigger(agent_data):
            print(f"{agent_id}:ModifyDriverParm: ")
            dynamic_agent = agent if isinstance(agent, DynamicAgent) else None
            if self.spec_.modify_parm().modify_target_speed():
                dynamic_agent.AdjustTargetSpeed(self.spec_.target_speed())
                print(f"{agent_id}:AdjustTargetSpeed {self.spec_.target_speed()}")
            if self.spec_.modify_parm().modify_max_acc():
                dynamic_agent.AdjustMaxAcc(self.spec_.max_acc())
                print(f"{agent_id}:AdjustMaxAcc {self.spec_.max_acc()}")
            if self.spec_.modify_parm().modify_max_dcc():
                dynamic_agent.AdjustMaxDcc(self.spec_.max_dcc())
                print(f"{agent_id}:AdjustMaxDcc {self.spec_.max_dcc()}")
            self.life_span_ = ActionLifeSpan.RUNNING
        if not self.TriggerAlive():
            self.life_span_ = ActionLifeSpan.FINISHED