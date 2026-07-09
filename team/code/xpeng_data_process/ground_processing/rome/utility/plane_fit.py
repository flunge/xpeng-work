import numpy as np
from skspatial.objects import Plane, Points
import scipy


def estimate_flatplane(xyz):
    points = Points(xyz)
    points_centered, centroid = points.mean_center(return_centroid=True)
    u, s, _ = np.linalg.svd(points_centered.T)
    normal = u[:, 2]
    plane = Plane(centroid, normal)
    print('plane fit success!', plane, 'singular is: ', s)

    transform_normal2origin = np.eye(4)
    transform_normal2origin[:3, :3] = u
    transform_normal2origin[:3, 3] = np.asarray(plane.point)
    transform_origin2normal = np.linalg.inv(transform_normal2origin)
    return transform_origin2normal


def get_points_with_wings(xyz, offset):
    """Add more balanced points to trajectory xyz for plane fitting.
        The main purpose is to prevent ambiguious fitting when trajectory is
        almost stright line.

    Args:
        xyz (ndarray): shape(N, 3)
        offset (float): wings length.

    Returns:
        ndarray: shape(5N, 3), points with balanced wings
    """
    x_left_offset = xyz - np.array([[offset, 0, 0]])
    x_right_offset = xyz - np.array([[-offset, 0, 0]])
    y_left_offset = xyz - np.array([[0, offset, 0]])
    y_right_offset = xyz - np.array([[0, -offset, 0]])
    xyz = np.concatenate([xyz, x_left_offset, x_right_offset, y_left_offset, y_right_offset], axis=0)
    return xyz


def robust_estimate_flatplane(xyz, configs):
    """estimate flat plane from points. Assuming the points are mostly in xy plane.

    Args:
        xyz (ndarray): shape (N, 3) xyz points.
        configs (dict): configs.

    Returns:
        ndarray: transform_normal2origin
    """
    if configs.get("est_plane_use_adaptive_offset", False):
        diag_length = np.linalg.norm(xyz.max(axis=0) - xyz.min(axis=0))
        offset_ratio = configs.get("est_plane_adaptive_offset_ratio", 0.05)
        offset = max(1, offset_ratio * diag_length)
    else:
        offset = configs.get("est_plane_fixed_offset", 0.8)

    xyz = get_points_with_wings(xyz, offset)

    return estimate_flatplane(xyz)
