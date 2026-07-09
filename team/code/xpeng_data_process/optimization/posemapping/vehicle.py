import json
import os
from copy import deepcopy
from itertools import pairwise
from pathlib import Path
from typing import Dict
import cv2
import matplotlib.cm as cm
import numpy as np

from .point_cloud import Cloud
from .pose import Pose
from .sensor import BaseCamera, Camera, CachedImage, CrossMatch, FeatureMatch, Image, ImageKeyPoint, Landmark, Lidar, PointMatch, Visibility
from .utils import get_camera_pairs, get_lidar_pairs, is_major_movement, Log

class Vehicle:
    def __init__(self, clip_path:str, camera_names=None, repack_names=None, logger=Log()):
        self.clip_path = clip_path
        self.scale = 0.5 # since dataportal image is resized to 1/2
        self.image_source = "images_origin"  #  or "images"
        self.camera_shape:dict = {}

        self.calib_data = json.load(open(os.path.join(self.clip_path, "calib.json")))

        self.logger = logger
        self.time_delay:float = 0.0 # Time delay from visual to lidar
        self.lidar_poses:list[Pose] = [] # List of lidar poses
        self.pose_list:list[Pose] = [] # List of pose objects
        self.calib_dict:dict = {} # Calibration dictionary
        self.camera_list:list[Camera] = [] # List of camera objects
        self.lidar_list:list[Lidar] = [] # List of lidar objects
        self.image_list:list[Image] = [] # List of image objects
        self.visibility_list:list[Visibility] = [] # List of visibility objects
        self.visual_match_list:list[FeatureMatch] = [] # List of visual match objects
        self.point_match_list:list[PointMatch] = [] # List of point match objects
        self.cross_match_list:list[CrossMatch] = [] # List of cross match objects
        self.loop_match_list:list[PointMatch] = [] # List of loop match objects
        self.landmark_list:list[Landmark] = [] # List of landmark objects
        self.mask_folder:str = None # Mask directory
        self.camera_names:list[str] = camera_names # List of camera names
        self.repack_names:list[str] = repack_names # List of lidar names
        self.lidar_names:list[str] = [] # List of lidar names
        self.mods_list:list[dict] = [] # List of mod objects
        self.cloud_list:list[Cloud] = [] # List of lidar point cloud objects
        self.immobile_tracks:set = set() # Set of immobile objects
        self.output_dir:str = None # Output directory
        self.pose_scale:float = 1.0 # Pose scale
        self.visual_scale:float = 1.0 # Visual scale
        self.lidar_scale:float = 1.0 # Lidar scale
        self.symm_scale:float = 1.0 # Symmetry scale
        self.visual_rotation:float = 0.0 # Visual rotation
        self.lidar_rotation:float = 0.0 # Lidar rotation
        self.pose_updated:bool = False # Pose updated flag

        self.load_cameras()
        self.load_pose_data()
        if self.camera_list:
            self.fetch_images()
        # Transform the pose list by the inverse of the first main pose
        if self.pose_list:
            self.transform_poses()

    '''Cluster the images by time'''
    def cluster_images_by_time(self, time_diff=1e7)->dict:
        clusters = {}
        for image in self.image_list:
            # Check if the time is not in the clusters dictionary
            if image.time not in clusters:
                # Add the time to the clusters dictionary
                clusters[image.time] = []
            # Append the image to the cluster
            clusters[image.time].append(image)
        # Return the clusters
        return clusters

    '''Count the matched keypoints'''
    def count_matched_keypoints(self):
        # Create a set to store the matched keypoints
        matched_img_kpts = set()
        # Add the matched query keypoints to the set
        matched_img_kpts.update([match.query_img_kpt for match in self.visual_match_list])
        # Add the matched train keypoints to the set
        matched_img_kpts.update([match.train_img_kpt for match in self.visual_match_list])
        # # Iterate over the matches
        # for match in self.visual_match_list:
        #     # Get the query image keypoint
        #     query_img_kpt = match.query_img_kpt
        #     # Get the train image keypoint
        #     train_img_kpt = match.train_img_kpt
        #     # Check if the query image keypoint is not in the matched keypoints
        #     if query_img_kpt not in matched_img_kpts:
        #         # Add the query image keypoint to the matched keypoints
        #         matched_img_kpts.add(query_img_kpt)
        #     # Check if the train image keypoint is not in the matched keypoints
        #     if train_img_kpt not in matched_img_kpts:
        #         # Add the train image keypoint to the matched keypoints
        #         matched_img_kpts.add(train_img_kpt)
        # Return the matched keypoints
        return matched_img_kpts

    '''Fetch all images in the subrun data object'''
    def fetch_images(self):
        # Get the major times
        major_times = self.get_major_times()

        for cam_name in self.camera_names:
            # Get the camera by name
            camera = self.get_camera_by_name(cam_name)

            image_list = [
                i for i in os.listdir(os.path.join(self.clip_path, self.image_source, cam_name)) if ".png" in i
            ]
            for i, img_name in enumerate(image_list):
                time = int(img_name.split('.')[0])
                if time not in major_times:
                    continue
                image_path = os.path.join(self.clip_path, self.image_source, cam_name, img_name)
                image = Image(len(self.image_list), camera, image_path, time)
                if cam_name not in self.camera_shape:
                    img = cv2.imread(image_path, -1)
                    self.camera_shape[cam_name] = img.shape[:2]
                image.shape = self.camera_shape[cam_name]

                mod_path = os.path.join(self.clip_path, "masks_obj", cam_name, img_name)
                # mod_mask = cv2.imread(mod_path, -1) if os.path.exists(mod_path) else None

                # Set the mask name
                mask_name = f"{cam_name}_mask"
                image.cached_mask = CachedImage(mod_path, None, mask_name, time)
                self.image_list.append(image)
                # For debugging
                # if len(self.image_list) == 2:
                #     break
        self.logger.info(f"Loaded images: {len(self.image_list)}")

    '''Filter out cluster with less than 2 images'''
    @staticmethod
    def filter_clusters(clusters:dict):
        # Create a dictionary to store the filtered clusters
        filtered_clusters = {}
        # Iterate over the clusters
        for time, cluster in clusters.items():
            # Check if the length of the cluster is less than 2
            if len(cluster) < 2:
                # Skip the cluster if the length of the cluster is less than 2
                continue
            # Add the cluster to the filtered clusters dictionary
            filtered_clusters[time] = cluster
        # Return the filtered clusters
        return filtered_clusters

    '''Get the camera by name'''
    def get_camera_by_name(self, camera_name:str)->Camera:
        # Iterate over the camera list
        for i in range(len(self.camera_list)):
            # Get the camera object by index
            camera = self.camera_list[i]
            # Check if the camera name matches the input camera name
            if camera.camera_name == camera_name:
                # Return the camera object if the camera name matches the input camera name
                return camera
        # Return None if the camera object is not found
        return None

    '''Get the image times by camera name'''
    def get_camera_times(self, camera_name:str):
        # Get the image files by camera name
        images:list[Image] = self.get_images_by_camera_name(camera_name)
        # Create a list of tuples containing the image time
        image_times = [image.time for image in images]
        # Sort the image times
        image_times.sort()
        # Return the image times
        return image_times

    '''Get the cloud pose by interpolating the vehicle pose at the cloud time and transforming it by the lidar extrinsic matrix'''
    def get_cloud_pose(self, cloud:Cloud)->Pose:
        # Check if the cloud pose is not None
        if cloud.pose is not None:
            # Return the cloud pose if it is not None
            return cloud.pose
        # Get the time offset by multiplying the time delay by 1e9
        time_offset = int(self.time_delay * 1e9)
        # Get the vehicle pose at the cloud time by interpolation
        vehicle_pose = self.get_pose_by_time(cloud.time + time_offset)
        # Get the lidar extrinsic matrix
        transform_vehicle2lidar = self.get_lidar_by_name(cloud.lidar_name).extrinsic
        # Get the cloud pose by transforming the vehicle pose
        transform_lidar2vehicle = transform_vehicle2lidar.inverse()
        # Multiply the vehicle pose by the inverse of the transform matrix
        cloud_pose = vehicle_pose.multiply(transform_lidar2vehicle)
        # Set the cloud pose as the cloud pose newly created
        cloud.pose = cloud_pose
        # Return the cloud pose
        return cloud_pose

    '''Get all clouds with the given lidar name'''
    def get_clouds_by_lidar_name(self, lidar_name:str)->list:
        # List to store the clouds
        clouds:list[Cloud] = []
        # Loop through each cloud in the cloud list
        for cloud in self.cloud_list:
            # Check if the lidar name matches the input lidar name
            if cloud.lidar_name == lidar_name:
                # Get the cloud pose by interpolating the vehicle pose at the cloud time
                self.get_cloud_pose(cloud)
                # Append the cloud object to the list of clouds
                clouds.append(cloud)
        # Return the clouds
        return clouds

    '''Get the image by index'''
    def get_image_by_index(self, image_index:int)->Image:
        # Get the image object by index
        return self.image_list[image_index]

    '''Get the image camera by name'''
    def get_image_camera(self, image:Image)->Camera:
        # Get the camera by name from the image and return it
        return self.get_camera_by_name(image.camera_name)

    '''Get the image pose by interpolating the vehicle pose at the image time and transforming it by the camera extrinsic matrix'''
    def get_image_pose(self, image:Image)->Pose:
        # Check if the image pose is not None
        if image.pose is not None:
            # Return the image pose if it is not None
            return image.pose
        # Get the vehicle pose at the image time by interpolation
        vehicle_pose = self.get_pose_by_time(image.time)
        # Get the camera extrinsic matrix
        transform_image_vehicle = self.get_camera_by_name(image.camera_name).extrinsic
        # Get the image pose by transforming the vehicle pose
        transform_vehicle_image = transform_image_vehicle.inverse()
        # Set the image pose as the vehicle pose multiplied by the inverse of the transform matrix
        image.pose = vehicle_pose.multiply(transform_vehicle_image)
        # Return the image pose
        return image.pose

    '''Get the image pose inverse by interpolating the vehicle pose at the image time and transforming it by the camera extrinsic matrix inverse'''
    def get_image_pose_inv(self, image:Image)->Pose:
        # Check if the image pose inverse is not None
        if image.pose_inv is not None:
            # Return the image pose inverse if it is not None
            return image.pose_inv
        # Otherwise
        else:
            # Get the image pose by interpolating the vehicle pose at the image time
            image_pose = self.get_image_pose(image)
            # Set the image pose inverse as the inverse of the image pose
            image.pose_inv = image_pose.inverse()
            # Return the image pose inverse
            return image.pose_inv

    '''Get all images with the given camera name'''
    def get_images_by_camera_name(self, camera_name:str)->list:
        # Get the images by camera name
        images = [image for image in self.image_list if image.camera_name == camera_name]
        return images

    '''Get the lidar by name'''
    def get_lidar_by_name(self, lidar_name:str)->Lidar:
        # Iterate over the lidar list
        for i in range(len(self.lidar_list)):
            # Get the lidar object by index
            lidar = self.lidar_list[i]
            # Check if the lidar name matches the input lidar name
            if lidar.lidar_name == lidar_name:
                # Return the lidar object if the lidar name matches the input lidar name
                return lidar
        # Return None if the lidar object is not found
        return None

    '''Get the main camera name'''
    def get_main_camera_name(self):
        # Check if 'cam2' is in the camera names
        if 'cam2' in self.camera_names:
            # Return 'cam2' if it is in the camera names
            return 'cam2'
        # otherwise,
        else:
            # Return the first camera name in the camera names
            return self.camera_names[0]

    '''Get the main lidar name'''
    def get_main_lidar_name(self):
        # Check if 'lidar0' is in the lidar names
        if 'lidar0' in self.lidar_names:
            # Return 'lidar0' if it is in the lidar names
            return 'lidar0'
        # Check if 'lidar2' is in the lidar names
        elif 'lidar2' in self.lidar_names:
            # Return 'lidar2' if it is in the lidar names
            return 'lidar2'
        # otherwise,
        else:
            # Return the first lidar name in the lidar names
            return self.lidar_names[0]

    '''Get the main sensor name'''
    def get_main_sensor_name(self):
        # Check if the camera names list is not empty
        if self.camera_names:
            # Return the main camera name
            return self.get_main_camera_name()
        # Check if the lidar names list is not empty
        elif self.lidar_names:
            # Return the main lidar name if the camera names list is empty
            return self.get_main_lidar_name()
        else:
            # Return None if both the camera names and lidar names lists are empty
            return None


    '''Get all times with major movements'''
    def get_major_times(self):
        # List to store the major times
        major_times = []
        # Initialize the previous pose
        prev_pose:Pose = None
        # Get the main times
        main_times = self.get_orig_main_times()
        # Get the sum of the trip from the poses
        sum_trip = self.get_trip_from_poses()
        # Get the major movement threshold
        major_threshold = max(1.0, sum_trip / 200.0)
        # Iterate over each file in the list
        for image_time in main_times:
            # Check if the previous pose is None
            if len(major_times) == 0:
                # Append the time to the list
                major_times.append(image_time)
                # Get the pose at the image time
                prev_pose = self.get_pose_by_time(image_time)
                # Set the previous pose as the last pose
                last_pose = prev_pose
            else:
                # Get the current pose at the image time
                curr_pose = self.get_pose_by_time(image_time)
                # Get the delta pose by multiplying the inverse of the previous pose by the current pose
                delta_pose = prev_pose.inverse().multiply(curr_pose)
                # Get the inter-frame pose by multiplying the inverse of the last pose by the current pose
                inter_pose = last_pose.inverse().multiply(curr_pose)
                # Check if the movement is major
                if is_major_movement(delta_pose, inter_pose, major_threshold):
                    # Append the time to the list
                    major_times.append(image_time)
                    # Set the previous pose as the current pose
                    prev_pose = curr_pose
                # Set the last pose as the current pose
                last_pose = curr_pose
        # Check if the major times list is empty or has only one element
        if len(major_times) <= 1:
            # Select 10 items evenly form the main times if the major times list is empty or has only one element
            major_times = [main_times[i] for i in range(0, len(main_times), len(main_times) // 10)]
        # Make sure the last time is included to avoid interpolation erro when the vehicle is not moving at the end
        if major_times[-1] != main_times[-1]:
            major_times.append(main_times[-1])
        # Return the major times
        return major_times

    '''Get the original main times'''
    def get_orig_main_times(self):
        # # Get the main camera name from the first camera in the camera list
        # main_sensor_name = self.get_main_sensor_name()
        # # Get the main times
        # main_times = self.get_orig_sensor_times(main_sensor_name)
        # # Return the main times
        # return main_times
        main_times = [int(k) for k in self.calib_data["local_pose"].keys()]
        return list(sorted(main_times))

    '''Get the pose at query time by interpolation'''
    def get_pose_by_time(self, time:int)->Pose:
        # Get the pose at query time by interpolation
        return Pose.interpolate(self.pose_list, time)

    '''Get relative rotation from the extrinsics of the cameras'''
    def get_rotation_from_camera_extrinsics(self, ref_camera_list)->float:
        # Check if the reference camera list is None
        if ref_camera_list is None:
            # Return 1 if the reference camera list is None
            return 1
        # Get the current camera list
        curr_camera_list = self.camera_list

        # List to store the rotations
        camera_rotations = {}
        # Iterate over the camera pairs
        for ref_camera in ref_camera_list:
            # Get the current camera
            curr_camera = [camera for camera in curr_camera_list if camera.camera_name == ref_camera.camera_name][0]
            # Get the original and current transforms
            ref_transform = ref_camera.extrinsic
            curr_transform = curr_camera.extrinsic
            # Add the translation norm to the odometry
            rotation = curr_transform.R @ ref_transform.R.T
            # Get the cosine value of the rotation angle
            cos_value = (np.trace(rotation) - 1) / 2
            # Truncate the cos value to be in the range of -1 to 1
            cos_value = np.clip(cos_value, -1, 1)
            # Get the rotation angle
            angle = np.arccos(cos_value)
            # Get the rotation angle in degrees
            degree = np.degrees(angle)
            # Append the rotation angle to the list
            camera_rotations[ref_camera.camera_name] = degree
        # Print all camera rotations
        self.logger.info(f"Camera Rotations: {camera_rotations}")
        # Get the maximum rotation angle
        max_rotation = max(camera_rotations.values())
        # Set the visual rotation as the maximum rotation angle
        self.visual_rotation = max_rotation
        # Return the maximum rotation angle
        return max_rotation

    def get_rotation_from_lidar_extrinsics(self, ref_lidar_list:list)->float:
        # Check if the reference lidar list is None
        if ref_lidar_list is None:
            return 1
        # Get the current lidar list
        curr_lidar_list:list[Lidar] = self.lidar_list
        # List to store the rotations
        lidar_rotations:dict = {}
        # Sort the lidar list by lidar name
        ref_lidar_list.sort(key=lambda x: x.lidar_name)
        curr_lidar_list.sort(key=lambda x: x.lidar_name)
        # Iterate over the lidar pairs
        for ref_lidar in ref_lidar_list:
            # Get the current lidar
            curr_lidar:Lidar = [lidar for lidar in curr_lidar_list if lidar.lidar_name == ref_lidar.lidar_name][0]
            # Get the original and current transforms
            ref_transform:Pose = ref_lidar.extrinsic
            curr_transform:Pose = curr_lidar.extrinsic
            # Add the translation norm to the odometry
            rotation:np.ndarray = curr_transform.R @ ref_transform.R.T
            # Calculate the cos value and clip to valid range
            cos_value = np.clip((np.trace(rotation) - 1) / 2, -1.0, 1.0)
            # Get the rotation angle
            angle:float = np.arccos(cos_value)
            # Get the rotation angle in degrees
            degree:float = np.degrees(angle)
            # Append the rotation angle to the list
            lidar_rotations[ref_lidar.lidar_name] = degree
        # Print all lidar rotations
        self.logger.info(f"Lidar Rotations: {lidar_rotations}")
        # Get the maximum rotation angle
        max_rotation:float = max(lidar_rotations.values())
        # Set the lidar rotation as the maximum rotation angle
        self.lidar_rotation = max_rotation
        # Return the maximum rotation angle
        return max_rotation

    '''Get scale factor from the extrinsics of the cameras'''
    def get_scale_from_camera_extrinsics(self, ref_camera_list)->float:
        # Check if the reference camera list is None
        if ref_camera_list is None:
            return 1
        # Get the current camera list
        curr_camera_list = self.camera_list
        # List to store the camera pairs
        camera_pairs = get_camera_pairs(self.camera_names)
        # Initialize the original and current odometry
        ref_extrinsics = []
        curr_extrinsics = []
        # Iterate over the camera pairs
        for camera_pair in camera_pairs:
            # Get the original and current cameras
            ref_camera0 = [camera for camera in ref_camera_list if camera.camera_name == camera_pair[0]][0]
            ref_camera1 = [camera for camera in ref_camera_list if camera.camera_name == camera_pair[1]][0]
            curr_camera0 = [camera for camera in curr_camera_list if camera.camera_name == camera_pair[0]][0]
            curr_camera1 = [camera for camera in curr_camera_list if camera.camera_name == camera_pair[1]][0]
            # Get the original and current transforms
            ref_transform = ref_camera0.extrinsic.multiply(ref_camera1.extrinsic.inverse())
            curr_transform = curr_camera0.extrinsic.multiply(curr_camera1.extrinsic.inverse())
            # Add the translation norm to the odometry
            ref_extrinsics.append(np.linalg.norm(ref_transform.t))
            curr_extrinsics.append(np.linalg.norm(curr_transform.t))
        # Print the original and current extrinsics
        self.logger.info(f"Updated Extrinsics: {ref_extrinsics}")
        self.logger.info(f"Original Extrinsics: {curr_extrinsics}")
        # Calculate the scale factor
        scale = 1.0 if sum(ref_extrinsics) == 0 else sum(curr_extrinsics) / sum(ref_extrinsics)
        # Set the visual scale as the scale factor
        self.visual_scale = scale
        # Return the scale factor
        return scale

    '''Get scale factor from the extrinsics of the lidars'''
    def get_scale_from_lidar_extrinsics(self, ref_lidar_list:list, ref_camera_list:list)->float:
        # Check if the reference lidar list is None
        if ref_lidar_list is None:
            return 1
        # Get the current lidar list
        curr_lidar_list:list[Lidar] = self.lidar_list
        # List to store the lidar pairs
        lidar_pairs:list[tuple] = get_lidar_pairs(self.lidar_names)
        # Initialize the original and current odometry
        ref_extrinsics:list[float] = []
        curr_extrinsics:list[float] = []
        # Iterate over the lidar pairs
        for lidar_pair in lidar_pairs:
            # Get the original and current lidars
            ref_lidar0:Lidar = [lidar for lidar in ref_lidar_list if lidar.lidar_name == lidar_pair[0]][0]
            ref_lidar1:Lidar = [lidar for lidar in ref_lidar_list if lidar.lidar_name == lidar_pair[1]][0]
            curr_lidar0:Lidar = [lidar for lidar in curr_lidar_list if lidar.lidar_name == lidar_pair[0]][0]
            curr_lidar1:Lidar = [lidar for lidar in curr_lidar_list if lidar.lidar_name == lidar_pair[1]][0]
            # Get the original and current transforms
            ref_transform:Pose = ref_lidar0.extrinsic.multiply(ref_lidar1.extrinsic.inverse())
            curr_transform:Pose = curr_lidar0.extrinsic.multiply(curr_lidar1.extrinsic.inverse())
            # Add the translation norm to the odometry
            ref_extrinsics.append(np.linalg.norm(ref_transform.t))
            curr_extrinsics.append(np.linalg.norm(curr_transform.t))
        # Check if the image list is not empty
        if self.image_list:
            # Get the main camera name
            main_camera_name = self.get_main_camera_name()
            # Get the curr main camera from the camera list
            curr_main_camera:Camera = self.get_camera_by_name(main_camera_name)
            # Get the ref main camera from the camera list
            ref_main_camera:Camera = [camera for camera in ref_camera_list if camera.camera_name == main_camera_name][0]
            # Sort the lidar list by lidar name
            ref_lidar_list.sort(key=lambda x: x.lidar_name)
            curr_lidar_list.sort(key=lambda x: x.lidar_name)
            # Iterate over the lidar list
            for ref_lidar, curr_lidar in zip(ref_lidar_list, curr_lidar_list):
                # Get the original and current transforms
                ref_transform = ref_main_camera.extrinsic.multiply(ref_lidar.extrinsic.inverse())
                curr_transform = curr_main_camera.extrinsic.multiply(curr_lidar.extrinsic.inverse())
                # Add the translation norm to the odometry
                ref_extrinsics.append(np.linalg.norm(ref_transform.t))
                curr_extrinsics.append(np.linalg.norm(curr_transform.t))
        # Print the original and current extrinsics
        self.logger.info(f"Updated Extrinsics: {ref_extrinsics}")
        self.logger.info(f"Original Extrinsics: {curr_extrinsics}")
        # Calculate the scale factor
        scale = 1.0 if sum(ref_extrinsics) == 0 else sum(curr_extrinsics) / sum(ref_extrinsics)
        # Set the lidar scale as the scale factor
        self.lidar_scale = scale
        # Return the scale factor
        return scale

    '''Get scale factor from the poses of the vehicle'''
    def get_scale_from_poses(self, ref_pose_list)->float:
        # Check if the pose list is the same length as the reference pose list
        if len(self.pose_list) == len(ref_pose_list):
            # Set the current pose list as the pose list if it is the same length as the reference pose list
            curr_pose_list = self.pose_list
        # Otherwise, interpolate the current pose list by the times of the reference pose list
        else:
            # Get the times of the reference pose list
            times = [pose.time for pose in ref_pose_list]
            # Interpolate the current pose list by the times of the reference pose list
            curr_pose_list = Pose.interpolate_poses(self.pose_list, times)
        # Initialize the original and current odometry
        ref_odometry = []
        curr_odometry = []
        # Iterate over the pose pairs
        for i in range(1, len(curr_pose_list)):
            # Get the original and current poses
            ref_pose0 = ref_pose_list[i-1]
            ref_pose1 = ref_pose_list[i]
            curr_pose0 = curr_pose_list[i-1]
            curr_pose1 = curr_pose_list[i]
            # Get the original and current odometry
            ref_odometry.append(np.linalg.norm(ref_pose1.t - ref_pose0.t))
            curr_odometry.append(np.linalg.norm(curr_pose1.t - curr_pose0.t))
        # Print the original and current odometry
        self.logger.info(f"Updated Odometry: {ref_odometry[0::50]}")
        self.logger.info(f"Original Odometry: {curr_odometry[0::50]}")
        # Calculate the scale factor
        scale = 1.0 if sum(ref_odometry) < 5 else sum(curr_odometry) / sum(ref_odometry)
        # Set the pose scale as the scale factor
        self.pose_scale = scale
        # Return the scale factor
        return scale

    '''Get scale factor from the extrinsics of the cameras'''
    def get_scale_from_symmetry_extrinsics(self, ref_camera_list)->float:
        # Check if the reference camera list is None
        if ref_camera_list is None:
            # Return 1 if the reference camera list is None
            return 1
        # Get the current camera list
        curr_camera_list = self.camera_list
        # List to store the camera pairs
        camera_pairs = get_camera_pairs(self.camera_names)
        # Initialize the original and current odometry
        ref_extrinsics = []
        curr_extrinsics = []
        # Iterate over the camera pairs
        for camera_pair in camera_pairs:
            # Get the original and current cameras
            ref_camera0 = [camera for camera in ref_camera_list if camera.camera_name == camera_pair[0]][0]
            ref_camera1 = [camera for camera in ref_camera_list if camera.camera_name == camera_pair[1]][0]
            curr_camera0 = [camera for camera in curr_camera_list if camera.camera_name == camera_pair[0]][0]
            curr_camera1 = [camera for camera in curr_camera_list if camera.camera_name == camera_pair[1]][0]
            # Get the original and current transforms
            ref_transform = ref_camera0.extrinsic.multiply(ref_camera1.extrinsic.inverse())
            curr_transform = curr_camera0.extrinsic.multiply(curr_camera1.extrinsic.inverse())
            # Add the translation norm to the odometry
            ref_extrinsics.append(np.linalg.norm(ref_transform.t))
            curr_extrinsics.append(np.linalg.norm(curr_transform.t))
        # Calculate the symmetry of the scale factor
        symm_scales = [(ref_extrinsics[i]+1)/(ref_extrinsics[-2-i]+1) for i in [0, 1, 2]]
        # Get the symmetry scale with the maximum divergence from 1
        symm_scale = max(symm_scales, key=lambda x: abs(x-1))
        # Print the symmetry scales and the symmetry scale
        self.logger.info(f"Symmetry Scales: {symm_scales}, Symmetry Scale: {symm_scale}")
        # Set the symmetry scale as the scale factor
        self.symm_scale = symm_scale
        # Return the scale factor
        return symm_scale

    '''Get sensor times by sensor name'''
    def get_sensor_times(self, sensor_name:str):
        # Check if the sensor name is in the camera names
        if self.camera_names and sensor_name in self.camera_names:
            # Return the camera times by sensor name
            return self.get_camera_times(sensor_name)
        # Check if the sensor name is in the lidar names
        elif self.lidar_names and sensor_name in self.lidar_names:
            # Return the lidar times by sensor name
            return self.get_lidar_times(sensor_name)
        # Otherwise
        else:
            # Return None if the sensor name is not in the camera names or lidar names
            return None

    '''Get the subrun ID from the subrun directory or subrun data'''
    def get_subrun_id(self):
        # # Check if the subrun directory is not None
        # if self.subrun_dir.valid:
        #     # Return the subrun ID from the subrun directory
        #     return self.subrun_dir.get_subrun_id()
        # # Check if the subrun data is not None
        # elif self.subrun_data.valid:
        #     # Return the subrun ID from the subrun data
        #     return self.subrun_data.get_subrun_id()
        # # Otherwise
        # else:
        #     # Return None if both the subrun directory and subrun data are None
        #     return None
        return os.path.basename(self.clip_path)

    '''Get total trip from the poses of the vehicle'''
    def get_trip_from_poses(self)->float:
        # Initialize the sum trip as 0
        sum_trip = 0
        # Iterate over the pose list
        for i in range(1, len(self.pose_list)):
            # Get the poses at the current and previous indices
            pose0 = self.pose_list[i-1]
            pose1 = self.pose_list[i]
            # Add the translation norm to the sum trip
            sum_trip += np.linalg.norm(pose1.t - pose0.t)
        # Return the sum trip
        return sum_trip

    '''Get virtual camera by scaling the original camera intrinsic matrix and setting the width and height of the virtual camera to the image width and height'''
    def get_virtual_camera(self, image:Image)->Camera:
        # Get the original camera by name
        cam = self.get_camera_by_name(image.camera_name)
        # Get the scale by dividing the image width by the original camera width
        scale = image.shape[1] / cam.width
        # Get the scaled intrinsic matrix
        scaled_intrinsic = cam.getscaled_intrinsic(scale)
        # Create a new virtual camera object
        virtual_camera = BaseCamera(cam.camera_name, scaled_intrinsic, cam.dist, cam.extrinsic, image.shape[1], image.shape[0], cam.hfov, cam.vfov)
        # Return the virtual camera
        return virtual_camera

    '''Interpolate the lidar poses by the original lidar times'''
    def interpolate_lidar_poses(self):
        # Calculate the time offset
        time_offset = int(self.time_delay * 1e9)
        # Get the original main times
        lidar_times = self.get_orig_lidar_times()
        # Interpolate the main poses by the original main times
        self.lidar_poses = Pose.interpolate_poses(self.pose_list, lidar_times, time_offset)

    '''Interpolate the main poses by the original main times'''
    def interpolate_main_poses(self):
        # Get the original main times
        main_times = self.get_orig_main_times()
        # Interpolate the main poses by the original main times
        new_pose_list = Pose.interpolate_poses(self.pose_list, main_times)
        # Update the pose list with the new pose list
        self.update_pose_list(new_pose_list)

    '''Load the cameras from the calibration data'''
    def load_cameras(self):
        # Check if the camera names are not provided
        if self.camera_names is None:
            return
        # Get the camera calibration data
        self.calib_dict = {camera_name: self.calib_data[camera_name] for camera_name in self.camera_names
                           if camera_name in self.calib_data}
        camera_calib_data = self.calib_dict
        # Iterate over the camera calibration data
        for camera_name, camera_dict in camera_calib_data.items():
            # Check if the camera name is not 'cam2', 'cam3', 'cam4', 'cam5', 'cam6', or 'cam7'
            if camera_name not in self.camera_names:
                # Continue if the camera name is not 'cam2', 'cam3', 'cam4', 'cam5', 'cam6', or 'cam7'
                continue
            # Load camera mask
            mask = self.load_mask(camera_name)
            # Create a new camera object
            camera_dict['intrinsic']['cx'] = float(camera_dict['intrinsic']['cx']) / self.scale
            camera_dict['intrinsic']['cy'] = float(camera_dict['intrinsic']['cy']) / self.scale
            camera_dict['intrinsic']['focal_length'] = float(camera_dict['intrinsic']['focal_length']) * 4.2 / 1000 / self.scale
            camera = Camera(camera_name, camera_dict, mask)
            # Append the camera object to the camera list
            self.camera_list.append(camera)
            # self.logger.info(f"camera: {camera_name}, intrinsic: {camera.intrinsic}, extrinsic: {camera.extrinsic}, shape: {camera.height}x{camera.width}, dist: {camera.dist}")
        self.logger.info(f"Loaded {len(self.camera_list)} cameras {self.camera_names}")

    '''Load the camera mask from the mask directory using the camera name'''
    def load_mask(self, camera_name:str)->np.ndarray:
        # Get the directory of mask images
        mask_dir = os.path.join(os.path.dirname(__file__), "mask")
        if not os.path.exists(mask_dir):
            return None
        # Get the mask path
        mask_path = os.path.join(mask_dir, f"{camera_name}.png")
        # if not os.path.exists(mask_path):
        #     mask_path = os.path.join(mask_dir, f"{camera_name}.jpg")
        # Load the mask using OpenCV
        mask = cv2.imread(mask_path, cv2.IMREAD_ANYCOLOR)
        # Check if the mask image has 3 channels
        if mask.ndim == 3:
            # Convert the mask image to grayscale if it has 3 channels
            mask = cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)
        # half_mask = cv2.resize(mask, (0, 0), fx=0.5, fy=0.5)
        # cv2.imshow('mask', half_mask)
        # cv2.waitKey(0)
        # Set the edges of the mask to 0
        margin = 4
        mask[:margin, :] = 0
        mask[-margin:, :] = 0
        mask[:, :margin] = 0
        mask[:, -margin:] = 0
        # Return the camera mask
        return mask

    '''Load the pose data from the subrun data object'''
    def load_pose_data(self)->list:
        # Get the local pose data from calib.json
        self.pose_list = [Pose(R=np.array(pose_list)[:3, :3], t=np.array(pose_list)[:3, 3], time=int(timestampe))
                          for timestampe, pose_list in self.calib_data["local_pose"].items()]
        self.logger.info(f"Loaded {len(self.pose_list)} poses")

    '''Pack the remaining keypoints for each image'''
    def pack_images_keypoints(self, matched_img_kpts:dict)->dict:
        # Create a dictionary to store the image keypoints
        img_kpt_map = {}
        # Iterate over the images
        for image in self.image_list:
            # Get the image index
            image_index = image.image_index
            # Get the selected indices by filtering the matched keypoints
            selected_indices = [i for i in range(len(image.keypoints)) if ImageKeyPoint(image_index, i) in matched_img_kpts]
            # Get the new keypoints by selecting the keypoints with the selected indices
            new_keypoints = [image.keypoints[i] for i in selected_indices]
            # Set the new keypoints to the image keypoints map
            img_kpt_map.update({ImageKeyPoint(image_index, index): ImageKeyPoint(image_index, new_index) for new_index, index in enumerate(selected_indices)})
            # # Create a list to store the new keypoints
            # new_keypoints = []
            # # Iterate over the keypoints
            # for i, kpt in enumerate(image.keypoints):
            #     # Create a new image keypoint object
            #     img_kpt = ImageKeyPoint(image_index, i)
            #     # Check if the image keypoint is not in the matched keypoints
            #     if img_kpt not in matched_img_kpts:
            #         continue
            #     # Check if the image keypoint is valid
            #     # if not self.check_image_keypoint(img_kpt):
            #     #     continue
            #     # Create a new image keypoint object
            #     new_img_kpt = ImageKeyPoint(image_index, len(new_keypoints))
            #     # Append the keypoint to the new keypoints list
            #     new_keypoints.append(kpt)
            #     # Add the image keypoint to the dictionary
            #     img_kpt_map[img_kpt] = new_img_kpt
            # Set the new keypoints to the image keypoints
            image.keypoints = new_keypoints
        # Return the image keypoints dictionary
        return img_kpt_map

    '''Remove invalid matches from the match list and pack the remaining matches'''
    def reindex_matches(self, img_kpt_map:dict):
        # Get the feature matches from the visual matches
        new_match_list = [FeatureMatch(img_kpt_map[match.query_img_kpt], img_kpt_map[match.train_img_kpt], match.distance) for match in self.visual_match_list] # if match.query_img_kpt in img_kpt_map and match.train_img_kpt in img_kpt_map
        # # Create a list to store the new matches
        # new_match_list = []
        # # Iterate over the matches
        # for match in self.visual_match_list:
        #     # Get the query image keypoint
        #     query_img_kpt = match.query_img_kpt
        #     # Get the train image keypoint
        #     train_img_kpt = match.train_img_kpt
        #     # Check if the query image keypoint is not in the image keypoint map
        #     if query_img_kpt not in img_kpt_map:
        #         continue
        #     # Check if the train image keypoint is not in the image keypoint map
        #     if train_img_kpt not in img_kpt_map:
        #         continue
        #     # Create a new match object
        #     new_match = FeatureMatch(img_kpt_map[query_img_kpt], img_kpt_map[train_img_kpt], match.distance)
        #     # Append the match to the new match list
        #     new_match_list.append(new_match)
        # Set the new matches to the match list
        self.visual_match_list = new_match_list
        # Return the new matches
        return new_match_list

    '''Reset the sensor poses to None'''
    def reset_sensor_poses(self):
        # Iterate over the images
        for image in self.image_list:
            # Set the image pose to None
            image.pose = None
            # Set the image pose inverse to None
            image.pose_inv = None
        # Iterate over the clouds
        for cloud in self.cloud_list:
            # Set the cloud pose to None
            cloud.pose = None

    '''Scale the visual system by the scale factor'''
    def scale_visual_system(self):
        # Iterate over the pose list
        for pose in self.pose_list:
            # Scale the translation by the scale factor
            pose.t = pose.t * self.pose_scale
        # Iterate over the camera list
        for camera in self.camera_list:
            # Scale the translation by the scale factor
            camera.extrinsic.t = camera.extrinsic.t * self.visual_scale
        # Iterate over the landmark list
        for landmark in self.landmark_list:
            # Scale the 3D point by the scale factor
            landmark.point3d = landmark.point3d * self.visual_scale

    '''Transform the poses origin to the first main pose'''
    def transform_poses(self):
        if self.camera_names:
            # get the main camera name
            main_camera_name = self.get_main_camera_name()
            # get the main images
            main_images = self.get_images_by_camera_name(main_camera_name)
            # get the main image times
            main_times = [image.time for image in main_images]
        elif self.lidar_names:
            # get the main lidar name
            main_lidar_name = self.get_main_lidar_name()
            # get the main clouds
            main_clouds = self.get_clouds_by_lidar_name(main_lidar_name)
            # get the main cloud times
            main_times = [cloud.time for cloud in main_clouds]
        else:
            return
        # get the first main image time
        first_main_time = min(main_times)
        # get the first main pose
        first_main_pose = self.get_pose_by_time(first_main_time)
        # transform the origin of pose list to the first main pose
        new_pose_list = Pose.transform_origin(self.pose_list, first_main_pose)
        # update the pose list
        self.update_pose_list(new_pose_list)

    '''Update the pose list with the new pose list and reset the sensor poses'''
    def update_pose_list(self, new_pose_list):
        # Set the pose list as the new pose list
        self.pose_list = new_pose_list
        # Reset the sensor poses
        self.reset_sensor_poses()
