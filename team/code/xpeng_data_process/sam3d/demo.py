import os
from pathlib import Path
import sys
import torch
import numpy as np

current_dir = os.path.dirname(os.path.abspath(__file__))
notebook_dir = os.path.join(current_dir, "notebook")
# import inference code
sys.path.append(notebook_dir)
from inference import Inference, load_image, load_single_mask, load_mask

# load model
config_path = f"/workspace/group_share/adc-sim/users/wangyd13/checkpoints/pipeline.yaml"
inference = Inference(config_path, compile=False)

# load image (RGBA only, mask is embedded in the alpha channel)
# image = load_image("/workspace/group_share/adc-sim/users/dsc/sam3d_data/slice278_cam2.png")
# mask = load_mask("/workspace/group_share/adc-sim/users/dsc/sam3d_data/seg.png")
# # mask = load_single_mask("/workspace/wangyd13@xiaopeng.com/sam-3d-objects/notebook/images/shutterstock_stylish_kidsroom_1640806567", index=14)

# # run model
# output = inference(image, mask, seed=42)

# # export gaussian splat
# output["gs"].save_ply(f"splat.ply")
# print("Your reconstruction has been saved to splat.ply")


# 输入目录路径
input_directory = "/root/workspace/group_share/adc-sim/users/dsc/sam3d_data/"  # 输入图像和掩码目录路径
output_directory = "/root/workspace/wangyd13@xiaopeng.com/datasets"  # 输出目录与输入目录相同
# 确保目录路径存在
if not os.path.exists(input_directory):
    print(f"目录不存在: {input_directory}")
else:
    # 获取目录中的所有文件
    files = os.listdir(input_directory)
    
    # 分别存储图像文件和掩码文件
    image_files = []
    mask_files = []
    
    # 遍历文件，根据文件名特征分类
    for filename in files:
        if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            # 检查文件名是否包含下划线
            if '_' in filename:
                # 检查文件名最后一个下划线后的字符是否为'mask'
                name_parts = filename.split('_')
                if name_parts[-1].startswith('mask'):
                    mask_files.append(filename)
                else:
                    image_files.append(filename)
            else:
                # 没有下划线的文件作为图像文件
                image_files.append(filename)
    
    # 匹配图像文件和掩码文件并执行推理
    for image_filename in image_files:
        # 构建图像文件路径
        image_path = os.path.join(input_directory, image_filename)
        
        # 尝试找到对应的掩码文件
        # 假设掩码文件名是图像文件名加上'_mask'后缀
        image_name_without_ext = os.path.splitext(image_filename)[0]
        mask_filename = image_name_without_ext + "_mask.png"  # 假设掩码文件是PNG格式
        depth_filename = image_name_without_ext + "_depth.npy"  # 假设深度文件是PNG格式
        
        # 如果存在对应的掩码文件
        if mask_filename in mask_files:
            mask_path = os.path.join(input_directory, mask_filename)
            depth_path = os.path.join(input_directory, depth_filename)
            # 加载图像和掩码
            image = load_image(image_path)
            mask = load_mask(mask_path)
            depth_data = np.load(depth_path)  

            # 检查数据维度并转换为(H, W, 3)格式
            # 如果depth_data是(H, W)的深度图，您需要将其转换为点云坐标
            if depth_data.ndim == 2:
                # 这是一个简单的示例，实际转换需要根据相机内参进行
                # 创建坐标网格
                h, w = depth_data.shape
                y, x = np.mgrid[0:h, 0:w]
                
                # 简单的点云转换（需要根据实际相机参数调整）
                # 这里假设fx, fy, cx, cy是相机内参
                fx, fy, cx, cy = 500, 500, w/2, h/2  # 示例值，需要替换为实际值
                
                # 计算3D坐标
                x_3d = (x - cx) * depth_data / fx
                y_3d = (y - cy) * depth_data / fy
                z_3d = depth_data
                
                # 组合成(H, W, 3)的点云
                pointmap = np.stack([x_3d, y_3d, z_3d], axis=-1)
                
            elif depth_data.ndim == 3 and depth_data.shape[2] == 3:
                # 如果已经是(H, W, 3)格式，直接使用
                pointmap = depth_data
            pointmap_tensor = torch.from_numpy(pointmap).float()
            # 执行推理
            output = inference(image, mask, seed=42, pointmap=pointmap)
            
            # 构建输出文件路径（与输入在同一目录下）
            output_filename = os.path.splitext(image_filename)[0] + ".ply"
            output_path = os.path.join(output_directory, output_filename)
            
            # 保存结果
            output["gs"].save_ply(output_path)
            print(f"处理完成: {image_filename} -> {output_filename}")
