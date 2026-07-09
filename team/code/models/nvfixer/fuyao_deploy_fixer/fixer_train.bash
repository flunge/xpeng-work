tracker_run_name=$1
workspace_path="/workspace/wangyd13@xiaopeng.com"
hf_home_path="$workspace_path/pretrain_model"
export TORCH_HOME="$workspace_path/torch_cache"
export HF_HOME=$hf_home_path
export WANDB_API_KEY="wandb_v1_4oSCxca2U8J4mN1KxO5Cj5th57W"
fixer_path="$workspace_path/Fixer"
cd $fixer_path
# ===================== 新增：自动执行tokenizer patch =====================
# 定义patch文件路径和目标文件路径
PATCH_FILE="${fixer_path}/tokenizer.patch"
TARGET_FILE="/usr/local/lib/python3.10/dist-packages/cosmos_predict2/tokenizers/tokenizer.py"

# 检查patch文件是否存在
if [ ! -f "${PATCH_FILE}" ]; then
    echo "ERROR: tokenizer.patch not found at ${PATCH_FILE}"
    exit 1
fi

# 检查是否已经patch过（通过检查文件是否有patch标记，或直接执行patch --dry-run）
echo "Checking if tokenizer.py is already patched..."
if patch --dry-run -N "${TARGET_FILE}" "${PATCH_FILE}" > /dev/null 2>&1; then
    echo "Applying patch to ${TARGET_FILE}..."
    patch "${TARGET_FILE}" "${PATCH_FILE}"
    echo "Patch applied successfully!"
else
    echo "tokenizer.py is already patched, skip."
fi
# ===================== patch逻辑结束 =====================

HF_ENDPOINT=https://hf-mirror.com CUDA_VISIBLE_DEVICES=0 \
    python src/train_pix2pix_turbo_nocond_cosmos_base_faster_tokenizer.py \
    --output_dir "/workspace/wangyd13@xiaopeng.com/Fixer/output_finetune" \
    --dataset_folder "/workspace/wangyd13@xiaopeng.com/Fixer/datasets/output_dataset_interval24_ref.json" \
    --pretrained_path "/workspace/group_share/adc-sim/users/wangyd13/Fixer/pretrained/pretrained_fixer.pkl" \
    --max_train_steps 500000 \
    --learning_rate 2e-5 \
    --train_batch_size 1 \
    --gradient_accumulation_steps 1 \
    --dataloader_num_workers 4 \
    --timestep 250 \
    --seed 42 \
    --train_full_unet \
    --freeze_vae_encoder \
    --allow_tf32 \
    --use_sched \
    --mixed_precision bf16 \
    --train_image_prep resize_576x1024 \
    --test_image_prep resize_576x1024 \
    --lambda_l2 1.0 \
    --lambda_lpips 0.3 \
    --lambda_gan 0.0 \
    --lambda_clipsim 0.0 \
    --lambda_gram 0.0 \
    --report_to wandb \
    --tracker_project_name fixer_finetune \
    --tracker_run_name ${tracker_run_name} \
    --checkpointing_steps 1000 \
    --eval_freq 1000 \
    --viz_freq 1000 \
    --track_val_fid \
    --num_samples_eval 20
