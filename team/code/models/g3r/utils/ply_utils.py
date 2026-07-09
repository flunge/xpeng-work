import os
import sys
import torch
import numpy as np
from plyfile import PlyData, PlyElement
from .math_utils import inverse_sigmoid

current_dir = os.path.dirname(__file__) 
root_path = os.path.abspath(os.path.join(current_dir, "..", ".."))
sys.path.extend([root_path])
from street_gaussians.lib.utils.graphics_utils import BasicPointCloud

def construct_list_of_attributes():
    l = ['x', 'y', 'z', 'nx', 'ny', 'nz']
    # All channels except the 3 DC
    for i in range(3):
        l.append('f_dc_{}'.format(i))
    for i in range(9):
        l.append('f_rest_{}'.format(i))
    l.append('opacity')
    for i in range(3):
        l.append('scale_{}'.format(i))
    for i in range(4):
        l.append('rot_{}'.format(i))
    # for i in range(self._semantic.shape[1]):
    #     l.append('semantic_{}'.format(i))
    return l

def make_g3r_ply(gaussians, valid_id):
    xyz = gaussians["means"].detach().cpu().numpy()
    normals = np.zeros_like(xyz)
    fused_color = (gaussians["colors"].detach() - 0.5) / 0.28209479177387814
    max_sh_degree = 1
    features = torch.zeros((fused_color.shape[0], 3, (max_sh_degree + 1) ** 2)).float()
    features[..., 0] = fused_color
    f_dc = features[:, :, 0:1].transpose(1, 2).contiguous()
    f_rest = features[:, :, 1:].transpose(1, 2).contiguous()
    f_dc = f_dc.transpose(1, 2).flatten(start_dim=1).contiguous()
    f_rest = f_rest.transpose(1, 2).flatten(start_dim=1).contiguous()

    opacities = inverse_sigmoid(gaussians["opacities"]).detach().cpu().numpy()
    opacities = opacities.reshape(-1, 1)
    scales = torch.log(gaussians["scales"]).detach().cpu().numpy()
    rotation = gaussians["rotations"].detach().cpu().numpy()
    semamtics = np.zeros((xyz.shape[0], 0))

    dtype_full = [(attribute, 'f4') for attribute in construct_list_of_attributes()]
    attributes = np.concatenate((xyz, normals, f_dc, f_rest, opacities, scales, rotation, semamtics), axis=1)

    elements = np.empty(xyz.shape[0], dtype=dtype_full)

    if valid_id is not None:
        elements = np.empty(valid_id.shape[0], dtype=dtype_full)
        attributes= attributes[valid_id, :]

    elements[:] = list(map(tuple, attributes))
    return elements

def save_vis_g3r_gaussians(gaussians, save_path):
    plydata = make_g3r_ply(gaussians, valid_id = None)
    plydata = PlyElement.describe(plydata, 'vertex')
    plydata_list = [plydata]
    PlyData(plydata_list).write(save_path)
    return

def save_init_g3r_gaussians(gaussians, save_path):
    dtype = [('px', 'f4'), ('py', 'f4'), ('pz', 'f4'),
            ('nx', 'f4'), ('ny', 'f4'), ('nz', 'f4'),
            ('sx', 'f4'), ('sy', 'f4'), ('sz', 'f4'),
            ('opacity', 'f4'),
            ('red', 'f4'), ('green', 'f4'), ('blue', 'f4'),
            ('qw', 'f4'), ('qx', 'f4'), ('qy', 'f4'), ('qz', 'f4')]

    points_xyz = gaussians["means"].detach().cpu().numpy()
    normals = np.zeros_like(points_xyz)
    elements = np.empty(points_xyz.shape[0], dtype=dtype)
    attributes = np.concatenate((points_xyz, normals,
                                 gaussians["scales"].detach().cpu().numpy(),
                                 gaussians["opacities"].detach().cpu().numpy().reshape(-1, 1),
                                 gaussians["colors"].detach().cpu().numpy(),
                                 gaussians["rotations"].detach().cpu().numpy()), axis=1)
    elements[:] = list(map(tuple, attributes))

    vertex_element = PlyElement.describe(elements, 'vertex')
    ply_data = PlyData([vertex_element])
    ply_data.write(save_path)
    return

def convertG3RPly(gaussians):
    points_xyz = gaussians["means"].detach().cpu().numpy()
    normals = np.zeros_like(points_xyz)
    return BasicPointCloud(points=points_xyz,
                           colors=gaussians["colors"].detach().cpu().numpy(),
                           normals=normals,
                           rots=gaussians["rotations"].detach().cpu().numpy(),
                           scales=gaussians["scales"].detach().cpu().numpy(),
                           opacities=gaussians["opacities"].detach().cpu().numpy().reshape(-1, 1))


def obtain_g3r_gaussians_from_ply(path):
    positions, colors, normals, rotations, scales, opacities = read_g3r_ply_file(path)
    gaussians = {}
    gaussians["means"] = torch.from_numpy(positions)
    gaussians["rotations"] = torch.from_numpy(rotations)

    # scales = 0.02 * torch.ones((scales.shape[0], 3), dtype=torch.float)
    # gaussians["scales"] = scales

    gaussians["scales"] = torch.from_numpy(scales)
    gaussians["opacities"] = torch.from_numpy(opacities)
    gaussians["colors"] = torch.from_numpy(colors)
    return gaussians

def update_g3r_gaussians_with_count(scene_gaussians, update_id_counts, current_gaussians, update_id, total_num_points, weight = 1.0):
    if scene_gaussians is None:
        scene_gaussians = {
            'means': torch.zeros((total_num_points, 3)),
            'rotations': torch.zeros((total_num_points, 4)),
            'colors': torch.zeros((total_num_points, 3)),
            'scales': torch.zeros((total_num_points, 3)),
            'opacities': torch.zeros(total_num_points)
        }
        update_id_counts = torch.zeros(total_num_points)

    scene_gaussians["means"][update_id, :] = current_gaussians["means"].detach().clone().cpu()
    scene_gaussians["rotations"][update_id, :] = current_gaussians["rotations"].detach().clone().cpu()
    scene_gaussians["scales"][update_id, :] += weight * current_gaussians["scales"].detach().clone().cpu()
    scene_gaussians["colors"][update_id, :] += weight * current_gaussians["colors"].detach().clone().cpu()
    scene_gaussians["opacities"][update_id] += weight * current_gaussians["opacities"].detach().clone().cpu()
    update_id_counts[update_id] += weight
    return scene_gaussians, update_id_counts

def update_g3r_gaussians(scene_gaussians, current_gaussians, update_id, total_num_points):
    if scene_gaussians is None:
        scene_gaussians = {
            'means': torch.zeros((total_num_points, 3)),
            'rotations': torch.zeros((total_num_points, 4)),
            'colors': torch.zeros((total_num_points, 3)),
            'scales': torch.zeros((total_num_points, 3)),
            'opacities': torch.zeros(total_num_points)
        }

    scene_gaussians["means"][update_id, :] = current_gaussians["means"].detach().clone().cpu()
    scene_gaussians["scales"][update_id, :] = current_gaussians["scales"].detach().clone().cpu()
    scene_gaussians["rotations"][update_id, :] = current_gaussians["rotations"].detach().clone().cpu()
    scene_gaussians["colors"][update_id, :] = current_gaussians["colors"].detach().clone().cpu()
    scene_gaussians["opacities"][update_id] = current_gaussians["opacities"].detach().clone().cpu()
    return scene_gaussians

def average_g3r_gaussians(total_scene_gaussians, update_id_counts):
    valid_mask = update_id_counts > 0
    counts_expanded_1d = update_id_counts.unsqueeze(-1)
    counts_expanded_3d = counts_expanded_1d.expand(-1, 3)
    total_scene_gaussians["scales"][valid_mask] /= counts_expanded_3d[valid_mask]
    total_scene_gaussians["colors"][valid_mask] /= counts_expanded_3d[valid_mask]
    total_scene_gaussians["opacities"][valid_mask] /= update_id_counts[valid_mask]

    total_scene_gaussians["means"] = total_scene_gaussians["means"][valid_mask]
    total_scene_gaussians["rotations"] = total_scene_gaussians["rotations"][valid_mask]
    total_scene_gaussians["colors"] = total_scene_gaussians["colors"][valid_mask]
    total_scene_gaussians["scales"] = total_scene_gaussians["scales"][valid_mask]
    total_scene_gaussians["opacities"] = total_scene_gaussians["opacities"][valid_mask]
    return total_scene_gaussians

def read_g3r_ply_file(file_path):
    plydata = PlyData.read(file_path)
    vertices = plydata['vertex']
    positions = np.vstack([vertices['px'], vertices['py'], vertices['pz']]).T
    colors = np.vstack([vertices['red'], vertices['green'], vertices['blue']]).T
    normals = np.vstack([vertices['nx'], vertices['ny'], vertices['nz']]).T
    rotations = np.vstack([vertices['qw'], vertices['qx'], vertices['qy'], vertices['qz']]).T
    scales = np.vstack([vertices['sx'], vertices['sy'], vertices['sz']]).T
    opacities = np.array(vertices['opacity']).reshape(-1, 1)
    return positions, colors, normals, rotations, scales, opacities

def obtain_ground_surfel_gaussians(points_path):
    plydata = PlyData.read(points_path)        
    vertices = plydata['vertex']
    positions = torch.tensor(np.vstack([vertices['x'], vertices['y'], vertices['z']]).T, dtype=torch.float32)
    rotations = torch.tensor(np.vstack([vertices['qw'], vertices['qx'], vertices['qy'], vertices['qz']]).T, dtype=torch.float32)
    colors = torch.tensor(np.vstack([vertices['red'], vertices['green'], vertices['blue']]).T / 255.0, dtype=torch.float32)

    scales = 0.02 * torch.ones((positions.shape[0], 3), dtype=torch.float)
    opacities = 0.1 * torch.ones((positions.shape[0], 1), dtype=torch.float)

    gaussians = {}
    gaussians["means"] = positions
    gaussians["rotations"] = rotations
    gaussians["scales"] = scales
    gaussians["opacities"] = opacities
    gaussians["colors"] = colors
    return gaussians

def vised_ground_surfel(cfg):
    gaussians = obtain_ground_surfel_gaussians(cfg)
    save_vis_g3r_gaussians(gaussians, "ground_surfel_vis.ply")
    return

def merge_g3r_ply_files(ply_files, save_path):
    all_positions, all_colors, all_normals = [], [], []
    all_rotations, all_scales, all_opacities = [], [], []

    for file_path in ply_files:
        print(f"Processing {file_path}")
        positions, colors, normals, rotations, scales, opacities = read_g3r_ply_file(file_path)

        all_positions.append(positions)
        all_colors.append(colors)
        all_normals.append(normals)
        all_rotations.append(rotations)
        all_scales.append(scales)
        all_opacities.append(opacities)

        del positions, colors, normals, rotations, scales, opacities
        gc.collect()

    merged_positions = np.vstack(all_positions)
    merged_colors = np.vstack(all_colors)
    merged_normals = np.vstack(all_normals)
    merged_rotations = np.vstack(all_rotations)
    merged_scales = np.vstack(all_scales)
    merged_opacities = np.vstack(all_opacities)

    del all_positions, all_colors, all_normals, all_rotations, all_scales, all_opacities
    gc.collect()

    dtype = [('px', 'f4'), ('py', 'f4'), ('pz', 'f4'),
            ('nx', 'f4'), ('ny', 'f4'), ('nz', 'f4'),
            ('sx', 'f4'), ('sy', 'f4'), ('sz', 'f4'),
            ('opacity', 'f4'),
            ('red', 'f4'), ('green', 'f4'), ('blue', 'f4'),
            ('qw', 'f4'), ('qx', 'f4'), ('qy', 'f4'), ('qz', 'f4')]

    normals = np.zeros_like(merged_positions)
    elements = np.empty(merged_positions.shape[0], dtype=dtype)
    attributes = np.concatenate((merged_positions, normals,
                                 merged_scales,
                                 merged_opacities,
                                 merged_colors,
                                 merged_rotations), axis=1)
    elements[:] = list(map(tuple, attributes))

    vertex_element = PlyElement.describe(elements, 'vertex')
    ply_data = PlyData([vertex_element])
    ply_data.write(save_path)
    return

def merge_g3r_gaussians(total_scene_gaussians, scene_gaussians):
    if total_scene_gaussians is None:
        total_scene_gaussians = {}
        total_scene_gaussians["means"] = scene_gaussians["means"].detach().clone().cpu()
        total_scene_gaussians["scales"] = scene_gaussians["scales"].detach().clone().cpu()
        total_scene_gaussians["rotations"] = scene_gaussians["rotations"].detach().clone().cpu()
        total_scene_gaussians["opacities"] = scene_gaussians["opacities"].detach().clone().cpu()
        total_scene_gaussians["colors"] = scene_gaussians["colors"].detach().clone().cpu()
    else:
        total_scene_gaussians["means"] = torch.cat([total_scene_gaussians["means"], scene_gaussians["means"].detach().clone().cpu()], dim=0)
        total_scene_gaussians["scales"] = torch.cat([total_scene_gaussians["scales"], scene_gaussians["scales"].detach().clone().cpu()], dim=0)
        total_scene_gaussians["rotations"] = torch.cat([total_scene_gaussians["rotations"], scene_gaussians["rotations"].detach().clone().cpu()], dim=0)
        total_scene_gaussians["opacities"] = torch.cat([total_scene_gaussians["opacities"], scene_gaussians["opacities"].detach().clone().cpu()], dim=0)
        total_scene_gaussians["colors"] = torch.cat([total_scene_gaussians["colors"], scene_gaussians["colors"].detach().clone().cpu()], dim=0)
    return total_scene_gaussians

def merge_gaussians_with_points(total_scene_gaussians, points_info):
    total_scene_gaussians["means"] = torch.cat([total_scene_gaussians["means"], points_info[:, :3]], dim=0)
    total_scene_gaussians["rotations"] = torch.cat([total_scene_gaussians["rotations"], points_info[:, 3:7]], dim=0)
    total_scene_gaussians["colors"] = torch.cat([total_scene_gaussians["colors"], points_info[:, 7:10]], dim=0)
    total_scene_gaussians["scales"] = torch.cat([total_scene_gaussians["scales"], points_info[:, 10:13]], dim=0)
    total_scene_gaussians["opacities"] = torch.cat([total_scene_gaussians["opacities"], points_info[:, 13]], dim=0)
    return total_scene_gaussians

def repair_gaussians(total_scene_gaussians, all_updated_id, input_points, unquantized_points_info):
    total_points_num = input_points.shape[0]
    all_ids = set(range(total_points_num))
    unrecorded_ids = np.array(list(all_ids - all_updated_id))
    print("Repair number: ", unrecorded_ids.shape[0])

    repair_points = input_points[unrecorded_ids, :]
    total_scene_gaussians = merge_gaussians_with_points(total_scene_gaussians, repair_points)
    total_scene_gaussians = merge_gaussians_with_points(total_scene_gaussians, unquantized_points_info)
    return total_scene_gaussians
