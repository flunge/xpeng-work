import numpy as np
import cv2
import torch
import os

from scene.cameras import Camera

def check_gassians_outside_object(iteration, xyz, viewpoint_cam: Camera):
    """
    Check if any of the gaussians are outside the object by projecting them to the image plane.
    If any gaussian is outside the object, return True.
    """
    # size is same as gaussians.xyz.shape[0]
    gaussians_outside_object = torch.zeros(xyz.shape[0], dtype=torch.bool)
    if iteration < 3000:
        return gaussians_outside_object.to("cuda")

    gt_image = viewpoint_cam.original_image.cpu()
    gt_image_np = convert_cpu_image_to_numpy(gt_image)
    if gt_image_np is None:
        print("[Warning] GT image is None, cannot check gaussians outside object.")
        return gaussians_outside_object.to("cuda")

    points_2d = convert_gassians_to_pixel_coordinates(xyz, viewpoint_cam)
    
    # Check if any point is in the image mask, the mask's rgb is black
    for i, (u, v) in enumerate(points_2d):
        if 0 <= u < gt_image_np.shape[1] and 0 <= v < gt_image_np.shape[0]:
            # if np.all(gt_image_np[v, u] == [0, 0, 0]) or np.all(gt_image_np[v, u] == [255, 255, 255]):
            if np.all(gt_image_np[v, u] == [0, 0, 0]):
                gaussians_outside_object[i] = True

    # print how many gaussians are outside the object, and how many are inside
    total_gaussians = xyz.shape[0]
    num_outside = torch.sum(gaussians_outside_object).item()
    num_inside = torch.sum(~gaussians_outside_object).item()

    if iteration % 100 == 0:
        print(f"[check_gassians_outside_object] iteration: {iteration}, total: {total_gaussians}, {num_outside} gaussians are outside the object, {num_inside} gaussians are inside the object.")

    # if num_outside > 4000:
    #     project_gaussians_to_image(xyz, viewpoint_cam)

    return gaussians_outside_object.to("cuda")

def project_gaussians_to_image(xyz, viewpoint_cam: Camera):
    gt_image = viewpoint_cam.original_image.cpu()
    gt_image_np = convert_cpu_image_to_numpy(gt_image)
    if gt_image_np is None:
        print("[Warning] GT image is None, cannot project gaussians to image.")
        return

    points_2d = convert_gassians_to_pixel_coordinates(xyz, viewpoint_cam)

    for (u, v) in points_2d:
        cv2.circle(gt_image_np, (int(u), int(v)), 1, (0, 255, 0), -1)
    cv2.imwrite("projected_gaussians.png", gt_image_np)
        
    return 

def convert_gassians_to_pixel_coordinates(xyz, viewpoint_cam: Camera):
    camera_r = torch.tensor(viewpoint_cam.R.T, dtype=torch.float32).cpu()
    camera_t = torch.tensor(viewpoint_cam.T, dtype=torch.float32).reshape(3, 1).cpu()
    intrinsic = torch.tensor(viewpoint_cam.K, dtype=torch.float32).cpu()

    gaussians_xyz = xyz.cpu()
    gaussians_xyz = gaussians_xyz.T

    xyzs_cam = torch.matmul(camera_r, gaussians_xyz) + camera_t
    xyzs_cam = xyzs_cam.T

    points_2d = torch.matmul(xyzs_cam, intrinsic.T)
    points_2d = points_2d[:, :2] / points_2d[:, 2:]

    return points_2d.cpu().detach().numpy().astype(np.int32)

def rendered_image_saved(rand_idx, rendered_image, gt_image, saved_dir):
    """
    Save the rendered image and ground truth image to the specified directory.
    """
    if not os.path.exists(saved_dir):
        os.makedirs(saved_dir, exist_ok=True)

    gt_image_np = convert_cpu_image_to_numpy(gt_image.cpu())
    rendered_image_np = convert_cpu_image_to_numpy(rendered_image.cpu().detach())
    if gt_image_np is not None and rendered_image_np is not None:
        combined_image = np.hstack((gt_image_np, rendered_image_np))
        # convert black mask to white mask
        combined_image[combined_image == 0] = 255  # Change black pixels to white
        image_path = os.path.join(saved_dir, f"rendered_image_{rand_idx}.png")
        cv2.imwrite(image_path, combined_image)
        print(f"[rendered_image_saved] Combined image saved to {image_path}")


def print_using_variable(iteration, viewpoint_cam: Camera, gaussians, rendered_image):
    print("[print_using_variable] Iteration:", iteration)

    # print viewpoint_cam and gt_image
    print("[print_using_variable] Viewpoint Camera:", viewpoint_cam.__dict__.keys())
    print("[print_using_variable] Gaussians:", gaussians.__dict__.keys())
    
    # print gaussians xyz, features, opacity, scales, rotations shape
    print("[print_using_variable] Gaussians XYZ shape:", gaussians.get_xyz.shape)
    print("[print_using_variable] Gaussians Features shape:", gaussians.get_features.shape)
    print("[print_using_variable] Gaussians Opacity shape:", gaussians.get_opacity.shape)
    print("[print_using_variable] Gaussians Rotations shape:", gaussians.get_rotation.shape)

    # print scaling details
    print("[print_using_variable] Gaussians Scaling", gaussians.get_scaling)
    # print max radii2D
    print("[print_using_variable] Gaussians Max Radii2D:", gaussians.max_radii2D)

    gt_image = viewpoint_cam.original_image.cpu()
    # display gt image
    gt_image_np = convert_cpu_image_to_numpy(gt_image)

    # display rendered image
    rendered_image_np = convert_cpu_image_to_numpy(rendered_image.cpu().detach())
    if gt_image_np is not None and rendered_image_np is not None:
        combined_image = np.hstack((gt_image_np, rendered_image_np))
        cv2.imwrite("combined_image_{}.png".format(iteration), combined_image)

def convert_cpu_image_to_numpy(cpu_image):
    if cpu_image is not None and hasattr(cpu_image, 'shape'):
        image_trans = cpu_image.numpy().transpose(1, 2, 0)  # Convert from CHW to HWC format
        image_np = image_trans[..., [2, 1, 0]]  # Convert RGB to BGR for OpenCV
        image_np = np.ascontiguousarray(image_np)  # Ensure contiguous memory layout
        image_np = (image_np * 255.0).astype('uint8')  # Convert to uint8 for OpenCV
        return image_np
    return None