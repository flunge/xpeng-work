import sys, os

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, "..", "..", ".."))
_UCP_DIR = os.path.join(_REPO_ROOT, "pipeline", "ucp")
if _UCP_DIR not in sys.path:
    sys.path.insert(0, _UCP_DIR)
    
from download_file_from_oss2 import download_file_from_oss2


if __name__ == "__main__":
    ################################## SETTINGS ##################################
    clips = {
        "c-3be02c38-0119-32a6-bb8e-8e0abd5f2370": "trained_model_sim3dgs_v416_1347",      # d03es 77099237
    }
    save_root = "/workspace/yangxh7@xiaopeng.com/model_cam_switch/d03es"
    ##############################################################################

    object_root = "sim_engine/ips_output_reconic/"
    suffix = ""
    render_root = _SCRIPT_DIR

    for clip, folder in clips.items():
        local_root = f"{save_root}/{clip}"
        os.makedirs(local_root, exist_ok=True)
        local_file_path = os.path.join(local_root, f"3dgs_model_{folder}.tgz")
        object_key = os.path.join(object_root, f"{clip}/{folder}/3dgs_model.tgz")
        download_file_from_oss2(local_file_path, object_key)
        
        os.system(f"cd {local_root}; tar xf {local_file_path}")
        os.system(f"cd {local_root}; mv model1 {folder}")
        os.system(f"rm {local_file_path}")

    use_difix = True
    mode = 'render'
    output_folder = f"difix_render_{mode}" if use_difix else f"render_{mode}"

    for clip, folder in clips.items():
        local_root = f"{save_root}/{clip}"
        config_file = os.path.join(local_root, folder, "configs/config_sim.yaml")
        if use_difix:
            os.system(f"cd {render_root}; bash deploy_render.bash "
                f"{config_file} {folder} {clip} {mode} {output_folder} {use_difix}")
        else:
            os.system(f"cd {render_root}; bash deploy_render.bash "
                f"{config_file} {folder} {clip} {mode} {output_folder}")
        