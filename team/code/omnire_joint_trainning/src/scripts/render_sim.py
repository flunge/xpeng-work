import argparse
import os, sys
import cv2
import numpy as np
import torch
import time
import json  
 
# import from parent directory
current_dir = os.path.dirname(__file__) 
reconic_path = os.path.abspath(os.path.join(current_dir, ".."))
print(f"import reconic_path {reconic_path}")
# omnire_joint_trainning/src/scripts/render_sim.py
sim_interface_path = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
print(f"import sim_interface_path {sim_interface_path}")
sys.path.extend([reconic_path, sim_interface_path])
from sim_interface.utils import (
    get_lateral_shifted_egoposes,
    get_lateral_sin_waved_egoposes,
    quaternion_matrix,
)

from sim_interface.visualizers.xpeng_visualizer import XpengVisualizer
from reconic.simulator.reconic_simulator import ReconicSimulator
from reconic.simulator.reconic_simulator import fun_one_frame as render_fun_batch
from reconic.simulator.reconic_simulator import fun as render_fun_single
from reconic.simulator.render_strategy.strategies_factory import RenderStrategyFactory


def _localpose_to_matrix(mflp):
    position = mflp["smooth_pose"]["pose"]["p"]
    rotation = mflp["smooth_pose"]["pose"]["q"]
    translation = np.array([position["x"], position["y"], position["z"]], dtype=np.float32)
    quaternion = np.array([rotation["w"], rotation["x"], rotation["y"], rotation["z"]], dtype=np.float32)
    ego_pose_world = quaternion_matrix(quaternion)
    ego_pose_world[:3, 3] = translation
    return ego_pose_world.astype(np.float32)

def render_profile(
        simulator, rendered_timestamps, egoposes_shifted, save_path=None
    ):
    # simulator.gaussian.precompute_gaussians()
    simulator.cameras = [0,3,4,7]
    # simulator.cameras = [2, 5, 6]
    # simulator.cameras = [3,4,5,6]
    time_per_frame = []
    for idx, timestamp in enumerate(rendered_timestamps):
        ego_idx = simulator.timestamps_origin.index(timestamp)
        ego_pose_shifted = egoposes_shifted[ego_idx]
        ego_pose_world = simulator.get_anchor_pose() @ ego_pose_shifted
        t1 = time.time()
        results = simulator.simulate_one_frame_batch(timestamp, ego_pose_world)
        if idx != 0:
            time_per_frame.append(time.time() - t1)
        print(f"[INFO] idx {idx} done, cost: {time.time() - t1}")
        # for cam_name in results:
        #     file_path = f'{save_path}/{cam_name}/{idx}.png'
        #     os.makedirs(os.path.dirname(file_path), exist_ok=True)
        #     Image.fromarray(results[cam_name].permute(1,2,0).cpu().numpy()).save(file_path)
    # time_img_mean = np.mean(simulator.timings, axis=0)
    # time_frame_mean = np.sum(simulator.timings, axis=0) / len(rendered_timestamps)
    np.set_printoptions(formatter={'float_kind': '{:.4f}'.format})
    print(f"[INFO] frame timing mean: {np.mean(time_per_frame)} s")
    print(f"[INFO] frame timing from largest to smallest: {np.sort(time_per_frame)[::-1]} s")


def render_sim_origin(simulator, save_path='', mode="render", batch_mode=False):
    visualizer = XpengVisualizer(save_path)
    target_vis = {
        'redistort_rgb': 'rgb', 
        'redistort_rgb_background': 'Background_rgb', 
        'redistort_rgb_ground': 'Ground_rgb', 
        'redistort_rgb_object': 'Dynamic_rgb'
    }

    fps = 5
    stride = int(100 / fps)
    LocalPose_path = os.path.join(simulator.model_path, "LocalPoseTopic.json")
    LocalPose = json.load(open(LocalPose_path,"r"))[::stride]
    rendered_timestamps = [item['time_stamp']["nsec"] for item in LocalPose]
    ego_poses_world = np.stack([_localpose_to_matrix(item) for item in LocalPose], axis=0)
    strategy = RenderStrategyFactory.create_strategy()
    strategy.images_origin_downloader()

    if mode == "novel":
        ego_poses_world = get_lateral_sin_waved_egoposes(ego_poses_world, amplitude=3.5)

    idx = 0
    for timestamp, ego_pose_world in zip(rendered_timestamps, ego_poses_world):
        idx += 1
        result = dict()
        result_redistort = dict()

        if batch_mode:
            cam_names = [simulator._label2camera[cam_id] for cam_id in simulator.cameras]
            fun_res = render_fun_batch(simulator, timestamp, cam_names, None, ego_pose_world=ego_pose_world, debug=True)
            for cam_name, fun_res in fun_res.items():
                h, w = fun_res['height'], fun_res['width']
                img_data = fun_res['image'].reshape(h, w, 3)
                result[cam_name] = {"rgb": img_data}
                result_redistort[cam_name] = {"redistort_rgb": img_data}
                if 'image_gt' in fun_res:
                    result_redistort[cam_name]['redistort_rgb_gt'] = fun_res['image_gt'].permute(1, 2, 0).cpu().numpy().astype(np.uint8)
        else:
            for cam_id in simulator.cameras:
                cam_name = simulator._label2camera[cam_id]
                fun_res = render_fun_single(simulator, timestamp, cam_name, None, ego_pose_world=ego_pose_world, debug=True)
                h, w = fun_res['height'], fun_res['width']
                img_data = fun_res['image'].reshape(h, w, 3)
                result[cam_name] = {"rgb": img_data}
                result_redistort[cam_name] = {"redistort_rgb": img_data}
                if 'image_gt' in fun_res:
                    result_redistort[cam_name]['redistort_rgb_gt'] = fun_res['image_gt'].permute(1, 2, 0).cpu().numpy().astype(np.uint8)
        
        for cam_name in result:
            # read ground truth image if exists
            dataset_dir = os.path.join(simulator.cfg.data.data_root, simulator.cfg.data.scene_idx)
            img_gt_path = os.path.join(dataset_dir, "images_origin", f"{cam_name}/{timestamp}.png")
            group_share_dir = "/workspace/group_share/adc-sim/users/yangxh7/origin_img"
            group_share_path = os.path.join(group_share_dir, simulator.cfg.data.scene_idx, f"images_origin/{cam_name}/{timestamp}.png")
            if os.path.exists(img_gt_path):
                result_redistort[cam_name]['redistort_rgb_gt'] = cv2.cvtColor(
                    cv2.imread(img_gt_path), cv2.COLOR_BGR2RGB
                )
            elif os.path.exists(group_share_path):
                result_redistort[cam_name]['redistort_rgb_gt'] = cv2.cvtColor(
                    cv2.imread(group_share_path), cv2.COLOR_BGR2RGB
                )
            elif 'redistort_rgb_gt' not in result_redistort[cam_name]:
                result_redistort[cam_name]['redistort_rgb_gt'] = None

            # redistort images
            for k, v in target_vis.items():
                if k not in result_redistort[cam_name]:
                    if v in result[cam_name]:
                        result[cam_name][v] = torch.clamp(result[cam_name][v] * 255, 0, 255).permute(2, 0, 1)
                        result[cam_name][v] = result[cam_name][v].to(torch.uint8)
                        result_redistort[cam_name][k] = simulator.redistort_gpu(cam_name, result[cam_name][v])
                        # convert to numpy
                        result_redistort[cam_name][k] = (result_redistort[cam_name][k].permute(1, 2, 0).cpu().numpy()) 
                    else:
                        result_redistort[cam_name][k] = None

            # fill in empty images
            for k in result_redistort[cam_name]:
                if result_redistort[cam_name][k] is None:
                    result_redistort[cam_name][k] = np.zeros(result_redistort[cam_name]['redistort_rgb'].shape, dtype=np.uint8)

            image_name = timestamp
            visualizer.visualize_redistort(result_redistort[cam_name], cam_name, image_name)
            print(f"Rendering {cam_name} {idx}/{len(rendered_timestamps)} done", flush=True)

    video_mode = "novel" if mode == "novel" else "origin"
    visualizer.save_video_merged(mode=video_mode, fps=fps)

    # 如果 simulator 启用了 CLIP-IQA，自动保存评分结果
    if save_path and getattr(simulator, '_clipiqa_records', None):
        simulator.save_clipiqa_scores(save_path)

def render_sim(
        simulator, rendered_timestamps, rendered_cameras, egoposes_shifted, 
        fps=1, name='redistort', save_path='', hil_mode=False, save_img=False, full_mode=True,
        save_video=True
    ):
    visualizer = XpengVisualizer(save_path)
    visualizer.save_image = save_img
    if full_mode:
        target_vis = {
            'redistort_rgb': 'rgb', 
            'redistort_rgb_background': 'Background_rgb', 
            'redistort_rgb_ground': 'Ground_rgb', 
            'redistort_rgb_object': 'Dynamic_rgb'
        }
    else:
        target_vis = {'redistort_rgb': 'rgb'}

    for idx, timestamp in enumerate(rendered_timestamps):
        for cam_id in rendered_cameras:
            ego_idx = simulator.timestamps_origin.index(timestamp)
            ego_pose_shifted = egoposes_shifted[ego_idx]
            ego_pose_world = simulator.anchor_pose @ ego_pose_shifted
            cam_name = simulator._label2camera[cam_id]
            if hil_mode:
                result, ret_cam_name = simulator.render_hil(cam_name, int(timestamp), ego_pose_world.astype(np.float32))
            else:
                result, ret_cam_name = simulator.render(cam_name, int(timestamp), ego_pose_world.astype(np.float32))
            assert(ret_cam_name == cam_name)
            result_redistort = dict()

            # read ground truth image if exists
            dataset_dir = os.path.join(simulator.cfg.data.data_root, simulator.cfg.data.scene_idx)
            img_gt_path = os.path.join(dataset_dir, "images_origin", f"{cam_name}/{timestamp}.png")
            if os.path.exists(img_gt_path):
                result_redistort['redistort_rgb_gt'] = cv2.cvtColor(
                    cv2.imread(img_gt_path), cv2.COLOR_BGR2RGB
                )
            else:
                result_redistort['redistort_rgb_gt'] = None

            # redistort images
            for k, v in target_vis.items():
                if v in result:
                    result[v] = torch.clamp(result[v] * 255, 0, 255).permute(2, 0, 1)
                    result[v] = result[v].to(torch.uint8)
                    result_redistort[k] = simulator.redistort_gpu(cam_name, result[v])
                    # convert to numpy
                    result_redistort[k] = (result_redistort[k].permute(1, 2, 0).cpu().numpy()) 
                else:
                    result_redistort[k] = None

            # fill in empty images
            for k in result_redistort:
                if result_redistort[k] is None:
                    result_redistort[k] = np.zeros(result_redistort['redistort_rgb'].shape, dtype=np.uint8)

            image_name = timestamp
            visualizer.visualize_redistort(result_redistort, cam_name, image_name)
            if idx % 10 == 0:
                print(f"Rendering {cam_name} {idx+1}/{len(rendered_timestamps)} done", flush=True)
    # visualizer.save_video_ground(fps=fps)
    if save_video:
        visualizer.save_video_merged(mode=name, fps=fps, save_merged=full_mode)


def render_evaluate(
        simulator, rendered_timestamps, rendered_cameras, egoposes_shifted, fps=1, name='redistort', save_path='', argmode = "evaluate"
    ):
    from scripts.evaluate_model import MetricBase, PSNRMetric, process_metric_calculation
    if argmode == "render_evaluate":
        visualizer = XpengVisualizer(save_path)
    target_vis = {
        'redistort_rgb': 'rgb', 
        'redistort_rgb_background': 'Background_rgb', 
        'redistort_rgb_ground': 'Ground_rgb', 
        'redistort_rgb_object': 'Dynamic_rgb'
    }
    metrics = []
    metrics.append(PSNRMetric())

    for idx, timestamp in enumerate(rendered_timestamps):
        for cam_id in rendered_cameras:
            ego_idx = simulator.timestamps_origin.index(timestamp)
            ego_pose_shifted = egoposes_shifted[ego_idx]
            ego_pose_world = simulator.anchor_pose @ ego_pose_shifted
            cam_name = simulator._label2camera[cam_id]
            result, ret_cam_name = simulator.render(cam_name, int(timestamp), ego_pose_world.astype(np.float32))
            assert(ret_cam_name == cam_name)
            result_redistort = dict()

            # read ground truth image if exists
            dataset_dir = os.path.join(simulator.cfg.data.data_root, simulator.cfg.data.scene_idx)
            img_gt_path = os.path.join(dataset_dir, "images_origin", f"{cam_name}/{timestamp}.png")
            if os.path.exists(img_gt_path):
                result_redistort['redistort_rgb_gt'] = cv2.cvtColor(
                    cv2.imread(img_gt_path), cv2.COLOR_BGR2RGB
                )
            else:
                result_redistort['redistort_rgb_gt'] = None

            # redistort images
            for k, v in target_vis.items():
                if v in result:
                    result[v] = torch.clamp(result[v] * 255, 0, 255).permute(2, 0, 1)
                    result[v] = result[v].to(torch.uint8)
                    result_redistort[k] = simulator.redistort_gpu(cam_name, result[v])
                    # convert to numpy
                    result_redistort[k] = (result_redistort[k].permute(1, 2, 0).cpu().numpy()) 
                else:
                    result_redistort[k] = None

            # fill in empty images
            for k in result_redistort:
                if result_redistort[k] is None:
                    result_redistort[k] = np.zeros(result_redistort['redistort_rgb'].shape, dtype=np.uint8)
            if argmode == "render_evaluate":
                image_name = timestamp
                visualizer.visualize_redistort(result_redistort, cam_name, image_name)
            print(f"Rendering {cam_name} {idx+1}/{len(rendered_timestamps)} done", flush=True)
            if result_redistort['redistort_rgb_gt'] is not None and name == "origin":
                for metric in metrics:
                    if not isinstance(metric, MetricBase):
                        raise TypeError("metric must be an instance of MetricBase")
                    process_metric_calculation(simulator, timestamp, cam_name, result_redistort, metric)
    if argmode == "render_evaluate":
        visualizer.save_video_merged(mode=name, fps=fps)
    # save result
    for metric in metrics:
        metric_save_path = os.path.join(save_path, f"{metric.name()}_results")
        metric.save_result(metric_save_path)
        print(f"{metric.name().upper()} results saved to {metric_save_path}")


def render_lane_change(simulator, render_out_path, shift_distance=3.5):
    stride = 2
    fps = 10 / stride
    rendered_timestamps = simulator.timestamps_origin[::stride]
    rendered_cameras = simulator.cameras

    egoposes_shifted = get_lateral_shifted_egoposes(
        simulator.egoposes_anchored_origin, 
        shift_distance=shift_distance  ### positive: shift left, negative: shift right
    )
    render_sim(simulator, rendered_timestamps, rendered_cameras, egoposes_shifted, name="shift_"+str(shift_distance), save_path=render_out_path, fps=fps)


def render_sine_waved_lane_change(simulator, render_out_path):
    stride = 2
    fps = 10 / stride
    rendered_timestamps = simulator.timestamps_origin[::stride]
    rendered_cameras = simulator.cameras

    egoposes_shifted = get_lateral_sin_waved_egoposes(
        simulator.egoposes_anchored_origin, 
        amplitude=3.5
    )
    render_sim(simulator, rendered_timestamps, rendered_cameras, egoposes_shifted, 
        name="sin_wave", fps=fps, save_path=render_out_path, full_mode=False)


def render_origin(simulator, render_out_path, mode="render"):
    stride = 2
    fps = 10 / stride
    rendered_timestamps = simulator.timestamps_origin[::stride]
    rendered_cameras = simulator.cameras
    egoposes_shifted = simulator.egoposes_anchored_origin
    if mode == "render" :
        render_sim(simulator, rendered_timestamps, rendered_cameras, egoposes_shifted, name="origin", fps=fps, save_path=render_out_path)
    elif mode == "evaluate" or mode == "render_evaluate":
        render_evaluate(simulator, rendered_timestamps, rendered_cameras, egoposes_shifted, name="origin", fps=fps, save_path=render_out_path, argmode = mode)
    elif mode == "render_hil":
        simulator.gaussian.precompute_gaussians()
        render_sim(simulator, rendered_timestamps, rendered_cameras, egoposes_shifted, name="origin", fps=fps, save_path=render_out_path, hil_mode=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser("3DGS Render Sim")
    parser.add_argument("--config", required=True, type=str, default="", help="reconic trained result config")
    parser.add_argument("--save_path", required=True, type=str, default="", help="reconic render result path")
    parser.add_argument("--mode", type=str, default="render", help="render mode")
    parser.add_argument("--sim", action='store_true', default=False, help="use cp simulation")
    parser.add_argument("--iter", type=int, default=None, help="iter")
    parser.add_argument("--batch", action='store_true', default=False, help="use batch mode")
    args = parser.parse_args()

    simulator = ReconicSimulator(args.config, cp_simulation=args.sim, iter=args.iter, init_from_feedforward=False)
    t1 = time.time()
    if args.mode == "render" or args.mode == "render_evaluate" or args.mode == "render_hil" or args.mode == "novel":
        # 打开能看到各个模型的 video，关闭则看不到
        simulator.gaussian.render_cfg["render_each_class"] = True

        if not args.sim:
            render_origin(simulator, args.save_path, args.mode)
            # render_sine_waved_lane_change(simulator, args.save_path)
            # render_lane_change(simulator, args.save_path, 3.0)
            # render_lane_change(simulator, args.save_path, -3.0)
        else:
            render_sim_origin(simulator, args.save_path, args.mode, args.batch)
    elif args.mode == "profile":
        simulator.gaussian.render_cfg["render_each_class"] = False
        slices = simulator.timestamps_origin[::5]
        render_profile(simulator, slices, simulator.egoposes_anchored_origin, args.save_path)
    elif args.mode == "evaluate":
        simulator.gaussian.render_cfg["render_each_class"] = True
        render_origin(simulator, args.save_path, args.mode)
    t2 = time.time()
    print(f"Time cost: {t2 - t1} seconds")