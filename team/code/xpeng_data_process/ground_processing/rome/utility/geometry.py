import os
import cv2
import torch
import numpy as np
from scipy import spatial
from scipy.spatial import Delaunay

def createFlatMesh(x_length, y_length, resolution=0.1):
    """
    Create a flat mesh for testing.

    Args:
        x_length (float): Length along x of the mesh.
        y_length (float): Length along y of the mesh.
        resolution (float): Resolution of the mesh.

    Returns:
        torch.Tensor: A tensor of shape (N, 3) containing the vertices of the mesh.
        torch.Tensor: A tensor of shape (N, 3) containing the faces of the mesh.
    """
    num_vertices_x = int(x_length / resolution) + 1
    num_vertices_y = int(y_length / resolution) + 1
    assert num_vertices_x > 0 and num_vertices_y > 0, "Mesh resolution too high."

    vertices = torch.zeros((num_vertices_x, num_vertices_y, 3), dtype=torch.float32)
    vertices[:, :, 0] = torch.unsqueeze(torch.linspace(0, x_length, num_vertices_x), dim=0).T
    vertices[:, :, 1] = torch.unsqueeze(torch.linspace(0, y_length, num_vertices_y), dim=0)
    vertices = vertices.reshape(-1, 3)

    # 2 means top-right and bottom-left triangles
    # 3 means 3 vertices of each trianle
    faces = torch.zeros((num_vertices_x - 1, num_vertices_y - 1, 2, 3), dtype=torch.int64)
    all_indices = torch.arange(0, num_vertices_x * num_vertices_y, 1, dtype=torch.int64).reshape((num_vertices_x, num_vertices_y))
    faces[:, :, 0, 0] = all_indices[:-1, :-1]
    faces[:, :, 0, 1] = all_indices[:-1, 1:]
    faces[:, :, 0, 2] = all_indices[1:, 1:]
    faces[:, :, 1, 0] = all_indices[:-1, :-1]
    faces[:, :, 1, 1] = all_indices[1:, 1:]
    faces[:, :, 1, 2] = all_indices[1:, :-1]
    faces = faces.reshape(-1, 3)
    return vertices, faces, (num_vertices_x, num_vertices_y)


def createHiveFlatMesh(x_length, y_length, resolution=0.1):
    """
    Create a flat hive mesh.

    Args:
        x_length (float): Length along x of the mesh.
        y_length (float): Length along y of the mesh.
        poses (torch.Tensor): A tensor of shape (N, 3) containing the poses of the mesh.
        resolution (float): Resolution of the mesh. default: 1
    Returns:
        torch.Tensor: A tensor of shape ((num_vertices_x * num_vertices_y), 3) containing the vertices of the mesh.
        torch.Tensor: A tensor of shape ((num_vertices_x-1) * (num_vertices_y-1), 3) containing the faces of the mesh.
    """
    x_resolution = resolution
    y_resolution = x_resolution * 2 / 1.7320508075688772
    num_vertices_x = int(x_length / x_resolution) + 1
    num_vertices_y = int(y_length / y_resolution) + 1
    assert num_vertices_x > 0 and num_vertices_y > 0, "Mesh resolution too high."
    vertices = torch.zeros((num_vertices_x, num_vertices_y, 3), dtype=torch.float32)
    vertices[:, :, 0] = torch.unsqueeze(torch.linspace(0, x_length, num_vertices_x), dim=0).T
    for i in range(num_vertices_x):
        if i % 2 == 0:
            vertices[i, :, 1] = torch.linspace(0, y_length + y_resolution / 2, num_vertices_y)
        else:
            vertices[i, :, 1] = torch.linspace(-y_resolution / 2, y_length, num_vertices_y)
    vertices = vertices.reshape(-1, 3)

    # 2 means top-right and bottom-left triangles
    # 3 means 3 vertices of each trianle
    faces = torch.zeros((num_vertices_x - 1, num_vertices_y - 1, 2, 3), dtype=torch.int64)
    all_indices = torch.arange(0, num_vertices_x * num_vertices_y, 1, dtype=torch.int64).reshape((num_vertices_x, num_vertices_y))
    faces[:, :, 0, 0] = all_indices[:-1, :-1]
    faces[:, :, 0, 1] = all_indices[:-1, 1:]
    faces[:, :, 0, 2] = all_indices[1:, 1:]
    faces[:, :, 1, 0] = all_indices[:-1, :-1]
    faces[:, :, 1, 1] = all_indices[1:, 1:]
    faces[:, :, 1, 2] = all_indices[1:, :-1]

    # face 0 vert 0 down, face 1 vert 1 up in odd row
    faces[1::2, :, 0, 0] = faces[1::2, :, 1, 2]
    faces[1::2, :, 1, 1] = faces[1::2, :, 0, 1]
    faces = faces.reshape(-1, 3)

    ### vertices have (x_length/x_resolution, y_length/y_resolution) points. Arranged like a hive.
    ### faces have (x_length/x_resolution-1, y_length/y_resolution-1) triangle.
    return vertices, faces, (num_vertices_x, num_vertices_y)


def cutHiveMeshWithPoses(vertices, faces, bev_size_pixel, x_length, y_length, poses_xy, resolution=0.1, cut_range=30):
    """
    Cut mesh using poses

    Args:
        vertices (torch.Tensor): A tensor of shape (N, 3) containing the vertices of the mesh.
        faces (torch.Tensor): A tensor of shape (N, 3) containing the faces of the mesh.
        bev_size_pixel (tuple): The size of the bev in pixel.
        x_length (float): Length along x of the mesh.
        y_length (float): Length along y of the mesh.
        poses_xy (torch.Tensor): A tensor of shape (N, 2) containing the poses in camera2world transform.
    """
    import pymeshlab
    x_resolution = resolution
    y_resolution = x_resolution * 2 / 1.7320508075688772
    (num_vertices_x, num_vertices_y) = bev_size_pixel
    # pose_xy to pixel_xy
    pixel_xy = np.zeros_like(poses_xy)
    min_poses = poses_xy[:, :2].min(0)
    pixel_xy[:, 0] = (poses_xy[:, 0] - min_poses[0] + cut_range) / x_resolution
    pixel_xy[:, 1] = (poses_xy[:, 1] - min_poses[1] + cut_range) / y_resolution
    pixel_xy = np.unique(pixel_xy.round(), axis=0)

    # construct the mask
    mask = np.zeros((num_vertices_x - 1, num_vertices_y - 1), dtype=np.uint8)
    pixel_xy[:, 0] = np.clip(pixel_xy[:, 0], 0, num_vertices_x - 2)
    pixel_xy[:, 1] = np.clip(pixel_xy[:, 1], 0, num_vertices_y - 2)
    pixel_xy = pixel_xy.astype(np.longlong)
    mask[pixel_xy[:, 0], pixel_xy[:, 1]] = 1
    # mask = mask[::-1, ::-1]  # rotate the mask 180 degrees
    # cv2.imwrite('mask.png', mask.astype(np.uint8) * 255)

    # dilate the mask
    kernel = np.ones((int(cut_range / x_resolution), int(cut_range / y_resolution)), dtype=np.uint8)
    mask = cv2.dilate(mask.astype(np.uint8), kernel, iterations=2)
    # cv2.imwrite('mask_dilate.png', mask.astype(np.uint8) * 255)

    # give faces colors
    face_quality = np.ones((num_vertices_x - 1, num_vertices_y - 1, 2, 1), dtype=np.float64)
    face_quality[mask == 0, :, 0] = 0.0
    face_quality = face_quality.reshape(-1, 1)
    source_mesh = pymeshlab.Mesh(vertex_matrix=vertices.numpy(), face_matrix=faces.numpy(), f_quality_array=face_quality)
    ms = pymeshlab.MeshSet()
    ms.add_mesh(source_mesh, "source_mesh")
    m = ms.current_mesh()
    # face_color_matrix = m.face_color_matrix()
    ms.conditional_face_selection(condselect="fq < 1")  # equals to fr == 0
    # print(ms.current_mesh().selected_face_number())
    ms.delete_selected_faces()
    ms.remove_unreferenced_vertices()
    m = ms.current_mesh()

    # get numpy arrays of vertices and faces of the current mesh
    v_matrix = torch.from_numpy(m.vertex_matrix().astype(np.float32))
    f_matrix = torch.from_numpy(m.face_matrix().astype(np.int64))
    # ms.save_current_mesh("filted.ply")

    return v_matrix, f_matrix, (num_vertices_x, num_vertices_y)

def createMultiResolutionMesh(bev_seg_image_path, low_bev_resolution, high_bev_resolution):
    assert os.path.exists(bev_seg_image_path), f"bev_seg_image_path not exists: {bev_seg_image_path}"
    bev_seg_image = cv2.imread(bev_seg_image_path)
    bev_seg_image = cv2.cvtColor(bev_seg_image, cv2.COLOR_BGR2RGB)

    # label color
    mask_color = np.array([0, 0, 0])
    lane_color = np.array([0, 0, 255])
    curb_color = np.array([255, 0, 0])
    road_color = np.array([211, 211, 211])
    sidewalk_color = np.array([0, 191, 255])
    terrain_color = np.array([152, 251, 152])
    background_color = np.array([157, 234, 50])

    # generate 0.1m resolution vertexes
    road_area_uvs = np.argwhere(((bev_seg_image == road_color).all(axis=-1) | \
                                 (bev_seg_image == curb_color).all(axis=-1) | \
                                 (bev_seg_image == sidewalk_color).all(axis=-1) | \
                                 (bev_seg_image == terrain_color).all(axis=-1) | \
                                 (bev_seg_image == background_color).all(axis=-1)))[:, [1, 0]]
    vertex_x = (road_area_uvs[:, 0] * low_bev_resolution).reshape(-1, 1)
    vertex_y = ((bev_seg_image.shape[0] - road_area_uvs[:, 1]) * low_bev_resolution).reshape(-1, 1)
    road_area_vertex = np.concatenate((vertex_x, vertex_y), axis=1)

    # generate 0.02m resolution vertexes
    magnification = int(low_bev_resolution / high_bev_resolution)
    lane_area_uvs = np.argwhere((bev_seg_image == lane_color).all(axis=-1))[:, [1, 0]]
    lane_mask = np.zeros(bev_seg_image.shape[:2], dtype=np.uint8)
    lane_mask[lane_area_uvs[:, 1], lane_area_uvs[:, 0]] = 255

    # dilate the lane mask
    kernel = np.ones((3, 3), np.uint8)
    lane_mask = cv2.dilate(lane_mask.astype(np.uint8), kernel, iterations=1)
    new_height, new_width = lane_mask.shape[0] * magnification, lane_mask.shape[1] * magnification
    lane_mask = cv2.resize(lane_mask, (new_width, new_height), interpolation=cv2.INTER_NEAREST)
    lane_area_uvs = np.argwhere(lane_mask == 255)[:, [1, 0]]
    vertex_x = (lane_area_uvs[:, 0] * high_bev_resolution).reshape(-1, 1)
    vertex_y = ((lane_mask.shape[0] - lane_area_uvs[:, 1]) * high_bev_resolution).reshape(-1, 1)
    lane_area_vertex = np.concatenate((vertex_x, vertex_y), axis=1)

    # generate faces by delaunay triangulation
    vertexes = np.concatenate((road_area_vertex, lane_area_vertex), axis=0)
    tri = Delaunay(vertexes)
    faces = np.array(tri.simplices).astype(np.int64)
    vertexes = np.concatenate((vertexes, np.zeros((vertexes.shape[0], 1))), axis=1).astype(np.float32)

    # to torch tensor
    vertexes = torch.from_numpy(vertexes)
    faces = torch.from_numpy(faces)

    return vertexes, faces

def fps_by_distance(pointcloud, min_distance, return_idx=True, allow_same_gps=False):
    """subsample pointcloud by furthest point sampling algorithm

    Args:
        pointcloud (ndarray): shape=[N, 3] or [N, 2]
        min_distance (float): meters, minimum distance allowed in subsampled pointcloud
        return_idx (bool, optional): If set to true, return sampling index of original pointclouds.
        Defaults to True. Otherwise, return subsampled pointcloud
    """
    assert 2 <= pointcloud.shape[1] <= 3
    num_points = pointcloud.shape[0]
    sample_idx = np.zeros(num_points, dtype=bool)
    start_idx = np.random.randint(0, num_points)
    sample_idx[start_idx] = True
    sampled_min_distance = 1e9

    # Every time it returns a point that is furthest to all selected points, if the largest distance is greater than 240
    while np.any(~sample_idx) and sampled_min_distance > min_distance:
        sampled_points = pointcloud[sample_idx]
        local_min_list = []
        for point in pointcloud:
            distance = np.linalg.norm(point - sampled_points, ord=np.inf, axis=1)
            local_min = np.min(distance)
            if allow_same_gps and local_min == 0:
                local_min = min_distance + 1
            local_min_list.append(local_min)
        local_min_array = np.array(local_min_list)
        local_min_array[sample_idx] = 0
        furthest_point_idx = np.argmax(local_min_array)
        sampled_min_distance = local_min_array[furthest_point_idx]
        sample_idx[furthest_point_idx] = sampled_min_distance > min_distance
    if return_idx:
        return sample_idx
    else:
        return pointcloud[sample_idx]

def generate_waypoints(pose_xy_in, radius):
    pose_xy = pose_xy_in.copy()
    np.random.shuffle(pose_xy)

    kdtree = spatial.KDTree(data=pose_xy)
    waypoint_indices = np.arange(0, pose_xy.shape[0])

    waypoint_indices_tmp = waypoint_indices.copy()
    for curr_index in waypoint_indices_tmp:
        pose_indices_covered = []
        for index in waypoint_indices:
            if curr_index == index:
                continue
            covered = kdtree.query_ball_point(pose_xy[index], radius)
            pose_indices_covered += covered
        pose_indices_covered = np.unique(np.array(pose_indices_covered))
        if len(pose_indices_covered) == pose_xy.shape[0]:
            waypoint_indices = waypoint_indices[waypoint_indices != curr_index]

    return pose_xy[list(waypoint_indices)]


if __name__ == '__main__':
    # Create a mesh.
    vertices, faces, bev_size_pixel = createHiveFlatMesh(1.0, 1.0)
    pass
