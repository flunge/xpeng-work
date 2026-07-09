import os
import argparse
import hmac
import hashlib
import time
import logging
import functools
import requests
import json

logging.basicConfig(level=logging.INFO)

account = "simulation@xiaopeng.com"
oss_prefix_key_dict = {
    "data-pipeline-dds-quarantine": "oss_wl_quar",
    "ceph": "ceph_xp"
}

def parse_args():
    parser = argparse.ArgumentParser(description="Update scenario info with edited 3dgs version and dds paths")
    parser.add_argument("--cloudsim_scenario_id", type=str, required=True, help="CloudSim scenario ID to update")
    parser.add_argument("--edited_3dgs_version", type=str, required=True, help="Edited 3DGS version identifier")
    parser.add_argument("--dds_oss_path", type=str, required=True, help="DDS OSS path")
    return parser.parse_args()

def generate_hmac_sha256_signature(secret, message):
    hmac_key = bytes(secret, "utf-8")
    hmac_message = bytes(message, "utf-8")
    signature = hmac.new(hmac_key, hmac_message, hashlib.sha256).hexdigest()
    return signature

def retry(retries=3, delay=1):
    """
    重试装饰器
    
    :param retries: 重试次数
    :param delay: 重试间隔
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == retries:
                        raise e
                    print(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay} seconds...")
                    time.sleep(delay)
            return None
        return wrapper
    return decorator

@retry(retries=3, delay=2)
def request_to_cloudsim_api(host, path, req_type, body=None, form_data=None):
    # secret: YVofwMZRV&Fq
    secret = "iUUIQW$p!%E%"
    app_key = "simulation-auth"
    version = "1.0"
    sign_message = "/".join([app_key, version, account, str(int(time.time()*1000))])
    sign = generate_hmac_sha256_signature(secret, sign_message)
    if req_type == "POST":
        if form_data:
            r = requests.post(host+path, data=form_data, headers={
                "X-Sign": sign_message + "/" + sign
            })
        else:
            r = requests.post(host+path, json=body, headers={
                "X-Sign": sign_message + "/" + sign
            })
    else:
        r = requests.get(host+path, headers={
            "X-Sign": sign_message + "/" + sign
        })
    logging.info(f"Request to {host+path} with type {req_type} completed with resp: {r.content}")
    r.raise_for_status()

    return r


# curl 'https://cloudsim.xiaopeng.link/simulation/scenario/query/' \
#   -H 'accept: */*' \
#   -H 'accept-language: en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7' \
#   -H 'content-type: multipart/form-data; boundary=----WebKitFormBoundaryOz6KkFKA1LKHaEBP' \
#   -b '_ga=GA1.1.1689079798.1731407296; _ga_9HC7Y10E90=GS2.1.s1753691116$o6$g1$t1753691966$j60$l0$h0' \
#   -H 'origin: https://cloudsim.xiaopeng.link' \
#   -H 'priority: u=1, i' \
#   -H 'referer: https://cloudsim.xiaopeng.link/' \
#   -H 'sec-ch-ua: "Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"' \
#   -H 'sec-ch-ua-mobile: ?0' \
#   -H 'sec-ch-ua-platform: "Linux"' \
#   -H 'sec-fetch-dest: empty' \
#   -H 'sec-fetch-mode: cors' \
#   -H 'sec-fetch-site: same-origin' \
#   -H 'user-agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36' \
#   -H 'x-account: wangyl11@xiaopeng.com' \
#   -H 'x-token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJjbGllbnRWZXJpZnlDb2RlIjoiYTExNWY3NGVkMWM3MjAyZTdhMTY2MmVlOTU3ODE2YzAiLCJhY2NvdW50Ijoid2FuZ3lsMTFAeGlhb3BlbmcuY29tIiwidXNlck5hbWUiOiLnjovmsLjkuZAiLCJpYXQiOjE3NjQ4NTIwMDYsImV4cCI6MTc2NTQ1NjgwNn0.MEPrkChBUPVo6N7XxpSMsOFggcH4-kystAVXXGt_h_I' \
#   --data-raw $'------WebKitFormBoundaryOz6KkFKA1LKHaEBP\r\nContent-Disposition: form-data; name="id"\r\n\r\n30240154\r\n------WebKitFormBoundaryOz6KkFKA1LKHaEBP--\r\n'
def query_scenario_by_id(scenario_id):
    # Placeholder for querying existing scenario by ID
    host = "https://cloudsim.xiaopeng.link"
    path = f"/simulation/scenario/query/"
    # form data
    form_data = {
        "id": (None, str(scenario_id))
    }
    resp = request_to_cloudsim_api(host, path, "POST", form_data=form_data)

    if resp.status_code != 200:
        logging.error(f"Failed to query scenario id {scenario_id}, status code: {resp.status_code}, response: {resp.text}")
        return None, None, None, None
    
    scenario_info = resp.json()
    if scenario_info.get("result", "") != "success" or not scenario_info.get("data", {}).get("scenario", {}):
        logging.error(f"Scenario id {scenario_id} not found., response: {resp.text}")
        return None, None, None, None
    
    scenario_name = scenario_info.get("data", {}).get("name", "")
    scenario_config_str = scenario_info.get("data", {}).get("scenario", {}) 
    scenario_config = json.loads(scenario_config_str)
    cloud_bucket = scenario_config.get("ddsDataSource", {}).get("bucket", "")
    xpu_bucket = scenario_config.get("xpuDdsDataSource", {}).get("bucket", "")
    return scenario_name, scenario_config, cloud_bucket, xpu_bucket

# https://cloudsim.xiaopeng.link/simulation/scenario/duplicate_scenario/
def duplicate_updated_scenario(scenario_id, origin_scenario_name, edited_3dgs_version, origin_scenario_info, dds_oss_path, xpu_oss_path):
    # Placeholder for duplicating scenario with updated info
    host = "https://cloudsim.xiaopeng.link"
    path = f"/simulation/scenario/duplicate_scenario/"

    new_scenario_name = f"{origin_scenario_name}_{edited_3dgs_version}"

    updated_scenario_info = origin_scenario_info.copy()
    # update dds oss path
    # "ddsDataSource": {
    #     "bucket": "data-pipeline-dds-quarantine",
    #     "dds_files": [
    #       "demo/aeb_test_dds/Scenario_2025-11-28_05-50-32/recording_0_25-09-21_14:12:06.dat"
    #     ],
    #     "metadata": "cloudsim_scenario/driving/37/2025-11-28/30240154/unknown-L1NNSGHC6PB009513-h93xlidc-233632278929703962_2025-09-21-06-12-33/metadata",
    #     "calibration": "cloudsim_scenario/driving/37/2025-11-28/30240154/unknown-L1NNSGHC6PB009513-h93xlidc-233632278929703962_2025-09-21-06-12-33/calibration",
    #     "discovery": "demo/aeb_test_dds/Scenario_2025-11-28_05-50-32/discovery"
    #   },
    #   "xpuDdsDataSource": {
    #     "bucket": "ceph",
    #     "dds_files": [
    #       "/xpu_cluster/data/master_dataset_aligned/raw/XDDS_Master_Raw/2025-09-21/unknown-L1NNSGHC6PB009513-h93xlidc-233632278929703962_2025-09-21-06-12-33/recording_0_25-09-21_14:12:06.dat"
    #     ],
    #     "metadata": "/xpu_cluster/data/master_dataset_aligned/raw/XDDS_Master_Raw/2025-09-21/unknown-L1NNSGHC6PB009513-h93xlidc-233632278929703962_2025-09-21-06-12-33/metadata",
    #     "calibration": "/xpu_cluster/data/master_dataset_aligned/raw/XDDS_Master_Raw/2025-09-21/unknown-L1NNSGHC6PB009513-h93xlidc-233632278929703962_2025-09-21-06-12-33/calibration",
    #     "discovery": "/xpu_cluster/data/master_dataset_aligned/raw/XDDS_Master_Raw/2025-09-21/unknown-L1NNSGHC6PB009513-h93xlidc-233632278929703962_2025-09-21-06-12-33/discovery"
    #   },
    updated_data_source = updated_scenario_info.get("ddsDataSource", {})
    # retain original file name, change path prefix
    for key, value in updated_data_source.items():
        if key == "bucket":
            continue
        if isinstance(value, list):
            updated_data_source[key] = [os.path.join(dds_oss_path, os.path.basename(v)) for v in value]
        else:
            updated_data_source[key] = os.path.join(dds_oss_path, os.path.basename(value))

    updated_xpu_dds_data_source = updated_scenario_info.get("xpuDdsDataSource", {})
    # retain original file name, change path prefix
    for key, value in updated_xpu_dds_data_source.items():
        if key == "bucket":
            continue
        if isinstance(value, list):
            updated_xpu_dds_data_source[key] = [os.path.join(xpu_oss_path, os.path.basename(v)) for v in value]
        else:
            updated_xpu_dds_data_source[key] = os.path.join(xpu_oss_path, os.path.basename(value))

    updated_scenario_info["ddsDataSource"] = updated_data_source
    updated_scenario_info["xpuDdsDataSource"] = updated_xpu_dds_data_source

    data = {
        "scenario_id": str(scenario_id),
        "name": new_scenario_name,
        "labels": json.dumps([]),
        "description": f"Duplicated scenario with updated 3DGS version {edited_3dgs_version}",
        "updated_by": account,
        "copy_s_type": "yes",
        "scenario_config": json.dumps(updated_scenario_info)
    }

    logging.info(f"request to duplicate scenario with updated info: {data}")

    resp = request_to_cloudsim_api(host, path, "POST", form_data=data)

    if resp.status_code != 200:
        logging.error(f"Failed to duplicate scenario id {scenario_id}, status code: {resp.status_code}, response: {resp.text}")
        return None, None

    scenario_info = json.loads(resp.content)
    if not scenario_info.get("id", ""):
        logging.error(f"Failed to duplicate scenario id {scenario_id}, response: {scenario_info}")
        return None, None

    new_scenario_id = scenario_info.get("id", "")
    new_run_id = scenario_info.get("run_id", "")
    logging.info(f"Successfully duplicated scenario id {scenario_id} to new scenario id {new_scenario_id} with name {new_scenario_name}")
    return new_scenario_id, new_run_id

@retry(retries=3, delay=2)
def copy_dds_to_xpu_ceph(dds_dir_key, xpu_dir_key, scenario_id, run_id):
    xpu_api_url = "http://masterdataset-pipeline-shsre.xiaopeng.link/pipeline/xpu_data/send_copy_message/"

    form_data = {
        "src_path": dds_dir_key,
        "dst_path": xpu_dir_key,
        "run_id": str(run_id),
        "scenario_id": str(scenario_id),
    }

    logging.info(
        "[copy_dds_to_xpu_ceph] calling XPU data API with params: %s", form_data
    )

    response = requests.post(xpu_api_url, data=form_data, timeout=30)
    response.raise_for_status()

    result = response.json()
    logging.info("[copy_dds_to_xpu_ceph] XPU data API response: %s", result)

def update_scenario_info(cloudsim_scenario_id, edited_3dgs_version, dds_oss_path):
    # 1. query exist scenario by cloudsim_scenario_id with online interface
    origin_scenario_name, origin_scenario_info, cloud_bucket, xpu_bucket = query_scenario_by_id(cloudsim_scenario_id)
    if not origin_scenario_name or not origin_scenario_info:
        logging.error(f"[update_scenario_info] Failed to get origin scenario info for scenario id: {cloudsim_scenario_id}")
        exit(1)

    if not cloud_bucket or not xpu_bucket:
        logging.error(f"[update_scenario_info] Failed to get cloud or xpu bucket info from origin scenario for scenario id: {cloudsim_scenario_id}")
        exit(1)

    logging.info(f"Origin scenario name: {origin_scenario_name}, cloud bucket: {cloud_bucket}, xpu bucket: {xpu_bucket}")

    # 2. copy exist scenario to new scenario and get new scenario id
    xpu_oss_path = os.path.join("/xpu_cluster/data/master_dataset_aligned/raw/XDDS_Master_Raw/3dgs", edited_3dgs_version)
    new_scenario_id, new_run_id = duplicate_updated_scenario(cloudsim_scenario_id, origin_scenario_name, edited_3dgs_version, origin_scenario_info, dds_oss_path, xpu_oss_path)
    if not new_scenario_id:
        logging.error(f"[update_scenario_info] Failed to duplicate and update scenario for scenario id: {cloudsim_scenario_id}")
        exit(1)

    logging.info(f"[update_scenario_info] Finish Scenario Copy, new scenario: {new_scenario_id}, from origin scenario: {cloudsim_scenario_id}")

    # 3. trigger dds copied from cloud oss to ceph
    # replace /xpu_cluster -> xpu-cluster
    xpu_oss_path_replaced = xpu_oss_path.replace("/xpu_cluster", "xpu-cluster") 
    dds_dir_key = f"{oss_prefix_key_dict.get(cloud_bucket, '')}:{cloud_bucket}/{dds_oss_path}"
    xpu_dir_key = f"{oss_prefix_key_dict.get(xpu_bucket, '')}:{xpu_oss_path_replaced}"
    copy_dds_to_xpu_ceph(dds_dir_key, xpu_dir_key, new_scenario_id, new_run_id)

    logging.info(f"[update_scenario_info] Finish All Process, new scenario: {new_scenario_id}, from origin scenario: {cloudsim_scenario_id}")
    
if __name__ == "__main__":
    args = parse_args()
    cloudsim_scenario_id = args.cloudsim_scenario_id
    edited_3dgs_version = args.edited_3dgs_version
    dds_oss_path = args.dds_oss_path

    update_scenario_info(cloudsim_scenario_id, edited_3dgs_version, dds_oss_path)
