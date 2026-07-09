# config_manager.py
import os
import re
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, List
from omegaconf import OmegaConf, DictConfig

class SimulatorConfigManager:
    _instance = None
    _initialized = False
    
    def __new__(cls, scene_idx: str = ''):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, scene_idx: str = ''):
        if not self._initialized:
            # if config_path is None:
            current_dir = Path(__file__).parent
            config_path = current_dir / "render_config.yaml"
            
            self.config_path = str(config_path)
            self.clip_id = scene_idx
            self.update_current_scene(scene_idx)
            self.raw_config = self._load_yaml_config()
            self.processed_config = self._process_config()
            self._initialized = True
    
    @classmethod
    def get_instance(cls, scene_idx: str = ''):
        if cls._instance is None:
            cls._instance = cls(scene_idx)
        return cls._instance

    def _load_yaml_config(self) -> DictConfig:
        with open(self.config_path, 'r', encoding='utf-8') as f:
            yaml_content = yaml.safe_load(f)
        return OmegaConf.create(yaml_content)
    
    
    def _process_config(self) -> Dict[str, Any]:
        processed = {
            "render_strategies": self._process_render_strategies(),
            "model_configs": self._process_model_configs(),
        }
        return processed
    
    def _process_render_strategies(self) -> List[Dict]:
        strategies = []
        
        if not hasattr(self.raw_config.simulator, 'render_strategies'):
            print("Warning: No render_strategies found in configuration, using default strategy")
            return [{
                "name": "default",
                "class_name": "DefaultRenderStrategy",
                "conditions": [lambda: True]
            }]
        
        for name, strategy_config in self.raw_config.simulator.render_strategies.items():
            if not strategy_config.enabled:
                print(f"Info: Skipping disabled strategy '{name}'")
                continue
                
            strategy = {
                "name": name,
                "class_name": strategy_config.strategy_class,
                "conditions": self._parse_conditions(strategy_config.conditions)
            }
            strategies.append(strategy)
        
        if not any(s["name"] == "default" for s in strategies):
            print("Info: Adding default fallback strategy")
            strategies.append({
                "name": "default",
                "class_name": "DefaultRenderStrategy",
                "conditions": [lambda: True]
            })
        
        print(f"Info: Processed {len(strategies)} render strategies")
        return strategies
    
    def _process_model_configs(self) -> Dict[str, Any]:
        if not hasattr(self.raw_config.simulator, 'models'):
            return {}
        
        model_configs = {}
        
        for model_name, model_config in self.raw_config.simulator.models.items():
            if not hasattr(model_config, 'base') or not model_config.base.enabled:
                continue
                
            base_conditions_met = all(condition() for condition in self._parse_conditions(model_config.base.conditions))
            
            has_active_variants = False
            active_variants = []
            
            if hasattr(model_config, 'variants'):
                active_variants = self._get_active_variants(model_config.variants)
                has_active_variants = len(active_variants) > 0
            
            if not base_conditions_met and not has_active_variants:
                continue
                
            final_config = OmegaConf.to_container(model_config.base.config)
            
            if has_active_variants:
                for variant in active_variants:
                    overrides = OmegaConf.to_container(variant.config_overrides)
                    final_config.update(overrides)

            self._resolve_templates(final_config)
            
            model_configs[model_name] = final_config
            print(f"Successfully load {model_name} model config")
            print(final_config)
        return model_configs

    def _resolve_templates(self, config: Dict[str, Any]) -> None:
        for key, value in config.items():
            if isinstance(value, str):
                config[key] = self._resolve_string_template(value)
            elif isinstance(value, dict):
                self._resolve_templates(value)

    
    def _resolve_string_template(self, template_str: str) -> str:
        pattern = re.compile(r'\{([^{}:]+)(?::([^{}]*))?\}')
        
        def replacer(match):
            var_name = match.group(1).strip()
            default_value = match.group(2).strip() if match.group(2) else ''
            
            env_value = os.getenv(var_name, '').strip()
            
            return env_value if env_value else default_value

        previous_str = None
        current_str = template_str
        
        
        while previous_str != current_str:
            previous_str = current_str
            current_str = pattern.sub(replacer, current_str)

            
        return current_str 
    
    def _parse_conditions(self, conditions) -> List[callable]:
        
        parsed_conditions = []
        
        for condition in conditions:
            if hasattr(condition, 'always') and condition.always:
                parsed_conditions.append(lambda: True)
            elif hasattr(condition, 'env'):
                env_var = condition.env
                expected_value = condition.value
                parsed_conditions.append(
                    lambda env=env_var, val=expected_value: os.getenv(env, '') == val
                )
        
        return parsed_conditions
    
    def _get_active_variants(self, variants_config) -> List[Any]:
        active_variants = []
        if not variants_config:
            return active_variants
            
        for variant_name, variant_config in variants_config.items():
            if not variant_config.enabled:
                continue
            
            if all(condition() for condition in self._parse_conditions(variant_config.conditions)):
                active_variants.append(variant_config)

        return active_variants
    
    def get_render_strategies_config(self):
        return self.processed_config["render_strategies"]
    
    def should_load_difix(self) -> bool:
        return "difix" in self.processed_config["model_configs"]

    def get_difix_config(self) -> Optional[Dict[str, Any]]:
        return self.processed_config["model_configs"].get("difix", {})
    
    def update_current_scene(self, scene_idx: str):
        print(f"Info: Updating current scene to {scene_idx}")
        os.environ["SCENE_IDX"] = scene_idx


# render_config_manager = SimulatorConfigManager()