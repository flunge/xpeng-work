#!/usr/bin/env bash
# NVFixer 批量推理脚本
# 用法：bash run_infer.sh [options]
#
# 参数：
#   -i | --input         输入目录（含多个 cam* 子文件夹）         [必填]
#   -c | --ckpt          checkpoint 目录路径                       [必填]
#   -o | --output        输出目录                                   [必填]
#   --resolution         推理分辨率（默认 1024）
#   --batch_size         批大小（默认 1）
#   --max_frames         每个子文件夹最多处理帧数（默认不限）
#   --skip_frames        帧间隔采样，每 N 帧取 1 帧（默认 1）
#   --folder_pattern     子文件夹过滤 glob（如 "cam*"，默认处理全部）
#   -r | --ref_dir       参考图目录（可选，需与输入文件名匹配）
#   --warmup_iters       预热迭代次数（默认 10）
#   --save_frames        保留每帧输出图片（默认不保留，仅保存视频）
#   --vae_skip           开启 VAE skip connection
#   -h | --help          显示此帮助
#
# 注：timestep / use_reference_image 等模型架构参数自动从 ckpt 目录下的
#     train_config.yaml 读取，无需手动指定。

set -euo pipefail

# ── 默认值 ──────────────────────────────────────────────────────────────────
INPUT_DIR=""
CKPT_PATH=""
OUTPUT_DIR=""
RESOLUTION=1024
BATCH_SIZE=1
MAX_FRAMES=""
SKIP_FRAMES=1
FOLDER_PATTERN="cam*"
REF_DIR=""
WARMUP_ITERS=10
SAVE_FRAMES=true
VAE_SKIP=false

# ── 参数解析 ─────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    -i|--input)          INPUT_DIR="$2";       shift 2 ;;
    -c|--ckpt)           CKPT_PATH="$2";       shift 2 ;;
    -o|--output)         OUTPUT_DIR="$2";      shift 2 ;;
    --resolution)        RESOLUTION="$2";      shift 2 ;;
    --batch_size)        BATCH_SIZE="$2";      shift 2 ;;
    --max_frames)        MAX_FRAMES="$2";      shift 2 ;;
    --skip_frames)       SKIP_FRAMES="$2";     shift 2 ;;
    --folder_pattern)    FOLDER_PATTERN="$2";  shift 2 ;;
    -r|--ref_dir|-ref_dir) REF_DIR="$2";      shift 2 ;;
    --warmup_iters)      WARMUP_ITERS="$2";    shift 2 ;;
    --save_frames)       SAVE_FRAMES=true;     shift   ;;
    --vae_skip)          VAE_SKIP=true;        shift   ;;
    -h|--help)
      # 打印文件顶部连续注释块（遇到空行或非注释行停止）
      sed -n '/^#!/d; /^#/p; /^[^#]/q' "$0" | sed 's/^# \?//'
      exit 0 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

# ── 必填参数检查 ─────────────────────────────────────────────────────────────
if [[ -z "$INPUT_DIR" || -z "$CKPT_PATH" || -z "$OUTPUT_DIR" ]]; then
  echo "错误：-i/--input、-c/--ckpt、-o/--output 为必填项"
  echo "使用 -h 查看帮助"
  exit 1
fi

if [[ ! -d "$INPUT_DIR" ]]; then
  echo "错误：输入目录不存在: $INPUT_DIR"
  exit 1
fi

if [[ ! -d "$CKPT_PATH" ]]; then
  echo "错误：checkpoint 目录不存在: $CKPT_PATH"
  exit 1
fi

# ── 路径计算 ─────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFERENCE_SCRIPT="$SCRIPT_DIR/src/inference_pretrained_model.py"

if [[ ! -f "$INFERENCE_SCRIPT" ]]; then
  echo "错误：推理脚本未找到: $INFERENCE_SCRIPT"
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

# ── 构造 Python 命令 ──────────────────────────────────────────────────────────
CMD=(
  python "$INFERENCE_SCRIPT"
  --model         "$CKPT_PATH"
  --input         "$INPUT_DIR"
  --output        "$OUTPUT_DIR"
  --resolution    "$RESOLUTION"
  --batch_size    "$BATCH_SIZE"
  --skip_frames   "$SKIP_FRAMES"
  --warmup-iters  "$WARMUP_ITERS"
  --batch_folders
  --save_video          # 始终生成视频
)

[[ -n "$FOLDER_PATTERN" ]]  && CMD+=(--folder_pattern "$FOLDER_PATTERN")
[[ -n "$MAX_FRAMES" ]]      && CMD+=(--max_frames "$MAX_FRAMES")
[[ -n "$REF_DIR" ]]         && CMD+=(--ref_dir "$REF_DIR")
[[ "$VAE_SKIP" == true ]]   && CMD+=(--vae_skip_connection)

# ── 打印配置 ─────────────────────────────────────────────────────────────────
echo "============================================================"
echo "  NVFixer 批量推理"
echo "============================================================"
echo "  输入目录   : $INPUT_DIR"
echo "  Checkpoint : $CKPT_PATH"
echo "  输出目录   : $OUTPUT_DIR"
echo "  分辨率     : $RESOLUTION"
echo "  批大小     : $BATCH_SIZE"
echo "  帧间隔     : $SKIP_FRAMES"
echo "  最大帧数   : ${MAX_FRAMES:-不限}"
echo "  子文件夹   : ${FOLDER_PATTERN:-全部}"
echo "  参考图目录 : ${REF_DIR:-未指定}"
echo "  保留图片   : $SAVE_FRAMES"
echo "  VAE skip   : $VAE_SKIP"
echo "  (模型架构参数从 train_config.yaml 自动读取)"
echo "============================================================"

# ── 执行推理 ─────────────────────────────────────────────────────────────────
echo ""
echo "▶ 开始推理..."
"${CMD[@]}"

# ── 视频已由 Python 脚本生成；如不保留图片则清理 ─────────────────────────────
if [[ "$SAVE_FRAMES" == false ]]; then
  echo ""
  echo "▶ 清理中间帧图片（--save_frames 未指定）..."
  find "$OUTPUT_DIR" -maxdepth 2 \( -name "*.png" -o -name "*.jpg" -o -name "*.jpeg" \) -delete
  echo "  ✓ 图片已清理"
fi

echo ""
echo "============================================================"
echo "  ✓ 完成！视频保存在: $OUTPUT_DIR"
echo "============================================================"
