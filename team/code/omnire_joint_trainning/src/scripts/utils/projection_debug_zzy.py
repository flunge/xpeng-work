import numpy as np
import cv2
from pypcd import pypcd

def batch_boxes_center_to_corner(boxes_center):
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

def boxes_to_camera(boxes_center, ex_params):
    N = boxes_center.shape[0]
    if N == 0:
        return np.zeros((0, 8, 3), dtype=boxes_center.dtype)
    data_type = boxes_center.dtype
    boxes_corner = batch_boxes_center_to_corner(boxes_center)
    boxes_corner = np.concatenate((boxes_corner, np.ones((N, 8, 1), dtype=data_type)), axis=2)
    ex_matrixes = [ex_params for _ in range(N)]
    ex_matrixes = np.array(ex_matrixes, dtype=data_type)
    result = np.matmul(ex_matrixes, boxes_corner.transpose((0, 2, 1))).transpose((0, 2, 1))
    for i in range(result.shape[2]):
        result[:, :, i] = result[:, :, i] / result[:, :, -1]
    return result[:, :, :3]

def lidar_points_to_camera(points, ex_params):
    N = points.shape[1]
    data_type = points.dtype
    new_points = np.concatenate((points, np.ones((1, N), dtype=data_type)), axis=0)
    result = np.matmul(ex_params, new_points)
    for i in range(result.shape[0]):
        result[i, :] = result[i, :] / result[-1, :]
    return result[:3, :]

def add_distortion(boxes_corner, dist_params, project_mat, dist_mode="radtan"):
    # [k1, k2, p1, p2, k3, k4, k5, k6]
    N = boxes_corner.shape[0]
    if N == 0:
        return np.zeros((0, 8, 3), dtype=boxes_corner.dtype)
    if dist_mode == "radtan":
        if len(dist_params) != 8:
            print("invalid")
            return
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

def add_distortion_to_points(points, dist_params, project_mat, dist_mode="radtan"):
    # [k1, k2, p1, p2, k3, k4, k5, k6]
    # points (3, N)
    N = points.shape[1]
    if dist_mode == "radtan":
        if len(dist_params) != 8:
            print("invalid")
            return

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

def boxes_camera_to_image(boxes_cam, project_mat):
    N = boxes_cam.shape[0]
    if N == 0:
        return np.zeros((0, 8, 2), dtype=boxes_cam.dtype)
    project_mats = [project_mat for _ in range(N)]
    project_mats = np.array(project_mats, dtype=boxes_cam.dtype)
    image_points = np.matmul(project_mats, boxes_cam.transpose((0, 2, 1)))
    image_points[:, 0, :] = image_points[:, 0, :] / np.absolute(image_points[:, -1, :])
    image_points[:, 1, :] = image_points[:, 1, :] / np.absolute(image_points[:, -1, :])
    return image_points[:, :2, :].transpose(0, 2, 1)

def points_camera_to_image(points, project_mat):
    N = points.shape[1]
    project_mats = np.array(project_mat, dtype=points.dtype)
    image_points = np.matmul(project_mats, points)
    image_points[0, :] = image_points[0, :] / np.absolute(image_points[-1, :])
    image_points[1, :] = image_points[1, :] / np.absolute(image_points[-1, :])
    return image_points[:2, :]


def draw_bbox(img, points_2d, color=(0, 255, 0), thickness=2):
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

def draw_lidar_points(img, points):
    for point in points:
        try:
            x, y = int(point[0]), int(point[1])
            if 0 <= x < img.shape[1] and 0 <= y < img.shape[0]:  # Check image bounds
                cv2.circle(img, (x, y), 1, (0, 255, 0), -1)  # Green dot
        except:
            continue
    

if __name__ == "__main__":
    image_path = "/home/par-jiagangzhu/JijiaWork/xp_data/processed_data/c-fffbbe20-7c67-3729-a449-f26bc0e9f67e/images_origin/cam2/1719209605617086347.png"
    undistorted_image_path = "/home/par-jiagangzhu/JijiaWork/xp_data/processed_data/c-fffbbe20-7c67-3729-a449-f26bc0e9f67e/images/cam2/1719209605617086347.png"
    example_box_center = [[18.28079, 3.11635, 0.81147, 1.91389, 4.95886, 1.6547, -0.0036106766233189778]]
    example_box_center = np.array(example_box_center, dtype=np.float32)
    # example_box_center = np.expand_dims(example_box_center, axis=0)
    dist_params = [1.73327422, 0.414135277, 9.62825652e-06, 3.16780097e-05, 
                   0.00666139508, 2.1019454, 0.937177837, 0.0607602783]
    dist_params = np.array(dist_params, dtype=np.float32)
    in_mat = [[953.4520250000002, 0.0, 958.56421],
                [0.0, 953.4520250000002, 543.611145],
                [0.0, 0.0, 1.0]]
    in_mat = np.array(in_mat, dtype=np.float32)
    ex_mat_cam2 = [
                [
                    0.000102877617,
                    -0.999957681,
                    0.00919395685,
                    -0.00971274078
                ],
                [
                    0.118514113,
                    -0.00911688805,
                    -0.992910445,
                    1.25674462
                ],
                [
                    0.992952287,
                    0.00119169278,
                    0.11850822,
                    -2.0764451
                ],
                [
                    0.0,
                    0.0,
                    0.0,
                    1.0
                ]
            ]
    ex_mat_cam2 = np.array(ex_mat_cam2, dtype=np.float32)
    ex_mat_lidar1 =  [
                [
                    0.8390675588777439,
                    -0.543918321759321,
                    -0.010887132715504087,
                    -3.4102867997959407
                ],
                [
                    0.5439925920153155,
                    0.8390719842472226,
                    0.005501652127340202,
                    -1.2964715155692248
                ],
                [
                    0.006142639033971939,
                    -0.010538777235900545,
                    0.9999255836263268,
                    -0.6590445430158636
                ],
                [
                    0.0,
                    0.0,
                    0.0,
                    1.0
                ]
            ]
    ex_mat_lidar1 = np.array(ex_mat_lidar1, dtype=np.float32)

    # example_box_cam = boxes_to_camera(example_box_center, ex_mat_cam2)
    # example_box_dist = add_distortion(example_box_cam, dist_params, in_mat)
    # example_image_points = boxes_camera_to_image(example_box_dist, in_mat)
    # example_image_points = example_image_points[0]

    # undistorted_image_cropped_path = "./undistorted_image_cropped.jpg"
    # 读取图片
    image = cv2.imread(image_path)
    print("origin img: ", image.shape)

    undistorted_image = cv2.imread(undistorted_image_path)
    new_K = [[741.6997300229634, 0.0, 1533.229340977794],
             [0.0, 741.6997300229634, 873.1083838036953],
             [0.0, 0.0, 1.0]]


    # Load the point cloud from a PCD file
    # 读取点云
    # pcd_file = 'example.pcd'  # Replace with the path to your PCD file
    pcd_path = "/home/par-jiagangzhu/JijiaWork/xp_data/processed_data/c-fffbbe20-7c67-3729-a449-f26bc0e9f67e/pcd/1719209605617086347.pcd"
    pc = pypcd.PointCloud.from_path(pcd_path)
    # Extract x, y, z coordinates
    x = pc.pc_data['x']
    y = pc.pc_data['y']
    z = pc.pc_data['z']

    # Example: Create a (N, 3) numpy array of point positions
    points = np.column_stack((x, y, z))
    points = points.transpose((1, 0))

    # lidar to car
    lidar_points_cam = lidar_points_to_camera(points, ex_mat_cam2 @ np.linalg.inv(ex_mat_lidar1))
    # lidar_points_dist = add_distortion_to_points(lidar_points_cam, dist_params, in_mat)
    # car to camera 
    lidar_points_image = points_camera_to_image(lidar_points_cam, new_K)
    lidar_points_image = lidar_points_image.transpose((1, 0))

    draw_lidar_points(undistorted_image, lidar_points_image)
    # draw_bbox(image, example_image_points)
    # 显示结果
    undistorted_image = cv2.resize(undistorted_image, (1920, 1080))
    cv2.imshow("3D Bounding Box", undistorted_image)
    while True:
        key = cv2.waitKey(1) & 0xFF  # 使用0xFF只获取键盘输入的低8位
        if key == ord('q'):  # 按下 'q' 键
            print("按下 'q' 键，退出...")
            break
    cv2.destroyAllWindows()


    # # pcd_file = 'example.pcd'  # Replace with the path to your PCD file
    # pcd_path = "/home/par-jiagangzhu/JijiaWork/xp_data/image/c-fffbbe20-7c67-3729-a449-f26bc0e9f67e/pcd/1719209605617086347.pcd"
    # pc = pypcd.PointCloud.from_path(pcd_path)
    # # Extract x, y, z coordinates
    # x = pc.pc_data['x']
    # y = pc.pc_data['y']
    # z = pc.pc_data['z']
