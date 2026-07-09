import os
import logging
import argparse
from datetime import datetime
import json

logging.basicConfig(level=logging.INFO)

def run_cmd_and_log_out(cmd):
    logging.info(f"Running command: {cmd}")
    result = os.system(cmd)
    if result != 0:
        logging.error(f"Command failed with exit code {result}: {cmd}")
    return result

def download_file_from_oss(oss_path, local_path, extra_str=""):
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

    # ossutil -e http://oss-cn-wulanchabu.aliyuncs.com -i OSS_ACCESS_KEY_ID_REDACTED -k OSS_ACCESS_KEY_SECRET_REDACTED -r --parallel 8 cp -f "oss://cloudsim-ci-sh/sim_engine/artificially_created_scenes/c-f560ab8e-0f35-31fe-8e57-36a00fe39dd9/trained_model_202509021553/3dgs_model.tgz" ./
    cmd = f'ossutil -e {oss_endpoint} -i {access_key_id} -k {access_key_secret} -r cp -f "oss://{oss_bucket}/{oss_path}" "{local_path}" {extra_str}'
    run_cmd_and_log_out(cmd)

    target_path = os.path.join(local_path, oss_path.split("/")[-1])
    logging.info(f"Downloaded {oss_path} to {target_path}")

    return target_path

def parse_args():
    parser = argparse.ArgumentParser(description="OSS File Downloader")
    parser.add_argument(
        "--local_path",
        type=str,
        required=True,
        help="The local path where the file will be saved."
    )
    parser.add_argument(
        "--object_oss_path",
        type=str,
        required=True,
        help="The OSS path of the object to download (relative to the bucket)."
    )
    return parser.parse_args()

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

def get_ply_path_in_dir(ply_dir):
    ply_files = [f for f in os.listdir(ply_dir) if f.endswith(".ply")]
    if not ply_files:
        logging.error(f"No .ply files found in {ply_dir}")
        return None
    ply_file_path = os.path.join(ply_dir, ply_files[0])
    return ply_file_path

if __name__ == "__main__":
    args = parse_args()
    local_dir = os.path.join(args.local_path, "dynamic_assets_view")
    os.makedirs(local_dir, exist_ok=True)
    meta_json_path, ply_path_pattern = post_process_object_path(args.object_oss_path)
    ply_file_dir = download_file_from_oss(ply_path_pattern, local_dir, extra_str="--include \"*.ply\"")
    ply_file_path = get_ply_path_in_dir(ply_file_dir)

    print(f"Downloaded PLY file to: {ply_file_path}")
