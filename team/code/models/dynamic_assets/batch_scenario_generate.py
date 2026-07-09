import argparse
import os
import logging
import pandas as pd
import json
import new_scenario_generate as nsg

from agent_service.agent_service_main import generate_new_config
from agent_service.trajectory_visualizer import TrajectoryVisualizer


logging.basicConfig(level=logging.INFO)

def parse_args():
    parser = argparse.ArgumentParser(description="Batch Scenario Generator")
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

def read_csv_from_path(csv_path):
    if not os.path.exists(csv_path):
        logging.error(f"CSV file {csv_path} does not exist.")
        return None
    df = pd.read_csv(csv_path)
    logging.info(f"Read CSV file from {csv_path} with {len(df)} rows.")
    return df

def convert_csv_to_scenaro_json_list(df, model_name):
    scenario_json_list = []

    model_id = extract_model_id_from_model_name(model_name)
    if model_id is None:
        logging.error(f"Failed to extract model ID from model name: {model_name}")
        return scenario_json_list

    for index, row in df.iterrows():
        scenario_json = {
            "keep_original_objects": False,
            "objects": []
        }

        object_action_info = {
            "id": model_id, 
            "agent_configs": {
                "agent_attributes": {
                        "data_uid": model_id,
                        "type": "AGENT_VEHICLE",
                        "driver_model": "DRIVER_MODEL_DEFAULT"
                },
                "init_state_spec": {},
            },
            "action_configs": [],
        }

        # process init state
        pos_type = row["init_pos_type"]
        if pos_type == "RELATIVE_EGO_PATH_POS": 
            relative_ego_path_pos = {
                "ds": float(row["relative_ds"]),
                "dl": float(row["relative_dl"]),
                "dangle": float(row["d_angle"]),
            }
            velocity = row["velocity"]
            if pd.notna(velocity):
                relative_ego_path_pos["velocity"] = float(velocity)
            object_action_info["agent_configs"]["init_state_spec"] = {
                "pos_type": "RELATIVE_EGO_PATH_POS",
                "relative_ego_path_pos": relative_ego_path_pos,
            }
        elif pos_type == "RELATIVE_EGO_POS":
            relative_ego_pos = {
                "seconds": int(row["relative_sec"]),
                "ds": float(row["relative_ds"]),
                "dl": float(row["relative_dl"]),
                "dangle": float(row["d_angle"]),
            }
            velocity = row["velocity"]
            v_param = row["v_param"]
            if pd.notna(v_param):
                relative_ego_pos["v_param"] = float(v_param)
            if pd.notna(velocity):
                relative_ego_pos["velocity"] = float(velocity)
            object_action_info["agent_configs"]["init_state_spec"] = {
                "pos_type": "RELATIVE_EGO_POS",
                "relative_ego_pos": relative_ego_pos,
            }
        else:
            logging.warning(f"Unknown init_pos_type {pos_type} at row {index}, skipping.")
            continue
        
        # process action configs
        action_type = row["action_type"]
        action_config = {}
        if action_type == "ACTION_CHANGE_LANE":
            action_config = {
                "action_type": "ACTION_CHANGE_LANE",
                "action_change_lane_spec": {
                    "target_lane_index": int(row["trg_lane_idx"]),  # 变道方向和变道数量，1车道是按3米实现。+：往右变道  -：往左变道
                    "lane_change_duration": int(row["lc_duration"])  # 完成变道时间，单位：秒
                },
                "trigger_config": []
            }
        elif action_type == "ACTION_AGENT_ACCEL":
            accel_property = {
                "a": float(row["accel_a"]),
            }
            accel_auto = row["accel_auto"]
            if pd.notna(accel_auto) and str(accel_auto).strip():
                accel_property["auto_a"] = str(accel_auto).strip()
            action_config = {
                "action_type": "ACTION_AGENT_ACCEL",
                "speed_accel_spec": {
                    "accel_property": accel_property
                },
                "trigger_config": []
            }
        else:
            logging.warning(f"Unknown action_type {action_type} at row {index}, skipping.")
            continue

        # process trigger config
        trigger_type = row["trigger_type"]
        trigger_config = {}

        trigger_repeat = row["trigger_repeat"]
        repeat_val = bool(trigger_repeat) if pd.notna(trigger_repeat) else False

        if trigger_type == "TRIGGER_EGO_MILEAGE":
            trigger_config = {
                "trigger_type": "TRIGGER_EGO_MILEAGE",
                "repeat": repeat_val,
                "ego_mileage": {
                    "mileage": float(row["ego_mileage"])
                }
            }
        elif trigger_type == "TRIGGER_EGO_TIME":
            trigger_config = {
                "trigger_type": "TRIGGER_EGO_TIME",
                "repeat": repeat_val,
                "ego_time": {
                    "seconds": float(row["ego_time"])
                }
            }
        else: 
            logging.warning(f"Unknown trigger_type {trigger_type} at row {index}, skipping.")
            continue

        action_config["trigger_config"].append(trigger_config)
        object_action_info["action_configs"].append(action_config)

        scenario_json["objects"].append(object_action_info)

        scenario_json_list.append(scenario_json)
    logging.info(f"Converted CSV data to {len(scenario_json_list)} scenario JSON entries.")
    return scenario_json_list

def extract_model_id_from_model_name(model_name):
    # assuming model_name is like "model_000001319"
    parts = model_name.split("_")
    if len(parts) != 2 or not parts[1].isdigit():
        logging.error(f"Invalid model name format: {model_name}")
        return None
    return int(parts[1])

def output_json_file_to_config_dir(scenario_json_list, config_dir, scenario_date_id, model_name):
    # check scenario_json_list is not empty
    if not scenario_json_list:
        logging.error("No scenario JSON data to write.")
        return
    
    for idx, scenario_json in enumerate(scenario_json_list):
        output_json_dir = os.path.join(config_dir, f"{scenario_date_id}_{idx+1}")
        os.makedirs(output_json_dir, exist_ok=True)
        output_json_path = os.path.join(output_json_dir, "agent_service_config.json")

        with open(output_json_path, "w") as json_f:
            json.dump(scenario_json, json_f, indent=4)
        logging.info(f"Wrote scenario JSON to {output_json_path}")

        config_sim_path = os.path.join(config_dir, "config_sim.yaml")
        new_config_sim_path = os.path.join(output_json_dir, model_name + ".yaml")
        dynamic_dataset_config_path = os.path.join(config_dir, "dynamic_dataset_config.csv")

        generate_new_config(output_json_path, config_sim_path, new_config_sim_path, dynamic_dataset_config_path)

        vis_yaml_path = nsg.find_vis_yaml_in_dir(output_json_dir)
        if not vis_yaml_path:
            print(f"No visualization YAML file found in {output_json_dir}.")
            exit(1)
        print(f"Found visualization YAML file: {vis_yaml_path}")

        gid = nsg.extract_gid_in_yaml_name(vis_yaml_path)
        if not gid:
            print(f"No gid found in visualization YAML file: {vis_yaml_path}")
            exit(1)

        print(f"Extracted gid: {gid}")

        visualizer = TrajectoryVisualizer(vis_yaml_path)
        visualizer.visualize(
            selected_gids=[gid], 
            save_dir=output_json_dir
        )



def batch_process_csv_to_scenario_json(local_path, scenario_date_id, model_name):
    config_dir = os.path.join(local_path, "agent_config", scenario_date_id)
    csv_path = os.path.join(config_dir, "scenario_edit.csv")
    df = read_csv_from_path(csv_path)
    if df is None:
        return []

    scenario_json_list = convert_csv_to_scenaro_json_list(df, model_name)

    output_json_file_to_config_dir(scenario_json_list, config_dir, scenario_date_id, model_name)

if __name__ == "__main__":
    args = parse_args()
    agent_scenario_path = os.path.join(args.local_path, "agent_config", args.scenario_date_id)
    batch_process_csv_to_scenario_json(args.local_path, args.scenario_date_id, args.model_name)
    logging.info(f"Batch processed CSV to scenario JSON in {agent_scenario_path}")
