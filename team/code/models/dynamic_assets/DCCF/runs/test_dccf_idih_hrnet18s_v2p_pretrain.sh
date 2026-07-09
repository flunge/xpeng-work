pretrain_path="pretrained_models/dccf_idih_hrnet18s_v2p_HR_pretrain.pth"
CUDA_VISIBLE_DEVICES=0 python3 scripts/evaluate_upsample_refiner.py hrnet18s_v2p_idih256_upsample_hsl_refine_HR ${pretrain_path} \
    --resize-strategy Fixed256 \
    --version hsl \
    --config-path config_test_HR.yml \
    --datasets TEST_7A9F_23012155_CAM0 \
    --vis-dir "./harmonization_exps_hr/images_cam0"

# CUDA_VISIBLE_DEVICES=0 python3 scripts/evaluate_upsample_refiner.py hrnet18s_v2p_idih256_upsample_hsl_refine_HR ${pretrain_path} \
#     --resize-strategy Fixed256 \
#     --version hsl \
#     --config-path config_test_HR.yml \
#     --datasets TEST_7A9F_23012155_CAM2 \
#     --vis-dir "./harmonization_exps_hr/images_cam2"

# CUDA_VISIBLE_DEVICES=0 python3 scripts/evaluate_upsample_refiner.py hrnet18s_v2p_idih256_upsample_hsl_refine_HR ${pretrain_path} \
#     --resize-strategy Fixed256 \
#     --version hsl \
#     --config-path config_test_HR.yml \
#     --datasets TEST_7A9F_23012155_CAM3 \
#     --vis-dir "./harmonization_exps_hr/images_cam3"

# CUDA_VISIBLE_DEVICES=0 python3 scripts/evaluate_upsample_refiner.py hrnet18s_v2p_idih256_upsample_hsl_refine_HR ${pretrain_path} \
#     --resize-strategy Fixed256 \
#     --version hsl \
#     --config-path config_test_HR.yml \
#     --datasets TEST_7A9F_23012155_CAM4 \
#     --vis-dir "./harmonization_exps_hr/images_cam4"

# CUDA_VISIBLE_DEVICES=0 python3 scripts/evaluate_upsample_refiner.py hrnet18s_v2p_idih256_upsample_hsl_refine_HR ${pretrain_path} \
#     --resize-strategy Fixed256 \
#     --version hsl \
#     --config-path config_test_HR.yml \
#     --datasets TEST_7A9F_23012155_CAM5 \
#     --vis-dir "./harmonization_exps_hr/images_cam5"

# CUDA_VISIBLE_DEVICES=0 python3 scripts/evaluate_upsample_refiner.py hrnet18s_v2p_idih256_upsample_hsl_refine_HR ${pretrain_path} \
#     --resize-strategy Fixed256 \
#     --version hsl \
#     --config-path config_test_HR.yml \
#     --datasets TEST_7A9F_23012155_CAM6 \
#     --vis-dir "./harmonization_exps_hr/images_cam6"

# CUDA_VISIBLE_DEVICES=0 python3 scripts/evaluate_upsample_refiner.py hrnet18s_v2p_idih256_upsample_hsl_refine_HR ${pretrain_path} \
#     --resize-strategy Fixed256 \
#     --version hsl \
#     --config-path config_test_HR.yml \
#     --datasets TEST_7A9F_23012155_CAM7 \
#     --vis-dir "./harmonization_exps_hr/images_cam7"

# pretrain_path='pretrained_models/dccf_idih_hrnet18s_v2p_LR_pretrain.pth'
# CUDA_VISIBLE_DEVICES=0 python3 scripts/evaluate_upsample_refiner.py hrnet18s_v2p_idih256_upsample_hsl_refine_LR ${pretrain_path} \
#     --resize-strategy Fixed256 \
#     --res LR \
#     --version hsl \
#     --config-path config_test_LR.yml \
#     --datasets 7A9F_22963641_CAM0 \
#     --vis-dir 
