import os
import argparse
import sys

# 让 Python 能找到 agent_service 下的 configs
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'agent_service'))
from agent_service.trajectory_visualizer import TrajectoryVisualizer

def parse_args():
    parser = argparse.ArgumentParser(description="Trajectory Visualization")
    parser.add_argument(
        "--local_path",
        type=str,
        required=True,
        help="The local path where the scenario files are located."
    )
    parser.add_argument(
        "--scenario_date_id",
        type=str,
        required=True,
        help="The ID of the scenario to visualize."
    )
    return parser.parse_args()

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

    config_dir = os.path.join(args.local_path, "agent_config", args.scenario_date_id)

    vis_yaml_path = find_vis_yaml_in_dir(config_dir)
    if not vis_yaml_path:
        print(f"No visualization YAML file found in {config_dir}.")
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
        save_dir=config_dir
    )

    