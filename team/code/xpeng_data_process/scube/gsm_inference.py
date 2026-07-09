# Copyright (c) 2024, NVIDIA CORPORATION & AFFILIATES.  All rights reserved.
#
# NVIDIA CORPORATION & AFFILIATES and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION & AFFILIATES is strictly prohibited.

import sys, os
from pathlib import Path
sys.path.append(Path(__file__).parent.parent.as_posix())

SCUBE_PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_PARAM_PATH = SCUBE_PROJECT_ROOT / "configs" / "default" / "param.yaml"

import torch
import torchvision
import numpy as np
import fvdb
import fvdb.nn
import imageio.v3 as imageio
from scipy.spatial import KDTree
from plyfile import PlyData, PlyElement

import torch.nn.functional as F
from omegaconf import OmegaConf
from pycg import exp
from loguru import logger 
from tqdm import tqdm
from scube.utils.common_util import batch2device, get_default_parser, create_model_from_args
from scube.utils.gaussian_util import save_splat_file_RGB, process_gaussian_params_to_splat
from scube.data.base import DatasetSpec as DS

fvdb.nn.SparseConv3d.backend = 'igemm_mode1'

def get_parser():
    parser = exp.ArgumentParserX(
        base_config_path=DEFAULT_PARAM_PATH.as_posix(),
        parents=[get_default_parser()],
    )
    parser.add_argument('--ckpt_path', type=str, required=False, default='last', help='if specify other ckpt name.')
    parser.add_argument('--nosync', action='store_true', help='Do not synchronize nas even if forced.')
    parser.add_argument('--split', type=str, default="test", help='Dataset split to evaluate on. test or train')
    parser.add_argument('--output_root', type=str, default="../splat_output_waymo_wds/", help='Output directory.')
    parser.add_argument('--suffix', type=str, default="", help='Suffix for output directory.')
    parser.add_argument('--save_img_separately', action='store_true', help='save pred image separately in one folder')
    parser.add_argument('--save_gs', action='store_true', help='save gaussians to .pkl file')
    parser.add_argument('--input_frame_offsets', type=int, nargs='+', default=None, help='Input frame offsets.')
    parser.add_argument('--val_starting_frame', type=int, default=100, help='Starting frame.')
    parser.add_argument('--skybox_resolution', type=int, default=768, help='Skybox resolution.')
    parser.add_argument('--infer_case_id', type=str, default="")
    return parser

def _compute_voxel_indices(points, voxel_size=0.1):
    voxel_indices = np.floor(points / voxel_size).astype(np.int64)
    max_range = 1000000  # 假设坐标范围在[-1000000, 1000000]以内
    voxel_keys = voxel_indices[:, 0] * max_range * max_range + \
                 voxel_indices[:, 1] * max_range + \
                 voxel_indices[:, 2]
    return voxel_keys

@torch.inference_mode()
def render_and_save_gsm(net_model_gsm, known_args, saving_dir, img_reorder, 
                        save_img_together, save_gaussians):
    total_xyz = None
    total_scaling = None
    total_rotation = None
    total_opacity = None
    total_color = None
    voxel_to_idx = {}

    dataloader = net_model_gsm.test_dataloader(known_args.infer_case_id)
    for batch_idx, batch in enumerate(tqdm(dataloader)):
        print("======batch_idx====== ", batch_idx)
        batch = batch2device(batch, net_model_gsm.device)
        renderer_output, network_output = net_model_gsm.forward(batch)
        gt_package = net_model_gsm.loss.prepare_resized_gt(batch)
        vis_images_dict = net_model_gsm.loss.assemble_visualization(gt_package, renderer_output)

        if save_img_together:
            gt_images = vis_images_dict['gt_images'][0] # [N, H, W, 3]
            pd_images = vis_images_dict['pd_images'][0] # [N, H, W, 3]
            pd_images_fg = vis_images_dict['pd_images_fg'][0] # [N, H, W, 3]

            # reorder for better visualization. [N, H, W, 3]
            n_frames = gt_images.shape[0] // len(img_reorder)
            pd_images_reorder = torch.cat([x[img_reorder] for x in torch.chunk(pd_images, n_frames, dim=0)], dim=0)
            pd_images_fg_reorder = torch.cat([x[img_reorder] for x in torch.chunk(pd_images_fg, n_frames, dim=0)], dim=0)
            gt_images_reorder = torch.cat([x[img_reorder] for x in torch.chunk(gt_images, n_frames, dim=0)], dim=0)

            pd_images_reorder_resize = pd_images_reorder.permute(0, 3, 1, 2)
            pd_images_fg_reorder = pd_images_fg_reorder.permute(0, 3, 1, 2)
            gt_images_reorder_resize = gt_images_reorder.permute(0, 3, 1, 2)
            torchvision.utils.save_image(pd_images_reorder_resize, 
                                        saving_dir / f"{batch_idx}_pred_images.jpg", 
                                        nrow=len(img_reorder))
            torchvision.utils.save_image(pd_images_fg_reorder,
                                        saving_dir / f"{batch_idx}_pred_images_fg.jpg",
                                        nrow=len(img_reorder))
            torchvision.utils.save_image(gt_images_reorder_resize, 
                                        saving_dir / f"{batch_idx}_gt_images.jpg", 
                                        nrow=len(img_reorder))

        decoded_gaussians = network_output['decoded_gaussians'][0] 
        assert decoded_gaussians.shape[1] == 14
        output_path = saving_dir / f"{batch_idx}_rgb_gaussians.splat"
        xyz, scaling, rotation, opacity, color = save_splat_file_RGB(decoded_gaussians, output_path.as_posix(), batch[DS.GRID_TO_WORLD])

        current_xyz_np = xyz.cpu().numpy()
        
        if total_xyz is None:
            total_xyz = xyz
            total_scaling = scaling
            total_rotation = rotation
            total_opacity = opacity
            total_color = color
            total_voxel_indices = _compute_voxel_indices(current_xyz_np)
        else:
            current_voxel_indices = _compute_voxel_indices(current_xyz_np)
            total_xyz_np = total_xyz.cpu().numpy()
            existing_voxel_indices_set = set(_compute_voxel_indices(total_xyz_np))

            mask = []
            for idx, voxel_idx in enumerate(current_voxel_indices):
                if voxel_idx not in existing_voxel_indices_set:
                    mask.append(True)
                else:
                    mask.append(False)

            mask = np.array(mask)
            if np.any(mask):
                new_xyz = xyz[mask]
                new_scaling = scaling[mask]
                new_rotation = rotation[mask]
                new_opacity = opacity[mask]
                new_color = color[mask]

                total_xyz = torch.cat([total_xyz, new_xyz], dim=0)
                total_scaling = torch.cat([total_scaling, new_scaling], dim=0)
                total_rotation = torch.cat([total_rotation, new_rotation], dim=0)
                total_opacity = torch.cat([total_opacity, new_opacity], dim=0)
                total_color = torch.cat([total_color, new_color], dim=0)

                new_voxel_indices = current_voxel_indices[mask]
                total_voxel_indices = np.concatenate([total_voxel_indices, new_voxel_indices], axis=0)

        # save skybox representation
        net_model_gsm.skybox.save_skybox(network_output, saving_dir / "sky")
        net_model_gsm.renderer.save_decoder(saving_dir / "sky_params.pt")
        break

    init_ply_path = os.path.join(saving_dir, "gsm_bkgd_init.ply")
    print("save path ", init_ply_path)
    save_init_ply(init_ply_path, total_xyz, total_scaling, total_rotation, total_opacity, total_color)

    # output_path = os.path.join(saving_dir, "total.splat")
    # print("start save splat")
    # splat_data, xyz_np = process_gaussian_params_to_splat(total_xyz, total_scaling, total_rotation, total_opacity, total_color)
    # with open(output_path, "wb") as f:
    #     f.write(splat_data)

    # np.savetxt("xyz.txt", xyz_np, fmt="%.6f")
    # print("stop save splat")

def inverse_sigmoid(x):
    return torch.log(x/(1-x))

# xyz: (N, 3) float32
# scaling: (N, 3) float32
# rotation: (N, 4) float32
# opacity: (N,) or (N, 1) float32, range [0, 1]
# color: (N, 3) float32, range [0, 1]
def save_init_ply(init_ply_path, total_xyz, total_scaling, total_rotation, total_opacity, total_color):
    N = total_xyz.shape[0]
    exp_scales = total_scaling

    means_crop = total_xyz
    colors_crop = total_color
    opacities_crop_old = total_opacity
    opacities_crop = inverse_sigmoid(opacities_crop_old)

    # For rotations (assuming (N, 4) quaternion)
    quats_crop = total_rotation
    f_rotations = quats_crop / quats_crop.norm(dim=-1, keepdim=True)

    xyz = means_crop.detach().cpu().numpy()
    normals = np.zeros_like(xyz)

    # save init ply
    dtype = [('px', 'f4'), ('py', 'f4'), ('pz', 'f4'),
            ('nx', 'f4'), ('ny', 'f4'), ('nz', 'f4'),
            ('sx', 'f4'), ('sy', 'f4'), ('sz', 'f4'),
            ('opacity', 'f4'),
            ('red', 'f4'), ('green', 'f4'), ('blue', 'f4'),
            ('qw', 'f4'), ('qx', 'f4'), ('qy', 'f4'), ('qz', 'f4')]
    elements = np.empty(xyz.shape[0], dtype=dtype)
    attributes = np.concatenate((xyz, normals,
                                exp_scales.detach().cpu().numpy(),
                                opacities_crop.detach().cpu().numpy().reshape(-1, 1),
                                colors_crop.detach().cpu().numpy(),
                                f_rotations.detach().cpu().numpy()), axis=1)
    elements[:] = list(map(tuple, attributes))

    vertex_element = PlyElement.describe(elements, 'vertex')
    ply_data = PlyData([vertex_element])
    ply_data.write(init_ply_path)
    print("finish save init")
    return


def main():
    known_args = get_parser().parse_known_args()[0]
    if known_args.suffix != "":
        known_args.suffix = "_" + known_args.suffix
    saving_dir = Path(known_args.output_root) 
    saving_dir.mkdir(parents=True, exist_ok=True)

    hparam_update = {
        'skybox_resolution': known_args.skybox_resolution,
        'skybox_forward_sky_only': True,
        'train_val_num_workers': 0
    }

    model_name = "gsm"
    print("===before create model===")
    net_model_gsm, global_step_gsm = create_model_from_args(known_args.ckpt_path, model_name, get_parser(), hparam_update=hparam_update)
    net_model_gsm.cuda()
    print("===after create model===")

    dataset_kwargs = net_model_gsm.hparams.test_kwargs
    input_frame_offsets = [0]

    # update dataset_kwargs
    dataset_kwargs['split'] = 'test' # we can use the train_dataset, but set split to test for no random selection
    dataset_kwargs['val_starting_frame'] = known_args.val_starting_frame
    dataset_kwargs['input_frame_offsets'] = input_frame_offsets
    dataset_kwargs['sup_slect_ids'] = [0]
    dataset_kwargs['sup_frame_offsets'] = [0, 5, 10]
    dataset_kwargs['n_image_per_iter_sup'] = None
    
    # reorder for better visualization
    if len(dataset_kwargs['sup_slect_ids']) == 3:
        img_reorder = [1,0,2]
    elif len(dataset_kwargs['sup_slect_ids']) == 5:
        img_reorder = [3,1,0,2,4]
    elif len(dataset_kwargs['sup_slect_ids']) == 1:
        img_reorder = [0]
    else:
        raise NotImplementedError

    print("===start render===")
    render_and_save_gsm(net_model_gsm, known_args, saving_dir, img_reorder,
                        save_img_together=True, save_gaussians=True)

if __name__ == "__main__":
    main()