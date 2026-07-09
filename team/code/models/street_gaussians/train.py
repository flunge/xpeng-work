import os
import torch
import numpy as np
from scipy.spatial import cKDTree as KDTree
from tqdm import tqdm
from argparse import ArgumentParser, Namespace
from random import randint

from lib.models.street_gaussian_renderer import StreetGaussianRenderer
from lib.models.street_gaussian_model import StreetGaussianModel
from lib.models.scene import Scene
from lib.utils.loss_utils import l1_loss, l2_loss, psnr, ssim, get_ground_gs_index
from lib.utils.img_utils import save_img_torch, visualize_depth_numpy
from lib.utils.general_utils import safe_state
from lib.utils.camera_utils import Camera
from lib.utils.cfg_utils import save_cfg
from lib.utils.sim_utils import save_scene_info
from lib.utils.system_utils import searchForMaxIteration, cleanup_clip_folder
from lib.utils.eval_utils import EvaluatorInTrainer
from lib.utils.xpeng_utils import get_mask_from_semantics
from lib.utils.xpeng_novel_utils import render_camera_downwards
from lib.config.globals import SemanticType
from lib.datasets.dataset import Dataset
from lib.config import cfg


try:
    from torch.utils.tensorboard import SummaryWriter
    TENSORBOARD_FOUND = True
except ImportError:
    TENSORBOARD_FOUND = False


def training():
    training_args = cfg.train
    optim_args = cfg.optim
    data_args = cfg.data

    start_iter = 0
    state_dict = None
    cleanup_clip_folder(cfg.source_path)

    tb_writer = prepare_output_and_logger()
    dataset = Dataset(load_cameras=False)
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
    print(f'[INFO] Starting from {start_iter}', flush=True)

    dataset.load_cameras()
    gaussians = StreetGaussianModel(dataset.scene_info.metadata)
    scene = Scene(gaussians=gaussians, dataset=dataset)

    gaussians.training_setup()
    if state_dict is not None:
        gaussians.load_state_dict(state_dict)
        state_dict = None
    gaussians_renderer = StreetGaussianRenderer()

    iter_start = torch.cuda.Event(enable_timing = True)
    iter_end = torch.cuda.Event(enable_timing = True)

    evaluator = EvaluatorInTrainer()
    progress_bar = tqdm(range(start_iter, training_args.iterations))
    start_iter += 1

    viewpoint_stack = None

    if optim_args.get('lambda_background_init_lidar_constraint', [0., 0, 0, 0])[0] > 1e-15:
        points_bkgd = dataset.scene_info.point_cloud_dict['background']
        points_gd = dataset.scene_info.point_cloud_dict['ground'].downsample(0.1)
        # build kdtree with scipy
        con_points = np.concatenate([points_bkgd.points[:, :3], points_gd.points[:, :3]], axis=0)
        kdtree = KDTree(con_points)
        egopose_kdtree = KDTree(dataset.scene_info.metadata['origin_ego_pose'][:,0:3,3])
    else:
        kdtree = None
        egopose_kdtree= None

    num_cams = dataset.scene_info.metadata['num_cams']
    img_weight = optim_args.lambda_image_weight if "lambda_image_weight" in optim_args \
        else [1 for _ in range(num_cams)]

    for iteration in range(start_iter, training_args.iterations + 1):
    
        iter_start.record()
        gaussians.update_learning_rate(iteration)

        # Every 1000 its we increase the levels of SH up to a maximum degree
        if iteration % 1000 == 0:
            gaussians.oneupSHdegree()

        # Pick a random Camera
        if not viewpoint_stack:
            viewpoint_stack = scene.getTrainCameras().copy()
        
        viewpoint_cam: Camera = viewpoint_stack.pop(randint(0, len(viewpoint_stack) - 1))
    
        # ====================================================================
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
        ground_mask_real = ground_mask & mask
        if ground_mask_real.sum() < 10:
            ground_mask_real = None
        
        # get veh_hum, roadside, obj_bound mask
        veh_hum_mask = get_mask_from_semantics(gt_semantic, 
            [SemanticType.HUMAN, SemanticType.VEHICLE]).permute(2, 0, 1)
        roadside_mask = get_mask_from_semantics(gt_semantic, SemanticType.ROADSIDE).permute(2, 0, 1)
        obj_bound = viewpoint_cam.original_obj_bound.cuda().bool()
        
        # ====================================================================
        if (iteration - 1) == training_args.debug_from:
            cfg.render.debug = True

        scalar_dict = dict()
        tensor_dict = dict()
        render_pkg = gaussians_renderer.render(viewpoint_cam, gaussians)
        image, acc, viewspace_point_tensor, visibility_filter, radii = \
            render_pkg["rgb"], render_pkg['acc'], render_pkg["viewspace_points"], \
            render_pkg["visibility_filter"], render_pkg["radii"]
        depth = render_pkg['depth'] # [1, H, W]
        acc = torch.clamp(acc, min=1e-6, max=1.-1e-6)

        # rgb loss
        if cfg.data.use_cam2_extended_l1mask[1] > 0 and viewpoint_cam.meta['cam'] == 'cam2':
            h1 = cfg.data.use_cam2_extended_l1mask[0]
            h2 = h1 + cfg.data.use_cam2_extended_l1mask[1]
            mask_l1 = mask.detach().clone()
            mask_l1[:, h1:h2, :] = False
            Ll1 = l1_loss(image, gt_image, mask_l1)
        else:
            Ll1 = l1_loss(image, gt_image, mask)
        scalar_dict['l1_loss'] = Ll1.item()
        loss = img_weight[viewpoint_cam.id % num_cams] * (\
            (1.0 - optim_args.lambda_dssim) * optim_args.lambda_l1 * Ll1 \
            + optim_args.lambda_dssim * (1.0 - ssim(image, gt_image, mask=mask))
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
        if optim_args.lambda_semantic > 1e-12 and data_args.get('use_semantic', False) \
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
        
        if optim_args.lambda_reg > 1e-12 and gaussians.include_obj \
            and iteration >= optim_args.densify_until_iter and viewpoint_cam.novel_view is False:
            render_pkg_obj = gaussians_renderer.render_object(viewpoint_cam, gaussians)
            image_obj, acc_obj = render_pkg_obj["rgb"], render_pkg_obj['acc']
            acc_obj = torch.clamp(acc_obj, min=1e-6, max=1.-1e-6)

            obj_acc_loss = torch.where(obj_bound, 
                -(acc_obj * torch.log(acc_obj) +  (1. - acc_obj) * torch.log(1. - acc_obj)), 
                -torch.log(1. - acc_obj)).mean()
            scalar_dict['obj_acc_loss'] = obj_acc_loss.item()
            loss += optim_args.lambda_reg * obj_acc_loss

            if optim_args.lambda_object_box_reg > 0.:
                box_reg_loss = gaussians.get_box_reg_loss()
                scalar_dict['box_reg_loss'] = box_reg_loss.item()
                loss += optim_args.lambda_object_box_reg * box_reg_loss
        
        # lidar depth loss
        if optim_args.lambda_depth_lidar > 1e-12 and 'lidar_depth' in viewpoint_cam.meta \
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
        if optim_args.lambda_color_correction > 1e-12 and gaussians.use_color_correction \
            and viewpoint_cam.novel_view is False:
            color_correction_reg_loss = gaussians.color_correction.regularization_loss(viewpoint_cam)
            scalar_dict['color_correction_reg_loss'] = color_correction_reg_loss.item()
            loss += optim_args.lambda_color_correction * color_correction_reg_loss
        
        # pose correction loss
        if optim_args.lambda_pose_correction > 1e-12 and gaussians.use_pose_correction \
            and viewpoint_cam.novel_view is False:
            pose_correction_reg_loss = gaussians.pose_correction.regularization_loss()
            scalar_dict['pose_correction_reg_loss'] = pose_correction_reg_loss.item()
            loss += optim_args.lambda_pose_correction * pose_correction_reg_loss
                    
        # scale flatten loss
        if optim_args.lambda_scale_flatten > 1e-12 and viewpoint_cam.novel_view is False:
            scale_flatten_loss = gaussians.background.scale_flatten_loss()
            scalar_dict['scale_flatten_loss'] = scale_flatten_loss.item()
            loss += optim_args.lambda_scale_flatten * scale_flatten_loss
        
        # ground flatten loss
        if optim_args.lambda_ground_flatten > 1e-12 and ground_mask is not None \
            and viewpoint_cam.novel_view is False:
            if gaussians.include_ground:
                ground_flatten_loss = gaussians.ground.ground_flatten_loss()
            elif optim_args.squeeze_grd_gs:
                valid_ground_index = get_ground_gs_index(render_pkg, ground_mask)
                ground_flatten_loss = gaussians.background.ground_flatten_loss(valid_ground_index)
            else:
                raise UserWarning("[ERROR] ground_flatten_loss setting is not correct!")
            scalar_dict['ground_flatten_loss'] = ground_flatten_loss.item()
            loss += optim_args.lambda_ground_flatten * ground_flatten_loss

        # ground symmetry loss
        if optim_args.lambda_ground_symmetry > 1e-12 and ground_mask is not None \
            and viewpoint_cam.novel_view is False:
            if gaussians.include_ground:
                ground_symmetry_loss = gaussians.ground.ground_symmetry_loss()
            elif optim_args.squeeze_grd_gs:
                valid_ground_index = get_ground_gs_index(render_pkg, ground_mask)
                ground_symmetry_loss = gaussians.background.ground_symmetry_loss(valid_ground_index)
            else:
                raise UserWarning("[ERROR] ground_symmetry_loss setting is not correct!")
            scalar_dict['ground_symmetry_loss'] = ground_symmetry_loss.item()
            loss += optim_args.lambda_ground_symmetry * ground_symmetry_loss

        # ground acc loss
        if ground_mask is not None and optim_args.lambda_ground_acc > 1e-12:
            if gaussians.include_ground:
                render_grd = gaussians_renderer.render_ground(viewpoint_cam, gaussians)
                acc_grd = torch.clamp(render_grd['acc'], min=1e-6, max=1.-1e-6)
                grd_acc_loss = torch.where(~ground_mask, -torch.log(1 - acc_grd), 0)
                grd_acc_loss = grd_acc_loss[mask].mean()
            else:
                grd_acc_loss = -torch.log(acc[ground_mask]).mean()
            scalar_dict['grd_acc_loss'] = grd_acc_loss.item()
            loss += optim_args.lambda_ground_acc * grd_acc_loss

        # opacity sparse loss
        if optim_args.lambda_opacity_sparse > 1e-12 and viewpoint_cam.novel_view is False:
            gaussians.set_visibility(include_list=['background'])
            opacity = gaussians.get_opacity
            opacity = opacity.clamp(1e-6, 1-1e-6)
            log_opacity = opacity * torch.log(opacity)
            log_one_minus_opacity = (1-opacity) * torch.log(1 - opacity)
            sparse_loss = -1 * (log_opacity + log_one_minus_opacity)[visibility_filter].mean()
            scalar_dict['opacity_sparse_loss'] = sparse_loss.item()
            loss += optim_args.lambda_opacity_sparse * sparse_loss
                
        # normal loss
        if optim_args.lambda_normal_mono > 1e-12 and 'mono_normal' in viewpoint_cam.meta \
            and 'normals' in render_pkg and viewpoint_cam.novel_view is False:
            if sky_mask is None:
                normal_mask = mask
            else:
                normal_mask = torch.logical_and(mask, ~sky_mask)
                normal_mask = normal_mask.squeeze(0)
                normal_mask[:50] = False
                
            normal_gt = viewpoint_cam.meta['mono_normal'].permute(1, 2, 0).cuda() # [H, W, 3]
            R_c2w = viewpoint_cam.world_view_transform[:3, :3]
            normal_gt = torch.matmul(normal_gt, R_c2w.T) # to world space
            normal_pred = render_pkg['normals'].permute(1, 2, 0) # [H, W, 3]    
            
            normal_l1_loss = torch.abs(normal_pred[normal_mask] - normal_gt[normal_mask]).mean()
            normal_cos_loss = (1. - torch.sum(normal_pred[normal_mask] * normal_gt[normal_mask], dim=-1)).mean()
            scalar_dict['normal_l1_loss'] = normal_l1_loss.item()
            scalar_dict['normal_cos_loss'] = normal_cos_loss.item()
            normal_loss = normal_l1_loss + normal_cos_loss
            loss += optim_args.lambda_normal_mono * normal_loss

        if optim_args.lambda_normal_lidar > 1e-12 and 'lidar_normal' in viewpoint_cam.meta \
            and 'normals' in render_pkg and viewpoint_cam.novel_view is False:
            normal_gt = viewpoint_cam.meta['lidar_normal'].permute(1, 2, 0).cuda() # [H, W, 3]
            normal_pred = render_pkg['normals'].permute(1, 2, 0) # [H, W, 3]    
            normal_mask = (roadside_mask & ~obj_bound).squeeze(0)
            normal_l1_loss = torch.abs(normal_pred[normal_mask] - normal_gt[normal_mask]).mean()
            normal_cos_loss = (1. - torch.sum(normal_pred[normal_mask] * normal_gt[normal_mask], dim=-1)).mean()
            scalar_dict['normal_l1_loss'] = normal_l1_loss.item()
            scalar_dict['normal_cos_loss'] = normal_cos_loss.item()
            normal_loss = normal_l1_loss + normal_cos_loss
            loss += optim_args.lambda_normal_lidar * normal_loss

        scalar_dict['loss'] = loss.item()

        loss.backward()
        
        iter_end.record()
                
        is_save_images = True
        if is_save_images and (iteration % 1000 == 0):
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
        
        with torch.no_grad():
            # Log
            tensor_dict = dict()

            # update evaluation
            updated, ema_loss_for_log, ema_psnr_for_log, loss_dict, psnr_dict = evaluator.update(
                loss, image, gt_image, mask, ground_mask_real, non_sky_area_real, viewpoint_cam.meta['cam']
            )
            if not updated:
                print(f"[ITER {iteration}] Loss is nan or inf")
            
            if iteration % 10 == 0:
                progress_bar.set_postfix({"Exp": f"{cfg.task}-{cfg.exp_name}", 
                                          "Loss": f"{ema_loss_for_log:.{7}f},", 
                                          "PSNR": f"{ema_psnr_for_log:.{4}f}"})
                progress_bar.update(10)
                print(f"[ITER {iteration}] Loss: {ema_loss_for_log:.{7}f}, PSNR: {ema_psnr_for_log:.{4}f}")
                print(f"[ITER {iteration}] {scalar_dict}")

            if iteration == training_args.iterations:
                progress_bar.close()

            # Log and save
            if (iteration in training_args.save_iterations):
                print("\n[ITER {}] Saving Gaussians".format(iteration))
                scene.save(iteration)

            # Densification
            if iteration < optim_args.densify_until_iter:
                include_list = set(gaussians.model_name_id.keys()) - set(['sky'])  # , 'ground'
                gaussians.set_visibility(include_list=list(include_list))
                gaussians.parse_camera(viewpoint_cam)   
                gaussians.set_max_radii2D(radii, visibility_filter)
                gaussians.add_densification_stats(viewspace_point_tensor, visibility_filter)
                
                prune_big_points = iteration > optim_args.opacity_reset_interval

                if iteration > optim_args.densify_from_iter:
                    if iteration % optim_args.densification_interval == 0:
                        scalars, tensors = gaussians.densify_and_prune(
                            max_grad=optim_args.densify_grad_threshold,
                            min_opacity=optim_args.min_opacity,
                            prune_big_points=prune_big_points,
                            min_opacity_bkgd=optim_args.min_opacity_bkgd,
                            kdtree=kdtree,
                            egopose=egopose_kdtree
                        )

                        scalar_dict.update(scalars)
                        tensor_dict.update(tensors)
                        print(f"[ITER {iteration}] {scalars}", flush=True)
                        
            # Reset opacity
            if iteration < optim_args.densify_until_iter:
                if iteration % optim_args.opacity_reset_interval == 0:
                    gaussians.reset_opacity(exclude_list=['ground'])               
                if data_args.white_background and iteration == optim_args.densify_from_iter:
                    gaussians.reset_opacity()
                            
            # Update
            scalar_dict['ema_loss'] = ema_loss_for_log
            scalar_dict['ema_psnr'] = ema_psnr_for_log
            scalar_dict[f'loss_{viewpoint_cam.meta["cam"]}'] = loss_dict[viewpoint_cam.meta['cam']]
            for key, value in psnr_dict.items():
                scalar_dict['psnr_' + key] = value.item()
            
            training_report(tb_writer, iteration, scalar_dict, tensor_dict, 
                training_args.test_iterations, scene, gaussians_renderer)

            # Optimizer step
            if iteration < training_args.iterations:
                gaussians.update_optimizer()

            if (iteration in training_args.checkpoint_iterations):
                print("\n[ITER {}] Saving Checkpoint".format(iteration))
                state_dict = gaussians.save_state_dict(is_final=(iteration == training_args.iterations))
                state_dict['iter'] = iteration
                ckpt_path = os.path.join(cfg.trained_model_dir, f'iteration_{iteration}.pth')
                torch.save(state_dict, ckpt_path)


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
    training()

    # All done
    print("\nTraining complete.")