#!/usr/bin/env bash
# 对应 .vscode/launch.json 中的 TrainDifix 配置

GPU_MODELS=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null)
if [ -n "$GPU_MODELS" ] && [[ "$(echo "$GPU_MODELS" | head -1)" == *"A100"* ]]; then
  DRIVER_MAIN_VERSION=$(nvidia-smi | grep -oP 'Driver Version:\s*\K\d+\.\d+\.\d+' | head -1 | cut -d'.' -f1)
  if [ "$DRIVER_MAIN_VERSION" -gt 470 ]; then #若dirver版本大于470则清理原路径中的compat
    FINAL_LD_PATH=/usr/lib/x86_64-linux-gnu:/usr/local/cuda:/usr/local/cuda/lib:/usr/local/cuda/lib64:/usr/local/nvidia/lib:/usr/local/nvidia/lib64
    export LD_LIBRARY_PATH="$FINAL_LD_PATH"
    export WANDB_MODE="offline"
    export WANDB_DOCKER=false
    export WANDB_DISABLE_CODE=true
    export WANDB_DISABLE_META=true
    export WANDB_DISABLE_GIT=true
    echo "[INFO]new LD_LIBRARY_PATH: $LD_LIBRARY_PATH"
  fi
fi
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_DIR="$(dirname "$SCRIPT_DIR")"
CWD="/workspace/yangxh7@xiaopeng.com"

export TORCH_HOME="$CWD/torch_cache"
export HF_HOME="$CWD/pretrain_model"
export WANDB_API_KEY="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"
# export WANDB_MODE="offline"

##################
VERSION="v8"
TRAIN_ROOT="c-4b1dcb83-dd7f-3c65-8579-d53ad9dcee5d"
##################

cd "$CWD"
exec python "$SCRIPT_DIR/src/train_difix.py" \
    --output_dir "/workspace/yangxh7@xiaopeng.com/difix3D_train/$TRAIN_ROOT/$VERSION" \
    --dataset_path "/workspace/yangxh7@xiaopeng.com/difix3D_train/$TRAIN_ROOT/output_dataset_interval2.json" \
    --resume "/workspace/yangxh7@xiaopeng.com/difix3D_train/$TRAIN_ROOT/v7_2gpu/checkpoints/" \
    --image_height "576" \
    --image_width "1024" \
    --lora_rank_vae "4" \
    --train_batch_size "2" \
    --dataloader_num_workers 4 \
    --enable_xformers_memory_efficient_attention \
    --num_training_epochs "100" \
    --checkpointing_epoch "20" \
    --eval_freq "100000000" \
    --viz_freq "500" \
    --lambda_lpips "0.1" \
    --lambda_l2 "1.0" \
    --lambda_gram "0.1" \
    --gram_loss_warmup_steps "999999999999" \
    --tracker_project_name "difix_$VERSION" \
    --tracker_run_name "train_ngpu" \
    --timestep "199" \
    --set_grads_to_none \
    --gradient_checkpointing \
    --learning_rate "5e-5" # "5e-5"
