import cv2
import argparse
import yaml
from tqdm import tqdm
import sys
import os
import numpy as np
import torch
import torch.multiprocessing as mp
from torch.utils.data import DataLoader
from torch.distributed import destroy_process_group, init_process_group
from torch.nn.parallel import DistributedDataParallel as DDP
from torch.utils.data.distributed import DistributedSampler
from pytorch3d.renderer import PerspectiveCameras
from collections import defaultdict
import math
import skimage
from tabulate import tabulate
import logging

def visualize_all_cams(image, scale=2):
    original_image_shapes = [450, 800, 3]

    """ Concatenate camera images """
    cam2_shape = np.array(np.array(original_image_shapes[:2]), dtype=np.int32)
    cam2_shape = np.append(cam2_shape, 3)
    front_dummy_im = np.zeros(cam2_shape)

    cam3_shape = np.array(np.array(original_image_shapes[:2]), dtype=np.int32)
    cam3_shape = np.append(cam3_shape, 3)
    side_dummy_im = np.zeros(cam3_shape)

    if "cam2" not in image.keys():
        im1 = np.zeros_like(front_dummy_im)
    else:
        im1 = image["cam2"]

    im0 = image.get("cam0", front_dummy_im)
    im3 = image.get("cam3", side_dummy_im)
    im4 = image.get("cam4", side_dummy_im)
    im5 = image.get("cam5", side_dummy_im)
    im6 = image.get("cam6", side_dummy_im)
    im7 = image.get("cam7", front_dummy_im)

    im0 = cv2.resize(im0, (None, None), fx=scale, fy=scale)
    im1 = cv2.resize(im1, (None, None), fx=scale, fy=scale)
    im3 = cv2.resize(im3, (None, None), fx=scale, fy=scale)
    im4 = cv2.resize(im4, (None, None), fx=scale, fy=scale)
    im5 = cv2.resize(im5, (None, None), fx=scale, fy=scale)
    im6 = cv2.resize(im6, (None, None), fx=scale, fy=scale)
    im7 = cv2.resize(im7, (None, None), fx=scale, fy=scale)

    cam_w = max(im3.shape[1], im0.shape[1], im1.shape[1])
    cam_h = max(im0.shape[0], im1.shape[0], im3.shape[0], im4.shape[0], im5.shape[0], im6.shape[0], im7.shape[0])
    all_cam_im = np.zeros((cam_h*5, cam_w*2, 3), dtype=np.uint8)

    all_cam_im[0*cam_h:0*cam_h+im0.shape[0], cam_w//2:cam_w//2+im0.shape[1]] = im0
    all_cam_im[1*cam_h:1*cam_h+im1.shape[0], cam_w//2:cam_w//2+im1.shape[1]] = im1
    all_cam_im[2*cam_h:2*cam_h+im3.shape[0], 0:im3.shape[1]] = im3
    all_cam_im[2*cam_h:2*cam_h+im4.shape[0], cam_w:cam_w + im3.shape[1]] = im4
    all_cam_im[3*cam_h:3*cam_h+im5.shape[0], 0:im5.shape[1]] = im5
    all_cam_im[3*cam_h:3*cam_h+im6.shape[0], cam_w:cam_w + im6.shape[1]] = im6
    all_cam_im[4*cam_h:4*cam_h+im7.shape[0], cam_w//2:cam_w//2+im7.shape[1]] = im7
    return all_cam_im


def write_video(blend_image_list, video_path):
    blend_image_list_with_trip = dict()
    for image_name, cam_image_list in blend_image_list.items():
        vehicle_name, ts, camera_name = image_name.split("/")
        trip_info = "_".join([vehicle_name, ts])
        if trip_info not in blend_image_list_with_trip:
            blend_image_list_with_trip[trip_info] = dict()
        cam_image_list = sorted(cam_image_list, key=lambda x: int(x[0]))
        blend_image_list_with_trip[trip_info][camera_name] = cam_image_list

    # hacky way to get len slices
    global_image_list = []
    for trip in blend_image_list_with_trip.keys():
        slice_length = max([len(x) for x in blend_image_list_with_trip[trip].values()])
        ref_slice = min([int(x[0][0]) for x in blend_image_list_with_trip[trip].values()])
        for idx in range(slice_length):
            cur_slice = {}
            slice_number = ref_slice + idx
            for cam in blend_image_list_with_trip[trip].keys():
                camera_image = [x[1] for x in blend_image_list_with_trip[trip][cam] if int(x[0]) == slice_number]
                if len(camera_image) == 0:
                    image = np.zeros_like(blend_image_list_with_trip[trip][cam][0][1].shape, dtype=np.uint8)
                else:
                    cur_slice[str(cam)] = camera_image[0]
            formulate_image = visualize_all_cams(cur_slice)
            global_image_list.append(formulate_image)

    video = cv2.VideoWriter(video_path, cv2.VideoWriter_fourcc(*'mp4v'), 6, (global_image_list[0].shape[1], global_image_list[0].shape[0]))
    for image in global_image_list:
        video.write(image)
    video.release()


def calculate_frame_kpi(pred_img, gt_img, pred_seg, gt_seg, mask, labels=[1, 2, 3, 4]):
    """
    Calculate the KPI of one frame
    """
    pred_img = pred_img.copy()
    gt_img = gt_img.copy()
    pred_seg = pred_seg.copy()
    gt_seg = gt_seg.copy()

    pred_img[mask == 0] = 0
    gt_img[mask == 0] = 0
    pred_seg[mask == 0] = 0
    gt_seg[mask == 0] = 0

    psnr = skimage.metrics.peak_signal_noise_ratio(pred_img, gt_img)
    ssim = skimage.metrics.structural_similarity(pred_img, gt_img, channel_axis=2)

    intersections, unions = [], []
    for label in labels:
        intersections.append(np.sum(np.logical_and(pred_seg==label, gt_seg==label)))
        unions.append(np.sum(np.logical_or(pred_seg==label, gt_seg==label)))

    frame_kpi = {"PSNR": psnr,
                "SSIM": ssim,
                "class_intersection": intersections,
                "class_union": unions}

    return frame_kpi


def aggregate_kpi(all_frame_kpi):
    """
    Calculate the final KPI from frame KPIs
    """
    flatten_kpi_dict = {}
    for frame_name, frame_kpi in all_frame_kpi.items():
        for kpi_name, kpi_value in frame_kpi.items():
            if kpi_name in flatten_kpi_dict:
                flatten_kpi_dict[kpi_name].append(kpi_value)
            else:
                flatten_kpi_dict[kpi_name] = [kpi_value]

    num_frames = len(all_frame_kpi)
    psnr = np.array(flatten_kpi_dict["PSNR"]).mean()
    ssim = np.array(flatten_kpi_dict["SSIM"]).mean()
    class_intersection = np.array(flatten_kpi_dict["class_intersection"]).sum(axis=0)
    class_intersection = np.append(class_intersection, class_intersection.sum())
    class_union = np.array(flatten_kpi_dict["class_union"]).sum(axis=0)
    class_union = np.append(class_union, class_union.sum())
    class_iou = class_intersection / class_union

    eval_kpi = {"num_frames": num_frames,
                "PSNR": psnr,
                "SSIM": ssim,
                "class_intersection": class_intersection,
                "class_union": class_union,
                "class_iou": class_iou}

    return eval_kpi


def generate_kpi_tables(eval_kpi):
    """
    Organize KPI to tables.
    """
    quality_table = [["Number of frames", "PSNR", "SSIM"]]
    quality_table.append([eval_kpi["num_frames"], f"{eval_kpi['PSNR']:.3f}", f"{eval_kpi['SSIM']:.3f}"])

    iou_table = [["Class Name", "Intersection", "Union", "IoU"]]
    iou_table.append(["Painted Line", eval_kpi["class_intersection"][0], eval_kpi["class_union"][0], f"{eval_kpi['class_iou'][0]:.3f}"])
    iou_table.append(["Curb", eval_kpi["class_intersection"][1], eval_kpi["class_union"][1], f"{eval_kpi['class_iou'][1]:.3f}"])
    iou_table.append(["Road surface", eval_kpi["class_intersection"][2], eval_kpi["class_union"][2], f"{eval_kpi['class_iou'][2]:.3f}"])
    iou_table.append(["Sidewalk", eval_kpi["class_intersection"][3], eval_kpi["class_union"][3], f"{eval_kpi['class_iou'][3]:.3f}"])
    iou_table.append(["Overall", eval_kpi["class_intersection"][4], eval_kpi["class_union"][4], f"{eval_kpi['class_iou'][4]:.3f}"])

    table_str = tabulate(quality_table) + "\n\n" + tabulate(iou_table)

    return table_str