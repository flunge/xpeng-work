import cv2
import os
import time
import glob
import numpy as np
import torch
from reconic.simulator.render_strategy.render_strategy import RenderStrategy


class OriginalPngRenderStrategy(RenderStrategy):
    def _get_image_origin_dir(self):
        base_dir = f"/workspace/group_share/adc-sim/users/cloudsim/images_origin/{self.config_manager.clip_id}/images_origin/"
        return base_dir

    def get_reference_image(self, rendered_timestamp, camera):
        png_path = self.get_real_car_image(rendered_timestamp, camera, self.base_dir)
        if not png_path:
            print(
                f"Error: Failed to find undistorted image for timestamp {rendered_timestamp} and camera {camera}"
            )
            return None
        print(f"[OriginalPngRenderStrategy] find png_path = {png_path}")
        raw_img = cv2.imread(png_path, cv2.IMREAD_UNCHANGED)   
        if raw_img is None:
            print(
                f"Error: Failed to read undistorted image for timestamp {rendered_timestamp} and camera {camera}"
            )
            return None
        raw_img = cv2.cvtColor(raw_img, cv2.COLOR_BGR2RGB)
        return raw_img

    def render(self, simulator, camera, rendered_timestamp, ego_pose_world, 
            collision_info_arr, real_car_image=None):
        print(f"[RenderStrategy] Using original PNG render strategy")
        t1 = time.time()
        
        raw_img = self._get_ref_image(real_car_image, rendered_timestamp, camera)
        raw_img = self._post_process_image_to_numpy(raw_img)
        print(f"[OriginalPngRenderStrategy] read image cost: {(time.time() - t1) * 1000:.2f}ms")
        return raw_img

    def render_batch(self, simulator, camera_list, rendered_timestamp, ego_pose_world,
                    collision_info_arr, real_car_image_map=None):
        print(f"[RenderStrategy] Using original PNG batch render strategy")
        results = {}
        
        for cam in camera_list:
            real_car_image = real_car_image_map.get(cam) if real_car_image_map else None
            img = self._get_ref_image(real_car_image, rendered_timestamp, cam)
            results[cam] = self._post_process_image_to_numpy(img)
            print(f"[OriginalPngRenderStrategy] Rendering {cam} images done", flush=True)
        
        return results        