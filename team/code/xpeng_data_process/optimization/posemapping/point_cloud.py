import numpy as np
import os
import open3d as o3d
import pandas as pd
from scipy.spatial import cKDTree

from .mod3d import Mod3D
from .pose import Pose
from .utils import bisearch_list_nearest, calc_normal_nb, get_output_dir, point_to_key_nb
from .vis import save_points

class MapPoint:
    def __init__(self, cloud_index:int, point3d:np.ndarray):
        self.cloud_index = cloud_index
        self.point3d = np.array(point3d)

    '''Create a map point from a dictionary'''
    @staticmethod
    def from_dict(map_point_dict:dict):
        # Get the cloud index from the map point dictionary
        cloud_index = map_point_dict['cloud_index']
        # Get the 3D point from the map point dictionary
        point3d = np.array(map_point_dict['point3d'])
        # Create a map point object using the cloud index, 3D point, and point type
        map_point = MapPoint(cloud_index, point3d)
        return map_point


    '''Convert the map point to a dictionary'''
    def to_dict(self):
        map_point_dict = {
            'cloud_index': self.cloud_index,
            'point3d': self.point3d.tolist()
        }
        return map_point_dict

class MapSurfel:
    def __init__(self, cloud_index:int, point3d:np.ndarray, normal3d:np.ndarray, point_type:int=0):
        self.cloud_index = cloud_index
        self.point3d = np.array(point3d)
        self.normal3d = np.array(normal3d)
        self.point_type = point_type

    '''Create a map surfel from a dictionary'''
    @staticmethod
    def from_dict(map_surfel_dict:dict):
        # Get the cloud index from the map surfel dictionary
        cloud_index = map_surfel_dict['cloud_index']
        # Get the 3D point from the map surfel dictionary
        point3d = np.array(map_surfel_dict['point3d'])
        # Get the 3D normal from the map surfel dictionary
        normal3d = np.array(map_surfel_dict['normal3d'])
        # Get the point type from the map surfel dictionary
        point_type = map_surfel_dict['point_type']
        # Create a map surfel object using the cloud index, 3D point, 3D normal, and point type
        map_surfel = MapSurfel(cloud_index, point3d, normal3d, point_type)
        return map_surfel

    '''Convert the map surfel to a dictionary'''
    def to_dict(self):
        map_surfel_dict = {
            'cloud_index': self.cloud_index,
            'point3d': self.point3d.tolist(),
            'normal3d': self.normal3d.tolist(),
            'point_type': self.point_type
        }
        return map_surfel_dict


class CachedPointCloud:
    def __init__(self, pointcloud:o3d.geometry.PointCloud=None, lidar_name:str=None, time:int=None):
        timestamp = time if time is not None else pd.Timestamp.now().timestamp()
        cloud_name = lidar_name if lidar_name is not None else "pointcloud"
        output_dir = get_output_dir("pcd")
        file_name = f"{cloud_name}_{timestamp}.pcd"
        self.save_path = os.path.join(output_dir, file_name)
        if pointcloud is not None and len(pointcloud.points) > 0:
            o3d.io.write_point_cloud(self.save_path, pointcloud, compressed=True)

    def get_pointcloud(self):
        if not os.path.exists(self.save_path):
            return o3d.geometry.PointCloud()
        return o3d.io.read_point_cloud(self.save_path)

    def set_pointcloud(self, pointcloud:o3d.geometry.PointCloud):
        o3d.io.write_point_cloud(self.save_path, pointcloud, compressed=True)

    def set_cached_pointcloud(self, cached_pointcloud):
        if self.save_path != cached_pointcloud.save_path:
            self.clear()
            self.save_path = cached_pointcloud.save_path
            cached_pointcloud.save_path = None

    def __getattr__(self, name):
        pointcloud = self.get_pointcloud()
        return getattr(pointcloud, name)

    def __iadd__(self, other):
        pointcloud = self.get_pointcloud()
        pointcloud += other
        self.set_pointcloud(pointcloud)
        return self

    def select_by_index(self, indices:list):
        pointcloud = self.get_pointcloud()
        pointcloud = pointcloud.select_by_index(indices)
        return pointcloud

    def voxel_down_sample(self, voxel_size:float):
        pointcloud = self.get_pointcloud()
        pointcloud = pointcloud.voxel_down_sample(voxel_size)
        return pointcloud

    def clear(self):
        if os.path.exists(self.save_path):
            os.remove(self.save_path)

class Cloud:
    def __init__(self, cloud_index:int, cloud_path:str=None, lidar_name:str=None, time:int=0, mod_list:list=None, lidar_points:np.ndarray=None):
        self.cloud_index:int = cloud_index # Index of the cloud
        self.cloud_path:str = cloud_path # Path to the cloud file
        self.lidar_name:str = lidar_name # Name of the lidar, e.g. 'lidar0', 'lidar1', 'lidar2'
        self.time:int = time # Time of the cloud
        self.mod:dict = None # Mod object
        self.pose:Pose = None # Pose object
        self.local_map:LocalMap = None # Local map object
        self.cached_cloud:CachedPointCloud = None # Cached cloud object
        # Check if the cloud path is provided
        if cloud_path or lidar_points is not None:
            # Load the cloud  if the cloud path is provided
            self.load_cloud(cloud_path, lidar_points)
        # Check if the mod list is provided
        if mod_list:
            # Get the mod object from the mod list
            self.get_mod(mod_list)

    '''Check if the cloud is empty'''
    def is_empty(self):
        # Return if the cloud is None or the number of points in the cloud is 0
        return self.cloud is None or len(self.cloud.points) == 0

    '''Get point cloud from the cached cloud'''
    def __getattr__(self, name):
        # Check if the name is 'cloud'
        if name == 'cloud':
            # Return the point cloud from the cached cloud
            return self.cached_cloud.get_pointcloud()
        # Otherwise, return the attribute from the object
        return super().__getattr__(name)

    '''Set point cloud to the cached cloud'''
    def __setattr__(self, name, value):
        # Check if the name is 'cloud'
        if name == 'cloud':
            # Set the point cloud to the cached cloud
            self.cached_cloud.set_pointcloud(value)
        else:
            # Set the attribute to the object
            super().__setattr__(name, value)

    '''Clear the point cloud buffer and the mod buffer'''
    def clear_point_cloud(self):
        # Clear the point cloud buffer
        self.cached_cloud.clear()
        # Set the point cloud to None
        self.cached_cloud = None

    '''Clear the local map buffer'''
    def clear_local_map(self):
        # Check if the local map is None
        if self.local_map is None:
            # Return if the local map is None
            return
        # Clear the local map
        self.local_map.clear_buffer()
        # Set the local map to None
        self.local_map = None

    '''Clear the point cloud, local map points and the local map buffer'''
    def clear(self):
        # Clear the point cloud
        self.clear_point_cloud()
        # Clear the local map
        self.clear_local_map()

    '''Remove the points in the mod 3d bounding box from the point cloud'''
    def remove_points_in_mod(self, extrinsic:Pose, immobile_tracks:set):
        '''You can use open3d.geometry.PointCloud.crop to crop the cloud points inside the 3D mod bounding box either.'''
        '''However, the crop function create a copy of the cloud points each time a mod bbox was processed, which may '''
        '''be slow for large point clouds. Therefore, we use the following method to remove the points in the mod from the cloud.'''
        # Check if the mod is None
        if self.mod is None:
            # Return if the mod is None
            return
        # Get the mod list from the mod object
        mod_list = self.mod["mod_list"]
        # Get the mod 3D objects from the mod list
        mod3d_dict_list = [mod['mod_3d'] for mod in mod_list if mod.get("mod_3d") is not None]
        # Add the ego mod 3D object to the mod 3D objects list
        mod3d_dict_list.append(Mod3D.get_ego_mod3d_dict())
        # Check if the mod 3D objects are empty
        if not mod3d_dict_list:
            # Return if the mod 3D objects are empty
            return
        # Create an empty set to store the invalid indices
        invalid_indices = set()
        # Get the points from the point cloud
        local_points = np.array(self.cloud.points)
        # Transform the points to the vehicle frame
        vehicle_points = extrinsic.inverse().transform_points(local_points)
        # Create a KDTree from the vehicle points
        kdtree = cKDTree(vehicle_points)
        # Iterate over the mod 3D objects
        for mod3d_dict in mod3d_dict_list:
            # # Get the velocity from the mod 3D object
            # vel_world_dict = mod3d_dict['velocity'].get('world_ekf')
            # # Get the velocity in the world frame
            # vel_world = np.asarray([vel_world_dict['x'], vel_world_dict['y'], vel_world_dict['z']])
            # # Get the square of the speed in the world frame
            # speed_world_square = np.sum(vel_world**2)
            # # Get the world EKF credible flag from the mod 3D object
            # world_ekf_credible = mod3d_dict['velocity'].get('world_ekf_credible')
            # # Check if the squared speed is less than 0.1 * 0.1 and the world EKF is credible
            # if world_ekf_credible and speed_world_square < 0.1**2:
            #     # Continue if the squared speed is less than 0.1 * 0.1
            #     continue
            # Create a Mod3D object from the mod 3D object
            mod_3d = Mod3D(mod3d_dict)
            # Check if the track ID of the mod 3D object is in the immobile tracks
            if mod_3d.track_id in immobile_tracks:
                # Continue if the track ID of the mod 3D object is in the immobile tracks
                continue
            # Get the indices of the points in the mod 3D bounding box
            inner_indices = mod_3d.get_mod_point_indices(vehicle_points, kdtree)
            # Update the invalid indices with the indices of the points in the mod 3D bounding box
            invalid_indices.update(inner_indices)
        # Remove the points in the mod 3D bounding box from the point cloud
        self.cloud = self.cloud.select_by_index(list(invalid_indices), invert=True)

    '''Load the point cloud from the cloud path'''
    def load_cloud(self, cloud_path:str=None, lidar_points:np.ndarray=None):
        # Check if the lidar points are provided
        if lidar_points is not None:
            # Get the points from the lidar points if the lidar points are provided
            points = lidar_points
        # Check if the cloud path is provided
        elif self.cloud_path:
            # Load the point cloud from the cloud path using Open3D
            points = np.load(self.cloud_path)
        # Otherwise, return
        else:
            # Return if both the cloud path and the lidar points are not provided
            return
        # Get the camera name from the image path if it is not provided
        if self.lidar_name is None:
            # Get the lidar name from the cloud path
            self.lidar_name = self.get_lidar_name_from_cloud_path(cloud_path)
        # Get the time from the image path if it is not provided
        if self.time == 0:
            # Get the time from the cloud path
            self.time = self.get_time_from_cloud_path(cloud_path)
        # Check if the lidar name is equal to 'lidar0'
        if self.lidar_name == 'lidar0':
            # Filter the points based on the lidar name
            points = points[points[:, 6] == 0]
        # Check if the lidar name is equal to 'lidar1'
        elif self.lidar_name == 'lidar1':
            # Filter the points based on the lidar name
            points = points[points[:, 6] == 1]
        # Check if the lidar name is equal to 'lidar2'
        elif self.lidar_name == 'lidar2':
            # Filter the points based on the lidar name
            points = points[points[:, 6] == 2]
        # Set the point cloud to the points
        cloud = o3d.geometry.PointCloud()
        # Set the points to the point cloud
        cloud.points = o3d.utility.Vector3dVector(points[:, :3])
        # Set the point cloud to the cached point cloud
        self.cached_cloud = CachedPointCloud(cloud, self.lidar_name, self.time)

    '''Get the lidar name from the cloud path'''
    def get_lidar_name_from_cloud_path(self, cloud_path:str)->str:
        # Get the lidar name from the cloud path
        lidar_name = cloud_path.split('/')[-2]
        # Return the lidar name
        return lidar_name

    '''Get the time from the cloud path'''
    def get_time_from_cloud_path(self, cloud_path:str)->int:
        # Get the time from the cloud path
        time = int(os.path.split(cloud_path)[-1].split('.')[0])
        # Return the time
        return time

    '''Get the mod object from the mod list'''
    def get_mod(self, mod_list: list):
        # Get the time from the cloud
        time = self.time
        # Get the index of the mod object with the nearest time to the cloud time from the mod list
        index = bisearch_list_nearest(mod_list, time, lambda x: x["time"])
        # Check if the index is -1
        if index == -1:
            # Return if the index is -1
            return
        # Get the mod object from the mod list
        self.mod = mod_list[index]

class LocalMap:
    def __init__(self, cloud_list:list, center_index:int, win_size:int, max_range:float=60, voxel_size:float=1.0, debug:bool=False):
        self.max_range:float = max_range # Maximum range limit of the lidar
        self.cloud_index:int = cloud_list[center_index].cloud_index # Index of anchor cloud
        self.lidar_name:str = cloud_list[center_index].lidar_name # Name of the lidar
        self.pose:Pose = cloud_list[center_index].pose # Pose of the anchor cloud
        self.cloud_mixture:CachedPointCloud = None # Point cloud of curr local map
        self.kdtree:cKDTree = None # KDTree for the local map
        self.voxel_size:float = voxel_size # Voxel size for downsampling
        self.debug:bool = debug # Debug flag
        # Generate local map cloud by combining neighbouring clouds in the window
        self.generate_local_map(cloud_list, center_index, win_size)
        # self.normal_dict:dict = {}

    def __del__(self):
        if self.kdtree is not None:
            del self.kdtree
        if self.cloud_mixture is not None:
            self.cloud_mixture.clear()
            del self.cloud_mixture

    def clear_buffer(self):
        self.cloud_mixture.clear()
        self.kdtree = None

    def get_kdtree(self, points:np.ndarray)->cKDTree:
        if self.kdtree is None:
            self.kdtree = cKDTree(points)
        return self.kdtree

    def get_kdtree_points(self):
        points = np.asarray(self.cloud_mixture.points)
        if self.kdtree is None:
            self.kdtree = cKDTree(points)
        return self.kdtree, points

    def get_down_sampled_point_cloud(self, voxel_size:float=None):
        if voxel_size is None:
            voxel_size = self.voxel_size * (1 if self.lidar_name == 'lidar2' else 1)
        down_pcd = self.cloud_mixture.voxel_down_sample(voxel_size=voxel_size)
        return down_pcd

    @staticmethod
    def get_local_map(cloud_list:list, center_index:int, win_size:int):
        if cloud_list[center_index].local_map is not None:
            local_map:LocalMap = cloud_list[center_index].local_map
            local_map.pose = cloud_list[center_index].pose
            return cloud_list[center_index].local_map
        local_map = LocalMap(cloud_list, center_index, win_size)
        cloud_list[center_index].local_map = local_map
        return local_map

    def remove_radius_outlier(self, nb_points:int, radius:float):
        points = np.asarray(self.cloud_mixture.points)
        distances = np.linalg.norm(points, axis=1)
        max_range = (1 if self.lidar_name == 'lidar2' else 1) * self.max_range
        valid_indices = np.where(distances < max_range)[0]
        points = points[valid_indices]
        distances = distances[valid_indices]
        search_radius = distances * 0.0025 + radius
        kd_tree = cKDTree(points)
        distss, _ = kd_tree.query(points, nb_points, distance_upper_bound=np.max(search_radius))
        valid_indices = [valid_indices[i] for i, dists in enumerate(distss) if dists[-1] < search_radius[i]]
        down_pcd = self.cloud_mixture.select_by_index(valid_indices)
        self.cloud_mixture.set_pointcloud(down_pcd)

    def filter_local_map(self):
        down_pcd = self.cloud_mixture.voxel_down_sample(voxel_size=0.075)
        self.cloud_mixture.set_pointcloud(down_pcd)
        self.remove_radius_outlier(3, 0.25)

    def generate_local_map(self, cloud_list:list, center_index:int, win_size:int):
        cloud:Cloud = cloud_list[center_index]
        ref_cloud_pose = cloud.pose
        start_index = max(0, center_index-win_size//2)
        end_index = min(len(cloud_list)-1, center_index+win_size//2)
        clouds:list[Cloud] = cloud_list[start_index:end_index]
        if self.cloud_mixture is None:
            self.cloud_mixture = CachedPointCloud()
        for cloud in clouds:
            curr_cloud_pose = cloud.pose
            transform_curr_to_ref = ref_cloud_pose.inverse().multiply(curr_cloud_pose)
            cloud_copy = o3d.geometry.PointCloud(cloud.cloud)
            cloud_copy.transform(transform_curr_to_ref.get_transform_matrix())
            self.cloud_mixture += cloud_copy
        self.filter_local_map()
        if self.debug:
            self.save_cloud_mixture(f"local_map_{center_index}.ply")

    def save_cloud_mixture(self, filename:str):
        save_dir = get_output_dir("pcd")
        save_path = os.path.join(save_dir, filename)
        print(f"Saving local map to {save_path}")
        if self.cloud_mixture is not None and len(self.cloud_mixture.points) > 0:
            o3d.io.write_point_cloud(save_path, self.cloud_mixture.get_pointcloud(), compressed=True)
        else:
            points = np.asarray(self.cloud_mixture.points)
            save_points(points, save_path)

    def get_points(self):
        return np.asarray(self.cloud_mixture.points)

    def get_point(self, points:np.ndarray, index:int):
        return points[index]

    def calc_normal(self, points:np.ndarray, index:int, max_nn:int=50, min_nn:int=5):
        point = points[index]
        # key = point_to_key_nb(point)
        # if key in self.normal_dict:
        #     rets = self.normal_dict[key]
        #     return rets
        kdtree = self.get_kdtree(points)
        distance = np.linalg.norm(point)
        max_radius = (1.2 if self.lidar_name == 'lidar2' else 1) * 0.25
        search_radius = distance * 0.0025 + max_radius
        _, indices = kdtree.query(point, k=max_nn, distance_upper_bound=search_radius)
        if indices[min_nn] == kdtree.n:
            return (None, 0, point)  # No valid neighbors found
        indices = indices[indices != kdtree.n]
        points = points[indices]
        results = calc_normal_nb(points)
        mean_point = np.mean(points, axis=0)
        rets = (results[:3], int(results[3]), mean_point)
        # self.normal_dict[key] = rets
        return rets

    def get_mapsurfel(self, points:np.ndarray, index:int):
        point = points[index]
        normal, type, mean_point = self.calc_normal(points, index)
        surfel = MapSurfel(self.cloud_index, mean_point, normal, type)
        return surfel

    def get_mappoint(self, point:np.ndarray):
        return MapPoint(self.cloud_index, point)
