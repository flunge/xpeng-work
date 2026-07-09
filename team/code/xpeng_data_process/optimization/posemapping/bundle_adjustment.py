from __future__ import print_function
import random
import numpy as np
import cv2
import glob
import os
import json
import ctypes

from .dataset_json_utils import dump_dataset_to_json_file
from .pose import Pose
from .sensor import CrossMatch, ImageKeyPoint, PointMatch, SimpleCamera, SimpleCloud, SimpleImage, SimpleLandmark, SimpleLidar, Visibility
from .vehicle import Vehicle
from .utils import get_binary_path, get_output_dir, Log, read_json_file, uniform_sample_list, write_json_file
from .ctypes_utilis import CDataset, CDatasetNums, convert_cameras_from_ctypes, convert_clouds_from_ctypes, convert_clouds_to_ctypes, convert_cross_matches_from_ctypes, convert_cross_matches_to_ctypes, convert_images_from_ctypes, convert_images_to_ctypes, convert_landmarks_from_ctypes, convert_landmarks_to_ctypes, convert_lidars_from_ctypes, convert_lidars_to_ctypes, convert_point_matches_from_ctypes, convert_point_matches_to_ctypes, convert_poses_from_ctypes, convert_poses_to_ctypes, convert_visibilities_from_ctypes, convert_visibilities_to_ctypes, convert_cameras_to_ctypes


class BundleAdjustment:
    def __init__(self, vehicle:Vehicle, use_visual:bool, use_lidar:bool, logger=Log(), verbose:bool=False, proc_str=''):
        self.vehicle = vehicle # vehicle object
        self.time_delay = 0 # time delay between image time and point cloud time
        self.images = [] # list of SimpleImage objects
        self.landmarks = [] # list of Landmark objects
        self.poses = [] # list of Pose objects
        self.visibilities = [] # list of Visibility objects
        self.cameras = [] # list of SimpleCamera objects
        self.lidars = [] # list of Lidar objects
        self.point_matches = [] # list of PointMatch objects
        self.cross_matches = [] # list of CrossMatch objects
        self.clouds = [] # list of SimpleCloud objects
        self.use_visual = use_visual # boolean to use visual system
        self.use_lidar = use_lidar # boolean to use lidar system
        self.json_input_path = None # path of the dumped json input file
        self.json_output_path = None # path of the optimized json output
        self.binary_path = None # path of the ceres bundle adjustment executable
        self.dataset = None # dataset object for bundle adjustment to read and write data to/from it
        self.dataset_num = None # dataset numbers object for bundle adjustment to read and write data to/from it
        self.logger = logger
        self.verbose = verbose
        self.proc_str = proc_str # process string for bundle adjustment

    '''Collect data from vehicle to be used in bundle adjustment'''
    def data_from_vehicle(self):
        # image data is read-only in bundle adjustment, thus only need to be read
        self.images = self.read_images()
        # landmarks are partially read-write in bundle adjustment, thus need to be assigned
        self.landmarks = self.collect_landmarks()
        # visibilities are read-write in bundle adjustment, thus need to be assigned
        self.visibilities = self.vehicle.visibility_list
        # interpolate poses for the main images, because image time is not the same as pose time
        self.poses = self.get_main_sensor_poses()
        # camera data is partially read-write in bundle adjustment, thus need to be collected
        self.cameras = self.collect_cameras()
        # lidar data is partially read-write in bundle adjustment, thus need to be collected
        self.lidars = self.collect_lidars()
        # concatenate point matches and loop matches to be used in bundle adjustment
        all_point_match_list = self.vehicle.point_match_list + self.vehicle.loop_match_list
        # point matches are read-write in bundle adjustment, thus need to be assigned
        self.point_matches = uniform_sample_list(all_point_match_list, self.get_point_matches_limit())
        # cross matches are read-write in bundle adjustment, thus need to be assigned
        self.cross_matches = uniform_sample_list(self.vehicle.cross_match_list, self.get_point_matches_limit())
        # cloud data is read-only in bundle adjustment, thus only need to be read
        self.clouds = self.read_clouds()
        # get the time delay between image time and point cloud time from the vehicle
        self.time_delay = self.vehicle.time_delay#1.0/(1024*1024)#

    '''Get the limit of the number of point matches'''
    def get_point_matches_limit(self)->int:
        # Set the limit of the number of point matches
        limit = 0
        # Check if the lidar system is used
        if self.use_lidar:
            # Loop through all lidars in the vehicle
            for lidar in self.lidars:
                # Check if the lidar name is lidar2
                if lidar.lidar_name == 'lidar2':
                    # If the lidar name is lidar2, then add the limit by 1.5e6
                    limit += 1200000
                # Otherwise
                else:
                    # Add the limit by 0.5e6
                    limit += 500000
        # Return the limit
        return limit

    '''Interpolate poses for the images'''
    def get_main_sensor_poses(self):
        # clear the existing poses
        poses = []
        # get the main camera name
        main_sensor_name = self.vehicle.get_main_sensor_name() if self.use_visual else self.vehicle.get_main_lidar_name()
        # get the times of the images from the main camera
        main_times = self.vehicle.get_sensor_times(main_sensor_name)
        # interpolate poses for the images
        poses = Pose.interpolate_poses(self.vehicle.pose_list, main_times)
        # transform the origin of the poses to the first pose
        Pose.transform_origin_to_first_pose(poses)
        # return the interpolated poses
        return poses

    def check_rotation(self)->bool:
        # Check if the visual system is used
        if self.use_visual:
            # If the visual system is used, then get the visual scale
            self.vehicle.get_rotation_from_camera_extrinsics(self.cameras)
        # Check if the lidar system is used
        if self.use_lidar:
            # If the lidar system is used, then get the lidar scale
            self.vehicle.get_rotation_from_lidar_extrinsics(self.lidars)
        # Check if the visual rotation is not consistent
        if abs(self.vehicle.visual_rotation) > 2:
            # If the visual rotation is not consistent, then return False
            return False
        # Check if the lidar rotation is not consistent
        if abs(self.vehicle.lidar_rotation) > 2:
            # If the lidar rotation is not consistent, then return False
            return False
        # Return True if the rotation is consistent
        return True

    '''Check if the scale is consistent'''
    def check_scale(self)->bool:
        # Check if the visual system is used
        if self.use_visual:
            # If the visual system is used, then get the visual scale
            self.get_visual_scale()
        # Check if the lidar system is used
        if self.use_lidar:
            # If the lidar system is used, then get the lidar scale
            self.get_lidar_scale()
        # Check if the pose scale is not consistent
        if abs(self.vehicle.pose_scale - 1.0) > 0.05:
            # If the pose scale is not consistent, then return False
            return False
        # Check if the lidar scale is not consistent
        if abs(self.vehicle.lidar_scale - 1.0) > 0.1:
            # If the lidar scale is not consistent, then return False
            return False
        # Check if the visual scale is not consistent
        if abs(self.vehicle.visual_scale - 1.0) > 0.1:
            # If the visual scale is not consistent, then return False
            return False
        # Check if the symmetry scale is not consistent
        if abs(self.vehicle.symm_scale - 1.0) > 0.05:
            # If the symmetry scale is not consistent, then return False
            return False
        # Return True if the scale is consistent
        return True

    '''Print vehicle poses and optimized poses'''
    def print_poses(self):
        # Get the optimized poses
        optimized_poses:list[Pose] = self.poses
        # Get the optimized times
        optimized_times:list[int] = [pose.time for pose in optimized_poses]
        # Get the vehicle poses by interpolating the vehicle pose list with the optimized times
        vehicle_poses:list[Pose] = Pose.interpolate_poses(self.vehicle.pose_list, optimized_times)
        print("time,rx,ry,rz,x,y,z,rx_opt,ry_opt,rz_opt,x_opt,y_opt,z_opt")
        # Loop through all vehicle poses and optimized poses
        for i in range(len(vehicle_poses)):
            # Get the vehicle pose
            orig = vehicle_poses[i].get_rvec_t_vector()
            # Get the optimized pose
            opt = optimized_poses[i].get_rvec_t_vec().tolist()
            # Concatenate the vehicle pose and optimized pose
            v = orig + opt
            # Print the vehicle pose and optimized pose
            print("%d,%.5f,%.5f,%.5f,%.3f,%.3f,%.3f,%.5f,%.5f,%.5f,%.3f,%.3f,%.3f" % tuple(v))

    '''Backfill data from bundle adjustment results to vehicle after bundle adjustment is done'''
    def data_back_to_vehicle(self):
        # Image data, feature points, and lidar cloud do not need to be backfilled because it is read-only in
        # bundle adjustment, whereas pose and visibility are read-write, thus need to be fully backfilled
        # landmark, camera, lidar, matches data are partially read-write, thus need to be partially backfilled
        # Check if verbose is Set
        if self.verbose:
            # Print the vehicle poses and optimized poses
            self.print_poses()
        # Check if the scale is not consistent
        if not self.check_scale():
            # If the scale is not consistent, then log the error and return
            self.logger.error("Scale is not consistent, abort the backfilling")
            # Set the optimized flag to False
            self.optimized = False
            # Return
            return
        # Check if the rotation is not consistent
        if not self.check_rotation():
            # If the rotation is not consistent, then log the error and return
            self.logger.error("Rotation is not consistent, abort the backfilling")
            # Set the optimized flag to False
            self.optimized = False
            # Return
            return
        # Set the pose updated flag to True
        self.vehicle.pose_updated = True
        # Set the optimized flag to True
        self.optimized = True
        # Backfill landmark data
        self.backfill_landmarks()
        # Backfill pose data
        self.vehicle.update_pose_list(self.poses)
        # Backfill visibility data
        self.backfill_visibilities()
        # Backfill camera data, which is partially read-write in bundle adjustment
        self.backfill_cameras()
        # Backfill lidar data, which is partially read-write in bundle adjustment
        self.backfill_lidars()
        # Backfill point matches
        self.backfill_point_matches()
        # Backfill cross matches
        self.backfill_cross_matches()
        # Scale the visual system of the vehicle
        # self.scale_visual_system()
        # Backfill the time delay
        self.backfill_time_delay()

    '''Scale the visual system of the vehicle'''
    def scale_visual_system(self):
        # Check if the visual system is not used or the lidar system is used
        if self.use_lidar or not self.use_visual:
            # If the visual system is not used or the lidar system is used, then return
            return
        # Scale the visual system of the vehicle
        self.vehicle.scale_visual_system()

    '''Get the scale of the lidar system from bundle adjustment results'''
    def get_lidar_scale(self):
        # Check if the lidar system is not used
        if not self.use_lidar:
            # If the lidar system is not used, then return
            return 1
        # Get the scale of the lidar system from extrinsics
        scale_from_extrinsics = self.vehicle.get_scale_from_lidar_extrinsics(self.lidars, self.cameras)
        # Get the scale of the lidar system from poses
        scale_from_poses = self.vehicle.get_scale_from_poses(self.poses)
        # Use the scale from extrinsics if it is close to 1, otherwise use the scale from poses
        scale = scale_from_poses
        # Print the scales
        self.logger.info(f"Scale from poses: {scale_from_poses}, Scale from extrinsics: {scale_from_extrinsics}")
        # Return the scale
        return scale

    '''Get the scale of the visual system from bundle adjustment results'''
    def get_visual_scale(self):
        # Check if the visual system is not used
        if not self.use_visual:
            # If the visual system is not used, then return
            return 1
        # Get the scale of the visual system from symmetry extrinsics
        scale_from_symmetry = self.vehicle.get_scale_from_symmetry_extrinsics(self.cameras)
        # Get the scale of the visual system from extrinsics
        scale_from_extrinsics = self.vehicle.get_scale_from_camera_extrinsics(self.cameras)
        # Get the scale of the visual system from poses
        scale_from_poses = self.vehicle.get_scale_from_poses(self.poses)
        # Use the scale from extrinsics if it is close to 1, otherwise use the scale from poses
        scale = scale_from_extrinsics
        # Print the scales
        self.logger.info(f"Scale from extrinsics: {scale_from_extrinsics}, Scale from poses: {scale_from_poses}, Scale from symmetry: {scale_from_symmetry}")
        # Return the scale
        return scale

    '''Backfill cross matches from bundle adjustment results to vehicle after bundle adjustment is done'''
    def backfill_cross_matches(self):
        # Check if the lidar system or visual system is not used
        if not self.use_lidar or not self.use_visual:
            # If the lidar system or visual system is not used, then return
            return
        # Set the cross match list of vehicle to the cross matches
        self.vehicle.cross_match_list = self.cross_matches
        # # Loop through all cross matches in the vehicle
        # for i in range(len(self.vehicle.cross_match_list)):
        #     # Get the CrossMatch object
        #     cross_match = self.vehicle.cross_match_list[i]
        #     # Get the corresponding cross match object by index from the cross matches list
        #     cross_match_new = self.cross_matches[i]
        #     # Backfill the cross match
        #     cross_match.valid = cross_match_new.valid if cross_match_new is not None else False

    '''Backfill point matches from bundle adjustment results to vehicle after bundle adjustment is done'''
    def backfill_point_matches(self):
        # Check if the lidar system is not used
        if not self.use_lidar:
            # If the lidar system is not used, then return
            return
        # Set the point match list of vehicle to the point matches
        self.vehicle.point_match_list = self.point_matches
        # # Loop through all point matches in the vehicle
        # for i in range(len(self.vehicle.point_match_list)):
        #     # Get the PointMatch object
        #     point_match = self.vehicle.point_match_list[i]
        #     # Get the corresponding point match object by index from the point matches list
        #     point_match_new = self.point_matches[i]
        #     # Backfill the point match
        #     point_match.valid = point_match_new.valid if point_match_new is not None else False

    '''Backfill visibilities from bundle adjustment results to vehicle after bundle adjustment is done'''
    def backfill_visibilities(self):
        # Check if the visual system is not used
        if not self.use_visual:
            # If the visual system is not used, then return
            return
        # Set the visibility list of vehicle to the visibilities
        self.vehicle.visibility_list = self.visibilities

    '''Backfill time delay from bundle adjustment results to vehicle after bundle adjustment is done'''
    def backfill_time_delay(self):
        # Set the time delay of the vehicle to the time delay
        self.vehicle.time_delay = self.time_delay
        # Set the time delay of the vehicle calibration dictionary to the time delay
        self.vehicle.calib_dict['time_delay'] = self.time_delay
        # Print the time delay
        self.logger.info(f"Time delay: {self.time_delay}")

    '''Collect cameras from vehicle to be used in bundle adjustment'''
    def collect_cameras(self):
        # Create cameras from the vehicle cameras by creating SimpleCamera objects list comprehension
        cameras = [SimpleCamera(camera.camera_name, camera.intrinsic, camera.extrinsic) for camera in self.vehicle.camera_list]
        # # Create an empty list to store the cameras
        # cameras = []
        # # Loop through all cameras in the vehicle
        # for camera in vehicle.camera_list:
        #     # Create a SimpleCamera object from the Camera object
        #     simple_camera = SimpleCamera(camera.camera_name, camera.intrinsic, camera.extrinsic)
        #     # Append the SimpleCamera object to the cameras list
        #     cameras.append(simple_camera)
        # Return the cameras list
        return cameras

    '''Collect lidars from vehicle to be used in bundle adjustment'''
    def collect_lidars(self):
        lidars = [SimpleLidar(lidar.lidar_name, lidar.extrinsic) for lidar in self.vehicle.lidar_list]
        # # Create an empty list to store the lidars
        # lidars = []
        # # Loop through all lidars in the vehicle
        # for lidar in vehicle.lidar_list:
        #     # Create a SimpleLidar object from the Lidar object
        #     simple_lidar = SimpleLidar(lidar.lidar_name, lidar.extrinsic)
        #     # Append the SimpleLidar object to the lidars list
        #     lidars.append(simple_lidar)
        # Return the lidars list
        return lidars

    '''Collect landmarks from vehicle to be used in bundle adjustment'''
    def collect_landmarks(self):
        # Create landmarks from the vehicle landmarks by creating SimpleLandmark objects list comprehension
        simple_landmarks = [SimpleLandmark(landmark.index, landmark.point3d, landmark.valid) for landmark in self.vehicle.landmark_list]
        # # Create an empty list to store the landmarks
        # simple_landmarks = []
        # # Loop through all landmarks in the vehicle
        # for landmark in landmarks:
        #     # Create a SimpleLandmark object from the Landmark object
        #     simple_landmark = SimpleLandmark(landmark.index, landmark.point3d, landmark.valid)
        #     # Append the SimpleLandmark object to the landmarks list
        #     simple_landmarks.append(simple_landmark)
        # Return the landmarks list
        return simple_landmarks

    '''Read clouds information from vehicle to be used in bundle adjustment'''
    def read_clouds(self):
        clouds = [SimpleCloud(cloud.cloud_index, cloud.lidar_name, cloud.time) for cloud in self.vehicle.cloud_list]
        # clouds = []
        # # Loop through all clouds in the vehicle
        # for i in range(len(vehicle.cloud_list)):
        #     # Get the cloud object by index
        #     cloud = vehicle.cloud_list[i]
        #     # Create a SimpleCloud object from the cloud object
        #     simple_cloud = SimpleCloud(cloud.cloud_index, cloud.lidar_name, cloud.time)
        #     # Append the SimpleCloud object to the clouds list
        #     clouds.append(simple_cloud)
        # Return the clouds list
        return clouds

    '''Read images information from vehicle to be used in bundle adjustment'''
    def read_images(self):
        images = []
        # Loop through all images in the vehicle
        for i in range(len(self.vehicle.image_list)):
            # Get the image object by index
            image = self.vehicle.image_list[i]
            # Get the undistorted keypoints coordinates
            points_undistorted = [[keypoint.pt[0], keypoint.pt[1]] for keypoint in image.keypoints_undistorted]
            # Create a SimpleImage object from the image object
            simple_image = SimpleImage(image.camera_name, image.time, points_undistorted)
            # Append the SimpleImage object to the images list
            images.append(simple_image)
        # Return the images list
        return images

    '''Backfill landmark data from bundle adjustment results to vehicle after bundle adjustment is done'''
    def backfill_landmarks(self):
        # Check if the visual system is not used
        if not self.use_visual:
            # If the visual system is not used, then return
            return
        # Loop through all landmarks in the vehicle
        for i in range(len(self.vehicle.landmark_list)):
            # Get the SimpleLandmark object
            simple_landmark = self.landmarks[i]
            # Get the corresponding landmark object by index from the simple landmark object
            landmark = self.vehicle.landmark_list[simple_landmark.index]
            # Backfill the 3D point
            landmark.point3d = simple_landmark.point3d
            # Backfill the validity
            landmark.valid = simple_landmark.valid

    '''Backfill camera data from bundle adjustment results to vehicle after bundle adjustment is done'''
    def backfill_cameras(self):
        # Check if the visual system is not used
        if not self.use_visual:
            # If the visual system is not used, then return
            return
        # Loop through all cameras in the vehicle
        for i in range(len(self.vehicle.camera_list)):
            # Get the SimpleCamera object
            simple_camera = self.cameras[i]
            # Get the corresponding camera object by camera name from the simple camera object
            camera = self.vehicle.get_camera_by_name(simple_camera.camera_name)
            # Backfill the extrinsic matrix
            camera.extrinsic = simple_camera.extrinsic
            # Update the camera calibration dictionary
            camera.update_camera_dict()

    '''Backfill lidar data from bundle adjustment results to vehicle after bundle adjustment is done'''
    def backfill_lidars(self):
        # Check if the lidar system is not used
        if not self.use_lidar:
            # If the lidar system is not used, then return
            return
        # Loop through all lidars in the vehicle
        for i in range(len(self.vehicle.lidar_list)):
            # Get the SimpleLidar object
            simple_lidar = self.lidars[i]
            # Get the corresponding lidar object by lidar name from the simple lidar object
            lidar = self.vehicle.get_lidar_by_name(simple_lidar.lidar_name)
            # Backfill the extrinsic matrix
            lidar.extrinsic = simple_lidar.extrinsic
            # Update the lidar calibration dictionary
            lidar.update_lidar_dict()

    '''Convert data dictionary to dataset object for bundle adjustment to read and write data to/from it'''
    def convert_data_to_dataset(self, data:dict):
        # Convert the main sensor data to bytes
        main_sensor_data = data['main_sensor'].encode('utf-8')
        # Convert the images data to ctypes
        image_data = convert_images_to_ctypes(data['images'])
        # Convert the landmarks data to ctypes
        landmark_data = convert_landmarks_to_ctypes(data['landmarks'])
        # Convert the poses data to ctypes
        pose_data = convert_poses_to_ctypes(data['poses'])
        # Convert the visibilities data to ctypes
        visibility_data = convert_visibilities_to_ctypes(data['visibilities'])
        # Convert the cameras data to ctypes
        cameras_data = convert_cameras_to_ctypes(data['cameras'])
        # Convert the lidars data to ctypes
        lidar_data = convert_lidars_to_ctypes(data['lidars'])
        # Convert the point matches data to ctypes
        point_match_data = convert_point_matches_to_ctypes(data['point_matches'])
        # Convert the cross matches data to ctypes
        cross_match_data = convert_cross_matches_to_ctypes(data['cross_matches'])
        # Convert the clouds data to ctypes
        cloud_data = convert_clouds_to_ctypes(data['clouds'])
        # Set the time delay
        time_delay = self.time_delay
        # Create a CDataset object
        self.dataset = CDataset(main_sensor_data, image_data, landmark_data, pose_data, visibility_data, cameras_data, lidar_data, point_match_data, cross_match_data, cloud_data, time_delay)
        # Create a CDatasetNums object
        self.dataset_num = CDatasetNums(len(data['images']), len(data['landmarks']), len(data['poses']), len(data['visibilities']), len(data['cameras']), len(data['lidars']), len(data['point_matches']), len(data['cross_matches']), len(data['clouds']))
        # Return the dataset object and the dataset numbers object
        return self.dataset, self.dataset_num

    '''Convert dataset object to data dictionary after bundle adjustment is done'''
    def convert_dataset_to_data(self):
        # Create a dictionary to store the data
        data = {}
        # Get the main sensor data from the dataset object
        data["main_sensor"] = self.dataset.main_sensor.decode('utf-8')
        # Get the images data from the dataset object
        data["images"] = convert_images_from_ctypes(self.dataset.images, self.dataset_num.num_images)
        # Get the landmarks data from the dataset object
        data["landmarks"] = convert_landmarks_from_ctypes(self.dataset.landmarks, self.dataset_num.num_landmarks)
        # Get the poses data from the dataset object
        data["poses"] = convert_poses_from_ctypes(self.dataset.poses, self.dataset_num.num_poses)
        # Get the visibilities data from the dataset object
        data["visibilities"] = convert_visibilities_from_ctypes(self.dataset.visibilities, self.dataset_num.num_visibilities)
        # Get the cameras data from the dataset object
        data["cameras"] = convert_cameras_from_ctypes(self.dataset.cameras, self.dataset_num.num_cameras)
        # Get the lidars data from the dataset object
        data["lidars"] = convert_lidars_from_ctypes(self.dataset.lidars, self.dataset_num.num_lidars)
        # Get the point matches data from the dataset object
        data["point_matches"] = convert_point_matches_from_ctypes(self.dataset.point_matches, self.dataset_num.num_point_matches)
        # Get the cross matches data from the dataset object
        data["cross_matches"] = convert_cross_matches_from_ctypes(self.dataset.cross_matches, self.dataset_num.num_cross_matches)
        # Get the clouds data from the dataset object
        data["clouds"] = convert_clouds_from_ctypes(self.dataset.clouds, self.dataset_num.num_clouds)
        # Set the time delay
        data["time_delay"] = self.dataset.time_delay
        # Return the data
        return data

    '''Dump data to a file for bundle adjustment to read and write data to/from it'''
    def dump_for_bundle_adjustment(self):
        # # Get the temporary directory to save the temporary files
        # save_dir = get_output_dir("temp")
        # # Get the subrun id from the vehicle
        # subrun_id = self.vehicle.get_subrun_id()
        # # Get the absolute path of the dumped json input file
        # self.json_input_path = os.path.join(save_dir, f"{subrun_id}.json")
        # # Print the file path
        # print(f"Dumping data to {self.json_input_path}")
        # Create a dictionary to store the data
        data = {}
        # Set the main sensor to the name of the first camera in the vehicle
        data['main_sensor'] = self.vehicle.get_main_sensor_name()
        # Set the images as a list of dictionaries of the SimpleImage objects
        data['images'] = [image.to_dict() for image in self.images]
        # Set the landmarks as a list of dictionaries of the SimpleLandmark objects
        data['landmarks'] = [landmark.to_dict() for landmark in self.landmarks]
        # Set the poses as a list of dictionaries of the Pose objects
        data['poses'] = [pose.to_dict() for pose in self.poses]
        # Set the visibilities as a list of dictionaries of the Visibility objects
        data['visibilities'] = [visibility.to_dict() for visibility in self.visibilities]
        # Set the cameras as a list of dictionaries of the SimpleCamera objects
        data['cameras'] = [camera.to_dict() for camera in self.cameras]
        # Set the lidars as a list of dictionaries of the SimpleLidar objects
        data['lidars'] = [lidar.to_dict() for lidar in self.lidars]
        # Set the point matches as a list of dictionaries of the PointMatch objects
        data['point_matches'] = [point_match.to_dict() for point_match in self.point_matches]
        # Set the cross matches as a list of dictionaries of the CrossMatch objects
        data['cross_matches'] = [cross_match.to_dict() for cross_match in self.cross_matches]
        # Set the clouds as a list of dictionaries of the SimpleCloud objects
        data['clouds'] = [cloud.to_dict() for cloud in self.clouds]
        # Set the time delay
        data['time_delay'] = self.time_delay
        # Print the number of landmarks, poses, visibilities, cameras, lidars, point matches, cross matches, and clouds
        self.logger.info(f"Images: {len(data['images'])}, Landmarks: {len(data['landmarks'])}, Poses: {len(data['poses'])}, Visibilities: {len(data['visibilities'])}, Cameras: {len(data['cameras'])}, Lidars: {len(data['lidars'])}, Point Matches: {len(data['point_matches'])}/{len(self.vehicle.point_match_list)}, Cross Matches: {len(data['cross_matches'])}/{len(self.vehicle.cross_match_list)}, Clouds: {len(data['clouds'])}")
        # Check if the operating system is windows
        # if os.name == 'nt':
        #     # Write the data to the file
        #     write_json_file(self.json_input_path, data)
        # else:
        # Convert the data dictionary to the dataset object and the dataset numbers object
        self.convert_data_to_dataset(data)
        # Return the data
        return data

    def run_ceres_ba(self)->int:
        # Get the absolute path of the ceres bundle adjustment executable
        self.binary_path = get_binary_path()
        # Print the subrun id
        self.logger.info(f"Running ceres optimization for subrun {self.vehicle.get_subrun_id()}")
        # Check if the operating system is windows
        if os.name == 'nt':
            # Run bundle adjustment with the dumped json data by calling ceres bundle adjustment executable
            #ret = os.system(f"{self.binary_path} {self.json_input_path}")
            func = ctypes.WinDLL(self.binary_path)
        # Otherwise
        else:
            # Load the ceres bundle adjustment library
            func = ctypes.CDLL(self.binary_path)
        # Set the return type of the function
        func.run_ceres.restype = ctypes.c_int
        # Run bundle adjustment with the dataset objects by calling ceres bundle adjustment library
        ret = func.run_ceres(ctypes.byref(self.dataset), ctypes.byref(self.dataset_num))
        # Return the return value
        return ret

    '''Load data from a file that bundle adjustment has read and written data to/from it'''
    def load_from_bundle_adjustment(self):
        # # Get the temporary directory to save the temporary files
        # save_dir = get_output_dir("temp")
        # # Get the subrun id from the vehicle
        # subrun_id = self.vehicle.get_subrun_id()
        # # Get the absolute path of the optimized json output file
        # self.json_output_path = os.path.join(save_dir, f"{subrun_id}_opt.json")
        # # Print the file path
        # print(f"Loading data from {self.json_output_path}")
        # # Read the data from the file
        # data = read_json_file(self.json_output_path)
        # Convert the dataset object to data dictionary
        data = self.convert_dataset_to_data()
        # Load the landmarks from the data
        self.landmarks = [SimpleLandmark.from_dict(landmark) for landmark in data['landmarks']] if self.use_visual else []
        # Load the poses from the data
        self.poses = [Pose.from_dict(pose) for pose in data['poses']]
        # Load the visibilities from the data
        self.visibilities = [Visibility.from_dict(visibility) for visibility in data['visibilities']] if self.use_visual else []
        # Load the cameras from the data
        self.cameras = [SimpleCamera.from_dict(camera) for camera in data['cameras']] if self.use_visual else self.cameras
        # Load the lidars from the data
        self.lidars = [SimpleLidar.from_dict(lidar) for lidar in data['lidars']] if self.use_lidar else self.lidars
        # Load the point matches from the data
        self.point_matches = [PointMatch.from_dict(point_match) for point_match in data['point_matches']] if self.use_lidar else []
        # Load the cross matches from the data
        self.cross_matches = [CrossMatch.from_dict(cross_match) for cross_match in data['cross_matches']] if self.use_lidar and self.use_visual else []
        # Load the time delay from the data
        self.time_delay = data['time_delay']
        # Return the data
        return data

    '''Clear temporary files after bundle adjustment is done'''
    def clear_temp_files(self):
        # Check if the json input path exists
        if self.json_input_path is not None and os.path.exists(self.json_input_path):
            # If the json input path exists, then remove it
            os.remove(self.json_input_path)
        # Check if the json output path exists
        if self.json_output_path is not None and os.path.exists(self.json_output_path):
            # If the json output path exists, then remove it
            os.remove(self.json_output_path)

    '''Run bundle adjustment'''
    def run_bundle_adjustment(self):
        # collect data from vehicle to be used in bundle adjustment
        self.data_from_vehicle()
        # Dump data for bundle adjustment
        self.dump_for_bundle_adjustment()
        # Save data to json
        self.dataset.nums = self.dataset_num
        # dump_dataset_to_json_file(self.dataset, os.path.join(self.vehicle.get_output_dir(), f'{self.proc_str}_dataset_bef.json'))
        # Run ceres bundle adjustment
        self.run_ceres_ba()
        # dump_dataset_to_json_file(self.dataset, os.path.join(self.vehicle.get_output_dir(), f'{self.proc_str}_dataset_aft.json'))
        # After bundle adjustment is done, load optimized data from the output json file
        self.load_from_bundle_adjustment()
        # Backfill data from bundle adjustment results to vehicle
        self.data_back_to_vehicle()
        # Clear temporary files after bundle adjustment is done
        self.clear_temp_files()

