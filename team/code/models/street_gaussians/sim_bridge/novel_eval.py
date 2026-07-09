import os, sys
import json
from torch_fidelity import calculate_metrics

from sim_bridge.simulator import StreetGaussianSimulator
from lib.visualizers.xpeng_visualizer import XpengVisualizer
from lib.config import cfg
# import from parent directory
current_dir = os.path.dirname(__file__) 
root_path = os.path.abspath(os.path.join(current_dir, "..", ".."))
print(f"import relative_path {root_path}")
sys.path.extend([root_path])
from sim_interface.utils import get_lateral_shifted_egoposes, get_longitudinal_interpolated_egoposes
from sim_interface.utils import get_mflocalpose_from_dds_json


class NovelEvaluator(StreetGaussianSimulator):
    def __init__(self):
        super(NovelEvaluator, self).__init__()
        longitudinal_sample_stride, lateral_sample_stride = 5, 2
        egopose_longitudinal, new_timestamps = get_longitudinal_interpolated_egoposes(
            self.egoposes_anchored_origin, self.timestamps_origin, stride=longitudinal_sample_stride)
        egopose_shifted_l1 = get_lateral_shifted_egoposes(
            egopose_longitudinal, shift_distance=1., stride=lateral_sample_stride)
        egopose_shifted_l2 = get_lateral_shifted_egoposes(
            egopose_longitudinal, shift_distance=2., stride=lateral_sample_stride)
        egopose_shifted_r1 = get_lateral_shifted_egoposes(
            egopose_longitudinal, shift_distance=-1., stride=lateral_sample_stride)
        egopose_shifted_r2 = get_lateral_shifted_egoposes(
            egopose_longitudinal, shift_distance=-2., stride=lateral_sample_stride)
        # egoposes, timestamps, fps for videos
        self.to_eval = {
            "longitudinal": [egopose_longitudinal, new_timestamps, 5],
            "shifted_l1": [egopose_shifted_l1, new_timestamps[::lateral_sample_stride], 2.5],
            "shifted_l2": [egopose_shifted_l2, new_timestamps[::lateral_sample_stride], 2.5],
            "shifted_r1": [egopose_shifted_r1, new_timestamps[::lateral_sample_stride], 2.5],
            "shifted_r2": [egopose_shifted_r2, new_timestamps[::lateral_sample_stride], 2.5],
        }
        self.save_dir = os.path.join(
            cfg.model_path, "evaluation/iter_{}".format(max(cfg.train.checkpoint_iterations))
        )

    def process_one_views(self, rendered_timestamps, rendered_cameras, egoposes, key, visualizer):
        for idx, timestamp in enumerate(rendered_timestamps):
            for cam_id in rendered_cameras:
                ego_pose_shifted = egoposes[idx]
                ego_pose_world = self.anchor_pose @ ego_pose_shifted
                result, camera = self.render(cam_id, timestamp, ego_pose_world)
                cam_name = camera.meta['cam']
                result_redistort = self.redistort(camera, result['rgb'])

                visualizer.visualize_evaluator(result_redistort, camera, key)
                print(f"Rendering-Eval {key} {cam_name} {idx+1}/{len(rendered_timestamps)} done", flush=True)
    
    def generate_novel_views(self):
        for key in self.to_eval:
            # init visualizer
            visualizer = XpengVisualizer(self.save_dir)
            egoposes, timestamps, fps = self.to_eval[key]
            rendered_timestamps = timestamps
            rendered_cameras = self.cameras if 'shifted' not in key else self.cameras[:1]

            self.process_one_views(rendered_timestamps, rendered_cameras, egoposes, key, visualizer)
            visualizer.save_video_eval(mode=key, fps=fps)

    def evaluate(self, datasets_path):
        results = {}
        novel_views_folders = [
            i for i in os.listdir(self.save_dir) if os.path.isdir(os.path.join(self.save_dir, i))]
        for folder in novel_views_folders:
            folder_path = os.path.join(self.save_dir, folder)
            for subfolder in os.listdir(folder_path):
                if "cam" in subfolder:
                    generated_images = os.path.join(folder_path, subfolder)
                    real_images = os.path.join(datasets_path, "images_origin", subfolder)
                    metrics = calculate_metrics(
                        input1=real_images, input2=generated_images, 
                        cuda=True, isc=False, fid=True, kid=False
                    )
                    results[folder + "_" + subfolder] = metrics
        json_path = os.path.join(self.save_dir, "evaluation_results.json")
        json.dump(results, open(json_path, "w"), indent=4)
        return json_path


class NovelViewGenerator(StreetGaussianSimulator):
    def __init__(self, json_path, timestamps=None):
        super(NovelViewGenerator, self).__init__(cfg, cp_simulation=False)
        localpose_train = json.load(open(os.path.join(self.model_path, "localpose.json"), "r"))
        egopose_longitudinal, new_timestamps = get_mflocalpose_from_dds_json(
            json_path, timestamps, localpose_train
        )
        # timestamp_offset = self.result_dict['timestamp_offset']
        # full_anchorpose = localpose_train[str(timestamp_offset)]
        # egopose_longitudinal, new_timestamps = get_mflocalpose_from_dds_json_by_offset(
        #     json_path, timestamp_offset, full_anchorpose, timestamps
        # )
        # egoposes, timestamps, fps for videos
        self.to_eval = {
            "localpose": [egopose_longitudinal, new_timestamps, 1],
        }
        self.save_dir = os.path.join(
            cfg.model_path, "novelviews/iter_{}".format(max(cfg.train.checkpoint_iterations))
        )

    def process_one_views(self, rendered_timestamps, rendered_cameras, egoposes, key, visualizer):
        for idx, timestamp in enumerate(rendered_timestamps):
            for cam_id in rendered_cameras:
                ego_pose_shifted = egoposes[idx]
                ego_pose_world = ego_pose_shifted
                result, camera = self.render(cam_id, timestamp, ego_pose_world)
                cam_name = camera.meta['cam']
                result_redistort = self.redistort(cam_name, result['rgb'])

                visualizer.visualize_evaluator(result_redistort, camera, key)
                print(f"Rendering-Eval {key} {cam_name} {idx+1}/{len(rendered_timestamps)} done", flush=True)
    
    def generate_novel_views(self):
        for key in self.to_eval:
            # init visualizer
            visualizer = XpengVisualizer(self.save_dir)
            egoposes, timestamps, fps = self.to_eval[key]
            rendered_timestamps = timestamps
            rendered_cameras = self.cameras
            self.process_one_views(rendered_timestamps, rendered_cameras, egoposes, key, visualizer)


if __name__ == "__main__":
    cfg.mode = "render"
    cfg.render.save_image = False
    print("Rendering " + cfg.model_path)

    # novel_eval = NovelEvaluator()
    # t1 = time.time()
    # novel_eval.generate_novel_views()
    # t2 = time.time()
    # novel_eval.evaluate(cfg.source_path)
    # t3 = time.time()
    # print(f"Generate novel views time: {t2-t1}, Evaluate time: {t3-t2}")

    json_path = "/workspace/yangxh7@xiaopeng.com/datasets/xpeng/subrun/"\
        "c-480d958f-7f73-3b4b-b643-e46fe0c58b80/LocalPoseTopic.json"
    timestamps = [
        1739003474446420723
    ]
    novel_gen = NovelViewGenerator(json_path, timestamps)
    novel_gen.generate_novel_views()
    