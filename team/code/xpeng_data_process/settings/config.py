import argparse
import os
from copy import deepcopy
from settings import yacs
from settings.yacs import CfgNode as CN


def make_case_specific_settings(cfg):
    # check if cfg has clip id
    if "clip_id" in cfg:
        cfg.clip_path = os.path.join(cfg.root, cfg.clip_id)
    elif "subrun_list" in cfg:
        cfg.subrun_path = os.path.join(cfg.root, cfg.subrun_list[0])
        cfg.clip_id = cfg.subrun_list[0]
        cfg.clip_path = cfg.subrun_path
    else:
        raise ValueError("[ERROR] clip_id or subrun_list must be in cfg")
    cfg.target_lidar = "lidar1" if "lidar1" in cfg.lidar_list else "lidar2"
    if cfg.steps_controller.source == "vision":
        cfg.lidar_list = []
        cfg.processor.undistort_crop = True
    return cfg


def make_default_settings():
    cfg = CN()
    cfg.cam_list =  ["cam0", "cam2", "cam3", "cam4", "cam5", "cam6", "cam7"]
    cfg.lidar_list = ["lidar0", "lidar1"]
    cfg.slice_interval = 1
    cfg.strict_valid = True
    cfg.profile = False
    cfg.ips_deploy = True
    cfg.ppu_deploy = False
    cfg.use_h265_png = False
    cfg.record_type = "SENSOR_CLIP_RECORD_TYPE"         # use 'SENSOR_CLIP_RECORD_TYPE' or 'SUBRUN_RECORD_TYPE'
    cfg.use_raw_localpose = True                        # use xminer localpose or not
    cfg.pretrained_model_path = "/workspace/group_share/adc-sim/users/zf/recon_pretrained_models/"
    cfg.static_recon_oss_path = "prelabel_gxodips_visionsimips_*"  # "prelabel_playground_yuhangl/"
    cfg.enable_canbus_topic = False
    cfg.canbus_topic_list = ["DynamicXNetTopic"]
    cfg.steps_controller = CN()
    cfg.steps_controller.source = "lidar"        # use 'lidar' or 'vision'
    cfg.steps_controller.overwrite_dump = False         # if overwrite the dumped files from dataloader if exist
    cfg.steps_controller.json_processor = True          # process json inputs
    cfg.steps_controller.img_processor = True
    cfg.steps_controller.range_processor = True
    cfg.steps_controller.opt_processor = True
    cfg.steps_controller.colmap_processor = False
    cfg.steps_controller.run_rig_bundle_adjuster = False
    cfg.steps_controller.lidar_processor = True
    cfg.steps_controller.point_processor = True
    cfg.steps_controller.point_densifier = True
    cfg.steps_controller.depth_processor = True
    cfg.steps_controller.grdsurfel_processor = True
    cfg.steps_controller.trafficlight_processor = True
    cfg.steps_controller.g3r_processor = True
    cfg.steps_controller.evosplat_processor = True
    cfg.steps_controller.gsm_processor = True
    cfg.steps_controller.sam3d_processor = True
    cfg.steps_controller.lidar_densify_line = False
    cfg.steps_controller.pose_processor = True
    cfg.steps_controller.vision_data_fetcher = False
    cfg.steps_controller.ground_processor = True
    cfg.steps_controller.mvsnet_processor = True
    cfg.steps_controller.pcd_fusion_processor = True

    cfg.filter = CN()
    cfg.filter.min_data_len = 19
    cfg.filter.min_localpose_traj_len = 8
    cfg.filter.raise_on_smooth_pose_error = True

    cfg.opt_processor = CN()
    cfg.opt_processor.use_superglue = False
    cfg.opt_processor.use_dpvo = True
    cfg.opt_processor.use_lidaropt = False

    cfg.ground_processor = CN()
    cfg.ground_processor.method = "rogs"  # use 'rogs' or 'rome'
    cfg.ground_processor.z_weight_from_mvsnet = 0.
    cfg.ground_processor.oss_config = "rogs_config_20251219.yaml"

    cfg.mvsnet_processor = CN()
    cfg.mvsnet_processor.method = "mvsa"
    cfg.mvsnet_processor.mode = "parking"

    cfg.camopt = CN()
    cfg.camopt.network = "/workspace/group_share/adc-sim/users/zf/optimization_models/dpvo.pth"
    cfg.camopt.name = "campose"
    cfg.camopt.stride = 1
    cfg.camopt.skip = 0
    cfg.camopt.num_align = 50
    cfg.camopt.qa_mask_ratio = 0.8
    cfg.camopt.qa_continuous_fail_num = 10
    cfg.lidaropt = CN()
    cfg.lidaropt.num_pcd_cvt = 50
    cfg.lidaropt.model_path = "/workspace/group_share/adc-sim/users/zf/optimization_models"

    cfg.depth_processor = CN()
    cfg.depth_processor.normal_max_distance = 40                  # max valid distance for normal image
    cfg.depth_processor.depth_max_distance = 100                  # max valid distance for depth image
    cfg.depth_processor.depth_generator_voxel_size = 0.02         # for depth image generation
    cfg.depth_processor.depth_source = "complete"                 # generate depth image from 'complete' pcd or single 'pcd'
    cfg.depth_processor.reproj_conf_min = 0.6                     # minimum confidence threshold for reprojection

    cfg.processor = CN()
    cfg.processor.expand_ratio = CN({
        "cam0": 1.0,
        "cam2": 1.0,
        "cam3": 1.0,
        "cam4": 1.0,
        "cam5": 1.0,
        "cam6": 1.0,
        "cam7": 1.0
    })
    cfg.processor.object_bbox_src = "dxnet"                 # use 'sf' or 'dxnet'
    cfg.processor.undistort_crop = True
    cfg.processor.use_origin_mask = True
    cfg.processor.colmap_features = 8000
    cfg.processor.colmap_parser_src = "triangulated"        # use 'triangulated' or 'created'
    cfg.processor.colmap_pose_threshold = 0.1               # threshold for colmap pose filtering
    cfg.processor.object_voxel_size = 0.02
    cfg.processor.object_downsample_threshold = 30000       # if object points > threshold, downsample
    cfg.processor.lidar_points_valid_range = [[-30, 60], [-40, 40], [-2, 30]]
    cfg.processor.lidar_voxel_size_init = 0.2               # 以此参数生成第一版ply，用于生成深度图（背景暂不开启）
    cfg.processor.lidar_voxel_size_final = 0.2              # 以此参数生成最终ply，用gs训练
    cfg.processor.lidar_voxel_size_ground_init = 0.01       # 以此参数生成第一版ply，用于生成深度图
    cfg.processor.lidar_voxel_size_ground_final = 0.05      # 以此参数生成最终ply，用gs训练
    cfg.processor.vision_voxel_size = 0.2                   # for background points
    cfg.processor.vision_voxel_size_ground = 0.01           # for ground points

    cfg.projection = CN()
    cfg.projection.proj_lidar_to_img = False
    cfg.projection.proj_area = [24] # proj road marker
    cfg.projection.source_cam = ['cam2'] # source lidar
    cfg.projection.target_cam = ['cam5'] # target image

    cfg.XData = CN()
    cfg.XData.config = CN()
    cfg.XData.config.data_cache = "/dataset_perf1/simulation/"  # "/dataset/occupancy"
    cfg.XData.config.data_dir = "/dataset/downloader_v2/repository"
    cfg.XData.config.allow_use_cache_only = False

    cfg.trigger_time_offset_map = CN({
        "摆动/蛇形": {"takeover": 10, "issue": 5},
        "变道/绕行不合理": {"takeover": 10, "issue": 5},
        "不加速/加速慢": {"takeover": 10, "issue": 5},
        "不减速/制动不足": {"takeover": 5, "issue": 3},
        "不居中/贴边": {"takeover": 10, "issue": 5},
        "方向盘摆动/抖动": {"takeover": 5, "issue": 3},
        "跟/停距离远": {"takeover": 5, "issue": 3},
        "红绿灯相关问题": {"takeover": 5, "issue": 3},
        "加减速顿挫": {"takeover": 10, "issue": 5},
        "路口路径不合理": {"takeover": 10, "issue": 5},
        "逆向目标避让不足": {"takeover": 5, "issue": 3},
        "危险变道/绕行": {"takeover": 5, "issue": 3},
        "未及时变道/绕行": {"takeover": 15, "issue": 10},
        "压线": {"takeover": 10, "issue": 5},
        "异常减速": {"takeover": 5, "issue": 3},
        "撞路沿/障碍物": {"takeover": 5, "issue": 3},
        "不发起导航变道/过晚": {"takeover": 10, "issue": 5},
        "进逆向车道": {"takeover": 10, "issue": 5},
        "溜车": {"takeover": 5, "issue": 3},
        "不礼让行人": {"takeover": 5, "issue": 3},
        "主辅路/分合流未跟导航": {"takeover": 10, "issue": 5},
        "路口通行未跟导航": {"takeover": 10, "issue": 5},
    })
    return cfg


def make_default_env():
    os.environ["CUDA_VISIBLE_DEVICES"] = '0'


def make_cfg(cfg_file, default_cfg):
    with open(cfg_file, 'r') as f:
        current_cfg = yacs.load_cfg(f)

    cfg_list = [deepcopy(default_cfg) for i in range(len(current_cfg.datasets))]
    for i in range(len(current_cfg.datasets)):
        cfg_list[i].merge_from_other_cfg(CN(current_cfg.datasets[i]))
    return cfg_list, current_cfg


def get_config_list(make_env=True):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config",
        default='/root/repo/models/street_gaussians/configs/run_preprocess.yaml', type=str
    )
    args = parser.parse_args()

    if make_env:
        make_default_env()

    cfg = make_default_settings()
    cfg_list, current_cfg = make_cfg(args.config, cfg)

    print("======================= CURRENT CONFIG =====================")
    print(current_cfg)
    print("============================================================")
    print("======================= DEFAULT CONFIG =====================")
    print(cfg)
    print("============================================================")
    return cfg_list


