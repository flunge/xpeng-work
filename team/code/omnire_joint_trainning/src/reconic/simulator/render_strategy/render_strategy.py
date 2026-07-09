from abc import ABC, abstractmethod
import os
import glob
import numpy as np
import torch
from reconic.simulator.render_config_manager.render_config_manager import SimulatorConfigManager
from reconic.utils.oss_utils import download_and_extract_tgz_from_oss

class RenderStrategy(ABC):

    def __init__(self):
        self.config_manager = SimulatorConfigManager.get_instance()
        self._initialize()

    @abstractmethod
    def render(self, simulator, camera, rendered_timestamp, ego_pose_world, collision_info_arr, real_car_image = None):
        pass

    @abstractmethod
    def render_batch(self, simulator, camera_list, rendered_timestamp, ego_pose_world, collision_info_arr, real_car_image_map = None):
        pass

    def _initialize(self):
        self.base_dir = self._get_image_origin_dir()
        # self.images_origin_downloader()

    @abstractmethod
    def _get_image_origin_dir(self):
        pass

    def _process_gs_result(self, result, cam_name):
        """处理高斯渲染结果：归一化、转uint8、redistort"""
        result["rgb"] = torch.clamp(result["rgb"].permute(2, 0, 1) * 255, 0, 255).to(torch.uint8)
        return result["rgb"]

    def _post_process_image_to_numpy(self, image):
        """
        后处理：将图像转换为HWC格式的NumPy uint8数组
        支持输入：Tensor(CHW/HWC, CPU/CUDA)、NumPy数组(CHW/HWC)
        输出：NumPy数组 (H, W, C), dtype=uint8
        """
        if image is None:
            return None
        
        if isinstance(image, torch.Tensor):
            if image.device.type == 'cuda':
                image = image.cpu()
            image = image.numpy()
        
        if image.ndim == 3 and image.shape[0] == 3:
            image = np.transpose(image, (1, 2, 0))

        if image.dtype != np.uint8:
            image = image.astype(np.uint8)
        
        return image  
            
    def _get_ref_image_from_cache(self, real_car_image):
        """从缓存获取参考图像，转为GPU tensor"""
        try:
            image_data = real_car_image.get("image")
            if image_data is not None:
                image_np = np.asarray(image_data, dtype=np.uint8).reshape(
                    (real_car_image["height"], real_car_image["width"], 3))
                return torch.from_numpy(image_np).permute(2, 0, 1).to(torch.uint8).cuda()
        except Exception as e:
            print(f'[RenderStrategy] Error processing real_car_image: {e}')
        return None

    def _get_ref_image(self, real_car_image, rendered_timestamp, camera):
        """优先使用缓存图像，否则从文件读取"""
        ref_image = self._get_ref_image_from_cache(real_car_image) if real_car_image else None
        return ref_image if ref_image is not None else self.get_reference_image(rendered_timestamp, camera)            

    def images_origin_downloader(self):
        if not self.base_dir:
            print(f"[images_origin_downloader] Base directory is not set")
            return

        need_download = True
        if os.path.exists(self.base_dir):
            need_download = False
            print(f"[images_origin_downloader] Directory already exists: {self.base_dir}")
            # check if the image numbers is greater than 300 in each camera folder
            for cam in ['cam0', 'cam2', 'cam3', 'cam4', 'cam5', 'cam6', 'cam7']:
                cam_dir = os.path.join(self.base_dir, cam)
                if not os.path.exists(cam_dir) or len(os.listdir(cam_dir)) < 300    :
                    print(f"[images_origin_downloader] Camera folder {cam} does not exist or has less than 300 images: {cam_dir}")
                    need_download = True
                    break
        
        if need_download:
            print(f"[images_origin_downloader]first time move images_origin from oss to fuyao")
            oss_object_key = os.path.join("sim_engine/datasets", self.config_manager.clip_id, "images_origin/images_origin.tgz")
            download_and_extract_tgz_from_oss(oss_object_key, self.base_dir)
        else:
            print(f"[images_origin_downloader] images_origin already exists: {self.base_dir}")



    def get_real_car_image(
        self, timestamp: int, camname: str, base_dir: str, max_time_diff_ns: int = 800 * 1000000
    ):

        cam_list = ['cam0', 'cam2', 'cam3', 'cam4', 'cam5', 'cam6', 'cam7']

        if camname not in cam_list:
            print(f"[RenderStrategy] input is not valid cam, error name =  {camname}")
            return None

        timestamp = int(timestamp)
        trigger_time_dis = os.environ.get("TRIGGER_TIME_DIS")
        if trigger_time_dis is not None:
            trigger_time_dis_ns = int(float(trigger_time_dis) * 1e9)
            timestamp -= trigger_time_dis_ns
            print(f"[RenderStrategy] TRIGGER_TIME_DIS applied: {trigger_time_dis}s, adjusted timestamp: {timestamp}")

        # 构建搜索路径
        print(f"[RenderStrategy] input camname = {camname}")
        print(f"[RenderStrategy] input base_dir = {base_dir}")
        search_dir = os.path.join(base_dir, camname)
        if not os.path.exists(search_dir):
            print(f"[RenderStrategy] not valid path = {search_dir}")
            return None

        # 获取所有png文件
        pattern = "*.png"
        search_pattern = os.path.join(search_dir, pattern)
        all_files = glob.glob(search_pattern)

        if not all_files:
            return None

        # 提取所有时间戳
        timestamps = []
        file_paths = []
        for file_path in all_files:
            try:
                # 从文件名提取时间戳
                filename = os.path.basename(file_path)
                ts = int(filename.split('.')[0])
                timestamps.append(ts)
                file_paths.append(file_path)
            except ValueError:
                continue

        if not timestamps:
            return None

        # 找到最接近的时间戳
        timestamps = np.array(timestamps)
        time_diffs = np.abs(timestamps - timestamp)
        closest_idx = np.argmin(time_diffs)
        closest_timestamp = timestamps[closest_idx]
        closest_file_path = file_paths[closest_idx]
        min_time_diff = time_diffs[closest_idx]

        print(
            f"[RenderStrategy] target timestamp: {timestamp}, closest timestamp: {closest_timestamp}, diff: {min_time_diff/1e9} s"
        )

        # 校验时间差是否在允许范围内
        # if min_time_diff > max_time_diff_ns:
        #     print(
        #         f"[RenderStrategy] time diff {min_time_diff}ns exceeds threshold {max_time_diff_ns}ns"
        #     )
        #     return None

        print(f"[RenderStrategy] matching_files = {closest_file_path}")
        return closest_file_path    
