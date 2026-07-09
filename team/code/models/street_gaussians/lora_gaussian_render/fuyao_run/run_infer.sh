# 运行前修改图片的输入输出目录，如有必要，修改--base-model-id
# 推理的batch size效果不太明显，batch size为8比batch size为1节约1分钟左右

python lora_gaussian_render/inference.py \
        --base_model_id /workspace/wenkang.qin@gigaai.cc/pretrain_model/street_gaussians_render_fix \
        --lora_weights_path /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/lora_gaussian_render/model_weights_pix2pix_0109/dropout_0.05_new/c-fffe98ef-482c-3238-a437-6ef5b006a688/unet_weights \
        --inference_pkl_path /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/lora_gaussian_render/generative_model_data/shift_render_c-fffe98ef-482c-3238-a437-6ef5b006a688.pkl \
	--data_root /workspace/wenkang.qin@gigaai.cc/xh_data/m1_vision \
        --save_path /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/lora_gaussian_render/generative_pix2pix_output/dropout0.05_new/c-fffe98ef-482c-3238-a437-6ef5b006a688/result \
        --guidance_scale 2.0  --image_guidance_scale  0.9
