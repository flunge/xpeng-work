import torch
import time
import numpy as np
from PIL import Image
from reconic.simulator.render_strategy.render_strategy import RenderStrategy
import os


class DifixRenderStrategy(RenderStrategy):

    def _post_process(self, img_distort_tensor, camera, simulator):
        """后处理：resize到目标尺寸，转numpy"""
        target_height = int(simulator.calib_info['new' + camera]['height'])
        target_width = int(simulator.calib_info['new' + camera]['width'])
        
        if img_distort_tensor.shape[1] != target_height or img_distort_tensor.shape[2] != target_width:
            img_distort_tensor = torch.nn.functional.interpolate(
                img_distort_tensor.unsqueeze(0).float(),
                size=(target_height, target_width), mode='bilinear', align_corners=False
            ).squeeze(0).clamp(0, 255).to(torch.uint8)
        
        return img_distort_tensor.permute(1, 2, 0).cpu().numpy()

    def render(self, simulator, camera, rendered_timestamp, ego_pose_world, collision_info_arr, real_car_image=None):
        print(f"[RenderStrategy] Using Difix render strategy")
        t1 = time.time()
        result, camera_name = simulator.render(camera, int(rendered_timestamp), ego_pose_world, collision_info_arr)

        if result is None:
            return None

        print(f'render cost {time.time() - t1}')

        rgb = self._process_gs_result(result, camera_name)
        img_distort_tensor = simulator.redistort_gpu(camera_name, rgb)
        del result

        t2 = time.time()
        ref_image = self._get_ref_image(real_car_image, rendered_timestamp, camera)
        
        img_distort_tensor = simulator.image_fixer.fix_image_xpeng(
            img_distort_tensor, ref_img=ref_image, camera_name=camera_name)

        print(f'fix_image cost {time.time() - t2}')
        t3 = time.time()

        img_distort = self._post_process(img_distort_tensor, camera, simulator)
        print(f'img_distort cost {time.time() - t3}')
        return img_distort

    def get_reference_image(self, rendered_timestamp, camera):
        difix_config = self.config_manager.get_difix_config()

        if not difix_config.get("use_reference_image", False):
            print(f"[DifixRenderStrategy] use_reference_image is False")
            return None

        base_dir = difix_config.get("reference_image_path", "")
        image_path = self.get_real_car_image(rendered_timestamp, camera, base_dir)
        
        if image_path is None or not isinstance(image_path, str):
            print(f"[DifixRenderStrategy] reference image path is not found")
            return None
            
        ref_pil = Image.open(image_path).convert('RGB')
        ref_array = np.array(ref_pil)
        ref_tensor = torch.from_numpy(ref_array).permute(2, 0, 1).to(torch.uint8).cuda()
        return ref_tensor
    
    def _get_image_origin_dir(self):
        difix_config = self.config_manager.get_difix_config()
        return difix_config.get("reference_image_path", "")
    
    def render_batch(self, simulator, camera_list, rendered_timestamp, ego_pose_world, 
                     collision_info_arr, real_car_image_map=None):
        print(f"[RenderStrategy] Using Difix batch render strategy")
        results = dict()
        gs_results = simulator.render_multi_cam(camera_list, rendered_timestamp, ego_pose_world)

        for cam_name, result in zip(camera_list, gs_results):
            rgb = self._process_gs_result(result, cam_name)
            img_distort_tensor = simulator.redistort_gpu(cam_name, rgb)

            real_car_image = real_car_image_map.get(cam_name) if real_car_image_map else None
            ref_image = self._get_ref_image(real_car_image, rendered_timestamp, cam_name)
            
            img_distort_tensor = simulator.image_fixer.fix_image_xpeng(
                img_distort_tensor, ref_img=ref_image, camera_name=cam_name)

            img_distort = self._post_process(img_distort_tensor, cam_name, simulator)
            results[cam_name] = img_distort
            print(f"[OriginalPngRenderStrategy] Rendering {cam_name} images done", flush=True)
        
        return results