import argparse

import numpy as np
import torch
from plyfile import PlyData, PlyElement


def convert_model_to_ply(checkpoint_path=None, save_path=None, model_names=None):
    if model_names is None:
        model_names = ["Background", "Ground"]

    model = torch.load(checkpoint_path, map_location="cpu", weights_only=False)

    _xyz = []
    _features_dc = []
    _features_rest = []
    _opacity = []
    _scaling = []
    _rotation = []
    for model_name in model_names:
        if model_name not in model["models"]:
            continue
        _xyz.append(model["models"][model_name]["_means"])

        # Handle features_dc - convert Fourier features (3D) to standard format (2D)
        features_dc = model["models"][model_name]["_features_dc"]
        if features_dc.dim() == 3:
            # Fourier features: [N, fourier_dim, 3] -> take the first frequency component as DC
            features_dc = features_dc[:, 0, :]  # Use the first Fourier coefficient as DC
        _features_dc.append(features_dc)

        _features_rest.append(model["models"][model_name]["_features_rest"])
        _opacity.append(model["models"][model_name]["_opacities"])
        scale = model["models"][model_name]["_scales"]
        if scale.shape[1] == 2:
            scale = torch.cat([scale, torch.zeros((scale.shape[0], 1))], dim=-1)
        _scaling.append(scale)
        _rotation.append(model["models"][model_name]["_quats"])
    _xyz = torch.cat(_xyz)
    _features_dc = torch.cat(_features_dc)
    _features_rest = torch.cat(_features_rest)
    _opacity = torch.cat(_opacity)
    _scaling = torch.cat(_scaling)
    _rotation = torch.cat(_rotation)

    xyz = _xyz.numpy()
    normals = np.zeros_like(xyz)
    f_dc = _features_dc.contiguous().numpy()
    f_rest = _features_rest.transpose(1, 2).flatten(start_dim=1).contiguous().numpy()
    opacities = _opacity.numpy()
    scale = _scaling.numpy()
    rotation = _rotation.numpy()

    keys = ["x", "y", "z", "nx", "ny", "nz"]
    for i in range(f_dc.shape[1]):
        keys.append("f_dc_{}".format(i))
    for i in range(f_rest.shape[1]):
        keys.append("f_rest_{}".format(i))
    keys.append("opacity")
    for i in range(scale.shape[1]):
        keys.append("scale_{}".format(i))
    for i in range(rotation.shape[1]):
        keys.append("rot_{}".format(i))
    dtype_full = [(attribute, "f4") for attribute in keys]

    elements = np.empty(xyz.shape[0], dtype=dtype_full)
    attributes = np.concatenate((xyz, normals, f_dc, f_rest, opacities, scale, rotation), axis=1)
    elements[:] = list(map(tuple, attributes))
    el = PlyElement.describe(elements, "vertex")
    PlyData([el]).write(save_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert DriveStudio model to PLY format")
    parser.add_argument("--checkpoint_path", type=str, required=True, help="Path to checkpoint file")
    parser.add_argument("--save_path", type=str, required=True, help="Path to save output PLY file")
    parser.add_argument(
        "--model_names",
        type=str,
        nargs="+",
        default=["Background", "Ground", "RigidNodes", "RigidNodesLight", "DeformableNodes"],
        help="List of model names to extract (default: Background Ground)",
    )

    args = parser.parse_args()

    convert_model_to_ply(checkpoint_path=args.checkpoint_path, save_path=args.save_path, model_names=args.model_names)
