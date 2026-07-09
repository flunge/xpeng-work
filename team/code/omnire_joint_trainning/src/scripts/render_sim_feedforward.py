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
from scripts.render_sim import render_origin, render_sine_waved_lane_change


if __name__ == "__main__":
    parser = argparse.ArgumentParser("FeedForward Gaussian Splatting")
    parser.add_argument("--config_file", help="path to config file", type=str)
    parser.add_argument("--resume", action="store_true", help="resume training")
    parser.add_argument("--load_from", default=None, help="path to checkpoint to load from", type=str)
    parser.add_argument("--mode", type=str, default="render", help="render mode")
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

    # unused parameters 
    parser.add_argument("--enable_wandb", action="store_true", help="enable wandb logging")
    parser.add_argument("--entity", default="ziyc", type=str, help="wandb entity name")
    parser.add_argument("--enable_viewer", action="store_true", help="enable viewer")
    parser.add_argument("--viewer_port", type=int, default=8080, help="viewer port")
    parser.add_argument("opts", default=None, nargs=argparse.REMAINDER)

    args = parser.parse_args()
    simulator = ReconicSimulator(args, cp_simulation=False, iter=None, init_from_feedforward=True)

    save_path = os.path.join(args.output_root, args.project, args.run_name, "simulator_render")

    simulator.gaussian.render_cfg["render_each_class"] = True
    render_origin(simulator, save_path, args.mode)
    if args.mode != "render_hil":
        render_sine_waved_lane_change(simulator, save_path)