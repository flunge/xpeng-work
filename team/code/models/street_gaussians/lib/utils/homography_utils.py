import os
import cv2
import math
import random
import torch
import numpy as np
from scipy.spatial.transform import Rotation as R

def find_matching_points(R1, R2, K):
    ground_points = np.array([[10, 0, 0, 1],
                              [15, 0, 0, 1],
                              [20, 0, 0, 1],
                              [10, -2, 0, 1],
                              [10, 2, 0, 1],
                              [20, -2, 0, 1],
                              [20, 2, 0, 1]])
    src_points = np.matmul(R1, ground_points.T)
    src_points = np.matmul(K, src_points[:3,:]).T
    src_points = src_points / src_points[:,-1][:,None]
    dst_points = np.matmul(R2, ground_points.T)
    dst_points = np.matmul(K, dst_points[:3,:]).T
    dst_points = dst_points / dst_points[:,-1][:,None]

    H, mask = cv2.findHomography(src_points, dst_points, cv2.RANSAC, 5.0)

    return H, mask
 
def rotationMat(theta, trans, format='degree'):
    """
    Calculates Rotation Matrix given euler angles.
    :param theta: 1-by-3 list [rx, ry, rz] angle in degree
    :return:
    """
    if format == 'degree':
        theta = [i * math.pi / 180.0 for i in theta]
 
    R_x = np.array([[1, 0, 0],
                    [0, math.cos(theta[0]), -math.sin(theta[0])],
                    [0, math.sin(theta[0]), math.cos(theta[0])]
                    ])
 
    R_y = np.array([[math.cos(theta[1]), 0, math.sin(theta[1])],
                    [0, 1, 0],
                    [-math.sin(theta[1]), 0, math.cos(theta[1])]
                    ])
 
    R_z = np.array([[math.cos(theta[2]), -math.sin(theta[2]), 0],
                    [math.sin(theta[2]), math.cos(theta[2]), 0],
                    [0, 0, 1]
                    ])
    R = np.dot(R_z, np.dot(R_y, R_x))

    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = trans
    T[3, 3] = 1

    return T
 
def generate_image(viewpoint_cam, max_shift_distance, max_yaw_degree):    
  
    gt_image = viewpoint_cam.original_image.numpy()
    gt_mask  = viewpoint_cam.original_ground_mask.numpy().squeeze(0)

    c2w = viewpoint_cam.get_extrinsic()
    w2c = np.linalg.inv(c2w)

    theta = np.array([0, 0, random.uniform(-max_yaw_degree, max_yaw_degree)])
    trans = np.array([0, random.uniform(-max_shift_distance, max_shift_distance), 0])
    R = rotationMat(theta, trans)
    c2w_t = np.matmul(viewpoint_cam.ego_pose.cpu(), np.matmul(R, viewpoint_cam.extrinsic.cpu()))
    w2c_t = np.linalg.inv(c2w_t)
    K = viewpoint_cam.get_intrinsic()
    H, mask = find_matching_points(w2c, w2c_t, K)

    gt_image_numpy = np.transpose(gt_image, (1, 2, 0))
    height, width = gt_image_numpy.shape[:2]
    gt_image_warped = cv2.warpPerspective(gt_image_numpy, H, (width, height))
    gt_image_warped = np.transpose(gt_image_warped, (2, 0, 1))
    gt_image_warped = torch.from_numpy(gt_image_warped)

    gt_mask_warped = cv2.warpPerspective(gt_mask.astype(float), H, (width, height))
    gt_mask_warped = (gt_mask_warped > 0.5)
    indices = np.where(gt_mask_warped == True)
    gt_mask_warped = torch.from_numpy(gt_mask_warped).unsqueeze(0)

    return gt_image_warped, gt_mask_warped, c2w_t

def generate_image_shift(viewpoint_cam, max_shift_distance):    
  
    gt_image = viewpoint_cam.original_image.numpy()
    gt_mask  = viewpoint_cam.original_ground_mask.numpy().squeeze(0)

    c2w = viewpoint_cam.get_extrinsic()
    w2c = np.linalg.inv(c2w)

    theta = np.array([0, 0, 0])
    trans = np.array([0, random.uniform(-max_shift_distance, max_shift_distance), 0])

    R = rotationMat(theta, trans)
    c2w_t = np.matmul(viewpoint_cam.ego_pose.cpu(), np.matmul(R, viewpoint_cam.extrinsic.cpu()))
    w2c_t = np.linalg.inv(c2w_t)
    K = viewpoint_cam.get_intrinsic()
    H, mask = find_matching_points(w2c, w2c_t, K)

    gt_image_numpy = np.transpose(gt_image, (1, 2, 0))
    height, width = gt_image_numpy.shape[:2]
    gt_image_warped = cv2.warpPerspective(gt_image_numpy, H, (width, height))
    gt_image_warped = np.transpose(gt_image_warped, (2, 0, 1))
    gt_image_warped = torch.from_numpy(gt_image_warped)

    gt_mask_warped = cv2.warpPerspective(gt_mask.astype(float), H, (width, height))
    gt_mask_warped = (gt_mask_warped > 0.5)
    indices = np.where(gt_mask_warped == True)
    gt_mask_warped = torch.from_numpy(gt_mask_warped).unsqueeze(0)

    return gt_image_warped, gt_mask_warped, c2w_t


def generate_image_rotation(viewpoint_cam, max_yaw_degree):    
  
    gt_image = viewpoint_cam.original_image.numpy()
    gt_mask  = viewpoint_cam.original_ground_mask.numpy().squeeze(0)

    c2w = viewpoint_cam.get_extrinsic()
    w2c = np.linalg.inv(c2w)

    theta = np.array([0, 0, random.uniform(-max_yaw_degree, max_yaw_degree)])
    trans = np.array([0, 0, 0])

    R = rotationMat(theta, trans)
    c2w_t = np.matmul(viewpoint_cam.ego_pose.cpu(), np.matmul(R, viewpoint_cam.extrinsic.cpu()))
    w2c_t = np.linalg.inv(c2w_t)
    K = viewpoint_cam.get_intrinsic()
    H, mask = find_matching_points(w2c, w2c_t, K)

    gt_image_numpy = np.transpose(gt_image, (1, 2, 0))
    height, width = gt_image_numpy.shape[:2]
    gt_image_warped = cv2.warpPerspective(gt_image_numpy, H, (width, height))
    gt_image_warped = np.transpose(gt_image_warped, (2, 0, 1))
    gt_image_warped = torch.from_numpy(gt_image_warped)

    gt_mask_warped = cv2.warpPerspective(gt_mask.astype(float), H, (width, height))
    gt_mask_warped = (gt_mask_warped > 0.5)
    indices = np.where(gt_mask_warped == True)
    gt_mask_warped = torch.from_numpy(gt_mask_warped).unsqueeze(0)

    return gt_image_warped, gt_mask_warped, c2w_t