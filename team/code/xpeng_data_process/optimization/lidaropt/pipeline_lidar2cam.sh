#!/bin/bash

DATA_ROOT="/workspace/zhouf4@xiaopeng.com/data/posemapping_jija/c-f71bccd0-b443-30e7-a111-4c4d420fc378_v3_test"

OUTPUT_2dgs="output_cf71_v3test"

SAVE_DIR="cf71-0-t"

WORK_ROOT="/workspace/zhouf4@xiaopeng.com/code/publish/official/simworld/xpeng_data_process/optimization/lidaropt"

DYN_MASK_DIR_CAM0="$DATA_ROOT/masks_obj"
ROAD_MASK_DIR_CAM0="$DATA_ROOT/segs"
DYN_MASK_DIR_CAM2="$DATA_ROOT/masks_obj"
ROAD_MASK_DIR_CAM2="$DATA_ROOT/segs"
# DYN_MASK_DIR_CAM0="$WORK_ROOT/c-c97_cam0_masks/fine_dynamic_masks_all"
# ROAD_MASK_DIR_CAM0="$WORK_ROOT/c-c97_cam0_masks/road_masks"
# DYN_MASK_DIR_CAM2="$WORK_ROOT/c-c97_cam2_masks/fine_dynamic_masks_all"
# ROAD_MASK_DIR_CAM2="$WORK_ROOT/c-c97_cam2_masks/road_masks"
# DYN_MASK_DIR_CAM0="$WORK_ROOT/c-997_cam0_masks/fine_dynamic_masks_all"
# ROAD_MASK_DIR_CAM0="$WORK_ROOT/c-997_cam0_masks/road_masks"
# DYN_MASK_DIR_CAM2="$WORK_ROOT/c-997_cam2_masks/fine_dynamic_masks_all"
# ROAD_MASK_DIR_CAM2="$WORK_ROOT/c-997_cam2_masks/road_masks"

CAM0="cam0"
CAM2="cam2"
NUM_PCD_CVT=50
CUDA_DEVICE="0"
CONFIG_FILE="$WORK_ROOT/lidar2cam_opt/submodules/Python-VO/params/kitti_superpoint_supergluematch.yaml"
CONFIG_FILE_2dgs="$WORK_ROOT/lidar2cam_opt/option.yml"

if [ ! -d "$DATA_ROOT" ]; then
  echo "错误：数据根目录 $DATA_ROOT 不存在！"
  exit 1
fi

if [ ! -d "$DYN_MASK_DIR_CAM0" ]; then
  echo "错误：动态掩码目录 $DYN_MASK_DIR_CAM0 不存在！"
  exit 1
fi
if [ ! -d "$ROAD_MASK_DIR_CAM0" ]; then
  echo "错误：道路掩码目录 $ROAD_MASK_DIR_CAM0 不存在！"
  exit 1
fi

export CUDA_VISIBLE_DEVICES=$CUDA_DEVICE

# 1. 生成lidar2cam优化所需数据 (kitti形式), 使用cam0
echo "[Step 1]: running data preparation..."
python ./process/gen_global_pcd.py \
    --data_root="$DATA_ROOT" \
    --dyn_mask_dir="$DYN_MASK_DIR_CAM0" \
    --road_mask_dir="$ROAD_MASK_DIR_CAM0" \
    --cam="$CAM0" \
    --num_pcd_cvt="$NUM_PCD_CVT"
if [ $? -ne 0 ]; then
  echo "error: data preparation fails！"
  exit 1
fi
# 输出为 data_root/pcd_cvt_0目录

TMP_CONFIG="/tmp/kitti_superpoint_supergluematch_modified.yaml"
sed "s|root_path: .*|root_path: $DATA_ROOT/pcd_cvt_0|" "$CONFIG_FILE" > "$TMP_CONFIG"
CONFIG_FILE="$TMP_CONFIG"

# 2. superpoint&superglue特征匹配
echo "[Step 2]: running SuperPoint & SuperGlue..."
cd lidar2cam_opt/submodules/Python-VO
python main.py --config "$CONFIG_FILE"
if [ $? -ne 0 ]; then
  echo "error: superglue fails!"
  exit 1
fi

cd ../../..

TMP_CONFIG_2dgs="/tmp/option.yaml"
sed "s|path: .*|path: $DATA_ROOT/pcd_cvt_0|" "$CONFIG_FILE_2dgs" > "$TMP_CONFIG_2dgs"
sed "s|output: .*|output: $OUTPUT_2dgs|" "$TMP_CONFIG_2dgs" > "${TMP_CONFIG_2dgs}.tmp"
mv "${TMP_CONFIG_2dgs}.tmp" "$TMP_CONFIG_2dgs"
CONFIG_FILE_2dgs="$TMP_CONFIG_2dgs"

# 3. 2dgs
echo "[Step 3]: running 2DGS..."
cd lidar2cam_opt
python geometry/main.py --save_dir "$SAVE_DIR" --config "$CONFIG_FILE_2dgs"
if [ $? -ne 0 ]; then
  echo "error: running 2DGS fails!"
  exit 1
fi

# 4. calibration
echo "[Step 4]: running calibration..."
python calibration/main.py -g="$SAVE_DIR" --render --config "$CONFIG_FILE_2dgs"
if [ $? -ne 0 ]; then
  echo "error: running calibration fails!"
  exit 1
fi

cp "$OUTPUT_2dgs/$SAVE_DIR/res.json" "$DATA_ROOT/pcd_cvt_0/"
if [ $? -ne 0 ]; then
  echo "error: copy res.json fails!"
  exit 1
fi

# 5. lidar2cam优化后, 使用cam2, 用求解的delta_lidar2ego重新生成整体点云
echo "[Step 5]: running pcd regeneration..."
cd ../process
python gen_global_pcd.py --data_root="$DATA_ROOT" \
    --dyn_mask_dir="${DYN_MASK_DIR_CAM2}" \
    --road_mask_dir="${ROAD_MASK_DIR_CAM2}"\
    --cam="$CAM2" \
    --num_pcd_cvt="$NUM_PCD_CVT" \
    --apply_delta_lidar2ego
if [ $? -ne 0 ]; then
  echo "error: pcd regeneratio fails!"
  exit 1
fi
# 输出为 data_root/points3D_bkgd_new.ply和data_root/ground_mask_new.npy

echo "FINISH!!"