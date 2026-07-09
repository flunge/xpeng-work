import os
import torch
import pickle
import shutil
import tyro
import math
import numpy as np
import random
random.seed(123)
from PIL import Image
from accelerate import Accelerator
from pipeline import GaussianRenderFixerPipeline
from torchvision import transforms
from torchmetrics.image.fid import FrechetInceptionDistance
from utils import resize_with_padding, get_masks
from typing import Optional, List

def get_image_data(
    input_path: str,
    video_name: str,
    cam_masks: dict,
    size=(1920, 1280),
    cam_types = ['cam0', 'cam2', 'cam3', 'cam4']
):
    render_image_list, gt_image_list, gt_path_list, prompt_list = [],[],[],[]
    for cam_type in cam_types:
        shift_dir = [dir_ for dir_ in os.listdir(
                        os.path.join(input_path, "exp_" + video_name, "train")) 
                            if "shift" in dir_][0]
        image_list = [ image_name 
                        for image_name in os.listdir(os.path.join(input_path, 
                                                                  "exp_" + video_name,
                                                                  "train", 
                                                                  shift_dir)) 
                            if image_name.endswith(cam_type + '_rgb.png')]
        length = len(image_list)
        start, end = (length // 5), (length - length // 5)
        mid_idx = random.randint(start, end - 1)
        ts, _, _ = image_list[mid_idx].split('_')
        prompt = "the Xiaopeng Vehicle of CAM{} camera view.".format(
                            cam_type.split("cam")[0])
        prompt_list.append(prompt)
        render_path = os.path.join(input_path, "exp_" + video_name, "train",
                                   shift_dir, image_list[mid_idx])
        gt_path = render_path.replace("rgb.png", "gt.png")
        render_image, gt_image = Image.open(render_path), Image.open(gt_path)
        render_image_list.append(resize_with_padding(render_image, size))
        mask = cam_masks[os.path.basename(gt_path).split("_")[1]]
        # gt_image is masked, and render_image is not masked
        gt_image = resize_with_padding(gt_image, size)
        gt_image = Image.fromarray(np.uint8(gt_image * mask))
        gt_image_list.append(gt_image)
        gt_path_list.append(gt_path)
    return render_image_list, gt_image_list, gt_path_list, prompt_list

def save_render_gt_image(out_path, gt_path_list, gt_list, render_list, cam_mask):
    for gt_image, render_image, gt_path in zip(gt_list, render_list, gt_path_list):
        video_name = gt_path.split("/train")[0].split('/')[-1]
        gt_name = gt_path.split('/')[-1]
        render_name = gt_name.replace("gt.png", "rgb.png")
        # masked render_image in saved
        mask = cam_mask[render_name.split("_")[1]]
        render_image = Image.fromarray(np.uint8(np.array(render_image) * mask))
        video_path = os.path.join(out_path, video_name)
        if os.path.exists(video_path) == False:
            os.makedirs(video_path)
        dir_path = os.path.join(video_path, "render_and_gt")
        if os.path.exists(dir_path) == False:
            os.makedirs(dir_path)
        gt_image.save(os.path.join(dir_path, gt_name))
        render_image.save(os.path.join(dir_path, render_name))

def inference(
    pipe, 
    prompt_list,
    render_image_list,
    batch_size = 4,
    num_inference_steps = 50,
    image_guidance_scale = 2.6,
    guidance_scale = 1.4
):
    assert len(prompt_list) == len(render_image_list)
    length = len(render_image_list)
    gen_image = []

    for idx in range(0, math.ceil(length // batch_size)):
        begin, end = idx*batch_size, min((idx+1)*batch_size, length)
        images, prompts = render_image_list[begin:end], prompt_list[begin:end]
        result_image = pipe(
            prompts,
            image=images,
            num_inference_steps=num_inference_steps,
            image_guidance_scale=image_guidance_scale,
            guidance_scale=guidance_scale,
        ).images
        gen_image.extend(result_image)
    return gen_image

def save_result(path, gt_path_list, result_images,
                img_guidance_scale, guidance_scale,
                cam_masks):
    ret_images = []
    for gt_path, result_image in zip(gt_path_list, result_images):
        video_name = gt_path.split("/train")[0].split('/')[-1]
        outpath = os.path.join(path, video_name, 
                               "imgGdscale{}_gdscale{}".format(
                                    img_guidance_scale, guidance_scale))
        if os.path.exists(outpath) == False:
            os.makedirs(outpath)
        image_name = (gt_path.split('/')[-1]).replace("gt.png", "gen.png")
        # mask result_image
        mask = cam_masks[image_name.split("_")[1]]
        result_image = Image.fromarray(np.uint8(np.array(result_image) * mask))
        result_image.save(os.path.join(outpath, image_name))
        ret_images.append(result_image)
    return ret_images

def eval_by_fid(inference_list, 
                gt_list,
                input_img_size=(3, 1920, 1280), 
                reset_real_features=False, 
                normalize=True):
    assert len(inference_list) == len(gt_list)
    if torch.cuda.is_available():
        device = torch.device('cuda')
    else:
        device = torch.device('cpu')
    transform = transforms.Compose([
        transforms.Resize(input_img_size[1:]),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.5, 0.5, 0.5], 
                             std=[0.5, 0.5, 0.5])  # Normalize to [-1, 1]
    ])
    fid = FrechetInceptionDistance(input_img_size=input_img_size, 
                                   reset_real_features=reset_real_features, 
                                   normalize=normalize).to(device)
    gt_list = [transform(image) for image in gt_list]
    inference_list = [transform(image) for image in inference_list]
    if len(gt_list) == 1:
        gt_list.append(gt_list[0].clone())
        gt_tensors = torch.stack(gt_list, dim=0).to(device)
        inference_list.append(inference_list[0].clone())
        inference_tensors = torch.stack(inference_list, dim=0).to(device)
    else:
        gt_tensors = torch.stack(gt_list, dim=0).to(device)
        inference_tensors = torch.stack(inference_list, dim=0).to(device)
        
    fid.update(gt_tensors, real=True)
    fid.update(inference_tensors, real=False)
    fid_value = fid.compute()
    fid.reset()
    return fid_value.cpu().item()

def print_fid(video_name, fid_values, gdscale_list, img_gdscale_list):
    print('\n\n names: {}'.format(video_name))
    print("| guidance_scale | " + " | ".join([f"{gs:<5}" for gs in gdscale_list]) + " |")
    print("|--------------| " + " | ".join(["-----" for _ in gdscale_list]) + " |")
    
    for iscale, row in zip(img_gdscale_list, fid_values):
        print(f"| image_guidance_scale {iscale:<8} | " + 
                " | ".join([f"{round(float(fid),3):<5}" for fid in row]) + " |")

def main(
    base_model_id: str,
    lora_weights_path: str,
    image_path: str,
    save_path: str,
    mask_path: str,
    video_name: str,
    image_size: tuple=(1920, 1280),
    camera_ids: list=["cam0", "cam2", "cam3", "cam4"],
    num_inference_step: int = 50,
    img_guidance_scale_min: float = 1.8,
    img_guidance_scale_max: float = 3.6,
    guidance_scale_min: float = 1.0,
    guidance_scale_max: float = 2.0,
    batch_size: int = 2
):
    cam_mask = get_masks(os.path.join(mask_path, video_name), 
                         size=image_size, 
                         camera_ids=camera_ids)
    accelerator = Accelerator(mixed_precision="fp16")
    
    pipe = GaussianRenderFixerPipeline.from_pretrained(
        base_model_id,
        torch_dtype=torch.float16,
        safety_checker=None
    )
    pipe = pipe.to("cuda")
    pipe.unet = accelerator.prepare(pipe.unet)
    accelerator.load_state(os.path.join(lora_weights_path, video_name, "unet_weights"))
    
    render_list, gt_list, gt_path_list, prompt_list = get_image_data(image_path, 
                                                                     video_name, 
                                                                     cam_mask,
                                                                     size=image_size)
    save_render_gt_image(os.path.join(save_path, video_name), 
                         gt_path_list, gt_list, render_list,
                         cam_mask)
    img_gdscale_list = np.arange(img_guidance_scale_min, 
                                 img_guidance_scale_max, 
                                 0.2)
    gdscale_list = np.arange(guidance_scale_min, 
                             guidance_scale_max, 
                             0.1)
    gdscale_list = [round(gd, 1) for gd in gdscale_list]
    img_gdscale_list = [round(gd, 1) for gd in img_gdscale_list]
    fid_values = []
    for img_guidance_scale in img_gdscale_list:
        tmp = []
        for guidance_scale in gdscale_list:
            print('img_gdscale, gdscale_scale', img_guidance_scale, guidance_scale)
            result_images = inference(pipe, prompt_list, render_list, 
                                      batch_size, num_inference_step,
                                      img_guidance_scale, guidance_scale)
            result_images = save_result(os.path.join(save_path, video_name), gt_path_list, 
                                        result_images, img_guidance_scale, guidance_scale,
                                        cam_mask)
            h, w = image_size
            fid_value = eval_by_fid(result_images, gt_list, input_img_size=(3, h, w))
            print('fid', fid_value)
            tmp.append(fid_value)
        fid_values.append(tmp)
    pickle.dump(fid_values, open(os.path.join(save_path, 
                    video_name+str(img_guidance_scale_min)+'.pkl'), 'wb'))
    print_fid(video_name, fid_values, gdscale_list, img_gdscale_list)

if __name__ == "__main__":
    tyro.cli(main)
