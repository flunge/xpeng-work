import numpy as np
import torch
from plyfile import PlyData
from typing import Dict
import yaml

def load_rigid_ply(ply_path: str, new_instance_id=0, appearance_dim=8, device=torch.device('cpu')) -> Dict[str, torch.Tensor]:
    """
    从 PLY 文件加载 3D 高斯点，并返回与 RigidNodes 兼容的张量字典。

    Args:
        ply_path (str): PLY 文件路径
        new_instance_id (int): 新对象的 instance ID，用于 points_ids
        appearance_dim (int): appearance feature 维度（默认 8）
        device (str): 张量设备（'cpu' 或 'cuda'）

    Returns:
        dict: 包含以下 key 的 dict:
            '_means', '_scales', '_quats', '_opacities',
            '_features_dc', '_features_rest', '_appearance_features', 'points_ids'
    """
    plydata = PlyData.read(ply_path)
    vertex = plydata['vertex']

    # --- 1. 位置 (x, y, z) ---
    means = np.stack([vertex['x'], vertex['y'], vertex['z']], axis=1)  # [N, 3]

    # --- 2. 不透明度 (opacity) -> 转为 logit ---
    opacities = vertex['opacity'][..., np.newaxis]  # [N, 1]，假设已经是 logit

    # --- 3. 缩放 (scale_0, scale_1, scale_2) -> 转为 log ---
    scales = np.stack([vertex['scale_0'], vertex['scale_1'], vertex['scale_2']], axis=1)  # [N, 3]

    # --- 4. 旋转 (rot_0 ~ rot_3) ---
    quats = np.stack([vertex['rot_0'], vertex['rot_1'], vertex['rot_2'], vertex['rot_3']], axis=1)  # [N, 4]
    # 归一化四元数（安全起见）
    quats = quats / (np.linalg.norm(quats, axis=1, keepdims=True) + 1e-8)

    # --- 5. 球谐主色 (f_dc_0, f_dc_1, f_dc_2) ---
    features_dc = np.stack([vertex['f_dc_0'], vertex['f_dc_1'], vertex['f_dc_2']], axis=1)  # [N, 3]

    # --- 6. 高阶球谐 ---
    N = means.shape[0]
    SH_C = (3 + 1) ** 2  # SH degree 3 → 16 coeffs per channel, but commonly only DC + 1st used
    features_rest = np.zeros((N, 3, 3), dtype=np.float32)

    try:
        rest_names = [f'f_rest_{i}' for i in range(3 * 3)]  # 假设只存 3x3=9 个
        rest_vals = [vertex[name] for name in rest_names]
        features_rest_flat = np.stack(rest_vals, axis=1)  # [N, 9]
        features_rest = features_rest_flat.reshape(N, 3, 3)
    except (KeyError, IndexError):
        # 如果没有，保持为 0
        pass

    # --- 7. 外观特征（无来源，初始化为 0）---
    appearance_features = np.zeros((N, appearance_dim), dtype=np.float32) 

    # --- 8. points_ids（分配新 ID）---
    points_ids = np.full((N, 1), new_instance_id, dtype=np.int32)

    # --- 转为 PyTorch 张量 ---
    tensors = {
        '_means': torch.from_numpy(means).to(device),
        '_scales': torch.from_numpy(scales).to(device),
        '_quats': torch.from_numpy(quats).to(device),
        '_opacities': torch.from_numpy(opacities).to(device),
        '_features_dc': torch.from_numpy(features_dc).to(device),
        '_features_rest': torch.from_numpy(features_rest).to(device),
        '_appearance_features': torch.from_numpy(appearance_features).to(device),
        'points_ids': torch.from_numpy(points_ids).to(device),
    }

    return tensors


def mock_new_instance_tensors(
    num_frames,
    position_offset=[10.0, 0.0, 0.0],       # 正前方 10 米
    size=[4.8, 1.9, 1.5],                    # 长、宽、高（x, y, z）
    device=torch.device('cpu')
):
    """
    生成一个新的实例（旁车）的 instances_quats, instances_trans, instances_size, instances_fv。
    
    Args:
        num_frames (int): 总帧数（默认 299）
        new_instance_id (int): 新实例 ID（用于扩展维度，但张量本身不含 ID）
        position_offset (list): 旁车相对于自车的位置 [x, y, z]
        size (list): 实例尺寸 [length, width, height]
        device (str): 张量设备

    Returns:
        dict: 包含扩展后的四个张量（形状已 +1 实例维度）
    """
    # 1. 平移：所有帧都是同一个位置（正前方）
    trans = torch.tensor(position_offset, dtype=torch.float32, device=device)  # [3]
    instances_trans_new = trans.unsqueeze(0).expand(num_frames, 1, -1)         # [299, 1, 3]

    # 2. 旋转：单位四元数（无旋转）
    quat = torch.tensor([1.0, 0.0, 0.0, 0.0], dtype=torch.float32, device=device)  # [4]
    instances_quats_new = quat.unsqueeze(0).expand(num_frames, 1, -1)              # [299, 1, 4]

    # 3. 尺寸：静态尺寸
    size_tensor = torch.tensor(size, dtype=torch.float32, device=device)           # [3]
    instances_size_new = size_tensor.unsqueeze(0)                                  # [1, 3]

    # 4. 可见性/有效标志：全为 1（全程可见）
    instances_fv_new = torch.ones(num_frames, 1, dtype=torch.float32, device=device)  # [299, 1]

    return {
        "instances_trans": instances_trans_new,
        "instances_quats": instances_quats_new,
        "instances_size": instances_size_new,
        "instances_fv": instances_fv_new,
    }

def load_instance_tensors_from_yaml(
        yaml_path: str, 
        target_gid: int, 
        device=torch.device('cpu')
    ):
    """
    从 YAML 轨迹文件中加载指定 gid 的对象，生成 instances_* 张量（用于新增实例）。

    Args:
        yaml_path (str): YAML 文件路径
        target_gid (int): 要加载的对象 gid（如 999）
        device (str): 张量设备

    Returns:
        dict: {
            "instances_trans": [T, 1, 3],
            "instances_quats": [T, 1, 4],
            "instances_size": [1, 3],
            "instances_fv": [T, 1]
        }
    """
    with open(yaml_path, 'r') as f:
        data = yaml.safe_load(f)

    frames = data['results']['annotations']['frames']
    trans_list = []
    quat_list = []
    size_list = []

    found = False
    for frame in frames:
        objects = frame.get('objects', [])
        for obj in objects:
            if obj.get('gid') == target_gid:
                found = True
                trans = obj['translation']
                quat = obj['rotation']  # [w, x, y, z]
                size = obj['size']
                trans_list.append(trans)
                quat_list.append(quat)
                size_list.append(size)
                break
        else:
            # 如果某帧没有该对象，可选择跳过或报错
            raise ValueError(f"Frame {len(trans_list)} does not contain object with gid={target_gid}")

    if not found:
        raise ValueError(f"Object with gid={target_gid} not found in YAML!")

    # 转为 numpy
    trans_array = np.array(trans_list, dtype=np.float32)  # [T, 3]
    quat_array = np.array(quat_list, dtype=np.float32)    # [T, 4]
    size_array = np.array(size_list[0], dtype=np.float32) # 取第一帧尺寸 [3]

    # 转为 PyTorch 张量，并扩展实例维度（dim=1）
    instances_trans = torch.from_numpy(trans_array).unsqueeze(1).to(device)  # [T, 1, 3]
    instances_quats = torch.from_numpy(quat_array).unsqueeze(1).to(device)  # [T, 1, 4]
    instances_size = torch.from_numpy(size_array).unsqueeze(0).to(device)   # [1, 3]
    instances_fv = torch.ones(len(frames), 1, dtype=torch.float32, device=device)  # [T, 1]

    return {
        "instances_trans": instances_trans,
        "instances_quats": instances_quats,
        "instances_size": instances_size,
        "instances_fv": instances_fv,
    }