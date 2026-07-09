from threading import local

_thread_local = local()

class AgentDataField:
    _instance = None

    def __new__(cls):
        if not hasattr(_thread_local, 'agent_data_field_instance'):
            _thread_local.agent_data_field_instance = super().__new__(cls)
            _thread_local.agent_data_field_instance.dynamic_agent_map = {}
            _thread_local.agent_data_field_instance.static_agent_map = {}
        return _thread_local.agent_data_field_instance
        # if cls._instance is None:
        #     cls._instance = super().__new__(cls)
        #     cls._instance.dynamic_agent_map = {}
        #     cls._instance.static_agent_map = {}
        # return cls._instance

    def add_dynamic_agent(self, agent):
        self.dynamic_agent_map[agent.id()] = agent
        return True

    def add_static_agent(self, agent):
        self.static_agent_map[agent.id()] = agent
        return True

    def remove_agent(self, agent_id):
        if agent_id in self.dynamic_agent_map:
            del self.dynamic_agent_map[agent_id]
            return True
        elif agent_id in self.static_agent_map:
            del self.static_agent_map[agent_id]
            return True
        return False

    def get_dynamic_agent(self, agent_id):
        return self.dynamic_agent_map.get(agent_id)

    def get_static_agent(self, agent_id):
        return self.static_agent_map.get(agent_id)

    def mutable_dynamic_agent_map(self):
        return self.dynamic_agent_map

    def mutable_static_agent_map(self):
        return self.static_agent_map