# 这里首先需要准备好预训练模型，放在--base-model-id参数下，
# 准备好上一步生成模型需要的打包数据，放在--dataset-dict-path下，
# 设置合适的max-step和epoch，一般来说，一个case训练5000步效果即可，具体训练步数为min(num_epoch * len(self.dataloader), max_step)
# save dir为保存目录
# export HF_ENDPOINT=https://hf-mirror.com

export HF_HOME=/workspace/wenkang.qin@gigaai.cc/pretrain_model
 for pkl in /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/lora_gaussian_render/generative_model_data/origin/*; do
 	echo $pkl
     filename=$(basename "$pkl" .pkl)
     mkdir -p /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/lora_gaussian_render/model_weights_pix2pix_0109/dropout_0.05_new/$filename
 	python lora_gaussian_render/train.py \
         --base-model-id  /workspace/wenkang.qin@gigaai.cc/pretrain_model/street_gaussians_render_fix \
         --dataset-dict-path $pkl \
         --max-step 5000 \
         --num_epoch 60 \
         --dropout_prob 0.05 \
         --save-dir /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/lora_gaussian_render/model_weights_pix2pix_0109/dropout_0.05_new/$filename
         #--mask_path /workspace/wenkang.qin@gigaai.cc/xh_data/m1_vision/$filename
 done
