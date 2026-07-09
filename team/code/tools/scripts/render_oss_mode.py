import oss2
import sys, os
import yaml

############################ USER SET ############################
USER_ROOT = "/workspace/yangxh7@xiaopeng.com"
REPO_ROOT = f"{USER_ROOT}/codes/3dgs/"
RENDER_IDS = [
    "c-372caa4f-33c9-3123-a14a-2db800127a03",
]
##################################################################

sys.path.append(f"{REPO_ROOT}/pipeline/ucp")
sys.path.append(f"{REPO_ROOT}/models/street_gaussians")
from download_file_from_oss2 import download_file_from_oss2


if __name__ == "__main__":
    import tarfile
    import os

    object_root = "sim_engine/ips_output_subrun_depth/"
    suffix = ""
    local_root = f"{USER_ROOT}/{object_root.split('/')[1]}/{suffix}/"
    os.makedirs(local_root, exist_ok=True)
    for clip in RENDER_IDS:
        for m in ["256", "1347"]:
            local_file_path = os.path.join(local_root, "3dgs_model.tgz")
            local_model_path = os.path.join(local_root, clip)
            root_folder = f"trained_model_{m}" if len(suffix) == 0 else f"trained_model_{suffix}_{m}"
            object_key = os.path.join(object_root, f"{clip}/{root_folder}/3dgs_model.tgz")  # trained_model_raw_lp_
            download_file_from_oss2(local_file_path, object_key)
            with tarfile.open(local_file_path, "r:gz") as tgz_file:
                tgz_file.extractall(path=local_model_path)

            target_path = os.path.join(local_model_path, m)
            os.system(f"mv {local_model_path}/model1 {target_path}")

            config_sim = yaml.load(open(f"{target_path}/configs/config_sim.yaml"), Loader=yaml.FullLoader)
            config_sim["model_path"] = target_path
            config_sim["point_cloud_dir"] = os.path.join(target_path, "point_cloud")
            config_sim["trained_model_dir"] = os.path.join(target_path, "trained_model")
            yaml.dump(config_sim, open(f"{target_path}/configs/config_sim.yaml", "w"), default_flow_style=False)
        
            os.system(f"rm -rf {local_file_path}")
            os.system(f"python {REPO_ROOT}/models/street_gaussians/render_sim.py --config {target_path}/configs/config_sim.yaml")
            print(f"[INFO] Rendering {clip} {m} done.")
