# Camera pose manipulation and trajectory generation.
from typing import Dict, Tuple

import math
import numpy as np
import torch
from scipy.spatial.transform import Rotation as R
from scipy.spatial.transform import Slerp
from gsplat.rendering import rasterization
from ..datasets.dataset_meta import DATASETS_CONFIG


def interpolate_poses(key_poses: torch.Tensor, target_frames: int) -> torch.Tensor:
    """
    Interpolate between key poses to generate a smooth trajectory.

    Args:
        key_poses (torch.Tensor): Tensor of shape (N, 4, 4) containing key camera poses.
        target_frames (int): Number of frames to interpolate.

    Returns:
        torch.Tensor: Interpolated poses of shape (target_frames, 4, 4).
    """
    device = key_poses.device
    key_poses = key_poses.cpu().numpy()

    # Separate translation and rotation
    translations = key_poses[:, :3, 3]
    rotations = key_poses[:, :3, :3]

    # Create time array
    times = np.linspace(0, 1, len(key_poses))
    target_times = np.linspace(0, 1, target_frames)

    # Interpolate translations
    interp_translations = np.stack([np.interp(target_times, times, translations[:, i]) for i in range(3)], axis=-1)

    # Interpolate rotations using Slerp
    key_rots = R.from_matrix(rotations)
    slerp = Slerp(times, key_rots)
    interp_rotations = slerp(target_times).as_matrix()

    # Combine interpolated translations and rotations
    interp_poses = np.eye(4)[None].repeat(target_frames, axis=0)
    interp_poses[:, :3, :3] = interp_rotations
    interp_poses[:, :3, 3] = interp_translations

    return torch.tensor(interp_poses, dtype=torch.float32, device=device)


def look_at_rotation(direction: torch.Tensor, up: torch.Tensor = torch.tensor([0.0, 0.0, 1.0])) -> torch.Tensor:
    """Calculate rotation matrix to look at a specific direction."""
    front = torch.nn.functional.normalize(direction, dim=-1)
    right = torch.nn.functional.normalize(torch.cross(front, up), dim=-1)
    up = torch.cross(right, front)
    rotation_matrix = torch.stack([right, up, -front], dim=-1)
    return rotation_matrix


def get_interp_novel_trajectories(
    per_cam_poses: Dict[int, torch.Tensor],
    traj_type: dict,
    target_frames: int = 100,
    cam2ego: Dict[int, torch.Tensor] = None,
    ego2worlds: Dict[int, torch.Tensor] = None,
) -> torch.Tensor:
    standardized_trajectory_generators = {
        "front_center_interp": front_center_interp,
        "s_curve": s_curve,
        "three_key_poses": three_key_poses_trajectory,
    }

    if traj_type.type in standardized_trajectory_generators:
        assert False, "Standardized trajectory generations haven't been supported yet."
        original_frames = per_cam_poses[list(per_cam_poses.keys())[0]].shape[0]
        return standardized_trajectory_generators[traj_type.type](per_cam_poses, original_frames, target_frames)

    custom_trajectory_generators = {
        "relative_lane_shift": relative_lane_shift,
        "absolute_poses": absolute_poses,
    }

    if traj_type.type in custom_trajectory_generators:
        return custom_trajectory_generators[traj_type.type](cam2ego, ego2worlds, traj_type)

    raise ValueError(f"Unknown trajectory type: {traj_type}")


def front_center_interp(
    per_cam_poses: Dict[int, torch.Tensor],
    original_frames: int,
    target_frames: int,
    num_loops: int = 1,
) -> torch.Tensor:
    """Interpolate key frames from the front center camera."""
    assert 0 in per_cam_poses.keys(), "Front center camera (ID 0) is required for front_center_interp"
    key_poses = per_cam_poses[0][:: original_frames // 4]  # Select every 4th frame as key frame
    return interpolate_poses(key_poses, target_frames)


def s_curve(
    per_cam_poses: Dict[int, torch.Tensor],
    original_frames: int,
    target_frames: int,
) -> torch.Tensor:
    """Create an S-shaped trajectory using the front three cameras."""
    assert all(
        cam in per_cam_poses.keys() for cam in [0, 1, 2]
    ), "Front three cameras (IDs 0, 1, 2) are required for s_curve"
    key_poses = torch.cat(
        [
            per_cam_poses[0][0:1],
            per_cam_poses[1][original_frames // 4 : original_frames // 4 + 1],
            per_cam_poses[0][original_frames // 2 : original_frames // 2 + 1],
            per_cam_poses[2][3 * original_frames // 4 : 3 * original_frames // 4 + 1],
            per_cam_poses[0][-1:],
        ],
        dim=0,
    )
    return interpolate_poses(key_poses, target_frames)


def three_key_poses_trajectory(
    per_cam_poses: Dict[int, torch.Tensor],
    original_frames: int,
    target_frames: int,
) -> torch.Tensor:
    """
    Create a trajectory using three key poses:
    1. First frame of front center camera
    2. Middle frame with interpolated rotation and position from camera 1 or 2
    3. Last frame of front center camera

    The rotation of the middle pose is calculated using Slerp between
    the start frame and the middle frame of camera 1 or 2.

    Args:
        dataset_type (str): Type of the dataset (e.g., "waymo", "pandaset", etc.).
        per_cam_poses (Dict[int, torch.Tensor]): Dictionary of camera poses.
        original_frames (int): Number of original frames.
        target_frames (int): Number of frames in the output trajectory.

    Returns:
        torch.Tensor: Trajectory of shape (target_frames, 4, 4).
    """
    assert 0 in per_cam_poses.keys(), "Front center camera (ID 0) is required"
    assert 1 in per_cam_poses.keys() or 2 in per_cam_poses.keys(), "Either camera 1 or camera 2 is required"

    # First key pose: First frame of front center camera
    start_pose = per_cam_poses[0][0]
    key_poses = [start_pose]

    # Select camera for middle frame
    middle_frame = int(original_frames // 2)
    chosen_cam = np.random.choice([1, 2])

    middle_pose = per_cam_poses[chosen_cam][middle_frame]

    # Calculate interpolated rotation for middle pose
    start_rotation = R.from_matrix(start_pose[:3, :3].cpu().numpy())
    middle_rotation = R.from_matrix(middle_pose[:3, :3].cpu().numpy())
    slerp = Slerp([0, 1], R.from_quat([start_rotation.as_quat(), middle_rotation.as_quat()]))
    interpolated_rotation = slerp(0.5).as_matrix()

    # Create middle key pose with interpolated rotation and original translation
    middle_key_pose = torch.eye(4, device=start_pose.device)
    middle_key_pose[:3, :3] = torch.tensor(interpolated_rotation, device=start_pose.device)
    middle_key_pose[:3, 3] = middle_pose[:3, 3]  # Keep the original translation
    key_poses.append(middle_key_pose)

    # Third key pose: Last frame of front center camera
    key_poses.append(per_cam_poses[0][-1])

    # Stack the key poses and interpolate
    key_poses = torch.stack(key_poses)
    return interpolate_poses(key_poses, target_frames)


def relative_lane_shift(
    cam2egos: Dict[int, torch.Tensor] = None, ego2worlds: Dict[int, torch.Tensor] = None, traj_type: dict = None
) -> torch.Tensor:
    """
    Generate a trajectory by shifting the ego vehicle along the x-axis.
    Currently only support x-axis shift.
    """
    assert traj_type.direction == "x"
    dis_shift = traj_type.distance

    cam_poses = []
    for cam_id in cam2egos:
        cam2ego = cam2egos[cam_id].clone().detach()
        cam2ego[1, 3] += dis_shift
        for ego2world in ego2worlds[cam_id]:
            cam_pose = ego2world @ cam2ego
            cam_poses.append(cam_pose)

    return torch.stack(cam_poses)


def absolute_poses(
    cam2egos: Dict[int, torch.Tensor] = None, ego2worlds: Dict[int, torch.Tensor] = None, traj_type: dict = None
) -> torch.Tensor:
    raise NotImplementedError("Absolute trajectory generation is not implemented yet.")


def rotate_camera_around_x(camera2world: torch.Tensor, angle: float = -math.pi / 2) -> torch.Tensor:
    """
    将相机绕X轴旋转-90度（pitch down）。
    
    原始坐标系: x向前方，y向左边，z向天空
    目标: 绕X轴旋转-90度让相机向下俯视
    
    Args:
        camera2world (torch.Tensor): 4x4的相机到世界变换矩阵
        
    Returns:
        torch.Tensor: 修改后的4x4相机到世界变换矩阵
    """    
    # 提取旋转和平移
    R = camera2world[:3, :3]
    t = camera2world[:3, 3]

    # 绕X轴旋转-90度的旋转矩阵
    pitch_angle = angle  # -90度
    cos_pitch = math.cos(pitch_angle)
    sin_pitch = math.sin(pitch_angle)
    
    # 绕X轴旋转矩阵
    pitch_rotation = torch.tensor([
        [1, 0, 0],
        [0, cos_pitch, -sin_pitch],
        [0, sin_pitch, cos_pitch]
    ], dtype=torch.float32, device=camera2world.device)
    
    # 应用pitch旋转
    new_R = torch.mm(R, pitch_rotation)

    # 构造新的4x4相机到世界矩阵
    new_camera2world = torch.eye(4, dtype=torch.float32, device=camera2world.device)
    new_camera2world[:3, :3] = new_R
    new_camera2world[:3, 3] = t

    return new_camera2world


def render_camera_downwards(
    camera_info,
    image_info, 
    gaussians, 
) -> dict:
    """
    使用向下俯视的相机角度进行渲染，模仿xpeng_novel_utils.py中的render_camera_downwards函数。
    
    Args:
        camera_info: 相机信息对象，包含camera_to_world矩阵
        gaussians: 高斯模型对象
        exclude_models: 要排除的模型列表，默认为排除除ground外的所有模型
        
    Returns:
        dict: 渲染结果包
    """
    # 获取原始相机到世界变换矩阵
    c2w = camera_info.camera_to_world
    new_camera2world = rotate_camera_around_x(c2w)
    
    # 创建新的相机信息对象
    new_camera_info = camera_info.detach()  # 创建副本
    new_camera_info.camera_to_world = new_camera2world

    # 降低fov到原来的2/3，长宽也按比例缩小
    if camera_info.camera_name != "cam2":
        new_camera_info.intrinsic = new_camera_info.intrinsic
        new_camera_info.width = int(new_camera_info.width)
        new_camera_info.height = int(new_camera_info.height)
    else:
        new_camera_info.intrinsic = new_camera_info.intrinsic * 2 / 3
        new_camera_info.width = int(new_camera_info.width * 2 / 3)
        new_camera_info.height = int(new_camera_info.height * 2 / 3)

    # 执行渲染
    renders, alphas, _ = rasterization(
        means=gaussians.means,
        quats=gaussians.quats,
        scales=gaussians.scales,
        opacities=gaussians.opacities.squeeze(),
        colors=gaussians.rgbs,
        viewmats=torch.linalg.inv(new_camera_info.camera_to_world)[None, ...],  # [C, 4, 4]
        Ks=new_camera_info.intrinsic[None, ...],  # [C, 3, 3]
        width=new_camera_info.width,
        height=new_camera_info.height,
        packed=False,
        backgrounds=torch.zeros(3).to(torch.device("cuda"))[None, ...],
        absgrad=True,
        sparse_grad=False,
        rasterize_mode="classic",
    )
    renders = torch.clamp(renders[0], max=1.0)
    alphas = alphas[0].squeeze(-1)[..., None]
    results = {"rgb_gaussians": renders, "opacity": alphas}    
    return results

def get_camera_original_size_by_vehicle_model(dataset_name: str, cam_id: int, vehicle_model: int = None) -> Tuple[int, int]:
    original_size_config  = DATASETS_CONFIG[dataset_name][cam_id]["original_size"]
    
    if dataset_name != "xpeng":
        # 其他数据集，直接使用配置的分辨率
        return original_size_config

    if not isinstance(original_size_config, dict):
        return original_size_config

    # 根据车型枚举获取对应的key
    try:
        from ..datasets.xpeng.constants import VehicleModel, VEHICLE_MODEL_CATEGORY_MAP
        vehicle_enum = VehicleModel(vehicle_model)
        vehicle_category = VEHICLE_MODEL_CATEGORY_MAP.get(vehicle_enum, "default")
        
        # 从original_size_config中获取对应类别的尺寸
        return original_size_config.get(vehicle_category, original_size_config.get("default", (1080, 1920)))
    except (ValueError, KeyError):
        return original_size_config.get("default", (1080, 1920))