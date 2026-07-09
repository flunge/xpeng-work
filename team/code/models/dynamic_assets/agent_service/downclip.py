import oss2
import sys, os
import yaml
import tarfile

current_dir = os.path.dirname(os.path.abspath(__file__))
ips_deploy_dir = os.path.join(current_dir, '..', '..', 'ips_deploy')

sys.path.append(ips_deploy_dir)
from download_file_from_oss2 import download_file_from_oss2

data_type = "data" # data or 3dgs
clips = {
    # "c-a53d86bf-ae24-3cb6-a681-6531fd903545": "trained_model_v231_v231_1347",
    # "c-a53d86bf-ae24-3cb6-a681-6531fd903545": "complete",
    # "c-4155db0f-0930-3e4b-bda2-56555b893ee5": "complete",
    # "c-4155db0f-0930-3e4b-bda2-56555b893ee5": "trained_model_v230_ppu_1347",
    # "c-93b94572-41e4-3c3f-bed5-c236c1a89a59": "trained_model_v208_ppu_obj_1347",
    # "c-a65531c3-aae1-39e8-802e-52e982529f08": "trained_model_v231_v231_1347",
    "c-a65531c3-aae1-39e8-802e-52e982529f08": "complete",
}

if data_type == "data":
    object_root = "sim_engine/datasets_clip/"
    local_root = f"/workspace/duanzx@xiaopeng.com/dataset/c-a65531c3-aae1-39e8-802e-52e982529f08"
elif data_type == "3dgs":
    object_root = "sim_engine/ips_output_clip_depth/"
    local_root = f"/workspace/duanzx@xiaopeng.com/3dgs/online_data/3dgs/c-a65531c3-aae1-39e8-802e-52e982529f08"

if __name__ == "__main__":
    suffix = ""
    os.makedirs(local_root, exist_ok=True)
    for clip, folder in clips.items():
        local_file_path = os.path.join(local_root, "3dgs_model.tgz")
        local_model_path = os.path.join(local_root, clip)
        os.makedirs(local_model_path, exist_ok=True)

        if data_type == "data":
            object_key = os.path.join(object_root, f"{clip}/{folder}/dataset.tgz")
        elif data_type == "3dgs":
            object_key = os.path.join(object_root, f"{clip}/{folder}/3dgs_model.tgz")

        download_file_from_oss2(local_file_path, object_key)

        # with tarfile.open(local_file_path, "r:gz") as tgz_file:
        #     tgz_file.extractall(path=local_root)

        os.system(f"cd {local_root}; tar xf {local_file_path}")

        # os.system(f"cd {local_root}; tar xf {local_file_path} --exclude='depth' --exclude='colmap' --exclude='images' --exclude='input_ply' --exclude='segs' --exclude='pcd'")
        # os.system(f"mv {local_root}/model1 {local_model_path}")
        # os.system(f"mv {local_root}/model1/ground_mask.npy {local_model_path}")
        # os.system(f"rm {local_file_path}")
        # os.system(f"rm -rf {local_root}/model1")