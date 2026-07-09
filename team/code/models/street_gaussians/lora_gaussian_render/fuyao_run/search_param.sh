
# --base-model-id： 指预训练模型的路径
# --lora_weights_path： 指finetune过程中生成的模型的路径
# --image_path：输入数据的路径，也即渲染过程中生成的图片路径。
#                由于搜索过程非常费时，实际执行过程中会在该输入数据中随机抽取部分数据做搜索 
# --save_path：生成结果的保存路径
# --mask_path：mask文件存放路径
# --video_name：被搜索的video名字
# --image_guidance_scale_min: image_guidance_scale 的最小值，
#                              其与image_guidance_scale_max一起构成取值范围
# --image_guidance_scale_max: image_guidance_scale 的最大值，
#                              其与image_guidance_scale_min一起构成取值范围
# --guidance_scale_min: guidance_scale的最小值。其与guidance_scale_max一起构成取值范围
# --guidance_scale_max: guidance_scale的最大值。其与guidance_scale_min一起构成取值范围
# --batch_size:  batch size 大小

python lora_gaussian_render/search_param.py \
        --base_model_id /workspace/wenkang.qin@gigaai.cc/pretrain_model/street_gaussians_render_fix \
        --lora_weights_path /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/lora_gaussian_render/model_weights_pix2pix_0109/dropout_0.05_new \
        --image_path /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/output/xpeng_test_leo \
        --save_path /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/output/search_guidance_scale_dropout_0.05_new \
        --mask_path /workspace/wenkang.qin@gigaai.cc/xh_data/m1_vision \
        --video_name c-fff8d69c-133d-304e-ae56-e3c9ece12679 \
        --img_guidance_scale_min 0.4  --img_guidance_scale_max 1.6   \
        --guidance_scale_min 0.6  --guidance_scale_max 1.4  --batch_size 4
