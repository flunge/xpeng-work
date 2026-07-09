import argparse
import os, sys
import numpy as np

 
# import from parent directory
current_dir = os.path.dirname(__file__) 
reconic_path = os.path.abspath(os.path.join(current_dir, ".."))
print(f"import reconic_path {reconic_path}")
# omnire_joint_trainning/src/scripts/render_hil.py
sim_interface_path = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
print(f"import sim_interface_path {sim_interface_path}")
sys.path.extend([reconic_path, sim_interface_path])

from reconic.simulator.reconic_simulator import ReconicSimulator


def render_hil(
        simulator, rendered_timestamps, egoposes_shifted, 
    ):
    simulator.gaussian.precompute_gaussians()
    
    for idx, timestamp in enumerate(rendered_timestamps):
        ego_idx = simulator.timestamps_origin.index(timestamp)
        ego_pose_shifted = egoposes_shifted[ego_idx]
        ego_pose_world = simulator.get_anchor_pose() @ ego_pose_shifted
        results = simulator.simulate_one_frame_stream(timestamp, ego_pose_world)
        print(f"[INFO] idx {idx} done")
    print(f"[INFO] timings: {np.mean(simulator.timings, axis=0)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser("3DGS Render HIL")
    parser.add_argument("--config", required=True, type=str, default="", help="reconic trained result config")
    parser.add_argument("--iter", type=int, default=None, help="iter")
    
    args = parser.parse_args()

    simulator = ReconicSimulator(args.config, cp_simulation=False, iter=args.iter)
    simulator.gaussian.render_cfg["render_each_class"] = False
    slices = simulator.timestamps_origin[::5]
    render_hil(simulator, slices, simulator.egoposes_anchored_origin)
