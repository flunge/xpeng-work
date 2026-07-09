import numpy as np
import cv2
from matplotlib import cm 
from pypcd import pypcd
import torch

class Projection(object):
    def __init__(self):
        pass

    def batch_boxes_center_to_corner(self, boxes_center):
        N = boxes_center.shape[0]
        if N == 0:
            return np.zeros((0, 8, 3), dtype=boxes_center.dtype)
        centers = boxes_center[:, :3]
        w, l, h = boxes_center[:, 3], boxes_center[:, 4], boxes_center[:, 5]
        rotation = boxes_center[:, 6]

        bounding_box = [
            [[l[i] / 2, l[i] / 2, -l[i] / 2, -l[i] / 2, l[i] / 2, l[i] / 2, -l[i] / 2, -l[i] / 2],
            [w[i] / 2, -w[i] / 2, -w[i] / 2, w[i] / 2, w[i] / 2, -w[i] / 2, -w[i] / 2, w[i] / 2],
            [h[i] / 2, h[i] / 2, h[i] / 2, h[i] / 2, -h[i] / 2, -h[i] / 2, -h[i] / 2, -h[i] / 2]]
            for i in range(N)
        ]
        bounding_box = np.array(bounding_box, dtype=boxes_center.dtype)
        rotation_matrix = [[
            [np.cos(r), -np.sin(r), 0.0],
            [np.sin(r), np.cos(r), 0.0],
            [0.0, 0.0, 1.0]
        ] for r in rotation]
        rotation_matrix = np.array(rotation_matrix, dtype=boxes_center.dtype)
        eight_points = np.tile(centers, (8, 1, 1))
        corner_box = np.matmul(rotation_matrix, bounding_box) + eight_points.transpose((1, 2, 0))
        return corner_box.transpose((0, 2, 1))

    def boxes_to_camera(self, boxes_center, ex_params):
        N = boxes_center.shape[0]
        if N == 0:
            return np.zeros((0, 8, 3), dtype=boxes_center.dtype)
        data_type = boxes_center.dtype
        if not isinstance(ex_params, np.ndarray):
            ex_params = np.array(ex_params, dtype=np.float32)
        boxes_corner = self.batch_boxes_center_to_corner(boxes_center)
        boxes_corner = np.concatenate((boxes_corner, np.ones((N, 8, 1), dtype=data_type)), axis=2)
        ex_matrixes = [ex_params for _ in range(N)]
        ex_matrixes = np.array(ex_matrixes, dtype=data_type)
        result = np.matmul(ex_matrixes, boxes_corner.transpose((0, 2, 1))).transpose((0, 2, 1))
        for i in range(result.shape[2]):
            result[:, :, i] = result[:, :, i] / result[:, :, -1]
        return result[:, :, :3]

    def lidar_points_to_camera(self, points, ex_params, device="cpu"):
        device = torch.device(device if torch.cuda.is_available() else "cpu")
        points = torch.as_tensor(points, dtype=torch.float32, device=device)
        ex_params = torch.as_tensor(ex_params, dtype=torch.float32, device=device)
        if ex_params.dim() == 2:
            ex_params = ex_params.unsqueeze(0)
        N = points.shape[1]
        M = ex_params.shape[0]
        if points.shape[0] == 3:
            points = torch.cat((points, torch.ones(1, N, device=device)), dim=0)
        if M > 1:
            points = points.unsqueeze(0).expand(M, -1, -1)
            result = torch.bmm(ex_params, points)
        else:
            result = torch.matmul(ex_params[0], points)
            result = result.unsqueeze(0)
        result = result[:, :3] / result[:, 3:4]
        return result

    def transform_normals_to_camera(self, normals, ex_params):
        if not isinstance(ex_params, np.ndarray):
            ex_params = np.array(ex_params, dtype=np.float32)
        rotation_matrix = ex_params[:3, :3]  # Extract rotation part
        return np.matmul(rotation_matrix, normals)
        
    def add_distortion(self, boxes_corner, dist_params, project_mat, dist_mode="radtan"):
        # [k1, k2, p1, p2, k3, k4, k5, k6]
        N = boxes_corner.shape[0]
        if N == 0:
            return np.zeros((0, 8, 3), dtype=boxes_corner.dtype)
        
        if dist_mode == "radtan":
            if len(dist_params) != 8:
                print("invalid")
                return
            if not isinstance(dist_params, np.ndarray):
                dist_params = np.array(dist_params, dtype=np.float32)
            if not isinstance(dist_params, np.ndarray):
                project_mat = np.array(project_mat, dtype=np.float32)
            project_mats = [project_mat for _ in range(N)]
            project_mats = np.array(project_mats, dtype=boxes_corner.dtype)
            boxes_corner_copy = np.copy(boxes_corner)
            filter = np.argwhere(boxes_corner_copy[:, :, 2] <= 0)
            for i in range(filter.shape[0]):
                boxes_corner_copy[filter[i][0], filter[i][1], 2] = 1e-5
            image_points = np.matmul(project_mats, boxes_corner_copy.transpose((0, 2, 1)))
            image_points[:, 0, :] = image_points[:, 0, :] / np.absolute(image_points[:, -1, :])
            image_points[:, 1, :] = image_points[:, 1, :] / np.absolute(image_points[:, -1, :])
            
            image_points[:, 0, :] = (image_points[:, 0, :] - project_mat[0, 2]) / project_mat[0, 0]
            image_points[:, 1, :] = (image_points[:, 1, :] - project_mat[1, 2]) / project_mat[1, 1]

            xy_squared_norm = image_points[:, 0, :] ** 2 + image_points[:, 1, :] ** 2
            rad_dist_x = image_points[:, 0, :] * (1 + dist_params[0] * xy_squared_norm +
                                                dist_params[1] * (xy_squared_norm ** 2) +
                                                dist_params[4] * (xy_squared_norm ** 3)) / \
                                                (1 + dist_params[5] * xy_squared_norm + 
                                                dist_params[6] * (xy_squared_norm ** 2) +
                                                dist_params[7] * (xy_squared_norm ** 3))
            rad_dist_y = image_points[:, 1, :] * (1 + dist_params[0] * xy_squared_norm +
                                                dist_params[1] * (xy_squared_norm ** 2) +
                                                dist_params[4] * (xy_squared_norm ** 3)) / \
                                                (1 + dist_params[5] * xy_squared_norm + 
                                                dist_params[6] * (xy_squared_norm ** 2) +
                                                dist_params[7] * (xy_squared_norm ** 3))
            tan_dist_x = 2 * dist_params[2] * image_points[:, 0, :] * image_points[:, 1, :] + \
                            dist_params[3] * (xy_squared_norm + 2 * (image_points[:, 0, :] ** 2))
            tan_dist_y = dist_params[2] * (xy_squared_norm + 2 * (image_points[:, 1, :] ** 2)) + \
                        2 * dist_params[3] * image_points[:, 0, :] * image_points[:, 1, :]
            dist_cam_points = np.concatenate(((rad_dist_x + tan_dist_x)[:, np.newaxis, :],
                                            (rad_dist_y + tan_dist_y)[:, np.newaxis, :],
                                            np.ones((N, 1, 8), dtype=boxes_corner.dtype)), axis=1)
            dist_cam_points = dist_cam_points.transpose((0, 2, 1))
        return dist_cam_points

    def add_distortion_to_points(self, points, dist_params, project_mat, dist_mode="radtan"):
        # [k1, k2, p1, p2, k3, k4, k5, k6]
        # points (3, N)
        N = points.shape[1]
        if dist_mode == "radtan":
            if len(dist_params) != 8:
                print("invalid")
                return
            if not isinstance(dist_params, np.ndarray):
                # print("hello")
                dist_params = np.array(dist_params, dtype=np.float64)
            if not isinstance(project_mat, np.ndarray):
                project_mat = np.array(project_mat, dtype=np.float32)
            # print(dist_params)
            # print(project_mat[0, 2])
            image_points = np.matmul(project_mat, points)
            image_points[0, :] = image_points[0, :] / np.absolute(image_points[-1, :])
            image_points[1, :] = image_points[1, :] / np.absolute(image_points[-1, :])
            
            image_points[0, :] = (image_points[0, :] - project_mat[0, 2]) / project_mat[0, 0]
            image_points[1, :] = (image_points[1, :] - project_mat[1, 2]) / project_mat[1, 1]

            xy_squared_norm = image_points[0, :] ** 2 + image_points[1, :] ** 2
            rad_dist_x = image_points[0, :] * (1 + dist_params[0] * xy_squared_norm +
                                                dist_params[1] * (xy_squared_norm ** 2) +
                                                dist_params[4] * (xy_squared_norm ** 3)) / \
                                                (1 + dist_params[5] * xy_squared_norm + 
                                                dist_params[6] * (xy_squared_norm ** 2) +
                                                dist_params[7] * (xy_squared_norm ** 3))
            rad_dist_y = image_points[1, :] * (1 + dist_params[0] * xy_squared_norm +
                                                dist_params[1] * (xy_squared_norm ** 2) +
                                                dist_params[4] * (xy_squared_norm ** 3)) / \
                                                (1 + dist_params[5] * xy_squared_norm + 
                                                dist_params[6] * (xy_squared_norm ** 2) +
                                                dist_params[7] * (xy_squared_norm ** 3))
            tan_dist_x = 2 * dist_params[2] * image_points[0, :] * image_points[1, :] + \
                            dist_params[3] * (xy_squared_norm + 2 * (image_points[0, :] ** 2))
            tan_dist_y = dist_params[2] * (xy_squared_norm + 2 * (image_points[1, :] ** 2)) + \
                        2 * dist_params[3] * image_points[0, :] * image_points[1, :]
            dist_cam_points = np.concatenate(((rad_dist_x + tan_dist_x)[np.newaxis, :],
                                            (rad_dist_y + tan_dist_y)[np.newaxis, :],
                                            np.ones((1, N), dtype=points.dtype)), axis=0)
        return dist_cam_points

    def boxes_camera_to_image(self, boxes_cam, project_mat):
        N = boxes_cam.shape[0]
        if N == 0:
            return np.zeros((0, 8, 2), dtype=boxes_cam.dtype)
        if not isinstance(project_mat, np.ndarray):
            project_mat = np.array(project_mat, dtype=np.float32)
        project_mats = [project_mat for _ in range(N)]
        project_mats = np.array(project_mats, dtype=boxes_cam.dtype)
        image_points = np.matmul(project_mats, boxes_cam.transpose((0, 2, 1)))
        image_points[:, 0, :] = image_points[:, 0, :] / np.absolute(image_points[:, -1, :])
        image_points[:, 1, :] = image_points[:, 1, :] / np.absolute(image_points[:, -1, :])
        return image_points[:, :2, :].transpose(0, 2, 1)

    def points_camera_to_image(self, points, project_mat, device="cpu"):
        device = torch.device(device if torch.cuda.is_available() else "cpu")
        points = torch.as_tensor(points, dtype=torch.float32, device=device)
        project_mat = torch.as_tensor(project_mat, dtype=torch.float32, device=device)
        if project_mat.dim() == 2:
            project_mat = project_mat.unsqueeze(0)
        if points.dim() == 2:
            points = points.unsqueeze(0)
        image_points = torch.bmm(project_mat, points)
        image_points = image_points[:, :2] / torch.abs(image_points[:, 2:3])
        return image_points

    def draw_bbox(self, img, points_2d, color=(0, 255, 0), thickness=2):
        """
        绘制八点框
        :param img: 图像
        :param points_2d: (8, 2) 投影点
        :param color: 线框颜色
        :param thickness: 线框厚度
        """
        # 定义八点框的边（按点的索引连接）
        edges = [
            (0, 1), (1, 2), (2, 3), (3, 0),  # 底面
            (4, 5), (5, 6), (6, 7), (7, 4),  # 顶面
            (0, 4), (1, 5), (2, 6), (3, 7)   # 竖线
        ]
        for i, j in edges:
            pt1 = tuple(map(int, points_2d[i]))
            pt2 = tuple(map(int, points_2d[j]))
            cv2.line(img, pt1, pt2, color, thickness)

    def draw_lidar_points(self, img, points, colors, point_size=1):
        assert points.shape[0] == colors.shape[0]
        for idx in range(points.shape[0]):
            try:
                x, y = int(points[idx][0]), int(points[idx][1])
                if 0 <= x < img.shape[1] and 0 <= y < img.shape[0]:  # Check image bounds
                    cv2.circle(img, (x, y), point_size, (colors[idx][2], colors[idx][1], colors[idx][0]), -1)  # Green dot
            except:
                continue
    
    def draw_depth_image(self, img, depth_image, point_size=1, max_distance=100, valid_mask=None):
        depth_normalized = np.clip(depth_image, a_min=0, a_max=max_distance) / max_distance
        depth_normalized = np.expand_dims((depth_normalized * 255).astype(np.uint8), axis=-1)
        # 使用 matplotlib 的 colormap (例如 'viridis' 或 'jet')
        # colormap = cm.get_cmap('jet')  # 'jet' 映射为蓝-绿-红梯度
        rgb_image = cv2.applyColorMap(depth_normalized, cv2.COLORMAP_JET)
        # depth_colors = colormap(depth_normalized)[:, :3]  # 提取 RGB 值 (忽略 alpha 通道)
        # depth_colors = (depth_colors * 255)
        # 内部过滤：不绘制 depth==0 的点
        for x in range(depth_normalized.shape[0]):
            for y in range(depth_normalized.shape[1]):
                if depth_image[x, y] <= 1e-7:
                    continue
                if valid_mask is not None and not valid_mask[x, y]:
                    continue
                color = rgb_image[x, y]
                color = (int(color[0]), int(color[1]), int(color[2]))
                cv2.circle(img, (y, x), point_size, color, -1)


