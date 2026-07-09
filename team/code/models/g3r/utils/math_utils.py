import torch
import numpy as np
from scipy.spatial import cKDTree
from sklearn.neighbors import NearestNeighbors
from concurrent.futures import ThreadPoolExecutor


def nearest_distances_kdtree(points):
    tree = cKDTree(points)
    distances, _ = tree.query(points, k=2, workers=-1)
    min_distances = torch.from_numpy(distances[:, 1])
    return min_distances

def inverse_sigmoid(x):
    return torch.log(x/(1-x))

def quaternion_multiply_torch(q1, q2):
    w1, x1, y1, z1 = q1[:, 0], q1[:, 1], q1[:, 2], q1[:, 3]
    w2, x2, y2, z2 = q2[:, 0], q2[:, 1], q2[:, 2], q2[:, 3]

    w = w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2
    x = w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2
    y = w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2
    z = w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2
    return torch.stack([w, x, y, z], dim=1)

def compute_normal_and_quaternion(i, points, indices):
    neighbors = points[indices[i]]
    centroid = np.mean(neighbors, axis=0)
    centered_points = neighbors - centroid
    cov_matrix = np.cov(centered_points, rowvar=False)
    eigenvalues, eigenvectors = np.linalg.eigh(cov_matrix)
    normal = eigenvectors[:, np.argmin(eigenvalues)]
    
    if normal[2] < 0:
        normal = -normal
    normal = normal / np.linalg.norm(normal)
    
    quaternion = quaternion_from_vectors(np.array([0, 0, 1]), normal)
    return i, quaternion

def compute_normals_and_quaternions(points, k=6, use_multi_thread=True):
    points = points.numpy().astype(np.float64)
    points_number = points.shape[0]
    nbrs = NearestNeighbors(n_neighbors=k, algorithm='auto').fit(points)

    _, indices = nbrs.kneighbors(points)
    quaternions = np.zeros((points_number, 4))

    if use_multi_thread:
        with ThreadPoolExecutor(max_workers=64) as executor:
            futures = [
                executor.submit(compute_normal_and_quaternion, i, points, indices)
                for i in range(points_number)
            ]
            for future in futures:
                i, quaternion = future.result()
                quaternions[i] = quaternion
    else:
        for i in range(points.shape[0]):
            neighbors = points[indices[i]]
            centroid = np.mean(neighbors, axis=0)

            centered_points = neighbors - centroid
            cov_matrix = np.cov(centered_points, rowvar=False)
            eigenvalues, eigenvectors = np.linalg.eigh(cov_matrix)
            normal = eigenvectors[:, np.argmin(eigenvalues)]
            if normal[2] < 0:
                normal = -normal
            normal = normal / np.linalg.norm(normal)
            quaternions[i] = quaternion_from_vectors(np.array([0, 0, 1]), normal)

    return torch.from_nummpy(quaternions)

def quaternion_from_vectors(v1, v2): # rot from v1 to v2
    v1 = v1 / np.linalg.norm(v1)
    v2 = v2 / np.linalg.norm(v2)
    # compute axis of rotation 
    axis = np.cross(v1, v2)
    axis_norm = np.linalg.norm(axis)

    # vectors are parallel
    if axis_norm < 1e-10:
        return np.array([1,0,0,0])

    # compute quaternion 
    angle = np.arccos(np.dot(v1, v2))
    axis = axis / axis_norm 
    qw = np.cos(angle /2)
    qx, qy, qz = axis * np.sin(angle /2)
    return np.array([qw, qx, qy, qz])