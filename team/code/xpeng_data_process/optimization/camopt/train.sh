#!/bin/bash

CUDA_DEVICE="0"
export CUDA_VISIBLE_DEVICES=$CUDA_DEVICE

DATA_ROOT="/workspace/zhouf4@xiaopeng.com/data/posemapping_jija/c-f71bccd0-b443-30e7-a111-4c4d420fc378_v6"
SEG_DIR_CAM0="$DATA_ROOT/segs"
CAM0="cam0"

IMAGE_DIR="$DATA_ROOT/dyn_mask"
CALIB_FILE="$DATA_ROOT/intrinsics.txt"
SAVE_NAME="$DATA_ROOT/campose"

echo "[Step 1]: running dynamic mask generation..."
python ./gen_dyn_mask.py \
    --data_root="$DATA_ROOT" \
    --seg_dir="$SEG_DIR_CAM0" \
    --cam="$CAM0"

echo "[Step 2]: running campose optimization..."
python ./run_campose_est.py --imagedir="$IMAGE_DIR" \
    --calib="$CALIB_FILE" \
    --stride=1 \
    --save_colmap \
    --name="$SAVE_NAME" \
    --opts LOOP_CLOSURE True