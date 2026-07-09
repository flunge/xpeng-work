import os

import numpy as np
import cv2
import argparse
import yaml
import logging

from .utils.tools import plot_keypoints

from .DataLoader import create_dataloader
from .Detectors import create_detector
from .Matchers import create_matcher
from .VO.VisualOdometry import VisualOdometry, AbosluteScaleComputer

import torch
import random

def keypoints_plot(img, vo, last=None):
    if img.shape[2] == 1:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
        
    return plot_keypoints(img, vo.kptdescs["pairs"][-1]["match1"], vo.kptdescs["pairs"][-1]["score"])
    return plot_keypoints(img, vo.kptdescs["cur"]["keypoints"], vo.kptdescs["cur"]["scores"])

def keypoints_plot_imgs(img, match, score):
    if img.shape[2] == 1:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
        
    return plot_keypoints(img, match, score)

def keypoints_plot_imgs2(img, match0, match1, score):
    if img.shape[2] == 1:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
        
    return plot_keypoints(img, match1, score, last=match0)

class TrajPlotter(object):
    def __init__(self):
        self.errors = []
        self.traj = np.zeros((600, 600, 3), dtype=np.uint8)
        pass

    def update(self, est_xyz, gt_xyz):
        x, z = est_xyz[0], est_xyz[2]
        gt_x, gt_z = gt_xyz[0], gt_xyz[2]

        est = np.array([x, z]).reshape(2)
        gt = np.array([gt_x, gt_z]).reshape(2)

        error = np.linalg.norm(est - gt)

        self.errors.append(error)

        avg_error = np.mean(np.array(self.errors))

        # === drawer ==================================
        # each point
        draw_x, draw_y = int(x) + 290, int(z) + 90
        true_x, true_y = int(gt_x) + 290, int(gt_z) + 90

        # draw trajectory
        cv2.circle(self.traj, (draw_x, draw_y), 1, (0, 255, 0), 1)
        cv2.circle(self.traj, (true_x, true_y), 1, (0, 0, 255), 2)
        cv2.rectangle(self.traj, (10, 20), (600, 80), (0, 0, 0), -1)

        # draw text
        text = "[AvgError] %2.4fm" % (avg_error)
        cv2.putText(self.traj, text, (20, 40),
                    cv2.FONT_HERSHEY_PLAIN, 1, (255, 255, 255), 1, 8)

        return self.traj


def run_origin(args):
    with open(args.config, 'r') as f:
        config = yaml.load(f, Loader=yaml.FullLoader)

    # create dataloader
    loader = create_dataloader(config["dataset"])
    # create detector
    detector = create_detector(config["detector"])
    # create matcher
    matcher = create_matcher(config["matcher"])

    absscale = AbosluteScaleComputer()
    traj_plotter = TrajPlotter()

    # log
    fname = args.config.split('/')[-1].split('.')[0]
    log_fopen = open("results/" + fname + ".txt", mode='a')

    vo = VisualOdometry(detector, matcher, loader.cam)
    for i, img in enumerate(loader):
        # gt_pose = loader.get_cur_pose()
        R, t = vo.update(img, 5)

        # === log writer ==============================
        # print(i, t[0, 0], t[1, 0], t[2, 0], gt_pose[0, 3], gt_pose[1, 3], gt_pose[2, 3], file=log_fopen)

        # === drawer ==================================
        img1 = keypoints_plot(img, vo)
        img2 = traj_plotter.update(-t, -t)

        # cv2.imshow("keypoints", img1)
        # cv2.imshow("trajectory", img2)
        # if cv2.waitKey(10) == 27:
        #     break

    cv2.imwrite("results/" + fname + '.png', img2)
    # Save the resulting keypoints and matches
    result_path = os.path.join("results", fname + "_keypoints_matches.npy")
    keypoints = np.array(vo.kptdescs["cur"]["keypoints"])
    matches = np.array(vo.matches)
    scores = np.array(vo.kptdescs["cur"]["scores"])
    combined = np.hstack((keypoints, matches, scores.reshape(-1, 1)))
    with open(result_path, "wb") as f:
        np.save(f, combined)

def run(args):
    with open(args.config, 'r') as f:
        config = yaml.load(f, yaml.Loader)
    # config["dataset"]["sequence"] = args.sequence
    # create dataloader
    loader = create_dataloader(config["dataset"])
    # create detector
    detector = create_detector(config["detector"])
    # create matcher
    matcher = create_matcher(config["matcher"])

    absscale = AbosluteScaleComputer()
    traj_plotter = TrajPlotter()

    # log
    fname = args.config.split('/')[-1].split('.')[0]
    log_fopen = open("results/" + fname + ".txt", mode='w')

    vo = VisualOdometry(detector, matcher, loader.cam)
    imgs = []
    print("loader length: ", len(loader))
    for i, img in enumerate(loader):
        imgs.append(img)
        # gt_pose = loader.get_cur_pose()
        R, t = vo.update(img, 5)

        # # === log writer ==============================
        # print(i, t[0, 0], t[1, 0], t[2, 0], gt_pose[0, 3], gt_pose[1, 3], gt_pose[2, 3], file=log_fopen)
        # print(i, t[0, 0], t[1, 0], t[2, 0])

        # # === drawer ==================================
        # if i > 0:
        #     img1 = keypoints_plot(img, vo)
        #     img2 = traj_plotter.update(-t, -t)

            # cv2.imshow("keypoints", img1)
            # cv2.imshow("trajectory", img2)
            # if cv2.waitKey(10) == 27:
            #     break
    output_path = os.path.join(config["dataset"]["root_path"], "superpoint-superglue.npy")
    with open(output_path, "wb") as f:
        for i, pair in enumerate(vo.kptdescs["pairs"]):
            np.save(f, np.column_stack((pair["match0"], pair["match1"], pair["score"])))

    # for i, pair in enumerate(vo.kptdescs["pairs"]):
    #     img1 = keypoints_plot_imgs(imgs[i], pair["match0"], pair["score"])
    #     cv2.imshow("keypoints", img1)
    #     cv2.waitKey(0)
    #     img2 = keypoints_plot_imgs(imgs[i+1], pair["match0"], pair["match1"], pair["score"])
    #     cv2.imshow("keypoints", img2)
    #     cv2.waitKey(0)
    #     if cv2.waitKey(10) == 27:
    #         break


def run_superpoint_superglue(data_root, model_path="/workspace/group_share/adc-sim/users/zf/optimization_models", detector_config=None, matcher_config=None):
    ##### fix seed (zf) #####
    # seed = 0
    # np.random.seed(seed)
    # random.seed(seed)
    # torch.manual_seed(seed)
    # torch.cuda.manual_seed(seed)
    # torch.backends.cudnn.deterministic = True  # 确保 CuDNN 的确定性
    # torch.backends.cudnn.benchmark = False     # 禁用 CuDNN 性能优化以保证确定性
    #########################

    if detector_config is None:
        detector_config = {
            "name": "SuperPointDetector",
            "descriptor_dim": 256,
            "nms_radius": 4,
            "keypoint_threshold": 0.005,
            "max_keypoints": -1,
            "remove_borders": 4,
            "cuda": 1
        }
    
    if matcher_config is None:
        matcher_config = {
            "name": "SuperGlueMatcher",
            "descriptor_dim": 256,
            "weights": "outdoor",
            "sinkhorn_iterations": 100,
            "match_threshold": 0.2,
            "cuda": 1,
            "model_path": model_path
        }
    
    dataset_config = {
        "name": "KITTILoader",
        "root_path": data_root,
        "start": 0
    }
    
    loader = create_dataloader(dataset_config)
    detector = create_detector(detector_config)
    matcher = create_matcher(matcher_config)

    vo = VisualOdometry(detector, matcher, loader.cam)
    for i, img in enumerate(loader):
        R, t = vo.update(img, 5)

    output_path = os.path.join(data_root, "superpoint-superglue.npy")
    with open(output_path, "wb") as f:
        for i, pair in enumerate(vo.kptdescs["pairs"]):
            np.save(f, np.column_stack((pair["match0"], pair["match1"], pair["score"])))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='python_vo')
    parser.add_argument('--config', type=str, default='params/inf_superpoint_supergluematch.yaml',
                        help='config file')
    parser.add_argument('--logging', type=str, default='INFO',
                        help='logging level: NOTSET, DEBUG, INFO, WARNING, ERROR, CRITICAL')

    args = parser.parse_args()

    logging.basicConfig(level=logging._nameToLevel[args.logging])

    run(args)
