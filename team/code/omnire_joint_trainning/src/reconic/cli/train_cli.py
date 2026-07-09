import argparse
import os

from omegaconf import OmegaConf

from reconic.training_loop import GenerativeReconTrainingLoop, ReconTrainingLoop, XpengTrainingLoop


def train(args):
    if args.load_from:
        assert args.config_file is None, "config_file is not needed when resume training"
        args.config_file = os.path.join(args.output_root, args.project, args.run_name, "config.yaml")

    cfg = OmegaConf.load(args.config_file)
    if cfg.get("joint_training_cfg", None) is not None:
        trainer = GenerativeReconTrainingLoop(args)
    elif cfg.get("xpeng_trainer", None) is not None:
        trainer = XpengTrainingLoop(args)
    else:
        trainer = ReconTrainingLoop(args)
    trainer.train()


def main():
    parser = argparse.ArgumentParser("Train Gaussian Splatting for a single scene")
    parser.add_argument("--config_file", help="path to config file", type=str)
    parser.add_argument("--resume", action="store_true", help="resume training")
    parser.add_argument("--load_from", default=None, help="path to checkpoint to load from", type=str)
    parser.add_argument(
        "--output_root",
        default="./work_dirs/",
        help="path to save checkpoints and logs",
        type=str,
    )

    # eval
    parser.add_argument(
        "--render_video_postfix",
        type=str,
        default=None,
        help="an optional postfix for video",
    )

    # wandb logging part
    parser.add_argument("--enable_wandb", action="store_true", help="enable wandb logging")
    parser.add_argument("--entity", default="ziyc", type=str, help="wandb entity name")
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

    # viewer
    parser.add_argument("--enable_viewer", action="store_true", help="enable viewer")
    parser.add_argument("--viewer_port", type=int, default=8080, help="viewer port")

    # misc
    parser.add_argument(
        "opts",
        help="Modify config options using the command-line",
        default=None,
        nargs=argparse.REMAINDER,
    )

    args = parser.parse_args()
    train(args)


if __name__ == "__main__":
    main()
