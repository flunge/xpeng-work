import json
import random
import numpy as np
import cv2
import glob
import os
import csv
from numba import njit
from scipy.spatial.transform import Rotation

output_dir = None

class Log:
    def __init__(self):
        pass

    def info(self, msg):
        print(msg)

    def error(self, msg):
        print(msg)

    def warning(self, msg):
        print(msg)

'''Generate a color map segment from a start color to an end color'''
def gen_colormap_seg(start_color:np.ndarray, end_color:np.ndarray, num:int)->np.ndarray:
    # Initialize the color map
    colormap = np.zeros((num, 3), dtype=np.uint8)
    # Iterate through each color in the color map
    for i in range(num):
        # Calculate the color based on the start and end colors
        colormap[i] = [int(start_color[j] + (end_color[j] - start_color[j]) * i / (num - 1)) for j in range(3)]
    # Return the color map
    return colormap

# 0 0 32->0,0,255->0,255,255->255,255,255->255,255,0->255,0,0->32,0,0
'''Generate a jet color map for visualization of depth images and point clouds'''
def gen_colormap_jet()->np.ndarray:
    color_segments = [(0, 0, 0), (0, 0, 255), (0, 255, 255), (255, 255, 255), (255, 255, 0), (255, 0, 0), (0, 0, 0)]
    colormaps = []
    for i in range(len(color_segments) - 1):
        start_color = np.array(color_segments[i])
        end_color = np.array(color_segments[i + 1])
        segment_size = np.max(np.abs(end_color - start_color))
        colormap_segment = gen_colormap_seg(start_color, end_color, segment_size)
        colormaps.append(colormap_segment)
    return np.vstack(colormaps)

'''Get a random sample of a list of items'''
def random_sample_list(data:list, num:int)->list:
    # Check if the length of the list is less than or equal to the number
    if len(data) <= num:
        # If the length of the list is less than or equal to the number, then return the list itself
        return data
    # Return a random sample of the list
    return random.sample(data, int(num))

'''Get a uniform sample of a list of items'''
def uniform_sample_list(data:list, num:int)->list:
    # Check if the length of the list is less than or equal to the number
    if len(data) <= num:
        # If the length of the list is less than or equal to the number, then return the list itself
        return data
    # Get the indices of the list to sample
    indices = np.linspace(0, len(data)-1, int(num), dtype=int)
    # Return the sampled list
    return [data[i] for i in indices]

'''Get a uniform sample of a array of items'''
def uniform_sample_array(data:np.ndarray, num:int)->np.ndarray:
    # Check if the length of the list is less than or equal to the number
    if len(data) <= num:
        # If the length of the list is less than or equal to the number, then return the list itself
        return data
    # Get the indices of the list to sample
    indices = np.linspace(0, len(data)-1, int(num), dtype=int)
    # Return the sampled list
    return data[indices]

'''Read a JSON file and return the data'''
def read_json_file(file_path):
    # open the JSON file to read
    with open(file_path, 'r') as file:
        # load the JSON data
        data = json.load(file)
    # return the data
    return data

'''Write data to a JSON file'''
def write_json_file(file_path, data, indent=0):
    # open the JSON file to write
    with open(file_path, 'w') as file:
        # write the data to the JSON file
        json.dump(data, file, indent=indent)

'''search for a key in a sorted list of dictionaries'''
def bisearch_list(obj_list, key, get_key=lambda x: x):
    # initialize the left and right pointers
    left = 0
    right = len(obj_list) - 1
    # loop until the left pointer is less than or equal to the right pointer
    while left <= right:
        # calculate the middle index
        mid = (left + right) // 2
        # if the key is found, return the index
        if get_key(obj_list[mid]) == key:
            return mid
        # if the key is less than the middle element, update the right pointer
        elif get_key(obj_list[mid]) < key:
            left = mid + 1
        # if the key is greater than the middle element, update the left pointer
        else:
            right = mid - 1
    # return -1 if the key is not found
    return -1

'''search for a key in a sorted list of dictionaries and return the lower bound'''
def bisearch_list_lower_bound(obj_list, key, get_key=lambda x: x)->int:
    # initialize the left and right pointers
    left = 0
    right = len(obj_list) - 1
    # loop until the left pointer is less than the right pointer
    while left < right:
        # calculate the middle index
        mid = (left + right + 1) // 2
        # if the key is less than or equal to the middle element, update the left pointer
        if get_key(obj_list[mid]) <= key:
            left = mid
        # otherwise, update the right pointer
        else:
            right = mid - 1
    # return the left pointer
    return left

'''search for a key in a sorted list of dictionaries and return the nearest element'''
def bisearch_list_nearest(obj_list, key, get_key=lambda x: x)->int:
    # get the lower bound index
    lower_index = bisearch_list_lower_bound(obj_list, key, get_key)
    # if the lower bound index is -1, return 0
    if lower_index == -1:
        return 0
    # if the lower bound index is the last element, return the last index
    if lower_index == len(obj_list) - 1:
        return lower_index
    # get the keys of the lower and upper elements
    lower_key = get_key(obj_list[lower_index])
    upper_key = get_key(obj_list[lower_index + 1])
    # return the lower index if the key is closer to the lower element
    if key - lower_key < upper_key - key:
        return lower_index
    # otherwise, return the upper index
    return lower_index + 1

'''normalize a point by dividing by its last element'''
def normalize_point(point):
    # return the point divided by the last element
    return point / point[-1]

'''Load poses from a text file with multiple lines, of which each contains 8 data with the first being integer and others being decimal'''
def load_pose_vecs_from_text_file(filename, delimiter=' '):
    # Initialize the list of poses
    poses = []
    # Open the file to read
    with open(filename, 'r') as file:
        # Read each line in the file
        for line in file:
            # Split the line by space character
            values = line.strip().split(delimiter)
            # Convert the data types
            pose = [int(values[0])] + [float(value) for value in values[1:]]
            # Append the pose to the list
            poses.append(pose)
    # Return the list of poses
    return poses

'''Load pese vectors from json dictionary'''
def load_pose_vecs_from_pose_dict(pose_json:dict, pose_type:str="lidar_pose_list"):
    # Initialize the list of poses
    pose_vector_list = []
    # Check if 'lidar_pose_list' key exists in the JSON data
    if pose_type not in pose_json:
        # If the key does not exist, return poses
        return pose_vector_list
    # Iterate through each pose item in the JSON data
    for pose_item in pose_json[pose_type]:
        # Convert the pose dictionary to a pose vector
        pose_vector = pose_dict_to_vec(pose_item)
        # Append the pose to the list of poses
        pose_vector_list.append(pose_vector)
    # Return the list of poses
    return pose_vector_list

'''Load poses from json file'''
def load_pose_vecs_from_json_file(filename, pose_type:str="lidar_pose_list"):
    # Read the JSON file
    pose_json = read_json_file(filename)
    # Return the list of poses from the JSON data
    return load_pose_vecs_from_pose_dict(pose_json, pose_type)

'''Convert a pose dictionary to a pose vector'''
def pose_dict_to_vec(pose_dict:dict):
    # Get the timestamp, position and quaternion from the pose dictionary
    timestamp = pose_dict["time_stamp"]["nsec"]
    p = pose_dict["smooth_pose_info"]["local_pose"]["p"]
    q = pose_dict["smooth_pose_info"]["local_pose"]["q"]
    # Collect the x, y, z, w values from the position and quaternion
    p_x, p_y, p_z = p["x"], p["y"], p["z"]
    q_x, q_y, q_z, q_w = q["x"], q["y"], q["z"], q["w"]
    # Create a pose vector from the timestamp, position and quaternion
    pose_vector = [timestamp, p_x, p_y, p_z, q_x, q_y, q_z, q_w]
    # Return the pose vector
    return pose_vector

'''Convert a pose vector to a pose dictionary'''
def pose_vec_to_dict(pose_vec:list):
    # Get the timestamp, position and quaternion from the pose vector
    timestamp = pose_vec[0]
    p = pose_vec[1:4]
    q = pose_vec[4:]
    # Create a pose dictionary from the timestamp, position and quaternion
    pose_dict = {
        "time_stamp": {"nsec": timestamp},
        "smooth_pose_info": {
            "local_pose": {
                "p": {"x": p[0], "y": p[1], "z": p[2]},
                "q": {"x": q[0], "y": q[1], "z": q[2], "w": q[3]}
            }
        }
    }
    # Return the pose dictionary
    return pose_dict

'''Save poses to a json file'''
def save_poses_to_json_file(save_path:str, poses:list, pose_type:str="cam_pose_list"):
    # Initialize the pose JSON data
    pose_json = {pose_type: []}
    # Iterate through each pose in the list of poses
    for p in poses:
        # Get the timestamp, position and quaternion from the pose
        pose = p.get_t_q_vector()
        # Convert the pose vector to a pose dictionary
        pose_item = pose_vec_to_dict(pose)
        # Append the pose item to the list of poses
        pose_json[pose_type].append(pose_item)
    # Write the pose JSON data to the file
    write_json_file(save_path, pose_json, indent=0)

'''Save calib to a json file'''
def save_calib_to_json_file(save_path, calib_dict):
    # Set the 'calib_qa' key to True in the calib dictionary
    calib_dict["calib_qa"] = True
    # Write the calib dictionary to the file
    write_json_file(save_path, calib_dict, indent=0)

'''Save both camera & lidar poses to a json file'''
def save_both_poses_to_json_file(save_path, cam_poses:list, lidar_poses:list):
    # Initialize the pose JSON data
    pose_json = {"cam_pose_list": [], "lidar_pose_list": [], "pose_qa": True}
    # Iterate through each camera pose in the list of camera poses
    for p in cam_poses:
        # Get the timestamp, position and quaternion from the camera pose
        pose = p.get_t_q_vector()
        # Convert the pose vector to a pose dictionary
        pose_item = pose_vec_to_dict(pose)
        # Append the pose item to the list of camera poses
        pose_json["cam_pose_list"].append(pose_item)
    # Iterate through each lidar pose in the list of lidar poses
    for p in lidar_poses:
        # Get the timestamp, position and quaternion from the lidar pose
        pose = p.get_t_q_vector()
        # Convert the pose vector to a pose dictionary
        pose_item = pose_vec_to_dict(pose)
        # Append the pose item to the list of lidar poses
        pose_json["lidar_pose_list"].append(pose_item)
    # Write the pose JSON data to the file
    write_json_file(save_path, pose_json, indent=0)

'''Load poses from string list'''
def load_pose_vecs_from_str_list(str_list):
    for pose_str in str_list:
        if "smooth_pose_info" in pose_str:
            pose_key = "smooth_pose_info"
            pose_item_key = 'local_pose'
            break
        elif "smooth_pose" in pose_str:
            pose_key = "smooth_pose"
            pose_item_key = 'pose'
            break
        elif "local_pose_info" in pose_str:
            pose_key = "local_pose_info"
            pose_item_key = 'local_pose'
            break
        elif "global_pose" in pose_str:
            pose_key = "global_pose"
            pose_item_key = 'world_pose_in_ecef'
            break

    poses = []
    for pose_str in str_list:
        pose_dict = json.loads(pose_str)
        if pose_key not in pose_dict or pose_item_key not in pose_dict[pose_key]:
            continue

        timestamp = pose_dict["time_stamp"]["nsec"]
        p = pose_dict[pose_key][pose_item_key]['p']
        q = pose_dict[pose_key][pose_item_key]['q']
        p_x, p_y, p_z = p['x'], p['y'], p['z']
        q_x, q_y, q_z, q_w = q['x'], q['y'], q['z'], q['w']
        pose = [timestamp, p_x, p_y, p_z, q_x, q_y, q_z, q_w]
        poses.append(pose)

    return poses

'''Save poses to a text file with each line containing 8 data with the first being integer and others being decimal'''
def save_poses_to_text_file(save_path, poses, sep=' '):
    # Write the poses to the save path
    with open(save_path, 'w') as f:
        # Iterate over the poses
        for pose in poses:
            # Get the pose vector
            pose_vector = pose.get_t_q_vector()
            # Write the pose vector to the file
            f.write(f"{pose.time}{sep}{pose_vector[1]}{sep}{pose_vector[2]}{sep}{pose_vector[3]}{sep}{pose_vector[4]}{sep}{pose_vector[5]}{sep}{pose_vector[6]}{sep}{pose_vector[7]}\n")

def save_pose_to_map(save_path, poses):
    output_pose = {}
    for pose in poses:
        pose_vector = pose.get_t_q_vector()
        output_pose[pose.time] = [pose_vector[1],pose_vector[2],pose_vector[3],pose_vector[4],pose_vector[5],pose_vector[6],pose_vector[7]]
    return output_pose

'''Read a CSV file and return the data as a list of strings, starting from the offset line'''
def read_csv_lines(filename, offset=0):
    # Initialize the list of lines
    lines = []
    # Open the CSV file to read
    with open(filename, 'r') as file:
        # Create a CSV reader
        csv_reader = csv.reader(file)
        # Read each row in the CSV file
        for row in csv_reader:
            # Append the row as a string
            lines.append(','.join(row))
    # Return the lines starting from the offset
    return lines[offset:]

'''Check if the coordinates of a point are not a number or infinity'''
def is_nan_or_inf_point(point):
    # iterate through each coordinate in the point
    for i in range(len(point)):
        # return True if the coordinate is not a number or infinity
        if np.isnan(point[i]) or np.isinf(point[i]):
            return True
    # return False if all coordinates are valid
    return False

'''Check if a point is in the image'''
def is_point_in_image(point, image_shape):
    # return True if the point is within the image bounds else False
    return 0 <= point[0] < image_shape[1] and 0 <= point[1] < image_shape[0]

'''Check if a point is in the bounds of a rectangle'''
def is_point_in_bounds(point, lower_bound, upper_bound):
    # return True if the point is within the bounds of the rectangle else False
    return lower_bound[0] <= point[0] < upper_bound[0] and lower_bound[1] <= point[1] < upper_bound[1]

'''Check if a movement is a major movement'''
def is_major_movement(delta_pose, inter_pose, threshold:float = 1.0):
    # calculate the relative translation and rotation of the pose
    delta_t = np.linalg.norm(delta_pose.t)
    delta_r = np.linalg.norm(delta_pose.get_rvec())
    # calculate the current movement
    curr_movement = delta_t + delta_r * 6
    # calculate the relative translation and rotation of the inter-frame pose
    inter_t = np.linalg.norm(inter_pose.t)
    inter_r = np.linalg.norm(inter_pose.get_rvec())
    # calculate the inter-frame movement
    inter_movement = inter_t + inter_r * 6
    # calculate the next movement, which is the current movement multiplied by 2
    next_movement = curr_movement + inter_movement
    # calculate the difference of the current and next movement with the threshold
    diff_curr = abs(curr_movement - threshold)
    diff_next = abs(next_movement - threshold)
    # return True if the movement difference with threshold is less for current movement else False
    return diff_curr < diff_next

'''Check if a movement is a minor movement'''
def is_minor_movement(delta_pose, threshold = 0.1):
    # calculate the relative translation and rotation of the pose
    delta_t = np.linalg.norm(delta_pose.t)
    delta_r = np.linalg.norm(delta_pose.get_rvec())
    # calculate the movement
    movement = delta_t + delta_r * 6
    # return True if the movement is less than the threshold else False
    return movement < threshold

'''Check if a image keypoint is valid'''
def is_valid_image_keypoint(keypoint:cv2.KeyPoint, shape:np.ndarray):
    # return False if the keypoint size is 0
    if keypoint.size == 0:
        return False
    # return False if the keypoint is not a number or infinity
    if is_nan_or_inf_point(keypoint.pt):
        keypoint.size = 0
        return False
    # return False if the keypoint is not in the image
    if not is_point_in_image(keypoint.pt, shape):
        keypoint.size = 0
        return False
    # return True if the keypoint is valid
    return True

'''Get the lidar pairs for a list of lidar names'''
def get_lidar_pairs(lidar_names:list=None):
    # initialize the full list of lidar pairs
    full_pairs = [('lidar0', 'lidar1'), ('lidar2', 'lidar1'), ('lidar2', 'lidar0')]
    # return the full list if lidar names is None
    if lidar_names is None:
        return full_pairs
    # initialize the list of lidar pairs
    pairs = []
    # iterate through each pair in the full list
    for pair in full_pairs:
        # add the pair to the list if both lidars are in the lidar names list
        if pair[0] in lidar_names and pair[1] in lidar_names:
            pairs.append(pair)
    # return the list of lidar pairs
    return pairs

'''Get the camera pairs for a list of camera names'''
def get_camera_pairs(camera_names:list=None):
    # initialize the full list of camera pairs
    full_pairs = [('cam2', 'cam4'), ('cam4', 'cam6'), ('cam6', 'cam7'), ('cam7', 'cam5'), ('cam5', 'cam3'), ('cam3', 'cam2'), ('cam2', 'cam0')]
    # return the full list if camera names is None
    if camera_names is None:
        return full_pairs
    # initialize the list of camera pairs
    pairs = []
    # iterate through each pair in the full list
    for pair in full_pairs:
        # add the pair to the list if both cameras are in the camera names list
        if pair[0] in camera_names and pair[1] in camera_names:
            pairs.append(pair)
    # return the list of camera pairs
    return pairs

'''Get window size for a camera name'''
def get_win_size(camera_name:str=None):
    if camera_name == 'cam2':
        return (25, 25)
    elif camera_name == 'cam7':
        return (20, 20)
    return (25, 25)

'''Get the number of features for a camera name'''
def get_num_features(camera_name:str=None):
    if camera_name == 'cam2':
        return 6000
    elif camera_name == 'cam7':
        return 4000
    return 3000

'''Calculate the square distance between two points'''
def square_distance(point1, point2):
    return np.sum((np.array(point1) - np.array(point2)) ** 2)

'''Get the center part ratio for camera 2'''
def get_center_part_ratio(camera_name:str=None):
    if camera_name == 'cam2':
        return (0.3, 0.7)
    else:
        return (0.0, 1.0)

'''Get the left part ratio for a camera'''
def get_left_part_ratio(camera_name:str=None):
    if camera_name == 'cam7':
        return 0.5
    elif camera_name == 'cam3' or camera_name == 'cam5' or camera_name == 'cam6':
        return 0.3
    elif camera_name == 'cam4' or camera_name == 'cam2':
        return 0.6
    else:
        return 1.0

'''Get the right part ratio for a camera'''
def get_right_part_ratio(camera_name:str=None):
    if camera_name == 'cam4' or camera_name == 'cam5' or camera_name == 'cam6':
        return 0.7
    elif camera_name == 'cam7':
        return 0.5
    elif camera_name == 'cam3' or camera_name == 'cam2':
        return 0.4
    else:
        return 0.0

'''Get the lidar names from a repack name'''
def get_lidar_names_from_repack_name(lidar_name:str):
    lidar_name_to_calib_name = {
        'lidar0': ['lidar0'],
        'lidar1': ['lidar1'],
        'lidar2': ['lidar2'],
        'lidar_repack': ['lidar2'],
        'lidar_repack2': ['lidar0', 'lidar1']}
    return lidar_name_to_calib_name.get(lidar_name, None)

'''Get the repack name from a lidar name'''
def get_repack_name_from_lidar_name(lidar_name:str):
    lidar_name_to_repack_name = {
        'lidar0': 'lidar_repack2',
        'lidar1': 'lidar_repack2',
        'lidar2': 'lidar_repack',
        'lidar_repack': 'lidar_repack',
        'lidar_repack2': 'lidar_repack2'}
    return lidar_name_to_repack_name.get(lidar_name, None)

'''Get the path of the ceres bundle adjustment executable'''
def get_binary_path():
    # Get the directory of the script
    # Get the absolute path of the ceres bundle adjustment executable
    if os.name == 'nt':
        build_dir = get_script_dir("build")
        binary_path = os.path.join(build_dir, "Release", "ceres_ba.dll")
    else:
        build_dir = get_script_dir("ceres_ba")
        binary_path = os.path.join(build_dir, "libceres_ba.so")
    # Return the binary path
    return binary_path

'''Set the directory of output files'''
def set_output_dir(dir):
    global output_dir
    # Set the output directory if it is not None
    if dir:
        output_dir = dir

'''Get script directory'''
def get_script_dir(sub_dir=""):
    # Return the directory of the script
    parent_dir = os.path.dirname(os.path.realpath(__file__))
    # Get the directory of the script
    script_dir = os.path.join(parent_dir, sub_dir)
    # Return the script directory
    return script_dir

'''Get the path of the save directory'''
def get_output_dir(save_folder:str=""):
    global output_dir
    # Check if the output directory is None
    if output_dir is None:
        # Get the absolute path of the save directory
        save_dir = get_script_dir(save_folder)
    else:
        # Get the absolute path of the save directory
        save_dir = os.path.join(output_dir, save_folder)
    # Check if the save directory exists
    if not os.path.exists(save_dir):
        # Create the save directory if it does not exist
        os.makedirs(save_dir)
    # Return the save directory
    return save_dir

'''Calculate the normal of a point cloud'''
@njit
def calc_normal_nb(points:np.ndarray)->np.ndarray:
    cov = np.cov(points, rowvar=False)
    eigvals, eigvecs = np.linalg.eigh(cov)
    results = np.zeros((4,), dtype=np.float64)
    # If the point is on a line
    if eigvals[1] / eigvals[2] < 0.4:
        results[:3] = eigvecs[:, 2]
        results[3] = 1
    # If the point is on a plane
    elif eigvals[0] / eigvals[1] < 0.6:
        results[:3] = eigvecs[:, 0]
        results[3] = 2
    return results

'''Calculate the integer key from a point'''
@njit
def point_to_key_nb(point:np.ndarray)->int:
    x = int(point[0]*10 + (1<<20))
    y = int(point[1]*10 + (1<<20)) << 21
    z = int(point[2]*10 + (1<<20)) << 42
    return x + y + z

'''Erode an image using a kernel and threshold'''
@njit
def imerode_nb(image:np.ndarray, kernel_size:int, thresh:float)->np.ndarray:
    # Get the kernel half
    kernel_half = kernel_size // 2
    # Get the image shape
    rows, cols = image.shape
    # Initialize the result image
    result = image.copy()
    # Iterate through the image
    for i in range(kernel_half, rows - kernel_half):
        for j in range(kernel_half, cols - kernel_half):
            # Get the minimum value of the image and kernel
            min_val = np.min(image[i-kernel_half:i+kernel_half+1, j-kernel_half:j+kernel_half+1])
            # Set the result value based on the threshold
            if min_val < thresh:
                # Set the result value to min_val if it is less than the threshold
                result[i, j] = min_val
    # Return the result image
    return result

'''Read a subrun csv file and return the data'''
def read_subrun_csv(filename:str)->list:
    # Open the CSV file to read
    with open(filename, newline='') as csvfile:
        # Create a CSV reader
        csvreader = csv.reader(csvfile)
        # Read the rows in the CSV file
        lines = [row[0] for row in csvreader]
        # Get the lines starting from the second row
        lines = lines[1:]
    # Return the lines
    return lines

'''Write a subrun csv file with the data'''
def write_subrun_csv(filename:str, lines:list):
    # Open the CSV file to write
    with open(filename, 'w', newline='') as csvfile:
        # Create a CSV writer
        csvwriter = csv.writer(csvfile)
        # Write the header row
        csvwriter.writerow(['id'])
        # Write the lines to the CSV file
        for line in lines:
            # Write the line to the CSV file
            csvwriter.writerow([line])

'''Transform euler angles to rotation matrix'''
def euler2rotation(euler_angles:np.ndarray, seq="zyx")->np.ndarray:
    # Create a rotation object from euler angles
    rotation = Rotation.from_euler(seq, euler_angles, degrees=False)
    # Get the rotation matrix from the rotation object
    rotation_matrix = rotation.as_matrix()
    # Return the rotation matrix
    return rotation_matrix

'''Transform rotation matrix to euler angles'''
def rotation2euler(rot_matrix:np.ndarray, seq="zyx")->np.ndarray:
    # Create a rotation object from the rotation matrix
    rotation = Rotation.from_matrix(rot_matrix)
    # Get the euler angles from the rotation object
    euler_angles = rotation.as_euler(seq, degrees=False)
    # Return the euler angles
    return euler_angles

def get_prefix(record)->str:
    """Get prefix from record.

    Args:
        record (Record): record.

    Returns:
        str: prefix.
    """
    # Get metadata from record
    metadata = record.get_metadata()
    # Get prefix from metadata
    prefix = metadata.get('prefix', '')
    # Return prefix
    return prefix
