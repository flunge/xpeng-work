import os
import sys
import numpy as np
import torch
import enum

from PIL import Image
from lib.utils.graphics_utils import getWorld2View2, focal2fov, fov2focal, BasicPointCloud
from lib.utils.colmap_utils import read_extrinsics_text, read_intrinsics_text, qvec2rotmat, \
    read_extrinsics_binary, read_intrinsics_binary, read_points3D_binary, read_points3D_text
from lib.config import cfg
from lib.datasets.base_readers import CameraInfo, SceneInfo, getNerfppNorm, fetchPly, storePly
from typing import List, Tuple, Union
from pathlib import Path
from lib.utils.xpeng_utils import generate_dataparser_outputs


class SemanticType(enum.IntEnum):
    DEFAULT = 0
    GROUND = 1
    SKY = 2
    OBJECT = 3


def readColmapCameras(cam_extrinsics, cam_intrinsics, data_folder):
    selected_frames = cfg.data.get('selected_frames', None)
    if cfg.debug:
        selected_frames = [0, 0]
    
    output = generate_dataparser_outputs(
        datadir=data_folder, 
        selected_frames=selected_frames,
        cameras=cfg.data.get('cameras', [1, 2, 3, 4, 5, 6, 7]),
    )

    cam_infos = []
    for idx, key in enumerate(cam_extrinsics):
        sys.stdout.write('\r')
        # the exact output you're looking for:
        sys.stdout.write("Reading camera {}/{}".format(idx+1, len(cam_extrinsics)))
        sys.stdout.flush()

        extr = cam_extrinsics[key]
        intr = cam_intrinsics[extr.camera_id]
        height = intr.height
        width = intr.width

        uid = intr.id
        R = np.transpose(qvec2rotmat(extr.qvec))
        T = np.array(extr.tvec)
        if intr.model == "SIMPLE_PINHOLE":
            focal_length = intr.params[0]
            cx = intr.params[1]
            cy = intr.params[2]
            FovY = focal2fov(focal_length, height)
            FovX = focal2fov(focal_length, width)
            K = np.array([[focal_length, 0, cx], [0, focal_length, cy], [0, 0, 1]]).astype(np.float32)
        elif intr.model == "PINHOLE":
            focal_length_x = intr.params[0]
            focal_length_y = intr.params[1]
            cx = intr.params[2]
            cy = intr.params[3]
            FovY = focal2fov(focal_length_y, height)
            FovX = focal2fov(focal_length_x, width)
            K = np.array([[focal_length_x, 0, cx], [0, focal_length_y, cy], [0, 0, 1]]).astype(np.float32)
        else:
            assert False, "Colmap camera model not handled: only undistorted datasets (PINHOLE or SIMPLE_PINHOLE cameras) supported!"

        ######### image_path = os.path.join(images_folder, os.path.basename(extr.name))
        image_path = os.path.join(images_folder, "images", extr.name)
        image_name = os.path.basename(image_path).split(".")[0]
        image = Image.open(image_path)

        ######### read mask
        mask_path = image_path.replace('images/', 'masks/').replace('.jpg', '.png')
        if os.path.exists(mask_path):
            mask = Image.open(mask_path).convert('1')
            # mask = np.array(mask)
        else:
            sys.stdout.write(f"[ERROR] Mask {mask_path} not found!\n")
            sys.stdout.flush()
            mask = None
        
        ######### read sky_mask
        metadata = {}
        segs_path = image_path.replace('images/', 'segs/').replace('.jpg', '.png')
        if os.path.exists(segs_path):
            semantic = get_semantics_from_path(segs_path)
            sky_mask = get_mask_tensors(semantic, [SemanticType.SKY.value])
            metadata['sky_mask'] = sky_mask.convert('1')
            ground_mask = get_mask_tensors(semantic, [SemanticType.GROUND.value])
            metadata['ground_mask'] = ground_mask.convert('1')
            # metadata['semantic'] = semantic
        else:
            sys.stdout.write(f"[ERROR] Segs {segs_path} not found!\n")
            sys.stdout.flush()

        ######### read obj_bound
        obj_bound_path = image_path.replace('images/', 'masks_obj/').replace('.jpg', '.png')
        if os.path.exists(obj_bound_path):
            mask_obj = Image.open(obj_bound_path).convert('1')
            mask_obj_array = np.logical_not(np.array(mask_obj))
            inverted_image = Image.fromarray(mask_obj_array)
            metadata['obj_bound'] = inverted_image
        else:
            sys.stdout.write(f"[ERROR] masks_obj {obj_bound_path} not found!\n")
            sys.stdout.flush()

        cam_info = CameraInfo(uid=uid, R=R, T=T, FovY=FovY, FovX=FovX, K=K, 
            image=image, image_path=image_path, image_name=image_name,
            width=width, height=height, mask=mask, metadata=metadata)
        cam_infos.append(cam_info)
    sys.stdout.write('\n')
    return cam_infos


def get_semantics_from_path(filepath: Path, scale_factor: float = 1.0):

    pil_image = Image.open(filepath)
    if scale_factor != 1.0:
        width, height = pil_image.size
        newsize = (int(width * scale_factor), int(height * scale_factor))
        pil_image = pil_image.resize(newsize, resample=Image.NEAREST)
    image = np.array(pil_image, dtype="int64")
    if len(image.shape) == 3:
        image = image[:, :, 0]
    semantics = np.zeros_like(image)
    semantics[(image == 7) + (image == 8) + (image == 13) + (image == 14) + (image == 23) + (image == 24)] = SemanticType.GROUND.value
    semantics[image == 27] = SemanticType.SKY.value
    semantics[image == 55] = SemanticType.OBJECT.value
    
    return semantics

def get_mask_tensors(semantics, mask_indices):
    if isinstance(mask_indices, List):
        mask_indices = torch.tensor(mask_indices, dtype=torch.int64).view(1, 1, -1)
        # Compute mask by summing over the matching mask indices
    semantics_tensor = torch.from_numpy(semantics).unsqueeze(-1)  # Convert back to a tensor for masking
    mask_tensor = torch.sum(semantics_tensor == mask_indices, dim=-1, keepdim=True) == 1
    mask = mask_tensor.squeeze(-1).numpy().astype(np.uint8) * 255  # Convert to binary mask (0 or 255)
    
    # Convert mask from numpy array to PIL image
    mask_pil = Image.fromarray(mask)
    
    return mask_pil


def readColmapSceneInfo(path, images='images', split_test=8, **kwargs):
    ############### colmap_basedir = os.path.join(path, 'sparse/0')
    colmap_basedir = os.path.join(path, 'colmap/triangulated/sparse/model/')
    if not os.path.exists(colmap_basedir):
        colmap_basedir = os.path.join(path, 'sparse')
    try:
        cameras_extrinsic_file = os.path.join(colmap_basedir, "images.bin")
        cameras_intrinsic_file = os.path.join(colmap_basedir, "cameras.bin")
        cam_extrinsics = read_extrinsics_binary(cameras_extrinsic_file)
        cam_intrinsics = read_intrinsics_binary(cameras_intrinsic_file)
    except:
        cameras_extrinsic_file = os.path.join(colmap_basedir, "images.txt")
        cameras_intrinsic_file = os.path.join(colmap_basedir, "cameras.txt")
        cam_extrinsics = read_extrinsics_text(cameras_extrinsic_file)
        cam_intrinsics = read_intrinsics_text(cameras_intrinsic_file)

    reading_dir = images
    cam_infos_unsorted = readColmapCameras(
        cam_extrinsics=cam_extrinsics, 
        cam_intrinsics=cam_intrinsics, 
        data_folder=path
    )
    cam_infos = sorted(cam_infos_unsorted.copy(), key = lambda x : x.image_name)

    if split_test == -1:
        train_cam_infos = cam_infos
        test_cam_infos = []
    else:
        train_cam_infos = [c for idx, c in enumerate(cam_infos) if idx % split_test != 0]
        test_cam_infos = [c for idx, c in enumerate(cam_infos) if idx % split_test == 0]

    nerf_normalization = getNerfppNorm(train_cam_infos)

    ply_path = os.path.join(colmap_basedir, "points3D.ply")
    bin_path = os.path.join(colmap_basedir, "points3D.bin")
    txt_path = os.path.join(colmap_basedir, "points3D.txt")
    if not os.path.exists(ply_path):
        print("Converting point3d.bin to .ply, will happen only the first time you open the scene.")
        try:
            xyz, rgb, _ = read_points3D_binary(bin_path)
        except:
            xyz, rgb, _ = read_points3D_text(txt_path)
        storePly(ply_path, xyz, rgb)
    try:
        pcd = fetchPly(ply_path)
    except:
        pcd = None

    scene_info = SceneInfo(point_cloud=pcd,
                           train_cameras=train_cam_infos,
                           test_cameras=test_cam_infos,
                           nerf_normalization=nerf_normalization,
                           ply_path=ply_path)
    return scene_info