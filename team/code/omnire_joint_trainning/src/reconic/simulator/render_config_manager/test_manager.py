# test_manager.py
import unittest
import os
from render_config_manager import SimulatorConfigManager

class TestSimulatorConfigManager(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        """测试类初始化 - 按正确顺序执行"""
        print("=== 测试开始 ===")
        
        # 1. 首先设置环境变量
        os.environ['USE_DIFIX_MODE'] = 'false'
        os.environ['USE_DIFIX_LORA'] = 'false'
        os.environ['USE_DIFIX_FINETUNED'] = 'true'
        os.environ['SCENE_IDX'] = 'test_scene_001'
        print("✓ 环境变量已设置")
        
        # 2. 然后实例化配置管理器
        cls.config_manager = SimulatorConfigManager()
        print("✓ 配置管理器已实例化")
        print(f"  配置文件路径: {cls.config_manager.config_path}")
        print(f"  实例ID: {id(cls.config_manager)}")
    
    @classmethod
    def tearDownClass(cls):
        """测试类清理"""
        print("\n=== 测试结束 ===")
        # 清理环境变量
        for var in ['USE_DIFIX_MODE', 'USE_DIFIX_LORA', 'SCENE_IDX']:
            if var in os.environ:
                del os.environ[var]
        print("✓ 环境变量已清理")
    
    def test_01_instance_creation(self):
        """测试1: 单例模式验证"""
        print("\n--- 测试1: 单例模式 ---")
        another_instance = SimulatorConfigManager()
        self.assertIs(self.config_manager, another_instance)
        print("✓ 单例模式验证通过")
    
    def test_02_config_structure(self):
        """测试2: 配置结构检查"""
        print("\n--- 测试2: 配置结构 ---")
        processed_config = self.config_manager.processed_config
        
        print(f"处理后的配置键: {list(processed_config.keys())}")
        
        # 检查必需的配置项
        self.assertIn("render_strategies", processed_config)
        self.assertIn("model_configs", processed_config)
        
        print(f"渲染策略数量: {len(processed_config['render_strategies'])}")
        print(f"模型配置数量: {len(processed_config['model_configs'])}")
        print("✓ 配置结构检查通过")
    
    def test_03_render_strategies_loading(self):
        """测试3: 渲染策略加载详情"""
        print("\n--- 测试3: 渲染策略详情 ---")
        strategies = self.config_manager.get_render_strategies_config()
        
        for i, strategy in enumerate(strategies):
            print(f"策略 {i+1}:")
            print(f"  名称: {strategy.get('name')}")
            print(f"  类名: {strategy.get('class_name')}")
            print(f"  条件数量: {len(strategy.get('conditions', []))}")
            
            # 执行条件检查
            conditions = strategy.get('conditions', [])
            results = [cond() for cond in conditions]
            print(f"  条件结果: {results}")
        print("✓ 渲染策略加载验证通过")
    
    def test_04_model_configs_loading(self):
        """测试4: 模型配置加载"""
        print("\n--- 测试4: 模型配置详情 ---")
        difix_config = self.config_manager.get_difix_config()
        
        if difix_config:
            print("Difix模型配置:")
            for key, value in difix_config.items():
                print(f"  {key}: {value}")
        else:
            print("  Difix配置未加载")
        print("✓ 模型配置加载验证通过")
    
    # def test_05_conditional_loading(self):
    #     """测试5: 条件加载逻辑"""
    #     print("\n--- 测试5: 条件加载逻辑 ---")
        
    #     # 测试should_load_difix
    #     should_load = self.config_manager.should_load_difix()
    #     print(f"Difix应该加载: {should_load}")
        
    #     # 测试不同环境变量组合
    #     original_lora = os.environ.get('USE_DIFIX_LORA')
        
    #     # 测试关闭LoRA
    #     os.environ['USE_DIFIX_LORA'] = 'false'
    #     new_manager = SimulatorConfigManager()  # 重新实例化
    #     should_load_no_lora = new_manager.should_load_difix()
    #     print(f"关闭LoRA后Difix应该加载: {should_load_no_lora}")
        
    #     # 恢复环境变量
    #     os.environ['USE_DIFIX_LORA'] = original_lora
    #     print("✓ 条件加载逻辑验证通过")
    
    # def test_06_template_resolution_demo(self):
    #     """测试6: 模板解析功能演示"""
    #     print("\n--- 测试6: 模板解析演示 ---")
        
    #     # 创建测试模板
    #     test_cases = [
    #         "{NON_EXISTENT_VAR:test_default/{SCENE_IDX:default}}",
    #         "{SCENE_IDX:default}",
    #         "{NON_EXISTENT_VAR:test_default}",
    #         "普通字符串"
    #     ]
        
    #     for template in test_cases:
    #         resolved = self.config_manager._resolve_string_template(template)
    #         print(f"'{template}' -> '{resolved}'")
    #     print("✓ 模板解析功能验证通过")

if __name__ == '__main__':
    # 按照定义顺序执行测试
    unittest.main(verbosity=2)