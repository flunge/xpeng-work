import numpy as np
from copy import deepcopy
from utils.misc import get_transform_json


def get_lateral_shifted_egoposes(egoposes, shift_distance = 3.5, stride=1):
    ### shift_distance positive: shift left, negative: shift right
    displacements = np.diff(egoposes[:, :3, 3], axis=0)
    direction_norm = displacements / np.linalg.norm(displacements, axis=1)[:, None]
    direction_norm = np.vstack([direction_norm, direction_norm[-1]])

    perpendicular_vector = direction_norm.copy()
    perpendicular_vector[:, 0] = -direction_norm[:, 1]
    perpendicular_vector[:, 1] = direction_norm[:, 0]

    shift_vector = shift_distance * perpendicular_vector

    shift_matrix = np.tile(np.eye(4), (direction_norm.shape[0], 1, 1))
    shift_matrix[:, :3, 3] = shift_vector 

    shifted_egoposes = shift_matrix @ egoposes
    return shifted_egoposes[::stride]

    