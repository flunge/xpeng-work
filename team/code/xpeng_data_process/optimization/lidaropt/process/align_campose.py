import argparse
import os
import numpy as np
from scipy.spatial.transform import Rotation as R
from scipy.optimize import least_squares
import json

# OpenCV to Dataset coordinate transformation
# opencv coordinate system: x right, y down, z front
# waymo coordinate system: x front, y left, z up
OPENCV2DATASET = np.array(
    [[0, 0, 1, 0], [-1, 0, 0, 0], [0, -1, 0, 0], [0, 0, 0, 1]]
)

def gen_pose_quat(translation0,translation1,rot_angles0,rot_angles1,n_pose):
    r0 = R.from_euler('zyx', [rot_angles0[0], rot_angles0[1], rot_angles0[2]], degrees=True)
    r1 = R.from_euler('zyx', [rot_angles1[0], rot_angles1[1], rot_angles1[2]], degrees=True)
    rot_quat0= r0.as_quat()
    rot_quat1= r1.as_quat()
    traj=np.zeros((n_pose+1,7))
    for i in range(0,n_pose+1):
        traj[i,3:7]= (rot_quat1-rot_quat0)/float(n_pose)*float(i) +rot_quat0
        traj[i,0:3]= (translation1-translation0)/float(n_pose)*float(i)+translation0
    return traj

def pos_quat2SE(quat_data,do_opencv2lidar):
    SO = R.from_quat(quat_data[3:7]).as_matrix()
    SE = np.matrix(np.eye(4))
    SE[0:3,0:3] = np.matrix(SO)
    SE[0:3,3]   = np.matrix(quat_data[0:3]).T
    
    # w2c to c2w
    SE= np.linalg.inv(SE)
    
    if do_opencv2lidar:
        # opencv2lidar
        SE= np.matmul( OPENCV2DATASET,SE)
        
    SE = np.array(SE[0:3,:]).reshape(1,12)
    return SE

def pos_quats2SEs(quat_datas,do_opencv2lidar):
    data_len = quat_datas.shape[0]
    SEs = np.zeros((data_len,12))
    for i_data in range(0,data_len):
        SE = pos_quat2SE(quat_datas[i_data,:],do_opencv2lidar)
        SEs[i_data,:] = SE
    return SEs

def comp_w2cs(c2ws):
    w2cs = np.zeros((len(c2ws),7))
    for i in range(0, len(c2ws)):
        c2w1 = np.matrix(np.eye(4))
        c2w1[:3,:] = c2ws[i,:].reshape(3,4)
        w2c1 = np.linalg.inv(c2w1)
        r = R.from_matrix(w2c1[:3,:3])
        r_quat = r.as_quat()
        w2cs[i,3:7] = r_quat
        w2cs[i,0:3] = w2c1[:3,3].T
    return w2cs

def write_images(scene_dir, w2cs, n_pose):
    # cams=[0,2,3,4,5,6,7]
    fl1 = open(scene_dir+'/images.txt', 'w')
    fl1.writelines('# Image list with two lines of data per image:\n')
    fl1.writelines('#   IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME\n')
    fl1.writelines('#   POINTS2D[] as (X, Y, POINT3D_ID)\n')
    fl1.writelines('# Number of images: 4, mean observations per image: 1674.2\n')
    for it in range(0, len(w2cs)):
        tr= w2cs[it]
        cam_id= round( (it-(it % n_pose))/n_pose )
        ls1 =str(it+1) +' '+str(tr[6])+' '+  str(tr[3]) + ' ' + str(tr[4]) + ' ' + str(tr[5]) + ' ' + str(tr[0]) + ' ' + str(tr[1]) + ' ' + str(tr[2]) +' '+str(cam_id+1)+' '+str(it).zfill(4) +'.png\n' # png
        fl1.writelines(ls1)
        fl1.writelines('\n')
    fl1.close()


def pose_log(T):
    """
    将 SE(3) 矩阵变换成 6D 向量（平移 + 旋转向量）
    """
    rot = R.from_matrix(T[:3, :3])
    omega = rot.as_rotvec()
    trans = T[:3, 3]
    return np.concatenate([trans, omega])

def pose_inv(T):
    """
    计算 4x4 SE(3) 变换的逆
    """
    T_inv = np.eye(4)
    R_inv = T[:3, :3].T
    T_inv[:3, :3] = R_inv
    T_inv[:3, 3] = -R_inv @ T[:3, 3]
    return T_inv

def se3_cost(x, A, B):
    """
    残差函数: log(T * B_i^-1 * A_i)，每个返回一个 6D 残差
    """
    t = x[:3]
    r = x[3:6]
    
    T = np.eye(4)
    T[:3, :3] = R.from_rotvec(r).as_matrix()
    T[:3, 3] = t

    residuals = []
    for Ai, Bi in zip(A, B):
        err = pose_inv(Bi) @ T @ Ai
        residuals.append(pose_log(err))  # shape: (6,)
    
    return np.concatenate(residuals)

def scale_shift_cost(x, A, B):
    
    t = x[:3]
    r = x[3:6]
    k = x[6]
    
    T = np.eye(4)
    T[:3, :3] = R.from_rotvec(r).as_matrix()
    T[:3, 3] = t

    residuals = []
    for Ai, Bi in zip(A, B):
        kAi=Ai.copy()
        kAi[:3]=k*Ai[:3]
        err = T @ kAi - Bi
        residuals.append(err[:3])  # shape: (3,)
    
    return np.concatenate(residuals)

def align_poses_se3(A, B):
    """
    给定 A, B ∈ R^{N x 4 x 4}，返回最佳刚性变换 T(4x4), 使得 T @ A ≈ B
    """
    assert A.shape == B.shape and A.shape[1:] == (4, 4)

    x0 = np.zeros(6)  # 初始估计：无旋转、无平移
    result = least_squares(se3_cost, x0, args=(A, B), method='lm')

    t_opt = result.x[:3]
    r_opt = result.x[3:]
    T_opt = np.eye(4)
    T_opt[:3, :3] = R.from_rotvec(r_opt).as_matrix()
    T_opt[:3, 3] = t_opt

    return T_opt

def align_scale_shift(A, B):
    """
    给定A,B ∈ R^{N x 4}, 返回最佳变换 T(4x4),k, 使得 T @ (k*A) ≈ B
    """
    
    x0 = np.zeros(7)  # 初始估计：无旋转、无平移
    x0[6]=1
    result = least_squares(scale_shift_cost, x0, args=(A, B), method='lm')

    t_opt = result.x[:3]
    r_opt = result.x[3:6]
    k_opt = result.x[6]
    T_opt = np.eye(4)
    T_opt[:3, :3] = R.from_rotvec(r_opt).as_matrix()
    T_opt[:3, 3] = t_opt

    return T_opt,k_opt


def load_transform_data(data_root, transform_name):
    """
    加载transform0.json和localpose.json数据
    
    Args:
        data_root: 数据根目录
        
    Returns:
        tuple: (transform_json, localpose, actual_timestamps, transform_matrix, cam_to_ego, n_pose)
    """
    transform_json = json.load(open(os.path.join(data_root, transform_name)))
    localpose = json.load(open(os.path.join(data_root, "localpose.json")))
    actual_timestamps = sorted([int(k) for k in localpose.keys()])
    
    transform_matrix = {}
    for frame in transform_json["frames"]:
        if frame["camera"] == "cam0": 
            transform_matrix[frame["timestamp"]] = frame["transform_matrix"]
    
    cam_to_ego = transform_json["sensor_params"]["cam0"]["extrinsic"]
    n_pose = len(transform_matrix)
    
    return transform_json, localpose, actual_timestamps, transform_matrix, cam_to_ego, n_pose


def extract_camera_poses(transform_matrix, actual_timestamps, cam_to_ego, n_pose):
    """
    提取相机位姿数据
    
    Args:
        transform_matrix: 变换矩阵字典
        actual_timestamps: 实际时间戳列表
        cam_to_ego: 相机到ego的变换矩阵
        n_pose: 位姿数量
        
    Returns:
        tuple: (cam_to_worlds, ego_to_worlds)
    """
    cam_to_worlds = []
    for t in range(n_pose):
        cam_to_worlds.append(transform_matrix[actual_timestamps[t]])
    
    cam_to_worlds = np.stack(cam_to_worlds, axis=0)
    cam_to_ego_inv = np.linalg.inv(cam_to_ego)
    
    ego_to_worlds = []
    for cam_to_world in cam_to_worlds:
        ego_to_world = cam_to_world @ cam_to_ego_inv
        ego_to_worlds.append(ego_to_world)
    
    ego_to_worlds = np.stack(ego_to_worlds, axis=0)
    
    return cam_to_worlds, ego_to_worlds, cam_to_ego_inv


def load_camera_poses_from_file(campose_dir, n_pose):
    """
    从images.txt文件加载相机位姿
    
    Args:
        campose_dir: 相机位姿目录
        n_pose: 位姿数量
        
    Returns:
        tuple: (traj_0_fixed, c2ws_0_fixed, fixed_transforms)
    """
    fixed_pose_path = os.path.join(campose_dir, "images.txt")
    traj_0_fixed = np.zeros((n_pose, 7))
    
    with open(fixed_pose_path, 'r') as f:
        for t in range(n_pose):
            metastr = f.readline()
            strlist = metastr.split(' ')
            traj_0_fixed[t, 3:7] = [float(strlist[2]), float(strlist[3]), float(strlist[4]), float(strlist[1])]
            traj_0_fixed[t, 0:3] = [float(strlist[5]), float(strlist[6]), float(strlist[7])]
            metastr = f.readline()
    
    print('读取cam_0位姿完成.')
    
    do_opencv2lidar_fixed = True
    c2ws_0_fixed = pos_quats2SEs(traj_0_fixed, do_opencv2lidar_fixed)
    
    fixed_transforms = np.eye(4)[None, :, :].repeat(n_pose, axis=0)
    for i in range(n_pose):
        fixed_transforms[i, :3, :] = c2ws_0_fixed[i, :].reshape(3, 4)
    
    return traj_0_fixed, c2ws_0_fixed, fixed_transforms


def select_motion_frame_indices(translations, num_required, min_displacement=1.0,
                                relax_factor=0.5, max_relaxations=5):
    """
    根据位移阈值挑选一组用于对齐的帧索引。

    Args:
        translations: np.ndarray, shape (N, 3)，平移序列
        num_required: 需要的帧数量
        min_displacement: 相邻被选帧之间的最小位移
        relax_factor: 每次放宽阈值的缩放系数
        max_relaxations: 最大放宽次数

    Returns:
        tuple(list[int], float, bool): (索引列表, 使用的阈值, 是否触发回退)
    """
    translations = np.asarray(translations)
    total_frames = translations.shape[0]
    if total_frames == 0:
        return [], 0.0, True
    num_required = max(1, min(num_required, total_frames))

    def collect_indices(threshold):
        if threshold <= 0:
            return list(range(num_required))
        selected = [0]
        last_idx = 0
        for idx in range(1, total_frames):
            step = translations[idx] - translations[last_idx]
            if np.linalg.norm(step) >= threshold:
                selected.append(idx)
                last_idx = idx
                if len(selected) == num_required:
                    break
        return selected

    threshold = max(min_displacement, 0.0)
    best_indices = []
    for _ in range(max_relaxations):
        indices = collect_indices(threshold)
        if len(indices) >= num_required:
            return indices[:num_required], threshold, False
        if len(indices) > len(best_indices):
            best_indices = indices
        threshold *= max(relax_factor, 1e-3)

    # 回退: 使用已经找到的索引并补齐至 num_required
    fallback_indices = []
    seen = set()
    for idx in best_indices:
        if idx not in seen:
            fallback_indices.append(idx)
            seen.add(idx)
    for idx in range(total_frames):
        if idx not in seen:
            fallback_indices.append(idx)
            seen.add(idx)
        if len(fallback_indices) == num_required:
            break
    return fallback_indices[:num_required], 0.0, True


def align_camera_poses_shift(
    fixed_transforms,
    cam_to_worlds,
    num_align,
    cam_to_ego_inv,
    min_displacement=1.0,
    relax_factor=0.5,
    max_relaxations=5,
):
    """
    对齐相机位姿（位移采样版本）
    
    Args:
        fixed_transforms: 固定的变换矩阵
        cam_to_worlds: 相机到世界的变换矩阵
        num_align: 对齐数量
        cam_to_ego_inv: 相机到ego的逆变换矩阵
        min_displacement: 位移采样阈值（单位：米）
        relax_factor: 位移阈值放宽系数
        max_relaxations: 位移阈值最多放宽次数
        
    Returns:
        tuple: (T, k, cam0_to_worlds_fixed, ego_to_worlds_fixed)
    """
    # 参考位姿转化为首帧为基准
    cam_to_worlds0 = cam_to_worlds.copy()
    cam_to_worlds = np.linalg.inv(cam_to_worlds0[0, :, :]) @ cam_to_worlds0
    
    # 固定位姿转化为首帧为基准
    fixed_transforms0 = fixed_transforms.copy()
    fixed_transforms = np.linalg.inv(fixed_transforms0[0, :, :]) @ fixed_transforms0
    
    translations = cam_to_worlds[:, :3, 3]
    motion_indices, used_threshold, fallback_used = select_motion_frame_indices(
        translations,
        num_align,
        min_displacement=min_displacement,
        relax_factor=relax_factor,
        max_relaxations=max_relaxations,
    )
    if len(motion_indices) < 2:
        raise RuntimeError("[ERROR][DPVO] 位移采样结果不足以完成对齐，请检查输入数据。")

    if fallback_used:
        raise Warning(f"[ERROR][DPVO] 位移阈值筛帧未满足要求，无效场景。")
    else:
        print(
            f"[INFO][DPVO] 位移筛帧阈值: {used_threshold:.3f} m, "
            f"使用帧数: {len(motion_indices)}, [INFO][DPVO] 索引列表: {motion_indices}"
        )

    selected_fixed = fixed_transforms[motion_indices, :, 3]
    selected_cam = cam_to_worlds[motion_indices, :, 3]

    # 最小二乘求解T,k, 使得 T @ (k*A) ≈ B
    T, k = align_scale_shift(selected_fixed, selected_cam)
    
    k_fixed_transforms = fixed_transforms.copy()
    k_fixed_transforms[:, :3, 3] *= k
    
    cam0_to_worlds_fixed = fixed_transforms.copy()
    for i in range(len(fixed_transforms)):
        cam0_to_worlds_fixed[i, :, 3] = k_fixed_transforms[i, :, 3]
    
    # 坐标系变换, 转化到ref cam_to_worlds的坐标系
    cam0_to_worlds_fixed = cam_to_worlds0[0, :, :] @ cam0_to_worlds_fixed
    ego_to_worlds_fixed = cam0_to_worlds_fixed @ cam_to_ego_inv
    
    return T, k, cam0_to_worlds_fixed, ego_to_worlds_fixed


def align_camera_poses(fixed_transforms, cam_to_worlds, num_align, cam_to_ego_inv):
    """
    对齐相机位姿（连续帧版本）

    Args:
        fixed_transforms: 固定的变换矩阵
        cam_to_worlds: 相机到世界的变换矩阵
        num_align: 对齐数量
        cam_to_ego_inv: 相机到ego的逆变换矩阵

    Returns:
        tuple: (T, k, cam0_to_worlds_fixed, ego_to_worlds_fixed)
    """
    cam_to_worlds0 = cam_to_worlds.copy()
    cam_to_worlds = np.linalg.inv(cam_to_worlds0[0, :, :]) @ cam_to_worlds0

    fixed_transforms0 = fixed_transforms.copy()
    fixed_transforms = np.linalg.inv(fixed_transforms0[0, :, :]) @ fixed_transforms0

    T, k = align_scale_shift(
        fixed_transforms[:num_align, :, 3], cam_to_worlds[:num_align, :, 3]
    )

    k_fixed_transforms = fixed_transforms.copy()
    k_fixed_transforms[:, :3, 3] *= k

    cam0_to_worlds_fixed = fixed_transforms.copy()
    for i in range(len(fixed_transforms)):
        cam0_to_worlds_fixed[i, :, 3] = k_fixed_transforms[i, :, 3]

    cam0_to_worlds_fixed = cam_to_worlds0[0, :, :] @ cam0_to_worlds_fixed
    ego_to_worlds_fixed = cam0_to_worlds_fixed @ cam_to_ego_inv

    return T, k, cam0_to_worlds_fixed, ego_to_worlds_fixed


def generate_all_camera_poses(cam0_to_worlds_fixed, ego_to_worlds_fixed, transform_json, cam_list, n_pose):
    """
    生成所有相机的位姿
    
    Args:
        cam0_to_worlds_fixed: cam0的固定世界位姿
        ego_to_worlds_fixed: ego的固定世界位姿
        transform_json: 变换JSON数据
        cam_list: 相机列表
        n_pose: 位姿数量
        
    Returns:
        numpy.ndarray: 所有相机的世界位姿
    """
    cam_to_worlds_fixed = cam0_to_worlds_fixed
    
    for t in range(1, len(cam_list)):
        cam_c = 'cam' + str(cam_list[t])
        cam_to_ego_c = transform_json["sensor_params"][cam_c]["extrinsic"]
        cam_to_worlds_fixed_c = ego_to_worlds_fixed @ cam_to_ego_c
        cam_to_worlds_fixed = np.concatenate([cam_to_worlds_fixed, cam_to_worlds_fixed_c.copy()], axis=0)
    
    return cam_to_worlds_fixed


def main(data_root, campose_dir, num_align, transform_name):
    """
    主函数：执行相机位姿对齐流程
    
    Args:
        data_root: 数据根目录
        campose_dir: 相机位姿目录
        num_align: 对齐数量
        transform_name: 变换数据文件名
    """
    cam_list = [0, 2, 3, 4, 5, 6, 7]
    
    # 创建输出目录
    aligned_campose_dir = os.path.join(data_root, 'colmap/triangulated/aligned')
    os.makedirs(aligned_campose_dir, exist_ok=True)
    
    print(f"开始处理，对齐数量: {num_align}")
    
    # 加载变换数据
    transform_json, localpose, actual_timestamps, transform_matrix, cam_to_ego, n_pose = \
        load_transform_data(data_root, transform_name)
    print(f"总位姿数量: {n_pose}")
    
    # 提取相机位姿
    cam_to_worlds, ego_to_worlds, cam_to_ego_inv = extract_camera_poses(
        transform_matrix, actual_timestamps, cam_to_ego, n_pose
    )
    
    # 加载相机位姿文件
    traj_0_fixed, c2ws_0_fixed, fixed_transforms = load_camera_poses_from_file(campose_dir, n_pose)
    
    # 对齐相机位姿
    # T, k, cam0_to_worlds_fixed, ego_to_worlds_fixed = align_camera_poses(
    #     fixed_transforms, cam_to_worlds, num_align, cam_to_ego_inv
    # )
    T, k, cam0_to_worlds_fixed, ego_to_worlds_fixed = align_camera_poses_shift(
        fixed_transforms, cam_to_worlds, num_align, cam_to_ego_inv
    )
    
    print('求解的T和k:')
    print(f"T:\n{T}")
    print(f"k: {k}")
    
    # 生成所有相机位姿
    cam_to_worlds_fixed = generate_all_camera_poses(
        cam0_to_worlds_fixed, ego_to_worlds_fixed, transform_json, cam_list, n_pose
    )
    
    # 转化为world2cam, 4元数形式
    w2cs = comp_w2cs(cam_to_worlds_fixed[:, :3, :].reshape((round(len(cam_list) * n_pose), -1)))
    
    # 写入结果
    write_images(aligned_campose_dir, w2cs, n_pose)
    print(f"对齐完成，结果保存到: {aligned_campose_dir}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='相机位姿对齐工具')
    parser.add_argument('--data_root', required=True, help='数据根目录')
    parser.add_argument('--campose_dir', required=True, help='相机位姿目录')
    parser.add_argument('--num_align', type=int, default=50, help='对齐数量 (默认: 50)')
    
    args = parser.parse_args()
    
    # 执行主函数
    main(args.data_root, args.campose_dir, args.num_align)
