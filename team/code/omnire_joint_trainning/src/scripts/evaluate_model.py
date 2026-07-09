import json  
import os, sys
import cv2
import numpy as np
from abc import abstractmethod
from abc import ABC
from reconic.datasets.xpeng.constants import DATASET_CLASSES_IN_SEMANTIC


class MetricBase(ABC):
    def __init__(self):
        pass

    @abstractmethod
    def __call__(self, camera, modify_image, base_image, **kwargs):
        pass

    @abstractmethod
    def name() -> str:
        pass

    @abstractmethod
    def save_result(self, output):
        pass

    @abstractmethod
    def result(self):
        pass


class PSNRMetric(MetricBase):
    def __init__(self):
        self.__name = "psnr"
        self.__result = {}
        self.__skymask_result = {}
        self.__obj_result = {}
        

    def psnr(self, img1, img2):
        mse = np.mean(
                (img1 / 255.0 - img2 / 255.0) ** 2
            )
        if mse == 0:
            r = float("inf")
        else:
            r = 20 * np.log10(1 / np.sqrt(mse))
        return r

    def __call__(self, camera, time_stamp, modify_image, base_image, **kwargs):
        assert modify_image.shape == base_image.shape
        modify_image = modify_image.astype(np.float32)
        base_image = base_image.astype(np.float32)

        nomask_psnr = self.psnr(modify_image, base_image)
        if camera not in self.__result:
            self.__result[camera] = {}
        self.__result[camera][time_stamp] = nomask_psnr

        if kwargs.get("mask", None):
            seg_mask = cv2.imread(kwargs["mask"], cv2.IMREAD_GRAYSCALE)
            sky_mask = (seg_mask == 27)
            if camera not in self.__skymask_result:
                self.__skymask_result[camera] = {}
            self.__skymask_result[camera][time_stamp] = self.psnr(
                modify_image[~sky_mask], base_image[~sky_mask]
            )

            obj_mask = DATASET_CLASSES_IN_SEMANTIC["VEHICLE"]
            obj_region = np.isin(seg_mask, obj_mask).astype(np.uint8)
            kernel = np.ones((3, 3), np.uint8)
            obj_region_dilated = cv2.dilate(obj_region, kernel, iterations=1)
            if camera not in self.__obj_result:
                self.__obj_result[camera] = {}
            self.__obj_result[camera][time_stamp] = self.psnr(
                modify_image[obj_region_dilated == 1],
                base_image[obj_region_dilated == 1],
            )

        return nomask_psnr
    
    def compute_averages(self):
        averages = {
            "psnr": {},
            "psnr_nosky": {},
            "psnr_obj": {}
        }
        
        # 计算普通PSNR的平均值
        for cam in self.__result:
            if self.__result[cam]:  
                psnr_values = list(self.__result[cam].values())
                valid_values = [v for v in psnr_values if v != float('inf')]
                if valid_values:
                    averages["psnr"][cam] = np.mean(valid_values)
                else:
                    averages["psnr"][cam] = float('inf')
        
        # 计算无天空区域PSNR的平均值
        for cam in self.__skymask_result:
            if self.__skymask_result[cam]:  
                psnr_values = list(self.__skymask_result[cam].values())
                valid_values = [v for v in psnr_values if v != float('inf')]
                if valid_values:
                    averages["psnr_nosky"][cam] = np.mean(valid_values)
                else:
                    averages["psnr_nosky"][cam] = float('inf')
        
        # 计算obj PSNR的平均值
        for cam in self.__obj_result:
            if self.__obj_result[cam]:  
                psnr_values = list(self.__obj_result[cam].values())
                valid_values = [v for v in psnr_values if v != float('inf')]
                if valid_values:
                    averages["psnr_obj"][cam] = np.mean(valid_values)
                else:
                    averages["psnr_obj"][cam] = float('inf')
        
        return averages

    def save_result(self, output):
        if not os.path.exists(output):
            os.makedirs(output)
        for cam in self.__result:
            with open(os.path.join(output, f"{self.__name}_{cam}.json"), "w") as f:
                json.dump(self.__result[cam], f)
        for cam in self.__skymask_result:
            with open(os.path.join(output, f"{self.__name}_nosky_{cam}.json"), "w") as f:
                json.dump(self.__skymask_result[cam], f)
        for cam in self.__obj_result:
            with open(os.path.join(output, f"{self.__name}_obj_{cam}.json"), "w") as f:
                json.dump(self.__obj_result[cam], f)
        # 计算并保存各类PSNR的平均值到单独文件
        averages = self.compute_averages()
        with open(os.path.join(output, "psnr_averages.json"), "w") as f:
            json.dump(averages, f, indent=2)
        
        print(f"PSNR averages saved to {os.path.join(output, 'psnr_averages.json')}")

    def result(self):
        return self.__result

    def name(self):
        return self.__name


def process_metric_calculation(simulator, timestamp, cam_name, result_redistort, metric):
    dataset_dir = os.path.join(simulator.cfg.data.data_root, simulator.cfg.data.scene_idx)
    mask_path = None
    seg_dir = os.path.join(dataset_dir, "segs", cam_name)
    if os.path.exists(seg_dir):
        mask_file = os.path.join(seg_dir, f"{timestamp}.png")
        if os.path.exists(mask_file):
            mask_path = mask_file
    metric_value = metric(
        cam_name,
        timestamp,
        result_redistort['redistort_rgb'],
        result_redistort['redistort_rgb_gt'],
        mask=mask_path
    )
    print(f"{metric.name().upper()} for {cam_name} at {timestamp}: {metric_value}") 
    return metric_value