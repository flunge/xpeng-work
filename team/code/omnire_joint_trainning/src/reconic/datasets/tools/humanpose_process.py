import argparse
import logging
import os
from typing import Callable, List

import joblib
import numpy as np

from .extract_smpl import run_4DHumans
from .postprocess import match_and_postprocess

logger = logging.getLogger()


def extract_humanpose(
    scene_dir,
    projection_fn: Callable,
    camera_list: List[int],
    save_temp: bool = True,
    verbose: bool = False,
    fps: int = 12,
):
    """Extract human pose from the waymo dataset

    Args:
        scene_dir: str, path to the scene directory
        save_temp: bool, whether to save the intermediate results
        verbose: bool, whether to visualize debug images
        fps: int, FPS for the visualization video
    """
    # project human boxes to 2D image space
    GTTracks_meta = projection_fn(
        scene_dir,
        camera_list=camera_list,
        save_temp=save_temp,
        verbose=verbose,
        narrow_width_ratio=0.2,
        fps=fps,
    )

    # run 4DHuman to get predicted human tracks with SMPL parameters
    PredTracks_meta = run_4DHumans(
        scene_dir,
        camera_list=camera_list,
        save_temp=save_temp,
        verbose=verbose,
        fps=fps,
    )

    # match the predicted tracks with the ground truth tracks
    smpl_meta = match_and_postprocess(
        scene_dir,
        camera_list=camera_list,
        GTTracksDict=GTTracks_meta,
        PredTracksDict=PredTracks_meta,
        save_temp=save_temp,
        verbose=verbose,
        fps=fps,
    )

    joblib.dump(smpl_meta, os.path.join(scene_dir, "humanpose", "smpl.pkl"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Data converter arg parser")
    parser.add_argument("--data_dir", type=str, required=True, help="root path of waymo dataset")
    parser.add_argument("--dataset", type=str, default="waymo", help="dataset name")
    parser.add_argument(
        "--save_temp",
        action="store_true",
        help="Whether to save the intermediate results",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Whether to visualize the intermediate results",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=12,
        help="FPS for the visualization video if verbose is True",
    )
    args = parser.parse_args()

    if args.dataset == "waymo":
        from ..waymo.waymo_human_utils import CAMERA_LIST, project_human_boxes
    elif args.dataset == "pandaset":
        from ..pandaset.pandaset_human_utils import CAMERA_LIST, project_human_boxes
    elif args.dataset == "argoverse":
        from ..argoverse.argoverse_human_utils import CAMERA_LIST, project_human_boxes
    elif args.dataset == "nuscenes":
        from ..nuscenes.nuscenes_human_utils import CAMERA_LIST, project_human_boxes
    elif args.dataset == "kitti":
        from ..kitti.kitti_human_utils import CAMERA_LIST, project_human_boxes
    elif args.dataset == "nuplan":
        from ..nuplan.nuplan_human_utils import CAMERA_LIST, project_human_boxes
    elif args.dataset == "xpeng":
        from ..xpeng.xpeng_human_utils import CAMERA_LIST, project_human_boxes
    else:
        raise ValueError(
            f"Unknown dataset {args.dataset}, please choose from waymo, pandaset, argoverse, nuscenes, kitti, nuplan"
        )
    
    scene_dir = args.data_dir
    extract_humanpose(
        scene_dir=scene_dir,
        projection_fn=project_human_boxes,
        camera_list=CAMERA_LIST,
        save_temp=args.save_temp,
        verbose=args.verbose,
        fps=args.fps,
    )
    logger.info(f"Finished processing scene {scene_dir}")
