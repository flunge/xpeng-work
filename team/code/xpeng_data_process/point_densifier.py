import numpy as np
import os
import argparse 
import json
import cv2
import time
import torch
from pathlib import Path
from scipy.spatial.transform import Rotation as R
from scipy.spatial import KDTree
from plyfile import PlyData, PlyElement

from utils.calib_utils import get_intrisinc_from_transform
from utils.file_utils import storePly, timer, get_semantics_from_path, get_mask_from_semantics
from settings.globals import SemanticType


class PointDensifier:
    def __init__(self, cfg):
        self.cfg = cfg
        self.clip_path = Path(cfg.clip_path)
        self.transform_path = self.clip_path / "transform.json"
        self.transform_json = json.load(open(self.transform_path, "r"))

        self.old_xyzs = None
        self.old_rgbs = None
        self.old_ground_xyzs = None
        self.new_ground_xyzs = None
        self.old_ground_rgbs = None
        self.new_ground_rgbs = None
        self.old_ground_mask = None
        self.new_ground_mask = None
        self.seg_class = None

        # final result
        self.xyzs = None
        self.rgbs = None
        self.ground_mask = None
        self.lidar_mask = None
        # denoised results for training
        self.points_xyz_dict = dict()
        self.points_rgb_dict = dict()

    def get_camera2anchor_from_transform_json(self, transform_frame):
        return np.array(transform_frame["transform_matrix"])

    def save_ground_mask(self, save_vis=True):
        # save for training: ground_mask.npy
        self.ground_mask = self.ground_mask.astype(bool)
        np.save(self.clip_path / "ground_mask.npy", self.ground_mask)
        # save for visualization: misc/ground_labels.ply, misc/seg_class.npy
        if self.seg_class is not None:
            np.save(self.clip_path / "misc/seg_class.npy", self.seg_class)
        
        if save_vis:
            points_xyz = self.points_xyz_dict['bkgd']
            points_rgb = self.points_rgb_dict['bkgd']
            xyz_bkgd = points_xyz[~self.ground_mask.flatten()]
            rgb_bkgd = points_rgb[~self.ground_mask.flatten()]
            storePly(os.path.join(self.clip_path, "misc/vis_background_new.ply"), xyz_bkgd, rgb_bkgd)

            xyz_grd = points_xyz[self.ground_mask.flatten()]
            rgb_grd = points_rgb[self.ground_mask.flatten()]
            storePly(os.path.join(self.clip_path, "misc/vis_ground_new.ply"), xyz_grd, rgb_grd)
    
    def save_lidar_mask(self):
        self.lidar_mask = self.lidar_mask.astype(bool)
        np.save(self.clip_path / "lidar_mask.npy", self.lidar_mask)

    def save_training_points(self):
        pointcloud_dir = os.path.join(self.clip_path, 'input_ply')
        os.makedirs(pointcloud_dir, exist_ok=True)

        for k in self.points_xyz_dict.keys():
            points_xyz = self.points_xyz_dict[k]
            points_rgb = self.points_rgb_dict[k]
            ply_path = os.path.join(pointcloud_dir, f'points3D_{k}.ply')
            try:
                storePly(ply_path, points_xyz, points_rgb)
                print(f'[INFO] saving pointcloud for {k}, number of initial points is {points_xyz.shape}')
            except:
                print(f'[ERROR] failed to save pointcloud for {k}')
                continue

        xyzs_ground = self.xyzs[np.squeeze(self.ground_mask)]
        rgbs_ground = self.rgbs[np.squeeze(self.ground_mask)]
        ply_path = os.path.join(pointcloud_dir, f'points3D_ground.ply')
        try:
            storePly(ply_path, xyzs_ground, rgbs_ground)
            print(f'[INFO] saving pointcloud for ground, number of initial points is {xyzs_ground.shape}')
        except:
            print(f'[ERROR] failed to save pointcloud for ground')
    
    def load_training_points(self):
        pointcloud_dir = os.path.join(self.clip_path, 'input_ply')
        ply_path = os.path.join(pointcloud_dir, f'points3D_bkgd.ply')
        plydata = PlyData.read(ply_path)
        vertices = plydata['vertex']
        positions = np.vstack([vertices['x'], vertices['y'], vertices['z']]).T
        colors = np.vstack([vertices['red'], vertices['green'], vertices['blue']]).T
        self.points_xyz_dict['bkgd'] = positions
        self.points_rgb_dict['bkgd'] = colors
        self.old_xyzs = positions
        self.old_rgbs = colors
        self.old_ground_mask = np.load(self.clip_path / "ground_mask.npy")
        self.lidar_mask = np.load(self.clip_path / "lidar_mask.npy")      

    def compute_grid_area(self, corners_3d):
        """计算三维网格的面积"""
        if len(corners_3d) < 4:
            return 0.0
            
        # 计算四边形面积（拆分为两个三角形）
        p0, p1, p2, p3 = corners_3d
        area1 = 0.5 * np.linalg.norm(np.cross(p1-p0, p2-p0))
        area2 = 0.5 * np.linalg.norm(np.cross(p2-p0, p3-p0))
        return area1 + area2
    
    def sample_points_in_3d_grid(self, corners_3d, num_points):
        """
        在三维网格内随机均匀采样点
        corners_3d: 网格的四个三维角点 [左上, 右上, 右下, 左下]
        num_points: 需要采样的点数
        """
        if len(corners_3d) < 4 or num_points <= 0:
            return np.zeros((0, 3))
        
        # 将四边形拆分为两个三角形
        tri1 = [corners_3d[0], corners_3d[1], corners_3d[2]]  # 上三角形
        tri2 = [corners_3d[0], corners_3d[2], corners_3d[3]]  # 下三角形
        
        # 计算两个三角形的面积
        v1 = tri1[1] - tri1[0]
        v2 = tri1[2] - tri1[0]
        area1 = 0.5 * np.linalg.norm(np.cross(v1, v2))
        
        v1 = tri2[1] - tri2[0]
        v2 = tri2[2] - tri2[0]
        area2 = 0.5 * np.linalg.norm(np.cross(v1, v2))
        
        total_area = area1 + area2
        if total_area < 1e-6:
            return np.zeros((0, 3))
        
        # 按面积比例分配点数
        n1 = max(0, int(round(num_points * area1 / total_area)))
        n2 = num_points - n1
        
        points = []
        
        # 在第一个三角形内采样
        if n1 > 0:
            u = np.random.rand(n1)
            v = np.random.rand(n1)
            mask = u + v > 1
            u[mask] = 1 - u[mask]
            v[mask] = 1 - v[mask]
            w = 1 - u - v
            
            # 向量化计算点坐标
            tri_points = np.zeros((n1, 3))
            for i in range(3):
                tri_points[:, i] = w * tri1[0][i] + u * tri1[1][i] + v * tri1[2][i]
            points.append(tri_points)
        
        # 在第二个三角形内采样
        if n2 > 0:
            u = np.random.rand(n2)
            v = np.random.rand(n2)
            mask = u + v > 1
            u[mask] = 1 - u[mask]
            v[mask] = 1 - v[mask]
            w = 1 - u - v
            
            tri_points = np.zeros((n2, 3))
            for i in range(3):
                tri_points[:, i] = w * tri2[0][i] + u * tri2[1][i] + v * tri2[2][i]
            points.append(tri_points)
        
        return np.vstack(points) if points else np.zeros((0, 3))

    def fit_plane_ransac(self, points, max_iters=100, inlier_thresh=0.05, sample_size=500, device='cuda'):
        """
        GPU 加速的 RANSAC 平面拟合
        参数:
            points: 输入点云 (N, 3) 的 NumPy 数组
            max_iters: 最大迭代次数
            inlier_thresh: 内点阈值
            sample_size: 下采样大小
            device: 计算设备 ('cuda' 或 'cpu')
        
        返回:
            平面参数 [nx, ny, nz, px, py, pz] 或 None
        """
        # 转换点云为 PyTorch 张量并移至 GPU
        # points_t = torch.tensor(points, dtype=torch.float32, device=device)
        points_t = points
        N = points_t.shape[0]
        
        # 下采样点云
        if N > sample_size:
            indices = torch.randperm(N, device=device)[:sample_size]
            sample_points = points_t[indices]
        else:
            sample_points = points_t
            sample_size = N
        
        # 预计算点对向量 (避免在循环中重复计算)
        vectors = sample_points.unsqueeze(1) - sample_points.unsqueeze(0)
        
        # 准备随机采样索引
        rand_indices = torch.randint(0, sample_size, (max_iters, 3), device=device)
        
        # 最佳平面参数
        best_plane = None
        best_inliers = 0
        
        # 迭代计数器
        iter_count = 0
        
        while iter_count < max_iters:
            # 一次处理多个迭代 (批处理)
            batch_size = min(128, max_iters - iter_count)
            
            # 获取当前批次的随机点索引
            batch_indices = rand_indices[iter_count:iter_count+batch_size]
            
            # 获取三个点
            p0 = sample_points[batch_indices[:, 0]]
            p1 = sample_points[batch_indices[:, 1]]
            p2 = sample_points[batch_indices[:, 2]]
            
            # 计算向量 v1 = p1 - p0, v2 = p2 - p0
            v1 = p1 - p0
            v2 = p2 - p0
            
            # 计算法向量 (叉积)
            normal = torch.cross(v1, v2, dim=1)
            
            # 计算法向量长度
            norm = torch.norm(normal, dim=1, keepdim=True)
            
            # 过滤无效平面 (长度接近零)
            valid_mask = (norm.squeeze() > 1e-6)
            if not valid_mask.any():
                iter_count += batch_size
                continue
            
            # 归一化法向量
            normal[valid_mask] /= norm[valid_mask]
            
            # 计算平面方程 d = -n·p0
            d = -torch.sum(normal * p0, dim=1)
            
            # 计算所有点到平面的距离
            # dist = |n·p + d| / ||n||, 但 ||n||=1, 所以简化为 |n·p + d|
            dists = torch.abs(torch.matmul(sample_points, normal.t()) + d.unsqueeze(0))
            
            # 计算内点数量
            inliers = torch.sum(dists < inlier_thresh, dim=0)
            
            # 在批次中找到最佳平面
            batch_best_idx = torch.argmax(inliers)
            batch_best_inliers = inliers[batch_best_idx].item()
            
            # 更新全局最佳平面
            if batch_best_inliers > best_inliers:
                best_inliers = batch_best_inliers
                best_plane = torch.cat([
                    normal[batch_best_idx], 
                    d[batch_best_idx].unsqueeze(0)
                ])
                
                # 提前终止条件
                inlier_ratio = best_inliers / sample_size
                if inlier_ratio > 0.95:
                    # 提前终止，但完成当前批次
                    iter_count += batch_size
                    break
            
            iter_count += batch_size
        
        if best_plane is None:
            return None
        
        # 用所有内点精炼平面
        dists_all = torch.abs(torch.matmul(points_t, best_plane[:3]) + best_plane[3])
        inlier_mask = dists_all < inlier_thresh
        inlier_points = points_t[inlier_mask]
        
        if inlier_points.shape[0] < 3:
            return None
        
        # 最小二乘拟合精炼平面
        centroid = torch.mean(inlier_points, dim=0)
        centered = inlier_points - centroid
        cov = torch.matmul(centered.t(), centered) / (inlier_points.shape[0] - 1)
        
        # 使用 SVD 计算法向量
        _, _, V = torch.svd(cov)
        normal_refined = V[:, -1]
        
        # 返回格式: [法向量, 平面上点]
        return torch.cat([normal_refined, centroid]).cpu().numpy()

    def project_2d_to_3d_plane(self, x, y, ground_plane, fx, fy, cx, cy):
        """将2D像素点投影到3D地平面"""
        # 像素坐标转归一化射线
        ray_x = (x - cx) / fx
        ray_y = (y - cy) / fy
        ray_dir = np.array([ray_x, ray_y, 1.0])
        ray_dir /= np.linalg.norm(ray_dir)
        
        # 计算射线与地平面交点
        plane_normal = ground_plane[:3]
        plane_point = ground_plane[3:]
        denom = np.dot(ray_dir, plane_normal)
        if abs(denom) < 1e-6:
            return None  # 平行于平面，无交点
        t = np.dot(plane_point, plane_normal) / denom
        return ray_dir * t

    def batch_sample_points_in_3d_grid(self, all_corners_3d, all_num_points):
        # 如果没有输入，直接返回空数组
        if len(all_corners_3d) == 0:
            return np.zeros((0, 3))
        
        # 将输入转换为NumPy数组
        all_corners_3d = np.array(all_corners_3d)
        all_num_points = np.array(all_num_points)
        
        # 步骤1: 计算每个网格的两个三角形面积
        # 第一个三角形 (P0, P1, P2)
        v1 = all_corners_3d[:, 1] - all_corners_3d[:, 0]
        v2 = all_corners_3d[:, 2] - all_corners_3d[:, 0]
        cross1 = np.cross(v1, v2)
        area1 = 0.5 * np.linalg.norm(cross1, axis=1)
        
        # 第二个三角形 (P0, P2, P3)
        v3 = all_corners_3d[:, 2] - all_corners_3d[:, 0]
        v4 = all_corners_3d[:, 3] - all_corners_3d[:, 0]
        cross2 = np.cross(v3, v4)
        area2 = 0.5 * np.linalg.norm(cross2, axis=1)
        
        total_area = area1 + area2
        valid_mask = total_area > 1e-12
        
        # 只处理有效网格
        valid_corners = all_corners_3d[valid_mask]
        valid_num_points = all_num_points[valid_mask]
        valid_area1 = area1[valid_mask]
        valid_area2 = area2[valid_mask]
        valid_total_area = total_area[valid_mask]
        
        # 计算每个三角形的采样点数
        n1 = np.round(valid_num_points * valid_area1 / valid_total_area).astype(int)
        n2 = valid_num_points - n1
        
        # 步骤2: 为所有三角形生成采样点
        # 计算需要采样的总点数
        total_points = np.sum(n1) + np.sum(n2)
        if total_points == 0:
            return np.zeros((0, 3))
        
        # 预分配结果数组
        all_points = np.zeros((total_points, 3))
        
        # 为所有三角形生成随机数
        u = np.random.rand(total_points)
        v = np.random.rand(total_points)
        
        # 处理u+v>1的情况 (映射回三角形)
        mask = u + v > 1
        u[mask] = 1 - u[mask]
        v[mask] = 1 - v[mask]
        w = 1 - u - v
        
        # 步骤3: 计算每个点的位置
        # 创建索引映射
        start_idx = 0
        for i in range(len(valid_corners)):
            corners = valid_corners[i]
            
            # 处理第一个三角形
            if n1[i] > 0:
                end_idx = start_idx + n1[i]
                tri_points = (
                    w[start_idx:end_idx, None] * corners[0] +
                    u[start_idx:end_idx, None] * corners[1] +
                    v[start_idx:end_idx, None] * corners[2]
                )
                all_points[start_idx:end_idx] = tri_points
                start_idx = end_idx
            
            # 处理第二个三角形
            if n2[i] > 0:
                end_idx = start_idx + n2[i]
                # 第二个三角形的顶点 (P0, P2, P3)
                tri_points = (
                    w[start_idx:end_idx, None] * corners[0] +
                    u[start_idx:end_idx, None] * corners[2] +
                    v[start_idx:end_idx, None] * corners[3]
                )
                all_points[start_idx:end_idx] = tri_points
                start_idx = end_idx
        
        return all_points
    
    def get_mask(self, frame, line = False):#line为t处理车道线，为f处理地面
        semantics = get_semantics_from_path(self.clip_path / frame["file_path"].replace("images", "segs"))
        if line == True:
            specific_mask_img = (1 - get_mask_from_semantics(semantics, SemanticType.LANELINE))
        else:
            specific_mask_img = (1 - get_mask_from_semantics(semantics, SemanticType.GROUND))
        # if self.cfg.steps_controller.source == "vision":
        #     dir_path, file_name = os.path.split(str(self.clip_path / frame["file_path"].replace("images", "masks")))
        #     mask_path = os.path.join(dir_path, f"{os.path.basename(dir_path)}.png")
        #     mask_img = cv2.imread(
        #         mask_path,
        #         cv2.IMREAD_GRAYSCALE
        #     )
        # else:
        mask_img = cv2.imread(
            str(self.clip_path / frame["file_path"].replace("images", "masks")),
            cv2.IMREAD_GRAYSCALE
        )
        valid_specific_mask = np.logical_and(specific_mask_img, mask_img).astype(bool)  
        return valid_specific_mask
            
    def densify_tranning_points_one_frame(self, frame_idx, cam_idx, frame, line=False):#line为t处理车道线，为f处理地面
        new_points_list = []
        new_rgb_list = []

        t1 = time.time()

        # 获取坐标变换参数
        camera2anchor = self.get_camera2anchor_from_transform_json(frame)
        anchor2camera = np.linalg.inv(camera2anchor).astype(np.float32)
        cam_name = frame["camera"]
        
        # 获取相机内参
        intrinsic_matrix, _, _ = get_intrisinc_from_transform(frame)
        fx, fy = intrinsic_matrix[0, 0], intrinsic_matrix[1, 1]
        cx, cy = intrinsic_matrix[0, 2], intrinsic_matrix[1, 2]

        # 获取rgb原图，如果是cam2，则用rgb原图上色，因为电云颜色和cam2颜色最接近
        colorized_with_image_cams = [1]
        if cam_idx in colorized_with_image_cams:
            rgb_image = cv2.imread(str(self.clip_path / frame["file_path"]))
        
        # 创建有效地面区域掩码 (地面且非车身)，数组大小等于图片大小，为true的元素代码地面且非车身
        valid_specific_mask = self.get_mask(frame, line)
        h, w = valid_specific_mask.shape

        # 将数据转移到 GPU
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        valid_specific_mask = torch.tensor(valid_specific_mask, dtype=torch.bool, device=device)
        anchor2camera= torch.tensor(anchor2camera, dtype=torch.float32, device=device)
        if self.new_ground_xyzs is not None:
            ground_xyz = torch.vstack((self.old_ground_xyzs, self.new_ground_xyzs))
            ground_rgbs = torch.vstack((self.old_ground_rgbs, self.new_ground_rgbs))
        else:
            ground_xyz = self.old_ground_xyzs
            ground_rgbs = self.old_ground_rgbs

        # print(f'torch load cost {time.time() - t1}')
        # t1 = time.time()

        # 添加齐次坐标 (在 GPU 上完成)
        ones = torch.ones((ground_xyz.shape[0], 1), device=device)
        ground_xyz_hom = torch.cat([ground_xyz, ones], dim=1)
        # 坐标变换 (矩阵乘法)
        ground_xyz_in_cam = anchor2camera @ ground_xyz_hom.T
        # 筛选 z > 0 的点
        z_mask = (ground_xyz_in_cam[2] > 0) & (ground_xyz_in_cam[2] < 50)
        device = ground_xyz_in_cam.device
        intrinsic_matrix = torch.tensor(intrinsic_matrix, dtype=torch.float32, device=device)
        # 投影计算
        ground_xyz_in_cam = ground_xyz_in_cam[:, z_mask]
        ground_uv_homogeneous = intrinsic_matrix @ ground_xyz_in_cam
        # 齐次坐标归一化
        ground_xy_in_front_2d = ground_uv_homogeneous[:2] / ground_uv_homogeneous[2]
        # 四舍五入并转换为整数
        ground_xy_in_front_2d = torch.round(ground_xy_in_front_2d).to(torch.int32)
        # 返回到cpu上
        ground_xyz_in_cam = ground_xyz_in_cam.T

        # in_view_mask大小和ground_xyz_in_front_2d一致，每个元素代表投影的激光点是否在camera/图片视野内
        in_view_mask = (
            (ground_xy_in_front_2d[0, :] >= 0) & (ground_xy_in_front_2d[0, :] < w) & 
            (ground_xy_in_front_2d[1, :] >= 0) & (ground_xy_in_front_2d[1, :] < h)
        )
        # 只取在图片视野内的激光点
        ground_xy_in_view_2d = ground_xy_in_front_2d[:, in_view_mask].T

        # 获取投影点对应的颜色
        # 首先找到在图像范围内的点的原始索引
        indices_in_z = torch.nonzero(z_mask, as_tuple=False).squeeze(-1)  # 在相机前方的点的index（在所有点中的索引），大小等同于uv
        indices_in_view = indices_in_z[in_view_mask]  # 在图片视野内的点的index（在所有点中的索引）
        # 在图片视野内的激光点（3D）的颜色
        ground_rgbs_in_view = ground_rgbs[indices_in_view]  # 根据索引，查找在图片视野内的激光点（3D）的颜色
        # 从有效投影点中采样地面点进行平面拟合
        # 在cam/图片视野内的3D激光点
        ground_xyz_in_view = (ground_xyz_in_cam[:, :3])[in_view_mask]
        
        # ground_point_mask数组表示（camera视野内的）激光点是否在地面，为true的元素代表对应的激光点在地面
        ground_point_mask = valid_specific_mask[ground_xy_in_view_2d[:, 1], ground_xy_in_view_2d[:, 0]]
        # ground_points表示在地面上的3D点，点集从“在cam视野内的3D激光点”变成“在地面上的3D点”
        ground_points = ground_xyz_in_view[ground_point_mask]
        if not cam_idx in colorized_with_image_cams:
            ground_colors = ground_rgbs_in_view[ground_point_mask]


        # 地面上的3D点拟合出一个平面，用于计算空洞坐标
        if len(ground_points) > 1000:
            ground_plane = self.fit_plane_ransac(ground_points)
        else:
            print("skip frame ", frame_idx, " ", cam_name)
            return new_points_list, new_rgb_list  # 点数不足时跳过
        # 地平面中心，约束增加的新点位置
        ground_centroid = torch.mean(ground_points, axis=0)
        ground_points = ground_points.cpu().numpy()
        if not cam_idx in colorized_with_image_cams:
            ground_colors = ground_colors.cpu().numpy()
        ground_centroid = ground_centroid.cpu().numpy()

        # print(f'ransac cost {time.time() - t1}')
        # t1 = time.time()

        # print(f'[INFO] [densify_tranning_points] get ground plane done')

        # ========== 划分ground mask为网格，对缺少激光点的网格进行补点 ==========
        # ***** 参数配置 ***** #
        if line == False:#处理地面
            if not cam_idx in colorized_with_image_cams:
                # 其他cam看得窄，网格要大
                GRID_SIZE = 20 # 网格大小，越大，越只会补大空洞，无视小空洞
                MIN_OLD_POINTS_PER_GRID = 1 # 每个网格至少需要多少旧点
                MIN_NEW_POINTS_PER_GRID = 10 # 每个网格至少需要多少新点
                POINTS_PER_SQUARE_METER = 20  # 每平方米点数密度，决定空洞补得有多密，下次调小这个
            else:
                # cam2看得广，网格要小
                GRID_SIZE = 10 # 网格大小，越大，越只会补大空洞，无视小空洞
                MIN_OLD_POINTS_PER_GRID = 1 # 每个网格至少需要多少旧点
                MIN_NEW_POINTS_PER_GRID = 5 # 每个网格至少需要多少新点
                POINTS_PER_SQUARE_METER = 100  # 每平方米点数密度，决定空洞补得有多密，下次调小这个
            MAX_AREA_THRESHOLD = 4 # 道路起点/尽头会投影出特别大的区域，滤掉这些无效区域
            MAX_DISTANCE_FROM_CENTROID = 100 # 新点离地平面中心允许的最大距离，过滤太远的点
            MAX_DISTANCE_FROM_GROUND_PLANE = 2 # 新点离地平面边缘允许的最大距离，过滤太远的点
            MIN_DISTANCE_FROM_GROUND_PLANE = 0.1 # 新点离地平面边缘允许的最小距离，过滤补在有点云处的点
        else:#处理车道线
            if not cam_idx in colorized_with_image_cams:
                # 其他cam看得窄，网格要大
                GRID_SIZE = 5 # 网格大小，越大，越只会补大空洞，无视小空洞
                MIN_OLD_POINTS_PER_GRID = 20 # 每个网格至少需要多少旧点
                MIN_NEW_POINTS_PER_GRID = 80 # 每个网格至少需要多少新点
                POINTS_PER_SQUARE_METER = 20  # 每平方米点数密度，决定空洞补得有多密，下次调小这个
            else:
                # cam2看得广，网格要小
                GRID_SIZE = 3 # 网格大小，越大，越只会补大空洞，无视小空洞
                MIN_OLD_POINTS_PER_GRID = 20 # 每个网格至少需要多少旧点
                MIN_NEW_POINTS_PER_GRID = 80 # 每个网格至少需要多少新点
                POINTS_PER_SQUARE_METER = 100  # 每平方米点数密度，决定空洞补得有多密，下次调小这个
            MAX_AREA_THRESHOLD = 4 # 道路起点/尽头会投影出特别大的区域，滤掉这些无效区域
            MAX_DISTANCE_FROM_CENTROID = 50 # 新点离地平面中心允许的最大距离，过滤太远的点
            MAX_DISTANCE_FROM_GROUND_PLANE = 0.2 # 新点离地平面边缘允许的最大距离，过滤太远的点
            MIN_DISTANCE_FROM_GROUND_PLANE = 0.1 # 新点离地平面边缘允许的最小距离，过滤补在有点云处的点

        grid_h = int(torch.ceil(torch.tensor(h / GRID_SIZE)).item())
        grid_w = int(torch.ceil(torch.tensor(w / GRID_SIZE)).item())

        # 获取旧点数量（用于区分新旧点）
        old_point_count = self.old_ground_xyzs.shape[0]

        with torch.no_grad():
            # 计算每个点的网格索引
            grid_i = torch.clamp(ground_xy_in_view_2d[:, 1] // GRID_SIZE, 0, grid_h - 1).long()
            grid_j = torch.clamp(ground_xy_in_view_2d[:, 0] // GRID_SIZE, 0, grid_w - 1).long()
            flat_indices = grid_i * grid_w + grid_j

            # 区分原始点云和新补点
            is_old_point = indices_in_view < old_point_count  # 关键：标记原始点

            # 分别统计原始点云数量
            old_point_mask = is_old_point & ground_point_mask  # 原始点+地面点
            old_counts = torch.bincount(
                flat_indices[old_point_mask], 
                minlength=grid_h * grid_w
            ).view(grid_h, grid_w).cpu().numpy()

            # 分别统计新补点数量
            new_point_mask = (~is_old_point) & ground_point_mask  # 新点+地面点
            new_counts = torch.bincount(
                flat_indices[new_point_mask], 
                minlength=grid_h * grid_w
            ).view(grid_h, grid_w).cpu().numpy()

        # 向量化计算地面比例
        # 创建网格索引矩阵
        y_grids = torch.arange(0, grid_h, device=device).view(-1, 1)
        x_grids = torch.arange(0, grid_w, device=device).view(1, -1)

        # 计算每个网格的边界
        y_starts = y_grids * GRID_SIZE
        y_ends = torch.minimum(y_starts + GRID_SIZE, torch.tensor(h, device=device))
        x_starts = x_grids * GRID_SIZE
        x_ends = torch.minimum(x_starts + GRID_SIZE, torch.tensor(w, device=device))

        # 计算每个网格的面积
        grid_areas = (y_ends - y_starts) * (x_ends - x_starts)

        # 使用积分图技术加速地面像素统计
        # 创建积分图
        integral = torch.cumsum(torch.cumsum(valid_specific_mask, dim=0), dim=1)
        integral = torch.nn.functional.pad(integral, (1, 0, 1, 0))  # 左上角填充0

        # 计算每个网格的地面像素数量
        top_left = integral[y_starts, x_starts]
        top_right = integral[y_starts, x_ends]
        bottom_left = integral[y_ends, x_starts]
        bottom_right = integral[y_ends, x_ends]
        ground_pixels = bottom_right - bottom_left - top_right + top_left

        # 计算地面比例
        grid_ground_ratio = (ground_pixels / grid_areas).cpu().numpy()

        # 识别需要补洞的网格
        hole_grids = np.logical_and(
            grid_ground_ratio >= 1.0,  # 地面区域
            old_counts < MIN_OLD_POINTS_PER_GRID, # 原始点云 < MIN_OLD_POINTS_PER_GRID
            new_counts < MIN_NEW_POINTS_PER_GRID  # 新补点 < MIN_NEW_POINTS_PER_GRID
        )

        # 获取空洞网格的索引
        hole_grid_indices = np.argwhere(hole_grids)
        grids_to_fill_list = list(hole_grid_indices)

        # 如果没有空洞网格，跳过
        if not grids_to_fill_list:
            return new_points_list, new_rgb_list

        # print(f'[INFO] [densify_tranning_points] get hole to fill done, hole number ', len(grids_to_fill_list))

        # ========== 获取空洞角点 ==========
        new_points_list = []  # 存储新生成的三维点（相机坐标系）
        new_rgb_list = []     # 存储新点的颜色
        grid_areas = []       # 存储每个网格的面积
        valid_grids = []      # 存储有效的网格索引
        
        # 计算每个空洞网格的三维面积
        plane_normal = ground_plane[:3]
        plane_point = ground_plane[3:]
        
        # 预先计算平面常数项
        d0 = -np.dot(plane_normal, plane_point)
        
        # 创建所有网格的角点坐标
        grid_indices = np.array(grids_to_fill_list)
        grid_i = grid_indices[:, 0]
        grid_j = grid_indices[:, 1]
        
        # 计算每个网格的边界
        y_starts = grid_i * GRID_SIZE
        y_ends = np.minimum((grid_i + 1) * GRID_SIZE, h)
        x_starts = grid_j * GRID_SIZE
        x_ends = np.minimum((grid_j + 1) * GRID_SIZE, w)
        
        # 创建所有四个角点的坐标
        corners_2d = np.zeros((len(grid_i) * 4, 2), dtype=np.float32)
        
        # 左上角
        corners_2d[0::4, 0] = x_starts
        corners_2d[0::4, 1] = y_starts
        
        # 右上角
        corners_2d[1::4, 0] = x_ends - 1
        corners_2d[1::4, 1] = y_starts
        
        # 右下角
        corners_2d[2::4, 0] = x_ends - 1
        corners_2d[2::4, 1] = y_ends - 1
        
        # 左下角
        corners_2d[3::4, 0] = x_starts
        corners_2d[3::4, 1] = y_ends - 1
        
        # 向量化投影到3D平面
        ray_x = (corners_2d[:, 0] - cx) / fx
        ray_y = (corners_2d[:, 1] - cy) / fy
        ray_z = np.ones_like(ray_x)
        ray_dirs = np.vstack([ray_x, ray_y, ray_z]).T
        
        # 归一化射线方向
        norms = np.linalg.norm(ray_dirs, axis=1, keepdims=True)
        ray_dirs = ray_dirs / norms
        
        # 计算射线与平面的交点
        denoms = np.dot(ray_dirs, plane_normal)
        t = -d0 / denoms  # 使用平面方程 ax+by+cz+d=0
        
        # 处理平行情况（分母接近零）
        valid_mask = np.abs(denoms) > 1e-6
        corners_3d = np.full((len(ray_dirs), 3), np.nan)
        corners_3d[valid_mask] = ray_dirs[valid_mask] * t[valid_mask, np.newaxis]
        
        # 将角点分组为网格（每个网格4个点）
        corners_3d_grids = corners_3d.reshape(-1, 4, 3)
        
        # 检查每个网格是否有无效点
        valid_grid_mask = ~np.any(np.isnan(corners_3d_grids).any(axis=2), axis=1)
        
        # 向量化计算网格面积
        grid_areas = np.zeros(len(corners_3d_grids))
        
        # 计算第一个三角形的面积 (P0, P1, P2)
        v1 = corners_3d_grids[:, 1] - corners_3d_grids[:, 0]
        v2 = corners_3d_grids[:, 2] - corners_3d_grids[:, 0]
        cross1 = np.cross(v1, v2)
        area1 = 0.5 * np.linalg.norm(cross1, axis=1)
        
        # 计算第二个三角形的面积 (P0, P2, P3)
        v3 = corners_3d_grids[:, 2] - corners_3d_grids[:, 0]
        v4 = corners_3d_grids[:, 3] - corners_3d_grids[:, 0]
        cross2 = np.cross(v3, v4)
        area2 = 0.5 * np.linalg.norm(cross2, axis=1)
        
        grid_areas = area1 + area2
        
        # 应用面积阈值
        area_valid_mask = grid_areas < MAX_AREA_THRESHOLD
        final_valid_mask = valid_grid_mask & area_valid_mask
        
        # 收集有效网格
        valid_grids = []
        for i in np.where(final_valid_mask)[0]:
            grid_i_val = grid_i[i]
            grid_j_val = grid_j[i]
            corners = corners_3d_grids[i]
            valid_grids.append((grid_i_val, grid_j_val, corners))
        
        grid_areas = grid_areas[final_valid_mask]
        
        # 如果没有有效网格，跳过
        if len(grid_areas) == 0:
            return new_points_list, new_rgb_list

        # ========== 空洞撒点 ==========
        # 准备批量处理数据
        all_corners_3d = []
        all_num_points = []
        grid_indices = []
        
        # 收集所有网格数据
        for idx, (grid_i, grid_j, corners_3d) in enumerate(valid_grids):
            area = grid_areas[idx]
            num_points = max(1, int(area * POINTS_PER_SQUARE_METER))

            all_corners_3d.append(corners_3d)
            all_num_points.append(num_points)
            grid_indices.append(idx)
        
        # 批量生成点云（向量化优化）
        if len(all_corners_3d) > 0:
            # 使用批量采样函数
            all_points_3d = self.batch_sample_points_in_3d_grid(
                all_corners_3d, all_num_points
            )

            # print(f'batch_sample_points_in_3d_grid cost {time.time() - t1}')
            # t1 = time.time()

            # 如果没有生成点，跳过
            if len(all_points_3d) == 0:
                return new_points_list, new_rgb_list

            # 合并点云和颜色
            new_points_arr = all_points_3d

            # 初步过滤离地平面中心过远的点，速度快
            dist_to_centroid = np.linalg.norm(new_points_arr - ground_centroid, axis=1)
            valid_dist_mask = dist_to_centroid <= MAX_DISTANCE_FROM_CENTROID
            valid_points = new_points_arr[valid_dist_mask]
            if len(valid_points) == 0:
                return new_points_list, new_rgb_list

            # print(f'get points cost {time.time() - t1}')
            # t1 = time.time()

            # 根据最近点的颜色上色
            # print(f'[INFO] [densify_tranning_points] build view_ground_kdtree begin ', ground_points.shape)
            random_indices = np.random.choice(ground_points.shape[0], size=int(ground_points.shape[0] / 100), replace=False)
            downsampld_ground_points = ground_points[random_indices]
            view_ground_kdtree = KDTree(downsampld_ground_points)
            # print(f'[INFO] [densify_tranning_points] build view_ground_kdtree done')
            distances, indices = view_ground_kdtree.query(valid_points)
            # indices为地平面距离valid_points最近点的indexs
            if not cam_idx in colorized_with_image_cams:
                downsampld_ground_colors = ground_colors[random_indices]
                rgb_arr = downsampld_ground_colors[indices]
            # print(f'[INFO] [densify_tranning_points] view_ground_kdtree query done')

            # 二次精确过滤远离地平面的点，速度慢（但是经过初次过滤后，只剩很少点，速度就没问题了）
            filtered_indices = np.where(distances < MAX_DISTANCE_FROM_GROUND_PLANE)[0]
            final_valid_points = valid_points[filtered_indices]
            # 使用最近点的高度，避免在陡坡高度异常
            final_valid_points[:,1] = (downsampld_ground_points[indices[filtered_indices]])[:,1]

            if not cam_idx in colorized_with_image_cams:
                # 非cam2，用最近点云上色，因为cam2之外的cam颜色和点云颜色差很大
                final_rgb_arr = rgb_arr[filtered_indices]
            else:
                # cam2根据rgb_image上色
                valid_points_gpu = torch.tensor(final_valid_points, dtype=torch.float32, device=device)
                ones = torch.ones((final_valid_points.shape[0], 1), device=device)
                valid_points_gpu = torch.cat([valid_points_gpu, ones], dim=1)
                # valid_points_2d = anchor2camera @ valid_points_gpu.T
                uv_homogeneous = intrinsic_matrix @ valid_points_gpu.T
                division_row = uv_homogeneous[2, :]
                pixels = (uv_homogeneous[:2,:] / division_row).to(torch.int32)
                #这三句是为了解决final_rgb_arr变量赋值时的报错：index xxx is out of bounds for axis y with size xxx,但这样会影响颜色，如果有别的解决方案可直接替换
                h, w = rgb_image.shape[0], rgb_image.shape[1]
                pixels[1, :] = torch.clamp(pixels[1, :], 0, h - 1)
                pixels[0, :] = torch.clamp(pixels[0, :], 0, w - 1)

                final_rgb_arr = rgb_image[pixels[1, :].cpu().numpy(), pixels[0, :].cpu().numpy()]

            # print(f'color cost {time.time() - t1}')
            # t1 = time.time()

            # 转换到全局坐标系
            homogeneous_points = np.hstack([
                final_valid_points, 
                np.ones((len(final_valid_points), 1))
            ])
            global_points = (camera2anchor @ homogeneous_points.T).T[:, :3]
    
        return global_points, final_rgb_arr
    
    def densify_tranning_points(self):
        # 获取时间戳，目的是遍历每个时间戳的语义图，并将激光点投到每个时间的语义图上，查出空洞
        sorted_transforms = {}
        for i in self.transform_json['frames']:
            timestamp = i['timestamp']
            sorted_transforms.setdefault(timestamp, []).append(i)
        sorted_transforms = dict(sorted(sorted_transforms.items()))

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.old_ground_xyzs = torch.tensor(self.old_xyzs[np.squeeze(self.old_ground_mask)], dtype=torch.float32, device=device)
        self.old_ground_rgbs = torch.tensor(self.old_rgbs[np.squeeze(self.old_ground_mask)], dtype=torch.float32, device=device)
        
        # 处理每一帧图像
        for frame_idx, (t, transforms) in enumerate(sorted_transforms.items()):
            for cam_idx, frame in enumerate(transforms):
                if  self.cfg.steps_controller.source == "vision":
                    new_points, new_rgbs = self.densify_tranning_points_one_frame(frame_idx, cam_idx, frame, True)#vision仅加密车道线
                else:
                    new_points, new_rgbs = self.densify_tranning_points_one_frame(frame_idx, cam_idx, frame, False)#其余默认加密空洞
                    if self.cfg.steps_controller.lidar_densify_line == True:
                        new_points, new_rgbs = self.densify_tranning_points_one_frame(frame_idx, cam_idx, frame, True)#仅开启配置才加密车道线
                if len(new_points) <= 0:
                    continue
                
                new_points_tensor = torch.tensor(new_points, dtype=torch.float32, device=device)
                new_rgbs_tensor = torch.tensor(new_rgbs, dtype=torch.float32, device=device)
                new_gnd_mask = np.ones(len(new_points), dtype=bool)
                if self.new_ground_xyzs is not None:
                    self.new_ground_xyzs = torch.vstack((self.new_ground_xyzs, new_points_tensor))
                    self.new_ground_rgbs = torch.vstack((self.new_ground_rgbs, new_rgbs_tensor))
                    self.new_ground_mask = np.concatenate([self.new_ground_mask, new_gnd_mask.reshape(-1, 1)])
                else:
                    self.new_ground_xyzs = new_points_tensor
                    self.new_ground_rgbs = new_rgbs_tensor
                    self.new_ground_mask = new_gnd_mask.reshape(-1, 1)
                
                cam_name = frame["camera"]
                print("[INFO] [densify_tranning_points] fill hole done {0} {1}/{2} new point size {3}".format(
                    cam_name, frame_idx, len(sorted_transforms), len(new_points)))
            
        # final result  
        self.xyzs = np.vstack([self.old_xyzs, self.new_ground_xyzs.cpu().numpy()])
        self.rgbs = np.vstack([self.old_rgbs, self.new_ground_rgbs.cpu().numpy()])
        self.ground_mask = np.vstack([self.old_ground_mask, self.new_ground_mask])
        new_lidar_mask_zeros = np.zeros_like(self.new_ground_mask, dtype=bool)
        self.lidar_mask = np.vstack([self.lidar_mask, new_lidar_mask_zeros])
        self.points_xyz_dict['bkgd'] = self.xyzs
        self.points_rgb_dict['bkgd'] = self.rgbs
        
        add_points_size = self.new_ground_xyzs.cpu().numpy().shape[0]
        print("[INFO] [densify_tranning_points] add {0} points".format(add_points_size))

    def process_densify(self):
        t1 = time.time()
        self.load_training_points()
        self.densify_tranning_points()
        self.save_training_points()
        self.save_ground_mask()
        self.save_lidar_mask()
        print(f'process_densify cost {time.time() - t1}')

if __name__ == '__main__':
    from settings.config import make_default_settings, make_case_specific_settings
    parser = argparse.ArgumentParser(description='perception launch script')
    parser.add_argument(
        '--clip_id',
        type=str,
        required=True,
        help='1'
    )
    
    args = parser.parse_args()

    cfg = make_default_settings()
    cfg.ips_deploy = False
    cfg.dataset_name = "fm_pose"
    cfg.root = f"/workspace/zhangzy27@xiaopeng.com/code/bridge_hole_data"
    cfg.clip_id = args.clip_id
    cfg.ips_deploy = False
    cfg = make_case_specific_settings(cfg)

    point_densifier = PointDensifier(cfg)
    point_densifier.process_densify()