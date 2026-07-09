import numpy as np
import pandas as pd
import os
import sys
import json
from pathlib import Path
from datetime import datetime
_repo_root = Path(os.path.abspath(__file__)).parent.parent.parent.parent
_ucp_dir = _repo_root / "pipeline" / "ucp"
sys.path.insert(0, str(_repo_root / "models"))
sys.path.insert(0, str(_ucp_dir))

from download_file_from_oss2 import download_file_from_oss2, listdir_from_oss2, get_bucket


def download_clips_eval_2models(
        datasets_name='eval_dataset_v2.txt', target = "sim_engine/ips_output_depth/"
    ):
    # get eval datasets list
    clips = list(open(Path(os.path.abspath(__file__)).parent / f'eval_scenarios/{datasets_name}', 'r').readlines())
    clips = [d.strip() for d in clips]
    current_time = datetime.now().strftime('%Y%m%d%H%M%S')
    local_file_path = f"/workspace/yangxh7@xiaopeng.com/logs/eval/{current_time}"
    os.makedirs(local_file_path, exist_ok=True)

    valid_clips_psnr = {}
    valid_clips_fid = {}
    for clip in clips:
        criteria = ['psnr.csv', 'evaluation_results.json']
        for c in criteria:
            status = 1
            for m in ["256", "1347"]:
                object_key = f"{target}{clip}/trained_model_{m}/{c}"
                local_file = os.path.join(local_file_path, f"{clip}_{m}_{c}")
                status &= download_file_from_oss2(local_file, object_key, show_progress=False)
                if not status:
                    print(f"[ERROR] Failed to download {object_key}")
                    break

            if status and c == 'psnr.csv':
                try:
                    datfm1 = get_psnr_csv(os.path.join(local_file_path, f"{clip}_256_{c}"))
                    datfm2 = get_psnr_csv(os.path.join(local_file_path, f"{clip}_1347_{c}"))
                    valid_clips_psnr[clip] = pd.concat([datfm1, datfm2], axis=1)
                except Exception as e:
                    print(f"[ERROR] Failed to read {clip} psnr.csv with error: {e}")
            elif status and c == 'evaluation_results.json':
                try:
                    json_fid = get_fid_json(os.path.join(local_file_path, f"{clip}_256_{c}"))
                    json_fid.update(get_fid_json(os.path.join(local_file_path, f"{clip}_1347_{c}")))
                    valid_clips_fid[clip] = json_fid
                except Exception as e:
                    continue
    
    print("[INFO] Number of valid clips for PSNR: ", len(valid_clips_psnr))
    print("[INFO] Number of valid clips for FID: ", len(valid_clips_fid))
    return valid_clips_psnr, valid_clips_fid


def get_psnr_csv(file_path):
    datfm = pd.read_csv(file_path).set_index('index')
    return datfm


def get_fid_json(file_path):
    data = json.load(open(file_path, 'r'))
    return data


def summary_psnr(valid_clips_psnr):
    cams = '0234567'
    keys = ['count', 'mean', 'std', 'min', 'max', '25%', '50%', '75%']
    # set columns
    datfms = {f'cam{c}': pd.DataFrame(columns=keys) for c in cams}

    for clip, datfm in valid_clips_psnr.items():
        for c in cams:
            datfm_c = datfm.filter(regex=f'cam{c}', axis=1)
            datfm_c = datfm_c.describe().T
            datfm_c.index = [clip]
            datfms[f'cam{c}'] = pd.concat([datfms[f'cam{c}'], datfm_c], axis=0)

    # get report
    reports = pd.DataFrame(columns=[f'cam{c}' for c in cams], index=keys)
    for c in cams:
        description = datfms[f'cam{c}'].describe()
        for k in keys:
            reports.loc[k, f'cam{c}'] = description.loc[k, 'mean']
    reports.to_csv('./psnr_summary.csv')
    return reports, datfms
    

if __name__ == "__main__":
    valid_clips_psnr, valid_clips_fid = download_clips_eval_2models()
    reports, datfms = summary_psnr(valid_clips_psnr)
    