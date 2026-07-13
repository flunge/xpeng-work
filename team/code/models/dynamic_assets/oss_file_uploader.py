import os
import argparse
import logging

logging.basicConfig(level=logging.INFO)

def parse_args():
    parser = argparse.ArgumentParser(description="OSS File Downloader")
    parser.add_argument(
        "--local_path",
        type=str,
        required=True,
        help="The local path where the file will be saved."
    )
    parser.add_argument(
        "--scenario_date_id",
        type=str,
        required=True,
        help="The ID of the new scenario."
    )
    return parser.parse_args()

def run_cmd_and_log_out(cmd):
    logging.info(f"Running command: {cmd}")
    result = os.system(cmd)
    if result != 0:
        logging.error(f"Command failed with exit code {result}: {cmd}")
    return result

def tar_gz_directory(source_dir, output_tar_gz_path):
    cmd = f"tar -czvf {output_tar_gz_path} -C {source_dir} ."
    run_cmd_and_log_out(cmd)
    logging.info(f"Created tar.gz file {output_tar_gz_path} from directory {source_dir}")

def upload_tgz_to_oss(tar_gz_path, oss_path):
    """
    Upload a single file to OSS.
    """
    oss_bucket = "cloudsim-ci-sh"
    oss_endpoint = "http://oss-cn-wulanchabu.aliyuncs.com"
    access_key_id = "OSS_ACCESS_KEY_ID_REDACTED"
    access_key_secret = "OSS_ACCESS_KEY_SECRET_REDACTED"

    if oss_path.startswith("oss://"):
        # remove "oss://bucket_name/" prefix
        oss_path = "/".join(oss_path.split("/")[3:])

    cmd = f'ossutil -e {oss_endpoint} -i {access_key_id} -k {access_key_secret} cp -f "{tar_gz_path}" "oss://{oss_bucket}/{oss_path}"'
    run_cmd_and_log_out(cmd)

def precheck_before_upload(source_tgz_dir):
    if not os.path.exists(source_tgz_dir):
        logging.error(f"Source directory {source_tgz_dir} does not exist. Cannot create tar.gz.")
        return False
    
    dynamic_assets_ply_dir = os.path.join(source_tgz_dir, "dynamic_assets_ply")
    if not os.path.exists(dynamic_assets_ply_dir):
        logging.error(f"Dynamic assets PLY directory {dynamic_assets_ply_dir} does not exist.")
        return False
    
    # check if there is a ply and yaml file start with "model_"
    ply_files = [f for f in os.listdir(dynamic_assets_ply_dir) if f.endswith(".ply") and f.startswith("model_")]
    yaml_files = [f for f in os.listdir(dynamic_assets_ply_dir) if f.endswith(".yaml") and f.startswith("model_")]

    if not ply_files:
        logging.error(f"No PLY files found in {dynamic_assets_ply_dir} starting with 'model_'.")
        return False

    if not yaml_files:
        logging.error(f"No YAML files found in {dynamic_assets_ply_dir} starting with 'model_'.")
        return False

    return True

if __name__ == "__main__":
    args = parse_args()
    scenario_dir = os.path.join(args.local_path, "scenarios", args.scenario_date_id)
    if not os.path.exists(scenario_dir):
        print(f"Scenario directory {scenario_dir} does not exist.")
        exit(1)

    local_dir = args.local_path
    source_tgz_dir = os.path.join(local_dir, "scenarios", args.scenario_date_id, "model1")
    output_tar_gz_path = os.path.join(local_dir, "scenarios", args.scenario_date_id, "3dgs_model_edited.tgz")

    if not precheck_before_upload(source_tgz_dir):
        exit(1)

    tar_gz_directory(source_tgz_dir, output_tar_gz_path)

    oss_base_path = "3dgs_scenario_engine"
    target_oss_path = f"{oss_base_path}/{args.scenario_date_id}/3dgs_model_edited.tgz"

    upload_tgz_to_oss(output_tar_gz_path, target_oss_path)
