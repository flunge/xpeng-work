# --input_path: 输入数据的路径。也即生成模型推理后得到的图片路径。代码执行完后会将此路径下的所有视频都生成完
# --output_path： 得到的视频结果的保存路径
# --mask_path：mask 路径

python lora_gaussian_render/gen_video_from_image.py  \
    --input_path /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/lora_gaussian_render/generative_pix2pix_output/dropout0.05_new \
    --output_path /workspace/wenkang.qin@gigaai.cc/code/models/street_gaussians/lora_gaussian_render/generative_pix2pix_videos/dropout0.05_new \
    --mask_path /workspace/wenkang.qin@gigaai.cc/xh_data/m1_vision/
