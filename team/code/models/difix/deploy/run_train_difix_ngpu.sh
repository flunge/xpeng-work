#!/usr/bin/env bash
# 4卡训练脚本（Accelerate DDP）

GPU_MODELS=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null)
if [ -n "$GPU_MODELS" ] && [[ "$(echo "$GPU_MODELS" | head -1)" == *"A100"* ]]; then
  DRIVER_MAIN_VERSION=$(nvidia-smi | grep -oP 'Driver Version:\s*\K\d+\.\d+\.\d+' | head -1 | cut -d'.' -f1)
  if [ "${DRIVER_MAIN_VERSION:-0}" -gt 470 ]; then
    FINAL_LD_PATH=/usr/lib/x86_64-linux-gnu:/usr/local/cuda:/usr/local/cuda/lib:/usr/local/cuda/lib64:/usr/local/nvidia/lib:/usr/local/nvidia/lib64
    export LD_LIBRARY_PATH="$FINAL_LD_PATH"
    export WANDB_MODE="offline"
    export WANDB_DOCKER=false
    export WANDB_DISABLE_CODE=true
    export WANDB_DISABLE_META=true
    export WANDB_DISABLE_GIT=true
    echo "[INFO] new LD_LIBRARY_PATH: $LD_LIBRARY_PATH"
  fi
fi

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_DIR="$(dirname "$SCRIPT_DIR")"
CWD="/workspace/yangxh7@xiaopeng.com"

export TORCH_HOME="$CWD/torch_cache"
export HF_HOME="$CWD/pretrain_model"
export WANDB_API_KEY="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"

##################
# $1~$4 仅用于 deploy 标签/资源；VERSION/TRAIN_ROOT/WORKSPACE 由 config 内设置
NUM_GPUS=${1:-4}
NODE_NUM=${2:-1}
MAIN_PROCESS_PORT=${3:-29501}
CONFIG_NAME=${4:-"train_full_dataset"}
TOTAL_PROCESSES=$((NUM_GPUS * NODE_NUM))
##################
cd "$CWD"
echo "[INFO] Starting training: num_gpus_per_node=$NUM_GPUS, node_num=$NODE_NUM, total_processes=$TOTAL_PROCESSES, main_process_port=$MAIN_PROCESS_PORT, config=$CONFIG_NAME"

export NCCL_TIMEOUT=3600
export TORCH_NCCL_BLOCKING_WAIT=1

# 从 configs/${CONFIG_NAME}.yaml 读全部训练参数
CONFIG_PATH="$SCRIPT_DIR/configs/${CONFIG_NAME}.yaml"
if [ ! -f "$CONFIG_PATH" ]; then
  echo "[ERROR] Config not found: $CONFIG_PATH"
  exit 1
fi

if [ "$NODE_NUM" -gt 1 ]; then
  # 尝试从常见调度环境变量中推断 machine_rank / master_addr
  MACHINE_RANK="${MACHINE_RANK:-${NODE_RANK:-}}"
  MAIN_PROCESS_IP="${MAIN_PROCESS_IP:-${MASTER_ADDR:-${MAIN_ADDR:-}}}"

  if [ -z "${MACHINE_RANK}" ]; then
    echo "[ERROR] Multi-node launch requires machine rank."
    echo "        Please set one of: MACHINE_RANK / NODE_RANK"
    echo "        Debug env snapshot: MACHINE_RANK=${MACHINE_RANK:-}, NODE_RANK=${NODE_RANK:-}, RANK=${RANK:-}, WORLD_RANK=${WORLD_RANK:-}"
    exit 2
  fi
  if [ -z "${MAIN_PROCESS_IP}" ]; then
    echo "[ERROR] Multi-node launch requires master address."
    echo "        Please set one of: MAIN_PROCESS_IP / MASTER_ADDR / MAIN_ADDR"
    exit 2
  fi

  echo "[INFO] Distributed args: machine_rank=${MACHINE_RANK}, main_process_ip=${MAIN_PROCESS_IP}, main_process_port=${MAIN_PROCESS_PORT}"
  exec accelerate launch \
      --multi_gpu \
      --num_machines "$NODE_NUM" \
      --machine_rank "$MACHINE_RANK" \
      --main_process_ip "$MAIN_PROCESS_IP" \
      --main_process_port "$MAIN_PROCESS_PORT" \
      --num_processes "$TOTAL_PROCESSES" \
      "$SCRIPT_DIR/src/train_difix.py" \
      --config "$CONFIG_PATH"
else
  exec accelerate launch \
      --multi_gpu \
      --num_machines "$NODE_NUM" \
      --num_processes "$TOTAL_PROCESSES" \
      --main_process_port "$MAIN_PROCESS_PORT" \
      "$SCRIPT_DIR/src/train_difix.py" \
      --config "$CONFIG_PATH"
fi