import torch
import numpy as np
from PIL import Image

def read_depth_file(filepath):
    if filepath.endswith("pfm"):
        data = read_pfm(filepath)
    elif filepath.endswith("npy"):
        npy_info = np.load(filepath, allow_pickle=True).item()
        values = npy_info['value']
        mask = npy_info['mask']
        h, w = mask.shape
        data = np.full((h, w), 0, dtype=values.dtype)
        data[mask] = values

    return data

def read_pfm(filepath):
    with open(filepath, 'rb') as f:
        header = f.readline().decode('utf-8').rstrip()
        if header == 'PF':
            color = True
        elif header == 'Pf':
            color = False
        else:
            raise ValueError('Not a PFM file.')

        dim_match = f.readline().decode('utf-8')
        width, height = map(int, dim_match.split())

        scale = float(f.readline().decode('utf-8').rstrip())
        endian = '<' if scale < 0 else '>'
        scale = abs(scale)
        data = np.fromfile(f, endian + 'f')

    if color:
        data = data.reshape((height, width, 3))
    else:
        data = data.reshape((height, width))

    data = np.flipud(data)
    return data
def read_rgb_filename(image_filename=None, seg_mask_bkgd=None):

    assert image_filename is not None
    pil_image = Image.open(image_filename)
    image = np.array(pil_image, dtype="uint8")
    image = torch.from_numpy(image.astype("float32") / 255.0)
    if seg_mask_bkgd is not None:
        seg_mask_bkgd = torch.from_numpy(seg_mask_bkgd)
        seg_mask = seg_mask_bkgd.bool()
        seg_mask = seg_mask.unsqueeze(-1).repeat(1, 1, 3)
        masked_image = image * seg_mask.float()
    else:
        masked_image = image
    return masked_image

def eval_source_images_from_current_imageid(rgbs, depths, all_pose, eval_pose,seg_mask_bkgds, num_select = 3):
    eye = torch.tensor([0., 0., 0., 1.]).to(all_pose)
    all_pose = torch.cat([all_pose, eye[None,None,:].repeat(all_pose.shape[0],1,1)],dim=1)
    eval_pose = torch.cat([eval_pose, eye[None,None,:].repeat(eval_pose.shape[0],1,1)],dim=1)
    assert len(eval_pose) == 1

    nearest_pose_ids = get_nearest_pose_ids(eval_pose.detach().cpu().numpy()[0],
                                            all_pose.detach().cpu().numpy(),
                                            num_select=num_select,
                                            tar_id= -1,
                                            angular_dist_method='dist')
    nearest_pose_ids = np.array(sorted(nearest_pose_ids))
    src_poses = all_pose[nearest_pose_ids,...]
    src_rgbs = [read_rgb_filename(rgbs[i],seg_mask_bkgds[i]) for i in nearest_pose_ids]
    
    src_rgbs =  torch.stack(src_rgbs,dim=0)

    if depths is not None:
        src_depths = [get_image_depth_tensor_from_path(depths[i]) for i in nearest_pose_ids]
        src_depths =  torch.stack(src_depths,dim=0)
    else:
        src_depths = None
    return src_rgbs, src_poses, nearest_pose_ids, src_depths

def get_image_depth_tensor_from_path(filepath, scale_factor: float = 1.0) -> torch.Tensor:
    pil_mask = read_depth_file(filepath)
    if scale_factor != 1.0:
        width, height = pil_mask.shape
        new_width, new_height = (int(width * scale_factor), int(height * scale_factor))
        pil_mask = cv2.resize(pil_mask, (new_width, new_height), interpolation=cv2.INTER_NEAREST)
    depth_tensor = torch.from_numpy(np.array(pil_mask))
    return depth_tensor

def batched_angular_dist_rot_matrix(R1, R2):
    assert R1.shape[-1] == 3 and R2.shape[-1] == 3 and R1.shape[-2] == 3 and R2.shape[-2] == 3
    return np.arccos(np.clip((np.trace(np.matmul(R2.transpose(0, 2, 1), R1), axis1=1, axis2=2) - 1) / 2.,
                             a_min=-1 + TINY_NUMBER, a_max=1 - TINY_NUMBER))

def angular_dist_between_2_vectors(vec1, vec2):
    TINY_NUMBER = 1e-6
    vec1_unit = vec1 / (np.linalg.norm(vec1, axis=1,
                        keepdims=True) + TINY_NUMBER)
    vec2_unit = vec2 / (np.linalg.norm(vec2, axis=1,
                        keepdims=True) + TINY_NUMBER)
    angular_dists = np.arccos(
        np.clip(np.sum(vec1_unit*vec2_unit, axis=-1), -1.0, 1.0))
    return angular_dists

def get_nearest_pose_ids(tar_pose, ref_poses, num_select, tar_id=-1, angular_dist_method='vector',
                         scene_center=(0, 0, 0), view_selection_method='nearest', view_selection_stride=None):
    num_cams = len(ref_poses)
    num_select = min(num_select, num_cams - 1)
    batched_tar_pose = tar_pose[None, ...].repeat(num_cams, 0)

    if angular_dist_method == 'matrix':
        dists = batched_angular_dist_rot_matrix(batched_tar_pose[:, :3, :3], ref_poses[:, :3, :3])
    elif angular_dist_method == 'vector':
        tar_cam_locs = batched_tar_pose[:, :3, 3]
        ref_cam_locs = ref_poses[:, :3, 3]
        scene_center = np.array(scene_center)[None, ...]
        tar_vectors = tar_cam_locs - scene_center
        ref_vectors = ref_cam_locs - scene_center
        dists = angular_dist_between_2_vectors(tar_vectors, ref_vectors)
    elif angular_dist_method == 'dist':
        tar_cam_locs = batched_tar_pose[:, :3, 3]
        ref_cam_locs = ref_poses[:, :3, 3]
        dists = np.linalg.norm(tar_cam_locs - ref_cam_locs, axis=1)
    else:
        raise Exception('unknown angular distance calculation method!')

    if tar_id >= 0:
        assert tar_id < num_cams
        dists[tar_id] = 1e3  # make sure not to select the target id itself

    sorted_ids = np.argsort(dists)

    if view_selection_method == 'nearest':
        if view_selection_stride is not None:
            idx = np.minimum(np.arange(1, num_select + 1, dtype=int)
                             * view_selection_stride, num_cams - 1)
            selected_ids = sorted_ids[idx]
        else:
            selected_ids = sorted_ids[:num_select]
    else:
        raise Exception('unknown view selection method!')

    return selected_ids