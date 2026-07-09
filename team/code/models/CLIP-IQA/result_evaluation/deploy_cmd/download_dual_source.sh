#!/bin/bash
# 双源下载：从 CCES job 下载 scenario.json，从 e2e job 下载 clipiqa_scores.json
# 按 scenario_description 匹配两个 job 的对应关系
#
# 用法:
#   bash download_dual_source.sh <cces_job_id> <e2e_job_id> [num_shards] [only_files] [limit]
#
# 示例:
#   bash download_dual_source.sh 11910037 146175           # 8 分片并行，下载全部
#   bash download_dual_source.sh 11910037 146175 4         # 4 分片
#   bash download_dual_source.sh 11910037 146175 8 clipiqa_scores.json 10  # 每分片限 10 条

if [ "$#" -lt 2 ]; then
    echo "Usage: $0 <cces_job_id> <e2e_job_id> [num_shards=8] [only_files=clipiqa_scores.json] [limit=0]"
    exit 1
fi

CCES_JOB_ID="$1"
E2E_JOB_ID="$2"
NUM_SHARDS="${3:-8}"
ONLY_FILES="${4:-clipiqa_scores.json}"
LIMIT="${5:-0}"

task_prefix="dds_dual"

# 自动检测用户和工作目录
USER_NAME="${USER:-wangyd13}"
USER_WORKSPACE="${USER_WORKSPACE:-/workspace/${USER_NAME}@xiaopeng.com}"
USER_SHARED="${USER_SHARED:-/workspace/group_share/adc-sim/users/${USER_NAME}}"

# 脚本路径（使用相对路径）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLIP_IQA_PATH="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SCRIPT="${CLIP_IQA_PATH}/result_evaluation/download_cases_oss1.py"
# 修复 symlink 路径：本地 /root/workspace → /workspace（fuyao 云端挂载路径）
SCRIPT="${SCRIPT/#\/root\/workspace\//\/workspace\/}"

# 输出目录
OUT_DIR="${USER_SHARED}/jobid_dds"

echo "[INFO] CCES job=${CCES_JOB_ID}, e2e job=${E2E_JOB_ID}"
echo "[INFO] num_shards=${NUM_SHARDS}, only_files=${ONLY_FILES}, limit=${LIMIT}"
echo "[INFO] 输出目录: ${OUT_DIR}/J${CCES_JOB_ID}"
echo ""

for SHARD_IDX in $(seq 0 $((NUM_SHARDS - 1))); do
    LABEL="${task_prefix}_C${CCES_JOB_ID}_E${E2E_JOB_ID}_s${SHARD_IDX}"
    echo "[SUBMIT] shard ${SHARD_IDX}/${NUM_SHARDS} → label=${LABEL}"

     fuyao deploy \
        --gpu-type=A100 --volume=adc-sim --queue=adc-sim --release \
        --site=fuyao_b1_prod2 --label "${LABEL}" \
        --docker-image infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:dusc-260121-1905 \
        --project="adc-sim" --experiment "sim3dgs-sim" \
        --gpus-per-node=1 --nodes=1 \
        bash -c "
set -e

# ── A100 库路径修复 ─────────────────────────────────────────
GPU_MODELS=\$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null)
if [[ \"\$(echo \"\$GPU_MODELS\" | head -1)\" == *'A100'* ]]; then
  DRIVER_MAIN_VERSION=\$(nvidia-smi | grep -oP 'Driver Version:\s*\K\d+\.\d+\.\d+' | head -1 | cut -d'.' -f1)
  if [ \"\$DRIVER_MAIN_VERSION\" -gt 470 ]; then
    export LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu:/usr/local/cuda:/usr/local/cuda/lib:/usr/local/cuda/lib64:/usr/local/nvidia/lib:/usr/local/nvidia/lib64
    echo '[INFO] new LD_LIBRARY_PATH set for A100'
  fi
fi

# ── 安装依赖 ────────────────────────────────────────────────
pip install -q oss2 lz4 requests 2>/dev/null || true

echo '[INFO] shard=${SHARD_IDX}/${NUM_SHARDS} 开始：CCES=${CCES_JOB_ID} + e2e=${E2E_JOB_ID}'

python3 -u '${SCRIPT}' \
    --job_id ${CCES_JOB_ID} \
    --e2e_job_id ${E2E_JOB_ID} \
    --only_files '${ONLY_FILES}' \
    --mapping_by_job_desc \
    --out_dir '${OUT_DIR}' \
    --workers 4 \
    --shard_idx ${SHARD_IDX} \
    --num_shards ${NUM_SHARDS} \
    --limit ${LIMIT} \
    --use_ali_internal_endpoint auto

echo '[DONE] shard=${SHARD_IDX}/${NUM_SHARDS} 完成，输出: ${OUT_DIR}/J${CCES_JOB_ID}'
"
    sleep 1
done

echo ""
echo "===== 已提交 ${NUM_SHARDS} 个 fuyao 任务 ====="
echo "任务标签前缀: ${task_prefix}_C${CCES_JOB_ID}_E${E2E_JOB_ID}_s*"
echo "输出目录: ${OUT_DIR}/J${CCES_JOB_ID}"
echo ""
echo "每个 case 目录包含:"
echo "  scenario.json        <- CCES simulation/dds_stores/{sim_task_id}/"
echo "  clipiqa_scores.json  <- e2e   on_target_pytorch/dds_stores/{e2e_task_id}/"
