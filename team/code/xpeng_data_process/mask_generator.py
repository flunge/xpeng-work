import cv2
import json
import os
import threading
import numpy as np
from PIL import Image, ImageDraw


class MaskGenerator:
    def __init__(self, cfg):
        self.cfg = cfg
        self.undistort_crop = cfg.processor.undistort_crop
        self.masks_path = os.path.join(cfg.clip_path, "masks")
        for cam_name in cfg.cam_list:
            os.makedirs(os.path.join(self.masks_path, cam_name), exist_ok=True)

        self.clip_metadata = json.load(open(os.path.join(cfg.clip_path, "metadata.json")))
        self.mask_folder_mapping = {
            50: "assets/Vehicle_Mask/F30_Masks",
            43: "assets/Vehicle_Mask/E38A_Masks",
            21: "assets/Vehicle_Mask/E28A_Masks",
            40: "assets/Vehicle_Mask/E38_Masks",
            60: "assets/Vehicle_Mask/H93_Masks",
            70: "assets/Vehicle_Mask/F57_Masks",
            201: "assets/Vehicle_Mask/XP5_201_Masks",
            205: "assets/Vehicle_Mask/XP5_269_Masks",
            203: "assets/Vehicle_Mask/E38B_Masks",
            206: "assets/Vehicle_Mask/F30B_Masks",
            231: "assets/Vehicle_Mask/H93AS_Masks",
            269: "assets/Vehicle_Mask/XP5_269_Masks",
            247: "assets/Vehicle_Mask/XP5_247_Masks",
            239: "assets/Vehicle_Mask/XP5_239_Masks",
            229: "assets/Vehicle_Mask/XP5_229_Masks",
            243: "assets/Vehicle_Mask/XP5_243_Masks",
            238: "assets/Vehicle_Mask/XP5_238_Masks",
            268: "assets/Vehicle_Mask/XP5_268_Masks",
            245: "assets/Vehicle_Mask/XP5_245_Masks",
            281: "assets/Vehicle_Mask/XP5_281_Masks",
            284: "assets/Vehicle_Mask/XP5_284_Masks",
            244: "assets/Vehicle_Mask/XP5_244_Masks",
            283: "assets/Vehicle_Mask/XP5_283_Masks",
            270: "assets/Vehicle_Mask/XP5_270_Masks",
            304: "assets/Vehicle_Mask/XP5_304_Masks",
            212: "assets/Vehicle_Mask/D01M_Masks",
            # 可以在这里继续添加其他车型的映射
        }
        self.mask_dict = {
            "cam2": None,
            "cam3": None,
            "cam4": None,
            "cam5": None,
            "cam6": None
        }
        self._lock = threading.Lock()

    def get_mask_folder(self, origin=False):
        # 获取车型编号
        vehicle_model = self.clip_metadata.get("vehicle_model", None)
        # 根据车型编号获取对应的掩膜文件夹路径
        mask_folder = self.mask_folder_mapping.get(vehicle_model)
        if mask_folder is None:
            raise Exception(f"未找到对应车型的掩膜，车型编号: {vehicle_model}")
        return mask_folder if not origin else mask_folder + "_Origin"

    def setup_default_mask(self, undistorted_img, cam_name):
        mask_folder = self.get_mask_folder()
        code_dir = os.path.dirname(os.path.abspath(__file__))
        mask_file_name = f"_{cam_name}_mask.png"
        mask_path = os.path.join(code_dir, mask_folder, mask_file_name)
        mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
        mask = cv2.resize(mask, (undistorted_img.shape[1], undistorted_img.shape[0]))
        self.mask_dict[cam_name] = mask

    def setup_default_mask_from_origin(self, undistorter, cam_name):
        mask_folder = self.get_mask_folder(origin=True)
        code_dir = os.path.dirname(os.path.abspath(__file__))
        mask_file_name = f"_{cam_name}_mask.png"
        mask_path = os.path.join(code_dir, mask_folder, mask_file_name)
        mask_origin = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
        assert mask_origin is not None, f"Origin mask image not found: {mask_path}"
        mask, _1, _2 = undistorter.undistort(mask_origin, cam_name, self.undistort_crop)
        self.mask_dict[cam_name] = mask
        
    def generate_mask(self, undistorted_img, roi, cam_name, undistorter=None):
        if cam_name in ["cam0", "cam7"]:
            x, y, w, h = roi
            mask = np.ones(undistorted_img.shape[:2], dtype=np.uint8) * 255
            black_pixels = np.all(undistorted_img == 0, axis=-1)
            mask[black_pixels & ~((y <= np.arange(mask.shape[0])[:, None]) & 
                                (np.arange(mask.shape[0])[:, None] < y+h) & 
                                (x <= np.arange(mask.shape[1])) & 
                                (np.arange(mask.shape[1]) < x+w))] = 0
        else:
            with self._lock:
                if self.mask_dict[cam_name] is None:
                    if self.cfg.processor.use_origin_mask:
                        self.setup_default_mask_from_origin(undistorter, cam_name)
                    else:
                        self.setup_default_mask(undistorted_img, cam_name)
                mask = self.mask_dict[cam_name]
        return mask

    