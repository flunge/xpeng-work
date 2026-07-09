import numpy as np
import cv2
import torch
from PIL import Image
from torchvision import transforms
from torchmetrics.image.fid import FrechetInceptionDistance


def resize_bbox_and_padding(origin_size, target_size, xyxy):
    h, w = origin_size
    target_h, target_w = target_size   
    # 计算缩放比例
    ratio = min(target_w / w, target_h / h)
    new_w, new_h = int(w * ratio), int(h * ratio)  
    # 计算填充量（上下左右对称填充）
    delta_w, delta_h = target_w - new_w, target_h - new_h
    top, left = delta_h // 2, delta_w // 2
    ret_list = []
    for bbox in xyxy:
        x_min, y_min, x_max, y_max = bbox[0], bbox[1], bbox[2], bbox[3]
        x_min = int(x_min * ratio) + left
        y_min = int(y_min * ratio) + top
        x_max = int(x_max * ratio) + left
        y_max = int(y_max * ratio) + top
        ret_list.append([x_min, y_min, x_max, y_max, bbox[4]])
    return ret_list

def resize_bbox(origin_size, target_size, xyxy):
    h, w = origin_size
    target_h, target_w = target_size  
    # 计算缩放比例
    ratio_w, ratio_h = target_w / w, target_h / h
    ret_list = []
    for bbox in xyxy:
        x_min, y_min, x_max, y_max = bbox[0], bbox[1], bbox[2], bbox[3]
        x_min, y_min = int(x_min * ratio_w), int(y_min * ratio_h)
        x_max, y_max = int(x_max * ratio_w), int(y_max * ratio_h)
        ret_list.append([x_min, y_min, x_max, y_max, bbox[4]])
    return ret_list

def image_resize_and_padding(image, target_size, pad_color=(0, 0, 0), 
                             interpolation=cv2.INTER_LINEAR):
    """
    将图像等比例缩放并填充至目标分辨率
    
    参数:
        image: 输入图像 (H, W, C)
        #target_size: 目标分辨率 (target_width, target_height)
        pad_color: 填充颜色 (BGR格式，默认为黑色)
        interpolation: 缩放插值方法 (默认为线性插值)
    
    返回:
        padded_image: 调整后的图像 (target_height, target_width, C)
    """
    # 获取原始图像尺寸和目标尺寸
    h, w = image.shape[:2]
    target_h, target_w = target_size       
    # 计算缩放比例
    ratio = min(target_w / w, target_h / h)
    new_w = int(w * ratio)
    new_h = int(h * ratio)
    # 缩放图像
    resized = cv2.resize(image, (new_w, new_h), 
                         interpolation=interpolation)
    
    # 计算填充量（上下左右对称填充）
    delta_w = target_w - new_w
    delta_h = target_h - new_h
    top = delta_h // 2
    bottom = delta_h - top
    left = delta_w // 2
    right = delta_w - left
    
    # 添加填充
    padded = cv2.copyMakeBorder(
        resized, 
    top, bottom, left, right, 
    cv2.BORDER_CONSTANT, 
    value=pad_color
    )
    return padded

def compute_fid_multi_frames(novel_images_list, 
                gt_images_list,
                image_size=(3, 640, 960),
                is_cv2_image=False,
                reset_real_features=False,
                normalize=True,
                batch_size=32):
    assert len(novel_images_list) == len(gt_images_list)
    if is_cv2_image:
        gt_images_list = [ cv2_to_pil(image) for image in gt_images_list]
        novel_images_list = [ cv2_to_pil(image) for image in novel_images_list]

    transform = transforms.Compose([
        transforms.Resize(image_size[1:]),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5])
    ])
    gt_images_list = [transform(image) for image in gt_images_list]
    novel_images_list = [transform(image) for image in novel_images_list]
    
    inception_model = FrechetInceptionDistance(input_img_size=image_size, 
                                               reset_real_features=reset_real_features,
                                               normalize=normalize).cuda()
    if len(gt_images_list) == 1:
        gt_images_list.append(gt_images_list[0].clone())
        gt_image_tensors = torch.stack(gt_images_list, dim=0)
        novel_images_list.append(novel_images_list[0].clone())
        novel_image_tensors = torch.stack(novel_images_list, dim=0)
    else:
        gt_image_tensors = torch.stack(gt_images_list, dim=0)
        novel_image_tensors = torch.stack(novel_images_list, dim=0)
        
    fid_list = []
    for idx in range(0, len(gt_images_list), batch_size): 
        end = min(len(gt_images_list), idx + batch_size)
        batch_gt_image_tensors = gt_image_tensors[idx:end]
        batch_novel_image_tensors = novel_image_tensors[idx:end]
        if batch_gt_image_tensors.device.type != "cuda":
            batch_gt_image_tensors = batch_gt_image_tensors.cuda()
            batch_novel_image_tensors = batch_novel_image_tensors.cuda()
        inception_model.update(batch_gt_image_tensors, real=True)
        inception_model.update(batch_novel_image_tensors, real=False)
        fid_value = inception_model.compute()
        fid_list.append(fid_value.item())
        del batch_gt_image_tensors, batch_novel_image_tensors
    inception_model.reset()
    return np.mean(fid_list)

def cv2_to_pil(image):
    image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    pil_image = Image.fromarray(image_rgb)
    return pil_image

def compute_fid(novel_image_tensor, 
                gt_image_tensor, 
                image_size=(3, 640, 960),
                reset_real_features=False,
                normalize=True):
    
    if novel_image_tensor.shape[0] == 1:
        gt_image_tensor = torch.concat([gt_image_tensor, gt_image_tensor], dim=0)
        novel_image_tensor = torch.concat([novel_image_tensor, novel_image_tensor], dim=0)
    
    Normalize = transforms.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5])
    gt_image_tensor, novel_image_tensor = Normalize(gt_image_tensor), Normalize(novel_image_tensor)
    
    inception_model = FrechetInceptionDistance(input_img_size=image_size, 
                                               reset_real_features=reset_real_features, 
                                               normalize=normalize).cuda()
    if gt_image_tensor.device.type != "cuda":
        gt_image_tensor = gt_image_tensor.cuda()
        novel_image_tensor = novel_image_tensor.cuda()
        
    inception_model.update(gt_image_tensor, real=True)
    inception_model.update(novel_image_tensor, real=False)
    fid_value = inception_model.compute()
    
    inception_model.reset()
    return fid_value

def mse(imageA, imageB):
    err = torch.sum((imageA.float() - imageB.float()) ** 2, dim=(1,2,3))
    err /= float(imageA.shape[1] * imageA.shape[2] * imageA.shape[3])
    return err

def eval_by_psnr(gt_image, novel_image):
    #计算峰值信噪比 (PSNR)
    mse_value = mse(gt_image, novel_image)
    if mse_value == 0:
        return float('inf')
    max_pixel = 255.0
    psnr_value = 20 * torch.log10(max_pixel / torch.sqrt(mse_value))
    return psnr_value.mean().item()

def draw_detection_result_on_image(image, gt_bboxes, predict_bboxes):
    def draw_bbox_class(image, bboxes, color, is_gt = "False"):
        for bbox in bboxes:
            x1,y1,x2,y2 = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
            class_id= bbox[4]
            # 绘制检测框
            cv2.rectangle(image, (x1, y1), (x2, y2), color, thickness=1)
            # 显示类别名称和置信度
            label = f"{class_id}"
            label_size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.3, 1)
            label_x = x1
            label_y = y1 - 10 if y1 - 10 > 10 else y1 + 10  # 防止标签超出图像边界
            cv2.rectangle(image, (label_x, label_y - label_size[1]), 
                          (label_x + label_size[0], label_y + label_size[1]), 
                          color, -1)
            cv2.putText(image, label, (label_x, label_y), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.3, (255, 255, 255), 1)
        return image
    gt_color = (0, 0, 255) # red
    pred_color = (255, 0, 0)  # blue 
    image = draw_bbox_class(image, gt_bboxes, 
                            gt_color, is_gt = "True")
    image = draw_bbox_class(image, predict_bboxes, 
                            pred_color, is_gt = "False")
    return image

def draw_2d_box_on_image(xyxy, image):
    color = (0, 0, 255) 
    for bbox in xyxy:
        x_min, y_min = int(bbox[0]), int(bbox[1])
        x_max, y_max = int(bbox[2]), int(bbox[3])
        cv2.rectangle(image, (x_min, y_min), (x_max, y_max), 
                      color, thickness=2)
    return image

def bbox_to_corner3d(box_size):
    min_x, min_y, min_z = -box_size[...,0], -box_size[...,1], -box_size[...,2]
    max_x, max_y, max_z = box_size[...,0], box_size[...,1], box_size[...,2]
    #(num_frames, 8, 3)
    corner3d = torch.stack((
            torch.stack((min_x, min_y, min_z), dim=1),
            torch.stack((min_x, min_y, max_z), dim=1),
            torch.stack((min_x, max_y, min_z), dim=1),
            torch.stack((min_x, max_y, max_z), dim=1),
            torch.stack((max_x, min_y, min_z), dim=1),
            torch.stack((max_x, min_y, max_z), dim=1),
            torch.stack((max_x, max_y, min_z), dim=1),
            torch.stack((max_x, max_y, max_z), dim=1)
    ), dim=1)
    return corner3d
