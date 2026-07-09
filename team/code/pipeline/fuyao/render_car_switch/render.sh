config_file=$1
save_path=$2
new_calib_path=$3
new_img_timestamps_path=$4
reference_png_dir=$5
clip=$6

echo "Repo root: $REPO_ROOT" # 环境变量，通过 deploy_render.bash 中设置

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../../.." && pwd)"
reconic_src="$repo_root/omnire_joint_trainning/src"
export PYTHONPATH="$reconic_src:$repo_root/models"
cd "$reconic_src"

export LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu:/usr/local/cuda:/usr/local/cuda/lib:/usr/local/cuda/lib64:/usr/local/nvidia/lib:/usr/local/nvidia/lib64
echo "LD_LIBRARY_PATH: $LD_LIBRARY_PATH"

# export USE_DIFIX_FINETUNED="true"
export USE_DIFIX_REFERENCE="true"
export SCENE_IDX=$clip
export REF_PATH=$reference_png_dir
export TRIGGER_TIME_DIS="1"
# export CKPT="/workspace/group_share/adc-sim/users/cloudsim/difix/ckpt_finetuned/default_trt"
export CKPT="/workspace/group_share/adc-sim/users/cloudsim/difix/ckpt_finetuned/train_v6_epoch_0210_step_1680000/"
export TORCH_HOME="/workspace/group_share/adc-sim/users/cloudsim/torch_cache"
export HF_HOME="/workspace/group_share/adc-sim/users/cloudsim/pretrain_model"
echo "USE_DIFIX enabled, set SCENE_IDX to $project_name and CKPT to $CKPT"

# --project $project_name --run_name $run_name 
python scripts/render_switch_car.py --config "$config_file" \
    --save_path "$save_path" \
    --new_calib_path "$new_calib_path" \
    --new_img_timestamps_path "$new_img_timestamps_path" \
    --reference_png_dir "$reference_png_dir"


