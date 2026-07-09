import argparse
import os, sys

 
# import from parent directory
current_dir = os.path.dirname(__file__) 
reconic_path = os.path.abspath(os.path.join(current_dir, ".."))
print(f"import reconic_path {reconic_path}")
# omnire_joint_trainning/src/scripts/render_sim_feedforward.py
sim_interface_path = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
print(f"import sim_interface_path {sim_interface_path}")
sys.path.extend([reconic_path, sim_interface_path])

from reconic.simulator.reconic_simulator import ReconicSimulator
from scripts.render_sim import render_sim_origin, render_sine_waved_lane_change


if __name__ == "__main__":
    parser = argparse.ArgumentParser("FeedForward Gaussian Splatting")
    parser.add_argument("--config_file", help="path to config file", type=str)
    parser.add_argument(
        "--output_root",
        default="./work_dirs/",
        help="path to save checkpoints and logs",
        type=str,
    )
    parser.add_argument(
        "--project",
        default="drivestudio",
        type=str,
        help="wandb project name, also used to enhance log_dir",
    )
    parser.add_argument(
        "--run_name",
        default="omnire",
        type=str,
        help="wandb run name, also used to enhance log_dir",
    )

    args = parser.parse_args()
    simulator = ReconicSimulator(args.config_file, cp_simulation=True, init_from_fastmode=True)
    
    save_path = os.path.join(args.output_root, args.project, args.run_name, "simulator_render")
    
    simulator.gaussian.render_cfg["render_each_class"] = True
    render_sim_origin(simulator, save_path, "render")

    simulator = ReconicSimulator(args.config_file, cp_simulation=False, init_from_fastmode=True)
    render_sine_waved_lane_change(simulator, save_path)