import os
import shutil

clips = [
    "c-8ef05525-5b6a-367b-9d13-77c48160a2b0"
]
src_dir = "/workspace/yangxh7@xiaopeng.com/difix_train/buqibu"
src_output = "difix_output_v2"
src_ckpt = "checkpoint_6001"

dst_dir = "/workspace/group_share/adc-sim/users/cloudsim/difix/lora/"
dst_backup_old_folder = "v1"


for clip in clips:
    src_path = os.path.join(src_dir, clip, src_output, src_ckpt)
    dst_path = os.path.join(dst_dir, clip)
    os.makedirs(os.path.join(dst_path, dst_backup_old_folder), exist_ok=True)
    # backup cmd
    cmd_backup = f"mv {dst_path}/model.pkl {dst_path}/unet/ {dst_path}/{dst_backup_old_folder}/"
    os.system(cmd_backup)

    # move ckpt
    cmd_copy = f"cp -r {src_path}/* {dst_path}/"
    os.system(cmd_copy)
    