import os
import re
import imageio
from PIL import Image
import numpy as np
from tqdm import tqdm
import torch
import torchvision.transforms.functional as F
import tyro


def make_grid(frames):
    frames_column = [np.concatenate(frame_row, axis=1) for frame_row in frames]
    frame_grid = np.concatenate(frames_column, axis=0)

    return frame_grid


def make_grid_sequence(frames_sequence):
    frames_length = len(np.array(frames_sequence[0][0]))
    for i in range(len(frames_sequence)):
        for j in range(len(frames_sequence[0])):
            try:
                assert len(frames_sequence[i][j]) == frames_length
            except:
                print("GG")
    frames_sequence = np.asarray(frames_sequence, dtype="object")
    frames_grid = []
    for t in range(frames_length):
        grid = make_grid(frames_sequence[:, :, t])
        frames_grid.append(grid)
    return frames_grid


def get_frames(path_img, prefix_names, 
               type_name, masks, 
               image_size=(960, 720), 
               cam_ids=["cam0", "cam2", "cam3", "cam4"]):

    def mask_resize_image(prefix, cam_id, mask):
        image = Image.open(os.path.join(path_img, 
                           prefix+'_' + cam_id + '_' + type_name + '.png'))
        resize_img = resize_with_padding(image, image_size)
        mask_img = np.array(resize_img) * mask
        return np.uint8(mask_img)
        
    ret_list = []
    for idx, cam_id in tqdm(enumerate(cam_ids)):
        cam_info = []
        for prefix in tqdm(prefix_names):
            img = mask_resize_image(prefix, cam_id, masks[idx])
            cam_info.append(mask_resize_image(prefix, cam_id, masks[idx]))
        ret_list.append(cam_info)
        
    return ret_list

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
    scale = min(target_width / original_width, 
                target_height / original_height)

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

def merge_mask(path_mask, image_size=(960, 720)):
    mask_names = os.listdir(path_mask)
    ret_image = Image.open(os.path.join(path_mask, 
                                        mask_names[0])).convert('RGB')
    ret_image = resize_with_padding(ret_image, image_size)
    ret_image = np.where(np.array(ret_image)==255, 1, 0)
    for mask_name in mask_names[1:]:
        mask_image = Image.open(os.path.join(path_mask, 
                                             mask_name)).convert('RGB')
        mask_image = resize_with_padding(mask_image, image_size)
        mask_image = np.where(np.array(mask_image)==255, 1, 0)
        ret_image = ret_image * mask_image
    return ret_image   

def get_masks(path_mask, image_size=(960, 720), 
              camera_ids=["cam0", "cam2", "cam3", "cam4"]):
    masks = []
    for cam_name in camera_ids:
        path_mask_img = os.path.join(path_mask, 
                                     "new_masks", 
                                     cam_name+".png")
        if os.path.exists(path_mask_img):
            mask = Image.open(path_mask_img)
            mask = resize_with_padding(mask, image_size)
            mask = np.where(np.array(mask)==255, 1, 0)
        else:
            mask = merge_mask(os.path.join(path_mask, "masks", "cam0"),
                              image_size=image_size)
        masks.append(mask)
    return masks

def check_image_list(image_prefixs, path, 
                     camera_ids=["cam0", "cam2", "cam3", "cam4"], 
                     type_names=["gt", "origin-input", "origin-output", 
                                 "shift-input", "shift-output"]):
    def is_exist(prefix, cam_id, type_name):
        path_img = os.path.join(
                path, prefix+'_' + cam_id + '_' + type_name + '.png')
        """if os.path.exists(path_img) == False:
            return False
        try:
            image = Image.open(path_img)
            resize_img = resize_with_padding(image, (960, 720))
            return True
        except:
            print(path_img)
            return False """
        return os.path.exists(path_img)

    def is_all_exist(prefix):
        for cam_id in camera_ids:
            for type_name in type_names:
                if(is_exist(prefix, cam_id, type_name)) == False:
                    return False
        return True

    ret_list = []
    for prefix in image_prefixs:
        if is_all_exist(prefix):
            ret_list.append(prefix)
    return ret_list

def main(input_path: str,
         output_path: str,
         image_size: tuple=(960, 720),
         mask_path : str = "/workspace/wenkang.qin@gigaai.cc/xh_data/m1_vision",
         type_names: list=["gt", "origin-input", "origin-output", 
                            "shift-input", "shift-output"],
         video_name: str = ""):
    if video_name == "":
        video_names = os.listdir(input_path)
    else:
        video_names = [video_name]
    for video_name in video_names:
        if os.path.exists(os.path.join(output_path, 
                                       video_name + '.mp4')):
            print(video_name, "exist!")
            continue
        masks = get_masks(os.path.join(mask_path, video_name))
        path_img = os.path.join(input_path, video_name, "result")

        image_names = os.listdir(path_img)
        prefix_names = [image_name.split("_")[0] 
                            for image_name in image_names]
        prefix_names = list(set(prefix_names))
        prefix_names.sort()
        prefix_names = check_image_list(prefix_names, path_img, 
                                        type_names=type_names)

        show_list = []
        if "gt" in type_names:
            gt_list = get_frames(path_img, prefix_names, "gt", 
                                 masks, image_size=image_size)
            show_list.append(gt_list)
            print('get gt list', len(gt_list))

        if "origin-input" in type_names:
            origin_input_list = get_frames(path_img, prefix_names, "origin-input", 
                                           masks, image_size=image_size)
            show_list.append(origin_input_list)
            print('get origin input list')

        if "origin-output" in type_names:
            origin_output_list = get_frames(path_img, prefix_names, "origin-output", 
                                            masks, image_size=image_size)
            show_list.append(origin_output_list)
            print('get origin output list')

        if "shift-input" in type_names:
            shift_input_list = get_frames(path_img, prefix_names, "shift-input", 
                                          masks, image_size=image_size)
            show_list.append(shift_input_list)
            print('get shift input list')

        if "shift-output" in type_names:
            shift_output_list = get_frames(path_img, prefix_names, "shift-output", 
                                           masks, image_size=image_size)
            show_list.append(shift_output_list)
            print('get shift output list')

        with imageio.get_writer(os.path.join(output_path, video_name + ".mp4"), 
                                fps=24) as writer:
            frames = make_grid_sequence(show_list)
            for frame in tqdm(frames):
                writer.append_data(frame)

if __name__ == "__main__":
    tyro.cli(main)
