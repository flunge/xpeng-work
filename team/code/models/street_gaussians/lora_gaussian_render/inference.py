import os
import re
import torch
import pickle
import shutil
import tyro
from PIL import Image
from accelerate import Accelerator
from pipeline import GaussianRenderFixerPipeline
from torchvision import transforms
from torchmetrics.image.fid import FrechetInceptionDistance
from utils import resize_with_padding
from typing import Optional, List


def inference_single_frame(
    base_model_id: str,
    lora_weights_path: str,
    prompt: str,
    image_path: str,
    num_inference_steps: int = 50,
    image_guidance_scale: float = 2.0,
    guidance_scale: float = 0.9,
    save_path: Optional[str] = None,
):

    pipe = GaussianRenderFixerPipeline.from_pretrained(
        base_model_id,
        torch_dtype=torch.float16,
        safety_checker=None
    )
    pipe = pipe.to("cuda")
    pipe.load_lora_weights(lora_weights_path)

    image = Image.open(image_path)

    result_image = pipe(
        prompt,
        image=image,
        num_inference_steps=num_inference_steps,
        image_guidance_scale=image_guidance_scale,
        guidance_scale=guidance_scale,
    ).images[0]
    if save_path is not None:
        os.makedirs(save_path, exist_ok=True)
        result_image.save(os.path.join(save_path, os.path.basename(image_path)))


def eval_by_fid(inference_list, 
                gt_list,
                input_img_size=(3, 1080, 1920), 
                reset_real_features=False, 
                normalize=True):
    assert len(inference_list) == len(gt_list)
    transform = transforms.Compose([
        transforms.Resize(input_img_size[1:]),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5])  # Normalize to [-1, 1]
    ])
    fid = FrechetInceptionDistance(input_img_size=input_img_size, 
                                   reset_real_features=reset_real_features, 
                                   normalize=normalize)
    gt_list = [transform(image) for image in gt_list]
    inference_list = [transform(image) for image in inference_list]
    if len(gt_list) == 1:
        gt_list.append(gt_list[0].clone())
        gt_tensors = torch.stack(gt_list, dim=0)
        inference_list.append(inference_list[0].clone())
        inference_tensors = torch.stack(inference_list, dim=0)
    else:
        gt_tensors = torch.stack(gt_list, dim=0)
        inference_tensors = torch.stack(inference_list, dim=0)
        
    fid.update(gt_tensors, real=True)
    fid.update(inference_tensors, real=False)
    fid_value = fid.compute()
    fid.reset()
    return fid_value

def inference(
    base_model_id: str,
    lora_weights_path: str,
    data_root: str, 
    prompts: List[str],
    image_paths: List[str],
    shift_meters: float = 0.0,
    num_inference_steps: int = 50,
    image_guidance_scale: float = 2.0,
    guidance_scale: float = 0.9,
    save_path: Optional[str] = None,
    image_size: tuple=(1920, 1280),
):
    print("image_size1", image_size)

    assert len(prompts) == len(image_paths)
    accelerator = Accelerator(mixed_precision="fp16")

    pipe = GaussianRenderFixerPipeline.from_pretrained(
        base_model_id,
        torch_dtype=torch.float16,
        safety_checker=None
    )
    
    pipe = pipe.to("cuda")

    pipe.unet = accelerator.prepare(pipe.unet)
    accelerator.load_state(lora_weights_path)

    is_origin_traj = True
    iter_dir = os.path.dirname(image_paths[0])
    if not shift_meters == 0.0:
        is_origin_traj = False

    data_dir = os.path.dirname(iter_dir)
    exp_dir = os.path.dirname(data_dir)
    
    # gt_dir = os.path.join(data_root, os.path.basename(exp_dir).split("_")[1], "images")
    gt_dir = os.path.join(data_root, "images")
    
    result_image_list, gt_image_list = [],[]
    for prompt, image_path in zip(prompts, image_paths):
        if save_path is not None:
            os.makedirs(save_path, exist_ok=True)
            img_name = os.path.basename(image_path)
            ts, ext = os.path.splitext(img_name)
            parent_path = os.path.dirname(image_path)
            cam_type = os.path.basename(parent_path)
            shift_output_str = "_shift_" + str(shift_meters) + "-output"
            # result_image_path = os.path.join(save_path, 
            #             ts + "_" + cam_type + ("_origin-output" if is_origin_traj else shift_output_str) + ext)
            # if os.path.exists(result_image_path):
            #     continue
        try:
            image = Image.open(image_path)
            image = resize_with_padding(image, image_size)
        except:
            continue
        result_image = pipe(
            prompt,
            image=image,
            num_inference_steps=num_inference_steps,
            image_guidance_scale=image_guidance_scale,
            guidance_scale=guidance_scale,
        ).images[0]
        result_image_list.append(result_image)
        gt_src = os.path.join(gt_dir, cam_type, ts + ext)
        gt_image = Image.open(gt_src)
        gt_image = resize_with_padding(gt_image, image_size)
        gt_image_list.append(gt_image)
        if save_path is not None:
            os.makedirs(save_path, exist_ok=True)
            img_name = os.path.basename(image_path)
            ts, ext = os.path.splitext(img_name)
            parent_path = os.path.dirname(image_path)
            cam_type = os.path.basename(parent_path)

            # shutil.copy(src, dst_dir)
            
            # gt_dst = os.path.join(save_path,  ts + "_" + cam_type + "_gt" + ext)
            # if not os.path.exists(gt_dst):
            #     shutil.copy(str(gt_src), str(gt_dst))
            shift_meters_str = "_shift_" + str(shift_meters)
            image.save(os.path.join(save_path, 
                        ts + "_" + cam_type + ("_origin-input" if is_origin_traj else (shift_meters_str + "-input")) + ext))
            result_image.save(os.path.join(save_path, 
                        ts + "_" + cam_type + ("_origin-output" if is_origin_traj else (shift_meters_str + "-output")) + ext))       
    h, w = image_size
    fid = eval_by_fid(result_image_list, gt_image_list, input_img_size=(3, h, w))
    print("the fid is {}".format(fid))

def main(
    base_model_id: str,
    lora_weights_path: str,
    inference_pkl_path: str,
    data_root: str,
    shift_meters: float = 0.0, 
    num_inference_steps: int = 100,
    image_guidance_scale: float = 2.6,
    guidance_scale: float = 1.4,
    save_path: Optional[str] = None,
    image_size: tuple=(1920, 1280)
):

    with open(inference_pkl_path, "rb") as f:
        dataset_dict = pickle.load(f)
    
    inference(
        base_model_id,
        lora_weights_path,
        data_root,
        dataset_dict["edit_prompt"],
        dataset_dict["input_image"],
        shift_meters,
        num_inference_steps,
        image_guidance_scale,
        guidance_scale,
        save_path,
        image_size=image_size
    )


def main_single_frame(
    base_model_id: str,
    lora_weights_path: str,
    image_path: str,
    num_inference_steps: int = 50,
    image_guidance_scale: float = 2.0,
    guidance_scale: float = 0.9,
    save_path: Optional[str] = None,
):
    inference_single_frame(
        base_model_id,
        lora_weights_path,
        "the Xiaopeng Vehicle of CAM0 camera view.",
        image_path,
        num_inference_steps,
        image_guidance_scale,
        guidance_scale,
        save_path,
    )

if __name__ == "__main__":
    tyro.cli(main)
    # tyro.cli(main_single_frame)
