import os, sys
import numpy as np
import shutil
import yaml
import time
import json
import open3d as o3d
import oss2

from plyfile import PlyData, PlyElement
from functools import wraps
from PIL import Image
from pathlib import Path

from settings.globals import SemanticType, DATASET_CLASSES_IN_SEMANTIC


def storePly(path, xyz, rgb):
    # set rgb to 0 - 255
    if rgb.max() <= 1. and rgb.min() >= 0:
        rgb = np.clip(rgb * 255, 0., 255.)
    # Define the dtype for the structured array
    dtype = [('x', 'f4'), ('y', 'f4'), ('z', 'f4'),
            ('nx', 'f4'), ('ny', 'f4'), ('nz', 'f4'),
            ('red', 'u1'), ('green', 'u1'), ('blue', 'u1')]
    
    normals = np.zeros_like(xyz)

    elements = np.empty(xyz.shape[0], dtype=dtype)
    attributes = np.concatenate((xyz, normals, rgb), axis=1)
    elements[:] = list(map(tuple, attributes))

    # Create the PlyData object and write to file
    vertex_element = PlyElement.describe(elements, 'vertex')
    ply_data = PlyData([vertex_element])
    ply_data.write(path)


def cleanup_ipy_in_folders(folder_path):
    folder_path_to_remove = []
    file_path_to_remove = []
    for root, folders, files in os.walk(folder_path):
        for folder in folders:
            if ".ipynb" in folder:
                folder_path_to_remove.append(os.path.join(root, folder))
        
        for file in files:
            if "-checkpoint." in file:
                file_path = os.path.join(root, file)
                file_path_to_remove.append(file_path)
    
    for f in file_path_to_remove:
        print("[INFO] Cleanup file: ", f)
        os.remove(f)

    for f in folder_path_to_remove:
        print("[INFO] Cleanup folder: ", f)
        shutil.rmtree(f)
        

def cleanup_clip_folder(clip_path):
    image_origin_dir = os.path.join(clip_path, "images_origin")
    image_dir = os.path.join(clip_path, "images")
    mask_dir = os.path.join(clip_path, "masks")
    mask_obj_dir = os.path.join(clip_path, "masks_obj")
    pcd_dir = os.path.join(clip_path, "pcd")
    autolabel_json = os.path.join(clip_path, "autolabel_json")
    for folder in [image_origin_dir, image_dir, mask_dir, mask_obj_dir, pcd_dir, autolabel_json]:
        if os.path.exists(folder):
            cleanup_ipy_in_folders(folder)


def load_yaml(config_path):
    with open(config_path, 'rb') as f:
        config = yaml.safe_load(f)
    return config


def get_files_in_folder(folder_path):
    file_paths = []
    for root, _, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            file_paths.append(file_path)
    return file_paths


def timer(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        elapsed_time = end_time - start_time
        print(f"[TIMER] Function '{func.__name__}' executed in {elapsed_time:.6f} seconds\n")
        return result
    return wrapper


def get_semantics_from_path(filepath: Path):
    pil_image = Image.open(filepath)
    image = np.array(pil_image, dtype="int64")
    if len(image.shape) == 3:
        image = image[:, :, 0]
    
    class_to_bit = {
        SemanticType.VEHICLE.value: 1,  # 2^0
        SemanticType.HUMAN.value: 2,    # 2^1
        SemanticType.SKY.value: 4,      # 2^2
        SemanticType.GROUND.value: 8, # 2^3
        SemanticType.LANELINE.value: 16, # 2^4
        SemanticType.TrafficLight.value: 32
    }
    
    class_to_label = {
        SemanticType.VEHICLE.value: DATASET_CLASSES_IN_SEMANTIC['VEHICLE'],
        SemanticType.HUMAN.value: DATASET_CLASSES_IN_SEMANTIC['HUMAN'],
        SemanticType.SKY.value: DATASET_CLASSES_IN_SEMANTIC['SKY'],
        SemanticType.LANELINE.value: DATASET_CLASSES_IN_SEMANTIC['LANELINE'],
        SemanticType.GROUND.value: DATASET_CLASSES_IN_SEMANTIC['GROUND'],
        SemanticType.TrafficLight.value: DATASET_CLASSES_IN_SEMANTIC['TrafficLight']
    }
    
    semantics = np.zeros_like(image, dtype=np.uint8)
    
    for label, class_ids in class_to_label.items():
        bit_mask = class_to_bit[label]
        semantics[np.isin(image, class_ids)] |= bit_mask
    
    return semantics


def get_mask_from_semantics(semantics, semantic_type: SemanticType):
    class_to_bit = {
        SemanticType.VEHICLE: 1,   # 2^0
        SemanticType.HUMAN: 2,     # 2^1
        SemanticType.SKY: 4,       # 2^2
        SemanticType.GROUND: 8,  # 2^3
        SemanticType.LANELINE: 16,    # 2^4
        SemanticType.TrafficLight:32
    }

    bit_mask = class_to_bit[semantic_type]
    mask = np.ones_like(semantics)
    mask[semantics & bit_mask != 0] = 0 
    
    return mask.astype("uint8")


def read_pcd(file_path, rig2anchor, lidar2rig, lidar_points_valid_range=None):
    # 读取pcd
    import open3d as o3d
    pcd_data = o3d.io.read_point_cloud(file_path)
    assert pcd_data.has_points(), f"[ERROR] Point cloud data is empty: {file_path}"
    points = np.array(pcd_data.points, dtype=np.float32)
    nan_rows = np.isnan(points).any(axis=1)
    points = points[~nan_rows]
    # 将每个点表示为齐次坐标 (x, y, z, 1)
    homogeneous_positions = np.hstack([points , np.ones((points.shape[0], 1), dtype=np.float32)])
    points2rig = np.dot(lidar2rig.astype(np.float32), homogeneous_positions.T).T
    if lidar_points_valid_range is not None:
        valid_x = np.logical_and(points2rig[:, 0] > lidar_points_valid_range[0][0],
            points2rig[:, 0] < lidar_points_valid_range[0][1])
        valid_y = np.logical_and(points2rig[:, 1] > lidar_points_valid_range[1][0],
            points2rig[:, 1] < lidar_points_valid_range[1][1])
        valid_z = np.logical_and(points2rig[:, 2] > lidar_points_valid_range[2][0],
            points2rig[:, 2] < lidar_points_valid_range[2][1])
        valid = valid_x * valid_y * valid_z
        points2rig = points2rig[valid]

    transformed_positions = np.dot(rig2anchor.astype(np.float32), points2rig.T).T[:, :3]
    pcds = o3d.geometry.PointCloud()
    pcds.points = o3d.utility.Vector3dVector(transformed_positions)
    return pcds


def save_time_diff(clip_path):
    from matplotlib import pyplot as plt
    cam_timestamps = json.load(open(os.path.join(clip_path, "cam_timestamps.json")))
    lidar_meta = json.load(open(os.path.join(clip_path, "lidar_metas.json")))

    # plot the timestamp difference between cam2 and [lidar, cam0, cam3 to cam6]
    cam2_timestamps = cam_timestamps["cam2"]
    lidar_timestamps = sorted([i['collected_at'] for i in lidar_meta.values()])
    fig, ax = plt.subplots(2, 3, figsize=(20, 10))
    time_diff = []
    for i in range(len(cam2_timestamps)):
        cam2_time = cam2_timestamps[i]
        lidar_time = lidar_timestamps[i]
        time_diff.append((cam2_time - lidar_time)/1e6)

    ax[1,2].scatter(range(len(time_diff)), time_diff, s=2, label="cam2_time - lidar_time [ms]")
    ax[1,2].set_title("cam2_time - lidar_time [ms]")

    for idx, cam in enumerate(["cam0", "cam3", "cam4", "cam5", "cam6"]):
        cam_times = cam_timestamps[cam]
        time_diff = []
        for i in range(len(cam2_timestamps)):
            cam2_time = cam2_timestamps[i]
            cam_time = cam_times[i]
            time_diff.append((cam2_time - cam_time)/1e6)
        fig_row = idx//3
        fig_col = idx%3
        ax[fig_row, fig_col].scatter(range(len(time_diff)), time_diff, s=2, label=f"cam2_time - {cam}_time [ms]")
        ax[fig_row, fig_col].set_title(f"cam2_time - {cam}_time [ms]")

    fig.tight_layout()
    plt.savefig(os.path.join(clip_path, "time_diff.png"))


class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


def read_custom_ply_with_colors(file_path):
    """
    Reads a PLY file generated by gaussian_model.py, which contains
    non-standard color properties ('r', 'g', 'b'), and constructs an
    Open3D PointCloud object with the correct color information.

    Args:
        file_path (str): The path to the .ply file.

    Returns:
        open3d.geometry.PointCloud: A point cloud object with points and colors
                                      loaded successfully. If the file does not
                                      contain color information, the returned
                                      point cloud will only have points. Returns
                                      None if an error occurs.
    """
    try:
        # 1. Read the file using plyfile
        plydata = PlyData.read(file_path)
        vertex_element = plydata['vertex']

        # 2. Extract coordinate data
        x = np.asarray(vertex_element['x'])
        y = np.asarray(vertex_element['y'])
        z = np.asarray(vertex_element['z'])
        points = np.vstack((x, y, z)).T

        # 3. Create an Open3D PointCloud object
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(points)

        # 4. Try to extract the non-standard 'r', 'g', 'b' color properties
        try:
            # These color values are float32 in the [0, 1] range,
            # which is what Open3D expects for pcd.colors.
            r = np.asarray(vertex_element['r'])
            g = np.asarray(vertex_element['g'])
            b = np.asarray(vertex_element['b'])
            colors = np.vstack((r, g, b)).T

            # Check if color values are within the expected [0, 1] range
            if colors.max() > 1.0 or colors.min() < 0.0:
                print("Warning: Color values are outside the expected [0, 1] range. Normalization might be required.")

            pcd.colors = o3d.utility.Vector3dVector(colors)

        except ValueError:
            # plyfile raises a ValueError if the 'r', 'g', 'b' properties do not exist
            print(f"Warning: Color properties 'r', 'g', 'b' not found in file '{file_path}'.")
            # The returned point cloud will not contain color information in this case

        print(f"Successfully loaded point cloud from '{file_path}'.")
        print(f"Number of points: {len(pcd.points)}")
        if pcd.has_colors():
            print("Point cloud has color information.")
        else:
            print("Point cloud does not have color information.")

        return pcd

    except Exception as e:
        print(f"An error occurred while reading file '{file_path}': {e}")
        return None


def download_file_from_oss2(
        local_file_path="/workspace/yangxh7@xiaopeng.com/3dgs_model.tgz",
        object_key = "sim_engine/ips_output_yxh/c-32499217-9887-3618-9119-c0ef4ee6cbb0/preprocess/3dgs_model.tgz",
        show_progress=True
    ):
    # Replace these with your actual values
    access_key_id = "OSS_ACCESS_KEY_ID_REDACTED"
    access_key_secret = "OSS_ACCESS_KEY_SECRET_REDACTED"
    bucket_name = "cloudsim-ci-sh"
    endpoint = "http://oss-cn-wulanchabu-internal.aliyuncs.com"  # Replace with your region

    # Initialize the OSS Auth and Bucket
    auth = oss2.Auth(access_key_id, access_key_secret)
    bucket = oss2.Bucket(auth, endpoint, bucket_name)
    
    # Progress callback function
    def progress_callback(consumed_bytes, total_bytes):
        if total_bytes:
            progress = int(consumed_bytes * 100 / total_bytes)
            sys.stdout.write(f"\rDownloading: {progress}%")
            sys.stdout.flush()

    try:
        if show_progress:
            bucket.get_object_to_file(object_key, local_file_path, progress_callback=progress_callback)
            print(f"\nFile {object_key} downloaded successfully!")
        else:
            bucket.get_object_to_file(object_key, local_file_path)
        return True
    except oss2.exceptions.AccessDenied as e:
        print("Access denied. Please check your credentials or bucket permissions.")
        return False
    except oss2.exceptions.NoSuchKey:
        print("The specified file does not exist.")
        return False
    except Exception as e:
        print(f"An error occurred: {e}")
        return False