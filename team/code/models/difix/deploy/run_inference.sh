#!/usr/bin/env bash
# 对应 .vscode/launch.json 中的 TrainDifix 配置

GPU_MODELS=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null)
if [ -n "$GPU_MODELS" ] && [[ "$(echo "$GPU_MODELS" | head -1)" == *"A100"* ]]; then
  DRIVER_MAIN_VERSION=$(nvidia-smi | grep -oP 'Driver Version:\s*\K\d+\.\d+\.\d+' | head -1 | cut -d'.' -f1)
  if [ "$DRIVER_MAIN_VERSION" -gt 470 ]; then #若dirver版本大于470则清理原路径中的compat
    FINAL_LD_PATH=/usr/lib/x86_64-linux-gnu:/usr/local/cuda:/usr/local/cuda/lib:/usr/local/cuda/lib64:/usr/local/nvidia/lib:/usr/local/nvidia/lib64
    export LD_LIBRARY_PATH="$FINAL_LD_PATH"
    echo "[INFO]new LD_LIBRARY_PATH: $LD_LIBRARY_PATH"
  fi
fi
##################
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_DIR="$(dirname "$SCRIPT_DIR")"
CWD="/workspace/yangxh7@xiaopeng.com"

export TORCH_HOME="$CWD/torch_cache"
export HF_HOME="$CWD/pretrain_model"

##################
VERSION="v9_2gpu"
CAMERA_NAME="cam2"
##################

cd "$CWD"
exec python "$SCRIPT_DIR/src/inference_difix.py" \
    --output_dir "/workspace/yangxh7@xiaopeng.com/difix3D_train/c-4b1dcb83-dd7f-3c65-8579-d53ad9dcee5d/inference/${VERSION}_${CAMERA_NAME}/" \
    --ckpt_path "/workspace/yangxh7@xiaopeng.com/difix3D_train/c-4b1dcb83-dd7f-3c65-8579-d53ad9dcee5d/$VERSION/checkpoints" \
    --data_path "/workspace/yangxh7@xiaopeng.com/difix3D_train/c-4b1dcb83-dd7f-3c65-8579-d53ad9dcee5d/output_dataset_interval2.json" \
    --camera_name "$CAMERA_NAME" \
    "$@"
