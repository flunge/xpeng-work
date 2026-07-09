from action_base_delegate import ActionBaseDelegate

class GenerateAgentDelegate(ActionBaseDelegate):
    def __init__(self, action_config):
        super().__init__(action_config)
        self.spec_ = action_config.action_generate_agent_spec()

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
            agent = None
            _success = False
            agent_config = self.spec_.agent_config()
            if agent_config.agent_attributes().type() < proto.AgentCategory.STATIC_AGENT_CATEGORY_MASK:
                if agent_config.agent_attributes().type() in [proto.AgentCategory.AGENT_CATEGORY_SEDAN,
                                                              proto.AgentCategory.AGENT_CATEGORY_SUV,
                                                              proto.AgentCategory.AGENT_CATEGORY_TRUCK,
                                                              proto.AgentCategory.AGENT_CATEGORY_BUS,
                                                              proto.AgentCategory.AGENT_CATEGORY_VAN]:
                    if agent_config.agent_attributes().driver_model().follow_type() in [proto.DriverFollowType.DRIVER_FOLLOW_STRAIGHT,
                                                                                         proto.DriverFollowType.DRIVER_FOLLOW_RTM,
                                                                                         proto.DriverFollowType.DRIVER_FOLLOW_RTM_RETROGRADE]:
                        agent = DynamicAgent(agent_config)
                    else:
                        agent = DynamicAgentVehicle(agent_config)
                else:
                    agent = DynamicAgent(agent_config)
                _success = agent_data.addDynamicAgent(agent)
            else:
                agent = StaticAgent(agent_config)
                _success = agent_data.addStaticAgent(agent)
            if _success:
                print(f"GenerateAgentDelegate::RunOneStep: agent {agent.id()} generated successfully")
            self.life_span_ = ActionLifeSpan.FINISHED