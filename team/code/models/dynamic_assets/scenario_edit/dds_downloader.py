import os
import logging
import argparse

logging.basicConfig(level=logging.INFO)

def run_cmd_and_log_out(cmd):
    logging.info(f"Running command: {cmd}")
    result = os.system(cmd)
    if result != 0:
        logging.error(f"Command failed with exit code {result}: {cmd}")
    return result

def download_file_from_oss(oss_bucket, oss_path, local_path, extra_str=""):
    """
    Upload a single file to OSS.
    """
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

def upload_object_to_oss(oss_bucket, local_path, oss_path, extra_str=""):
    """
    Upload a single file to OSS.
    """
    oss_endpoint = "http://oss-cn-wulanchabu.aliyuncs.com"
    access_key_id = os.environ.get("OSS_ACCESS_KEY_ID", "")
    access_key_secret = os.environ.get("OSS_ACCESS_KEY_SECRET", "")

    if oss_path.startswith("oss://"):
        # remove "oss://bucket_name/" prefix
        oss_path = "/".join(oss_path.split("/")[3:])

    # ossutil -e http://oss-cn-wulanchabu.aliyuncs.com -i os.environ.get("OSS_ACCESS_KEY_ID", "") -k os.environ.get("OSS_ACCESS_KEY_SECRET", "") -r --parallel 8 cp -f ./3dgs_model.tgz "oss://cloudsim-ci-sh/sim_engine/artificially_created_scenes/c-f560ab8e-0f35-31fe-8e57-36a00fe39dd9/trained_model_202509021553/3dgs_model.tgz"
    cmd = f'ossutil -e {oss_endpoint} -i {access_key_id} -k {access_key_secret} -r cp -f "{local_path}" "oss://{oss_bucket}/{oss_path}" {extra_str}'
    run_cmd_and_log_out(cmd)

    logging.info(f"Uploaded {local_path} to oss://{oss_bucket}/{oss_path}")