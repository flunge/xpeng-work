class ActionBaseTrigger:
    def __init__(self, trigger_config):
        self.trigger_type_ = trigger_config.get("trigger_type")
        self.repeat_ = trigger_config.get("repeat")
        self.triggered_ = False

    def get_type(self):
        return self.trigger_type_

    def alive(self):
        return not (not self.repeat_ and self.triggered_)

    def set_triggered(self, triggered):
        self.triggered_ = triggered

    def is_trigger_activated(self, agent_data):
        return False