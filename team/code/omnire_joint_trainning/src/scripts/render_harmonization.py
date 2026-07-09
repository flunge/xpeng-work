import os
import sys
import torch
import logging
import numpy as np
import argparse

# import from parent directory
current_dir = os.path.dirname(__file__) 
reconic_path = os.path.abspath(os.path.join(current_dir, ".."))
print(f"import reconic_path {reconic_path}")
sim_interface_path = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
print(f"import sim_interface_path {sim_interface_path}")
sys.path.extend([reconic_path, sim_interface_path])
from sim_interface.visualizers.xpeng_visualizer import XpengVisualizer
from reconic.simulator.reconic_simulator import ReconicSimulator

try:
    repo_root = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
    models_path = os.path.join(repo_root, "models")
    if models_path not in sys.path:
        sys.path.insert(0, models_path)
    from dynamic_assets.DCCF.scripts.cam_image_harmonize import conduct_dccf_harmonization, read_image_from_dccf_rst
except ImportError:
    logging.warning("[WARNING] dynamic_assets.DCCF not found, harmonization functions will not be available.")

logging.basicConfig(level=logging.INFO)

def render_harmonization(
        simulator, rendered_timestamps, rendered_cameras, egoposes_shifted, 
        fps=1, name='redistort_harmonization', save_path=''
    ):
    visualizer = XpengVisualizer(save_path)
    target_vis = {
        'redistort_rgb': 'rgb', 
        'redistort_rgb_mask' : 'DynamicAssets_masked_rgb',
        'redistort_rgb_harmonized' : 'rgb'
    }

    for idx, timestamp in enumerate(rendered_timestamps):
        for cam_id in rendered_cameras:
            ego_idx = simulator.timestamps_origin.index(timestamp)
            ego_pose_shifted = egoposes_shifted[ego_idx]
            ego_pose_world = simulator.anchor_pose @ ego_pose_shifted
            cam_name = simulator._label2camera[cam_id]
            result, ret_cam_name = simulator.render(cam_name, int(timestamp), ego_pose_world.astype(np.float32))
            assert(ret_cam_name == cam_name)
            result_redistort = dict()

            # redistort images
            for k, v in target_vis.items():
                if v in result:
                    if result[v].shape[2] == 3:
                        result[v] = torch.clamp(result[v] * 255, 0, 255).permute(2, 0, 1)
                    elif result[v].shape[0] == 3:
                        result[v] = torch.clamp(result[v] * 255, 0, 255)
                    else:
                        raise ValueError(f"Unexpected shape for {v}: {result[v].shape}")

                    result[v] = result[v].to(torch.uint8)
                    logging.info(f"result_redistort: cam_name: {cam_name}, k: {k}, v: {v}, result[v] shape: {result[v].shape}, dtype: {result[v].dtype}")
                    result_redistort[k] = simulator.redistort_gpu(cam_name, result[v])
                    # convert to numpy
                    result_redistort[k] = (result_redistort[k].permute(1, 2, 0).cpu().numpy()) 
                else:
                    result_redistort[k] = None

            # fill in empty images
            for k in result_redistort:
                if result_redistort[k] is None:
                    result_redistort[k] = np.zeros(result_redistort['redistort_rgb'].shape, dtype=np.uint8)
            
            vis_base_dir = conduct_dccf_harmonization(
                model_path=simulator.model_path,
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

            image_name = timestamp
            visualizer.visualize_redistort_harmonized(result_redistort, cam_name, image_name)
            print(f"Rendering {cam_name} {idx+1}/{len(rendered_timestamps)} done", flush=True)

    visualizer.save_video_harmonized(mode=name, fps=fps)

if __name__ == "__main__":
    parser = argparse.ArgumentParser("3DGS Render Sim")
    parser.add_argument("--config", required=True, type=str, default="", help="reconic trained result config")
    parser.add_argument("--save_path", required=True, type=str, default="", help="reconic render result path")
    args = parser.parse_args()
    simulator = ReconicSimulator(args.config, cp_simulation=False, iter=None)
    simulator.gaussian.render_cfg["render_each_class"] = True
    
    render_harmonization(
        simulator, 
        simulator.timestamps_origin, 
        simulator.cameras, 
        simulator.egoposes_anchored_origin, 
        name="harmonization", 
        fps=12, 
        save_path=args.save_path
    )