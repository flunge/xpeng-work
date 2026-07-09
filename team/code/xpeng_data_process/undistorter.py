import cv2
import json
import os
import threading
import numpy as np
from copy import deepcopy

from utils.calib_utils import get_camera_calib


class Undistorter:
    def __init__(self, cfg):
        self.cfg = cfg
        self.images_path = os.path.join(cfg.clip_path, "images")
        self.vision_images_path = os.path.join(cfg.clip_path, "images_vision")
        for cam_name in cfg.cam_list:
            os.makedirs(os.path.join(self.images_path, cam_name), exist_ok=True)

        self.expand_ratio = dict(cfg.processor.expand_ratio)
        self.calib_info = json.load(open(os.path.join(cfg.clip_path, "calib.json")))
        self.calib_info["expand_ratio"] = self.expand_ratio
        self.calib_info["undistort_crop"] = cfg.processor.undistort_crop
        self.roi_info = {}
        self.remap_cache = {}  # {cam_name: {'normal': (map1, map2), 'mvs': (map1, map2)}}
        self._lock = threading.Lock()

    def _lookup_or_store_remap(self, cam_name, cache_key, build_entry):
        with self._lock:
            cam_cache = self.remap_cache.get(cam_name)
            if cam_cache is not None and cache_key in cam_cache:
                return cam_cache[cache_key]

        entry = build_entry()

        with self._lock:
            if cam_name not in self.remap_cache:
                self.remap_cache[cam_name] = {}
            if cache_key not in self.remap_cache[cam_name]:
                self.remap_cache[cam_name][cache_key] = entry
            return self.remap_cache[cam_name][cache_key]

    def _build_remap_entry(self, img, camera_matrix, dist_coeffs, cam_name, expand, crop):
        h, w = img.shape[:2]
        h_new, w_new = int(expand * h), int(expand * w)
        alpha = 0 if crop else 1
        new_camera_matrix, roi = cv2.getOptimalNewCameraMatrix(
            camera_matrix, dist_coeffs, (w, h), alpha, (w_new, h_new)
        )
        map1, map2 = cv2.initUndistortRectifyMap(
            camera_matrix, dist_coeffs, None, new_camera_matrix, (w_new, h_new), cv2.CV_32FC1
        )
        return map1, map2, new_camera_matrix, roi

    def undistort_image_with_new_intrinc(self, img, camera_matrix, dist_coeffs, cam_name, expand=1., method=cv2.INTER_LINEAR, crop=False):
        cache_key = 'normal' if crop else 'noncrop'

        map1, map2, new_camera_matrix, roi = self._lookup_or_store_remap(
            cam_name,
            cache_key,
            lambda: self._build_remap_entry(img, camera_matrix, dist_coeffs, cam_name, expand, crop),
        )
        undistorted_img = cv2.remap(img, map1, map2, method)
        return undistorted_img, new_camera_matrix, roi

    def undistort(self, img, cam_name, undistort_crop, method=cv2.INTER_LINEAR):
        camera_matrix, dist_coeffs = get_camera_calib(self.calib_info[cam_name]['intrinsic'])

        undistorted_img, new_camera_matrix, roi = self.undistort_image_with_new_intrinc(
            img, camera_matrix, dist_coeffs, cam_name,
            expand=self.expand_ratio[cam_name], method=method, crop=undistort_crop
        )
        if undistort_crop:
            undistorted_noncrop_img, noncrop_camera_matrix, _ = self.undistort_image_with_new_intrinc(
                img, camera_matrix, dist_coeffs, cam_name,
                expand=self.expand_ratio[cam_name], method=method, crop=False
            )
            self._write_calib_info("noncrop", cam_name, noncrop_camera_matrix, dist_coeffs, undistorted_noncrop_img)

        self._write_calib_info("new", cam_name, new_camera_matrix, dist_coeffs, undistorted_img)
        with self._lock:
            if cam_name not in self.roi_info:
                self.roi_info[cam_name] = roi

        return undistorted_img, new_camera_matrix, roi

    def _build_mvs_remap_entry(self, img, cam_name):
        camera_matrix, dist_coeffs = get_camera_calib(self.calib_info[cam_name]['intrinsic'])
        h, w = img.shape[:2]
        map1, map2 = cv2.initUndistortRectifyMap(
            camera_matrix, dist_coeffs, None, camera_matrix, (w, h), cv2.CV_32FC1
        )
        return map1, map2, camera_matrix, None

    def undistort_vision(self, img, cam_name):
        map1, map2, new_camera_matrix, _ = self._lookup_or_store_remap(
            cam_name,
            'mvs',
            lambda: self._build_mvs_remap_entry(img, cam_name),
        )
        undistorted_img = cv2.remap(img, map1, map2, cv2.INTER_LINEAR)
        return undistorted_img, new_camera_matrix, None

    def get_remap_maps(self, img_shape, cam_name, mode='normal'):
        with self._lock:
            cam_cache = self.remap_cache.get(cam_name)
            if cam_cache is not None and mode in cam_cache:
                return cam_cache[mode]

        def build_entry():
            camera_matrix, dist_coeffs = get_camera_calib(self.calib_info[cam_name]['intrinsic'])
            h, w = img_shape[:2]

            if mode == 'normal':
                h_new, w_new = int(self.expand_ratio[cam_name] * h), int(self.expand_ratio[cam_name] * w)
                alpha = 0 if self.cfg.processor.undistort_crop else 1
                new_camera_matrix, roi = cv2.getOptimalNewCameraMatrix(
                    camera_matrix, dist_coeffs, (w, h), alpha, (w_new, h_new)
                )
                map1, map2 = cv2.initUndistortRectifyMap(
                    camera_matrix, dist_coeffs, None, new_camera_matrix, (w_new, h_new), cv2.CV_32FC1
                )
            elif mode == 'noncrop':
                h_new, w_new = int(self.expand_ratio[cam_name] * h), int(self.expand_ratio[cam_name] * w)
                new_camera_matrix, roi = cv2.getOptimalNewCameraMatrix(
                    camera_matrix, dist_coeffs, (w, h), alpha=1, newImgSize=(w_new, h_new)
                )
                map1, map2 = cv2.initUndistortRectifyMap(
                    camera_matrix, dist_coeffs, None, new_camera_matrix, (w_new, h_new), cv2.CV_32FC1
                )
            elif mode == 'mvs':
                map1, map2 = cv2.initUndistortRectifyMap(
                    camera_matrix, dist_coeffs, None, camera_matrix, (w, h), cv2.CV_32FC1
                )
                new_camera_matrix = camera_matrix
                roi = None
            else:
                raise ValueError(f"Unknown mode: {mode}. Must be 'normal', 'noncrop', or 'mvs'")

            return map1, map2, new_camera_matrix, roi

        return self._lookup_or_store_remap(cam_name, mode, build_entry)

    def _write_calib_info(self, prefix, cam_name, new_camera_matrix, dist_coeffs, img):
        key = prefix + cam_name
        with self._lock:
            if key in self.calib_info:
                return
            self.calib_info[key] = deepcopy(self.calib_info[cam_name])
            self.calib_info[key]["intrinsic"]["focal_length"] = new_camera_matrix[0, 0]
            self.calib_info[key]["intrinsic"]["focal_length_x"] = new_camera_matrix[0, 0]
            self.calib_info[key]["intrinsic"]["focal_length_y"] = new_camera_matrix[1, 1]
            self.calib_info[key]["intrinsic"]["cx"] = new_camera_matrix[0, 2]
            self.calib_info[key]["intrinsic"]["cy"] = new_camera_matrix[1, 2]
            self.calib_info[key]["intrinsic"]["distortion"] = dist_coeffs.tolist()
            self.calib_info[key]["name"] = key
            self.calib_info[key]["width"] = img.shape[1]
            self.calib_info[key]["height"] = img.shape[0]

    def dump_new_clib_info(self):
        with open(os.path.join(self.cfg.clip_path, "calib.json"), 'w+') as f:
            json.dump(self.calib_info, f, indent=4)

    def dump_roi_info(self):
        os.makedirs(os.path.join(self.cfg.clip_path, "misc"), exist_ok=True)
        for cam, roi in self.roi_info.items():
            x, y, w, h = roi
            dump_info = {
                "x": x, "y": y, "w": w, "h": h, "name": cam
            }
            json.dump(dump_info, 
                open(os.path.join(self.cfg.clip_path, "misc", f"roi_{cam}.json"), 'w+'), indent=4
            )
