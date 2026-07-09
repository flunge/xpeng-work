# export HF_ENDPOINT=https://hf-mirror.com
export HF_HOME=/workspace/wenkang.qin@gigaai.cc/pretrain_model

# for cfg in /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/configs/xpeng_100k_test_leo/*; do
# 	echo $pkl
#     filename=$(basename "$cfg" .yaml)
#     mkdir -p /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/lora_gaussian_render/generative_model_output/$filename
# 	fuyao deploy --site=fuyao_a1 \
# 		--queue=adc-sim-external \
# 		--job-name leo_gen \
# 		--label xiaopeng_sg \
# 	    --docker-image infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:wenkang.qin-241225-0309 \
# 		--project=4DWorldModel \
# 		--gpus-per-node=1 \
# 		--nodes=1 \
# 		"ls; cd /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/lora_gaussian_render; ls;
# 		 python inference.py 
# 			--base_model_id  /workspace/wenkang.qin@gigaai.cc/pretrain_model/street_gaussians_render_fix 
# 			--lora_weights_path /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/lora_gaussian_render/generative_model_output/$filename/unet_weights 
# 			--inference_pkl_path /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/lora_gaussian_render/generative_model_data/origin_render_$filename.pkl 
# 			--save_path /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/lora_gaussian_render/generative_model_output/$filename/result;

# 		 python inference.py 
# 			--base_model_id  /workspace/wenkang.qin@gigaai.cc/pretrain_model/street_gaussians_render_fix 
# 			--lora_weights_path /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/lora_gaussian_render/generative_model_output/$filename/unet_weights 
# 			--inference_pkl_path /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/lora_gaussian_render/generative_model_data/origin_render_$filename.pkl 
# 			--save_path /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/lora_gaussian_render/generative_model_output/$filename/result"
# done


fuyao deploy --site=fuyao_a1 \
			--queue=adc-sim-external \
			--job-name leo_gen \
			--label xiaopeng_sg \
			--docker-image infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:wenkang.qin-241225-0309 \
			--project=4DWorldModel \
			--gpus-per-node=1 \
			--nodes=1 \
			"ls; cd /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/lora_gaussian_render; ls; 
			python inference.py 
			--base_model_id /workspace/wenkang.qin@gigaai.cc/pretrain_model/street_gaussians_render_fix 
			--lora_weights_path /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/lora_gaussian_render/generative_model_output/c-fffbbe20-7c67-3729-a449-f26bc0e9f67e/unet_weights 
			--inference_pkl_path /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/lora_gaussian_render/generative_model_data/shift_render_c-fffbbe20-7c67-3729-a449-f26bc0e9f67e.pkl 
			--save_path /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/lora_gaussian_render/generative_model_output/c-fffbbe20-7c67-3729-a449-f26bc0e9f67e/result"


# fuyao deploy --site=fuyao_a1 \
# 			--queue=adc-sim-external \
# 			--job-name leo_gen \
# 			--label xiaopeng_sg \
# 			--docker-image infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:wenkang.qin-241225-0309 \
# 			--project=4DWorldModel \
# 			--gpus-per-node=1 \
# 			--nodes=1 \
# 			"ls; cd /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/lora_gaussian_render; ls; bash infer.sh"

# c-fff9095c-176e-3bf0-8479-ddd0c8cf1819
# ls; cd /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/lora_gaussian_render; ls; 



# python inference.py 
			# --base_model_id /workspace/wenkang.qin@gigaai.cc/pretrain_model/street_gaussians_render_fix 
			# --lora_weights_path /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/lora_gaussian_render/generative_model_output/c-fffbad8d-303d-3426-bc14-1dff335a9400/unet_weights 
			# --inference_pkl_path /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/lora_gaussian_render/generative_model_data/origin_render_c-fffbad8d-303d-3426-bc14-1dff335a9400.pkl 
			# --save_path /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/lora_gaussian_render/generative_model_output/c-fffbad8d-303d-3426-bc14-1dff335a9400/result;