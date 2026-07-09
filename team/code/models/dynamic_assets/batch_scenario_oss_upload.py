import os
import argparse
import logging
import oss_file_uploader as uploader

logging.basicConfig(level=logging.INFO)

def parse_args():
    parser = argparse.ArgumentParser(description="Batch OSS Uploader")
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

def get_all_sub_dirs_from_config_dir(agent_config_dir, scenario_date_id):
    sub_dirs = []
    for root, dirs, files in os.walk(agent_config_dir):
        for dir_name in dirs:
            if dir_name.startswith(scenario_date_id):
                sub_dirs.append(os.path.join(root, dir_name))
    return sub_dirs

def upload_sub_scenarios_to_oss(scenario_dir, agent_config_dir, scenario_date_id, model_name):
    sub_dirs = get_all_sub_dirs_from_config_dir(agent_config_dir, scenario_date_id)

    upload_record = {}

    for sub_dir in sub_dirs:
        sub_scenario_date_id = os.path.basename(sub_dir)
        model_config_file = os.path.join(sub_dir, f"{model_name}.yaml")
        if not os.path.exists(model_config_file):
            logging.error(f"Model config file {model_config_file} does not exist, skipping upload for {sub_dir}.")
            continue
        config_file_base_name = os.path.basename(model_config_file)
        new_config_scenario_path = os.path.join(scenario_dir, "model1", "dynamic_assets_ply", config_file_base_name)

        cmd_move_config = f"cp {model_config_file} {new_config_scenario_path}"
        os.system(cmd_move_config)
        logging.info(f"Moved config file to {new_config_scenario_path}")

        source_tgz_dir = os.path.join(scenario_dir, "model1")
        
        output_tar_gz_path = os.path.join(scenario_dir, f"{sub_scenario_date_id}.tar.gz")

        if not uploader.precheck_before_upload(source_tgz_dir):
            logging.error(f"Precheck failed for {source_tgz_dir}, skipping upload.")
            continue

        uploader.tar_gz_directory(source_tgz_dir, output_tar_gz_path)

        oss_base_path = "3dgs_scenario_engine"
        target_oss_path = f"{oss_base_path}/{sub_scenario_date_id}/3dgs_model_edited.tgz"
        uploader.upload_tgz_to_oss(output_tar_gz_path, target_oss_path)
        logging.info(f"Uploaded {output_tar_gz_path} to OSS at {target_oss_path}")
        upload_record[sub_scenario_date_id] = target_oss_path
    
    logging.info("Upload Summary: ")
    for sub_scenario, oss_path in upload_record.items():
        logging.info(f"{sub_scenario}: {oss_path}")
    

if __name__ == "__main__":
    args = parse_args()

    agent_config_dir = os.path.join(args.local_path, "agent_config", args.scenario_date_id)
    scenario_dir = os.path.join(args.local_path, "scenarios", args.scenario_date_id)

    upload_sub_scenarios_to_oss(scenario_dir, agent_config_dir, args.scenario_date_id, args.model_name)



    
