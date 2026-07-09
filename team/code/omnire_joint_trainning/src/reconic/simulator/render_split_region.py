"""Split-region mask selection for HIL rendering."""

from __future__ import annotations

import torch

from sim_interface.utils import point_in_polygon


def select_region_masks(region_masks, poly_vertices, camera_to_world) -> torch.Tensor:
    """Pick merged ground region masks closest to the camera position."""
    true_region_masks = torch.ones(region_masks[0].shape[0], device=region_masks[0].device)
    min_dist = 1e5
    min_index = None
    cam_pos = camera_to_world[:3, 3][None, :].cuda()

    for i, vertices in enumerate(poly_vertices):
        if not point_in_polygon(cam_pos, vertices):
            continue
        center = 0.25 * (vertices[0] + vertices[1] + vertices[2] + vertices[3])
        dist = torch.norm(center - camera_to_world[:2, 3][None, :].cuda(), dim=1).item()
        if dist < min_dist:
            min_dist = dist
            min_index = i

    if min_index is None:
        return true_region_masks

    i = min_index
    if i == 0:
        return region_masks[i] | region_masks[i + 1]
    if i == len(poly_vertices) - 1:
        return region_masks[i - 1] | region_masks[i]
    return region_masks[i - 1] | region_masks[i] | region_masks[i + 1]
