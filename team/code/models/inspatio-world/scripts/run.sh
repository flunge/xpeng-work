#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

MODE="infer"  # train | infer | both

METADATA_JSON="${REPO_DIR}/data/test_metadata.json"
OUTPUT_FOLDER="${REPO_DIR}/output/test_infer"

TRAIN_CONFIG="${REPO_DIR}/configs/train_lora_1.3b.yaml"
NUM_GPUS="1"
NUM_MACHINES="1"
MACHINE_RANK=""
MAIN_PROCESS_IP=""
MAIN_PROCESS_PORT=""

RUN_DIR=""

USE_TAE=0
COMPILE_DIT=0
REF_TIME_SHIFT=""
MAX_VIDEOS=""
NO_FINETUNE=0
CKPT_STEP=""
NO_REF=0

usage() {
    cat <<'EOF'
Usage:
  bash scripts/run.sh [options]

Modes:
  --mode train|infer|both          Default: infer

Train options:
  --train_config PATH              Training config YAML for train.py
  --num_gpus N                     Total processes for accelerate launch (default: 1)
  --num_machines N                 Total machine count for multinode (default: 1)
  --machine_rank N                 Current machine rank in [0, num_machines-1]
  --main_process_ip IP             Rank-0 machine IP (defaults to $MAIN_PROCESS_IP/$MASTER_ADDR)
  --main_process_port PORT         Rank-0 machine port (defaults to $MAIN_PROCESS_PORT/$MASTER_PORT)

Infer options:
  --run_dir PATH                   Training run dir containing config_used.yaml
  --ref_time_shift SECONDS         Temporal shift of the ref/source video in seconds
                                   (mirrors training data.ref_time_shift_seconds; default: 0)
  --max_videos N                   Only render the first N metadata entries
  --ckpt_step N                    Use the checkpoint saved at step N (loads
                                   *_step<N>.safetensors). Default: auto (prefer *_final,
                                   else largest step)
  --use_tae                        Use TAE decode (default: WanVAE)
  --compile_dit                    Enable torch.compile for DiT
  --no_finetune                    Skip fine-tuned weights in run_dir; run base model only
                                   (output tagged <train_mode>_step0)
  --no_ref                         Render WITHOUT a reference image: drop the ref from the
                                   KV-cache context but KEEP the previous-block history
                                   (block 0 self-attends; later blocks use the chunk
                                   history + render/mask + text). Use with a model trained
                                   with no_ref_prob>0
EOF
}

TRAIN_OVERRIDES=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h)
            usage
            exit 0
            ;;
        --mode)
            MODE="$2"
            shift 2
            ;;
        --train_config)
            TRAIN_CONFIG="$2"
            shift 2
            ;;
        --num_gpus)
            NUM_GPUS="$2"
            shift 2
            ;;
        --num_machines)
            NUM_MACHINES="$2"
            shift 2
            ;;
        --machine_rank)
            MACHINE_RANK="$2"
            shift 2
            ;;
        --main_process_ip)
            MAIN_PROCESS_IP="$2"
            shift 2
            ;;
        --main_process_port)
            MAIN_PROCESS_PORT="$2"
            shift 2
            ;;
        --run_dir)
            RUN_DIR="$2"
            shift 2
            ;;
        --ref_time_shift)
            REF_TIME_SHIFT="$2"
            shift 2
            ;;
        --max_videos)
            MAX_VIDEOS="$2"
            shift 2
            ;;
        --ckpt_step)
            CKPT_STEP="$2"
            shift 2
            ;;
        --use_tae)
            USE_TAE=1
            shift
            ;;
        --compile_dit)
            COMPILE_DIT=1
            shift
            ;;
        --no_finetune)
            NO_FINETUNE=1
            shift
            ;;
        --no_ref)
            NO_REF=1
            shift
            ;;
        --metadata_json)
            METADATA_JSON="$2"
            shift 2
            ;;
        --)
            shift
            while [[ $# -gt 0 ]]; do
                TRAIN_OVERRIDES+=("$1")
                shift
            done
            ;;
        *)
            # Forward unknown key=value args to training as OmegaConf overrides.
            if [[ "$1" == *=* ]]; then
                TRAIN_OVERRIDES+=("$1")
                shift
            else
                echo "Unknown option: $1"
                usage
                exit 1
            fi
            ;;
    esac
done

case "${MODE}" in
    train|infer|both) ;;
    *)
        echo "Error: --mode must be one of train|infer|both (got ${MODE})"
        exit 1
        ;;
esac

export LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu:/usr/local/cuda:/usr/local/cuda/lib:/usr/local/cuda/lib64:/usr/local/nvidia/lib:/usr/local/nvidia/lib64
export PATH="${REPO_DIR}/.venv/bin:${PATH}"
echo "REPO_DIR: ${REPO_DIR}"

find_latest_run_dir() {
    local latest
    latest="$(find "${REPO_DIR}/output" -type f -name config_used.yaml -printf '%T@ %h\n' 2>/dev/null | sort -nr | head -n1 | awk '{print $2}')"
    printf '%s' "${latest}"
}

resolve_machine_rank() {
    if [[ -n "${MACHINE_RANK}" ]]; then
        printf '%s' "${MACHINE_RANK}"
        return 0
    fi

    local keys=(FUYAO_NODE_RANK NODE_RANK GROUP_RANK MACHINE_RANK SLURM_NODEID)
    local key
    for key in "${keys[@]}"; do
        if [[ -n "${!key:-}" ]]; then
            printf '%s' "${!key}"
            return 0
        fi
    done

    return 1
}

run_training() {
    echo "============================================"
    echo "Training"
    echo "  train_config:         ${TRAIN_CONFIG}"
    echo "  num_processes(total): ${NUM_GPUS}"
    echo "  num_machines:         ${NUM_MACHINES}"
    echo "============================================"

    local accelerate_args=(
      --num_processes "${NUM_GPUS}"
            --mixed_precision bf16
    )

    if [[ "${NUM_MACHINES}" -gt 1 ]]; then
        local resolved_machine_rank
        if ! resolved_machine_rank="$(resolve_machine_rank)"; then
            echo "Error: multinode launch requires machine rank."
            echo "Provide --machine_rank or set one of: FUYAO_NODE_RANK/NODE_RANK/GROUP_RANK/MACHINE_RANK/SLURM_NODEID"
            exit 1
        fi

        local resolved_main_ip="${MAIN_PROCESS_IP:-${MASTER_ADDR:-}}"
        local resolved_main_port="${MAIN_PROCESS_PORT:-${MASTER_PORT:-29500}}"
        if [[ -z "${resolved_main_ip}" ]]; then
            echo "Error: multinode launch requires main process IP."
            echo "Provide --main_process_ip or set MAIN_PROCESS_IP/MASTER_ADDR."
            exit 1
        fi

        accelerate_args+=(
          --num_machines "${NUM_MACHINES}"
          --machine_rank "${resolved_machine_rank}"
          --main_process_ip "${resolved_main_ip}"
          --main_process_port "${resolved_main_port}"
          --same_network
        )

        echo "  machine_rank:         ${resolved_machine_rank}"
        echo "  main_process_ip:      ${resolved_main_ip}"
        echo "  main_process_port:    ${resolved_main_port}"
    fi

    (
      cd "${REPO_DIR}"
      accelerate launch "${accelerate_args[@]}" \
        train.py --config "${TRAIN_CONFIG}" "${TRAIN_OVERRIDES[@]}"
    )

    # Prefer latest run folder if user did not pin run_dir.
    if [[ -z "${RUN_DIR}" ]]; then
        RUN_DIR="$(find_latest_run_dir)"
        if [[ -n "${RUN_DIR}" ]]; then
            echo "[train] latest run_dir detected: ${RUN_DIR}"
        fi
    fi
}

run_inference() {
    if [[ -z "${RUN_DIR}" ]]; then
        RUN_DIR="$(find_latest_run_dir)"
        if [[ -z "${RUN_DIR}" ]]; then
            echo "Error: --run_dir not provided and no output/**/config_used.yaml found."
            exit 1
        fi
        echo "[infer] auto-selected latest run_dir: ${RUN_DIR}"
    fi

    if [[ ! -f "${RUN_DIR}/config_used.yaml" ]]; then
        echo "Error: invalid run_dir (missing config_used.yaml): ${RUN_DIR}"
        exit 1
    fi

    if [[ ! -f "${METADATA_JSON}" ]]; then
        echo "Error: metadata json not found: ${METADATA_JSON}"
        echo "Pass a valid --metadata_json (default: ${REPO_DIR}/data/test_metadata.json)"
        exit 1
    fi

    mkdir -p "${OUTPUT_FOLDER}"

    echo "============================================"
    echo "Inference (metadata-driven)"
    echo "  run_dir:        ${RUN_DIR}"
    echo "  metadata_json:  ${METADATA_JSON}"
    echo "  output_folder:  ${OUTPUT_FOLDER}"
    echo "============================================"

    local infer_args=(
        --run_dir "${RUN_DIR}"
        --metadata_json "${METADATA_JSON}"
        --output_folder "${OUTPUT_FOLDER}"
    )

    if [[ -n "${REF_TIME_SHIFT}" ]]; then
        infer_args+=(--ref_time_shift "${REF_TIME_SHIFT}")
    fi
    if [[ -n "${MAX_VIDEOS}" ]]; then
        infer_args+=(--max_videos "${MAX_VIDEOS}")
    fi
    if [[ -n "${CKPT_STEP}" ]]; then
        infer_args+=(--ckpt_step "${CKPT_STEP}")
    fi

    if [[ "${USE_TAE}" -eq 1 ]]; then
        infer_args+=(--use_tae)
    fi
    if [[ "${COMPILE_DIT}" -eq 1 ]]; then
        infer_args+=(--compile_dit)
    fi
    if [[ "${NO_FINETUNE}" -eq 1 ]]; then
        infer_args+=(--no_finetune)
    fi
    if [[ "${NO_REF}" -eq 1 ]]; then
        infer_args+=(--no_ref)
    fi

    (
      cd "${REPO_DIR}"
      CUDA_VISIBLE_DEVICES="${INFER_GPU:-0}" torchrun --nproc_per_node=1 \
        --master_port="${INFER_MASTER_PORT:-29610}" \
        inference_causal_test.py "${infer_args[@]}"
    )
}

case "${MODE}" in
    train)
        run_training
        ;;
    infer)
        run_inference
        ;;
    both)
        run_training
        run_inference
        ;;
esac
