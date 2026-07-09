import torch

def inverse_sigmoid(x):
    return torch.log(x/(1-x))

def construct_list_of_attributes():
    l = ['x', 'y', 'z', 'nx', 'ny', 'nz']
    for i in range(3):
        l.append('f_dc_{}'.format(i))
    for i in range(9):
        l.append('f_rest_{}'.format(i))
    l.append('opacity')
    for i in range(3):
        l.append('scale_{}'.format(i))
    for i in range(4):
        l.append('rot_{}'.format(i))
    return l

def get_viewmat(optimized_camera_to_world):
    R = optimized_camera_to_world[:, :3, :3]
    T = optimized_camera_to_world[:, :3, 3:4]
    # flip the z and y axes to align with gsplat conventions
    R = R * torch.tensor([[[1, -1, -1]]], device=R.device, dtype=R.dtype)
    # analytic matrix inverse to get world2camera matrix
    R_inv = R.transpose(1, 2)
    T_inv = -torch.bmm(R_inv, T)
    viewmat = torch.zeros(R.shape[0], 4, 4, device=R.device, dtype=R.dtype)
    viewmat[:, 3, 3] = 1.0  # homogenous
    viewmat[:, :3, :3] = R_inv
    viewmat[:, :3, 3:4] = T_inv
    return viewmat

def num_sh_bases(degree: int) -> int:
    MAX_SH_DEGREE = 4
    assert degree <= MAX_SH_DEGREE, f"We don't support degree greater than {MAX_SH_DEGREE}."
    return (degree + 1) ** 2