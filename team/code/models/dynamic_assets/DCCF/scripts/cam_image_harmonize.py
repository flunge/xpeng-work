import os
import cv2
import numpy as np
import tempfile
import time
import shutil
import yaml
from PIL import Image
from dynamic_assets.DCCF.scripts.harmonization_evaluator import create_harmonization_evaluator

def conduct_dccf_harmonization(model_path, simulator, img_distort, dynamic_obj_mask_distort, cam_name, image_name, timestamp, cam_id):
    result_redistort = dict()
    result_redistort['redistort_rgb'] = img_distort
    result_redistort['redistort_rgb_object'] = dynamic_obj_mask_distort

    # try with temp
    temp_dir = os.path.join(model_path, "temp_dccf", f"{timestamp}")
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir, exist_ok=True)
    
    t1 = time.time()
    img_path, dynamic_obj_mask_path = visualize_redistort_for_harmonization(
        temp_dir, simulator, result_redistort, cam_name, image_name
    )
    t2 = time.time()
    print(f"[conduct_image_harmonization] Time taken for visualization: {t2 - t1:.2f} seconds")

    dataset_name = f"{cam_id}_{timestamp}".upper()
    datasets = [dataset_name]
    dataset_path =  os.path.join(temp_dir, "dccf", cam_name)
    dataset_dirs = [
        os.path.join(dataset_path, "composite_images"),
        os.path.join(dataset_path, "real_images"),
        os.path.join(dataset_path, "masks")
    ]
    for dir_path in dataset_dirs:
        os.makedirs(dir_path, exist_ok=True)

    # 拷贝合成图片到 composite_images 和 real_images
    img_filename = os.path.basename(img_path)
    shutil.copy2(
        img_path, 
        os.path.join(dataset_dirs[0], img_filename)  # 复制到 composite_images
    )
    shutil.copy2(
        img_path, 
        os.path.join(dataset_dirs[1], img_filename)  # 复制到 real_images
    )

    # 拷贝mask图片到 masks
    dynamic_obj_mask_filename = os.path.basename(dynamic_obj_mask_path)
    shutil.copy2(
        dynamic_obj_mask_path, 
        os.path.join(dataset_dirs[2], dynamic_obj_mask_filename)  # 复制到 masks
    )

    t3 = time.time()
    print(f"[conduct_image_harmonization] Time taken for file operations: {t3 - t2:.2f} seconds")

    config_path_hr = os.path.join(dataset_path, "config_test.yml")
    # 配置内容
    config_key = dataset_name + "_PATH"
    config_data = {
        "MODELS_PATH": "",
        "EXPS_PATH": "",
        config_key: dataset_path,
    }

    # 写入YAML文件
    with open(config_path_hr, 'w') as f:
        yaml.dump(config_data, f, sort_keys=False)
    vis_base_dir = os.path.join(dataset_path, "images")
    
    simulator.camera_filter_smoother.set_cam_id(cam_id)
    if simulator.harmonization_evaluator is None:
        simulator.harmonization_evaluator = create_harmonization_evaluator('', datasets, config_path_hr=config_path_hr, vis_base_dir=vis_base_dir, res='HR')
    else:
        simulator.harmonization_evaluator.reset_cfg(config_path=config_path_hr)
    simulator.harmonization_evaluator.evaluate(
        datasets=datasets,
        res='HR',
        vis_dir=vis_base_dir
    )
    t4 = time.time()
    print(f"[conduct_image_harmonization] Time taken for harmonization evaluation: {t4 - t3:.2f} seconds")

    return vis_base_dir
    
def read_image_from_dccf_rst(vis_base_dir):
    SUPPORTED_IMG_EXTS = ('.jpg', '.jpeg', '.png', '.bmp', '.tiff')
    if not os.path.exists(vis_base_dir):
            raise FileNotFoundError(f"[read_image_from_dccf_rst] Visualization directory does not exist, please check the run_evaluation execution result: {vis_base_dir}")

    img_files = []
    for filename in os.listdir(vis_base_dir):
        if filename.startswith('.'):
            continue  # Skip hidden files
        if filename.lower().endswith(SUPPORTED_IMG_EXTS):
            img_files.append(os.path.join(vis_base_dir, filename))
    
    if len(img_files) == 0:
            raise FileNotFoundError(f"No images found in the vis_base_dir directory: {vis_base_dir}")
    elif len(img_files) > 1:
        print(f"Warning: There are {len(img_files)} images in vis_base_dir, the first one will be used: {os.path.basename(img_files[0])}")

    target_img_path = img_files[0]
    try:
        with Image.open(target_img_path) as img:
            img_rgb = img.convert('RGB')
            final_img = np.array(img_rgb, dtype=np.uint8)
    except Exception as e:
        raise RuntimeError(f"Failed to read the target image: {target_img_path}, Error: {str(e)}")

    if len(final_img.shape) != 3 or final_img.shape[2] != 3:
        channel_info = final_img.shape[2] if len(final_img.shape) >= 3 else "None"
        raise ValueError(
            f"Target image format is invalid! It should be an RGB image with shape [height, width, 3]. "
            f"Current shape: {final_img.shape}, Number of channels: {channel_info}"
        )

    return final_img


def visualize_redistort_for_harmonization(result_dir, simulator, result, cam_name, image_name):
    rgb = result['redistort_rgb']
    rgb_obj = result['redistort_rgb_object']
    
    try:
        os.makedirs(os.path.join(result_dir, "redistort_rgb", cam_name), exist_ok=True)
        os.makedirs(os.path.join(result_dir, "redistort_rgb_obj_mask", cam_name), exist_ok=True)
        os.makedirs(os.path.join(result_dir, "redistort_rgb_obj", cam_name), exist_ok=True)
        os.makedirs(os.path.join(result_dir, "redistort_rgb_obj_mask_final", cam_name), exist_ok=True)

        cv2.imwrite(os.path.join(result_dir, "redistort_rgb", cam_name, f'{image_name}.png'), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))

        cv2.imwrite(os.path.join(result_dir, "redistort_rgb_obj", cam_name, f'{image_name}.png'), cv2.cvtColor(rgb_obj, cv2.COLOR_RGB2GRAY))
        img_gray = cv2.cvtColor(rgb_obj, cv2.COLOR_RGB2GRAY)
        binary_img = np.where(img_gray > 0, 255, 0).astype(np.uint8)
        cv2.imwrite(os.path.join(result_dir, "redistort_rgb_obj_mask", cam_name, f'{image_name}.png'), binary_img)
        print(f"[visualize_redistort_for_harmonization] Saved images to temporary directory: {result_dir}")

        # 去掉边框
        background_color=(0, 0, 0)
        model_path = simulator.model_path
        frame_mask_path = os.path.join(model_path, 'images', f'{cam_name}_mask.png')
        print(f"[visualize_redistort_for_harmonization] visualize_redistort_for_harmonization frame_mask_path: {frame_mask_path}")
        # 打开并处理边框掩码图片
        with Image.open(frame_mask_path) as frame_img:
            frame_np = np.array(frame_img)
            if len(frame_np.shape) == 2:  # 灰度掩码
                # 掩码中非0的区域视为需要保留的区域
                keep_mask = frame_np != 0
            elif frame_np.shape[-1] == 3:  # RGB掩码
                # 任意通道非0的区域视为需要保留的区域
                keep_mask = np.any(frame_np != [0, 0, 0], axis=-1)
            elif frame_np.shape[-1] == 4:  # RGBA掩码，使用RGB通道判断
                keep_mask = np.any(frame_np[:, :, :3] != [0, 0, 0], axis=-1)
            else:
                raise ValueError(f"不支持的掩码图像形状: {frame_np.shape}，仅支持灰度图(2D)、RGB(3通道)或RGBA(4通道)")
        
        origin_mask_path = os.path.join(result_dir, "redistort_rgb_obj_mask", cam_name, f'{image_name}.png')
        final_mask_path = os.path.join(result_dir, "redistort_rgb_obj_mask_final", cam_name, f'{image_name}.png')
        with Image.open(origin_mask_path) as origin_mask_img:
            # 确保图片尺寸与掩码一致
            if origin_mask_img.size != (keep_mask.shape[1], keep_mask.shape[0]):
                raise ValueError(f"图像尺寸不一致")
            
            # 转换为numpy数组以便处理
            origin_mask_np = np.array(origin_mask_img)
            
            # 计算需要替换为背景色的区域（掩码之外的区域）
            replace_mask = ~keep_mask  # 取反操作
            
            # 处理不同类型的A组图片
            if len(origin_mask_np.shape) == 2:  # 灰度图
                origin_mask_np[replace_mask] = background_color[0]  # 只使用背景色的第一个通道值
            elif origin_mask_np.shape[-1] == 3:  # RGB图
                origin_mask_np[replace_mask] = background_color
            elif origin_mask_np.shape[-1] == 4:  # RGBA图，保留alpha通道
                origin_mask_np[replace_mask] = (*background_color, origin_mask_np[replace_mask, 3])
            
            # 保存处理后的图片
            result_img = Image.fromarray(origin_mask_np)
            result_img.save(final_mask_path)
            return os.path.join(result_dir, "redistort_rgb", cam_name, f'{image_name}.png'), final_mask_path
            
    finally:
        print(f"[visualize_redistort_for_harmonization] Saved images to temporary directory, {result_dir}")