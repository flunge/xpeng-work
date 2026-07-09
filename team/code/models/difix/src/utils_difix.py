import numpy as np
import cv2
import json
import os
from PIL import Image


def calculate_psnr(img1, img2, mask=None):
    """
    计算PSNR，当提供mask时，只考虑mask为True（非零）区域的像素
    """
    if isinstance(img1, Image.Image):
        img1 = np.array(img1)
    if isinstance(img2, Image.Image):
        img2 = np.array(img2)
    if img1.shape != img2.shape:
        img2_pil = Image.fromarray(img2)
        img2_pil = img2_pil.resize((img1.shape[1], img1.shape[0]), Image.Resampling.LANCZOS)
        img2 = np.array(img2_pil)
    
    img1 = img1.astype(np.float32) / 255.0
    img2 = img2.astype(np.float32) / 255.0
    
    if mask is not None:
        # mask: (H, W), 非零区域为有效区域
        if mask.shape[:2] != img1.shape[:2]:
            mask = cv2.resize(mask[0], (img1.shape[1], img1.shape[0]))
        valid_mask = mask > 0
        if img1.ndim == 3:
            valid_mask = np.broadcast_to(valid_mask[:, :, np.newaxis], img1.shape)
        if not np.any(valid_mask):
            return float('nan')
        mse = np.mean((img1[valid_mask] - img2[valid_mask]) ** 2)
    else:
        mse = np.mean((img1 - img2) ** 2)
    
    if mse == 0:
        return float('inf')
    max_pixel = 1.0
    psnr = 20 * np.log10(max_pixel / np.sqrt(mse))
    return psnr


def load_mask(custom_data, cam_names=('cam0', 'cam2', 'cam3', 'cam4', 'cam5', 'cam6', 'cam7'), image_size=None):
    # cache all masks
    mask_folder_mapping = {
        50: "xpeng_data_process/assets/Vehicle_Mask/F30_Masks",
        43: "xpeng_data_process/assets/Vehicle_Mask/E38A_Masks",
        21: "xpeng_data_process/assets/Vehicle_Mask/E28A_Masks",
        40: "xpeng_data_process/assets/Vehicle_Mask/E38_Masks",
        60: "xpeng_data_process/assets/Vehicle_Mask/H93_Masks",
        70: "xpeng_data_process/assets/Vehicle_Mask/F57_Masks",
        201: "xpeng_data_process/assets/Vehicle_Mask/XP5_201_Masks",
        205: "xpeng_data_process/assets/Vehicle_Mask/XP5_269_Masks",
        203: "xpeng_data_process/assets/Vehicle_Mask/E38B_Masks",
        206: "xpeng_data_process/assets/Vehicle_Mask/F30B_Masks",
        231: "xpeng_data_process/assets/Vehicle_Mask/H93AS_Masks",
        269: "xpeng_data_process/assets/Vehicle_Mask/XP5_269_Masks"
        # 可以在这里继续添加其他车型的映射
    }
    code_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cached_masks = {} # key vehicle_model, value is mask
    all_clips = {} # key clip id, value is metadata path
    for val in custom_data.values():
        if val["clip_id"] not in all_clips:
            src_img_path = "/".join(list(custom_data.values())[0]["image"].split("/")[:-4])
            metadata = json.load(open(os.path.join(src_img_path, "metadata.json")))
            vehicle_model = metadata.get("vehicle_model", None)
            mask_folder = mask_folder_mapping.get(vehicle_model) + "_Origin"
            mask_dict = {}
            for cam_name in cam_names:
                mask_file_name = f"_{cam_name}_mask.png"
                mask_path = os.path.join(code_dir, mask_folder, mask_file_name)
                if mask_path not in cached_masks:
                    if os.path.exists(mask_path):
                        mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
                        if image_size is not None:
                            mask = cv2.resize(mask, (image_size[1], image_size[0]))
                    else:
                        print(f"Mask file not found: {mask_path}, Use all white mask")
                        if image_size is not None:
                            mask = np.ones((image_size[1], image_size[0]), dtype=np.uint8) * 255
                        else:
                            mask = None
                    mask = np.expand_dims(mask, axis=0)
                    cached_masks[mask_path] = mask
                else:
                    mask = cached_masks[mask_path]
                mask_dict[cam_name] = mask
            all_clips[val["clip_id"]] = mask_dict
    return all_clips


def save_config(output_dir, args):
    config = {
        "image_height": args.image_height,
        "image_width": args.image_width,
        "lora_rank_vae": args.lora_rank_vae,
        "timestep": args.timestep,
    }
    with open(os.path.join(output_dir, "config.json"), "w") as f:
        json.dump(config, f)
        
        
def load_config(ckpt_path):
    with open(os.path.join(ckpt_path, "config.json"), "r") as f:
        config = json.load(f)
    return config