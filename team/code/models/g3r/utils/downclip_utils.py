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

subfile_list = ["images", "input_ply", "masks", "masks_obj", "segs", "surfel_ground", "ground_mask.npy", "transform.json"]

def down_training_data(data_folder, clip):
    os.makedirs(data_folder, exist_ok=True)
    local_file_path = os.path.join(data_folder, "3dgs_model.tgz")
    local_model_path = os.path.join(data_folder, clip)
    os.makedirs(local_model_path, exist_ok=True)

    object_key = os.path.join("sim_engine/datasets_clip/", f"{clip}/complete/dataset.tgz")
    download_file_from_oss2(local_file_path, object_key)

    val = os.system(f"cd {data_folder}; tar xf {local_file_path}")
    model_folder = os.path.join(data_folder, "model1")
    if val != 0 or not os.path.exists(model_folder):
        return False

    for subfile in subfile_list:
        subpath = os.path.join(model_folder, subfile)
        if not os.path.exists(model_folder):
            return False
        os.system(f"mv {subpath} {local_model_path}")

    os.system(f"rm {local_file_path}")
    os.system(f"rm -rf {model_folder}")
    return True