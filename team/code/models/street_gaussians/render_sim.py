import os, sys
import json
import cv2
import numpy as np
import torchvision
import torch
from collections import defaultdict
from lib.config import cfg
from lib.utils.general_utils import safe_state
from lib.utils.img_utils import visualize_depth_numpy
from lib.visualizers.xpeng_visualizer import XpengVisualizer
from sim_bridge.simulator import StreetGaussianSimulator
from sim_interface.utils import find_closest_msg
from scipy.spatial.transform import Rotation as R
import lib.utils.plt_display_utils as plt_display_utils

try:
    from dynamic_assets.DCCF.scripts.cam_image_harmonize import conduct_dccf_harmonization, read_image_from_dccf_rst
except ImportError:
    print("[WARNING] dynamic_assets.DCCF not found, harmonization functions will not be available.")

# import from parent directory
current_dir = os.path.dirname(__file__) 
root_path = os.path.abspath(os.path.join(current_dir, "..", ".."))
print(f"import relative_path {root_path}")
sys.path.extend([root_path])
from sim_interface.utils import get_lateral_shifted_egoposes, get_lateral_sin_waved_egoposes


def render_profile(
        simulator, rendered_timestamps, egoposes_shifted, 
    ):
    profile_dict = defaultdict(list)
    for idx, timestamp in enumerate(rendered_timestamps):
        ego_idx = simulator.timestamps_origin.index(timestamp)
        ego_pose_shifted = egoposes_shifted[ego_idx]
        ego_pose_world = simulator.get_anchor_pose() @ ego_pose_shifted
        simulator.simulate_one_frame(timestamp, ego_pose_world, profile_dict)

    for cam in profile_dict:
        time_costs = np.array(profile_dict[cam][1:])
        img_size = simulator.camera_wh[cam]
        print(f"[SUMMARY] Camera {cam} with size {img_size} render/redistort costs: {time_costs.mean(axis=0)} ms")


def render_sim(
        simulator, 
        rendered_timestamps, 
        rendered_cameras, 
        egoposes_shifted, 
        fps=1, 
        name='redistort', 
        is_scenario_edit = False
    ):
    """
    egoposes_shifted: anchor egopose (no cp simulation) or world egopose (cp simulation)
    """
    save_dir = os.path.join(
        cfg.model_path, 'origin', "iter_{}".format(max(cfg.train.checkpoint_iterations))
    )
    visualizer = XpengVisualizer(save_dir)
    target_vis = {
        'redistort_rgb': 'rgb', 
        'redistort_rgb_background': 'rgb_background', 
        'redistort_rgb_ground': 'rgb_ground', 
        'redistort_rgb_object': 'rgb_object'
    }

    is_trigger_harmony = cfg.render.get("trigger_harmonization", False)
    if is_trigger_harmony:
        target_vis['redistort_rgb_mask'] = 'rgb_mask'
        target_vis['redistort_rgb_harmonized'] = 'rgb'

    for idx, timestamp in enumerate(rendered_timestamps):
        for cam_id in rendered_cameras:
            if simulator.cp_simulation:
                ego_pose_shifted = egoposes_shifted[idx]
                result, camera = simulator.render_all(cam_id, timestamp, ego_pose_shifted)
            elif is_scenario_edit:
                ego_pose_shifted = egoposes_shifted[idx]
                ego_pose_world = simulator.get_anchor_pose() @ ego_pose_shifted
                result, camera = simulator.render_all(cam_id, timestamp, ego_pose_world)
            else:
                ego_idx = simulator.timestamps_origin.index(timestamp)
                ego_pose_shifted = egoposes_shifted[ego_idx]
                ego_pose_world = simulator.get_anchor_pose() @ ego_pose_shifted
                result, camera = simulator.render_all(cam_id, timestamp, ego_pose_world)
            cam_name = camera.meta['cam']
            result_redistort = dict()

            # read ground truth image if exists
            img_gt_path = os.path.join(cfg.source_path, "images_origin", f"{cam_name}/{timestamp}.png")
            if os.path.exists(img_gt_path):
                result_redistort['redistort_rgb_gt'] = cv2.cvtColor(
                    cv2.imread(img_gt_path), cv2.COLOR_BGR2RGB
                )
            else:
                result_redistort['redistort_rgb_gt'] = None

            # redistort images
            for k, v in target_vis.items():
                if v in result:
                    # from torch float to torch uint8
                    result[v] = torch.clamp(result[v] * 255, 0, 255)
                    result[v] = result[v].to(torch.uint8)
                    result_redistort[k] = simulator.redistort_gpu(cam_name, result[v])
                    # optionally fix the image using difix
                    if cfg.render.get("fix", False) and cam_id in cfg.fixer.cam:
                        result_redistort[k] = simulator.image_fixer.fix_image(result_redistort[k])
                        target_height = int(simulator.calib_info['new' + cam_name]['height'])
                        target_width = int(simulator.calib_info['new' + cam_name]['width'])
                        if result_redistort[k].shape[1] != target_height or result_redistort[k].shape[2] != target_width:
                            result_redistort[k] = torch.nn.functional.interpolate(
                                result_redistort[k].unsqueeze(0).float(),
                                size=(target_height, target_width), mode='bilinear', align_corners=False
                            ).squeeze(0).clamp(0, 255).to(torch.uint8)
                    # convert to numpy
                    result_redistort[k] = (result_redistort[k].permute(1, 2, 0).cpu().numpy()) 
                else:
                    result_redistort[k] = None
            
            # fill in empty images
            for k in result_redistort:
                if result_redistort[k] is None:
                    result_redistort[k] = np.zeros(result_redistort['redistort_rgb'].shape, dtype=np.uint8)

            if is_trigger_harmony:
                vis_base_dir = conduct_dccf_harmonization(
                    model_path=cfg.model_path,
                    simulator=simulator,
                    img_distort=result_redistort['redistort_rgb'],
                    dynamic_obj_mask_distort=result_redistort['redistort_rgb_mask'],
                    cam_name=cam_name,
                    image_name=str(timestamp),
                    timestamp=timestamp,
                    cam_id=cam_id 
                )

                final_img = read_image_from_dccf_rst(vis_base_dir)
                result_redistort['redistort_rgb_harmonized'] = final_img
                visualizer.visualize_redistort_harmonized(result_redistort, camera)

            visualizer.visualize_redistort(result_redistort, camera)
            print(f"Rendering {cam_name} {idx+1}/{len(rendered_timestamps)} done", flush=True)
        
    visualizer.save_video_ground(fps=fps)
    visualizer.save_video_merged(mode=name, fps=fps)

    if is_trigger_harmony:
        visualizer.save_video_harmonized(fps=fps)
        simulator.harmonization_evaluator.display_smooth_plot(saved_dir=save_dir)
    


def render_pix2pix(
        simulator, rendered_timestamps, rendered_cameras, egoposes_shifted, 
        suffix='shifted'
    ):
    num_iter = cfg.train_xpeng.iterations_ground
    output_dir_iter = os.path.join(cfg.model_path, f"pix2pix_data_{suffix}", f"iter{num_iter}")
    os.makedirs(output_dir_iter, exist_ok=True)

    for idx, timestamp in enumerate(rendered_timestamps):
        for cam_id in rendered_cameras:
            ego_idx = simulator.timestamps_origin.index(timestamp)
            ego_pose_shifted = egoposes_shifted[ego_idx]
            ego_pose_world = simulator.get_anchor_pose() @ ego_pose_shifted
            result, camera = simulator.render_all(cam_id, timestamp, ego_pose_world)
            img_name = camera.image_name
            cam_type = camera.meta["cam"]
            torchvision.utils.save_image(
                result["rgb"],
                os.path.join(output_dir_iter, f"{img_name}_{cam_type}_rgb.png"),
            )
            depth_colored = visualize_depth_numpy(result["depth"].cpu().numpy().squeeze(0))[0]
            depth_colored = depth_colored[..., [2, 1, 0]] / 255.
            depth_colored = torch.from_numpy(depth_colored).permute(2, 0, 1).float()
            torchvision.utils.save_image(
                depth_colored,
                os.path.join(output_dir_iter, f"{img_name}_{cam_type}_depth.png"),
            )
            torchvision.utils.save_image(
                result["rgb_background"],
                os.path.join(output_dir_iter, f"{img_name}_{cam_type}_background.png"),
            )
            torchvision.utils.save_image(
                result["rgb_object"],
                os.path.join(output_dir_iter, f"{img_name}_{cam_type}_object.png"),
            )
            torchvision.utils.save_image(
                (result["acc_object"] > 0.8) * 255.0,
                os.path.join(output_dir_iter, f"{img_name}_{cam_type}_objMask.png"),
            )
            torchvision.utils.save_image(
                ((1 - result["acc"]) > 0.8) * 255.0,
                os.path.join(output_dir_iter, f"{img_name}_{cam_type}_skyMask.png"),
            )
            
            print(f"Rendering pix2pix {cam_type} {idx+1}/{len(rendered_timestamps)} done", flush=True)

def render_lane_change(simulator, pix2pix=False, shift_distance=3.5):
    stride = 2 if not pix2pix else 1
    fps = 10 / stride
    rendered_timestamps = simulator.timestamps_origin[::stride]
    rendered_cameras = simulator.cameras

    egoposes_shifted = get_lateral_shifted_egoposes(
        simulator.egoposes_anchored_origin, 
        shift_distance=shift_distance  ### positive: shift left, negative: shift right
    )
    if not pix2pix:
        render_sim(simulator, rendered_timestamps, rendered_cameras, egoposes_shifted, name="redistort", fps=fps)
    else:
        render_pix2pix(simulator, rendered_timestamps, rendered_cameras, egoposes_shifted, suffix=f'shifted_{shift_distance}')

def render_sine_waved_lane_change(simulator, pix2pix=False):
    stride = 2 if not pix2pix else 1
    fps = 10 / stride
    rendered_timestamps = get_rendered_timestamps(
        cfg.data.selected_frames, stride, simulator.timestamps_origin
    )
    rendered_cameras = simulator.cameras

    egoposes_shifted = get_lateral_sin_waved_egoposes(
        simulator.egoposes_anchored_origin, 
        amplitude=3.5
    )
    render_sim(simulator, rendered_timestamps, rendered_cameras, egoposes_shifted, name="sin_wave", fps=fps)

def render_origin(simulator, pix2pix=False):
    stride = 2 if not pix2pix else 1
    fps = 10 / stride
    rendered_timestamps = get_rendered_timestamps(
        cfg.data.selected_frames, stride, simulator.timestamps_origin
    )
    rendered_cameras = simulator.cameras
    egoposes_shifted = simulator.egoposes_anchored_origin
    render_sim(simulator, rendered_timestamps, rendered_cameras, egoposes_shifted, name="origin", fps=fps)

def fill_timestamps_to_target_fps(timestamps, target_fps=12):
    filled_timestamps = []
    target_interval_ns = int(1e9 / target_fps)
    for i in range(len(timestamps) - 1):
        start_ts = timestamps[i]
        end_ts = timestamps[i + 1]
        filled_timestamps.append(start_ts)
        current_ts = start_ts + target_interval_ns
        while current_ts < end_ts:
            filled_timestamps.append(current_ts)
            current_ts += target_interval_ns
    filled_timestamps.append(timestamps[-1])
    return filled_timestamps

def interpolate_egoposes_to_timestamps(egoposes, original_timestamps, target_timestamps):
    """
    Interpolate ego poses (4x4 SE(3) matrices) to target timestamps using SLERP for rotation
    and linear interpolation for translation.

    Args:
        egoposes (np.ndarray): Shape (N, 4, 4), original ego poses.
        original_timestamps (list or np.ndarray): Shape (N,), timestamps in nanoseconds.
        target_timestamps (list or np.ndarray): Shape (M,), desired timestamps in nanoseconds.

    Returns:
        np.ndarray: Shape (M, 4, 4), interpolated ego poses.
    """
    from scipy.spatial.transform import Rotation, Slerp
    original_timestamps = np.array(original_timestamps, dtype=np.float64)  # Slerp needs float
    target_timestamps = np.array(target_timestamps, dtype=np.float64)

    if not np.all(np.diff(original_timestamps) > 0):
        raise ValueError("Original timestamps must be strictly increasing.")

    N = len(original_timestamps)
    M = len(target_timestamps)
    interpolated_poses = np.zeros((M, 4, 4))

    # Extract rotations and translations
    rotations = []
    translations = np.empty((N, 3))
    for i in range(N):
        mat = egoposes[i]
        rotations.append(Rotation.from_matrix(mat[:3, :3]))
        translations[i] = mat[:3, 3]

    # Create Slerp interpolator for rotations
    # Note: Slerp expects shape (N,) for times and (N, ...) for rotations
    rotations_array = Rotation.concatenate(rotations)  # shape (N,)
    slerp_rot = Slerp(original_timestamps, rotations_array)

    # Interpolate translations linearly (use np.interp for each axis)
    trans_x = np.interp(target_timestamps, original_timestamps, translations[:, 0])
    trans_y = np.interp(target_timestamps, original_timestamps, translations[:, 1])
    trans_z = np.interp(target_timestamps, original_timestamps, translations[:, 2])
    trans_interp = np.stack([trans_x, trans_y, trans_z], axis=1)  # (M, 3)

    # Interpolate rotations
    rot_interp = slerp_rot(target_timestamps)  # Rotation object of length M

    # Assemble final poses
    for j in range(M):
        pose = np.eye(4)
        pose[:3, :3] = rot_interp[j].as_matrix()
        pose[:3, 3] = trans_interp[j]
        interpolated_poses[j] = pose

    return interpolated_poses

def render_origin_with_target_fps(simulator, target_fps=12):
    rendered_timestamps = get_rendered_timestamps(
        cfg.data.selected_frames, 1, simulator.timestamps_origin
    )
    rendered_timestamps_after = fill_timestamps_to_target_fps(rendered_timestamps, target_fps)
    rendered_cameras = simulator.cameras
    egoposes_shifted_before = simulator.egoposes_anchored_origin
    egoposes_shifted_after = interpolate_egoposes_to_timestamps(
        egoposes_shifted_before,
        rendered_timestamps,
        rendered_timestamps_after
    )  # shape (M, 4, 4)

    render_sim(
        simulator, 
        rendered_timestamps_after, 
        rendered_cameras, 
        egoposes_shifted_after, 
        name="origin", 
        fps=target_fps, 
        is_scenario_edit=True
    )

def render_origin_cp_simulation(simulator, pix2pix=False):
    stride = 2 if not pix2pix else 1
    fps = 10 / stride
    rendered_timestamps = get_rendered_timestamps(
        cfg.data.selected_frames, stride, simulator.timestamps_origin
    )
    rendered_cameras = simulator.cameras


    with open(os.path.join(
        cfg.model_path, 'LocalPoseTopic.json')  , 'r') as f:
        localpose_json = json.load(f)
    localposes = {lp["time_stamp"]["nsec"]: lp for lp in localpose_json}
    egoposes_world = np.zeros((len(rendered_timestamps), 4, 4))
    for idx, timestamp in enumerate(rendered_timestamps):
        lp = find_closest_msg(timestamp, localposes)
        egopose = np.array(
            [
                lp["smooth_pose"]["pose"]["q"]["w"],
                lp["smooth_pose"]["pose"]["q"]["x"],
                lp["smooth_pose"]["pose"]["q"]["y"],
                lp["smooth_pose"]["pose"]["q"]["z"],
                lp["smooth_pose"]["pose"]["p"]["x"],
                lp["smooth_pose"]["pose"]["p"]["y"],
                lp["smooth_pose"]["pose"]["p"]["z"],
            ]
        )
        q = egopose[:4]
        t = egopose[4:7]
        rotation_matrix = R.from_quat([q[1], q[2], q[3], q[0]]).as_matrix()
        rotation_matrix = np.array(rotation_matrix)
        translation_matrix = np.array([t[0],t[1],t[2]])
        rig_to_world =  np.eye(4)
        rig_to_world[:3,:3] = rotation_matrix
        rig_to_world[:3,3] = translation_matrix

        egoposes_world[idx] = rig_to_world
    
    render_sim(
        simulator,
        rendered_timestamps,
        rendered_cameras,
        egoposes_world,
        name="origin_cp_simulation",
        fps=fps,
    )

def get_rendered_timestamps(select_frames, stride, timestamps_origin):
    if len(select_frames) > 0:
        rendered_timestamps = [
            timestamps_origin[i] for i in range(len(timestamps_origin)) \
                if i >= select_frames[0] and i <= select_frames[1]]
    else:
        rendered_timestamps = timestamps_origin[::stride]
    return rendered_timestamps

if __name__ == "__main__":
    if cfg.mode == "pix2pix":
        simulator = StreetGaussianSimulator(iter=50000)
        # render_origin(simulator)
        # render_sine_waved_lane_change(simulator)
        # render_lane_change(simulator)
        render_lane_change(simulator, pix2pix=True)
    elif cfg.mode == "profile":
        cfg.render.fix = False
        cfg.fixer.cam = [1, 2, 3, 4]
        simulator = StreetGaussianSimulator(cfg)
        import cProfile
        profiler = cProfile.Profile()
        profiler.enable() 
        slices = simulator.timestamps_origin[::10]
        # simulator.cameras = simulator.cameras[1:2]
        render_profile(simulator, slices, simulator.egoposes_anchored_origin)
        profiler.disable()
        profiler.dump_stats("render_profile.prof")
    elif cfg.mode == "edit":
        simulator = StreetGaussianSimulator(cfg)
        simulator.auto_edit(1.2)
        simulator.write_to_ply()
        simulator.remove_unused_files()
    elif cfg.mode == 'render_cp_simulation':
        simulator = StreetGaussianSimulator(cfg, cp_simulation=True)
        render_origin_cp_simulation(simulator)
    elif cfg.mode == 'harmonized':
        simulator = StreetGaussianSimulator(cfg, cp_simulation=False)
        render_origin_with_target_fps(simulator, target_fps=12)
    else:
        cfg.mode = "render"
        cfg.render.save_image = False
        cfg.render.fix = False
        print("Rendering " + cfg.model_path)
        safe_state(cfg.eval.quiet)

        simulator = StreetGaussianSimulator(cfg, cp_simulation=False)
        # simulator.auto_edit(1.2, opacity_threshold=0.02)
        render_origin(simulator)
        render_sine_waved_lane_change(simulator)
        # render_lane_change(simulator)
