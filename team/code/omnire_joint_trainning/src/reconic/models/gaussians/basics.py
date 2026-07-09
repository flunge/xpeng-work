import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Union

import numpy as np
import torch
import torch.nn.functional as F
from gsplat.utils import normalized_quat_to_rotmat
from sklearn.neighbors import NearestNeighbors

def inverse_sigmoid(x):
    return torch.log(x/(1-x))


def fit_plane_to_points(pts):
    centroid = torch.mean(pts, dim=0)
    centered = pts - centroid
    _, _, V = torch.linalg.svd(centered)
    normal = V[-1]
    normal = normal / torch.linalg.norm(normal)
    return normal, centroid


def project_point_to_plane(point, normal, plane_point):
    vec = point - plane_point
    dist = torch.dot(vec, normal)
    projection = point - dist * normal
    return projection

def num_sh_bases(degree: int) -> int:
    """
    Returns the number of spherical harmonic bases for a given degree.
    """
    MAX_SH_DEGREE = 4
    assert degree <= MAX_SH_DEGREE, f"We don't support degree greater than {MAX_SH_DEGREE}."
    return (degree + 1) ** 2


def quat_to_rotmat(quat: torch.Tensor) -> torch.Tensor:
    assert quat.shape[-1] == 4, quat.shape
    return normalized_quat_to_rotmat(F.normalize(quat, dim=-1))


def interpolate_quats(q1, q2, fraction=0.5):
    q1 = q1 / torch.norm(q1, dim=-1, keepdim=True)
    q2 = q2 / torch.norm(q2, dim=-1, keepdim=True)

    dot = (q1 * q2).sum(dim=-1)
    dot = torch.clamp(dot, -1, 1)

    neg_mask = dot < 0
    q2[neg_mask] = -q2[neg_mask]
    dot[neg_mask] = -dot[neg_mask]

    similar_mask = dot > 0.9995
    q_interp_similar = q1 + fraction * (q2 - q1)

    theta_0 = torch.acos(dot)
    theta = theta_0 * fraction

    sin_theta = torch.sin(theta)
    sin_theta_0 = torch.sin(theta_0)

    s1 = torch.cos(theta) - dot * sin_theta / sin_theta_0
    s2 = sin_theta / sin_theta_0

    q_interp = (s1[..., None] * q1) + (s2[..., None] * q2)

    final_q_interp = torch.zeros_like(q1)
    final_q_interp[similar_mask] = q_interp_similar[similar_mask]
    final_q_interp[~similar_mask] = q_interp[~similar_mask]
    return final_q_interp


def random_quat_tensor(N):
    """
    Defines a random quaternion tensor of shape (N, 4)
    """
    u = torch.rand(N)
    v = torch.rand(N)
    w = torch.rand(N)
    return torch.stack(
        [
            torch.sqrt(1 - u) * torch.sin(2 * math.pi * v),
            torch.sqrt(1 - u) * torch.cos(2 * math.pi * v),
            torch.sqrt(u) * torch.sin(2 * math.pi * w),
            torch.sqrt(u) * torch.cos(2 * math.pi * w),
        ],
        dim=-1,
    )


def quat_mult(q1, q2):
    # NOTE:
    # Q1 is the quaternion that rotates the vector from the original position to the final position
    # Q2 is the quaternion that been rotated
    w1, x1, y1, z1 = q1.T
    w2, x2, y2, z2 = q2.T
    w = w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2
    x = w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2
    y = w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2
    z = w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2
    return torch.stack([w, x, y, z]).T


def RGB2SH(rgb):
    """
    Converts from RGB values [0,1] to the 0th spherical harmonic coefficient
    """
    C0 = 0.28209479177387814
    return (rgb - 0.5) / C0


def SH2RGB(sh):
    """
    Converts from the 0th spherical harmonic coefficient to RGB values [0,1]
    """
    C0 = 0.28209479177387814
    return sh * C0 + 0.5


def projection_matrix(znear, zfar, fovx, fovy, device: Union[str, torch.device] = "cpu"):
    """
    Constructs an OpenGL-style perspective projection matrix.
    """
    top = znear * math.tan(0.5 * fovy)
    bottom = -top
    right = znear * math.tan(0.5 * fovx)
    left = -right
    return torch.tensor(
        [
            [2 * znear / (right - left), 0.0, (right + left) / (right - left), 0.0],
            [0.0, 2 * znear / (top - bottom), (top + bottom) / (top - bottom), 0.0],
            [0.0, 0.0, (zfar + znear) / (zfar - znear), -1.0 * zfar * znear / (zfar - znear)],
            [0.0, 0.0, 1.0, 0.0],
        ],
        device=device,
    )


@dataclass
class dataclass_camera:
    camera_id: int
    timestep_id: int
    fraction_from_cur_timestep: float
    novel_view: bool
    camtoworlds: torch.Tensor
    camtoworlds_gt: torch.Tensor
    Ks: torch.Tensor
    H: int
    W: int


@dataclass
class dataclass_gs:
    _opacities: torch.Tensor
    _means: torch.Tensor
    _rgbs: torch.Tensor
    _scales: torch.Tensor
    _quats: torch.Tensor
    detach_keys: List[str]
    extras: Optional[Dict[str, torch.Tensor]] = None

    def set_grad_controller(self, detach_keys):
        self.detach_keys = detach_keys

    @property
    def opacities(self):
        if "activated_opacities" in self.detach_keys:
            return self._opacities.detach()
        else:
            return self._opacities

    @property
    def means(self):
        if "means" in self.detach_keys:
            return self._means.detach()
        else:
            return self._means

    @property
    def rgbs(self):
        if "colors" in self.detach_keys:
            return self._rgbs.detach()
        else:
            return self._rgbs

    @property
    def scales(self):
        if "scales" in self.detach_keys:
            return self._scales.detach()
        else:
            return self._scales

    @property
    def quats(self):
        if "quats" in self.detach_keys:
            return self._quats.detach()
        else:
            return self._quats


def remove_from_optim(optimizer, deleted_mask, param_dict):
    """removes the deleted_mask from the optimizer provided"""
    for group_idx, group in enumerate(optimizer.param_groups):
        name = group["name"]
        if name in param_dict.keys():
            old_params = group["params"][0]
            new_params = param_dict[name]
            assert len(new_params) == 1
            param_state = optimizer.state[old_params]
            del optimizer.state[old_params]

            # Modify the state directly without deleting and reassigning.
            param_state["exp_avg"] = param_state["exp_avg"][~deleted_mask]
            param_state["exp_avg_sq"] = param_state["exp_avg_sq"][~deleted_mask]

            # Update the parameter in the optimizer's param group.
            del optimizer.param_groups[group_idx]["params"][0]
            del optimizer.param_groups[group_idx]["params"]
            optimizer.param_groups[group_idx]["params"] = new_params
            optimizer.state[new_params[0]] = param_state


def dup_in_optim(optimizer, dup_mask, param_dict, n=2):
    """adds the parameters to the optimizer"""
    for group_idx, group in enumerate(optimizer.param_groups):
        name = group["name"]
        if name in param_dict.keys():
            old_params = group["params"][0]
            new_params = param_dict[name]
            param_state = optimizer.state[old_params]

            # Check if optimizer state contains the expected keys
            if "exp_avg" not in param_state or "exp_avg_sq" not in param_state:
                # Initialize Adam optimizer state variables if they don't exist
                # This happens when optimizer hasn't performed any steps yet
                param_state["exp_avg"] = torch.zeros_like(old_params.data)
                param_state["exp_avg_sq"] = torch.zeros_like(old_params.data)
                param_state["step"] = torch.tensor(0, dtype=torch.float32)

            # Handle dup_mask indexing for different tensor dimensions
            if param_state["exp_avg"].dim() == 2:
                # Standard 2D case: [N, features]
                mask_indices = dup_mask.squeeze()
            else:
                # Handle higher dimensions (e.g., Fourier features: [N, fourier_dim, 3])
                # Expand mask to match the first dimension
                mask_indices = dup_mask

            repeat_dims = (n,) + tuple(1 for _ in range(param_state["exp_avg"].dim() - 1))
            param_state["exp_avg"] = torch.cat(
                [
                    param_state["exp_avg"],
                    torch.zeros_like(param_state["exp_avg"][mask_indices]).repeat(*repeat_dims),
                ],
                dim=0,
            )
            param_state["exp_avg_sq"] = torch.cat(
                [
                    param_state["exp_avg_sq"],
                    torch.zeros_like(param_state["exp_avg_sq"][mask_indices]).repeat(*repeat_dims),
                ],
                dim=0,
            )
            del optimizer.state[old_params]
            optimizer.state[new_params[0]] = param_state
            optimizer.param_groups[group_idx]["params"] = new_params
            del old_params


def k_nearest_sklearn(x: torch.Tensor, k: int):
    """
    Find k-nearest neighbors using sklearn's NearestNeighbors.
    x: The data tensor of shape [num_samples, num_features]
    k: The number of neighbors to retrieve
    """
    # Convert tensor to numpy array
    x_np = x.cpu().numpy()

    # Build the nearest neighbors model
    nn_model = NearestNeighbors(n_neighbors=k + 1, algorithm="auto", metric="euclidean").fit(x_np)

    # Find the k-nearest neighbors
    distances, indices = nn_model.kneighbors(x_np)

    # Exclude the point itself from the result and return
    return distances[:, 1:].astype(np.float32), indices[:, 1:].astype(np.float32)

def IDFT(time, dim):
    if isinstance(time, float):
        time = torch.tensor(time)
    t = time.view(-1, 1).float()
    idft = torch.zeros(t.shape[0], dim)
    indices = torch.arange(dim)
    even_indices = indices[::2]
    odd_indices = indices[1::2]
    idft[:, even_indices] = torch.cos(torch.pi * t * even_indices)
    idft[:, odd_indices] = torch.sin(torch.pi * t * (odd_indices + 1))
    return idft



if __name__ == "__main__":
    quats_prev_frame = torch.tensor(
        [
            [4.3390e-02, 4.1600e-06, -9.5784e-05, 9.9906e-01],
            [1.1272e-04, 1.0807e-08, 9.5874e-05, -1.0000e00],
            [1.7490e-04, 1.6769e-08, -9.5874e-05, 1.0000e00],
        ],
        device="cuda:0",
    )

    quats_next_frame = torch.tensor(
        [
            [4.2516e-02, 4.0762e-06, -9.5787e-05, 9.9910e-01],
            [3.8867e-05, 3.7264e-09, -9.5874e-05, 1.0000e00],
            [1.8267e-04, 1.7513e-08, -9.5874e-05, 1.0000e00],
        ],
        device="cuda:0",
    )

    quats_cur_frame = interpolate_quats(quats_prev_frame, quats_next_frame, 0.5)

