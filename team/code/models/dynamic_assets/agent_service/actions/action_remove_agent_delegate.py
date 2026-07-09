from action_base_delegate import ActionBaseDelegate

class RemoveAgentDelegate(ActionBaseDelegate):
    def __init__(self, action_config):
        super().__init__(action_config)
        self.spec_ = action_config.action_remove_agent_spec()

    def RunOneStep(self):
        if self.life_span_ == ActionLifeSpan.FINISHED:
            return
        agent_data = AgentDataField.Instance()
        if not agent_data:
            print("agent_data is nullptr")
            return
        if not self.TriggerAlive():
            self.life_span_ = ActionLifeSpan.FINISHED
            return
        if self.life_span_ == ActionLifeSpan.WAITING and self.ShouldTrigger(agent_data):
            print(f"RemoveAgentDelegate::RunOneStep: agent {self.spec_.agent_id()} try remove")
            _success = agent_data.removeAgent(self.spec_.agent_id())
            if _success:
                print(f"RemoveAgentDelegate::RunOneStep: agent {self.spec_.agent_id()} removed successfully")
            self.life_span_ = ActionLifeSpan.FINISHED