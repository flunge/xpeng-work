import abc
import os

import cv2
import numpy as np
import torch
from ultralytics import YOLO
import json

from ..datasets.base.scene_dataset import ObjectType
from .metric_utils import draw_detection_result_on_image, image_resize_and_padding, resize_bbox_and_padding

class_to_object_type = {
    "car": ObjectType.Vehicle,
    "bus": ObjectType.Vehicle,
    "truck": ObjectType.Vehicle,
    "pedestrian": ObjectType.Pedestrian,
    "cyclist": ObjectType.Cyclist,
    "motorcycle": ObjectType.Cyclist,
}

class Evaluate2dDection(abc.ABC):
    def __init__(
        self,
        model_path: str,
        batch_size: int = 2,
        confidence_threshold: float = 0.0,
        iou_threshold: float = 0.3,
        model_input_size: tuple = (640, 640),
        show_image_path = "",
    ):
        self.model_path = model_path
        self.model = YOLO(model_path).cuda()
        self.batch_size = batch_size
        self.confidence_threshold = confidence_threshold
        self.iou_threshold = iou_threshold
        self.model_input_size = model_input_size
        self.show_image_path = show_image_path

    def map_classid_to_object_type(self, classid, id_classname):
        classname = id_classname[classid]
        object_type = class_to_object_type[classname]
        return object_type

    def calculate_iou(self, box1, box2):
        """
        计算两个边界框的交并比（IoU）
        :param box1: 第一个边界框，格式为 [x1, y1, x2, y2]
        :param box2: 第二个边界框，格式为 [x1, y1, x2, y2]
        :return: IoU值
        """
        x1 = max(box1[0], box2[0])
        y1 = max(box1[1], box2[1])
        x2 = min(box1[2], box2[2])
        y2 = min(box1[3], box2[3])
        intersection_area = max(0, x2 - x1) * max(0, y2 - y1)
        box1_area = (box1[2] - box1[0]) * (box1[3] - box1[1])
        box2_area = (box2[2] - box2[0]) * (box2[3] - box2[1])
        union_area = box1_area + box2_area - intersection_area
        if union_area == 0:
            return 0
        return intersection_area / union_area

    def inference_multi_images(self, novel_images_list, gt_bboxes_list, id_classname, image_names_list, cam_name_list):
        all_infer_objects_list, all_gt_objects_list = [], []
        image_name_pred_bboxes = {}
        for idx in range(0, len(novel_images_list), self.batch_size):
            end = min(idx + self.batch_size, len(novel_images_list))
            batch_novel_images = [image_resize_and_padding(novel_images_list[b_idx], 
                                                           self.model_input_size) 
                                    for b_idx in range(idx, end)]
            batch_novel_images_list = batch_novel_images.copy() 
            batch_novel_images = torch.from_numpy(np.stack(batch_novel_images, axis=0)) / 255.0
            batch_novel_images = torch.permute(batch_novel_images, (0,3,1,2)).cuda()
            batch_gt_bboxes = gt_bboxes_list[idx:end]
            batch_image_names = image_names_list[idx:end]
            batch_cam_names = cam_name_list[idx:end]
            results = self.model(batch_novel_images)
            for jdx, (result, gt_bboxes, image_name, cam_name) in enumerate(zip(results, batch_gt_bboxes, batch_image_names, batch_cam_names)):
                origin_size = novel_images_list[idx+jdx].shape[:2]
                resize_gt_bboxes = resize_bbox_and_padding(origin_size, 
                                                           self.model_input_size, 
                                                           gt_bboxes)
                all_gt_objects_list.extend(resize_gt_bboxes)
                predict_bboxes = self.process_detection_result(result, resize_gt_bboxes, id_classname)
                all_infer_objects_list.extend(predict_bboxes)
                # show the gt and predicted bboxes on images
                if self.show_image_path != "":            
                    draw_image = draw_detection_result_on_image(batch_novel_images_list[jdx], 
                                                                resize_gt_bboxes, 
                                                                predict_bboxes)
                    cv2.imwrite(os.path.join(self.show_image_path, image_name + f"-{cam_name}" + "-pred_gt_bbox.png"), 
                                draw_image)
                    image_name_pred_bboxes[image_name + f"-{cam_name}" + "-pred_gt_bbox.png"] = predict_bboxes
            del batch_novel_images, batch_novel_images_list
            torch.cuda.empty_cache()
        return all_infer_objects_list, all_gt_objects_list, image_name_pred_bboxes
    
    def process_detection_result(self, result, resize_gt_bboxes, id_classname):
        predict_bboxes = []
        gt_matched = [False] * len(resize_gt_bboxes)
        for box in result.boxes:
            confidence = box.conf[0].cpu().item()
            if confidence < self.confidence_threshold:
                continue
            class_id = int(box.cls[0].cpu().numpy())
            if class_id in id_classname.keys():
                xyxy = box.xyxy[0].cpu().numpy()
                x1, y1, x2, y2 = map(int, xyxy)  # Convert to integers
                class_id = self.map_classid_to_object_type(class_id, id_classname)
                # match gt bboxes
                max_iou, max_gt_index = 0, -1
                class_ground_truths = [gt for gt in resize_gt_bboxes if int(gt[4]) == class_id]
                for j, gt_bbox in enumerate(class_ground_truths):
                    iou = self.calculate_iou([x1, y1, x2, y2], gt_bbox[:4])
                    if iou > max_iou:
                        max_iou = iou
                        max_gt_index = j
                if max_iou >= self.iou_threshold and not gt_matched[max_gt_index]:
                    predict_bboxes.append([x1,y1,x2,y2,int(class_id),confidence,True])
                    gt_matched[max_gt_index] = True
                else:
                    predict_bboxes.append([x1,y1,x2,y2,int(class_id),confidence,False])
        return predict_bboxes
    
    def get_precision_recall(self, class_preds, class_gts, num_gts):
        class_preds_sorted = sorted(class_preds, key=lambda x: -x[5])
        # 每一个预测结果均计算一次 precision 和 recall。
        tp, fp = 0, 0
        pr_points = []
        for pred in class_preds_sorted:
            if pred[-1]:  # have matched a gt_bbox
                tp += 1
            else:
                fp += 1
            recall = tp / num_gts if num_gts != 0 else 0.0
            precision = tp / (tp + fp) if (tp + fp) != 0 else 0.0
            pr_points.append((recall, precision))
        return pr_points, tp, fp

    def calculate_ap(self, pr_points):
        if not pr_points:
            return 0.0
        pr_points.sort()
        unique_pr = []
        # 记录当前的最大precision
        current_max_p = -1
        # 记录上一个 recall
        prev_r = None
        # 针对每一个（recall, precision）均要找到当前recall值下对应的最大precision
        # 因为 p-r 曲线中，曲线上的每一个点为当前 recall（横坐标）对应的最大 precision（纵坐标）
        for r, p in pr_points:
            if prev_r is None:
                prev_r = r
                current_max_p = p
            else:
                if r == prev_r:
                    if p > current_max_p:
                        current_max_p = p
                else:
                    unique_pr.append((prev_r, current_max_p))
                    prev_r = r
                    current_max_p = p
        unique_pr.append((prev_r, current_max_p))
        ap = 0.0
        # 使用积分方法计算p-r曲线下的面积
        for i in range(len(unique_pr) - 1):
            r1, p1 = unique_pr[i]
            r2, p2 = unique_pr[i + 1]
            dr = r2 - r1
            avg_p = (p1 + p2) / 2
            ap += dr * avg_p
        return ap

    def calculate_map(self, gts, preds):
        """
        计算平均精度均值（mAP）
        :param predictions: 预测结果列表，每个元素为 [x1, y1, x2, y2, class_id, confidence, matched]
        :param ground_truths: 真实标签列表，每个元素为 [x1, y1, x2, y2, class_id]
        :return: mAP值
        """
        unique_classes = set()
        for gt in gts:
            unique_classes.add(gt[4])
        for pred in preds:
            unique_classes.add(pred[4])
        if len(unique_classes) == 0:
            return 0.0
        unique_classes = sorted(unique_classes)
        total_ap = 0.0
        classid_metric = {}
        for cls in unique_classes:
            # 提取属于本类别的所有 gt 和 pred 信息
            class_gts = [gt for gt in gts if gt[4] == cls]
            class_preds = [pred for pred in preds if pred[4] == cls]
            num_gts = len(class_gts)
            if num_gts == 0:
                classid_metric[cls] = {
                    "ap": 0.0,
                    "precision": 0.0,
                    "recall": 0.0,
                    "num_gt": 0.0,
                    "num_tp": 0.0,
                    "num_fp": 0.0,
                }
                continue
            pr_points, tp, fp = self.get_precision_recall(class_preds, class_gts, num_gts)
            ap = self.calculate_ap(pr_points)
            total_ap += ap
            if (tp + fp) > 0:
                precision_total = round(tp / (tp + fp), 3)
            if num_gts > 0:
                recall_total = round(tp / num_gts, 3)
            classid_metric[cls] = {
                "ap": ap,
                "precision": precision_total,
                "recall": recall_total,
                "num_gt": num_gts,
                "num_tp": tp,
                "num_fp": fp,
            }
        return total_ap / len(unique_classes), classid_metric

    def evaluate_images(self, show_result_path, 
                        image_names_list, novel_images_list, cam_name_list, 
                        gt_infos_list, id_classname):
        infer_objects_list, gt_objects_list, image_name_pred_bboxes = self.inference_multi_images(novel_images_list, 
            gt_infos_list, 
            id_classname,
            image_names_list,
            cam_name_list)
        if self.show_image_path != "":
            with open(os.path.join(self.show_image_path, "image_names_prediction_results.json"), "w") as file_o:
                json.dump(image_name_pred_bboxes, file_o)
            file_o.close()
        mAP, classid_metric = self.calculate_map(gt_objects_list, infer_objects_list)
        return mAP, classid_metric
