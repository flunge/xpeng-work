import os
import logging
import argparse

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

if __name__ == "__main__":
    args = parse_args()
    local_dir = os.path.join(args.local_path, "scenarios", f"{args.scenario_date_id}", "videos")
    os.makedirs(local_dir, exist_ok=True)

    scenario_video_oss_path = f"3dgs_scenario_engine/{args.scenario_date_id}/videos/"

    # Example usage
    downloaded_file_path = download_file_from_oss(scenario_video_oss_path, local_dir)
    logging.info(f"File downloaded to: {downloaded_file_path}")