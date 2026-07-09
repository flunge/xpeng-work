import json
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, "..", "..", ".."))
_UCP_DIR = os.path.join(_REPO_ROOT, "pipeline", "ucp")
if _UCP_DIR not in sys.path:
    sys.path.insert(0, _UCP_DIR)

from download_file_from_oss2 import download_file_from_oss2


CAR_CALIB_SRC = {
    "e29": "/workspace/group_share/adc-sim/users/multi_vehicle/calibs/calib_e29.json",
    "f01es": "/workspace/group_share/adc-sim/users/multi_vehicle/calibs/calib_f01es.json",
    "h93aes": "/workspace/group_share/adc-sim/users/multi_vehicle/calibs/calib_h93aes.json",
    "f57aes": "/workspace/group_share/adc-sim/users/multi_vehicle/calibs/calib_f57aes.json",
    "e38be": "/workspace/group_share/adc-sim/users/multi_vehicle/calibs/calib_e38be.json",
    "f01xccp": "/workspace/group_share/adc-sim/users/multi_vehicle/calibs/calib_f01xccp.json",
    "g01": "/workspace/group_share/adc-sim/users/multi_vehicle/calibs/calib_g01.json",
    "g02": "/workspace/group_share/adc-sim/users/multi_vehicle/calibs/calib_g02.json",
    "g02_noacc": "/workspace/group_share/adc-sim/users/multi_vehicle/calibs/calib_g02_noacc.json",
    "d03es": "/workspace/group_share/adc-sim/users/multi_vehicle/calibs/calib_d03es.json",
}


if __name__ == "__main__":
    ################################## SETTINGS ##################################
    json_file = "/workspace/yangxh7@xiaopeng.com/model_cam_switch/e29/e29_task_info_list-Copy1.json"
    save_root = "/workspace/yangxh7@xiaopeng.com/model_cam_switch/e29" 
    ##############################################################################
    
    render_root = _SCRIPT_DIR
    deploy_script = os.path.join(render_root, "deploy_render_switch.bash")

    with open(json_file, "r", encoding="utf-8") as f:
        records = json.load(f)

    model_items = []
    for record in records:
        model_path = record.get("threedgs_model_path", "")
        if not model_path.startswith("oss://"):
            continue
        object_key = model_path.replace("oss://cloudsim-ci-sh/", "", 1)
        parts = object_key.split("/")
        # expected: sim_engine/ips_output_reconic/{clip}/{folder}/3dgs_model.tgz
        if len(parts) < 5:
            continue
        clip = parts[-3]
        folder = parts[-2]
        model_items.append({
            "clip": clip,
            "folder": folder,
            "openloop_scenario_id": record.get("openloop_scenario_id", ""),
            "closeloop_scenario_id": record.get("closeloop_scenario_id", ""),
        })

    print(f"[INFO] downloading {len(model_items)} models")

    for item in model_items:
        closeloop_scenario_id = item["closeloop_scenario_id"]
        clip = item["clip"]
        folder = item["folder"]
        local_root = f"{save_root}/{closeloop_scenario_id}"
        extracted_folder = os.path.join(local_root, folder)
        if os.path.isdir(extracted_folder):
            print(f"[SKIP] already exists: {extracted_folder}")
            continue

        os.makedirs(local_root, exist_ok=True)
        local_file_path = os.path.join(local_root, f"3dgs_model_{folder}.tgz")
        object_key = f"sim_engine/ips_output_reconic/{clip}/{folder}/3dgs_model.tgz"
        download_file_from_oss2(local_file_path, object_key)
        
        os.system(f"cd {local_root}; tar xf {local_file_path}")
        os.system(f"cd {local_root}; mv model1 {folder}")
        os.system(f"rm {local_file_path}")
        print(f"[INFO] downloaded {local_file_path}")

    mode = 'h93aes'

    for item in model_items:
        folder = item["folder"]
        openloop_scenario_id = item["openloop_scenario_id"]
        closeloop_scenario_id = item["closeloop_scenario_id"]
        clip = item["clip"]
        local_root = f"{save_root}/{closeloop_scenario_id}"
        output_folder = f"car_switch_{mode}_dds_png_new2minus1"
        reference_png_dir = f"/workspace/group_share/adc-sim/users/yangxh7/origin_img/{clip}/images_origin/"

        # config_file
        config_file = os.path.join(local_root, folder, "configs/config_sim.yaml")

        # save_path
        save_path = os.path.join(local_root, folder, output_folder)

        # new_calib_path
        if mode == 'origin':
            new_calib_path = os.path.join(local_root, folder, "calib.json")
        else:
            new_calib_path = CAR_CALIB_SRC[mode]

        # new_img_timestamps_path
        new_img_timestamps_path = os.path.join(local_root, "timestamp_records.json")

        # job_name
        job_name = f"switch_car_{mode}_{clip}_{closeloop_scenario_id}"

        os.system(
            f"cd {render_root}; bash {deploy_script} "
            f"{config_file} {save_path} {new_calib_path} {new_img_timestamps_path} "
            f"{job_name} {reference_png_dir} {clip}"
        )
        