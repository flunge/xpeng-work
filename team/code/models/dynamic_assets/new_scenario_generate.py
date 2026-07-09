import os
import argparse
import sys
import logging

logging.basicConfig(level=logging.INFO)

# 让 Python 能找到 agent_service 下的 configs
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'agent_service'))

from agent_service.agent_service_main import generate_new_config
from agent_service.trajectory_visualizer import TrajectoryVisualizer

def parse_args():
    parser = argparse.ArgumentParser(description="OSS File Downloader")
    parser.add_argument(
        "--local_path",
        type=str,
        required=True,
        help="The local path where the file will be saved."
    )
    parser.add_argument(
        "--model_name",
        type=str,
        required=True,
        help="The name of the model to be used in the scenario."
    )
    parser.add_argument(
        "--scenario_date_id",
        type=str,
        required=True,
        help="The ID of the new scenario."
    )
    return parser.parse_args()

def move_new_config_to_scenario_dir(new_config_path, scenario_dir):
    config_base_name =  os.path.basename(new_config_path)
    new_config_scenario_path = os.path.join(scenario_dir, "model1", "dynamic_assets_ply", config_base_name)
    cmd_move_config = f"mv {new_config_path} {new_config_scenario_path}"
    os.system(cmd_move_config)
    print(f"Moved new config to {new_config_scenario_path}")

def find_vis_yaml_in_dir(config_dir):
    for root, dirs, files in os.walk(config_dir):
        for file in files:
            if file.endswith("_vis.yaml"):
                return os.path.join(root, file)
    return None

def extract_gid_in_yaml_name(yaml_path):
    # extract 1319 in model_000001319_vis.yaml
    base_name = os.path.basename(yaml_path)
    number_str = base_name.replace("_vis.yaml", "").replace("model_", "")
    if number_str.isdigit():
        return int(number_str)
    return None

if __name__ == "__main__":
    args = parse_args()
    agent_scenario_path = os.path.join(args.local_path, "agent_config", args.scenario_date_id)

    agent_config_path = os.path.join(agent_scenario_path, "agent_service_config.json")
    config_sim_path = os.path.join(agent_scenario_path, "config_sim.yaml")
    new_config_sim_path = os.path.join(agent_scenario_path, args.model_name + ".yaml")
    dynamic_dataset_config_path = os.path.join(agent_scenario_path, "dynamic_dataset_config.csv")

    generate_new_config(agent_config_path, config_sim_path, new_config_sim_path, dynamic_dataset_config_path)

    # move new config to scenario dir
    scenario_dir = os.path.join(args.local_path, "scenarios", args.scenario_date_id)
    move_new_config_to_scenario_dir(new_config_sim_path, scenario_dir)

    vis_yaml_path = find_vis_yaml_in_dir(agent_scenario_path)
    if not vis_yaml_path:
        print(f"No visualization YAML file found in {agent_scenario_path}.")
        exit(1)
    print(f"Found visualization YAML file: {vis_yaml_path}")

    gid = extract_gid_in_yaml_name(vis_yaml_path)
    if not gid:
        print(f"No gid found in visualization YAML file: {vis_yaml_path}")
        exit(1)

    print(f"Extracted gid: {gid}")

    visualizer = TrajectoryVisualizer(vis_yaml_path)
    visualizer.visualize(
        selected_gids=[gid], 
        save_dir=agent_scenario_path
    )