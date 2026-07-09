import os
import numpy as np
import time
import math
from tqdm import tqdm
from argparse import Namespace
from random import randint
from torch.utils.data import DataLoader

from lib.models.street_gaussian_renderer import StreetGaussianRenderer
from lib.models.street_gaussian_model import StreetGaussianModel
from lib.models.scene import Scene
from lib.models.appearance_network import decouple_appearance
from lib.utils.loss_utils import l1_loss, l2_loss, psnr, ssim, get_faiss_index
from lib.utils.general_utils import safe_state
from lib.utils.cfg_utils import save_cfg
from lib.utils.img_utils import save_img_torch, visualize_depth_numpy
from lib.utils.sim_utils import save_scene_info, edit_ground_gaussians, edit_background_gaussians
from lib.utils.system_utils import searchForMaxIteration, cleanup_clip_folder
from lib.utils.eval_utils import EvaluatorInTrainer
from lib.utils.xpeng_utils import get_mask_from_semantics
from lib.utils.xpeng_novel_utils import render_camera_downwards
from lib.config.globals import SemanticType
from lib.datasets.dataset import Dataset, CameraDataset
from lib.config import cfg
import torch
import gc


try:
    from torch.utils.tensorboard import SummaryWriter
    TENSORBOARD_FOUND = True
except ImportError:
    TENSORBOARD_FOUND = False


def training_xpeng():
    training_args = cfg.train
    training_xpeng_args = cfg.train_xpeng
    optim_args = cfg.optim
    data_args = cfg.data

    start_iter = 0
    state_dict = None
    cleanup_clip_folder(cfg.source_path)
    t_start = time.time()

    tb_writer = prepare_output_and_logger()
    dataset = Dataset(load_cameras=True)
    try:
        if cfg.loaded_iter == -1:
            loaded_iter = searchForMaxIteration(cfg.trained_model_dir)
        else:
            loaded_iter = cfg.loaded_iter
        ckpt_path = os.path.join(cfg.trained_model_dir, f'iteration_{loaded_iter}.pth')
        state_dict = torch.load(ckpt_path)
        start_iter = state_dict['iter']
        print(f'[INFO] Loading model from {ckpt_path}', flush=True)
    except Exception as e:
        print(f'[Warning] Loading model failed: {e}. Training from the scratch', flush=True)

    save_cfg(cfg, cfg.model_path, epoch=start_iter)
    save_scene_info(cfg.source_path, cfg.model_path, cfg.save_misc)
    iteration = start_iter
    print(f'[INFO] Starting from {start_iter}', flush=True)

    gaussians = StreetGaussianModel(dataset.scene_info.metadata)
    scene = Scene(gaussians=gaussians, dataset=dataset)

    gaussians.training_setup()
    if state_dict is not None:
        gaussians.load_state_dict(state_dict)
        state_dict = None
    gaussians_renderer = StreetGaussianRenderer()

    evaluator = EvaluatorInTrainer()

    if optim_args.get('lambda_background_init_lidar_constraint', [0., 0, 0, 0])[0] > 1e-15:
        points_bkgd = dataset.scene_info.point_cloud_dict['background']
        points_gd = dataset.scene_info.point_cloud_dict['ground'].downsample(0.1)
        ego_traj = dataset.scene_info.metadata['origin_ego_pose'][:,0:3,3]
        bkgd_faiss_index_gpu, ego_faiss_index_gpu = get_faiss_index(points_bkgd, points_gd, ego_traj)
    else:
        bkgd_faiss_index_gpu = None
        ego_faiss_index_gpu= None

    num_cams = dataset.scene_info.metadata['num_cams']
    img_weight = optim_args.lambda_image_weight if "lambda_image_weight" in optim_args \
        else [1 for _ in range(num_cams)]

    densify_from_iter = training_xpeng_args.iterations_ground + optim_args.densify_from_iter
    densify_until_iter = training_xpeng_args.iterations_ground + optim_args.densify_until_iter
    opacity_reset_end = training_xpeng_args.iterations_ground + optim_args.get('opacity_reset_end', 99999999999)
    total_iter = training_xpeng_args.iterations_ground + training_xpeng_args.iterations_streetgaussian

    if training_xpeng_args.get('phase1_save', False):
        save_iterations = training_args.save_iterations + [training_xpeng_args.iterations_ground]
        checkpoint_iterations = training_args.checkpoint_iterations + [training_xpeng_args.iterations_ground]
    else:
        save_iterations = training_args.save_iterations
        checkpoint_iterations = training_args.checkpoint_iterations

    progress_bar = tqdm(range(start_iter, total_iter))

    # 创建训练数据集
    train_dataset = CameraDataset(dataset, split='train')
    train_dataloader = DataLoader(
        train_dataset,
        batch_size=1,
        shuffle=True,
        num_workers=2,
        prefetch_factor=2,
        pin_memory=True,
        collate_fn=lambda x: x[0]
    )
    total_epochs = math.ceil((total_iter - start_iter) / len(train_dataloader))
    print(f"[INFO] Total epochs: {total_epochs}, total iterations: {total_iter}", flush=True)

    ################################################################################################
    t_train = time.time()
    for epoch in range(total_epochs):
        print(f"[INFO] Starting epoch {epoch + 1}/{total_epochs}, iteration {iteration}/{total_iter}", flush=True)
        for sub_iter, viewpoint_cam in enumerate(train_dataloader):
            iteration += 1
            train_dataset.set_iteration(iteration)
            if viewpoint_cam is None:
                continue
                    
            viewpoint_cam.to_cuda()

            if (iteration - 1) == training_args.debug_from:
                cfg.render.debug = True

            gaussians.update_learning_rate(iteration)

            # Every 1000 its we increase the levels of SH up to a maximum degree
            if iteration % 1000 == 0:
                gaussians.oneupSHdegree()
            
            scalar_dict = dict()
            tensor_dict = dict()
            # ==========================================================================================
            # Get semantic and mask
            gt_semantic = viewpoint_cam.original_semantic.cuda()
            gt_image = viewpoint_cam.original_image.cuda()

            if hasattr(viewpoint_cam, 'original_mask'):
                mask = viewpoint_cam.original_mask.cuda().bool()
            else:
                mask = torch.ones_like(gt_image[0:1]).bool()

            # get sky mask
            sky_mask = get_mask_from_semantics(gt_semantic, SemanticType.SKY).permute(2, 0, 1)
            non_sky_area_real = ~sky_mask & mask
            if non_sky_area_real.sum() < 10:
                non_sky_area_real = None

            # get ground mask
            ground_mask = get_mask_from_semantics(gt_semantic, SemanticType.GROUND).permute(2, 0, 1)
            non_ground_mask = ~ground_mask & mask
            ground_mask_real = ground_mask & mask
            if ground_mask_real.sum() < 10:
                ground_mask_real = None
            
            # get veh_hum, roadside, obj_bound mask
            veh_hum_mask = get_mask_from_semantics(gt_semantic, 
                [SemanticType.HUMAN, SemanticType.VEHICLE]).permute(2, 0, 1)
            roadside_mask = get_mask_from_semantics(gt_semantic, SemanticType.ROADSIDE).permute(2, 0, 1)
            obj_bound = viewpoint_cam.original_obj_bound.cuda().bool()
            obj_bound_for_static_scene = viewpoint_cam.original_obj_bound_for_static_scene.cuda().bool()

            if iteration <= training_xpeng_args.iterations_ground:
                render_pkg = gaussians_renderer.render_ground(viewpoint_cam, gaussians)
                image, acc, viewspace_point_tensor, visibility_filter, radii = \
                    render_pkg["rgb"], render_pkg['acc'], render_pkg["viewspace_points"], \
                    render_pkg["visibility_filter"], render_pkg["radii"]
                depth = render_pkg['depth'] # [1, H, W]
                
                if ground_mask_real is not None and training_xpeng_args.phase1_exclude_obj_bound:
                    ground_mask_real = ground_mask_real & ~obj_bound

                if ground_mask_real is None or ground_mask_real.sum() < 100:
                    print(f"[ITER {iteration}] Skip due to small ground area", flush=True)
                    continue
                
                if optim_args.get('lambda_depth_weight_sigma', 0.) > 1e-6 and viewpoint_cam.meta['cam'] == 'cam2':
                    sigma = optim_args.get('lambda_depth_weight_sigma', 0.)
                    d_min, d_max = depth.min(), depth.max()
                    depths_norm = (depth - d_min) / (d_max - d_min + 1e-6)
                    depth_weights = torch.clamp(torch.exp(-depths_norm / sigma), min=0.1)  # 最小权重阈值
                else:
                    depth_weights = None

                # rgb loss
                if training_xpeng_args.phase1_only_cam2 and viewpoint_cam.meta['cam'] != 'cam2':
                    Ll1 = torch.zeros(1).cuda()
                    Lssim = torch.zeros(1).cuda()
                else:
                    if cfg.data.use_cam2_extended_l1mask[1] > 0 and viewpoint_cam.meta['cam'] == 'cam2':
                        h1 = cfg.data.use_cam2_extended_l1mask[0]
                        h2 = h1 + cfg.data.use_cam2_extended_l1mask[1]
                        mask_l1 = ground_mask_real.detach().clone()
                        mask_l1[:, h1:h2, :] = False
                        Ll1 = l1_loss(image, gt_image, mask_l1, depth_weights)
                    else:
                        Ll1 = l1_loss(image, gt_image, ground_mask_real, depth_weights)
                    Lssim = ssim(image, gt_image, mask=ground_mask_real, weight=depth_weights)
                        
                scalar_dict['l1_loss'] = Ll1.item()

                loss = img_weight[viewpoint_cam.id % num_cams] * (\
                    (1.0 - optim_args.lambda_dssim) * optim_args.lambda_l1 * Ll1 \
                    + optim_args.lambda_dssim * (1.0 - Lssim)
                )

                # acc loss
                if optim_args.get('lambda_ground_acc', 0.) > 1e-6:
                    acc = torch.clamp(acc, min=1e-6, max=1.-1e-6)
                    # [TODO] grd_acc_loss will incorrectly penalize the unseen ground gs in the iterated image
                    grd_acc_loss = torch.where(ground_mask, -torch.log(acc), 0.0) 
                    grd_acc_loss = grd_acc_loss[mask].mean()
                    scalar_dict['grd_acc_loss'] = grd_acc_loss.item()
                    loss += optim_args.lambda_ground_acc * grd_acc_loss

                if optim_args.get('lambda_novel_ground_acc', 0.) > 1e-6 \
                    and viewpoint_cam.meta['cam'] == 'cam2':
                    novel_render_pkg = render_camera_downwards(
                        viewpoint_cam, gaussians_renderer, gaussians
                    )
                    novel_render_acc = torch.clamp(novel_render_pkg['acc'], min=1e-6, max=1.-1e-6)
                    novel_grd_acc_loss = (-torch.log(novel_render_acc)).mean()
                    scalar_dict['novel_grd_acc_loss'] = novel_grd_acc_loss.item()
                    loss += optim_args.lambda_novel_ground_acc * novel_grd_acc_loss
                
                # ground symmetry loss
                if optim_args.lambda_ground_flatten > 0:
                    ground_flatten_loss = gaussians.ground.ground_flatten_loss()
                    scalar_dict['ground_flatten_loss'] = ground_flatten_loss.item()
                    loss += optim_args.lambda_ground_flatten * ground_flatten_loss

                # ground flatten loss
                if optim_args.lambda_ground_symmetry > 0:
                    ground_symmetry_loss = gaussians.ground.ground_symmetry_loss()
                    scalar_dict['ground_symmetry_loss'] = ground_symmetry_loss.item()
                    loss += optim_args.lambda_ground_symmetry * ground_symmetry_loss

                # lidar depth loss
                if optim_args.lambda_depth_lidar > 1e-12 and 'lidar_depth' in viewpoint_cam.meta \
                    and viewpoint_cam.novel_view is False:            
                    lidar_depth = viewpoint_cam.meta['lidar_depth'].cuda() # [1, H, W]
                    depth_mask = torch.logical_and(
                        (lidar_depth > 0.), mask & ~veh_hum_mask & ~obj_bound & ground_mask
                    )
                    if torch.nonzero(depth_mask).any():
                        expected_depth = depth / (render_pkg['acc'] + 1e-10)  
                        depth_error = torch.abs((expected_depth[depth_mask] - lidar_depth[depth_mask]))
                        depth_error, _ = torch.topk(depth_error, int(0.95 * depth_error.size(0)), largest=False)
                        lidar_depth_loss = depth_error.mean()
                        scalar_dict['lidar_depth_loss'] = lidar_depth_loss
                    else:
                        lidar_depth_loss = torch.zeros_like(Ll1)  
                    
                    # check if lidar_depth_loss is nan
                    if not torch.isnan(lidar_depth_loss):
                        loss += optim_args.lambda_depth_lidar * lidar_depth_loss

                scalar_dict['loss'] = loss.item()
                loss.backward()

                with torch.no_grad():
                    cam_name = viewpoint_cam.meta['cam']
                    # update evaluation
                    updated, ema_loss_for_log, ema_psnr_for_log, loss_dict, psnr_dict = evaluator.update(
                        loss, image, gt_image, mask, ground_mask_real, None, cam_name
                    )
                    if not updated:
                        print(f"[ITER {iteration}] Loss is nan or inf")

                    # Progress bar
                    if iteration % 10 == 0:
                        progress_bar.set_postfix({"Exp": f"{cfg.task}-{cfg.exp_name}-{cam_name}", 
                                                "Loss-Ground": f"{loss_dict[cam_name]:.{7}f},", 
                                                "PSNR-Ground": f"{psnr_dict[cam_name]:.{4}f}"})
                        progress_bar.update(10)
                        print(f"[ITER {iteration}][{cam_name}] Loss_ema-Ground: {loss_dict[cam_name]:.{7}f}, "\
                            f"PSNR-Ground: {psnr_dict[cam_name+'_ground']:.{4}f}", flush=True)
                        print(f"[ITER {iteration}] {scalar_dict}", flush=True)

                    # Prune ground gaussians if low opacity
                    if iteration < training_xpeng_args.prune_until_iter:
                        cam_width = viewpoint_cam.image_width
                        cam_height = viewpoint_cam.image_height
                        gaussians.set_visibility('ground')
                        gaussians.parse_camera(viewpoint_cam)
                        gaussians.set_max_radii2D(radii, visibility_filter)
                        gaussians.add_densification_stats(viewspace_point_tensor, visibility_filter, cam_width, cam_height)

                        if iteration > training_xpeng_args.prune_from_iter:
                            prune_big_points = iteration > optim_args.opacity_reset_interval
                            if iteration % optim_args.densification_interval == 0:
                                gaussians.ground.prune(
                                    min_opacity=optim_args.min_opacity_grd,
                                    prune_big_points=prune_big_points
                                )

                    # Reset opacity
                    if iteration < training_xpeng_args.prune_until_iter and \
                        iteration % optim_args.opacity_reset_interval == 0:
                            gaussians.reset_opacity(exclude_list=list(
                                set(gaussians.model_name_id.keys()) # - set(['ground'])
                            ))

                    # Optimizer step
                    gaussians.ground.update_optimizer()

            ################################################################################################
            elif training_xpeng_args.iterations_ground < iteration <= total_iter:
                render_pkg = gaussians_renderer.render(viewpoint_cam, gaussians)
                image, acc, viewspace_point_tensor, visibility_filter, radii = \
                    render_pkg["rgb"], render_pkg['acc'], render_pkg["viewspace_points"], \
                    render_pkg["visibility_filter"], render_pkg["radii"]
                depth = render_pkg['depth'] # [1, H, W]

                # rgb loss
                if training_xpeng_args.get('phase2_appearance_embedding', False):
                    decouple_image, transformation_map = decouple_appearance(image, gaussians.background, viewpoint_cam.id)
                else:
                    decouple_image = image
                    
                mask_rgb = non_ground_mask if training_xpeng_args.phase2_rgb_no_ground else mask
                if not gaussians.include_obj and gaussians.include_quasi_static_obj:
                    rgb_obj_bound = obj_bound & (~obj_bound_for_static_scene)
                    mask_rgb = mask_rgb & (~rgb_obj_bound)
                if cfg.data.use_cam2_extended_l1mask[1] > 0 and viewpoint_cam.meta['cam'] == 'cam2':
                    h1 = cfg.data.use_cam2_extended_l1mask[0]
                    h2 = h1 + cfg.data.use_cam2_extended_l1mask[1]
                    mask_l1 = mask_rgb.detach().clone()
                    mask_l1[:, h1:h2, :] = False
                    Ll1 = l1_loss(decouple_image, gt_image, mask_l1)
                else:
                    Ll1 = l1_loss(decouple_image, gt_image, mask_rgb)
                scalar_dict['l1_loss'] = Ll1.item()
                loss = img_weight[viewpoint_cam.id % num_cams] * (\
                    (1.0 - optim_args.lambda_dssim) * optim_args.lambda_l1 * Ll1 \
                    + optim_args.lambda_dssim * (1.0 - ssim(image, gt_image, mask=mask_rgb))
                )

                # sky loss
                if optim_args.lambda_sky > 0 and gaussians.include_sky and sky_mask is not None \
                    and viewpoint_cam.novel_view is False:
                    acc = torch.clamp(acc, min=1e-6, max=1.-1e-6)
                    sky_loss = torch.where(sky_mask, -torch.log(1 - acc), -torch.log(acc))
                    sky_loss = sky_loss[mask].mean()
                    if len(optim_args.lambda_sky_scale) > 0:
                        sky_loss *= optim_args.lambda_sky_scale[viewpoint_cam.meta['cam']]
                    scalar_dict['sky_loss'] = sky_loss.item()
                    loss += optim_args.lambda_sky * sky_loss

                # semantic loss
                if optim_args.lambda_semantic > 0 and data_args.get('use_semantic', False) \
                    and 'semantic' in viewpoint_cam.meta and viewpoint_cam.novel_view is False:
                    gt_semantic = viewpoint_cam.meta['semantic'].cuda().long() # [1, H, W]
                    if torch.all(gt_semantic == -1):
                        semantic_loss = torch.zeros_like(Ll1)
                    else:
                        semantic = render_pkg['semantic'].unsqueeze(0) # [1, S, H, W]
                        semantic_loss = torch.nn.functional.cross_entropy(
                            input=semantic, 
                            target=gt_semantic,
                            ignore_index=-1, 
                            reduction='mean'
                        )
                    scalar_dict['semantic_loss'] = semantic_loss.item()
                    loss += optim_args.lambda_semantic * semantic_loss
                
                # obj reg loss
                if optim_args.lambda_reg > 0 and (gaussians.include_obj or gaussians.include_quasi_static_obj)\
                    and iteration >= densify_until_iter and viewpoint_cam.novel_view is False:
                    render_pkg_obj = gaussians_renderer.render_object(viewpoint_cam, gaussians)
                    _, acc_obj = render_pkg_obj["rgb"], render_pkg_obj['acc']
                    acc_obj = torch.clamp(acc_obj, min=1e-6, max=1.-1e-6)
                    obj_bound_for_acc = obj_bound if gaussians.include_obj else obj_bound_for_static_scene
                    obj_acc_loss = torch.where(obj_bound_for_acc, 
                        -(acc_obj * torch.log(acc_obj) +  (1. - acc_obj) * torch.log(1. - acc_obj)), 
                        -torch.log(1. - acc_obj)).mean()
                    scalar_dict['obj_acc_loss'] = obj_acc_loss.item()
                    loss += optim_args.lambda_reg * obj_acc_loss

                    if optim_args.lambda_object_box_reg > 0.:
                        box_reg_loss = gaussians.get_box_reg_loss()
                        scalar_dict['box_reg_loss'] = box_reg_loss.item()
                        loss += optim_args.lambda_object_box_reg * box_reg_loss

                # lidar depth loss
                if optim_args.lambda_depth_lidar > 0 and 'lidar_depth' in viewpoint_cam.meta \
                    and viewpoint_cam.novel_view is False:            
                    lidar_depth = viewpoint_cam.meta['lidar_depth'].cuda() # [1, H, W]
                    depth_mask = torch.logical_and((lidar_depth > 0.), mask & ~veh_hum_mask & ~obj_bound)
                    if not cfg.data.use_lidar_slice_depth:
                        depth_mask = depth_mask & ground_mask 
                    else:
                        depth_mask = depth_mask & (ground_mask | roadside_mask)
                    # check if depth_mask is empty
                    if torch.nonzero(depth_mask).any():
                        expected_depth = depth / (render_pkg['acc'] + 1e-10)  
                        depth_error = torch.abs((expected_depth[depth_mask] - lidar_depth[depth_mask]))
                        depth_error, _ = torch.topk(depth_error, int(0.95 * depth_error.size(0)), largest=False)
                        lidar_depth_loss = depth_error.mean()
                        scalar_dict['lidar_depth_loss'] = lidar_depth_loss
                    else:
                        lidar_depth_loss = torch.zeros_like(Ll1)  
                    # check if lidar_depth_loss is nan
                    if not torch.isnan(lidar_depth_loss):
                        loss += optim_args.lambda_depth_lidar * lidar_depth_loss

                # color correction loss
                if optim_args.lambda_color_correction > 0 and gaussians.use_color_correction \
                    and viewpoint_cam.novel_view is False:
                    color_correction_reg_loss = gaussians.color_correction.regularization_loss(viewpoint_cam)
                    scalar_dict['color_correction_reg_loss'] = color_correction_reg_loss.item()
                    loss += optim_args.lambda_color_correction * color_correction_reg_loss
                
                # pose correction loss
                if optim_args.lambda_pose_correction > 0 and gaussians.use_pose_correction \
                    and viewpoint_cam.novel_view is False:
                    pose_correction_reg_loss = gaussians.pose_correction.regularization_loss()
                    scalar_dict['pose_correction_reg_loss'] = pose_correction_reg_loss.item()
                    loss += optim_args.lambda_pose_correction * pose_correction_reg_loss
                            
                # scale flatten loss
                if optim_args.lambda_scale_flatten > 0 and viewpoint_cam.novel_view is False:
                    scale_flatten_loss = gaussians.background.scale_flatten_loss()
                    scalar_dict['scale_flatten_loss'] = scale_flatten_loss.item()
                    loss += optim_args.lambda_scale_flatten * scale_flatten_loss

                # opacity sparse loss
                if optim_args.lambda_opacity_sparse > 0 and viewpoint_cam.novel_view is False:
                    gaussians.set_visibility(include_list=['background'])   ################## USER ADD
                    opacity = gaussians.get_opacity
                    opacity = opacity.clamp(1e-6, 1-1e-6)
                    log_opacity = opacity * torch.log(opacity)
                    log_one_minus_opacity = (1-opacity) * torch.log(1 - opacity)
                    sparse_loss = -1 * (log_opacity + log_one_minus_opacity)[visibility_filter].mean()
                    scalar_dict['opacity_sparse_loss'] = sparse_loss.item()
                    loss += optim_args.lambda_opacity_sparse * sparse_loss
                
                # ground penalty loss
                if ground_mask is not None and optim_args.lambda_background_on_ground_penalty > 0:
                    render_pkg_bkd = gaussians_renderer.render_background(viewpoint_cam, gaussians)
                    acc_bkd = torch.clamp(render_pkg_bkd['acc'], min=1e-6, max=1.-1e-6)
                    bkd_acc_loss = -torch.log(1 - acc_bkd)
                    bkd_acc_loss = bkd_acc_loss[ground_mask].mean()
                    scalar_dict['bkd_acc_loss'] = bkd_acc_loss.item()
                    loss += optim_args.lambda_background_on_ground_penalty * bkd_acc_loss
                        
                # ground symmetry loss
                if optim_args.lambda_ground_flatten_phase2 > 0:
                    ground_flatten_loss = gaussians.ground.ground_flatten_loss()
                    scalar_dict['ground_flatten_loss'] = ground_flatten_loss.item()
                    loss += optim_args.lambda_ground_flatten_phase2 * ground_flatten_loss

                # ground flatten loss
                if optim_args.lambda_ground_symmetry_phase2 > 0:
                    ground_symmetry_loss = gaussians.ground.ground_symmetry_loss()
                    scalar_dict['ground_symmetry_loss'] = ground_symmetry_loss.item()
                    loss += optim_args.lambda_ground_symmetry_phase2 * ground_symmetry_loss

                # background maxscale loss
                if optim_args.lambda_background_maxscale[0] > 0 and optim_args.lambda_background_maxscale[1] > 0:
                    maxscale_loss = gaussians.background.maxscale_loss(optim_args.lambda_background_maxscale[1])
                    scalar_dict['background_maxscale_loss'] = maxscale_loss.item()
                    loss += optim_args.lambda_background_maxscale[0] * maxscale_loss

                # object maxscale loss
                if gaussians.include_obj and viewpoint_cam.novel_view is False \
                    and optim_args.lambda_object_maxscale[0] > 0 and optim_args.lambda_object_maxscale[1] > 0:
                    gaussians.set_visibility(include_list=gaussians.obj_list)
                    gaussians.parse_camera(viewpoint_cam)
                    try:
                        scales = gaussians.get_scaling
                    except Exception as e:
                        print(f"[WARNING] fail to get scale of objects {e}, Skip object_maxscale loss calculation...")
                    else:
                        sx = scales[:, 0]
                        sy = scales[:, 1]   
                        sz = scales[:, 2]
                        maxsize = optim_args.lambda_object_maxscale[1]
                        maxscale_loss = torch.clamp(sx - maxsize, min=0.0).nanmean() + \
                            torch.clamp(sy - maxsize, min=0.0).nanmean() + \
                            torch.clamp(sz - maxsize, min=0.0).nanmean()
                        scalar_dict['object_maxscale_loss'] = maxscale_loss.item()
                        loss += optim_args.lambda_object_maxscale[0] * maxscale_loss

                # novel view depth loss
                if cfg.train_xpeng.get('phase2_novel_depth', False):
                    novel_cam = viewpoint_cam.meta['novel_camera']
                    render_novel = gaussians_renderer.render(novel_cam, gaussians)
                    novel_depth = render_novel['depth']
                    novel_depth_gt = torch.from_numpy(novel_cam.meta['lidar_depth']).unsqueeze(0).cuda()
                    novel_depth_mask = torch.logical_and((novel_depth_gt > 0.), (novel_depth_gt < 10.))
                    # check if novel_depth_mask is empty
                    if torch.nonzero(novel_depth_mask).any():
                        expected_depth = novel_depth / (render_novel['acc'] + 1e-10)  
                        depth_error = torch.abs((expected_depth[novel_depth_mask] - novel_depth_gt[novel_depth_mask]))
                        depth_error, _ = torch.topk(depth_error, int(0.95 * depth_error.size(0)), largest=False)
                        novel_depth_loss = depth_error.mean()
                        scalar_dict['novel_depth_loss'] = novel_depth_loss
                    else:
                        novel_depth_loss = torch.zeros_like(Ll1)  
                    # check if novel_depth_loss is nan
                    if not torch.isnan(novel_depth_loss):
                        loss += optim_args.lambda_depth_lidar * novel_depth_loss

                scalar_dict['loss'] = loss.item()
                scalar_dict.update(gaussians.get_number_of_gaussians())
                loss.backward()
                        
                with torch.no_grad():
                    # update evaluation
                    updated, ema_loss_for_log, ema_psnr_for_log, loss_dict, psnr_dict = evaluator.update(
                        loss, image, gt_image, mask, ground_mask_real, None, viewpoint_cam.meta['cam']
                    )
                    if not updated:
                        print(f"[ITER {iteration}] Loss is nan or inf")

                    # Progress bar
                    if iteration % 10 == 0:
                        progress_bar.set_postfix({"Exp": f"{cfg.task}-{cfg.exp_name}", 
                                                "Loss": f"{ema_loss_for_log:.{7}f},", 
                                                "PSNR": f"{ema_psnr_for_log:.{4}f}"})
                        progress_bar.update(10)
                        print(f"[ITER {iteration}] Loss: {ema_loss_for_log:.{7}f}, PSNR: {ema_psnr_for_log:.{4}f}", flush=True)
                        print(f"[ITER {iteration}] {scalar_dict}", flush=True)

                    # Densification
                    if iteration < densify_until_iter or optim_args.get("prune_after_densify", False):
                        gaussians.set_visibility(include_list=list(
                            set(gaussians.model_name_id.keys()) - set(['sky'])  # - set(['ground'])
                        ))
                        gaussians.parse_camera(viewpoint_cam)   
                        if viewpoint_cam.meta['cam'] in ['cam2', 'cam3', 'cam4']:
                            gaussians.set_max_radii2D(radii, visibility_filter)
                        
                        if iteration < densify_until_iter:
                            cam_width = viewpoint_cam.image_width
                            cam_height = viewpoint_cam.image_height
                            gaussians.add_densification_stats(viewspace_point_tensor, visibility_filter, cam_width, cam_height)
                            prune_big_points = iteration > optim_args.opacity_reset_interval + training_xpeng_args.iterations_ground
                            do_densify = iteration > densify_from_iter \
                                and iteration % optim_args.densification_interval == 0 \
                                and (iteration % optim_args.opacity_reset_interval >= optim_args.get("densify_after_num_images", 0))
                            if do_densify:
                                scalars, tensors = gaussians.densify_and_prune(
                                    max_grad=optim_args.densify_grad_threshold,
                                    min_opacity=optim_args.min_opacity,
                                    prune_big_points=prune_big_points,
                                    min_opacity_bkgd=optim_args.min_opacity_bkgd,
                                    bkgd_index=bkgd_faiss_index_gpu,
                                    egopose_index=ego_faiss_index_gpu
                                )
                                scalar_dict.update(scalars)
                                tensor_dict.update(tensors)
                                print(f"[ITER {iteration}] {scalars}", flush=True)
                        else: 
                            if iteration % optim_args.densification_interval == 0:
                                scalars, tensors = gaussians.background.densify_and_prune(
                                    max_grad=0, min_opacity=optim_args.min_opacity_bkgd, 
                                    prune_big_points=False, if_densify=False
                                )
                                scalar_dict.update(scalars)
                                tensor_dict.update(tensors)
                                print(f"[ITER {iteration}] {scalars}", flush=True)

                    # Reset opacity
                    if iteration < opacity_reset_end and iteration < densify_until_iter \
                        and iteration % optim_args.opacity_reset_interval == 0:
                        exclude_list = ['ground']
                        gaussians.reset_opacity(exclude_list=exclude_list)

                    # Optimizer step
                    if iteration < total_iter:
                        if training_xpeng_args.phase2_no_ground:
                            gaussians.update_optimizer(exclude_list=['ground'])
                        else:
                            if training_xpeng_args.phase2_ground_only_opacity:
                                gaussians.update_optimizer(exclude_list=['ground'])
                                gaussians.ground.update_optimizer_phase2()
                            else:
                                gaussians.update_optimizer()
            
            if cfg.data.get("save_log_images", False) and (iteration % 1000 == 0):
                try:
                    # row0: gt_image, image, depth
                    # row1: acc, image_obj, acc_obj
                    depth_colored, _ = visualize_depth_numpy(depth.detach().cpu().numpy().squeeze(0))
                    depth_colored = depth_colored[..., [2, 1, 0]] / 255.
                    depth_colored = torch.from_numpy(depth_colored).permute(2, 0, 1).float().cuda()
                    row0 = torch.cat([gt_image, image, depth_colored], dim=2)
                    acc = acc.repeat(3, 1, 1)
                    with torch.no_grad():
                        render_pkg_obj = gaussians_renderer.render_object(viewpoint_cam, gaussians)
                        image_obj, acc_obj = render_pkg_obj["rgb"], render_pkg_obj['acc']
                    acc_obj = acc_obj.repeat(3, 1, 1)
                    row1 = torch.cat([acc, image_obj, acc_obj], dim=2)
                    image_to_show = torch.cat([row0, row1], dim=1)
                    image_to_show = torch.clamp(image_to_show, 0.0, 1.0)
                    os.makedirs(f"{cfg.model_path}/log_images", exist_ok = True)
                    save_img_torch(image_to_show, f"{cfg.model_path}/log_images/{iteration}.jpg")
                except Exception as e:
                    print(f"[Warning] Failed to save log images: {e}", flush=True)

            with torch.no_grad():
                # Update
                scalar_dict['ema_loss'] = ema_loss_for_log
                scalar_dict['ema_psnr'] = ema_psnr_for_log
                scalar_dict[f'loss_{viewpoint_cam.meta["cam"]}'] = loss_dict[viewpoint_cam.meta['cam']]
                for key, value in psnr_dict.items():
                    scalar_dict['psnr_' + key] = value.item()
                
                training_report(tb_writer, iteration, scalar_dict, tensor_dict, 
                    training_args.test_iterations, scene, gaussians_renderer)

                # edit gaussians
                if training_xpeng_args.iterations_ground == iteration \
                    and optim_args.get('lambda_ground_max_surface', 1e8) < 1000:
                    # Progress ground big surface and volume gs
                    edit_ground_gaussians(gaussians, optim_args)
                    
                # Log and save
                if iteration in save_iterations:
                    print("\n[ITER {}] Saving Gaussians".format(iteration), flush=True)
                    scene.save(iteration)

                if iteration in checkpoint_iterations:
                    print("\n[ITER {}] Saving Checkpoint".format(iteration), flush=True)
                    state_dict = gaussians.save_state_dict(is_final=(iteration == total_iter))
                    state_dict['iter'] = iteration
                    ckpt_path = os.path.join(cfg.trained_model_dir, f'iteration_{iteration}.pth')
                    torch.save(state_dict, ckpt_path)

                if iteration == total_iter:
                    progress_bar.close()
    t_end = time.time()
    print(f"\nTraining complete in {(t_end - t_train)/3600:.2f}h")


def prepare_output_and_logger():
    # Set up output folder
    print("Output folder: {}".format(cfg.model_path))

    os.makedirs(cfg.model_path, exist_ok=True)
    os.makedirs(cfg.trained_model_dir, exist_ok=True)
    os.makedirs(cfg.record_dir, exist_ok=True)
    if not cfg.resume:
        os.system('rm -rf {}/*'.format(cfg.record_dir))
        os.system('rm -rf {}/*'.format(cfg.trained_model_dir))

    with open(os.path.join(cfg.model_path, "cfg_args"), 'w') as cfg_log_f:
        viewer_arg = dict()
        viewer_arg['sh_degree'] = cfg.model.gaussian.sh_degree
        viewer_arg['white_background'] = cfg.data.white_background
        viewer_arg['source_path'] = cfg.source_path
        viewer_arg['model_path']= cfg.model_path
        cfg_log_f.write(str(Namespace(**viewer_arg)))

    # Create Tensorboard writer
    tb_writer = None
    if TENSORBOARD_FOUND:
        tb_writer = SummaryWriter(cfg.record_dir)
    else:
        print("Tensorboard not available: not logging progress")
    return tb_writer


def training_report(tb_writer, iteration, scalar_stats, tensor_stats, testing_iterations, 
    scene: Scene, renderer: StreetGaussianRenderer):
    if tb_writer:
        try:
            for key, value in scalar_stats.items():
                tb_writer.add_scalar('train/' + key, value, iteration)
            for key, value in tensor_stats.items():
                tb_writer.add_histogram('train/' + key, value, iteration)
        except:
            print('Failed to write to tensorboard')

    # Report test and samples of training set
    if iteration in testing_iterations:
        torch.cuda.empty_cache()
        validation_configs = ({'name': 'test/test_view', 'cameras' : scene.getTestCameras()},
                              {'name': 'test/train_view', 'cameras' : 
                              [scene.getTrainCameras()[idx % len(scene.getTrainCameras())] for idx in range(5, 30, 5)]})

        for config in validation_configs:
            if config['cameras'] and len(config['cameras']) > 0:
                l1_test = 0.0
                psnr_test = 0.0
                for idx, viewpoint in enumerate(config['cameras']):
                    image = torch.clamp(renderer.render(viewpoint, scene.gaussians)["rgb"], 0.0, 1.0)
                    gt_image = torch.clamp(viewpoint.original_image.to("cuda"), 0.0, 1.0)
                    if tb_writer and (idx < 5):
                        tb_writer.add_images(
                            config['name'] + "_{}/render".format(viewpoint.image_name), image[None], global_step=iteration)
                        if iteration == testing_iterations[0]:
                            tb_writer.add_images(
                                config['name'] + "_{}/ground_truth".format(viewpoint.image_name), gt_image[None], global_step=iteration)

                    if hasattr(viewpoint, 'original_mask'):
                        mask = viewpoint.original_mask.cuda().bool()
                    else:
                        mask = torch.ones_like(gt_image[0]).bool()
                    l1_test += l1_loss(image, gt_image, mask).mean().double()
                    psnr_test += psnr(image, gt_image, mask).mean().double()

                psnr_test /= len(config['cameras'])
                l1_test /= len(config['cameras'])
                print("\n[ITER {}] Evaluating {}: L1 {} PSNR {}".format(iteration, config['name'], l1_test, psnr_test))
                if tb_writer:
                    tb_writer.add_scalar(config['name'] + '/loss_viewpoint - l1_loss', l1_test, iteration)
                    tb_writer.add_scalar(config['name'] + '/loss_viewpoint - psnr', psnr_test, iteration)

        if tb_writer:
            tb_writer.add_histogram("test/opacity_histogram", scene.gaussians.get_opacity, iteration)
            tb_writer.add_scalar('test/points_total', scene.gaussians.get_xyz.shape[0], iteration)
        torch.cuda.empty_cache()


if __name__ == "__main__":
    print("Optimizing " + cfg.model_path)

    # Initialize system state (RNG)
    safe_state(cfg.train.quiet)

    # Start GUI server, configure and run training
    torch.autograd.set_detect_anomaly(cfg.train.detect_anomaly)
    training_xpeng()

    # All done
    print("\nTraining complete.")
