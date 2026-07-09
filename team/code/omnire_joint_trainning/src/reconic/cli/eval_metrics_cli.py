import argparse
import json
import os
import glob
import cv2

import torch
import numpy as np
from omegaconf import OmegaConf
from skimage.metrics import structural_similarity as ssim
from torchmetrics.image.lpip import LearnedPerceptualImagePatchSimilarity

from reconic.datasets.driving_dataset import DrivingDataset
from reconic.metrics.eval_detection import Evaluate2dDection
from reconic.metrics.get_gt_infos import GroundTruthInfo
from reconic.metrics.metric_utils import compute_fid_multi_frames
from reconic.models.video_utils import compute_psnr


def eval_metrics(args):
    cfg = OmegaConf.load(os.path.join(args.result_path, "config.yaml"))
    shift = args.shift
    # build dataset
    dataset = DrivingDataset(cfg.project_dir, data_cfg=cfg.data)
    # Get images
    novel_images_list, image_indices_list, image_names_list, cam_name_list = [], [], [], []
    if "novel_view_data" in args.image_dirs.split("/"):
        image_names = glob.glob(os.path.join(args.result_path,
                                             "novel_view_data",
                                             "image_*_shift_{}.png".format(shift)))
        for image_name in image_names:
            novel_images_list.append(cv2.imread(image_name))
            image_name_prefix = image_name.split("/")[-1].split(".png")[0]
            image_names_list.append(image_name_prefix)
            image_index = image_name_prefix.split("_")[1]
            image_indices_list.append(int(image_index))
    elif ("videos" in args.image_dirs.split("/")) or ("videos_eval" in args.image_dirs.split("/")):
        image_names = glob.glob(os.path.join(args.result_path, args.image_dirs, "*.png")) 
        for image_name in image_names:
            novel_images_list.append(cv2.imread(image_name))
            image_name_prefix = image_name.split("/")[-1].split(".png")[0]
            image_names_list.append(image_name_prefix)
            frame_index, camera_index = image_name_prefix.split("_")
            image_index = int(frame_index) * len(cfg.data.pixel_source.cameras) + int(camera_index)
            image_indices_list.append(int(image_index))
    elif "simulator_render" in args.image_dirs.split("/"):
        localpose = json.load(open(os.path.join(args.result_path, "localpose.json")))
        actual_timestamps = sorted([int(k) for k in localpose.keys()])
        timestamps = [i for i in actual_timestamps]
        # frame_idx = np.abs(np.array(timestamps) - timestamp_sim).argmin()
        print(os.path.join(args.result_path, args.image_dirs))
        cam_list = sorted(os.listdir(os.path.join(args.result_path, args.image_dirs)))
        image_names = sorted(glob.glob(os.path.join(args.result_path, args.image_dirs, cam_list[0], "*.png")))
        # print(image_names[:10])
        for _, img_path in enumerate(image_names):
            img_name, img_ext = os.path.splitext(os.path.basename(img_path))
            # print(img_name)
            frame_idx = np.abs(np.array(timestamps) - int(img_name)).argmin()
            for cam_idx, cam in enumerate(cam_list):
                # image_name = os.path.basename(image_name)
                image_names_list.append(img_name)
                novel_images_list.append(cv2.imread(os.path.join(args.result_path, args.image_dirs, cam, img_name + img_ext)))
                image_index = frame_idx * len(cam_list) + cam_idx
                print(image_index)
                image_indices_list.append(image_index)
                cam_name_list.append(cam)
    else:
        print("please input the right result image path!")
        return
    assert len(image_names) > 0, "result_path must have png images!"

    # get ground truth info
    gt_infos = GroundTruthInfo(
        dataset=dataset,
        shift=shift,
        detection_scope=cfg.metrics.detection.detection_scope,
        bbox_minimal_area=cfg.metrics.detection.bbox_minimal_area
    )
    gt_bbox_infos_list, gt_images_list = gt_infos.get_gt_bboxes(
        novel_images_list, image_indices_list
    )
    show_detection_path = os.path.join(args.result_path, "show_detection_results")
    os.makedirs(show_detection_path, exist_ok=True)
    gt_infos.show_images(
        show_detection_path,
        image_names_list,
        gt_images_list,
        novel_images_list,
        gt_bbox_infos_list,
        cam_name_list
    )
    
    # eval detection model by yolo11m
    detection2d = Evaluate2dDection(
        model_path=cfg.metrics.detection.model_path,
        batch_size=cfg.metrics.batch_size,
        confidence_threshold=cfg.metrics.detection.confidence_threshold,
        iou_threshold=cfg.metrics.detection.iou_threshold,
        model_input_size=cfg.metrics.detection.model_input_size,
        show_image_path=show_detection_path,
    )
    mAP, classid_metric = detection2d.evaluate_images(
        show_detection_path, image_names_list, novel_images_list, cam_name_list, 
        gt_bbox_infos_list, cfg.metrics.detection.id_classname_in_model
    )
    
    
    # write to log
    print(f"Eval over {len(image_names)} images:")
    print(f"\t Image  mAP:  {mAP:.4f}")
    for classid, metrics in classid_metric.items():
        ap, tp, fp, gts = metrics["ap"], metrics["num_tp"], metrics["num_fp"], metrics["num_gt"]
        precision, recall = metrics["precision"], metrics["recall"]
        print(f"\n\t class: {cfg.metrics.detection.classid_name[classid]}")
        print(f"\t\t AP: {ap}")
        print(f"\t\t precision: {precision}")
        print(f"\t\t recall: {recall}")
        print(f"\t\t number of ground_truth: {gts}")
        print(f"\t\t number of tp: {tp}")
        print(f"\t\t number of fp: {fp}")
    
    # write info to json file
    output_info = {
        "start_timestep": cfg.data.start_timestep,
        "end_timestep": cfg.data.end_timestep,
        "shift": shift,
    }
    detection_info = {
        "iou_threshold": cfg.metrics.detection.iou_threshold,
        "confidence_threshold": cfg.metrics.detection.confidence_threshold,
        "mAP": mAP,
    }
    detection_info["class_metric"] = {}
    for classid, metric in classid_metric.items():
        clsid = cfg.metrics.detection.classid_name[classid]
        detection_info["class_metric"][clsid] = metric
    output_info["detection"] = detection_info
    
    os.makedirs(os.path.join(args.result_path, "metrics"), exist_ok=True)
    with open(os.path.join(args.result_path, "metrics", f"offline_evaluation_metrics_shift{shift}.json"), "w") as file_o:
        json.dump(output_info, file_o)


def main():
    parser = argparse.ArgumentParser("Evaluate frames for a single scene")
    parser.add_argument(
        "--result_path",
        default="./output",
        help="path to save checkpoints and logs",
        type=str,
    )
    parser.add_argument(
        "--image_dirs",
        default="novel_view_data",
        help="path to save png images",
        type=str,
    )
    parser.add_argument(
        "--shift",
        default=-3.0,
        help="value to shift distance",
        type=float,
    )
    args = parser.parse_args()
    eval_metrics(args)


if __name__ == "__main__":
    main()
