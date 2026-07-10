import os
import logging
import argparse
from datetime import datetime
import json

logging.basicConfig(level=logging.INFO)

def generate_datetime_subdir(local_base_dir):
    now = datetime.now()
    now_date_str = now.strftime("%Y-%m-%d_%H-%M-%S")
    now_date_str_with_scenario = f"Scenario_{now_date_str}"
    local_dir = os.path.join(local_base_dir, "scenarios", now_date_str_with_scenario)
    os.makedirs(local_dir, exist_ok=True)
    return local_dir

def run_cmd_and_log_out(cmd):
    logging.info(f"Running command: {cmd}")
    result = os.system(cmd)
    if result != 0:
        logging.error(f"Command failed with exit code {result}: {cmd}")
    return result

def post_process_object_path(oss_path):
    # input: oss://cloudsim-ci-sh/3dgs_dynamic/2024_01_23_11_17_18/trained_results/
    # output1: oss://cloudsim-ci-sh/3dgs_dynamic/2024_01_23_11_48_58/colmap_processed/meta.json
    # output2: oss://cloudsim-ci-sh/3dgs_dynamic/2024_01_23_11_17_18/trained_results/
    if oss_path.endswith("/"):
        oss_path = oss_path[:-1]
    base_path = "/".join(oss_path.split("/")[:-1])
    meta_json_path = f"{base_path}/colmap_processed/meta.json"
    ply_path_pattern = f"{oss_path}"
    return meta_json_path, ply_path_pattern

def download_file_from_oss(oss_path, local_path, extra_str=""):
    """
    Upload a single file to OSS.
    """
    oss_bucket = "cloudsim-ci-sh"
    oss_endpoint = "http://oss-cn-wulanchabu.aliyuncs.com"
    access_key_id = os.environ.get("OSS_ACCESS_KEY_ID", "")
    access_key_secret = os.environ.get("OSS_ACCESS_KEY_SECRET", "")

    if oss_path.startswith("oss://"):
        # remove "oss://bucket_name/" prefix
        oss_path = "/".join(oss_path.split("/")[3:])

    # ossutil -e http://oss-cn-wulanchabu.aliyuncs.com -i os.environ.get("OSS_ACCESS_KEY_ID", "") -k os.environ.get("OSS_ACCESS_KEY_SECRET", "") -r --parallel 8 cp -f "oss://cloudsim-ci-sh/sim_engine/artificially_created_scenes/c-f560ab8e-0f35-31fe-8e57-36a00fe39dd9/trained_model_202509021553/3dgs_model.tgz" ./
    cmd = f'ossutil -e {oss_endpoint} -i {access_key_id} -k {access_key_secret} -r cp -f "oss://{oss_bucket}/{oss_path}" "{local_path}" {extra_str}'
    run_cmd_and_log_out(cmd)

    target_path = os.path.join(local_path, oss_path.split("/")[-1])
    logging.info(f"Downloaded {oss_path} to {target_path}")

    return target_path

def untar_tgz_file(tar_gz_path, extract_dir):
    cmd = f"tar -xvf {tar_gz_path} -C {extract_dir}"
    run_cmd_and_log_out(cmd)
    logging.info(f"Extracted {tar_gz_path} to {extract_dir}")

def parse_args():
    parser = argparse.ArgumentParser(description="OSS File Downloader")
    parser.add_argument(
        "--scenario_oss_path",
        type=str,
        required=True,
        help="The OSS path of the file to download (relative to the bucket)."
    )
    parser.add_argument(
        "--object_oss_path",
        type=str,
        required=True,
        help="The OSS path of the object to download (relative to the bucket)."
    )
    parser.add_argument(
        "--local_path",
        type=str,
        required=True,
        help="The local path where the file will be saved."
    )
    return parser.parse_args()

def move_meta_and_ply_to_scenario_dir(meta_file_path, ply_file_path, scenario_dir):
    cmd_meta = f"mv {meta_file_path} {scenario_dir}/meta.json"
    run_cmd_and_log_out(cmd_meta)
    cmd_ply = f"mv {ply_file_path} {scenario_dir}/"
    run_cmd_and_log_out(cmd_ply)
    logging.info(f"Moved meta.json and .ply files to {scenario_dir}")

def generate_ply_dir_in_scenario(local_dir):
    scenario_dir = os.path.join(local_dir, "model1")
    os.makedirs(scenario_dir, exist_ok=True)
    # /workspace/wangyl11@xiaopeng.com/download/20251029_1456_human_2/trained_rst_origin/c-0f3210e5-5446-3700-8499-c2960d9948e7/all/dynamic_assets_ply
    ply_dir = os.path.join(scenario_dir, "dynamic_assets_ply")
    os.makedirs(ply_dir, exist_ok=True)
    return ply_dir

def move_file_2_ply_dir(file_path, ply_dir):
    cmd_move_ply = f"mv {file_path} {ply_dir}/"
    run_cmd_and_log_out(cmd_move_ply)
    logging.info(f"Moved .ply files to {ply_dir}")

    base_name = os.path.basename(file_path)
    return os.path.join(ply_dir, base_name)

def get_ply_path_in_dir(ply_dir):
    ply_files = [f for f in os.listdir(ply_dir) if f.endswith(".ply")]
    if not ply_files:
        logging.error(f"No .ply files found in {ply_dir}")
        return None
    ply_file_path = os.path.join(ply_dir, ply_files[0])
    return ply_file_path

def genrate_new_ply_name():
    # model_000000999.ply
    # start with model_*
    # number >= 900
    random_number = 900 + int(datetime.now().timestamp()) % 1000
    new_ply_name = f"model_{random_number:09d}"
    return new_ply_name

def rename_file_path(original_path, new_name):
    dir_path = os.path.dirname(original_path)
    base_path = os.path.basename(original_path)
    # retain the original file extension
    extension = os.path.splitext(base_path)[1]
    new_name = f"{new_name}{extension}"
    new_path = os.path.join(dir_path, new_name)
    cmd_rename = f"mv {original_path} {new_path}"
    
    run_cmd_and_log_out(cmd_rename)
    logging.info(f"Renamed {original_path} to {new_path}")
    return new_path

def generate_asset_config_csv(agent_config_dir, meta_file_path, ply_file_path):
    # header: id,obj_name,obj_path,length,width,height,config_sim_type
    logging.info(f"Generating asset config CSV in {agent_config_dir}, meta: {meta_file_path}, ply: {ply_file_path}")
    asset_config_csv_path = os.path.join(agent_config_dir, "dynamic_dataset_config.csv")
    with open(asset_config_csv_path, "w") as f:
        f.write("id,obj_name,obj_path,length,width,height,config_sim_type\n")
        
        # only one model
        model_file = os.path.basename(ply_file_path)
        model_id_str = model_file.replace("model_", "").replace(".ply", "")
        logging.info(f"model_id_str: {model_id_str}")
        model_id = int(model_id_str)
        obj_name = "CAR"
        obj_path = f"dynamic_assets_ply/{model_file}"

        # read length, width, height from meta.json
        with open(meta_file_path, "r") as meta_f:
            meta_data = json.load(meta_f)
            # {"bbox": [-1.6044040261478234, -0.8541682427228395, -0.6671946999336692, 1.6044040261478234, 0.8541682427228395, 0.6671946999336692]}
            bbox = meta_data.get("bbox", [-1, -1, -1, 1, 1, 1])
            length = bbox[3] - bbox[0]
            width = bbox[4] - bbox[1]
            height = bbox[5] - bbox[2]
        config_sim_type = "car"
        f.write(f"{model_id},{obj_name},{obj_path},{length},{width},{height},{config_sim_type}\n")

    logging.info(f"Generated asset config CSV at {asset_config_csv_path}, model_id: {model_id}")
    return asset_config_csv_path, model_id
    

def generate_agent_config_dir(local_path, scenario_id, scenario_dir):
    agent_config_dir = os.path.join(local_path, "agent_config", scenario_id)
    os.makedirs(agent_config_dir, exist_ok=True)

    origin_config_path = os.path.join(scenario_dir, "model1", "configs", "config_sim.yaml")
    target_config_path = os.path.join(agent_config_dir, "config_sim.yaml")

    cmd_copy_config = f"cp {origin_config_path} {target_config_path}"
    run_cmd_and_log_out(cmd_copy_config)
    logging.info(f"Generated agent config dir at {agent_config_dir}")

    return agent_config_dir

if __name__ == "__main__":
    args = parse_args()
    local_dir = generate_datetime_subdir(args.local_path)
    # local_dir = "/app/agent_config/Scenario_2025-11-26_10-53-58"
    meta_json_path, ply_path_pattern = post_process_object_path(args.object_oss_path)
    scenario_tgz_path = download_file_from_oss(args.scenario_oss_path, local_dir)
    
    untar_tgz_file(scenario_tgz_path, local_dir)
    meta_file_path = download_file_from_oss(meta_json_path, local_dir)
    ply_file_dir = download_file_from_oss(ply_path_pattern, local_dir, extra_str="--include \"*.ply\"")
    ply_file_path = get_ply_path_in_dir(ply_file_dir)
    new_ply_name = genrate_new_ply_name()

    new_ply_file_path = rename_file_path(ply_file_path, new_ply_name)

    print(f"Downloaded meta.json path: {meta_file_path}, ply files path: {ply_file_path}, new ply name: {new_ply_file_path}")

    new_ply_dir = generate_ply_dir_in_scenario(local_dir)
    new_ply_file_path = move_file_2_ply_dir(new_ply_file_path, new_ply_dir)
    new_meta_file_path = move_file_2_ply_dir(meta_file_path, new_ply_dir)

    scenario_id = os.path.basename(local_dir)

    agent_config_dir = generate_agent_config_dir(args.local_path, scenario_id, local_dir)

    _, model_id = generate_asset_config_csv(agent_config_dir, new_meta_file_path, new_ply_file_path)

    print(f"新场景的ID是 (scenario_date_id): {scenario_id}, 新的本地资产名是 (model_name): {new_ply_name}, 新的模型ID是 (model_id): {model_id}")

