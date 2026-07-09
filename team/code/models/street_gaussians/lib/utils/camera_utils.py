import numpy as np
import torch
import copy
import torch.nn as nn
import cv2
import math
import copy
import time
import gc
import os
from PIL import Image
from tqdm import tqdm
from lib.utils.xpeng_utils import get_mask_from_semantics, get_semantics_from_path, get_image_mask_tensor_from_path
from lib.utils.general_utils import PILtoTorch, NumpytoTorch, matrix_to_quaternion
from lib.utils.graphics_utils import fov2focal, getProjectionMatrix, getWorld2View, getWorld2View2, getProjectionMatrixK
from lib.datasets.base_readers import CameraInfo
from lib.config import cfg
from lib.config.globals import SemanticType
from lib.utils.homography_utils import generate_image_shift, generate_image_rotation
from diff_gaussian_rasterization import GaussianRasterizationSettings, GaussianRasterizer

# if training, put everything to cuda
# image_to_cuda = (cfg.mode == 'train') 

class Camera(nn.Module):
    def __init__(
        self, 
        id,
        RT, R, T, 
        FoVx, FoVy, K,
        image, image_name, 
        trans = np.array([0.0, 0.0, 0.0]), 
        scale = 1.0,
        metadata = dict(),
        masks = dict(),
        height=None, width=None, c2anchor=None, to_cuda=True
    ):
        if image is not None:
            super(Camera, self).__init__()

        self.id = id
        self.RT = torch.from_numpy(RT).float()
        self.R = R
        self.T = T
        self.FoVx = FoVx
        self.FoVy = FoVy
        self.K = K
        self.image_name = image_name
        self.trans, self.scale = trans, scale

        self.novel_view = False

        # meta and mask
        self.meta = metadata
        for name, mask in masks.items():
            setattr(self, name, mask)
        
        if image is not None:
            self.original_image = image.clamp(0, 1)                
            self.image_height, self.image_width = self.original_image.shape[1], self.original_image.shape[2]
        elif height is not None and width is not None:
            self.image_height, self.image_width = height, width
            self.original_image = None
        else:
            raise ValueError("Either image or height and width must be provided for Camera initialization.")
        
        self.zfar = 1000.0
        self.znear = 0.001
        self.world_view_transform = torch.tensor(getWorld2View2(R, T, trans, scale)).transpose(0, 1)
        
        if self.K is not None:
            self.projection_matrix = getProjectionMatrixK(znear=self.znear, zfar=self.zfar, K=self.K, H=self.image_height, W=self.image_width).transpose(0,1)
            self.K = torch.from_numpy(self.K).float()
        else:
            self.projection_matrix = getProjectionMatrix(znear=self.znear, zfar=self.zfar, fovX=self.FoVx, fovY=self.FoVy).transpose(0,1)

        if image is not None:
            self.full_proj_transform = (self.world_view_transform.unsqueeze(0).bmm(self.projection_matrix.unsqueeze(0))).squeeze(0)
            self.camera_center = self.world_view_transform.inverse()[3, :3]
        else:
            self.full_proj_transform = self.world_view_transform @ self.projection_matrix
            self.camera_center = torch.Tensor(c2anchor[:3, 3])
        
        if 'ego_pose' in self.meta.keys():
            self.ego_pose = torch.from_numpy(self.meta['ego_pose']).float()
            self.ego_pose_rot = matrix_to_quaternion(self.ego_pose[:3, :3].unsqueeze(0)).squeeze(0)
            del self.meta['ego_pose']

        # metadata['ego_pose_smoothed']
        if 'ego_pose_smoothed' in self.meta.keys():
            self.ego_pose_smoothed = torch.from_numpy(self.meta['ego_pose_smoothed']).float()
            self.ego_pose_smoothed_rot = matrix_to_quaternion(self.ego_pose_smoothed[:3, :3].unsqueeze(0)).squeeze(0)
            del self.meta['ego_pose_smoothed']

        if 'extrinsic' in self.meta.keys():
            self.extrinsic = torch.from_numpy(self.meta['extrinsic']).float()
            del self.meta['extrinsic']

        if to_cuda:
            self.to_cuda()
    
    def to_cuda(self):
        self.world_view_transform = self.world_view_transform.cuda()
        self.projection_matrix = self.projection_matrix.cuda()
        self.full_proj_transform = self.full_proj_transform.cuda()
        self.camera_center = self.camera_center.cuda()
        self.RT = self.RT.cuda()
        if hasattr(self, 'K'):
            self.K = self.K.cuda()
        if hasattr(self, 'original_image') and self.original_image is not None:
            self.original_image = self.original_image.cuda()
        if hasattr(self, 'ego_pose'):
            self.ego_pose = self.ego_pose.cuda()
            self.ego_pose_rot = self.ego_pose_rot.cuda()
        if hasattr(self, 'ego_pose_smoothed'):
            self.ego_pose_smoothed = self.ego_pose_smoothed.cuda()
            self.ego_pose_smoothed_rot = self.ego_pose_smoothed_rot.cuda()
        if hasattr(self, 'extrinsic'):
            self.extrinsic = self.extrinsic.cuda()

    def set_extrinsic(self, c2w):
        w2c = np.linalg.inv(c2w)
        R = w2c[:3, :3].T
        T = w2c[:3, 3]
        
        # set R, T
        self.R = R
        self.T = T
        
        # change attributes associated with R, T
        self.world_view_transform = torch.tensor(getWorld2View2(R, T, self.trans, self.scale)).transpose(0, 1).cuda()
        self.full_proj_transform = (self.world_view_transform.unsqueeze(0).bmm(self.projection_matrix.unsqueeze(0))).squeeze(0)
        self.camera_center = self.world_view_transform.inverse()[3, :3]
    
    def set_intrinsic(self, K):
        self.K = torch.from_numpy(K).float().cuda()
        self.projection_matrix = getProjectionMatrixK(znear=self.znear, zfar=self.zfar, K=self.K, H=self.image_height, W=self.image_width).transpose(0,1).cuda()
        self.full_proj_transform = (self.world_view_transform.unsqueeze(0).bmm(self.projection_matrix.unsqueeze(0))).squeeze(0)
    
    def set_image(self, image):
        self.original_image = image

    def set_masks(self, masks):
        for name, mask in masks.items():
            setattr(self, name, mask)
    
    def set_novel_view(self):
        self.novel_view = True

    def get_extrinsic(self):
        w2c = np.eye(4)
        w2c[:3, :3] = self.R.T
        w2c[:3, 3] = self.T
        c2w = np.linalg.inv(w2c)
        return c2w
    
    def get_intrinsic(self):
        ixt = self.K.cpu().numpy()
        return ixt
    
        
class MiniCam:
    def __init__(self, width, height, fovy, fovx, znear, zfar, world_view_transform, full_proj_transform):
        self.image_width = width
        self.image_height = height    
        self.FoVy = fovy
        self.FoVx = fovx
        self.znear = znear
        self.zfar = zfar
        self.world_view_transform = world_view_transform
        self.full_proj_transform = full_proj_transform
        view_inv = torch.inverse(self.world_view_transform)
        self.camera_center = view_inv[3][:3]


def loadmask(cam_info: CameraInfo, resolution, resize_mode):
    masks = dict()
    if cfg.source_type == 'vision':
        masks['original_mask'] = torch.ones((1, cam_info.height, cam_info.width)).bool()
    else:
        mask = get_image_mask_tensor_from_path(cam_info.mask_path)  
        if mask is not None:
            if type(mask) == torch.Tensor:
                masks['original_mask'] = torch.permute(mask, (2, 0, 1))
            else:
                masks['original_mask'] = PILtoTorch(mask, resolution, resize_mode=resize_mode).clamp(0, 1).bool()
        
            if cfg.dilate_mask > 0:
                kernel = np.ones((cfg.dilate_mask, cfg.dilate_mask), np.uint8) 
                inverted_original_mask = ~(masks['original_mask'][0].cpu().numpy())
                t1 = time.time()
                # inverted_dilated_mask = binary_dilation(inverted_original_mask, structure=kernel)
                inverted_dilated_mask = cv2.dilate(inverted_original_mask.astype(np.uint8), kernel, iterations=1).astype(bool)
                masks['original_mask'] = torch.tensor(~inverted_dilated_mask).unsqueeze(0).bool()
                # print(f"[Loader] Dilated mask of {cam_info.metadata['cam']} in {time.time() - t1:.2f} seconds")

    if cam_info.acc_mask is not None:
        masks['original_acc_mask'] = PILtoTorch(cam_info.acc_mask, resolution, resize_mode=resize_mode).clamp(0, 1).bool()

    if 'obj_bound' in cam_info.metadata:
        masks['original_obj_bound'] = PILtoTorch(cam_info.metadata['obj_bound'], resolution, resize_mode=resize_mode).clamp(0, 1).bool()
        del cam_info.metadata['obj_bound']
    if 'obj_bound_for_static_scene' in cam_info.metadata:
        masks['original_obj_bound_for_static_scene'] = PILtoTorch(cam_info.metadata['obj_bound_for_static_scene'], resolution, resize_mode=resize_mode).clamp(0, 1).bool()
        del cam_info.metadata['obj_bound_for_static_scene']
    

    return masks


def loadmetadata(metadata, resolution):
    output = copy.deepcopy(metadata)

    # semantic, commented since memory issue
    if 'semantic' in metadata:
        output['semantic'] = NumpytoTorch(metadata['semantic'], resolution, resize_mode=Image.NEAREST)
    elif 'semantics' in metadata:
        output['semantic'] = metadata['semantics']
    
    # lidar_depth
    if 'lidar_depth' in metadata:
        output['lidar_depth'] = NumpytoTorch(metadata['lidar_depth'], resolution, resize_mode=Image.NEAREST)
    
    # lidar_normal
    if 'lidar_normal' in metadata:
        output['lidar_normal'] = NumpytoTorch(metadata['lidar_normal'], resolution, resize_mode=Image.NEAREST)
        cfg.render.render_normal = True

    # mono depth
    if 'mono_depth' in metadata:
        output['mono_depth'] = NumpytoTorch(metadata['mono_depth'], resolution, resize_mode=Image.NEAREST)
        
    # mono normal
    if 'mono_normal' in metadata:
        output['mono_normal'] = NumpytoTorch(metadata['mono_normal'], resolution, resize_mode=Image.NEAREST)
        cfg.render.render_normal = True
        
    return output
        
        
WARNED = False
def loadCam(cam_info: CameraInfo, resolution_scale):
    orig_w, orig_h = cam_info.image.size
    if cfg.resolution in [1, 2, 4, 8]:
        scale = resolution_scale * cfg.resolution
        resolution = round(orig_w / scale), round(orig_h / scale)
    else:  # should be a type that converts to float
        if cfg.resolution == -1:
            if orig_w > 1600:
                global WARNED
                if not WARNED:
                    print("[ INFO ] Encountered quite large input images (>1.6K pixels width), rescaling to 1.6K.\n "
                        "If this is not desired, please explicitly specify '--resolution/-r' as 1")
                    WARNED = True
                global_down = orig_w / 1600
            else:
                global_down = 1
        else:
            global_down = orig_w / cfg.resolution

        scale = float(global_down) * float(resolution_scale)
        resolution = (int(orig_w / scale), int(orig_h / scale))

    K = copy.deepcopy(cam_info.K)
    K[:2] /= scale

    image = PILtoTorch(cam_info.image, resolution, resize_mode=Image.BILINEAR)[:3, ...]
    masks = loadmask(cam_info, resolution, resize_mode=Image.NEAREST)
    metadata = loadmetadata(cam_info.metadata, resolution)

    if cfg.train_xpeng.get('phase2_novel_depth', False):
        novel_cam_info = cam_info.metadata['novel_camera']
        novel_cam = Camera(
            id=cam_info.uid, 
            R=novel_cam_info.R, 
            T=novel_cam_info.T, 
            FoVx=novel_cam_info.FovX, 
            FoVy=novel_cam_info.FovY, 
            K=K,
            image=image, 
            masks={},
            image_name=cam_info.image_name, 
            metadata=novel_cam_info.metadata,
        )
        metadata['novel_camera'] = novel_cam
    
    return Camera(
        id=cam_info.uid, 
        RT=cam_info.RT,
        R=cam_info.R, 
        T=cam_info.T, 
        FoVx=cam_info.FovX, 
        FoVy=cam_info.FovY, 
        K=K,
        image=image, 
        masks=masks,
        image_name=cam_info.image_name, 
        metadata=metadata,
    )


def load_camera_on_demand(cam_info: CameraInfo, resolution_scale):
    newmetadata = copy.deepcopy(cam_info.metadata)

    cam_info_image = Image.open(cam_info.image_path)
    orig_w, orig_h = cam_info_image.size
    scale = resolution_scale * cfg.resolution
    resolution = round(orig_w / scale), round(orig_h / scale)

    K = copy.deepcopy(cam_info.K)
    K[:2] /= scale

    # ====== load semantic ======
    seg_mask_path = cam_info.metadata.get('seg_mask_path', None)
    newmetadata['semantic'] = get_semantics_from_path(seg_mask_path)

    # ====== load lidar depth ======
    if "lidar_depth_path" in cam_info.metadata:
        depth = np.load(cam_info.metadata['lidar_depth_path'], allow_pickle=True)
        depth = dict(depth.item())
        mask = depth['mask']
        value = depth['value']
        depth = np.zeros_like(mask).astype(np.float32)
        depth[mask] = value
        if cfg.data.use_lidar_slice_depth:
            depth_pcd_path = cam_info.metadata['lidar_depth_path'].replace('depth', 'depth_pcd')
            depth_pcd = dict(np.load(depth_pcd_path, allow_pickle=True).item())
            mask = depth_pcd['mask']
            value = depth_pcd['value']
            depth_pcd = np.zeros_like(mask).astype(np.float32)
            depth_pcd[mask] = value
            roadside_mask = get_mask_from_semantics(
                newmetadata['semantic'], SemanticType.ROADSIDE).squeeze(2).cpu().numpy()
            depth[roadside_mask] = depth_pcd[roadside_mask]
        newmetadata['lidar_depth'] = depth

    # ====== load lidar normal ======
    if 'mono_normal_path' in cam_info.metadata:
        newmetadata['mono_normal'] = np.load(cam_info.metadata['mono_normal_path'])
    if 'normal_pcd_path' in cam_info.metadata:
        lidar_normal = np.load(cam_info.metadata['normal_pcd_path'], allow_pickle=True)
        lidar_normal = dict(lidar_normal.item())
        mask = lidar_normal['mask']
        value = lidar_normal['value']
        lidar_normal = np.zeros((mask.shape[0], mask.shape[1], 3)).astype(np.float32)
        lidar_normal[mask] = value
        newmetadata['lidar_normal'] = lidar_normal

    # convert image to tensor
    image = PILtoTorch(cam_info_image, resolution, resize_mode=Image.BILINEAR)[:3, ...]
    masks = loadmask(cam_info, resolution, resize_mode=Image.NEAREST)
    masks['original_semantic'] = newmetadata['semantic']
    del newmetadata['semantic']
    metadata = loadmetadata(newmetadata, resolution)

    if cfg.train_xpeng.get('phase2_novel_depth', False):
        novel_cam_info = cam_info.metadata['novel_camera']
        novel_cam = Camera(
            id=cam_info.uid, 
            R=novel_cam_info.R, 
            T=novel_cam_info.T, 
            FoVx=novel_cam_info.FovX, 
            FoVy=novel_cam_info.FovY, 
            K=K,
            image=image, 
            masks={},
            image_name=cam_info.image_name, 
            metadata=novel_cam_info.metadata,
        )
        metadata['novel_camera'] = novel_cam
    
    return Camera(
        id=cam_info.uid, 
        RT=cam_info.RT,
        R=cam_info.R, 
        T=cam_info.T, 
        FoVx=cam_info.FovX, 
        FoVy=cam_info.FovY, 
        K=K,
        image=image, 
        masks=masks,
        image_name=cam_info.image_name, 
        metadata=metadata,
        to_cuda=False
    )


def cameraList_from_camInfos(cam_infos, resolution_scale):
    camera_list = []
    cams = dict()
    total_cams = len(cam_infos)
    for i, cam_info in tqdm(enumerate(cam_infos)):
        camera_list.append(loadCam(cam_info, resolution_scale))
        cams[cam_info.metadata['cam']] = True
        del cam_info
        gc.collect()
        if cfg.debug and len(camera_list) > 10 and 'cam2' in cams:
            break
        print(f"[INFO] Loaded {i+1} cameras out of {total_cams}")
    return camera_list


def cameraList_generated_cams(cam_infos, resolution_scale):
    camera_list = []
    novel_camera_lists = ["cam0", "cam1", "cam2", "cam3", "cam4", "cam5", "cam6", "cam7"]
    for i, cam_info in tqdm(enumerate(cam_infos)):
        camera = loadCam(cam_info, resolution_scale)
        camera_list.append(camera)

        if camera.meta["cam"] in novel_camera_lists:
            novel_camera_shift = copy.deepcopy(camera)
            novel_image_shift, novel_mask_shift, novel_c2w = generate_image_shift(novel_camera_shift, cfg.train.max_shift_distance)
            masks_shift = {}
            masks_shift["original_mask"] = novel_mask_shift
            novel_camera_shift.set_extrinsic(novel_c2w)
            novel_camera_shift.set_image(novel_image_shift)
            novel_camera_shift.set_masks(masks_shift)
            novel_camera_shift.set_novel_view()
            camera_list.append(novel_camera_shift)

            novel_camera_rotation = copy.deepcopy(camera)
            novel_image_rotation, novel_mask_rotation, novel_c2w = generate_image_rotation(novel_camera_rotation, cfg.train.max_yaw_degree)
            masks_rotation = {}
            masks_rotation["original_mask"] = novel_mask_rotation
            novel_camera_rotation.set_extrinsic(novel_c2w)
            novel_camera_rotation.set_image(novel_image_rotation)
            novel_camera_rotation.set_masks(masks_rotation)
            novel_camera_rotation.set_novel_view()
            camera_list.append(novel_camera_rotation)

    return camera_list

def camera_to_JSON(id, camera: CameraInfo):
    Rt = np.zeros((4, 4))
    Rt[:3, :3] = camera.R.transpose()
    Rt[:3, 3] = camera.T
    Rt[3, 3] = 1.0

    W2C = np.linalg.inv(Rt)
    pos = W2C[:3, 3]
    rot = W2C[:3, :3]
    serializable_array_2d = [x.tolist() for x in rot]
    camera_entry = {
        'id' : id,
        'img_name' : camera.image_name,
        'width' : camera.width,
        'height' : camera.height,
        'position': pos.tolist(),
        'rotation': serializable_array_2d,
        'fy' : fov2focal(camera.FovY, camera.height),
        'fx' : fov2focal(camera.FovX, camera.width)
    }
    return camera_entry

def make_rasterizer(
    viewpoint_camera: Camera,
    active_sh_degree = 0,
    bg_color = None,
    scaling_modifier = None,
):
    if bg_color is None:
        bg_color = [1, 1, 1] if cfg.data.white_background else [0, 0, 0]
        bg_color = torch.tensor(bg_color).float().cuda()
    if scaling_modifier is None:
        scaling_modifier = cfg.render.scaling_modifier
    debug = cfg.render.debug
    
    # Set up rasterization configuration
    tanfovx = math.tan(viewpoint_camera.FoVx * 0.5)
    tanfovy = math.tan(viewpoint_camera.FoVy * 0.5)

    raster_settings = GaussianRasterizationSettings(
        image_height=int(viewpoint_camera.image_height),
        image_width=int(viewpoint_camera.image_width),
        tanfovx=tanfovx,
        tanfovy=tanfovy,
        bg=bg_color,
        scale_modifier=scaling_modifier,
        viewmatrix=viewpoint_camera.world_view_transform,
        projmatrix=viewpoint_camera.full_proj_transform,
        sh_degree=active_sh_degree,
        campos=viewpoint_camera.camera_center,
        prefiltered=False,
        debug=debug,
    )    
            
    rasterizer: GaussianRasterizer = GaussianRasterizer(raster_settings=raster_settings)
    return rasterizer
