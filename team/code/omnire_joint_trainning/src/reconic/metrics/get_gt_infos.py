import abc
import os

import cv2
import numpy as np
import torch

from ..datasets.driving_dataset import DrivingDataset
from .metric_utils import bbox_to_corner3d, draw_2d_box_on_image, resize_bbox


class GroundTruthInfo(abc.ABC):
    def __init__(
        self,
        dataset: DrivingDataset = None,
        shift: float = 3.0,
        detection_scope: int = 100,
        bbox_minimal_area: int=4,
    ):
        self.dataset = dataset
        self.shift = shift
        self.detection_scope = detection_scope
        self.bbox_minimal_area = bbox_minimal_area

        self.get_instances_info()

    def get_instances_info(self):
        (
            self.instances_pose,
            _,
            _,
            self.per_frame_instance_mask,
            self.instances_types,
            self.instances_size,
        ) = self.dataset.get_instance_infos()
        self.per_frame_instances_mask = self.per_frame_instance_mask.bool()

    def update_camera_pose(self, T, shift):
        """
        基于平移变化, 更新相机外参矩阵，。
        Args:
            T (numpy.ndarray): 原始外参矩阵，形状为 (4, 4)。
            delta_t (numpy.ndarray): 平移向量，形状为 (3,)。
        Returns:
            numpy.ndarray: 更新后的外参矩阵，形状为 (4, 4)。
        """
        delta_t = torch.Tensor([0.0, -float(shift), 0.0])
        # 提取旋转矩阵 R 和平移向量 t
        R = T[:3, :3]
        t = T[:3, 3]
        # 更新平移向量
        t_new = t + R @ delta_t
        # 构造新的外参矩阵
        T_new = torch.eye(4)
        T_new[:3, :3] = R
        T_new[:3, 3] = t_new
        return T_new

    def get_2d_bounding_box(self, image_points):
        """
        计算2D检测框的边界
        :param image_points: 投影后的2D坐标 (8, 2)
        :return: 2D检测框的左上角和右下角坐标 (xmin, ymin, xmax, ymax)
        """
        xmin = np.min(image_points[..., 0], axis=-1)
        ymin = np.min(image_points[..., 1], axis=-1)
        xmax = np.max(image_points[..., 0], axis=-1)
        ymax = np.max(image_points[..., 1], axis=-1)
        return np.stack([xmin, ymin, xmax, ymax], axis=1)

    def check_2dbbox(self, bbox, size):
        h, w = size
        x_min, y_min, x_max, y_max = bbox[:, 0], bbox[:, 1], bbox[:, 2], bbox[:, 3]
        x_min, y_min = np.maximum(x_min, 0), np.maximum(y_min, 0)
        x_max, y_max = np.minimum(x_max, w), np.minimum(y_max, h)
        return (x_min < x_max) & (y_min < y_max)
    
    def check_area(self, bbox):
        """
        过滤非常小的物体，被检测的目标大小需大于某个阈值
        """
        x_min, y_min, x_max, y_max = bbox[:, 0], bbox[:, 1], bbox[:, 2], bbox[:, 3] 
        area = (x_max - x_min) * (y_max - y_min)
        return area >= self.bbox_minimal_area

    def get_frame_info(self, image_index, novel_image_size):
        """
        给定 image_index, 得到其对应的原视角的图片, 以及图片中的bbox和类别信息。
        """
        image_info, cam_info = self.dataset.pixel_source.get_image(image_index)
        frame_index = image_info.frame_index
        gt_image = (image_info.pixels * 255).numpy().astype("uint8")
        gt_image = cv2.cvtColor(gt_image, cv2.COLOR_RGB2BGR)
        # (num_instances,)
        instance_mask = self.per_frame_instances_mask[frame_index]
        # (num_instances, 4, 4)
        instance_obj2world = self.instances_pose[frame_index][instance_mask]
        # (num_instances, 3)
        instance_size = self.instances_size[frame_index][instance_mask]
        # (num_instances,)
        instance_type = self.instances_types[frame_index][instance_mask]
        # (4,4)
        cam2ego, ego2world = cam_info.camera_to_ego, cam_info.ego_to_world
        # (3,3)
        intrinsics = cam_info.intrinsic

        bbox_info = self.transfer_world_to_image(instance_obj2world, instance_size, 
                                                 instance_type, ego2world, cam2ego, 
                                                 intrinsics, novel_image_size
        )
        resized_bbox_info = resize_bbox(gt_image.shape[:2], novel_image_size, bbox_info)

        return resized_bbox_info, gt_image

    def transfer_world_to_image(self, instance_obj2world, instance_size, instance_type, 
                                ego2world, cam2ego, intrinsics, size
    ):
        # transfer to ego
        # (num_instances, 4, 4) = (num_instances, 4, 4) @ (4, 4)
        pose_obj2ego = torch.linalg.pinv(ego2world) @ instance_obj2world
        corners_local = bbox_to_corner3d(instance_size * 0.5)
        # (num_instances, 8, 4)
        corners_local = torch.concat([corners_local, torch.ones_like(corners_local[..., :1])], dim=-1)
        # (num_instances, 8, 4) = (num_instances, 8, 4) @ (num_instances, 4, 4)
        corners_ego = corners_local @ pose_obj2ego.transpose(1, 2)  # ?

        # transfer to camera
        ego2cam = self.update_camera_pose(torch.linalg.pinv(cam2ego), self.shift)
        corners_cam = ego2cam @ corners_ego.transpose(1, 2)

        # transfer to image
        # (num_instances, 3, 8) = (3, 3) @ (num_instances, 3, 8)
        corners_pixel = intrinsics @ corners_cam[:, :3, :]
        corners_pixel[:, 0, :] = corners_pixel[:, 0, :] / torch.absolute(corners_pixel[:, -1, :])
        corners_pixel[:, 1, :] = corners_pixel[:, 1, :] / torch.absolute(corners_pixel[:, -1, :])
        # (num_instances, 8, 2)
        corners_pixel = corners_pixel[:, :2, :].transpose(1, 2)

        # filter bboxes
        # (num_instances, 4)
        bbox2d = self.get_2d_bounding_box(corners_pixel.numpy())
        scope_filter = (corners_cam[:, 2, 0].numpy() > 0) & (corners_cam[:, 2, 0].numpy() < self.detection_scope)
        bbox_filter = self.check_2dbbox(bbox2d, size)
        area_filter = self.check_area(bbox2d)
        bbox2d = bbox2d[scope_filter & bbox_filter & area_filter]
        typenames = instance_type[scope_filter & bbox_filter & area_filter]
        bbox_info = self.postprocess_bbox(bbox2d, typenames, size)
        return bbox_info

    def postprocess_bbox(self, bbox2d, typenames, size):
        ret = []
        heigth, width = size
        for bbox, typename in zip(bbox2d, typenames):
            x1, y1, x2, y2 = bbox
            x1, y1 = max(int(x1), 0), max(int(y1), 0)
            x2, y2 = max(int(x2), 0), max(int(y2), 0)
            ret.append([x1, y1, x2, y2, typename.item()])
        return ret

    def show_images(self, show_image_path, image_names_list, gt_images_list, 
                    novel_images_list, bbox_infos_list, cam_name_list):
        for idx, (image_name, novel_image, cam_name) in enumerate(zip(image_names_list, novel_images_list, cam_name_list)):
            gt_image, bbox_info = gt_images_list[idx], bbox_infos_list[idx]
            image_draw = draw_2d_box_on_image(bbox_info, novel_image)
            cv2.imwrite(os.path.join(show_image_path, image_name + f"-{cam_name}" + "-gt_bboxes.png"), image_draw)
            cv2.imwrite(os.path.join(show_image_path, image_name + f"-{cam_name}" + "-gt.png"), gt_image)

    def get_gt_bboxes(self, novel_images_list, image_indices_list):
        bbox_infos_list, gt_images_list = [], []
        for novel_image, image_index in zip(novel_images_list, image_indices_list):
            resized_bbox_info, gt_image = self.get_frame_info(image_index, novel_image.shape[:2])
            bbox_infos_list.append(resized_bbox_info)
            gt_images_list.append(gt_image)

        return bbox_infos_list, gt_images_list
    