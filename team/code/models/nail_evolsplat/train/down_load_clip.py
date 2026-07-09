import oss2
import sys, os
import yaml
import tarfile

current_dir = os.path.dirname(__file__)
repo_root = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
_ucp_dir = os.path.join(repo_root, "pipeline", "ucp")
_models_dir = os.path.join(repo_root, "models")
for _p in (_ucp_dir, _models_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from download_file_from_oss2 import download_file_from_oss2


def down_training_data(data_folder, clip):
    os.makedirs(data_folder, exist_ok=True)
    local_model_path = os.path.join(data_folder, clip)
    local_file_path = os.path.join(local_model_path, "3dgs_model.tgz")
    if os.path.exists(local_model_path) and os.path.exists(os.path.join(local_model_path,"images")): 
            return True
    os.makedirs(local_model_path, exist_ok=True)
    object_key = os.path.join("sim_engine/datasets_vision/", f"{clip}/version_preprocessdata1205/lvy_1205test/dataset.tgz")
    # object_key = os.path.join("sim_engine/datasets_vision_/", f"{clip}/version_1119_dev_evolsplat_difix_4w_evo/lvy_114_g3rnoval/dataset.tgz")
    download_file_from_oss2(local_file_path, object_key)


    try:
        if not os.path.exists(local_file_path):
            print(f"!!there is no dataset.tgz for {clip}") 
            return False
        val = os.system(f"cd {local_model_path}; tar xf {local_file_path}")
    except:
        print(f'[ERROR] failed to tar xf {local_file_path}')
        return False

    model_folder = os.path.join(local_model_path, "model1")
    if val != 0 or not os.path.exists(model_folder):
        print(f"!!tar fail for {clip}") 
        return False

    os.system(f"mv {model_folder}/* {local_model_path}")
    return True




def cp_training_data(data_folder, clip):
    os.makedirs(data_folder, exist_ok=True)
    local_model_path = os.path.join(data_folder, clip)
    local_file_path = os.path.join(local_model_path, "3dgs_model.tgz")
    if os.path.exists(local_model_path) and os.path.exists(os.path.join(local_model_path,"images")): 
            return True
    os.makedirs(local_model_path, exist_ok=True)
    try:
        src_data = f"/workspace/group_share/adc-sim/users/zf/ips_vision/version_407_1127/{clip}/dataset.tgz"
        os.system(f"cp -r {src_data} {local_file_path}")
        if not os.path.exists(local_file_path):
            print(f"!!there is no dataset.tgz for {clip}") 
            return False
        val = os.system(f"cd {local_model_path}; tar xf {local_file_path}")
    except:
        print(f'[ERROR] failed to tar xf {local_file_path}')
        return False

    model_folder = os.path.join(local_model_path, "model1")
    if val != 0 or not os.path.exists(model_folder):
        print(f"!!tar fail for {clip}") 
        return False

    os.system(f"mv {model_folder}/* {local_model_path}")
    return True