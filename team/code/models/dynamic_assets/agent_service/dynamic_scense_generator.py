import os
import argparse
from agent_service_main import generate_new_config

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='dynamic_scense_generator')
    parser.add_argument('model_path', type=str, help='3dgs model路径')
    parser.add_argument('dynamic_config_path', type=str, help='动态场景配置路径')
    parser.add_argument('dynamic_dataset_config_path', type=str, help='动态资产配置路径')
    
    args = parser.parse_args()

    print("model_path: ", args.model_path)
    print("dynamic_config_path: ", args.dynamic_config_path)
    print("dynamic_dataset_config_path: ", args.dynamic_dataset_config_path)

    config_sim_path = os.path.join(args.model_path, "model1", "configs_bak", "config_sim.yaml")
    new_config_sim_path = os.path.join(args.model_path, "model1", "configs")
    if not os.path.exists(new_config_sim_path):
        os.makedirs(new_config_sim_path)
    output_path = os.path.join(new_config_sim_path, "config_sim.yaml")
    generate_new_config(args.dynamic_config_path, config_sim_path, output_path, args.dynamic_dataset_config_path)
