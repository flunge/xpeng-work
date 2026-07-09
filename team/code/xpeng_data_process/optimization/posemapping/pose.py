import itertools
import numpy as np
import cv2
from scipy.spatial.transform import Rotation
from scipy.spatial.transform import Slerp
from .utils import bisearch_list_lower_bound, load_pose_vecs_from_json_file, load_pose_vecs_from_pose_dict, load_pose_vecs_from_str_list, load_pose_vecs_from_text_file, Log
class Pose:
    def __init__(self, R:np.ndarray, t:np.ndarray, time:int=0, name:str=None, logger=Log()):
        self.R = np.array(R) # Rotation matrix
        self.t = np.array(t).reshape((3, 1)) # Translation vector
        self.time = time # Time(in nano seconds)
        self.name = name # Frame name of the pose
        self.logger = logger

    '''Convert the pose object to a dictionary'''
    def to_dict(self):
        # Convert the rotation matrix and translation vector to a dictionary
        pose = {
            'rvec': self.get_rvec().tolist(),
            'tvec': self.get_tvec().tolist(),
            'time': self.time
        }
        # Return the dictionary
        return pose

    '''Convert the pose object to a dictionary of extrinsic parameters'''
    def to_dict_of_extrinsic(self):
        # Convert the rotation matrix and translation vector to a dictionary
        pose = {
            'rvec': self.get_rvec().tolist(),
            'tvec': self.get_tvec().tolist()
        }
        # Return the dictionary
        return pose

    '''Get the pose from a dictionary'''
    @staticmethod
    def from_dict(data):
        # Get the rotation matrix and translation vector from the dictionary
        R = Pose.angle_axis_to_rotation_matrix(np.array(data['rvec']))
        # Convert the translation vector to a column vector
        t = np.array(data['tvec']).reshape((3, 1))
        # Get the time from the dictionary
        time = data['time']
        # Create a pose object
        pose = Pose(R, t, time)
        # Return the pose object
        return pose

    '''Get the pose from a transformation matrix and time'''
    @staticmethod
    def from_transform_time(transform_matrix:np.ndarray, time:int=0)->'Pose':
        # Extract the rotation matrix from the transformation matrix
        R = transform_matrix[:3, :3]
        # Extract the translation vector from the transformation matrix and convert it to a column vector
        t = transform_matrix[:3, 3].reshape((3, 1))
        # Return the pose object
        return Pose(R, t, time)

    '''Get the pose from a dictionary of extrinsic parameters'''
    @staticmethod
    def from_dict_of_extrinsic(data):
        # Get the rotation matrix from the dictionary
        R = Pose.angle_axis_to_rotation_matrix(np.array(data['rvec']))
        # Convert the translation vector to a column vector
        t = np.array(data['tvec']).reshape((3, 1))
        # Create a pose object
        pose = Pose(R, t)
        # Return the pose object
        return pose

    '''String representation of the Pose object'''
    def __str__(self):
        # Return the string representation of the pose object
        return f"Pose(R={self.R}, t={self.t}, time={self.time})"

    '''Representation of the Pose object'''
    def __repr__(self):
        # Return the string representation of the pose object
        return self.__str__()

    '''Get rotation vector of the pose'''
    def get_rvec(self)->np.ndarray:
        # Convert the rotation matrix to an angle-axis rotation vector
        return Rotation.from_matrix(self.R).as_rotvec()

    '''Get translation vector of the pose'''
    def get_tvec(self)->np.ndarray:
        # Get the flattened translation vector as a row vector and return it
        return self.t.flatten()

    '''Get quaternion of the pose'''
    def get_q(self)->np.ndarray:
        # Convert the rotation matrix to a quaternion
        return Rotation.from_matrix(self.R).as_quat()

    '''Get the quaternion and translation vector of the pose as a single vector'''
    def get_q_t_vec(self)->np.ndarray:
        # Convert the rotation matrix to a quaternion
        q = Pose.rotation_matrix_to_quaternion(self.R)
        # Return the 7D vector with quaternion and translation vector
        return np.concatenate((q, self.get_tvec()))

    '''Get the quaternion and translation vector of the pose as a single vector'''
    def get_t_q_vec(self)->np.ndarray:
        # Convert the rotation matrix to a quaternion
        q = Pose.rotation_matrix_to_quaternion(self.R)
        # Return the 7D vector with quaternion and translation vector
        return np.concatenate((self.get_tvec(),q))

    '''Get the pose as a 8D vector with time, quaternion and translation vector'''
    def get_q_t_vector(self)->list:
        # Convert the rotation matrix to a quaternion
        q = Pose.rotation_matrix_to_quaternion(self.R).tolist()
        # Convert the translation vector to a list
        t = self.get_tvec().tolist()
        # Concatenate the time, quaternion and translation vector
        res = [int(self.time)]
        # Append the quaternion
        res.extend(q)
        # Append the translation vector
        res.extend(t)
        # Return the 8D vector with time, quaternion and translation vector
        return res

    '''Get the pose as a 8D vector with time, translation vector and quaternion'''
    def get_t_q_vector(self)->list:
        # Convert the rotation matrix to a quaternion
        q = Pose.rotation_matrix_to_quaternion(self.R).tolist()
        # Convert the translation vector to a list
        t = self.get_tvec().tolist()
        # Concatenate the time, translation vector and quaternion
        res = [int(self.time)]
        # Append the translation vector
        res.extend(t)
        # Append the quaternion
        res.extend(q)
        # Return the 8D vector with time, quaternion and translation vector
        return res

    '''Get the angle-axis rotation vector and translation vector of the pose as a single vector'''
    def get_rvec_t_vec(self)->np.ndarray:
        # Convert the rotation matrix to an angle-axis rotation vector
        rvec = Rotation.from_matrix(self.R).as_rotvec()
        # Return the 6D vector with angle-axis rotation vector and translation vector
        return np.concatenate((rvec, self.get_tvec()))

    '''Get the pose as a 7D vector with time, angle-axis rotation vector and translation vector'''
    def get_rvec_t_vector(self)->list:
        # Convert the rotation matrix to an angle-axis rotation vector
        rvec = Rotation.from_matrix(self.R).as_rotvec().tolist()
        # Convert the translation vector to a list
        t = self.get_tvec().tolist()
        # Concatenate the time, angle-axis rotation vector and translation vector
        res = [int(self.time)]
        # Append the angle-axis rotation vector
        res.extend(rvec)
        # Append the translation vector
        res.extend(t)
        # Return the 7D vector with time, angle-axis rotation vector and translation vector
        return res

    '''Get the quaternion and translation vector of the pose as a single vector'''
    def get_transform_matrix(self)->np.ndarray:
        # Return the 4x4 transformation matrix of the pose
        return self.get_transform_matrix_4x4()

    '''Get the 4x4 transformation matrix of the pose'''
    def get_transform_matrix_4x4(self)->np.ndarray:
        # Create a 4x4 identity matrix
        transform_matrix = np.eye(4)
        # Fill the topleft 3x3 matrix with the rotation matrix
        transform_matrix[:3, :3] = self.R
        # Fill the rightmost column with the translation vector
        transform_matrix[:3, 3] = self.t.flatten()
        # Return the transformation matrix
        return transform_matrix

    '''Get the 3x4 transformation matrix of the pose'''
    def get_transform_matrix_3x4(self)->np.ndarray:
        # Create a 3x4 matrix with identity rotation matrix and zero translation vector
        transform_matrix = np.eye(3, 4)
        # Fill the topleft 3x3 matrix with the rotation matrix
        transform_matrix[:, :3] = self.R
        # Fill the rightmost column with the translation vector
        transform_matrix[:, 3] = self.t.flatten()
        # Return the transformation matrix
        return transform_matrix

    '''Get the inverse of the pose'''
    def inverse(self)->'Pose':
        # Inverse of the rotation matrix is its transpose
        R_inv = self.R.T
        # Inverse of the translation vector is -R_inv * t
        t_inv = -R_inv @ self.t
        # Return the inverse pose object
        return Pose(R_inv, t_inv, self.time)

    '''Multiply the pose with another pose on the rightside'''
    def multiply_right(self, pose)->'Pose':
        # Multiply the rotation matrix of the other pose with rotation matrix
        self.R = self.R @ pose.R
        # Multiply the translation vector of the other pose with the rotation matrix and add the translation vector
        self.t = self.R @ pose.t + self.t
        # Return the pose object
        return self

    '''Multiply the pose with another pose on the rightside and return the result as a new pose'''
    def multiplied_right(self, pose)->'Pose':
        # Multiply the rotation matrix of the other pose with rotation matrix
        R = self.R @ pose.R
        # Multiply the translation vector of the other pose with the rotation matrix and add the translation vector
        t = self.R @ pose.t + self.t
        # Return the pose object
        return Pose(R, t, self.time)

    '''Multiply the pose with another pose on the leftside'''
    def multiply_left(self, pose)->'Pose':
        # Multiply the rotation matrix with that of the other pose
        self.R = pose.R @ self.R
        # Multiply the translation vector with the rotation matrix of the other pose and add the translation vector of the other pose
        self.t = pose.R @ self.t + pose.t
        # Return the pose object
        return self

    '''Multiply the pose with another pose on the leftside and return the result as a new pose'''
    def multiplied_left(self, pose)->'Pose':
        # Multiply the rotation matrix with that of the other pose
        R = pose.R @ self.R
        # Multiply the translation vector with the rotation matrix of the other pose and add the translation vector of the other pose
        t = pose.R @ self.t + pose.t
        # Return the pose object
        return Pose(R, t, self.time)

    '''Multiply the pose with another pose on the leftside and return the result as a new pose'''
    def multiply(self, pose)->'Pose':
        # Multiply the rotation matrix with that of the other pose
        R = self.R @ pose.R
        # Multiply the translation vector with the rotation matrix of the other pose and add the translation vector
        t = self.R @ pose.t + self.t
        # Return the new pose object
        return Pose(R, t, max(self.time, pose.time))

    '''Dot product of the pose with another pose'''
    def dot(self, pose)->'Pose':
        # Multiply the pose with another pose on the left side and return the result
        return self.multiply(pose)

    '''Transform a point using the pose'''
    def transform_point(self, point:np.ndarray)->np.ndarray:
        # Check the shape of the point and transform it accordingly
        if point.shape == (3, 1):
            # Multiply the point with the rotation matrix and add the translation vector
            return self.R @ point + self.t
        else:
            # Multiply the point with the rotation matrix of the pose and add the translation vector of the pose
            return point @ self.R.T + self.t.flatten()

    '''Transform a list of points using the pose'''
    def transform_points(self, points:np.ndarray)->np.ndarray:
        # Multiply the points with the rotation matrix and add the translation vector
        if points.shape[0] == 3:
            return self.R @ points + self.t
        elif points.shape[1] == 3:
            return points @ self.R.T + self.t.T
        else:
            self.logger.error("Invalid shape of points, must be 3xN or Nx3")
            return points

    '''Transform field points using the pose'''
    def transform_field_points(self, points:np.ndarray)->np.ndarray:
        # Copy the points
        res = points.copy()
        # Transform the points using the pose
        res[:, :3] = self.transform_points(points[:, :3])
        # return the transformed points
        return res

    '''Transform a point using the pose and return the homogeneous coordinates'''
    def transform_point_4d(self, point:np.ndarray)->np.ndarray:
        # Multiply the point with the transformation matrix on the left side and return the result
        return self.get_transform_matrix_4x4() @ point

    '''Create a unit pose object'''
    @staticmethod
    def identity()->'Pose':
        # Return a pose object with identity rotation matrix and zero translation vector
        return Pose(np.eye(3), np.zeros((3,1)))

    '''Create a pose object from a 4x4 transformation matrix'''
    @staticmethod
    def from_transform_matrix_4x4(transform_matrix:np.ndarray, time=0)->'Pose':
        # Extract the rotation matrix from the transformation matrix
        R = transform_matrix[:3, :3]
        # Extract the translation vector from the transformation matrix and convert it to a column vector
        t = transform_matrix[:3, 3].reshape((3, 1))
        # Return the pose object
        return Pose(R, t, time)

    '''Create a pose object from a a 6D vector with rotation vector and translation vector'''
    @staticmethod
    def from_rvec_t_vec(pose_vector:np.ndarray, time=0)->'Pose':
        # Convert the rotation vector to a rotation matrix
        return Pose.from_rvec_t(pose_vector[:3], pose_vector[3:], time)

    '''Create a pose object from a a 7D vector with time, rotation vector and translation vector'''
    @staticmethod
    def from_rvec_t_vector(pose_vector:np.ndarray)->'Pose':
        # Convert the rotation vector to a rotation matrix
        return Pose.from_rvec_t(pose_vector[1:4], pose_vector[4:], pose_vector[0])

    '''Create a pose object from a 7D vector with translation vector and quaternion'''
    @staticmethod
    def from_q_t_vec(pose_vector:np.ndarray, time=0)->'Pose':
        # Convert the quaternion to a rotation matrix
        return Pose.from_q_t(pose_vector[:4], pose_vector[4:], time)

    '''Create a pose object from a 8D vector with time, translation vector and quaternion'''
    @staticmethod
    def from_t_q_vector(pose_vector:np.ndarray)->'Pose':
        # Convert the quaternion to a rotation matrix
        return Pose.from_q_t(pose_vector[4:], pose_vector[1:4], pose_vector[0])

    '''Create a pose object from a 8D vector with time, quaternion and translation vector'''
    @staticmethod
    def from_q_t_vector(pose_vector:np.ndarray)->'Pose':
        # Convert the quaternion to a rotation matrix
        return Pose.from_q_t(pose_vector[1:4], pose_vector[4:], pose_vector[0])

    '''Create a pose object from time, quaternion and translation vector'''
    @staticmethod
    def from_q_t(q:np.ndarray, t:np.ndarray, time=0)->'Pose':
        # Convert the quaternion to a rotation matrix
        R = Pose.quaternion_to_rotation_matrix(q)
        # Convert the translation vector to a column vector
        t = np.array(t).reshape((3, 1))
        # Return the pose object
        return Pose(R, t, time)

    '''Create a pose object from time, angle-axis rotation vector and translation vector'''
    @staticmethod
    def from_rvec_t(rvec:np.ndarray, t:np.ndarray, time:int=0)->'Pose':
        # Convert the angle-axis rotation vector to a rotation matrix
        R = Pose.angle_axis_to_rotation_matrix(rvec)
        # Convert the translation vector to a column vector
        t = np.array(t).reshape((3, 1))
        # Return the pose object
        return Pose(R, t, time)

    '''Create a pose object from frame pose'''
    @staticmethod
    def from_frame_pose(frame_name:str, frame_pose:np.ndarray, time:int=0)->'Pose':
        # Convert the frame pose to a pose object
        pose = Pose.from_transform_matrix_4x4(frame_pose, time)
        # Set the name of the pose object
        pose.name = frame_name
        # Return the pose object
        return pose

    '''Transform a 3 by 3 rotation matrix into a quaternion'''
    @staticmethod
    def rotation_matrix_to_quaternion(R:np.ndarray)->np.ndarray:
        # Convert the rotation matrix to a rotation object and then to a quaternion
        return Rotation.from_matrix(R).as_quat()

    '''Transform a 3 by 3 rotation matrix into an angle-axis rotation vector'''
    @staticmethod
    def rotation_matrix_to_angle_axis(R:np.ndarray)->np.ndarray:
        # Convert the rotation matrix to a rotation object and then to an angle-axis rotation vector
        return Rotation.from_matrix(R).as_rotvec()

    '''Transform a quaternion into a 3 by 3 rotation matrix'''
    @staticmethod
    def quaternion_to_rotation_matrix(q:np.ndarray)->np.ndarray:
        # Convert the quaternion to a rotation matrix
        return Rotation.from_quat(q).as_matrix()

    '''Transform an angle-axis rotation vector into a 3 by 3 rotation matrix'''
    @staticmethod
    def angle_axis_to_rotation_matrix(rvec:np.ndarray)->np.ndarray:
        # Convert the angle-axis rotation vector to a rotation matrix
        return Rotation.from_rotvec(rvec).as_matrix()

    '''Interpolate pose between two poses using SLERP for rotation and linear interpolation for translation'''
    @staticmethod
    def interpolate_pose(pose0, pose1, time)->'Pose':
        # Calculate the interpolation parameter
        t = float(time - pose0.time) / float(pose1.time - pose0.time)
        # Get the quaternions of the two poses
        r0 = Rotation.from_matrix(pose0.R)
        r1 = Rotation.from_matrix(pose1.R)
        # Perform SLERP interpolation
        rots = Rotation.concatenate([r0, r1])
        slerp = Slerp([0, 1], rots)
        interpolated_quat = slerp(t)
        interpolated_rot = interpolated_quat.as_matrix()
        # Perform linear interpolation for translation
        interpolated_trans = (1 - t) * pose0.t + t * pose1.t
        # Combine interpolated rotation and translation into a 4x4 matrix
        interpolated_pose = Pose(interpolated_rot, interpolated_trans, time)
        # Return the interpolated pose
        return interpolated_pose

    '''Interpolate pose between two poses using linear interpolation for rotation and linear interpolation for translation'''
    @staticmethod
    def interpolate_pose_by_rot_vec(pose0, pose1, time)->'Pose':
        # Calculate the interpolation parameter
        t = float(time - pose0.time) / float(pose1.time - pose0.time)
        # Get the relative rotation matrix between the two poses
        deltaR = pose0.R.T @ pose1.R
        # Get the rotation vector of the relative rotation matrix
        delta_rvec = Rotation.from_matrix(deltaR).as_rotvec()
        # Interpolate the incremental rotation vector using linear interpolation
        inc_rvec = t * delta_rvec
        # Get the incremental rotation matrix from the incremental rotation vector
        incR = Rotation.from_rotvec(inc_rvec).as_matrix()
        # Get the interpolated rotation matrix
        interpolated_R = pose0.R @ incR
        # Interpolate the translation vector using linear interpolation
        interpolated_t = (1 - t) * pose0.t + t * pose1.t
        # Create the interpolated pose object using the interpolated rotation vector and translation vector
        interpolated_pose = Pose(interpolated_R, interpolated_t, time)
        # Return the interpolated pose
        return interpolated_pose

    '''Interpolate between a list of poses using linear interpolation'''
    @staticmethod
    def interpolate(pose_list:list, time:int)->'Pose':
        # If the time is before the first pose, interpolate the pose between the first two poses
        if time < pose_list[0].time:
            return Pose.interpolate_pose_by_rot_vec(pose_list[0], pose_list[1], time)
        # If the time is after the last pose, interpolate the pose between the last two poses
        if time > pose_list[-1].time:
            return Pose.interpolate_pose_by_rot_vec(pose_list[-2], pose_list[-1], time)

        # Find the interval in which the time lies and interpolate the pose
        i = bisearch_list_lower_bound(pose_list, time, lambda x: x.time)
        # If the desired time is exactly the time of a pose, return the pose
        if pose_list[i].time == time:
            return Pose(pose_list[i].R, pose_list[i].t, time)
        # Interpolate the pose
        pose = Pose.interpolate_pose(pose_list[i], pose_list[i + 1], time)
        # Return the interpolated pose
        return pose

    '''Interpolate between a list of poses using linear interpolation for a list of times'''
    '''Return the list of interpolated poses'''
    @staticmethod
    def interpolate_poses(pose_list:list, times:list, time_offset:int=0)->list:
        # Create an empty list to store the interpolated poses
        interpolated_poses = []
        # Loop through each time in the list
        for time in times:
            # Interpolate the pose for the current time
            interpolated_pose = Pose.interpolate(pose_list, time+time_offset)
            # Append the interpolated pose to the list
            interpolated_poses.append(interpolated_pose)
        # Return the list of interpolated poses
        return interpolated_poses

    '''Transform the pose list by the inverse of the first pose'''
    @staticmethod
    def transform_origin_to_first_pose(pose_list:list)->list:
        # Get the first pose in the list
        # Transform the pose list by the inverse of the first pose
        return Pose.transform_origin(pose_list, pose_list[0])

    '''Transform the pose list by the inverse of the input pose'''
    @staticmethod
    def transform_origin(pose_list:list, origin)->list:
        # Get the inverse of the first pose
        origin_inv = origin.inverse()
        # Transform each pose in the list by the inverse of the first pose
        new_poses = [pose.multiplied_left(origin_inv) for pose in pose_list]
        # Return the list of new poses
        return new_poses

    '''Transform the pose list by the inverse of pose at input time'''
    @staticmethod
    def transform_origin_at_time(pose_list:list, time:int)->list:
        # Get the pose at the input time
        origin = Pose.interpolate(pose_list, time)
        # Transform the pose list by the inverse of the pose at the input time
        return Pose.transform_origin(pose_list, origin)

    '''Load poses from a text file with multiple lines, of which each contains 8 data with the first being integer and others being decimal'''
    @staticmethod
    def load_poses_from_text_file(filename, delimiter=' ')->list:
        # Load the pose vectors from the text file
        pose_vec_list = load_pose_vecs_from_text_file(filename, delimiter)
        # Return the list of poses
        return [Pose.from_t_q_vector(pose_vec) for pose_vec in pose_vec_list]

    '''Load poses from json dictionary'''
    @staticmethod
    def load_poses_from_json_dict(json_dict:dict, pose_type:str="lidar_pose_list")->list:
        # Load the pose vectors from the json dictionary
        pose_vec_list = load_pose_vecs_from_pose_dict(json_dict, pose_type)
        # Return the list of poses
        return [Pose.from_t_q_vector(pose_vec) for pose_vec in pose_vec_list]

    '''Load poses from json file, which is an output of occupancy autolabeling'''
    @staticmethod
    def load_poses_from_json_file(filename, pose_type:str="lidar_pose_list")->list:
        # Load the pose vectors from the json file
        pose_vec_list = load_pose_vecs_from_json_file(filename, pose_type)
        # Return the list of poses
        return [Pose.from_t_q_vector(pose_vec) for pose_vec in pose_vec_list]

    '''Load poses from string list, which is an temporary var of occupancy autolabeling'''
    @staticmethod
    def load_poses_from_string_list(pose_str_list:list)->list:
        # Load the pose vectors from the string list
        pose_vec_list = load_pose_vecs_from_str_list(pose_str_list)
        # Return the list of poses
        return [Pose.from_t_q_vector(pose_vec) for pose_vec in pose_vec_list]

class PoseList:
    def __init__(self, poses:list):
        # Store the list of poses
        self.pose_list:list[Pose] = poses
        # Create dictionaries to store the poses by name and pose
        self.name_pose_dict = {pose.name: pose for pose in poses}
        # Create a dictionary to store the poses by time and pose
        self.time_pose_dict = {pose.time: pose for pose in poses}

    '''Get the pose list from a frame dictionary'''
    @staticmethod
    def from_frame_dict(frame_dict:dict)->'PoseList':
        # Get the pose objects from the dictionaries
        poses = [Pose.from_frame_pose(frame_name, frame_pose) for frame_name, frame_pose in frame_dict.items()]
        # Construct the PoseList object
        pose_list = PoseList(poses)
        # Return the PoseList object
        return pose_list

    '''Get the pose list from a list of frame dictionary and timestamp dictionary'''
    @staticmethod
    def from_frame_time_dict(frame_dict:dict, timestamp_dict:dict)->'PoseList':
        # Get the pose objects from the dictionaries
        poses = [Pose.from_frame_pose(frame_name, frame_pose, timestamp_dict[frame_name]) for frame_name, frame_pose in frame_dict.items()]
        # Construct the PoseList object
        pose_list = PoseList(poses)
        # Return the PoseList object
        return pose_list

    '''Check if a delta pose is a major movement'''
    @staticmethod
    def check_delta_pose_movement(delta_pose, threshold = 0.1):
        # calculate the relative translation and rotation of the pose
        delta_t = np.linalg.norm(delta_pose.t)
        delta_r = np.linalg.norm(delta_pose.get_rvec())
        # calculate the movement
        movement = delta_t + delta_r * 18
        # return True if the movement is less than the threshold else False
        return movement > threshold

    '''Check if a curr pose is a major movement from the prev pose'''
    def check_inter_frame_movement(self, curr_frame:str, prev_frame:str, threshold = 0.1):
        # get the current and previous poses
        curr_pose = self.name_pose_dict[curr_frame]
        prev_pose = self.name_pose_dict[prev_frame]
        # calculate the relative pose
        delta_pose = curr_pose.multiplied_left(prev_pose.inverse())
        # calculate the relative translation and rotation of the pose
        delta_t = np.linalg.norm(delta_pose.t)
        delta_r = np.linalg.norm(delta_pose.get_rvec())
        # calculate the movement
        movement = delta_t + delta_r * 18
        # return True if the movement is less than the threshold else False
        return movement > threshold

    '''Get total trip from the poses of the vehicle'''
    def get_trip(self)->float:
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

    '''Get major movement frames from the poses of the vehicle'''
    def get_major_movement_frames(self, threshold = 1.0)->list:
        # Check if the pose list is empty
        if len(self.pose_list) == 0:
            return []
        # Initialize the list of major movement frames
        major_movement_frames = [self.pose_list[0].name]
        # Get the first pose in the list
        pose0 = self.pose_list[0]
        # Iterate over the pose list
        for i in range(1, len(self.pose_list)):
            # Get the poses at the current and previous indices
            pose1 = self.pose_list[i]
            # Calculate the delta pose
            delta_pose = pose1.multiplied_left(pose0.inverse())
            # Check if the delta pose is a major movement
            if PoseList.check_delta_pose_movement(delta_pose, threshold):
                # Append the current frame name to the list of major movement frames
                major_movement_frames.append(pose1.name)
                # Update the previous pose
                pose0 = pose1
        # Return the list of major movement frames
        return major_movement_frames
