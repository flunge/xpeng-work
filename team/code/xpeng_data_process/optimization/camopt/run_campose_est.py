import os
import time as _time
from multiprocessing import Process, Queue
from pathlib import Path
from queue import Empty as QueueEmpty

import cv2
import numpy as np
import torch
from evo.core.trajectory import PoseTrajectory3D
from evo.tools import file_interface
from scipy.spatial.transform import Rotation as R
from yacs.config import CfgNode as CN

from .dpvo.config import cfg
from .dpvo.dpvo import DPVO
from .dpvo.plot_utils import save_output_for_COLMAP, save_ply
from .dpvo.stream import image_stream, video_stream, cam0_stream
from .dpvo.utils import Timer

# Timeout for queue.get() in run_vslam, to detect dead reader subprocess
_QUEUE_GET_TIMEOUT = 120  # seconds

# Map common exit codes to human-readable signal names
_SIGNAL_NAMES = {
    -9: "SIGKILL (likely OOM Killer)",
    -11: "SIGSEGV (segmentation fault)",
    -6: "SIGABRT (aborted)",
    -15: "SIGTERM (terminated)",
    -7: "SIGBUS (bus error)",
}

SKIP = 0

def show_image(image, t=0):
    image = image.permute(1, 2, 0).cpu().numpy()
    cv2.imshow('image', image / 255.0)
    cv2.waitKey(t)

def pos_quat2SE(quat_data):
    SO = R.from_quat(quat_data[3:7]).as_matrix()
    SE = np.matrix(np.eye(4))
    SE[0:3,0:3] = np.matrix(SO)
    SE[0:3,3]   = np.matrix(quat_data[0:3]).T
    SE = np.array(SE[0:3,:]).reshape(1,12)
    return SE

def pos_quats2SEs(quat_datas):
    data_len = quat_datas.shape[0]
    SEs = np.zeros((data_len,12))
    for i_data in range(0,data_len):
        SE = pos_quat2SE(quat_datas[i_data,:])
        SEs[i_data,:] = SE
    return SEs

@torch.no_grad()
def run(cfg, network, imagedir, calib, stride=1, skip=0, viz=False, timeit=False):

    slam = None
    queue = Queue(maxsize=8)

    if os.path.isdir(imagedir):
        reader = Process(target=image_stream, args=(queue, imagedir, calib, stride, skip))
    else:
        reader = Process(target=video_stream, args=(queue, imagedir, calib, stride, skip))

    reader.start()
    print(f"[run] Reader subprocess started (pid={reader.pid}), imagedir={imagedir}")
    frame_count = 0
    t0 = _time.time()

    try:
        while 1:
            try:
                data = queue.get(timeout=_QUEUE_GET_TIMEOUT)
            except QueueEmpty:
                if not reader.is_alive():
                    elapsed = _time.time() - t0
                    sig_name = _SIGNAL_NAMES.get(reader.exitcode, "unknown")
                    raise RuntimeError(
                        f"[run][ERROR] Reader subprocess (pid={reader.pid}) died "
                        f"with exitcode={reader.exitcode} ({sig_name}) after processing "
                        f"{frame_count} frames ({elapsed:.1f}s elapsed). imagedir={imagedir}"
                    )
                print(f"[run][WARN] queue.get() timed out after {_QUEUE_GET_TIMEOUT}s, "
                      f"reader still alive (pid={reader.pid}), waiting...")
                continue

            (t, image, intrinsics) = data
            if t < 0: break

            image = torch.from_numpy(image).permute(2,0,1).cuda()
            intrinsics = torch.from_numpy(intrinsics).cuda()

            if slam is None:
                _, H, W = image.shape
                slam = DPVO(cfg, network, ht=H, wd=W, viz=viz)

            with Timer("SLAM", enabled=timeit):
                slam(t, image, intrinsics)
            frame_count += 1

    finally:
        if reader.is_alive():
            print(f"[run][WARN] Reader subprocess still alive in finally block, terminating...")
            reader.terminate()
            reader.join(timeout=10)
            if reader.is_alive():
                reader.kill()
                reader.join(timeout=5)
        else:
            reader.join(timeout=5)
        print(f"[run] Reader subprocess cleaned up "
              f"(exitcode={reader.exitcode}, {_SIGNAL_NAMES.get(reader.exitcode, 'normal' if reader.exitcode == 0 else 'error')}), "
              f"processed {frame_count} frames in {_time.time() - t0:.1f}s")

    if slam is None:
        raise RuntimeError(
            f"[run][ERROR] No frames were processed by DPVO. "
            f"Reader exitcode={reader.exitcode}, imagedir={imagedir}"
        )

    points = slam.pg.points_.cpu().numpy()[:slam.m]
    colors = slam.pg.colors_.view(-1, 3).cpu().numpy()[:slam.m]

    return slam.terminate(), (points, colors, (*intrinsics, H, W))


@torch.no_grad()
def run_vslam(user_cfg, network, clip_path, transform_name,stride=1, skip=0, viz=False, timeit=False):
    user_cfg2 = CN(user_cfg)
    cfg.merge_from_other_cfg(user_cfg2)
    slam = None
    queue = Queue(maxsize=8)

    reader = Process(target=cam0_stream, args=(queue, clip_path, transform_name, stride, skip))
    reader.start()
    print(f"[run_vslam] Reader subprocess started (pid={reader.pid}), clip_path={clip_path}")
    frame_count = 0
    t0 = _time.time()

    try:
        while 1:
            # Use timeout to avoid infinite hang if reader subprocess dies
            try:
                data = queue.get(timeout=_QUEUE_GET_TIMEOUT)
            except QueueEmpty:
                # Timeout: check if reader is still alive
                if not reader.is_alive():
                    elapsed = _time.time() - t0
                    sig_name = _SIGNAL_NAMES.get(reader.exitcode, "unknown")
                    raise RuntimeError(
                        f"[run_vslam][ERROR] Reader subprocess (pid={reader.pid}) died "
                        f"with exitcode={reader.exitcode} ({sig_name}) after processing "
                        f"{frame_count} frames ({elapsed:.1f}s elapsed). clip_path={clip_path}"
                    )
                # Reader is still alive but slow (e.g. large images), keep waiting
                print(f"[run_vslam][WARN] queue.get() timed out after {_QUEUE_GET_TIMEOUT}s, "
                      f"reader still alive (pid={reader.pid}), waiting...")
                continue

            (t, image, intrinsics, mask) = data
            if t < 0:
                break

            image = torch.from_numpy(image).permute(2,0,1).cuda()
            intrinsics = torch.from_numpy(intrinsics).cuda()
            mask = torch.from_numpy(mask).cuda()
            if slam is None:
                _, H, W = image.shape
                slam = DPVO(cfg, network, ht=H, wd=W, viz=viz)

            with Timer("SLAM", enabled=timeit):
                slam(t, image, intrinsics, mask)
            frame_count += 1

    finally:
        # Ensure reader subprocess is properly cleaned up
        if reader.is_alive():
            print(f"[run_vslam][WARN] Reader subprocess still alive in finally block, terminating...")
            reader.terminate()
            reader.join(timeout=10)
            if reader.is_alive():
                print(f"[run_vslam][ERROR] Reader subprocess didn't terminate, killing...")
                reader.kill()
                reader.join(timeout=5)
        else:
            reader.join(timeout=5)
        print(f"[run_vslam] Reader subprocess cleaned up "
              f"(exitcode={reader.exitcode}, {_SIGNAL_NAMES.get(reader.exitcode, 'normal' if reader.exitcode == 0 else 'error')}), "
              f"processed {frame_count} frames in {_time.time() - t0:.1f}s")

    if slam is None:
        raise RuntimeError(
            f"[run_vslam][ERROR] No frames were processed by DPVO. "
            f"Reader exitcode={reader.exitcode}, clip_path={clip_path}"
        )

    points = slam.pg.points_.cpu().numpy()[:slam.m]
    colors = slam.pg.colors_.view(-1, 3).cpu().numpy()[:slam.m]

    return slam.terminate(), (points, colors, (*intrinsics, H, W))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--network', type=str, default='dpvo.pth')
    parser.add_argument('--imagedir', type=str)
    parser.add_argument('--calib', type=str)
    parser.add_argument('--name', type=str, help='name your run', default='result')
    parser.add_argument('--stride', type=int, default=2)
    parser.add_argument('--skip', type=int, default=0)
    parser.add_argument('--config', default="config/default.yaml")
    parser.add_argument('--timeit', action='store_true')
    parser.add_argument('--viz', action="store_true")
    parser.add_argument('--plot', action="store_true")
    parser.add_argument('--opts', nargs='+', default=[])
    parser.add_argument('--save_ply', action="store_true")
    parser.add_argument('--save_colmap', action="store_true")
    parser.add_argument('--save_trajectory', action="store_true")
    args = parser.parse_args()

    cfg.merge_from_file(args.config)
    cfg.merge_from_list(args.opts)

    print("Running with config...")
    print(cfg)

    (poses, tstamps), (points, colors, calib) = run(cfg, args.network, args.imagedir, args.calib, args.stride, args.skip, args.viz, args.timeit)
    trajectory = PoseTrajectory3D(positions_xyz=poses[:,:3], orientations_quat_wxyz=poses[:, [6, 3, 4, 5]], timestamps=tstamps)
    
    if args.save_ply:
        save_ply(args.name, points, colors)

    if args.save_colmap:
        save_output_for_COLMAP(args.name, trajectory, points, colors, *calib)
