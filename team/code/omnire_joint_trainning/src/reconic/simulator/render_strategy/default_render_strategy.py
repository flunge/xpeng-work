import torch
from reconic.simulator.render_strategy.render_strategy import RenderStrategy

class DefaultRenderStrategy(RenderStrategy):
    def render(self, simulator, camera, rendered_timestamp, ego_pose_world, collision_info_arr, real_car_image=None):
        print(f"[RenderStrategy] Using default render strategy")
        result, camera_name = simulator.render(camera, int(rendered_timestamp), ego_pose_world, collision_info_arr)
        if result is None:
            return None
        result["rgb"] = torch.clamp(result["rgb"].permute(2, 0, 1) * 255, 0, 255)
        result["rgb"] = result["rgb"].to(torch.uint8)
        img_distort_tensor = simulator.redistort_gpu(camera_name, result["rgb"])
        img_distort = img_distort_tensor.permute(1, 2, 0).cpu().numpy()
        return img_distort
    
    def _get_image_origin_dir(self):
        return ""
    
    def render_batch(self, simulator, camera_list, rendered_timestamp, ego_pose_world, collision_info_arr, real_car_image_map = None):
        print(f"[RenderStrategy] Using batch render strategy")
        results = dict()
        gs_results = simulator.render_multi_cam(camera_list, rendered_timestamp, ego_pose_world)

        print(f'camera = {camera_list}')
        for cam_name, result in zip(camera_list, gs_results):
            rgb = torch.clamp(result["rgb"].permute(2, 0, 1) * 255, 0, 255).to(torch.uint8)
            img_distort_tensor = simulator.redistort_gpu(cam_name, rgb)
            img_distort = img_distort_tensor.permute(1, 2, 0).cpu().numpy()
            results[cam_name] = img_distort 
        return results