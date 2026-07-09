import argparse
import logging
import os
import time

import torch
from omegaconf import OmegaConf

from reconic.utils.eval import do_evaluation
from reconic.utils.misc import import_str

logger = logging.getLogger()
current_time = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())


def eval(args):
    log_dir = os.path.dirname(args.load_from)
    cfg = OmegaConf.load(os.path.join(log_dir, "config.yaml"))
    cfg = OmegaConf.merge(cfg, OmegaConf.from_cli(args.opts))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    args.enable_wandb = False

    # build dataset
    dataset = import_str(cfg.data.type)(
        project_dir=cfg.project_dir,
        data_cfg=cfg.data,
    )

    # setup trainer
    recon_trainer = import_str(cfg.recon_trainer.type)(
        **cfg.recon_trainer,
        num_timesteps=dataset.num_img_timesteps,
        model_config=cfg.model,
        num_train_images=len(dataset.train_image_set),
        num_full_images=len(dataset.full_image_set),
        test_set_indices=dataset.test_timesteps,
        scene_aabb=dataset.get_aabb().reshape(2, 3),
        device=device,
    )

    # Resume from checkpoint
    recon_trainer.resume_from_checkpoint(ckpt_path=args.load_from, load_only_model=True)
    logger.info(f"Loading model from {args.load_from}, starting at step {recon_trainer.step}")

    if args.enable_viewer:
        # a simple viewer for background visualization
        recon_trainer.init_viewer(port=args.viewer_port)

    # define render keys
    render_keys = [
        "gt_rgbs",
        "rgbs",
        "Background_rgbs",
        "Ground_rgbs",
        "Dynamic_rgbs",
        # "RigidNodes_rgbs",
        # "DeformableNodes_rgbs",
        # "SMPLNodes_rgbs",
        # "depths",
        # "Background_depths",
        # "Ground_depths",
        # "RigidNodes_depths",
        # "DeformableNodes_depths",
        # "SMPLNodes_depths",
        # "mask"
    ]
    if cfg.render.vis_lidar:
        render_keys.insert(0, "lidar_on_images")
    if cfg.render.vis_sky:
        render_keys += ["rgb_sky_blend", "rgb_sky"]
    if cfg.render.vis_error:
        render_keys.insert(render_keys.index("rgbs") + 1, "rgb_error_maps")

    if args.save_catted_videos:
        cfg.logging.save_seperate_video = False

    for folder in ["videos_eval", "metrics_eval"]:
        os.makedirs(os.path.join(log_dir, folder), exist_ok=True)
    do_evaluation(
        step=recon_trainer.step,
        cfg=cfg,
        trainer=recon_trainer,
        dataset=dataset,
        render_keys=render_keys,
        post_fix="_eval",
    )

    if args.enable_viewer:
        print("Viewer running... Ctrl+C to exit.")
        time.sleep(1000000)


def main():
    parser = argparse.ArgumentParser("Train Gaussian Splatting for a single scene")
    # eval
    parser.add_argument("--load_from", default=None, help="path to checkpoint to load from", type=str, required=True)
    parser.add_argument("--save_catted_videos", type=bool, default=False, help="visualize lidar on image")

    # viewer
    parser.add_argument("--enable_viewer", action="store_true", help="enable viewer")
    parser.add_argument("--viewer_port", type=int, default=8080, help="viewer port")

    # misc
    parser.add_argument(
        "opts", help="Modify config options using the command-line", default=None, nargs=argparse.REMAINDER
    )

    args = parser.parse_args()
    eval(args)


if __name__ == "__main__":
    main()
