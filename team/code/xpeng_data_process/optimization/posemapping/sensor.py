import glob
import math
import os
import numpy as np
import cv2

from .mod3d import Mod2D, Mod3D
from .point_cloud import MapPoint, MapSurfel
from .pose import Pose
from .utils import bisearch_list_nearest, get_lidar_names_from_repack_name, get_output_dir, rotation2euler


class SimpleCloud:
    def __init__(self, cloud_index:int, lidar_name:str, time:int):
        self.cloud_index = cloud_index
        self.lidar_name = lidar_name
        self.time = time

    '''Create a cloud from a dictionary'''
    @staticmethod
    def from_dict(cloud_dict:dict):
        # Create a cloud object using the cloud index, lidar name, and time
        cloud = SimpleCloud(cloud_dict['cloud_index'], cloud_dict['lidar_name'], cloud_dict['time'])
        return cloud

    '''Convert the cloud to a dictionary'''
    def to_dict(self):
        # Convert the cloud to a dictionary
        cloud_dict = {'cloud_index':self.cloud_index, 'lidar_name':self.lidar_name, 'time':self.time}
        return cloud_dict

class SimpleCamera:
    def __init__(self, camera_name:str=None, intrinsic:np.ndarray=None, extrinsic:Pose=None):
        self.camera_name = camera_name # Name of the camera, e.g. 'cam2', 'cam3', 'cam4', 'cam5', 'cam6', 'cam7'
        self.intrinsic = intrinsic # Intrinsic matrix of the camera
        self.extrinsic = extrinsic # Extrinsic matrix of the camera

    '''Create a camera from a dictionary'''
    @staticmethod
    def from_dict(camera_dict:dict):
        # Get the camera name from the camera dictionary
        camera_name = camera_dict['camera_name']
        # Get the intrinsic matrix from the camera dictionary
        intrinsic = np.array(camera_dict['intrinsic'])
        # Get the extrinsic matrix from the camera dictionary
        extrinsic = Pose.from_dict_of_extrinsic(camera_dict['extrinsic'])
        # Create a camera object using the camera name, intrinsic matrix, and extrinsic matrix
        camera = SimpleCamera(camera_name, intrinsic, extrinsic)
        return camera


    '''Convert the camera to a dictionary'''
    def to_dict(self):
        # Convert the camera to a dictionary
        camera_dict = {'camera_name':self.camera_name, 'intrinsic':self.intrinsic.tolist(), 'extrinsic':self.extrinsic.to_dict_of_extrinsic()}
        return camera_dict

    '''Project a 3D point to the image plane'''
    def project_point_pinhole(self, point:np.ndarray):
        # Project the 3D point to the image plane
        point = self.intrinsic @ self.extrinsic.transform_point(point)
        # Normalize the projected point
        point /= point[2]
        # Return the projected point
        return point[:2]

class SimpleImage:
    def __init__(self, camera_name:str, time:int, points_undistorted:list):
        self.camera_name = camera_name # camera name
        self.time = time # image time
        self.points_undistorted = points_undistorted # undistorted keypoints coordinates

    '''Create an image from a dictionary'''
    @staticmethod
    def from_dict(image_dict:dict):
        # Get the camera name from the image dictionary
        camera_name = image_dict['camera_name']
        # Get the time from the image dictionary
        time = image_dict['time']
        # Get the undistorted keypoints coordinates from the image dictionary
        points_undistorted = image_dict['points_undistorted']
        # Create an image object using the camera name, time, and undistorted keypoints coordinates
        image = SimpleImage(camera_name, time, points_undistorted)
        return image

    '''Convert the image to a dictionary'''
    def to_dict(self):
        # Convert the image to a dictionary
        image_dict = {'camera_name':self.camera_name, 'time':self.time, 'points_undistorted':self.points_undistorted}
        return image_dict

class SimpleLidar:
    def __init__(self, lidar_name:str, extrinsic:Pose):
        self.lidar_name = lidar_name # lidar name
        self.extrinsic = extrinsic # extrinsic matrix

    '''Create a lidar from a dictionary'''
    @staticmethod
    def from_dict(lidar_dict:dict):
        # Get the lidar name from the lidar dictionary
        lidar_name = lidar_dict['lidar_name']
        # Get the extrinsic matrix from the lidar dictionary
        extrinsic = Pose.from_dict_of_extrinsic(lidar_dict['extrinsic'])
        # Create a lidar object using the lidar name and extrinsic matrix
        lidar = SimpleLidar(lidar_name, extrinsic)
        return lidar

    '''Convert the lidar to a dictionary'''
    def to_dict(self):
        # Convert the lidar to a dictionary
        lidar_dict = {'lidar_name':self.lidar_name, 'extrinsic':self.extrinsic.to_dict_of_extrinsic()}
        return lidar_dict

class SimpleLandmark:
    def __init__(self, index:int, point3d:np.ndarray, valid:bool=True):
        self.index = index # Landmark ID
        self.valid = valid # Validity of the landmark
        self.point3d = np.array(point3d, dtype=np.float64) # 3D point

    '''Create a landmark from a dictionary'''
    @staticmethod
    def from_dict(landmark_dict:dict):
        # Get the index from the landmark dictionary
        index = landmark_dict['index']
        # Get the validity from the landmark dictionary
        valid = landmark_dict['valid']
        # Get the 3D point from the landmark dictionary
        point3d = np.asarray(landmark_dict['point3d'], dtype=np.float64)
        # Create a landmark object using the index, validity, and 3D point
        landmark = SimpleLandmark(index, point3d, valid)
        return landmark

    '''Convert the landmark to a dictionary'''
    def to_dict(self):
        # Convert the landmark to a dictionary
        landmark_dict = {'index':self.index, 'valid':self.valid, 'point3d':self.point3d.tolist()}
        return landmark_dict

class SubrunDir:
    def __init__(self, subrun_dir:str):
        self.valid = True if isinstance(subrun_dir, str) else False
        self.subrun_dir = subrun_dir
        if self.valid:
            sub_dirs = glob.glob(subrun_dir)
            if sub_dirs is not None and len(sub_dirs) > 0:
                self.subrun_dir = sub_dirs[0]
            else:
                self.valid = False

    @staticmethod
    def extract_subrun_id(subrun_dir:str)->str:
        # Get the subrun ID from the subrun directory
        subrun_id = os.path.basename(subrun_dir)
        return subrun_id

    '''Get the subrun ID from the subrun directory'''
    def get_subrun_id(self)->str:
        # Get the subrun ID from the subrun directory
        subrun_id = os.path.basename(self.subrun_dir)
        return subrun_id

    '''Get the pose files in the subrun directory'''
    def get_pose_files(self)->list:
        # Get the subrun ID
        subrun_id = self.get_subrun_id()
        # Get the pose file path regular expression
        pose_file_path_regex = os.path.join(self.subrun_dir, f"{subrun_id}_pose.txt")
        # Get the pose files in the subdirectory
        pose_files = glob.glob(pose_file_path_regex)
        # Check if the pose files are empty
        if pose_files is not None and len(pose_files) > 0:
            # Return the pose files if they are not empty
            return pose_files
        # Get the pose file path regular expression
        pose_file_path_regex = os.path.join(self.subrun_dir, "*", "pose.txt")
        # Get the pose files in the subdirectory
        pose_files = glob.glob(pose_file_path_regex)
        # Return the pose files
        return pose_files

    '''Get the calibration file in the subrun directory'''
    def get_calib_file(self)->str:
        # Get the subrun ID
        subrun_id = self.get_subrun_id()
        # Get the calibration file regular expression
        calib_file_regex = os.path.join(self.subrun_dir, f"{subrun_id}_calib.json")
        # Get the calibration file
        calib_files = glob.glob(calib_file_regex)
        # Check if the calibration file is empty
        if calib_files is not None and len(calib_files) > 0:
            # Return the calibration file if it is not empty
            return calib_files[0]
        # Get the calibration file regular expression
        calib_file_regex = os.path.join(self.subrun_dir, "*", "calibration.json")
        # Get the calibration file
        calib_files = glob.glob(calib_file_regex)
        # Check if the calibration file is empty
        if calib_files is not None and len(calib_files) > 0:
            # Return the calibration file
            return calib_files[0]
        # Otherwise, return None
        return None

    '''Get the files in the subrun directory for the sensor'''
    def get_sensor_files(self, sensor_name:str)->list:
        # Get the sensor files based on the sensor name
        # Check if the sensor name starts with 'cam'
        if sensor_name.startswith('cam'):
            # Get the image files using the camera name if the sensor name starts with 'cam'
            sensor_files = self.get_image_files(sensor_name)
        # Check if the sensor name starts with 'lidar'
        elif sensor_name.startswith('lidar'):
            # Get the lidar files using the lidar name if the sensor name starts with 'lidar'
            sensor_files = self.get_lidar_files(sensor_name)
        # Return the sensor files
        return sensor_files

    '''Get the image files in the subrun directory using the camera name'''
    def get_image_files(self, camera_name="cam*")->list:
        # Get the image path regular expression
        image_path_regex = os.path.join(self.subrun_dir, "*", camera_name, "*.jpg")
        # Get the image files in the subdirectory
        image_files = glob.glob(image_path_regex)
        return image_files

    '''Get the lidar files in the subrun directory using the repack name'''
    def get_repack_files(self, repack_name="lidar*")->list:
        # Get the lidar path regular expression
        lidar_path_regex = os.path.join(self.subrun_dir, "*", repack_name, "*.npy")
        # Get the lidar files in the subdirectory
        lidar_files = glob.glob(lidar_path_regex)
        return lidar_files

    '''Get the lidar files in the subrun directory using the lidar name'''
    def get_lidar_files(self, lidar_name="lidar*")->list:
        # Get the lidar path regular expression
        lidar_path_regex = os.path.join(self.subrun_dir, "*", lidar_name, "*.npy")
        # Get the lidar files in the subdirectory
        lidar_files = glob.glob(lidar_path_regex)
        # Check if the lidar files are empty
        if not lidar_files:
            # Get the repack names in the subrun directory
            repack_names = self.get_repack_names()
            # Iterate over the repack names
            for repack_name in repack_names:
                # Get the lidar names from the repack name
                lidar_names = get_lidar_names_from_repack_name(repack_name)
                # Check if the lidar name is in the lidar names
                if lidar_name in lidar_names:
                    # Get the lidar files from the repack name if the lidar name is in the lidar names
                    lidar_files = self.get_repack_files(repack_name)
                    # Break the loop if the lidar files are not empty
                    if lidar_files is not None and len(lidar_files) > 0:
                        break
        return lidar_files

    '''Get the camera names in the subrun directory'''
    def get_camera_names(self, camera_name="cam*")->list:
        # Get the camera directory regular expression
        camera_dir_regex = os.path.join(self.subrun_dir, "*", camera_name)
        # Get the camera directories in the subdirectory
        camera_dirs = glob.glob(camera_dir_regex)
        # Get the camera names from the camera directories
        camera_names = [os.path.basename(camera_dir) for camera_dir in camera_dirs]
        return camera_names

    '''Get the liar repack names in the subrun directory'''
    def get_repack_names(self, repack_name="lidar*")->list:
        # Get the lidar directory regular expression
        repack_dir_regex = os.path.join(self.subrun_dir, "*", repack_name)
        # Get the lidar directories in the subdirectory
        repack_dirs = glob.glob(repack_dir_regex)
        # Get the lidar names from the lidar directories
        repack_names = [os.path.basename(repack_dir) for repack_dir in repack_dirs]
        return repack_names

    '''Get the dynamic object detection files in the subrun directory'''
    def get_mod_files(self):
        # Create an empty list to store the mod files list
        mods_files = []
        # Get the clip dir regular expression
        clip_dir_regex = os.path.join(self.subrun_dir, "c-*")
        # Get clip dirs
        clip_dirs = glob.glob(clip_dir_regex)
        # Loop over clip dirs
        for clip_dir in clip_dirs:
            # Get clip id from clip dir
            clip_id = os.path.basename(clip_dir)
            # Create an empty list to store the mod files
            mod_files = []
            # Get the mod file path regular expression
            mod_file_dir_regex = os.path.join(clip_dir, "cam2", "*/")
            # Get the mod files in the subdirectory
            mod_dirs = glob.glob(mod_file_dir_regex)
            if not mod_dirs:
                # Get the mod file path regular expression
                mod_file_dir_regex = os.path.join(clip_dir, "lidar_repack", "*/")
                # Get the mod files in the subdirectory
                mod_dirs = glob.glob(mod_file_dir_regex)
            # Loop through the mod directories
            for mod_dir in mod_dirs:
                # Check if the mod directory exists
                if os.path.isdir(mod_dir):
                    # Get the mod file path regular expression
                    mod_file_path_regex = os.path.join(mod_dir, "*.json")
                    # Get the mod files in the mod directory
                    mod_file = glob.glob(mod_file_path_regex)[-1]
                    # Append the mod file to the list of mod files
                    mod_files.append(mod_file)
            # Add mod file list to mods dict
            mods_files.append(mod_files)
        # Return the list of mod files
        return mods_files

class Lidar:
    def __init__(self, lidar_name:str=None, lidar_dict:dict=None, extrinsic:Pose=None, lidar_pos:str=None):
        self.lidar_name = lidar_name # Name of the lidar, e.g. 'lidar0', 'lidar1', 'lidar2'
        self.lidar_dict = lidar_dict # Lidar dictionary containing the lidar calibration data
        self.extrinsic = extrinsic # Extrinsic matrix of the lidar
        self.lidar_pos = lidar_pos # Position of the lidar, e.g. 'rslidar128', 'rslidarm1_left', 'rslidarm1_right'
        # Get parameters form lidar dict if it is provided
        if lidar_dict:
            self.parse_lidar_dict()

    '''Parse the lidar dictionary'''
    def parse_lidar_dict(self):
        # Get the extrinsic matrix from the lidar dictionary
        self.extrinsic = Pose.from_transform_matrix_4x4(np.array(self.lidar_dict['extrinsic']['transformation_matrix']))
        # Get the position from the lidar dictionary
        self.pos = self.lidar_dict['pos']

    '''Save the extrinsic back to the lidar dictionary'''
    def update_lidar_dict(self):
        # Get the extrinsic matrix from the camera dictionary
        extrinsic_mat = np.linalg.inv(self.extrinsic.get_transform_matrix_4x4())
        # Get the euler angles and translation from the extrinsic matrix
        euler_angles = rotation2euler(extrinsic_mat[:3, :3], "xyz")
        translates = extrinsic_mat[:3, 3]
        # Update the camera dictionary with the extrinsic matrix
        self.lidar_dict['extrinsic']['x'] = translates[0]
        self.lidar_dict['extrinsic']['y'] = translates[1]
        self.lidar_dict['extrinsic']['z'] = translates[2]
        self.lidar_dict['extrinsic']['roll'] = math.degrees(euler_angles[0])
        self.lidar_dict['extrinsic']['pitch'] = math.degrees(euler_angles[1])
        self.lidar_dict['extrinsic']['yaw'] = math.degrees(euler_angles[2])
        # Update the lidar dictionary
        self.lidar_dict['extrinsic']['transformation_matrix'] = self.extrinsic.get_transform_matrix_4x4().tolist()

    '''Check if the point is within the field of view of the lidar'''
    def point_in_fov(self, point:np.ndarray, max_dist:float=None)->bool:
        # Get the field of view from the lidar dictionary
        # Set the field of view to 360 degrees if the lidar name is 'lidar2' else 120 degrees
        fov = 360 if self.lidar_name == 'lidar2' else 120
        # Check if the maximum distance is None
        if max_dist is None:
            # Set the maximum distance to 150.0 if the lidar name is 'lidar2' else 100.0
            max_dist = 150.0 if self.lidar_name == 'lidar2' else 100.0
        # Get the angle between the point and the lidar
        angle = np.arctan2(point[1], point[0]) * 180 / np.pi
        # Get the square distance between the point and the lidar
        square_dist = np.sum(point[:2] ** 2)
        # Check if the angle is within the field of view
        return abs(angle) <= fov / 2 and square_dist <= max_dist ** 2

class BaseCamera(SimpleCamera):
    def __init__(self, camera_name:str=None, intrinsic:np.ndarray=None, dist:np.ndarray=None, extrinsic:Pose=None, width:int=None, height:int=None, hfov:float=None, vfov:float=None):
        self.camera_name = camera_name # Name of the camera, e.g. 'cam2', 'cam3', 'cam4', 'cam5', 'cam6', 'cam7'
        self.intrinsic = intrinsic # Intrinsic matrix of the camera
        self.dist = dist # Distortion coefficients of the camera
        self.extrinsic = extrinsic # Extrinsic matrix of the camera
        self.scaled_intrinsic = {} # Scaled intrinsic matrix of the camera
        self.width = width if width else 0 # Width of the camera image
        self.height = height if height else 0 # Height of the camera image
        self.hfov = hfov if hfov else math.radians(170) # Horizontal field of view of the camera
        self.vfov = vfov if vfov else math.radians(170) # Vertical field of view of the camera

    '''Get the scaled intrinsic matrix'''
    def getscaled_intrinsic(self, scale:float=1.0)->np.ndarray:
        # Check if the scale is already in the dictionary
        if scale in self.scaled_intrinsic:
            return self.scaled_intrinsic[scale]
        # Create a copy of the intrinsic matrix
        scaled_intrinsic = np.copy(self.intrinsic)
        # Scale the intrinsic matrix
        scaled_intrinsic[0, 0] *= scale
        scaled_intrinsic[1, 1] *= scale
        scaled_intrinsic[0, 2] *= scale
        scaled_intrinsic[1, 2] *= scale
        # Add the scaled intrinsic matrix to the dictionary
        self.scaled_intrinsic[scale] = scaled_intrinsic
        # Return the scaled intrinsic matrix
        return scaled_intrinsic

    '''Undistort the image using the intrinsic matrix and distortion coefficients'''
    def undistort_image(self, image:np.ndarray)->np.ndarray:
        # Undistort the image using the intrinsic matrix and distortion coefficients
        undistorted_image = cv2.undistort(image, self.intrinsic, self.dist)
        return undistorted_image

    '''Undistort the image points using the intrinsic matrix and distortion coefficients'''
    def undistort_image_points(self, points:np.ndarray)->np.ndarray:
        # You can call cv2.undistortImagePoints instead in the latest OpenCV (version 4.9.0+)
        if callable(getattr(cv2, 'undistortImagePoints', None)):
            # Undistort the points using the intrinsic matrix and distortion coefficients
            return cv2.undistortImagePoints(points, self.intrinsic, self.dist)
        # Undistort the points using the intrinsic matrix and distortion coefficients
        undistorted_normalized_points = cv2.undistortPoints(points, self.intrinsic, self.dist)
        undistorted_normalized_point3s = np.hstack((undistorted_normalized_points.reshape(-1, 2), np.ones((undistorted_normalized_points.shape[0], 1))))
        undistorted_point3s = np.dot(undistorted_normalized_point3s, self.intrinsic[:2].T)
        undistorted_points = undistorted_point3s.reshape(-1, 1, 2)
        return undistorted_points

    '''Undistort the points using the intrinsic matrix and distortion coefficients'''
    def undistort_points(self, points:np.ndarray)->np.ndarray:
        if points is None or len(points) == 0:
            return points
        # Undistort the points using the intrinsic matrix and distortion coefficients
        undistorted_points = self.undistort_image_points(points)
        return undistorted_points

    '''Undistort the keypoints using the intrinsic matrix and distortion coefficients'''
    def undistort_keypoints(self, keypoints:list, keypoint_scale=1.0)->list:
        # Convert the keypoints to a NumPy array
        points = np.array([keypoint.pt for keypoint in keypoints], dtype=np.float32).reshape(-1, 1, 2)
        # Scale the points using the keypoint scale
        points *= keypoint_scale
        # Undistort the points using the intrinsic matrix and distortion coefficients
        undistorted_points = self.undistort_points(points)
        # Squeeze the undistorted points array
        undistorted_points = undistorted_points.reshape(-1, 2)
        # Create a list to store the undistorted keypoints
        undistorted_keypoints = [cv2.KeyPoint(kpt_un[0], kpt_un[1], kpt.size, kpt.angle, kpt.response, kpt.octave, kpt.class_id) for kpt, kpt_un in zip(keypoints, undistorted_points)]
        # undistorted_keypoints = []
        # # Iterate over the keypoints
        # for i, kpt in enumerate(keypoints):
        #     # Get the undistorted keypoint
        #     kpt_un = undistorted_points[i, 0]
        #     # Create a new undistorted keypoint using the undistorted point coordinates and the original keypoint attributes
        #     undistorted_keypoint = cv2.KeyPoint(kpt_un[0], kpt_un[1], kpt.size, kpt.angle, kpt.response, kpt.octave, kpt.class_id)
        #     # Append the undistorted keypoint to the list of undistorted keypoints
        #     undistorted_keypoints.append(undistorted_keypoint)
        return undistorted_keypoints

    '''Project the points to the image plane using the intrinsic matrix and distortion coefficients'''
    def project_points(self, points):
        # Get the pose from the extrinsic matrix
        pose = self.extrinsic
        # Transform the points to the camera frame
        camera_points = pose.transform_points(points)
        # Get the points indices with negtive z coordinates
        invalid_z = camera_points[:, 2] <= 0
        # Get the points indices with invalid horizontal field of view
        invalid_hfov = np.abs(camera_points[:, 0]) > camera_points[:, 2] * np.tan(self.hfov / 2)
        # Get the points indices with invalid vertical field of view
        invalid_vfov = np.abs(camera_points[:, 1]) > camera_points[:, 2] * np.tan(self.vfov / 2)
        # Get the invalid indices
        invalid_indices = invalid_z | invalid_hfov | invalid_vfov
        # Set the camera points to origin if the z coordinate is negative
        camera_points[invalid_indices] = 0
        # Project the points using the intrinsic matrix and pose
        proj_points, _ = cv2.projectPoints(points, pose.R, pose.t, self.intrinsic, self.dist)
        # Set the camera points to zero if the z coordinate is negative
        camera_points[invalid_indices] = 0
        # Return the projected points
        return proj_points, camera_points

    '''Project the point to the image plane using the intrinsic matrix and distortion coefficients'''
    def project_point(self, point):
        # Get the pose from the extrinsic matrix
        pose = self.extrinsic
        # Convert the point to a NumPy array
        points = np.array([point]).reshape(-1,1,3)
        # Project the point using the intrinsic matrix and pose
        proj_point = cv2.projectPoints(points, pose.R, pose.t, self.intrinsic, self.dist)
        # Return the projected point
        return proj_point[0].flatten()

    '''Project the keypoints to the image plane using the intrinsic matrix and distortion coefficients'''
    def project_keypoints(self, keypoints:list):
        # Get the pose from the extrinsic matrix
        pose = self.extrinsic
        # Convert the keypoints to a NumPy array
        points = np.array([keypoint.pt for keypoint in keypoints], dtype=np.float32).reshape(-1, 1, 2)
        # Project the points using the intrinsic matrix and pose
        proj_points, _ = self.project_points(points, pose)
        # Convert the projected points to a list of keypoints
        proj_keypoints = [cv2.KeyPoint(point[0, 0], point[0, 1], 0) for point in proj_points[0]]
        # Return the projected keypoints
        return proj_keypoints

class Camera(BaseCamera):
    def __init__(self, camera_name:str=None, camera_dict:dict=None, mask:np.ndarray=None):
        self.camera_name = camera_name # Name of the camera, e.g. 'cam2', 'cam3', 'cam4', 'cam5', 'cam6', 'cam7'
        self.camera_dict = camera_dict # Camera dictionary containing the camera calibration data
        self.mask = mask # Camera mask for the camera
        self.intrinsic = np.eye(3) # Intrinsic matrix of the camera
        self.dist = np.zeros(8) # Distortion coefficients of the camera
        self.extrinsic = Pose.identity() # Extrinsic matrix of the camera
        self.scaled_intrinsic = {} # Scaled intrinsic matrix of the camera
        self.width = 0 # Width of the camera image
        self.height = 0 # Height of the camera image
        # Get parameters form camera dict if it is provided
        if camera_dict:
            self.parse_camera_dict()

    '''Parse the camera dictionary'''
    def parse_camera_dict(self):
        # Parse the camera dictionary
        # hfov = float(self.camera_dict['properties']['hfov'])
        # vfov = float(self.camera_dict['properties']['vfov'])
        self.width = float(self.camera_dict['properties']['width'])
        self.height = float(self.camera_dict['properties']['height'])
        self.hfov = math.radians(float(self.camera_dict['properties'].get('hfov', 170)))
        self.vfov = math.radians(float(self.camera_dict['properties'].get('vfov', 170)))
        focal_length = float(self.camera_dict['intrinsic']['focal_length'])
        fx = focal_length * 1000 / 4.2 # self.width / (2 * math.tan(math.radians(hfov) / 2))
        fy = focal_length * 1000 / 4.2 # self.height / (2 * math.tan(math.radians(vfov) / 2))
        cx = self.camera_dict['intrinsic']['cx']
        cy = self.camera_dict['intrinsic']['cy']
        k1 = self.camera_dict['intrinsic']['k1']
        k2 = self.camera_dict['intrinsic']['k2']
        p1 = self.camera_dict['intrinsic']['p1']
        p2 = self.camera_dict['intrinsic']['p2']
        k3 = self.camera_dict['intrinsic']['k3']
        k4 = self.camera_dict['intrinsic']['k4']
        k5 = self.camera_dict['intrinsic']['k5']
        k6 = self.camera_dict['intrinsic']['k6']
        self.intrinsic = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]])
        self.extrinsic = Pose.from_transform_matrix_4x4(np.array(self.camera_dict['extrinsic']['transformation_matrix']))
        self.dist = np.array([k1, k2, p1, p2, k3, k4, k5, k6])

    '''Save the extrinsic back to the camera dictionary'''
    def update_camera_dict(self):
        # Get the extrinsic matrix from the camera dictionary
        extrinsic_mat = np.linalg.inv(self.extrinsic.get_transform_matrix_4x4())
        # Get the euler angles and translation from the extrinsic matrix
        euler_angles = rotation2euler(extrinsic_mat[:3, :3], "xyz")
        translates = extrinsic_mat[:3, 3]
        # Update the camera dictionary with the extrinsic matrix
        self.camera_dict['extrinsic']['x'] = translates[0]
        self.camera_dict['extrinsic']['y'] = translates[1]
        self.camera_dict['extrinsic']['z'] = translates[2]
        self.camera_dict['extrinsic']['roll'] = math.degrees(euler_angles[0])
        self.camera_dict['extrinsic']['pitch'] = math.degrees(euler_angles[1])
        self.camera_dict['extrinsic']['yaw'] = math.degrees(euler_angles[2])
        # Update the camera dictionary
        self.camera_dict['extrinsic']['transformation_matrix'] = self.extrinsic.get_transform_matrix_4x4().tolist()

    '''Resize the camera mask'''
    def resize_mask(self, shape:np.ndarray)->np.ndarray:
        # Resize the camera mask
        self.mask = cv2.resize(self.mask, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST)
        # Return the resized camera mask
        return self.mask


class CachedImage:
    def __init__(self, image_path:str=None, image:np.ndarray=None, camera_name:str=None, time:int=None):
        if image_path and os.path.exists(image_path):
            self.save_path = image_path
            return
        output_dir = get_output_dir("image")
        file_name = f"{camera_name}_{time}.jpg"
        self.save_path = os.path.join(output_dir, file_name)
        if image is not None and len(image) > 0:
            cv2.imwrite(self.save_path, image)

    def get_image(self):
        if not os.path.exists(self.save_path):
            return None
        return cv2.imread(self.save_path, cv2.IMREAD_ANYDEPTH)

    def set_image(self, image:np.ndarray):
        cv2.imwrite(self.save_path, image)

    def clear(self):
        if os.path.exists(self.save_path):
            os.remove(self.save_path)

class Image:
    def __init__(self, image_index:int, camera:Camera, image_path:str=None, time:int=0, mod_list:list=None, image_data:np.ndarray=None):
        self.image_index:int = image_index # Index of the image
        self.camera:Camera = camera # Name of the camera, e.g. 'cam2', 'cam3', 'cam4', 'cam5', 'cam6', 'cam7'
        self.camera_name:str = camera.camera_name if camera else None # Name of the camera, e.g. 'cam2', 'cam3', 'cam4', 'cam5', 'cam6', 'cam7'
        self.time:int = time # Time of the image
        self.cached_mask:CachedImage = None # Mod mask for the image
        self.keypoints:list[cv2.KeyPoint] = [] # Keypoints of the image
        self.keypoints_undistorted:list[cv2.KeyPoint] = [] # Undistorted keypoints of the image
        self.pose:Pose = None # Pose object
        self.pose_inv:Pose = None # Inverse pose object
        self.mod:dict = None # Mod object
        self.keypoint_scale:float = 1.0 # Keypoint scale
        self.cached_image:CachedImage = None # Cached image object
        self.shape:np.ndarray = np.array([0, 0]) # Shape of the image
        # Check if the image path or image data is provided
        if image_path or image_data is not None:
            # Load the image if the image path is provided
            self.load_image(image_path, image_data)
        # Check if the mod list is provided
        if mod_list:
            # Get the mod object from the mod list if the mod list is provided
            self.get_mod(mod_list)

    '''Load the image from the image path'''
    def __getattr__(self, name):
        if name == 'image':
            return self.cached_image.get_image()
        elif name == 'mod_mask':
            return self.cached_mask.get_image()
        return super().__getattr__(name)

    '''Set the image to the image path'''
    def __setattr__(self, name, value):
        if name == 'image':
            self.cached_image.set_image(value)
            self.shape = value.shape
        elif name == 'mod_mask':
            self.cached_mask.set_image(value)
        else:
            super().__setattr__(name, value)

    '''Clear the image buffer'''
    def clear_buffer(self):
        # Clear the image buffer
        self.cached_image.clear()
        self.cached_mask.clear()
        self.camera = None
        self.mod = None

    '''Get the mod object from the mod list'''
    def get_mod(self, mod_list: list):
        # Get the time from the image
        time = self.time
        # Get the index of the mod object with the nearest time to the image time from the mod list
        index = bisearch_list_nearest(mod_list, time, lambda x: x["time"])
        # Check if the index is -1
        if index == -1:
            # Return if the index is -1
            return
        # Get the mod object from the mod list
        self.mod = mod_list[index]

    '''Draw motion blur area on the mask'''
    def draw_motion_blur_area(self, mask:np.ndarray):
        # Check if the camera name is not 'cam7'
        if self.camera_name != 'cam7':
            # Return if the camera name is not 'cam7'
            return
        # Get the ego speed vector from the mod dictionary
        vel_vec = self.mod['ego_info']['ego_speed_vec']
        # Get the ego velocity from the ego speed vector
        ego_velocity = np.asarray([vel_vec['x'], vel_vec['y'], vel_vec['z']])
        # Get the ego speed from the ego velocity
        ego_speed = np.linalg.norm(ego_velocity)
        # Get the height and width of the mask
        h, w = mask.shape[:2]
        # Get the thickness of the motion blur area
        t = max(0, min(h//6, int(ego_speed * 4 - 20)))
        # Get the vertex points of the motion blur area
        points = np.array([[[0, h], [w, h], [w, h - t], [w//2, h - t*2], [0, h - t]]], dtype=np.int32)
        # Draw the motion blur area on the mask
        cv2.fillPoly(mask, points, 0)

    '''Generate full mask mixed with mod and camera from the mod file and camera mask separately'''
    def generate_full_mask(self, immobile_tracks:set):
        # Create a new mask based on camera mask using openCV deep copy
        mod_mask = self.camera.mask.copy()
        # If size of mod_mask mismatches with image size
        if mod_mask.shape[0] != self.shape[0] or mod_mask.shape[1] != self.shape[1]:
            # Resize the mod mask to the image size
            mod_mask = cv2.resize(mod_mask, (self.shape[1], self.shape[0]))
        # Check if the mod is not None and 'mod_list' is in the mod
        if self.mod is not None and 'mod_list' in self.mod:
            # Draw motion blur area on the mask
            self.draw_motion_blur_area(mod_mask)
            # Get the mask from the mod file
            mod_list = self.mod["mod_list"]
            # Iterate over the mod list
            for mod_obj in mod_list:
                # Get the 2D mod from the mod object
                mod2d_dict = mod_obj.get("mod_2d")
                # Check if the 2D mod is None
                if mod2d_dict is None:
                    continue
                mod_2d = Mod2D(mod2d_dict)
                # Get the 3D mod from the mod object
                mod3d_dict = mod_obj.get("mod_3d")
                # Initialize the mod extension
                mod_ext = 4
                # Check if the 3D mod is not None
                if mod3d_dict is not None:
                    # Create a Mod3D object from the 3D mod dictionary
                    mod_3d = Mod3D(mod3d_dict)
                    # Get the velocity from the 3D mod
                    mod_vel = mod_3d.velocity
                    # Get the speed from the velocity
                    mod_speed = np.linalg.norm(mod_vel)
                    # Get the 3D box from the 3D mod
                    mod_box3d = mod_3d.bbox3d_info
                    # Get the position from the 3D box
                    mod_position = np.array([mod_box3d['x'], mod_box3d['y'], mod_box3d['z']])
                    # Get the distance from the position
                    mod_dist = np.linalg.norm(mod_position)
                    # # Get the credible flag from the 3D mod
                    # world_ekf_credible = mod_3d['velocity'].get('world_ekf_credible')
                    # # Treat zero speed dynamic object as static object
                    # if mod_speed < 0.1 and world_ekf_credible:
                    #     continue
                    if mod_3d.track_id in immobile_tracks:
                        continue
                    # Get the extension from the speed and distance
                    mod_ext = min(16, int(mod_speed/mod_dist*10))
                # Get the 2D detections from the 2D mod
                det_2d = mod_2d.detections.get(self.camera_name)
                # Check if the 2D detections are None
                if det_2d is None:
                    continue
                # Get the 2D bounding box from the 2D box
                box_2d = det_2d.bbox2d
                # Get the top-left and bottom-right coordinates of the box
                top_left = (box_2d[0]//2 - mod_ext, box_2d[1]//2 - mod_ext)
                bottom_right = (box_2d[2]//2 + mod_ext, box_2d[3]//2 + mod_ext)
                # Draw a rectangle on the mask
                cv2.rectangle(mod_mask, top_left, bottom_right, 0, -1)
        # Set the mask name
        mask_name = f"{self.camera_name}_mask"
        # Set the cached mask to the mod mask
        self.cached_mask = CachedImage(None, mod_mask, mask_name, self.time)
        # half_mask = cv2.resize(mask, (0, 0), fx=0.5, fy=0.5)
        # cv2.imshow('mask', half_mask)
        # cv2.waitKey(0)

    '''Load the image from the image path'''
    def load_image(self, image_path:str=None, image:np.ndarray=None):
        # # Check if the image path is a string
        # if isinstance(image_path, str):
        #     # Load the image using OpenCV
        #     image = cv2.imread(image_path)
        # # Check if the image path is a NumPy array
        # if not isinstance(image, np.ndarray):
        #     # Return if the image is None
        #     return
        # # Filter the image using a bilateral filter
        # #image = cv2.bilateralFilter(image, d=5, sigmaColor=30, sigmaSpace=30)
        # # Check if the image is a rgb image
        # if image.ndim == 3 and image.shape[2] >= 3:# and os.name == 'posix'
        # # convert the image to gray scale if it is a rgb image
        #     image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        # # Check if the camera name is not a string
        # if not isinstance(self.camera_name, str):
        #     # Get the camera name from the image path using the split function
        #     self.camera_name = self.get_camera_name_from_image_path(image_path)
        # # check if the time is not provided
        # if self.time == 0:
        #     # Get the time from the image path if it is not provided
        #     self.time = self.get_time_from_image_path(image_path)
        # Set the image to the input image
        self.cached_image = CachedImage(image_path, None, self.camera_name, self.time)
        # # Set the shape of the image
        # self.shape[:] = image.shape[:2]
        # # if self.camera_name == 'cam7':
        # #     self.image = cv2.resize(self.image, (0, 0), fx=2.1, fy=2.1)

    '''Get the pixel value from the image at the given point'''
    @staticmethod
    def get_pixel(image:np.ndarray, point:np.ndarray):
        # Convert the point to an integer
        x, y = int(point[0]), int(point[1])
        # Limit the x and y values to the image dimensions
        x = max(0, min(x, image.shape[1] - 1))
        y = max(0, min(y, image.shape[0] - 1))
        # Return the pixel value from the image at the given point
        return image[y, x]

    '''Get the camera name from the image path'''
    def get_camera_name_from_image_path(self, image_path:str)->str:
        # Get the camera name from the image path using the split function
        camera_name = image_path.split('/')[-2]
        # Return the camera name
        return camera_name

    '''Get the time from the image path'''
    def get_time_from_image_path(self, image_path:str)->int:
        # Get the time from the image path
        time = int(os.path.split(image_path)[-1].split('.')[0])
        # Return the time
        return time

    '''Undistort the keypoints using the camera'''
    def undistort_keypoints(self, camera:BaseCamera):
        # Scale the keypoints using the camera
        self.scale_keypoints(camera)
        # Undistort the keypoints using the camera
        self.keypoints_undistorted = camera.undistort_keypoints(self.keypoints, self.keypoint_scale)
        # Set the keypoints to None
        self.keypoints.clear()
        # Return the undistorted keypoints
        return self.keypoints_undistorted

    '''Scale the keypoints using the camera'''
    def scale_keypoints(self, camera:BaseCamera):
        # Calculate the new scale factor
        new_scale = camera.width / self.shape[1]
        # Set the new scale factor
        self.keypoint_scale = new_scale

class Landmark:
    def __init__(self, index:int, point3d:np.ndarray, valid:bool=True, color:np.ndarray=np.array(0.0)):
        self.index = index # Landmark ID
        self.point3d = np.array(point3d, dtype=np.float64) # 3D point
        # Check if the color is a scalar, if so, convert it to a 3D color, otherwise, use the 3D color
        self.color3d = np.array([color, color, color], dtype=np.float64) if color.ndim == 0 else color
        self.valid = valid # Validity of the landmark

class Visibility:
    def __init__(self, landmark_index:int, img_kpt_list:list):
        self.img_kpts = img_kpt_list
        self.landmark_index = landmark_index

    '''Create a visibility from a dictionary'''
    @staticmethod
    def from_dict(visibility_dict:dict):
        # Get the landmark index from the visibility dictionary
        landmark_index = visibility_dict['landmark_index']
        # Get the image keypoints from the visibility dictionary
        img_kpts = [ImageKeyPoint.from_dict(img_kpt) for img_kpt in visibility_dict['img_kpts']]
        # Create a visibility object using the landmark index and image keypoints
        visibility = Visibility(landmark_index, img_kpts)
        return visibility

    '''Convert the visibility to a dictionary'''
    def to_dict(self):
        # Convert the visibility to a dictionary
        visibility_dict = {'landmark_index':self.landmark_index, 'img_kpts': [img_kpt.to_dict() for img_kpt in self.img_kpts]}
        return visibility_dict

class ImageKeyPoint:
    def __init__(self, image_index:int, keypoint_index:int, valid:bool=True):
        self.image_index = image_index
        self.keypoint_index = keypoint_index
        self.valid = valid

    '''Create an ImageKeyPoint from a dictionary'''
    @staticmethod
    def from_dict(img_kpt_dict:dict):
        # Get the image index from the image keypoint dictionary
        image_index = img_kpt_dict['image_index']
        # Get the keypoint index from the image keypoint dictionary
        keypoint_index = img_kpt_dict['keypoint_index']
        # Get the validity from the image keypoint dictionary
        valid = img_kpt_dict['valid']
        # Create an ImageKeyPoint object using the image index, keypoint index, and validity
        img_kpt = ImageKeyPoint(image_index, keypoint_index, valid)
        return img_kpt

    '''Convert the ImageKeyPoint to a dictionary'''
    def to_dict(self):
        img_kpt = {'image_index': self.image_index, 'keypoint_index': self.keypoint_index, 'valid': self.valid}
        return img_kpt

    '''transform ImageKeyPoint to a unique key for comparison in a set or dictionary'''
    def get_key(self)->int:
        return self.image_index*65536+self.keypoint_index

    '''check if two ImageKeyPoint objects are equal'''
    def __eq__(self, other)->bool:
        return self.image_index == other.image_index and self.keypoint_index == other.keypoint_index

    '''check if one ImageKeyPoint object is less than another ImageKeyPoint object'''
    def __lt__(self, other)->bool:
        return self.get_key() < other.get_key()

    '''this function must be implemented if ImageKeyPoint need to be used as a key in a set or dictionary'''
    def __hash__(self)->int:
        return hash(self.get_key())

class FeatureMatch:
    def __init__(self,
                 query_img_kpt:ImageKeyPoint=None,
                 train_img_kpt:ImageKeyPoint=None,
                 distance:float=None):
        self.query_img_kpt = query_img_kpt
        self.train_img_kpt = train_img_kpt
        self.distance = distance

    def to_dict(self):
        return {
            'query_img_kpt': self.query_img_kpt.to_dict() if self.query_img_kpt else None,
            'train_img_kpt': self.train_img_kpt.to_dict() if self.train_img_kpt else None,
            'distance': self.distance
        }

    @staticmethod
    def from_dict(match_dict):
        query_dict = match_dict.get('query_img_kpt')
        train_dict = match_dict.get('train_img_kpt')
        distance = match_dict.get('distance')

        query_img_kpt = ImageKeyPoint.from_dict(query_dict) if query_dict else None
        train_img_kpt = ImageKeyPoint.from_dict(train_dict) if train_dict else None

        return FeatureMatch(query_img_kpt, train_img_kpt, distance)

class PointMatch:
    def __init__(self, src_point:MapPoint, dst_surfel:MapSurfel, valid:bool=True):
        self.src_point = src_point
        self.dst_surfel = dst_surfel
        self.valid = valid

    '''Create a point match from a dictionary'''
    @staticmethod
    def from_dict(point_match_dict:dict):
        # Get the source point from the point match dictionary
        src_point = MapPoint.from_dict(point_match_dict['src_point'])
        # Get the destination surfel from the point match dictionary
        dst_surfel = MapSurfel.from_dict(point_match_dict['dst_surfel'])
        # Get the validity from the point match dictionary
        valid = point_match_dict['valid']
        # Create a point match object using the source point, destination surfel, and validity
        point_match = PointMatch(src_point, dst_surfel, valid)
        return point_match

    '''Convert the point match to a dictionary'''
    def to_dict(self):
        point_match_dict = {
            'src_point': self.src_point.to_dict(),
            'dst_surfel': self.dst_surfel.to_dict(),
            'valid': self.valid
        }
        return point_match_dict

class CrossMatch:
    def __init__(self, landmark_index:int, dst_surfel:MapSurfel, valid:bool=True):
        self.landmark_index = landmark_index
        self.dst_surfel = dst_surfel
        self.valid = valid

    '''Create a cross match from a dictionary'''
    @staticmethod
    def from_dict(cross_match_dict:dict):
        # Get the landmark index from the cross match dictionary
        landmark_index = cross_match_dict['landmark_index']
        # Get the destination surfel from the cross match dictionary
        dst_surfel = MapSurfel.from_dict(cross_match_dict['dst_surfel'])
        # Get the validity from the cross match dictionary
        valid = cross_match_dict['valid']
        # Create a cross match object using the landmark index, destination surfel, and validity
        cross_match = CrossMatch(landmark_index, dst_surfel, valid)
        # Return the cross match object
        return cross_match

    '''Convert the cross match to a dictionary'''
    def to_dict(self):
        # Convert the cross match to a dictionary
        cross_match_dict = {
            'landmark_index': self.landmark_index,
            'dst_surfel': self.dst_surfel.to_dict(),
            'valid': self.valid
        }
        # Return the cross match dictionary
        return cross_match_dict


if __name__ == '__main__':
    image_path_regex = "E:/download/c-f4b4f267*/c-7286dc9d*/cam2/1679299291454256702.jpg"
    image_path = glob.glob(image_path_regex)[0]
    image = cv2.imread(image_path)
    sift = cv2.SIFT_create(nfeatures=5000, nOctaveLayers=5, contrastThreshold=0.01, edgeThreshold=20, sigma=1.6)
    kpts = sift.detect(image)
    intrinsic = np.array([[1.91031543e+03/2, 0.00000000e+00, 1.92478552e+03/2],
       [0.00000000e+00, 1.91031543e+03/2, 1.08982544e+03/2],
       [0.00000000e+00, 0.00000000e+00, 1.00000000e+00]])
    dist = np.array([ 2.21313536e-01, -1.49427235e-01,  1.72309374e-04,  1.16085168e-04,
       -8.57501291e-03,  5.82212508e-01, -1.56733766e-01, -4.38998155e-02])
    camera = BaseCamera('cam2', intrinsic, dist, np.eye(4))
    image_undistorted = camera.undistort_image(image)
    kpts_undistorted = camera.undistort_keypoints(kpts)
    img_kpts = image.copy()
    cv2.drawKeypoints(image, kpts, img_kpts)
    img_kpts_undistorted = image_undistorted.copy()
    cv2.drawKeypoints(image_undistorted, kpts_undistorted, img_kpts_undistorted)
    cv2.imwrite("img_kpts.jpg", img_kpts)
    cv2.imwrite("img_kpts_undistorted.jpg", img_kpts_undistorted)