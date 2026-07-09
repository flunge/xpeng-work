import cv2
import os
from pathlib import Path
import argparse
import torch
import imageio
import copy
import numpy as np
import supervision as sv
from loguru import logger
from tqdm import tqdm
from ultralytics import YOLO
from sam2.build_sam import build_sam2, build_sam2_video_predictor
from sam2.sam2_image_predictor import SAM2ImagePredictor
from mask_dictionary_model import MaskDictionaryModel, ObjectInfo, TrackingResult, load_mask_from_memory

# sam2
detect_min_height_threshold = 1/16
MODELS_DIR="models"
sam2_checkpoint = os.path.join(MODELS_DIR, "sam2.1_hiera_large.pt")
sam2_model_cfg = "configs/sam2.1/sam2.1_hiera_l.yaml"
PROMPT_TYPE_FOR_VIDEO = "mask"
device = "cuda:0"
STEP=20

sam2_video_predictor = build_sam2_video_predictor(sam2_model_cfg, sam2_checkpoint, device=device)
sam2_image_predictor = SAM2ImagePredictor(sam2_video_predictor)
yolo_model = YOLO(os.path.join(MODELS_DIR, "yolo11x.pt"), verbose=False).to(device)
yolo_model = yolo_model.to(device)


def load_video_frames(video_path):
    video = cv2.VideoCapture(video_path)
    fps = int(video.get(cv2.CAP_PROP_FPS))
    frames = []
    count = 0
    while True:
        ret, frame = video.read()
        if not ret:
            break
        else:
            count += 1
        
        frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    return frames, fps


def detect_image_yolo(image):
    with torch.no_grad():
        results = yolo_model(image, verbose=False)  # predict on an image

    cls = results[0].boxes.cls.int().cpu()
    indices = torch.where(cls == 0)[0]          # person

    labels  = results[0].boxes.cls[indices]
    boxes = results[0].boxes.xyxy[indices]
    scores = results[0].boxes.conf[indices]
    indices = torch.where(scores > 0.5)[0]

    labels  = labels[indices]
    boxes  = boxes[indices]
    scores = scores[indices]

    box_heights = boxes[:, 3] - boxes[:, 1]
    height_threshold = np.array(image).shape[0]  * detect_min_height_threshold
    indices = torch.where(box_heights >= height_threshold)[0]  # 保留高度大于等于阈值的框

    labels  = labels[indices]
    boxes  = boxes[indices]
    scores = scores[indices]
    
    return labels, boxes, scores


def detect_image(image):
    mask_dict = MaskDictionaryModel(promote_type=PROMPT_TYPE_FOR_VIDEO, mask_name=f"_mask.npy")
    labels, boxes, scores = detect_image_yolo(image)

    sam2_image_predictor.set_image(image)
    input_boxes = boxes
    OBJECTS = labels
    if input_boxes.shape[0] != 0:
        # prompt SAM 2 image predictor to get the mask for the object
        masks, scores, logits = sam2_image_predictor.predict(
            point_coords=None,
            point_labels=None,
            box=input_boxes,
            multimask_output=False,
        )
        # convert the mask shape to (n, H, W)
        if masks.ndim == 2:
            masks = masks[None]
            scores = scores[None]
            logits = logits[None]
        elif masks.ndim == 4:
            masks = masks.squeeze(1)
            logits = logits.squeeze(1)

        masks = masks > 0
        # If you are using point prompts, we uniformly sample positive points based on the mask
        if mask_dict.promote_type == "mask":
            mask_dict.add_new_frame_annotation(mask_list=torch.tensor(masks).to(device), box_list=torch.tensor(input_boxes), label_list=OBJECTS)
        else:
            raise NotImplementedError("SAM 2 video predictor only support mask prompts")
    else:
        logger.warning("No object detected in the frame, skip merge the frame merge")

    return mask_dict


def track_video(inference_state, mask_dict:MaskDictionaryModel, start_frame_idx, tres):
    #  Step 4: Propagate the video predictor to get the segmentation results for each frame
    tres.objects_count = mask_dict.update_masks(tracking_annotation_dict=tres.sam2_masks, iou_threshold=0.8, objects_count=tres.objects_count)
    tres.frame_object_count[start_frame_idx] = tres.objects_count
    logger.info(f"objects_count {tres.objects_count}")

    if len(mask_dict.labels) == 0:
        logger.warning("No object detected in the frame, skip the frame {}".format(start_frame_idx))
        return

    sam2_video_predictor.reset_state(inference_state)
    for object_id, object_info in mask_dict.labels.items():
        frame_idx, out_obj_ids, out_mask_logits = sam2_video_predictor.add_new_mask(
            inference_state,
            start_frame_idx,
            object_id,
            object_info.mask,
        )

    video_segments = {}  # output the following {step} frames tracking masks
    for out_frame_idx, out_obj_ids, out_mask_logits in sam2_video_predictor.propagate_in_video(inference_state, max_frame_num_to_track=STEP, start_frame_idx=start_frame_idx):
        frame_masks = MaskDictionaryModel()
        for i, out_obj_id in enumerate(out_obj_ids):
            out_mask = out_mask_logits[i] > 0.0  # .cpu().numpy()
            object_info = ObjectInfo(instance_id=out_obj_id, mask=out_mask[0], class_name=mask_dict.get_target_class_name(out_obj_id), logit=mask_dict.get_target_logit(out_obj_id))
            ret = object_info.update_box()
            if ret :
                frame_masks.labels[out_obj_id] = object_info
                frame_masks.mask_name = f"mask_{out_frame_idx}.npy"
                frame_masks.mask_height = out_mask.shape[-2]
                frame_masks.mask_width = out_mask.shape[-1]

        tres.sam2_masks = copy.deepcopy(frame_masks)

        labels = {object_id: object_info.to_dict() for (object_id, object_info) in frame_masks.labels.items()}
        video_segments[out_frame_idx] = labels      # object_dict = {object_id: object_info}

    tres.video_segments.update(video_segments)             # 收集结果


def get_all_mask(frames, video_segments, fps, scene_dir):
    os.makedirs(scene_dir, exist_ok=True)
    os.makedirs(scene_dir+'/mask_images', exist_ok=True)
    
    out_masks = []
    for kkk in range(len(frames)):
        image = frames[kkk]
        mask_all = torch.zeros(image.shape[:2], device=device).to(torch.bool)
        if kkk in video_segments:
            object_dict = video_segments[kkk]
            for object_id, object_item in object_dict.items():
                mask = load_mask_from_memory(object_item["mask"]).to(device, dtype=torch.bool)
                mask_all = mask_all | mask
                # mask_all = mask_all | object_item.mask
        # cv2.imwrite("test.jpg", mask_all.cpu().numpy().astype(np.uint8) * 255)
        nonzero_indices = torch.nonzero(mask_all)
        if nonzero_indices.size(0) == 0:
            print("nonzero_indices {} {}".format(kkk, nonzero_indices))
            mask_all = mask_all.cpu().numpy().astype(np.uint8) * 255
        else:
            R = np.sqrt(nonzero_indices.shape[0]) * 0.045
            R = int(max(R, 19))
            mask_all = mask_all.cpu().numpy().astype(np.uint8) * 255
            mask_all = cv2.dilate(mask_all, kernel=np.ones((R, R)))

        image1=image.copy()
        image1= cv2.cvtColor(image1, cv2.COLOR_RGB2BGR)
        mask=(mask_all>0)
        image1[mask,:]=0
        cv2.imwrite(scene_dir+'/mask_images/' +str(kkk).zfill(4)+'.png', image1)

        if kkk==0:
            h, w = image1.shape[:2]
            fx=1.2*float(w)
            fy=1.2*float(w)
            cx=0.5*float(w)
            cy=0.5*float(h)
        
        out_masks.append(mask_all)
    
    imageio.mimsave(scene_dir+'/mask.mp4', out_masks, "mp4", fps=fps, macro_block_size=None)
    scene_path = Path(scene_dir)
    (scene_path / "intrinsics.txt").write_text(f"{fx} {fy} {cx} {cy}")


def main(video_path, scene_dir):
    frames, fps = load_video_frames(video_path)
    num_frames = len(frames)

    inference_state = sam2_video_predictor.init_state(video_path=video_path)
    tres = TrackingResult()
    range_list = list(range(0, num_frames, STEP))
    for start_frame_idx in tqdm(range_list):
        image = frames[start_frame_idx]
        mask_dict = detect_image(image)            # detect
        track_video(inference_state, mask_dict, start_frame_idx, tres)       # tracking
    
    get_all_mask(frames, tres.video_segments, fps, scene_dir)
    

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--video_path", type=str, required=False)
    parser.add_argument("--scene_dir", type=str)
    args = parser.parse_args()
    main(args.video_path, args.scene_dir)
