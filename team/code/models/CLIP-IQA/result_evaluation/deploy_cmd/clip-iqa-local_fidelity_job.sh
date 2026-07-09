#!/bin/bash
# 用法：bash clip-iqa-local_fidelity_job.sh <job_id> [num_shards] [gap_mean_thr] [gap_std_thr]
#
# Fidelity-only 评测流水线（仅支持含 ref_* 字段的 JSON）
# - Stage 1: 并行 shard，计算 gap 统计
# - Stage 2: merge + 根据 gap mean/std 阈值过滤异常 case
#
# ※ 必须在脚本所在目录（deploy_cmd/）下执行
#
# 示例：
#   cd /workspace/wangyd13@xiaopeng.com/CLIP-IQA/deploy_cmd
#
#   # 基础用法（无过滤）
#   bash clip-iqa-local_fidelity_job.sh J11918778 8
#
#   # 带阈值过滤
#   bash clip-iqa-local_fidelity_job.sh J11918778 8 10.0 5.0

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <job_id> [num_shards=7] [gap_mean_threshold] [gap_std_threshold]"
    echo ""
    echo "Examples:"
    echo "  $0 J11918778 8              # 8-shard parallel, no filtering"
    echo "  $0 J11918778 8 10.0 5.0     # filter gap_mean > 10.0 or gap_std > 5.0"
    exit 1
fi

JOB_ID="$1"
NUM_SHARDS="${2:-7}"
GAP_MEAN_THR="${3:-}"
GAP_STD_THR="${4:-}"

# ══════════════════════════════════════════════════════════════
# ─── 用户配置区（修改此处以适配不同用户环境）─────────────────
# ══════════════════════════════════════════════════════════════

# 用户工作区路径（根据实际情况修改，默认从环境变量读取或使用当前用户）
USER_WORKSPACE="${USER_WORKSPACE:-/workspace/${USER}@xiaopeng.com}"
USER_SHARED="${USER_SHARED:-/workspace/group_share/adc-sim/users/${USER}}"

# CLIP-IQA 项目路径（使用相对路径，自动定位到 simworld/models/CLIP-IQA）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLIP_IQA_PATH="$(cd "${SCRIPT_DIR}/../.." && pwd)"
# 修复 symlink 路径：本地 /root/workspace → /workspace（fuyao 云端挂载路径）
CLIP_IQA_PATH="${CLIP_IQA_PATH/#\/root\/workspace\//\/workspace\/}"
# fuyao 云端使用的 USER_WORKSPACE（去除 /root 前缀）
FUYAO_USER_WORKSPACE="${USER_WORKSPACE/#\/root\/workspace\//\/workspace\/}"

# Conda 环境名（sim-clip-iqa_sim_7 镜像内置）
CONDA_ENV="/root/anaconda3/envs/closeloop-3dgs"

# Docker 镜像
DOCKER_IMAGE="infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:sim-clip-iqa_sim_7"

# Fuyao 配置
GPU_TYPE="A100"
VOLUME="adc-sim"
QUEUE="adc-sim"
SITE="fuyao_b1_prod2"
PROJECT="adc-sim"
EXPERIMENT="sim3dgs-sim"

# ══════════════════════════════════════════════════════════════
# ─── 路径配置（通常无需修改）─────────────────────────────────
# ══════════════════════════════════════════════════════════════

# 输入：待评估的 case 目录根路径
JOB_DIR="${USER_SHARED}/jobid_dds/${JOB_ID}"

# 输出：shard CSV 落盘路径（共享存储）
SHARD_SUFFIX="_clipiqa_fidelity_shards"
OUTPUT_DIR="${USER_SHARED}/jobid_dds/${JOB_ID}${SHARD_SUFFIX}"

# 最终结果输出路径（merge 后，使用 simworld 同级目录）
RESULT_BASE="${USER_WORKSPACE}/clip_iqa_result"
FINAL_OUTPUT_DIR="${RESULT_BASE}/dds/${JOB_ID}_fidelity"

# ══════════════════════════════════════════════════════════════
# ─── 提交 NUM_SHARDS 个 fuyao job ────────────────────────────
# ══════════════════════════════════════════════════════════════

echo "=========================================="
echo "Fidelity-only Pipeline Submission"
echo "=========================================="
echo "Job ID:         ${JOB_ID}"
echo "Num Shards:     ${NUM_SHARDS}"
echo "Input Dir:      ${JOB_DIR}"
echo "Output Dir:     ${OUTPUT_DIR}"
echo "Gap Mean Thr:   ${GAP_MEAN_THR:-none}"
echo "Gap Std Thr:    ${GAP_STD_THR:-none}"
echo "=========================================="
echo ""

for (( i=0; i<NUM_SHARDS; i++ )); do
    LABEL="clipiqa_fidelity_${JOB_ID}_s${i}of${NUM_SHARDS}"
    echo "[submit] shard ${i}/${NUM_SHARDS}  label=${LABEL}"

    fuyao deploy --gpu-type="${GPU_TYPE}" --volume="${VOLUME}" --queue="${QUEUE}" --release \
                 --site="${SITE}" --label "${LABEL}" \
                 --docker-image "${DOCKER_IMAGE}" \
                 --project="${PROJECT}" --experiment "${EXPERIMENT}" --gpus-per-node=1 --nodes=1 \
        bash -c "
set -e

export HF_HOME='${FUYAO_USER_WORKSPACE}/pretrain_model'
export TORCH_HOME='${FUYAO_USER_WORKSPACE}/torch_cache'

# A100 GPU driver compatibility fix
GPU_MODELS=\$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null)
if [[ \"\$(echo \"\$GPU_MODELS\" | head -1)\" == *'A100'* ]]; then
  DRIVER_MAIN_VERSION=\$(nvidia-smi | grep -oP 'Driver Version:\s*\K\d+\.\d+\.\d+' | head -1 | cut -d'.' -f1)
  if [ \"\$DRIVER_MAIN_VERSION\" -gt 470 ]; then
    export LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu:/usr/local/cuda:/usr/local/cuda/lib:/usr/local/cuda/lib64:/usr/local/nvidia/lib:/usr/local/nvidia/lib64
    echo '[INFO] new LD_LIBRARY_PATH set for A100'
  fi
fi

mkdir -p '${OUTPUT_DIR}'
cd '${CLIP_IQA_PATH}'

source /root/anaconda3/etc/profile.d/conda.sh
conda activate '${CONDA_ENV}'

python result_evaluation/analyze_json_iqa_local_fidelity.py \
    --job_dir '${JOB_DIR}' \
    --output_dir '${OUTPUT_DIR}' \
    --num_shards ${NUM_SHARDS} \
    --shard_idx ${i}

echo '[DONE] shard ${i}/${NUM_SHARDS} finished: ${OUTPUT_DIR}/shard_${i}.csv'
"
done

# ══════════════════════════════════════════════════════════════
# ─── 生成 merge 命令提示 ──────────────────────────────────────
# ══════════════════════════════════════════════════════════════

echo ""
echo "=========================================="
echo "All ${NUM_SHARDS} shards submitted."
echo "=========================================="
echo ""
echo "After all jobs complete, run locally to merge + compute fidelity scores:"
echo ""
echo "  cd ${CLIP_IQA_PATH}"
echo ""

# 根据是否提供阈值生成不同的 merge 命令
if [ -n "${GAP_MEAN_THR}" ] || [ -n "${GAP_STD_THR}" ]; then
    echo "  # Fidelity score with gap filtering:"
    MERGE_CMD="  python result_evaluation/analyze_json_iqa_local_fidelity.py \\"
    MERGE_CMD="${MERGE_CMD}\n      --merge \\"
    MERGE_CMD="${MERGE_CMD}\n      --shard_dir '${OUTPUT_DIR}' \\"
    MERGE_CMD="${MERGE_CMD}\n      --output_dir '${FINAL_OUTPUT_DIR}' \\"
    MERGE_CMD="${MERGE_CMD}\n      --filter_mode v2_full_weights"

    if [ -n "${GAP_MEAN_THR}" ]; then
        MERGE_CMD="${MERGE_CMD} \\\n      --gap_mean_threshold ${GAP_MEAN_THR}"
    fi
    if [ -n "${GAP_STD_THR}" ]; then
        MERGE_CMD="${MERGE_CMD} \\\n      --gap_std_threshold ${GAP_STD_THR}"
    fi

    echo -e "${MERGE_CMD}"
else
    echo "  # Fidelity score (no filtering):"
    echo "  python result_evaluation/analyze_json_iqa_local_fidelity.py \\"
    echo "      --merge \\"
    echo "      --shard_dir '${OUTPUT_DIR}' \\"
    echo "      --output_dir '${FINAL_OUTPUT_DIR}' \\"
    echo "      --filter_mode v2_full_weights"
    echo ""
    echo "  # Fidelity score with gap filtering (example):"
    echo "  python result_evaluation/analyze_json_iqa_local_fidelity.py \\"
    echo "      --merge \\"
    echo "      --shard_dir '${OUTPUT_DIR}' \\"
    echo "      --output_dir '${FINAL_OUTPUT_DIR}' \\"
    echo "      --filter_mode v2_full_weights \\"
    echo "      --gap_mean_threshold 20.0 \\"
    echo "      --gap_std_threshold 15.0"
fi

echo ""
echo "=========================================="
echo "Output will be saved to: ${FINAL_OUTPUT_DIR}"
echo "=========================================="
