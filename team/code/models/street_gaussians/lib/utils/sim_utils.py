import os
import shutil
import cv2
import torch
import numpy as np


def save_scene_info(src_folder, dst_folder, save_misc=False):
    to_save = ["calib.json", "calib_origin.json", "localpose.json", "LocalPoseTopic.json", 
               "anchorpose.json", "annotation_for_train.json", "transform.json", "metadata.json"]
    for filename in to_save:
        src_path = os.path.join(src_folder, filename)
        dst_path = os.path.join(dst_folder, filename)
        if os.path.exists(src_path):
            shutil.copy(src_path, dst_path)
        else:
            print(f"[WARNING] {src_path} does not exist. Skipping.")
            
    autolabel_json_path = os.path.join(src_folder, "autolabel_json")
    if os.path.exists(autolabel_json_path):
        shutil.copytree(
            autolabel_json_path, os.path.join(dst_folder, "autolabel_json"), dirs_exist_ok=True
        )

    misc_path = os.path.join(src_folder, "misc")
    if save_misc and os.path.exists(misc_path):
        shutil.copytree(misc_path, os.path.join(dst_folder, "misc"), dirs_exist_ok=True)

    # copy one frame image to dst_folder for redistort
    masks = os.path.join(src_folder, "masks")
    dst_image_path = os.path.join(dst_folder, "images")
    os.makedirs(dst_image_path, exist_ok=True)
    
    if not os.path.exists(masks):
        print(f"[Warning]masks路径不存在")
    else:
        for cam in os.listdir(masks):
            if 'cam' not in cam:
                continue
            masks_list = []
            masks_acc = []
            masks_path = os.path.join(masks, cam)
            for mask_path in os.listdir(masks_path):
                if mask_path.endswith('.png'):
                    mask0_path = os.path.join(masks_path, mask_path)
                    acc = cv2.imread(mask0_path, cv2.IMREAD_GRAYSCALE).sum()
                    masks_list.append(mask0_path)
                    masks_acc.append(acc)

            # choose the mask with the largest area
            target_mask = masks_list[masks_acc.index(max(masks_acc))]
            mask0_path = os.path.join(masks_path, target_mask)
            shutil.copy(mask0_path, os.path.join(dst_image_path, cam + "_mask.png"))

            images_undistort_path = os.path.join(src_folder, "images", cam)
            image0_path = os.path.join(images_undistort_path, os.listdir(images_undistort_path)[0])
            shutil.copy(image0_path, os.path.join(dst_image_path, cam + "_image.png"))
            

def mask_ego_path_gs(ego_frame_poses, gs_xyz, ego_radius=1., ego_height=3.):
    ### Denoise the point cloud
    ego_positions = ego_frame_poses[:, :3, 3]
    gs_xyz = np.asarray(gs_xyz)
    indices_inside_all_spheres = np.array([])
    for i in range(ego_positions.shape[0]):
        center = ego_positions[i]
        # Compute the distance of each point from the current center
        distances_xy = np.sqrt((gs_xyz[:, 0] - center[0]) ** 2 + (gs_xyz[:, 1] - center[1]) ** 2)
        distances_z = np.abs(gs_xyz[:, 2] - center[2])

        # Get the indices of points inside the current sphere
        inside_sphere_mask = (distances_xy <= ego_radius) * (distances_z <= ego_height)
        indices_inside_sphere = np.where(inside_sphere_mask)[0]

        # Append indices of points inside this sphere to the list
        indices_inside_all_spheres = np.union1d(indices_inside_all_spheres.astype(int), indices_inside_sphere)

    # get the mask of points inside any sphere
    mask_gs = np.zeros(gs_xyz.shape[0], dtype=bool)
    mask_gs[indices_inside_all_spheres.astype(int)] = True
    return mask_gs


def mask_ego_path_gs_with_kdtree(egopose_kdtree, gaussian_means_detached, meter_valid, height_valid):
    ego_distances, _ = egopose_kdtree.query(gaussian_means_detached, k=1)
    ego_distances = torch.from_numpy(ego_distances)
    egopose_pts_mask = torch.where(ego_distances <= meter_valid, True, False)
    egopose_pts_mask_np = egopose_pts_mask.detach().cpu().numpy().flatten()
    ego_height_mask = gaussian_means_detached[:, 2] < height_valid
    egopose_pts_mask_np = egopose_pts_mask_np & ego_height_mask.detach().cpu().numpy().flatten()
    return egopose_pts_mask_np


def edit_ground_gaussians(gaussians, optim_args):
    try:
        scales_gd = gaussians.ground.get_scaling.detach().cpu()
        surface_gd = (scales_gd**2).sum(dim=-1)
        volume_gd = torch.prod(scales_gd, dim=1, keepdim=True) 
        ground_max_surface = optim_args.get('lambda_ground_max_surface', 1e8)
        ground_max_volume = optim_args.get('lambda_ground_max_volume', 1e8)
        mask_large_surface_gs_gd = surface_gd > ground_max_surface
        mask_large_volume_gs_gd = volume_gd > ground_max_volume
        mask_large_volume_gs_gd = torch.squeeze(mask_large_volume_gs_gd)
        mask_large_gs_gd = mask_large_surface_gs_gd | mask_large_volume_gs_gd
        print(f"[INFO] prune ground for max surface {mask_large_surface_gs_gd.sum()}/{gaussians.ground.get_xyz.shape[0]}")
        print(f"[INFO] prune ground for max volume {mask_large_volume_gs_gd.sum()}/{gaussians.ground.get_xyz.shape[0]}")
        print(f"[INFO] Total prune ground {mask_large_gs_gd.sum()}/{gaussians.ground.get_xyz.shape[0]}")
    except Exception as e:
        print(f"[WARNING] Failed to compute ground gaussians scaling: {e}")
    else:
        try:
            gaussians.ground.prune_points(mask_large_gs_gd)
        except Exception as e:
            print(f"[WARNING] Failed to prune ground gaussians: {e}")
            print("[WARNING] No ground gaussians pruning applied.")
    return


def edit_background_gaussians(gaussians, egopose_kdtree, opacity_threshold=0.):
    scales_bkgd = gaussians.background.get_scaling.detach().cpu()
    xyz_bkgd = gaussians.background.get_xyz.detach().cpu()
    surface_bkgd = (scales_bkgd**2).sum(dim=-1)
    opacity_bkgd = gaussians.background.get_opacity.detach().cpu()

    mask_large_gs_bkgd_egopose = (surface_bkgd > 1).detach().cpu().numpy() & \
        mask_ego_path_gs_with_kdtree(egopose_kdtree, xyz_bkgd, 7, 6)
    mask_egopose_gs = mask_ego_path_gs_with_kdtree(egopose_kdtree, xyz_bkgd, 1.2, 3.)

    mask_low_opacity_bkgd = (opacity_bkgd < opacity_threshold).detach().cpu().numpy().flatten()
    mask_total = mask_egopose_gs | mask_low_opacity_bkgd | mask_large_gs_bkgd_egopose
    print(f"[INFO] Total prune background {mask_total.sum()}/{gaussians.background.get_xyz.shape[0]}")
    print(f"[INFO] --- low opacity ({opacity_threshold}) background {mask_low_opacity_bkgd.sum()}")
    print(f"[INFO] --- background gs on egopose path {mask_egopose_gs.sum()}")
    print(f"[INFO] --- background gs along egopose   {mask_large_gs_bkgd_egopose.sum()}")

    gaussians.background.prune_points(mask_total)
    return