from lib.utils.xpeng_utils import generate_dataparser_outputs
from lib.utils.xpeng_utils import get_image_mask_tensor_from_path
from lib.utils.xpeng_utils import _label2camera
from lib.utils.graphics_utils import focal2fov, BasicPointCloud
from lib.utils.data_utils import get_val_frames
from lib.datasets.base_readers import CameraInfo, SceneInfo, getNerfppNorm, fetchPly, get_Sphere_Norm, fetchGroundSurfelPly, fetchG3RPly
from lib.config import cfg
from lib.config.yacs import CfgNode as CN
from tqdm import tqdm
from PIL import Image
from copy import deepcopy
import os
import numpy as np
import sys
import shutil
import time

sys.path.append(os.getcwd())
current_dir = os.path.dirname(__file__) 
root_path = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
sys.path.extend([root_path])

def readXpengFullInfo(path, images='images', split_train=-1, split_test=-1, **kwargs):
    # copy input ply to model output folder
    shutil.copytree(
        os.path.join(cfg.source_path, 'input_ply'), os.path.join(cfg.model_path, 'input_ply'), dirs_exist_ok=True
    )
    shutil.copyfile(
        os.path.join(cfg.source_path, 'ground_mask.npy'), os.path.join(cfg.model_path, 'ground_mask.npy')
    )
    if cfg.data.get('use_surfel', True):
        shutil.copytree(
            os.path.join(cfg.source_path, 'surfel_ground'), os.path.join(cfg.model_path, 'surfel_ground'), 
            dirs_exist_ok=True
        )
    if cfg.data.get('use_g3r_ground_init', True):
        shutil.copytree(
            os.path.join(cfg.source_path, 'g3r_ground'), os.path.join(cfg.model_path, 'g3r_ground'), 
            dirs_exist_ok=True
        )

    selected_frames = cfg.data.get('selected_frames', None)
    selected_cameras = cfg.data.get('cameras', [1, 2, 3, 4, 5, 6, 7])
    frame_stride = cfg.data.get('frame_stride', 1)
        
    bkgd_ply_path = os.path.join(cfg.model_path, 'input_ply/points3D_bkgd.ply')
    assert os.path.exists(bkgd_ply_path), f"[ERROR] Background ply {bkgd_ply_path} not exists!"

    output = generate_dataparser_outputs(
        datadir=path, 
        selected_frames=selected_frames,
        cameras=selected_cameras,
        frame_stride=frame_stride
    )
    if cfg.train_xpeng.get('phase2_novel_depth', False):
        # generate novel camera infos
        from lib.utils.xpeng_novel_utils import generate_novel_dataparser_outputs
        output_novel = generate_novel_dataparser_outputs(
            datadir=path, 
            start_frame=output['start_frame'], end_frame=output['end_frame'],
            timestamps=output['timestamps'],
            cameras=selected_cameras,
            frame_stride=frame_stride
        )

    anchor_pose = output['anchor_pose']
    exts = output['exts']
    ixts = output['ixts']
    poses = output['poses']
    c2ws = output['c2ws']
    image_filenames = output['image_filenames']
    obj_tracklets = output['obj_tracklets']
    obj_tracklets_world = output['obj_tracklets_world']
    obj_info = output['obj_info']
    frames, cams = output['frames'], output['cams']
    frames_idx = output['frames_idx']
    num_frames = output['num_frames']
    cams_timestamps = output['cams_timestamps']
    tracklet_timestamps = output['tracklet_timestamps']
    obj_bounds = output['obj_bounds']
    obj_bounds_for_static_scene = output['obj_bounds_for_static_scene']
    train_frames, test_frames = get_val_frames(
        num_frames, 
        test_every=split_test if split_test > 0 else None,
        train_every=split_train if split_train > 0 else None,
    )

    scene_metadata = dict()
    scene_metadata['obj_tracklets'] = obj_tracklets
    scene_metadata['obj_tracklets_world'] = obj_tracklets_world
    scene_metadata['tracklet_timestamps'] = tracklet_timestamps
    scene_metadata['obj_meta'] = obj_info
    scene_metadata['num_images'] = len(exts)
    scene_metadata['num_cams'] = len(cfg.data.cameras)
    scene_metadata['num_frames'] = num_frames
    scene_metadata['origin_ego_pose'] = poses
    
    camera_timestamps = dict()
    for cam in selected_cameras:
        cam_name = _label2camera[cam]
        camera_timestamps[cam_name] = dict()
        camera_timestamps[cam_name]['train_timestamps'] = []
        camera_timestamps[cam_name]['test_timestamps'] = []      

    ########################################################################################################################
    camera_wh = dict()
    cam_infos = []
    for i in tqdm(range(len(exts))):
        # generate pose and image
        ext = exts[i]
        ixt = ixts[i]
        c2w = c2ws[i]
        pose = poses[i]
        image_path = image_filenames[i]
        image_name = os.path.basename(image_path).split('.')[0]
        calibrations = output['calibrations']
        cam_name = cams[i]

        # width, height = image.size
        width, height = calibrations['new'+cam_name]['width'], calibrations['new'+cam_name]['height']
        fx, fy = ixt[0, 0], ixt[1, 1]
        FovY = focal2fov(fy, height)
        FovX = focal2fov(fx, width)    
        
        if cam_name not in camera_wh:
            camera_wh[cam_name] = (width, height)

        RT = np.linalg.inv(c2w)
        R = RT[:3, :3].T
        T = RT[:3, 3]
        K = ixt.copy()
        
        metadata = dict()
        metadata['anchor_pose'] = anchor_pose
        metadata['frame'] = frames[i]
        metadata['cam'] = cam_name
        metadata['frame_idx'] = frames_idx[i]
        metadata['ego_pose'] = pose
        metadata['extrinsic'] = ext
        metadata['timestamp'] = cams_timestamps[i]
        metadata['c2w'] = c2w

        if frames_idx[i] in train_frames:
            metadata['is_val'] = False
            camera_timestamps[cam_name]['train_timestamps'].append(cams_timestamps[i])
        else:
            metadata['is_val'] = True
            camera_timestamps[cam_name]['test_timestamps'].append(cams_timestamps[i])

        # ============================== Optional load novel cameras
        if cfg.train_xpeng.get('phase2_novel_depth', False):
            from lib.utils.xpeng_novel_utils import generate_novel_camera_info
            novel_metadata = deepcopy(metadata)
            novel_metadata['ego_pose'] = output['poses'][i]
            R_novel, T_novel, novel_metadata = generate_novel_camera_info(
                path, novel_metadata, output_novel, i, cam_name, image_name)
            novel_cam_info = CameraInfo(
                uid=i, R=R_novel, T=T_novel, FovY=FovY, FovX=FovX, K=K,
                image=None, image_path=image_path, image_name=image_name,
                width=width, height=height, mask=None,
                metadata=novel_metadata
            )
            metadata['novel_camera'] = novel_cam_info

        # ============================== load dynamic mask
        metadata['obj_bound'] = Image.fromarray(obj_bounds[i])
        metadata['obj_bound_for_static_scene'] = Image.fromarray(obj_bounds_for_static_scene[i])

        # ============================== load sky and ground mask
        seg_mask_dir = os.path.join(path, 'segs')
        seg_mask_path = os.path.join(seg_mask_dir, cam_name, f'{image_name}.png')
        metadata['seg_mask_path'] = seg_mask_path
                            
        # ============================== Optional: load lidar depth
        depth_path = os.path.join(path, 'depth', cam_name, f'{image_name}.npy')
        if cfg.optim.lambda_depth_lidar > 0:
            assert os.path.exists(depth_path), f"[ERROR] Lidar depth {depth_path} not exists!"
            metadata['lidar_depth_path'] = depth_path

        # ============================== Optional: load monocular normal
        mono_normal_dir = os.path.join(path, 'mono_normal')
        if cfg.data.use_mono_normal:
            mono_normal_path = os.path.join(mono_normal_dir, cam_name, f'{image_name}.npy')
            metadata['mono_normal_path'] = mono_normal_path

        normal_pcd_dir = os.path.join(path, 'normal_pcd')
        normal_pcd_path = os.path.join(normal_pcd_dir, cam_name, f'{image_name}.npy')
        if cfg.data.use_lidar_normal:
            assert os.path.exists(normal_pcd_path), f"[ERROR] Lidar normal {normal_pcd_path} not exists!"
            metadata['normal_pcd_path'] = normal_pcd_path

        # ============================== load ego mask
        mask_path = os.path.join(path, "masks", cam_name, f'{image_name}.png')
        # mask = get_image_mask_tensor_from_path(mask_path)  
        
        cam_info = CameraInfo(
            uid=i, RT=RT, R=R, T=T, FovY=FovY, FovX=FovX, K=K,
            image=None, image_path=image_path, image_name=image_name,
            width=width, height=height, 
            mask=None,
            mask_path=mask_path,
            metadata=metadata)
        cam_infos.append(cam_info)

    train_cam_infos = [cam_info for cam_info in cam_infos if not cam_info.metadata['is_val']]
    test_cam_infos = [cam_info for cam_info in cam_infos if cam_info.metadata['is_val']]
    
    for cam in selected_cameras:
        cam_name = _label2camera[cam]
        camera_timestamps[cam_name]['train_timestamps'] = sorted(camera_timestamps[cam_name]['train_timestamps'])
        camera_timestamps[cam_name]['test_timestamps'] = sorted(camera_timestamps[cam_name]['test_timestamps'])
    scene_metadata['camera_timestamps'] = camera_timestamps
        
    novel_view_cam_infos = []
    
    #######################################################################################################################3
    # Get scene extent
    # 1. Default nerf++ setting

    if cfg.mode == 'novel_view':
        nerf_normalization = getNerfppNorm(novel_view_cam_infos)
    else:
        nerf_normalization = getNerfppNorm(train_cam_infos)

    # 2. The radius we obtain should not be too small (larger than 10 here)
    nerf_normalization['radius'] = max(nerf_normalization['radius'], 10)
    
    # 3. If we have extent set in config, we ignore previous setting
    if cfg.data.get('extent', False):
        nerf_normalization['radius'] = cfg.data.extent
    
    # 4. We write scene radius back to config
    cfg.data.extent = float(nerf_normalization['radius'])

    # 5. We write scene center and radius to scene metadata    
    scene_metadata['scene_center'] = nerf_normalization['center']
    scene_metadata['scene_radius'] = nerf_normalization['radius']
    print(f'Scene radius: {nerf_normalization["radius"]}')

    # Get sphere center
    sphere_pcd: BasicPointCloud = fetchPly(bkgd_ply_path)
    
    sphere_normalization = get_Sphere_Norm(sphere_pcd.points)
    scene_metadata['sphere_center'] = sphere_normalization['center']
    scene_metadata['sphere_radius'] = sphere_normalization['radius']
    print(f'Sphere radius: {sphere_normalization["radius"]}')

    point_cloud: BasicPointCloud = sphere_pcd

    point_cloud_dict = dict()
    if cfg.model.nsg.include_ground:
        ground_mask = np.load(os.path.join(cfg.model_path, 'ground_mask.npy'))
        scene_metadata['ground_mask'] = ground_mask
        point_cloud_dict['background'] = point_cloud[~ground_mask.astype(bool).flatten()]

        if cfg.data.get('use_g3r_ground_init', True):
            point_cloud_dict['ground'] = fetchG3RPly(os.path.join(cfg.model_path, 'g3r_ground/g3r_ground.ply'))
        elif cfg.data.get('use_surfel', True):
            grd_surfel_path = os.path.join(cfg.model_path, 'surfel_ground/ground_surfel.ply')
            point_cloud_dict['ground'] = fetchGroundSurfelPly(grd_surfel_path)
        else:
            point_cloud_dict['ground'] = point_cloud[ground_mask.astype(bool).flatten()]
            if cfg.data.input_ground_downsample > 1e-8:
                point_cloud_dict['ground'] = point_cloud_dict['ground'].downsample(cfg.data.input_ground_downsample)

    else:
        point_cloud = point_cloud.downsample(0.1)
        point_cloud_dict['background'] = point_cloud
        point_cloud_dict['ground'] = None

    scene_info = SceneInfo(
        point_cloud_dict=point_cloud_dict,
        train_cameras=train_cam_infos,
        test_cameras=test_cam_infos,
        nerf_normalization=nerf_normalization,
        ply_path=bkgd_ply_path,
        metadata=scene_metadata,
        novel_view_cameras=novel_view_cam_infos,
    )
    
    ### write the preprocess results back to cfg
    cfg.results = CN()
    cfg.results.scene_center = scene_metadata['scene_center'].tolist()
    cfg.results.scene_radius = float(scene_metadata['scene_radius'])
    cfg.results.sphere_center = scene_metadata['sphere_center'].tolist()
    cfg.results.sphere_radius = float(scene_metadata['sphere_radius'])
    cfg.results.anchor_pose = anchor_pose.tolist()
    cfg.results.intrinsics = [i.tolist() for i in output['intrinsics']]
    cfg.results.extrinsics = [i.tolist() for i in output['extrinsics']]
    cfg.results.timestamps = output['timestamps']
    cfg.results.timestamp_offset = output['timestamp_offset']
    cfg.results.camera_wh = CN(camera_wh)
    cfg.results.annotations = CN(output['annotations'])
    cfg.results.ego_frame_poses = output['ego_frame_poses'].tolist()
    return scene_info
    
