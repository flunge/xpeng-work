#########################################################################
# WORKSPACE 目录
workspace_dir="/workspace/yangxh7@xiaopeng.com"
# 任务配置文件路径
train_config="difix3D_train/train_v3_1w_b/v3_2buckets/train_v3_1w_b_2buckets.yaml"
# 需要infer的ckpt文件路径
ckpt_path="difix3D_train/train_v3_1w_b/v3_2buckets/checkpoints_epoch_0039_step_234000"
# ref_image_mode: 0=当前帧GT作为ref；N>0=在当前clip内前后N帧内随机选一帧GT作为ref；None=不使用ref
ref_image_mode=0
# 是否是原始 Difix（true 则开启）
use_origin_difix=false
# 是否开启profile
profile=false
# job_name 列表，按需增删
train_data_root="codes/3dgs/models/difix/utils/eval_data_v1_0301/train_data_parts"
job_names=(
    "train_data_part_1.json"
    "train_data_part_2.json"
    "train_data_part_3.json"
    "train_data_part_4.json"
)
#########################################################################
ckpt_name=$(basename $ckpt_path)
train_config_name=$(basename $train_config)
origin_flag=""
if [ "$use_origin_difix" = true ]; then
    origin_flag="--use_origin_difix"
fi
if [ "$profile" = true ]; then
    profile_flag="--profile"
    job_names=(
        "train_data_part_0.json"
    )
fi

for job_name in "${job_names[@]}"; do
    echo ">>> 提交任务: ${job_name%.*}_${train_config_name}_${ckpt_name}_${ref_image_mode}_${origin_flag}_${profile_flag}"
    # nohup bash -c "
    #     FINAL_LD_PATH=/usr/lib/x86_64-linux-gnu:/usr/local/cuda:/usr/local/cuda/lib:/usr/local/cuda/lib64:/usr/local/nvidia/lib:/usr/local/nvidia/lib64
    #     export LD_LIBRARY_PATH=\"$FINAL_LD_PATH\"
    #     export TORCH_HOME=$workspace_dir/torch_cache
    #     export HF_HOME=$workspace_dir/pretrain_model
    #     python $workspace_dir/codes/3dgs/models/difix/src/inference_batch.py \
    #         --train_data_json $workspace_dir/$train_data_root/$job_name \
    #         --ckpt_path $workspace_dir/$ckpt_path \
    #         --train_config $workspace_dir/$train_config \
    #         --ref_image_mode $ref_image_mode \
    #         --frame_step 2 \
    #         --max_frames_per_clip -1 \
    #         $origin_flag $profile_flag
    # " > $workspace_dir/logs/inference_batch_$job_name.log 2>&1 &
    
    fuyao deploy --gpu-type=A100  --volume=adc-sim --queue=adc-sim --release\
                 --site=fuyao_b1_prod2 --label "${job_name%.*}_${train_config_name}_${ckpt_name}_${ref_image_mode}_${origin_flag}_${profile_flag}" \
                 --docker-image infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:yangxh7-251209-0220 \
                 --project="adc-sim" --experiment "sim3dgs-sim" --gpus-per-node=1 --nodes=1 \
        bash -c "
            FINAL_LD_PATH=/usr/lib/x86_64-linux-gnu:/usr/local/cuda:/usr/local/cuda/lib:/usr/local/cuda/lib64:/usr/local/nvidia/lib:/usr/local/nvidia/lib64
            export LD_LIBRARY_PATH=\"$FINAL_LD_PATH\"
            export TORCH_HOME=$workspace_dir/torch_cache
            export HF_HOME=$workspace_dir/pretrain_model
            python $workspace_dir/codes/3dgs/models/difix/src/inference_batch.py \
                --train_data_json $workspace_dir/$train_data_root/$job_name \
                --ckpt_path $workspace_dir/$ckpt_path \
                --train_config $workspace_dir/$train_config \
                --ref_image_mode $ref_image_mode \
                --frame_step 2 \
                --max_frames_per_clip -1 \
                $origin_flag $profile_flag
        "
done
echo ">>> 全部任务已提交"
