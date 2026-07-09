import torch
# from torchvision import transforms
import torchvision.transforms.functional as F
import numpy as np
import os
from PIL import Image


def pad_and_resize(image, target_size):
    # 获取目标宽高
    target_width, target_height = target_size
    
    # 获取原始图像的宽高
    width, height = image.size
    
    # 计算 padding
    padding_left = (target_width - width) // 2
    padding_top = (target_height - height) // 2
    padding_right = target_width - width - padding_left
    padding_bottom = target_height - height - padding_top

    # 添加 padding
    if padding_left > 0 and padding_top > 0 and padding_right > 0 and padding_bottom > 0:
        padded_image = F.pad(image, (padding_left, padding_top, padding_right, padding_bottom), fill=0)  # 0 代表黑色填充
    else:
        padded_image = image
    # 调整大小
    resized_image = F.resize(padded_image, target_size)
    
    return resized_image


def resize_with_padding(image, target_size, padding_value=0):
    """
    对图像进行等比例缩放和填充以调整到目标分辨率。
    
    参数：
        image (PIL.Image): 输入图像。
        target_size (tuple): 目标尺寸 (width, height)。
        padding_value (int): 填充的颜色值，默认为黑色 (0)。
    
    返回：
        PIL.Image: 调整后的图像。
    """
    target_width, target_height = target_size
    original_width, original_height = image.size

    # 计算缩放比例
    scale = min(target_width / original_width, target_height / original_height)

    # 等比例缩放图像
    new_width = int(original_width * scale)
    new_height = int(original_height * scale)
    resized_image = F.resize(image, (new_height, new_width))

    # 计算填充
    padding_left = (target_width - new_width) // 2
    padding_top = (target_height - new_height) // 2
    padding_right = target_width - new_width - padding_left
    padding_bottom = target_height - new_height - padding_top

    # 添加填充
    padded_image = F.pad(
        resized_image,
        (padding_left, padding_top, padding_right, padding_bottom),
        fill=padding_value
    )

    return padded_image

def merge_mask(path_mask, size):
    mask_names = os.listdir(path_mask)
    ret_image = Image.open(os.path.join(path_mask, mask_names[0])).convert('RGB')
    ret_image = resize_with_padding(ret_image, size)
    ret_image = np.where(np.array(ret_image)==255, 1, 0)
    for mask_name in mask_names[1:]:
        mask_image = Image.open(os.path.join(path_mask, mask_name)).convert('RGB')
        mask_image = resize_with_padding(mask_image, size)
        mask_image = np.where(np.array(mask_image)==255, 1, 0)
        ret_image = ret_image * mask_image
    return ret_image   

def get_masks(path_mask, size, camera_ids=["cam0", "cam2", "cam3", "cam4"]):
    cam_masks = {}
    for cam_name in camera_ids:
        path_mask_img = os.path.join(path_mask, "new_masks", cam_name+".png")
        if os.path.exists(path_mask_img):
            mask = Image.open(path_mask_img)
            mask = resize_with_padding(mask, size)
            mask = np.where(np.array(mask)==255, 1, 0)
            Image.fromarray(np.uint8(mask * 255)).save('read-mask-' + cam_name + '.png')
        else:
            mask = merge_mask(os.path.join(path_mask, "masks", cam_name), size)
            Image.fromarray(np.uint8(mask * 255)).save('merge-mask-' + cam_name + '.png')
        cam_masks[cam_name] = mask
    return cam_masks

def convert_to_np(image):
    image = resize_with_padding(image, (1920, 1280))
    # ori_w, ori_h = image.size
    # resizede_image = image.resize((ori_w // 2, ori_h // 2))
    image = image.convert("RGB")
    return np.array(image).transpose(2, 0, 1)

def mask_resize_image(image, mask, size):
    resize_img = resize_with_padding(image, size)
    mask_img = np.array(resize_img) * mask
    return np.uint8(mask_img)


def preprocess_conditions(sample, conditions, tokenizer, transforms=None):
    # import pdb; pdb.set_trace()
    condition_images = []
    for condition in conditions + ["edited_image"]:
        
        condition_images.append(
            np.concatenate([convert_to_np(image) for image in sample[condition]])
        )

    images = np.concatenate(condition_images)
    images = torch.tensor(images)
    images = 2 * (images / 255) - 1
    if transforms is not None:
        images = transforms(images)

    split_conditions = images.chunk(len(conditions) + 1)
    h, w = images.shape[-2:]
    for condition, pixel_values in zip(conditions + ["edited_image"], split_conditions):
        sample[condition + "_pixel_values"] = pixel_values.reshape(-1, 3, h, w)
    input_ids = tokenizer(
        sample["edit_prompt"],
        max_length=tokenizer.model_max_length,
        padding="max_length",
        truncation=True,
        return_tensors="pt",
    )
    sample["input_ids"] = input_ids.input_ids

    return sample


def preprocess_conditions(sample, conditions, tokenizer, transforms=None, cam_masks=None):
    # import pdb; pdb.set_trace()
    condition_images = []
    for condition in conditions + ["edited_image"]:
        condition_images.append(
            np.concatenate([convert_to_np(image) for image in sample[condition]])
        )

    images = np.concatenate(condition_images)
    images = torch.tensor(images)
    images = 2 * (images / 255) - 1
    if transforms is not None:
        images = transforms(images)

    split_conditions = images.chunk(len(conditions) + 1)
    h, w = images.shape[-2:]
    for condition, pixel_values in zip(conditions + ["edited_image"], split_conditions):
        sample[condition + "_pixel_values"] = pixel_values.reshape(-1, 3, h, w)
    input_ids = tokenizer(
        sample["edit_prompt"],
        max_length=tokenizer.model_max_length,
        padding="max_length",
        truncation=True,
        return_tensors="pt",
    )
    sample["input_ids"] = input_ids.input_ids

    if cam_masks != None:
        masks = []
        for prompt in sample["edit_prompt"]:
            cam = prompt.split("CAM")[1].split(" ")[0]
            mask = cam_masks["cam"+cam]
            masks.append(torch.from_numpy(mask))
        sample["masks"] = masks

    return sample
