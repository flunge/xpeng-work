#!/usr/bin/env python

'''
Feature-based image matching sample.
Note, that you will need the https://github.com/opencv/opencv_contrib repo for SIFT and SURF
'''

# Python 2/3 compatibility
from __future__ import print_function

import numpy as np
import cv2
from scipy.spatial import cKDTree


FLANN_INDEX_KDTREE = 1  # bug: flann enums are missing
FLANN_INDEX_LSH    = 6


def init_feature(name):
    chunks = name.split('-')
    if chunks[0] == 'sift':
        detector = cv2.SIFT_create(nfeatures=6000, nOctaveLayers=5, contrastThreshold=0.01, edgeThreshold=30, sigma=1.6)
        norm = cv2.NORM_L2
    elif chunks[0] == 'surf':
        detector = cv2.xfeatures2d.SURF_create(6000)
        norm = cv2.NORM_L2
    elif chunks[0] == 'orb':
        detector = cv2.ORB_create(nfeatures=6000, fastThreshold=8)
        norm = cv2.NORM_HAMMING
    elif chunks[0] == 'akaze':
        detector = cv2.AKAZE_create()#max_points=6000
        norm = cv2.NORM_HAMMING
    elif chunks[0] == 'brisk':
        detector = cv2.BRISK_create()
        norm = cv2.NORM_HAMMING
    else:
        return None, None
    if 'flann' in chunks:
        if norm == cv2.NORM_L2:
            flann_params = dict(algorithm = FLANN_INDEX_KDTREE, trees = 5)
        else:
            flann_params= dict(algorithm = FLANN_INDEX_LSH,
                               table_number = 6, # 12
                               key_size = 12,     # 20
                               multi_probe_level = 1) #2
        matcher = cv2.FlannBasedMatcher(flann_params, {})  # bug : need to pass empty dict (#1329)
    else:
        matcher = cv2.BFMatcher(norm)
    return detector, matcher

def remove_local_matches(kpt_pairs:list, radius=5):
    pts1 = np.array([kpp[0].pt for kpp in kpt_pairs])
    pts2 = np.array([kpp[1].pt for kpp in kpt_pairs])

def merge_nearby_keypoints(keypoints:list, radius:int=2)->list:
    # Initialize the list of merged keypoints
    if len(keypoints) == 0:
        return [], []
    merged_keypoints_indices = []
    keypoints_to_merged_indices = [-1] * len(keypoints)
    pts = np.asarray([kp.pt for kp in keypoints])
    search_tree = cKDTree(pts)
    indicess = search_tree.query_ball_point(pts, radius)
    # Iterate through each keypoint
    for i, indices in enumerate(indicess):
        kpt = keypoints[i]
        # Check if the keypoint is close to any merged keypoint
        is_close = False
        for index in indices:
            if index < i:
                is_close = True
                midx = keypoints_to_merged_indices[index]
                keypoints_to_merged_indices[i] = midx
                mkpt_index = merged_keypoints_indices[midx]
                mkpt = keypoints[mkpt_index]
                if kpt.response > mkpt.response:
                    merged_keypoints_indices[midx] = i
                break
        if not is_close:
            keypoints_to_merged_indices[i] = len(merged_keypoints_indices)
            merged_keypoints_indices.append(i)
    merged_indices = np.asarray(merged_keypoints_indices)
    indices = merged_indices[keypoints_to_merged_indices]
    return indices, merged_indices

def merge_nearby_pairs(kpt_pairs:list, radius=2)->list:
    if len(kpt_pairs) == 0:
        return kpt_pairs
    new_kpt_pairs = []
    kpts_query = [kpp[0] for kpp in kpt_pairs]
    kpts_train = [kpp[1] for kpp in kpt_pairs]

    query_indices, _ = merge_nearby_keypoints(kpts_query, radius)
    train_indices, _ = merge_nearby_keypoints(kpts_train, radius)

    added_train_indices = set()
    for i, query_index in enumerate(query_indices):
        if i == query_index:
            train_index = train_indices[i]
            if train_index in added_train_indices:
                continue
            added_train_indices.add(train_index)
            kpt_query = kpts_query[query_index]
            kpt_train = kpts_train[train_index]
            kpt_pair = (kpt_query, kpt_train)
            new_kpt_pairs.append(kpt_pair)
    return new_kpt_pairs

def remove_nearby_pairs(kpt_pairs:list, radius=3)->list:
    if len(kpt_pairs) < 200:
        return kpt_pairs

    kpts_query = [kpp[0] for kpp in kpt_pairs]
    kpts_train = [kpp[1] for kpp in kpt_pairs]

    query_indices, _ = merge_nearby_keypoints(kpts_query, radius)
    new_kpt_pairs =  [(kpts_query[i], kpts_train[i]) for i, query_index in enumerate(query_indices) if i == query_index]

    if len(new_kpt_pairs) < 100:
        return kpt_pairs
    return new_kpt_pairs

def filter_matches(kp_query:list, kp_train:list, matches:list, ratio = 0.7):
    kpt_matches = filter_matches_only(kp_query, kp_train, matches, ratio)
    p_query = np.array([kp_query[kpt_pair.queryIdx].pt for kpt_pair in kpt_matches])
    p_train = np.array([kp_train[kpt_pair.trainIdx].pt for kpt_pair in kpt_matches])
    return p_query, p_train, kpt_matches

def square_dist_point(pt1:tuple, pt2:tuple)->float:
    diff = np.asarray(pt1) - np.asarray(pt2)
    return np.sum(diff*diff)

def filter_matches_only(kpts_query:list, kpts_train:list, matches:list, ratio = 0.7):
    kpt_matches = []
    train_to_match = {}
    for match in matches:
        if len(match) < 2:
            continue
        best_match = match[0]
        if best_match.trainIdx in train_to_match:
            prev_match = train_to_match[best_match.trainIdx]
            if best_match.distance < prev_match.distance:
                prev_match.queryIdx = best_match.queryIdx
            square_dist = square_dist_point(kpts_query[best_match.queryIdx].pt, kpts_query[prev_match.queryIdx].pt)
            if square_dist > 2 * 2:
                continue
        second_match = match[1]
        if best_match.distance < ratio * second_match.distance:
            kpt_matches.append(best_match)
            train_to_match[best_match.trainIdx] = kpt_matches[-1]
        else:
            squre_dist = square_dist_point(kpts_train[best_match.trainIdx].pt, kpts_train[second_match.trainIdx].pt)
            if squre_dist > 2 * 2:
                continue
            kpt_matches.append(best_match)
            train_to_match[best_match.trainIdx] = kpt_matches[-1]
    return kpt_matches

def matches_to_pairs(kpts2:list, kpts1:list, matches21:list):
    return [(kpts2[match.queryIdx], kpts1[match.trainIdx]) for match in matches21]

def keypoints_to_points(keypoints:list):
    return [kpt.pt for kpt in keypoints]

def filter_matches_y(kpts2:list, kpts1:list, matches21:list, Kt:np.ndarray, A:np.ndarray, th:float=50):
    filtered_matches21 = []
    for match in matches21:
        pt1 = kpts1[match.trainIdx].pt
        pt2 = kpts2[match.queryIdx].pt
        uv1_1 = np.array([[pt1[0]],[pt1[1]], [1]])
        uv1_2 = np.array([[pt2[0]],[pt2[1]], [1]])
        x2a = A@uv1_2*5
        x2b = x2a*20
        x1a = x2a + Kt
        x1b = x2b + Kt
        x1a /= x1a[2,0]
        x1b /= x1b[2,0]
        x1a = x1a[:2,0]
        x1b = x1b[:2,0]
        x1 = uv1_1[:2,0]
        # Calculate the distance from x1 to the line formed by x1a and x1b
        dist = np.linalg.norm(np.cross(x1b-x1a, x1-x1a)) / np.linalg.norm(x1b-x1a)
        if dist < th:
            filtered_matches21.append(match)

    return filtered_matches21

'''Filter matches by fundamental matrix'''
def filter_matches_kta(p2:list, p1:list, matches21:list, Kt:np.ndarray, A:np.ndarray, th:float=50):
    filtered_matches21 = []
    for i in range(len(matches21)):
        pt1 = p1[i]
        pt2 = p2[i]
        uv1_2 = np.array([[pt2[0]],[pt2[1]], [1]])
        uv1_1 = np.array([[pt1[0]],[pt1[1]], [1]])
        x2 = A@uv1_2
        x1a = x2 + Kt
        x1a /= x1a[2,0]
        x1 = uv1_1 - x1a
        x2 = x2[:2,0]
        x1 = x1[:2,0]
        dist = np.linalg.norm(np.cross(x1, x2)) / np.linalg.norm(x2)
        if dist < th:
            filtered_matches21.append(matches21[i])

    return filtered_matches21

def filter_matches_geo(p2:np.ndarray, p1:np.ndarray, matches21:list, cmd:str='fund'):
    filtered_matches21 = matches21
    if len(p2) >= 4:
        if cmd.startswith('fund'):
            _, status21 = cv2.findFundamentalMat(p2, p1, cv2.FM_RANSAC, 1.0, 0.99)
            if status21 is None:
                _, status21 = cv2.findHomography(p2, p1, cv2.RANSAC, 20.0)
            # do not draw outliers (there will be a lot of them)
        elif cmd.startswith('homo'):
            _, status21 = cv2.findHomography(p2, p1, cv2.RANSAC, 20.0)
            if status21 is None:
                _, status21 = cv2.findFundamentalMat(p2, p1, cv2.FM_RANSAC, 1.0, 0.99)
            # do not draw outliers (there will be a lot of them)
        elif cmd == 'and':
            _, status21_a = cv2.findHomography(p2, p1, cv2.RANSAC, 45.0)
            _, status21_b = cv2.findFundamentalMat(p2, p1, cv2.FM_RANSAC, 1.0, 0.99)
            if status21_b is not None:
                status21 = status21_a & status21_b
            else:
                status21 = status21_a
        elif cmd == 'or':
            _, status21_a = cv2.findHomography(p2, p1, cv2.RANSAC, 45.0)
            _, status21_b = cv2.findFundamentalMat(p2, p1, cv2.FM_LMEDS)
            if status21_b is not None:
                status21 = status21_a | status21_b
            else:
                status21 = status21_a
        filtered_matches21 = [kpp for kpp, flag in zip(matches21, status21) if flag]

    return filtered_matches21

def filter_matches_full(kpts_query:list, kpts_train:list, matches:list, ratio = 0.7, method='fund'):
    p2, p1, kp_matches21 = filter_matches(kpts_query, kpts_train, matches, ratio)
    return filter_matches_geo(p2, p1, kp_matches21, method)

def filter_matches_simple(kpts_query:list, kpts_train:list, matches:list):
    kp_matches21 = filter_matches_only(kpts_query, kpts_train, matches, 0.7)
    return kp_matches21

def filter_matches_self(kpts_query:list, kpts_train:list, matches:list, ratio = 0.7, Kt:np.ndarray=None, A:np.ndarray=None):
    _, _, kp_matches21 = filter_matches(kpts_query, kpts_train, matches, ratio)
    return filter_matches_y(kpts_query, kpts_train, kp_matches21, Kt, A)

def sort_images(images:list):
    image_keys = {'cam0':0, 'cam3':1, 'cam2':2, 'cam4':3, 'cam5':4, 'cam7':5, 'cam6':6}
    sorted_indices = sorted(range(len(images)), key=lambda x: image_keys[images[x].camera_name])
    return sorted_indices

def arrange_images(imgs: list):
    max_hs = []
    sum_ws = []
    sorted_indices = sort_images(imgs)
    indice = []
    indices =[]

    new_line_indices = [i for i in sorted_indices if imgs[i].camera_name in ["cam0", "cam4", "cam6"]]
    for index in sorted_indices:
        indice.append(index)
        if index in new_line_indices:
            indices.append(indice)
            indice = []

    for indice in indices:
        hwcs = []
        for index in indice:
            if(index < len(imgs)):
                hwc = imgs[index].shape
                hwcs.append(hwc)
        hwcs_array = np.array(hwcs)
        max_hs.append(max(hwcs_array[:, 0]))
        sum_ws.append(sum(hwcs_array[:, 1]))
    vis = np.zeros((sum(max_hs), max(sum_ws), 3), np.uint8)

    start_w_offset = {ii: (max(sum_ws) - ws) // 2  for ii, ws in enumerate(sum_ws) if ws > 0}
    start_h = 0
    toplefts = [[0, 0]]*len(imgs)
    for ii, indice in enumerate(indices):
        start_w = start_w_offset[ii] if ii in start_w_offset else 0
        max_h = 0
        for index in indice:
            h,w = imgs[index].shape[:2]
            max_h = max(max_h, h)
            toplefts[index]=[start_w, start_h]
            vis[start_h:start_h+h, start_w:start_w+w, :] = imgs[index].image if len(imgs[index].shape) == 3 else cv2.cvtColor(imgs[index].image, cv2.COLOR_GRAY2BGR)
            start_w += w
        start_h += max_h

    return vis, toplefts

def draw_matches(vis, kp_pairs21, topleft1, topleft2):
    p1, p2 = [], []  # python 2 / python 3 change of zip unpacking
    for kpp in kp_pairs21:
        p2.append(np.int32(np.array(kpp[0].pt) + topleft2))
        p1.append(np.int32(np.array(kpp[1].pt) + topleft1))

    blue = (255, 0, 0)
    green = (0, 255, 0)

    for (x1, y1), (x2, y2) in zip(p1, p2):
        col = blue
        cv2.circle(vis, (x1, y1), 2, col, -1)
        cv2.circle(vis, (x2, y2), 2, col, -1)
        cv2.line(vis, (x1, y1), (x2, y2), green)

    return vis

if __name__ == '__main__':
    cv2.destroyAllWindows()