import os
import cv2
import time
import numpy as np
import pandas as pd
from lib.config import cfg
from lib.visualizers.xpeng_visualizer import XpengVisualizer
from sim_bridge.simulator import StreetGaussianSimulator


class EvaluatorMethod():
    def __init__(self, output_name, method):
        self.output_name = output_name
        self.method = method
        self.data_result = {"timestamp" : []}
        self.main_cam = None
    def run_method(self, cam_name, timestamp, img_base, img_upd):
        if self.main_cam is None or self.main_cam == cam_name:
            self.data_result["timestamp"].append(timestamp)
            self.main_cam = cam_name
        cam_result_list = self.data_result.get(cam_name, [])
        cam_result_list.append(self.method(img_base, img_upd))
        self.data_result[cam_name] = cam_result_list
    
    def save_result(self):
        df = pd.DataFrame(self.data_result)
        df_des = df.describe()
        merged = pd.concat([df_des, df])
        merged = merged.reset_index()
        merged.to_csv(self.output_name, index=False)


class ImageEvaluator():
    def __init__(self, output_dir=""):
        self.simulator_obj = StreetGaussianSimulator()
        self.evaluator_methods = []
        self.evaluator_methods.append(EvaluatorMethod(os.path.join(output_dir, "psnr.csv"), self.psnr))
        # self.evaluator_methods.append(EvaluatorMethod("imf.csv", self.psnr))

    def psnr(self, modify_image: np.ndarray, base_image: np.ndarray):
        assert modify_image.shape == base_image.shape
        modify_image_to_one = modify_image.astype(np.float32) / 255.0
        base_image_to_one = base_image.astype(np.float32) / 255.0
        mse = np.mean((modify_image_to_one - base_image_to_one) ** 2)
        if(mse == 0):
            return float("inf")
        return 20 * np.log10(1 / np.sqrt(mse))

    def run_evaluator(self):
        rendered_timestamps = self.simulator_obj.timestamps_origin
        rendered_cameras = self.simulator_obj.cameras
        egoposes_shifted = self.simulator_obj.egoposes_anchored_origin
        # print("run_evaluator: {}".format(rendered_timestamps))
        for idx, timestamp in enumerate(rendered_timestamps):
            # print("timestamp: {}, cnt: {}".format(timestamp, cnt))
            ego_idx = self.simulator_obj.timestamps_origin.index(timestamp)
            ego_pose_shifted = egoposes_shifted[ego_idx]
            ego_pose_world = self.simulator_obj.anchor_pose @ ego_pose_shifted
            
            for cam_id in self.simulator_obj.cameras:
                sim_camera_image, camera = self.simulator_obj.render(cam_id, timestamp, ego_pose_world)
                sim_camera_image_redistort = self.simulator_obj.redistort(camera, sim_camera_image["rgb"])
                cam_name = camera.meta['cam']
                print(os.path.join(cfg.source_path, "images_origin", f"{cam_name}/{timestamp}.png"))
                origin_camera_image = cv2.cvtColor(
                    cv2.imread(os.path.join(cfg.source_path, "images_origin", f"{cam_name}/{timestamp}.png")),
                    cv2.COLOR_BGR2RGB
                )
                for evaluator_method in self.evaluator_methods:
                    evaluator_method.run_method(cam_name, timestamp, origin_camera_image, sim_camera_image_redistort)

    def save_result(self):
        for evaluator_method in self.evaluator_methods:
            evaluator_method.save_result()

            
if __name__ == "__main__":
    img1 = np.random.randint(0, 256, (256, 256, 3), dtype=np.uint8)
    img2 = np.random.randint(0, 256, (256, 256, 3), dtype=np.uint8)
    evaluator = ImageEvaluator()
    print(evaluator.psnr(img1, img2))
    sim_start_time = time.time()
    evaluator.run_evaluator()
    sim_end_time = time.time()

    print("total_time: {}".format(sim_end_time - sim_start_time))
    # data = {
    #     'Name': ['Alice', 'Bob', 'Charlie'],
    #     'Age': [25, 30, 35],
    #     'City': ['New York', 'Los Angeles', 'Chicago']
    # }
    # df = pd.DataFrame(data)

    # df.to_csv('output.csv')