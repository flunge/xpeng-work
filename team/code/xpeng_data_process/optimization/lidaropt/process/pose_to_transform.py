import argparse
import os
import json
import numpy as np
from scipy.spatial.transform import Rotation as R


def read_colmap_images_txt(path):
    """
    读取 COLMAP 的 images.txt 文件，返回图像位姿和2D-3D匹配信息
    
    Args:
        path: images.txt 文件路径
        
    Returns:
        dict: 包含图像ID和位姿信息的字典
    """
    images_info = {}
    
    with open(path, 'r') as f:
        lines = f.readlines()

    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()

        if line == '' or line.startswith('#'):
            idx += 1
            continue

        # 第一行：IMAGE_ID QW QX QY QZ TX TY TZ CAMERA_ID IMAGE_NAME
        parts = line.split()
        image_id = int(parts[0])
        qw, qx, qy, qz = map(float, parts[1:5])
        tx, ty, tz = map(float, parts[5:8])
        camera_id = int(parts[8])
        image_name = parts[9]

        images_info[image_id] = {
            'image_name': image_name,
            'camera_id': camera_id,
            'quaternion': np.array([qw, qx, qy, qz]),
            'translation': np.array([tx, ty, tz]),
        }

        idx += 1

    return images_info


def quaternions_and_translations_to_matrices(quats, trans):
    """
    将四元数和平移向量转换为4x4变换矩阵
    
    Args:
        quats: (N, 4) 四元数数组 [qw, qx, qy, qz]
        trans: (N, 3) 平移向量数组 [tx, ty, tz]
        
    Returns:
        numpy.ndarray: (N, 4, 4) 4x4变换矩阵数组
        
    Raises:
        AssertionError: 当输入维度不匹配时
    """
    assert quats.shape[1] == 4 and trans.shape[1] == 3, "四元数应为4维，平移向量应为3维"
    assert quats.shape[0] == trans.shape[0], "四元数和平移向量的数量必须相同"

    # 转换为 scipy 的四元数格式 [qx, qy, qz, qw]
    quat_xyzw = np.roll(quats, shift=-1, axis=1)

    rot = R.from_quat(quat_xyzw)
    R_all = rot.as_matrix()  # (N, 3, 3)

    N = quats.shape[0]
    T_all = np.eye(4)[None, :, :].repeat(N, axis=0)  # (N, 4, 4)

    T_all[:, :3, :3] = R_all
    T_all[:, :3, 3] = trans

    return T_all


def load_transform_data(data_path, transform_name):
    """
    加载transform0.json文件
    
    Args:
        data_path: 数据根目录路径
        
    Returns:
        dict: 变换数据字典
    """
    transform_json_path = os.path.join(data_path, transform_name)
    
    with open(transform_json_path, 'r') as f:
        transform_data = json.load(f)
    
    return transform_data


def create_frame_info_dict(transform_data):
    """
    创建帧信息字典，以文件路径为键
    
    Args:
        transform_data: 变换数据字典
        
    Returns:
        dict: 帧信息字典
    """
    frame_info_dict = {}
    
    for item in transform_data["frames"]:
        frame_info_dict[item["file_path"]] = item
    
    return frame_info_dict


def process_poses_and_update_transforms(data_path, frame_info_dict, transform_data):
    """
    处理位姿数据并更新变换矩阵
    
    Args:
        data_path: 数据根目录路径
        frame_info_dict: 帧信息字典
        
    Returns:
        dict: 更新后的帧信息字典
    """
    # 从transform_data中获取image name到idx的映射
    sorted_transform_data = sorted(transform_data["frames"], key=lambda x: int(x["timestamp"]))
    cam_list = list(transform_data["sensor_params"]["camera_order"])
    image_name_list = []
    for cam in cam_list:
        for i in sorted_transform_data:
            if i["camera"] == cam:
                image_name_list.append(i["file_path"].replace("images/", ""))
    
    # 读取修正后的位姿
    fixed_pose_path = os.path.join(data_path, "colmap/triangulated/aligned", "images.txt")
    fixed_poses_dict = read_colmap_images_txt(fixed_pose_path)
    
    # 提取修正后的四元数和平移向量
    all_fixed_quats = []
    all_fixed_trans = []
    image_names = []
    
    for key in fixed_poses_dict.keys():
        quaternion = fixed_poses_dict[key]["quaternion"]
        translation = fixed_poses_dict[key]["translation"]
        
        all_fixed_quats.append(quaternion)
        all_fixed_trans.append(translation)
        image_names.append(image_name_list[key - 1])
    
    # 转换为numpy数组
    fixed_quats = np.stack(all_fixed_quats, axis=0)
    fixed_trans = np.stack(all_fixed_trans, axis=0)
    
    # 转换为4x4变换矩阵 (w2c)
    fixed_transforms = quaternions_and_translations_to_matrices(fixed_quats, fixed_trans)
    
    # 更新变换矩阵
    for idx in range(len(image_names)):
        image_name = image_names[idx]
        file_path = "images/" + image_name
        
        # 计算c2w变换矩阵 (取逆)
        fixed_transform = np.linalg.inv(fixed_transforms[idx])
        frame_info_dict[file_path]["transform_matrix"] = fixed_transform.tolist()
    
    return frame_info_dict


def save_updated_transform_data(transform_data, frame_info_dict, data_path):
    """
    保存更新后的变换数据
    
    Args:
        transform_data: 原始变换数据
        frame_info_dict: 更新后的帧信息字典
        data_path: 数据根目录路径
    """
    # 更新frames数据
    transform_data["frames"] = list(frame_info_dict.values())
    
    # 保存到新文件
    new_transform_json_path = os.path.join(data_path, "transform_ego_fix.json")
    
    with open(new_transform_json_path, 'w') as f:
        json.dump(transform_data, f, indent=4)
    
    print(f"更新后的变换数据已保存到: {new_transform_json_path}")


def compute_egopose_from_transform_data(transform_data):
    """
    从变换数据中计算ego位姿
    """
    egopose_data = {}
    sorted_transform_data = sorted(transform_data["frames"], key=lambda x: int(x["timestamp"]))
    cam0_to_rig = np.array(transform_data["sensor_params"]["cam0"]["extrinsic"])
    rig_to_cam0 = np.linalg.inv(cam0_to_rig)
    for transform_item in sorted_transform_data:
        if transform_item["camera"] == "cam0":
            cam0_to_world = np.array(transform_item["transform_matrix"])
            rig_to_world = cam0_to_world @ rig_to_cam0
            timestamp = str(transform_item["timestamp"])
            egopose_data[timestamp] = rig_to_world.tolist()

    return egopose_data


def main(data_path, transform_name):
    """
    主函数：执行位姿到变换矩阵的转换流程
    
    Args:
        data_path: 数据根目录路径
        transform_name: 变换数据文件名
    """
    print(f"开始处理数据: {data_path}")
    
    # 加载变换数据
    transform_data = load_transform_data(data_path, transform_name)
    
    # 创建帧信息字典
    frame_info_dict = create_frame_info_dict(transform_data)
    print(f"创建帧信息字典，共{len(frame_info_dict)}帧")
    
    # 处理位姿并更新变换矩阵
    frame_info_dict = process_poses_and_update_transforms(data_path, frame_info_dict, transform_data)
    print("位姿处理完成，变换矩阵已更新")
    
    # 保存更新后的数据
    save_updated_transform_data(transform_data, frame_info_dict, data_path)
    
    # compute egopose from transform_data with cam0 and save to json
    localpose_data = compute_egopose_from_transform_data(transform_data)
    with open(os.path.join(data_path, "localpose_ego_fix.json"), "w") as f:
        json.dump(localpose_data, f, indent=4)
    
    print("处理完成！")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='将COLMAP位姿转换为变换矩阵格式')
    parser.add_argument('--data_root', required=True, help='数据根目录路径')
    
    args = parser.parse_args()
    
    # 执行主函数
    main(args.data_root)
