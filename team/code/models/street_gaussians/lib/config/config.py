from .yacs import CfgNode as CN
import argparse
import os
import numpy as np
import yaml
from lib.utils.cfg_utils import make_cfg

cfg = CN()

cfg.workspace = os.environ['PWD']
cfg.loaded_iter = -1
cfg.ip = '127.0.0.1'
cfg.port = 6009
cfg.data_device = 'cuda'
cfg.mode = 'train' 
cfg.task = 'hello' # task folder name
cfg.exp_name = 'test' # experiment folder name
cfg.gpus = [0] # list of gpus to use 
cfg.debug = False
cfg.resume = True # If set to True, resume training from the last checkpoint.
cfg.save_misc = False

cfg.source_path = ''
cfg.model_path = ''
cfg.record_dir = None
cfg.resolution = 1
cfg.resolution_scales = [1]
cfg.novel_image = False
cfg.dilate_mask = 0    # expand the black area of the mask by this pixel, 0 for disable

cfg.eval = CN()
cfg.eval.skip_train = False 
cfg.eval.skip_test = False 
cfg.eval.eval_train = False
cfg.eval.eval_test = True
cfg.eval.quiet = False

cfg.train = CN()
cfg.train.debug_from = -1
cfg.train.detect_anomaly = False
cfg.train.test_iterations = [7000, 30000]
cfg.train.save_iterations = [7000, 30000]
cfg.train.iterations = 30000
cfg.train.quiet = False
cfg.train.checkpoint_iterations = [30000]
cfg.train.max_shift_distance = 1.5
cfg.train.max_yaw_degree = 3.0

cfg.train_xpeng = CN()
cfg.train_xpeng.iterations_ground = 30000
cfg.train_xpeng.iterations_streetgaussian = 50000
cfg.train_xpeng.prune_until_iter = 10000
cfg.train_xpeng.prune_from_iter = 1000
cfg.train_xpeng.phase1_save = False
cfg.train_xpeng.phase1_only_cam2 = False
cfg.train_xpeng.phase1_exclude_obj_bound = False
cfg.train_xpeng.phase2_include_obj_bound = False
cfg.train_xpeng.phase2_ground_only_opacity = True
cfg.train_xpeng.phase2_no_ground = False
cfg.train_xpeng.phase2_rgb_no_ground = False
cfg.train_xpeng.phase2_appearance_embedding = False

cfg.optim = CN()
# learning rate
cfg.optim.position_lr_init = 0.00016            # position_lr_init_{bkgd, obj ...}, similar to the following
cfg.optim.position_lr_final = 0.0000016
cfg.optim.position_lr_init_grd = 1e-15        # position_lr_init_{ground}
cfg.optim.position_lr_final_grd = 1e-16
cfg.optim.position_lr_delay_mult = 0.01
cfg.optim.position_lr_max_steps = 30000
cfg.optim.position_lr_delay_steps = 0
cfg.optim.feature_lr = 0.0025
cfg.optim.opacity_lr = 0.05
cfg.optim.scaling_lr = 0.005
cfg.optim.scaling_lr_final = 0.005
cfg.optim.rotation_lr = 0.001
# densification and pruning
cfg.optim.percent_dense = 0.01 
cfg.optim.densification_interval = 100
cfg.optim.opacity_reset_interval = 3000
cfg.optim.densify_from_iter = 500
cfg.optim.huge_obj_densify_until_iter = 28000
cfg.optim.densify_until_iter = 15000
cfg.optim.ground_training_iter = 15000
cfg.optim.densify_grad_threshold = 0.0002 # densify_grad_threshold_{bkgd, obj ...}
cfg.optim.densify_grad_abs_bkgd = False # densification strategy from AbsGS
cfg.optim.densify_grad_abs_obj = False 
cfg.optim.max_screen_size = 250
cfg.optim.min_opacity = 0.005
cfg.optim.min_opacity_bkgd = 0.005
cfg.optim.min_opacity_grd = 0.005
cfg.optim.percent_big_ws = 0.1
# loss weight
cfg.optim.lambda_l1 = 1.
cfg.optim.lambda_dssim = 0.2
cfg.optim.lambda_sky = 0.
cfg.optim.lambda_sky_scale = []
cfg.optim.lambda_semantic = 0.
cfg.optim.lambda_reg = 0.
cfg.optim.lambda_depth_lidar = 0.
cfg.optim.lambda_depth_mono = 0.
cfg.optim.lambda_normal_lidar = 0.
cfg.optim.lambda_normal_mono = 0.
cfg.optim.lambda_color_correction = 0.
cfg.optim.lambda_pose_correction = 0.
cfg.optim.lambda_scale_flatten = 0.
cfg.optim.lambda_opacity_sparse = 0.

cfg.optim.squeeze_grd_gs = False
cfg.optim.lambda_ground_acc = 0.
cfg.optim.lambda_ground_flatten = 0.
cfg.optim.lambda_ground_symmetry = 0.
cfg.optim.lambda_ground_flatten_phase2 = 0.
cfg.optim.lambda_ground_symmetry_phase2 = 0.

cfg.optim.lambda_background_on_ground_penalty = 0.
cfg.optim.lambda_background_maxscale = [0., 0.]     # two elements: [weight, max_scale]
cfg.optim.lambda_object_maxscale = [0., 0.]     # two elements: [weight, max_scale]
cfg.optim.lambda_object_box_reg = 0.

cfg.model = CN()
cfg.model.gaussian = CN()
cfg.model.gaussian.sh_degree = 3
cfg.model.gaussian.fourier_dim = 1 # fourier spherical harmonics dimension
cfg.model.gaussian.fourier_scale = 1.
cfg.model.gaussian.flip_prob = 0. # symmetry prior for rigid objects, flip gaussians with this probability during training
cfg.model.gaussian.semantic_mode = 'logits'

cfg.model.gaussian.use_tracklets_world = False # Only for Xpeng datasets, no interpolation of obj position
cfg.model.gaussian.huge_vehicle_length = 7.0

cfg.model.nsg = CN()
cfg.model.nsg.include_bkgd = True # include background
cfg.model.nsg.include_ground = True # include ground
cfg.model.nsg.include_obj = True # include object
cfg.model.nsg.include_sky = False # include sky cubemap
cfg.model.nsg.opt_track = True # tracklets optimization
cfg.model.sky = CN()
cfg.model.sky.resolution = 1024
cfg.model.sky.white_background = True


#### Note: We have not fully tested this.
cfg.model.use_color_correction = False # If set to True, learn transformation matrixs for appearance embedding
cfg.model.color_correction = CN() 
cfg.model.color_correction.mode = 'image' # If set to 'image', learn separate embedding for each image. If set to 'sensor', learn a single embedding for all images captured by one camera senosor. 
cfg.model.color_correction.use_mlp = False # If set to True, regress embedding from extrinsic by a mlp. Otherwise, define the embedding explicitly.
cfg.model.color_correction.use_sky = False # If set to True, using spparate embedding for background and sky
# Alternative choice from GOF: https://github.com/autonomousvision/gaussian-opacity-fields/blob/main/scene/appearance_network.py

cfg.model.use_pose_correction = False # If set to True, use pose correction for camera poses. 
cfg.model.pose_correction = CN()
cfg.model.pose_correction.mode = 'image' # If set to 'image', learn separate correction matrix for each image. If set to 'frame', learn a single correction matrix for all images corresponding to the same frame timestamp. 
####

cfg.data = CN()
cfg.data.white_background = False # If set to True, use white background. Should be False when using sky cubemap.
cfg.data.use_colmap_pose = False # If set to True, use colmap to recalibrate camera poses as input (rigid bundle adjustment now).
cfg.data.filter_colmap = False # If set to True, filter out SfM points by camera poses.
cfg.data.box_scale = 1.0 # Scale the bounding box by this factor.
cfg.data.split_test = -1 
cfg.data.shuffle = True
cfg.data.eval = True
cfg.data.type = 'Colmap'
cfg.data.images = 'images'
cfg.data.write_obj_bound = False
cfg.data.use_semantic = False
cfg.data.use_mono_depth = False
cfg.data.use_mono_normal = False
cfg.data.use_lidar_normal = False
cfg.data.use_colmap = True
cfg.data.use_surfel = True
cfg.data.use_metric_test = False
cfg.data.use_g3r_ground_init = False
cfg.data.use_g3r_background_init = False
cfg.data.use_lidar_slice_depth = False
cfg.data.use_cam2_extended_l1mask = [0, 0]
cfg.data.input_ground_downsample = 0.
# data.load_pcd_from: Load the initialization point cloud from a previous experiment without generation.
# data.extent: radius of the scene, we recommend 10 - 20 meters.
# data.sphere_scale: Scale the sphere radius by this factor.
# data.regenerate_pcd: Regenerate the initialization point cloud.

cfg.render = CN()
cfg.render.convert_SHs_python = False
cfg.render.compute_cov3D_python = False
cfg.render.debug = False
cfg.render.scaling_modifier = 1.0
cfg.render.fps = 24
cfg.render.render_normal = False
cfg.render.save_video = True
cfg.render.save_video_merged = True
cfg.render.save_image = True
cfg.render.save_image_merged = False
cfg.render.save_misc_images = False
cfg.render.coord = 'world' # ['world', 'vehicle']
cfg.render.concat_cameras = []
cfg.render.fix = False # If set to True, fix the image using difix

cfg.fixer = CN()
cfg.fixer.pretrained_path = '/workspace/group_share/adc-sim/users/led/ckpts/difix'
cfg.fixer.timesteps = [200]
cfg.fixer.cam = [1, 2, 3, 4, 5, 6] # cameras to apply difix
cfg.fixer.guidance_scale = 3.0
cfg.fixer.scale = 1 # 1 to disable any downsampling
cfg.fixer.fp16 = True
cfg.fixer.use_reference_image = False
cfg.fixer.compile_pipeline = False
cfg.fixer.xformers = True
cfg.fixer.prompt = "remove degradation"

cfg.viewer = CN()
cfg.viewer.frame_id = 0 # Select the frame_id (start from 0) to save for viewer


parser = argparse.ArgumentParser()
parser.add_argument("--config", default='/root/repo/models/street_gaussians/configs/default.yaml', type=str)
parser.add_argument("--mode", type=str, default="")
parser.add_argument('--det', type=str, default='')
parser.add_argument('--local_rank', type=int, default=0)
parser.add_argument('--print_cfg', type=bool, default=False)
parser.add_argument("opts", default=None, nargs=argparse.REMAINDER)

args, unknown_args = parser.parse_known_args()
# cfg = make_cfg(cfg, args)
# if len(args.mode) > 0:
#     cfg.mode = args.mode


def reload_config(args, cfg, parser, yaml_path):
    args.config = yaml_path
    cfg = make_cfg(cfg, args)
    if len(args.mode) > 0:
        cfg.mode = args.mode
        
yaml_path = "/tmp/cfg_path_output.yaml"
cfg_path=None
if os.path.exists(yaml_path):
    with open(yaml_path, 'r') as file:
        data = yaml.safe_load(file)
    cfg_path = data.get("cfg_path",None)
    print(f"config.py cfg_path={cfg_path}")


if cfg_path is not None:
    print(f"MY_ENV_VAR={cfg_path}")
    print(f"old cfg config ={args.config}")
    reload_config(args,cfg,parser,cfg_path)
    print(f"new model_path ={cfg.model_path}")
    print(f"new cfg config ={args.config}")
else:
    print("MY_ENV_VAR is not set")
    cfg = make_cfg(cfg, args)
    if len(args.mode) > 0:
        cfg.mode = args.mode
