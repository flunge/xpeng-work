import cv2
import open3d as o3d
import os
import numpy as np

from .utils import get_output_dir

'''Save the landmarks to a file'''
def save_landmarks(landmarks:list, file_name:str, logger=None):
    # Check if the operating system is posix
    # if os.name == 'posix':
    #     return
    # Get the save directory
    save_dir = get_output_dir("pcd")
    # Create the save directory if it does not exist
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
    # Create the file path
    save_path = os.path.join(save_dir, file_name)
    # Print the save path
    if logger:
        logger.info(f"Saving landmarks to {save_path}")
    # Create point cloud
    pcd = o3d.geometry.PointCloud()
    # Get points and colors from landmarks
    points = np.array([landmark.point3d for landmark in landmarks if landmark.valid])
    colors = np.array([landmark.color3d for landmark in landmarks if landmark.valid])
    # Set points and colors to point cloud
    pcd.points = o3d.utility.Vector3dVector(points)
    pcd.colors = o3d.utility.Vector3dVector(colors)
    # Save point cloud to file
    o3d.io.write_point_cloud(save_path, pcd, compressed=True)

'''Save the points to a file'''
def save_points(points:np.ndarray, file_name:str, logger=None):
    if points is None or len(points) == 0:
        return
    # Check if the operating system is posix
    # if os.name == 'posix':
    #     return
    # Get the save directory
    save_dir = get_output_dir("pcd")
    # Create the save directory if it does not exist
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
    # Create the file path
    save_path = os.path.join(save_dir, file_name)
    # Print the save path
    if logger:
        logger.info(f"Saving points to {save_path}")
    # Create point cloud
    pcd = o3d.geometry.PointCloud()
    # Get points and colors from landmarks
    points = np.array(points)
    # Set points and colors to point cloud
    pcd.points = o3d.utility.Vector3dVector(points)
    # Save point cloud to file
    o3d.io.write_point_cloud(save_path, pcd, compressed=True)

'''Arrange 7 camera images'''
def arrange_7cam_images(image_paths:list, save_path:str):
    # Create a canvas that can hold all 7 camera images
    canvas = np.zeros((2028, 3856, 3), dtype=np.uint8)
    # Iterate through the image paths
    for image_path in image_paths:
        # check if the image path contains the camera name
        if "cam0" in image_path:
            # Read the image
            img = cv2.imread(image_path)
            # Check if the image height is not 474
            if img.shape[0] != 474:
                # Calculate the scale
                scale = 474 / img.shape[0]
                # Resize the image
                img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
            # Get the height and width of the image
            h, w = img.shape[:2]
            # Paste the image to the canvas
            canvas[:h, 968+503:968+503+w] = img
        elif "cam3" in image_path:
            img = cv2.imread(image_path)
            if img.shape[0] != 774:
                scale = 774 / img.shape[0]
                img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
            h, w = img.shape[:2]
            canvas[474:474+h, :w] = img
        elif "cam5" in image_path:
            img = cv2.imread(image_path)
            if img.shape[0] != 774:
                scale = 774 / img.shape[0]
                img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
            h, w = img.shape[:2]
            canvas[474+774:474+774+h, :w] = img
        elif "cam2" in image_path:
            img = cv2.imread(image_path)
            if img.shape[0] != 1080:
                scale = 1080 / img.shape[0]
                img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
            h, w = img.shape[:2]
            canvas[474:474+h, 968:968+w] = img
        elif "cam7" in image_path:
            img = cv2.imread(image_path)
            if img.shape[0] != 474:
                scale = 474 / img.shape[0]
                img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
            h, w = img.shape[:2]
            canvas[474+1080:474+1080+h, 968+503:968+503+w] = img
        elif "cam4" in image_path:
            img = cv2.imread(image_path)
            if img.shape[0] != 774:
                scale = 774 / img.shape[0]
                img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
            h, w = img.shape[:2]
            canvas[474:474+h, 968+1920:968+1920+w] = img
        elif "cam6" in image_path:
            img = cv2.imread(image_path)
            if img.shape[0] != 774:
                scale = 774 / img.shape[0]
                img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
            h, w = img.shape[:2]
            canvas[474+774:474+774+h, 968+1920:968+1920+w] = img
    # Resize the canvas
    canvas = cv2.resize(canvas, (1920, 1080), interpolation=cv2.INTER_NEAREST)
    # Save the canvas
    cv2.imwrite(save_path, canvas)

