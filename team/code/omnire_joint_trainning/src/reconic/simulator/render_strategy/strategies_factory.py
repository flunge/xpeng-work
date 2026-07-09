# strategies_factory.py
import os
from reconic.simulator.render_config_manager.render_config_manager import SimulatorConfigManager
from reconic.simulator.render_strategy.default_render_strategy import DefaultRenderStrategy

class RenderStrategyFactory:
    _strategy_cache = {}

    @staticmethod
    def create_strategy():
        strategy_class = RenderStrategyFactory._get_render_strategy_class()
        if strategy_class not in RenderStrategyFactory._strategy_cache:
            RenderStrategyFactory._strategy_cache[strategy_class] = strategy_class()
        
        return RenderStrategyFactory._strategy_cache[strategy_class]
    
    @staticmethod
    def _get_render_strategy_class():
        simulator_config_manager = SimulatorConfigManager.get_instance()
        strategies_config = simulator_config_manager.get_render_strategies_config()
        
        for strategy_config in strategies_config:
            if RenderStrategyFactory._check_strategy_conditions(strategy_config["conditions"]):
                return RenderStrategyFactory._import_strategy_class(strategy_config["class_name"])
        return DefaultRenderStrategy
    
    @staticmethod
    def _check_strategy_conditions(conditions):
        return any(condition() for condition in conditions)
    
    @staticmethod
    def _import_strategy_class(class_name):
        module_name = RenderStrategyFactory._class_to_module_name(class_name)
        full_module_path = f"reconic.simulator.render_strategy.{module_name}"
        try:
            module = __import__(full_module_path, fromlist=[class_name])
            return getattr(module, class_name)
        except (ImportError, AttributeError) as e:
            print(f"Warning: Failed to import {class_name} from {full_module_path}: {e}")
            return DefaultRenderStrategy

    @staticmethod
    def _class_to_module_name(class_name):
        import re
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', class_name)
        module_name = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
        return module_name
