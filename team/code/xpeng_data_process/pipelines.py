import time
import os

from json_processor import JsonProcessor
from img_processor import ImgProcessor
from colmap_processor_ppu import PPUColmapProcessor
from colmap_processor import ColmapProcessor
from lidar_processor import LidarProcessor
from point_processor import PointProcessor
from point_densifier import PointDensifier
from depth_processor import DepthProcessor
from grdsurfel_processer import GrdSurfelProcessor
from vision_data_fetcher import VisionDataFetcher
from pose_processor import PoseProcessor
from ground_processor import GroundProcessor
from mvsnet_processor import MvsnetProcessor
from pcd_fusion_processor import PcdFusionProcessor
from trafficlight_processor import TrafficLightExtractor
from evosplat_processer import EvoSplatProcessor
from sam3d_processor import SAM3DProcessor
from utils.diag_utils import log_resource_status


def pipeline_m1_lidar_cpu(cfg, timing_dict=None):
    ################# Step 1: input jsons
    print("============================================================")
    print(f"######### [INFO] Start processing json inputs of {cfg.clip_id}")
    if cfg.steps_controller.json_processor:
        json_processor = JsonProcessor(cfg)
        json_processor.process_input_json()
    else:
        print(f"######### [INFO] Skip processing json inputs")

    ################# Step 2: process pose smooth
    print("============================================================")
    print(f"######### [INFO] Start processing pose smooth of {cfg.clip_id}")
    if cfg.steps_controller.pose_processor:
        pose_processor = PoseProcessor(cfg)
        pose_processor.process_pose_smooth()
    else:
        print(f"######### [INFO] Skip processing pose processer")
    
    ################# Step 3: generate range.json
    print("============================================================")
    print(f"######### [INFO] Start generate range.json of {cfg.clip_id}")
    t2 = time.time()
    if cfg.steps_controller.range_processor:
        from range_processor import RangeProcessor
        range_processor = RangeProcessor(cfg)
    else:
        print(f"######### [INFO] Skip generate range.json")

def pipeline_m1_lidar_gpu(cfg, timing_dict=None):
    ################# Step 3: undistorted img, mask, seg
    print("============================================================")
    print(f"######### [INFO] Start processing images of {cfg.clip_id}")
    t1 = time.time()
    if cfg.steps_controller.img_processor:
        img_processor = ImgProcessor(cfg, load_seg=True)
        img_processor.process_undistort_parallel()
        img_processor.process_origin_imgs()
    else:
        print(f"######### [INFO] Skip processing images")

    ################# Step 4: process calib optimization
    print("============================================================")
    print(f"######### [INFO] Start processing calib optimization of {cfg.clip_id}")
    t2 = time.time()
    if cfg.steps_controller.opt_processor:
        from opt_processor import OptProcessor
        opt_processor = OptProcessor(cfg)
        opt_processor.process_optimization()
    else:
        print(f"######### [INFO] Skip processing calib optimization")

    ################# Step 2d: concat and extract lidar points
    print("============================================================")
    print(f"######### [INFO] Start processing lidar of {cfg.clip_id}")
    t3 = time.time()
    if cfg.steps_controller.lidar_processor:
        lidar_processor = LidarProcessor(cfg)
        if not cfg.projection.proj_lidar_to_img:
            lidar_processor.process_lidar()
        else:
            lidar_processor.process_lidar_projection()
    else:
        print(f"######### [INFO] Skip processing lidar")

    ################# Step 6: run colmap
    print("============================================================")
    print(f"######### [INFO] Start processing colmap of {cfg.clip_id}")
    t4 = time.time()
    if cfg.steps_controller.colmap_processor:
        if cfg.ppu_deploy:
            print(f"######### [INFO] ppu running")
            colmap_processor = PPUColmapProcessor(cfg)
        else:
            colmap_processor = ColmapProcessor(cfg)

        colmap_processor.run_colmap()
    else:
        print(f"######### [INFO] Skip processing colmap")

    ################# Step 7: generate point cloud for training
    print("============================================================")
    print(f"######### [INFO] Start processing points of {cfg.clip_id}")
    t5 = time.time()
    if cfg.steps_controller.point_processor:
        point_processor = PointProcessor(cfg)
        point_processor.process_training_points()
    else:
        print(f"######### [INFO] Skip processing points")

    if cfg.steps_controller.point_densifier:
        point_denser = PointDensifier(cfg)
        point_denser.process_densify()
    else:
        print(f"######### [INFO] Skip densify points")

    ################# Step 8: generate ground surfel
    print("============================================================")
    print(f"######### [INFO] Start processing ground surfel of {cfg.clip_id}")
    t6 = time.time()
    if cfg.steps_controller.grdsurfel_processor:
        grdsurfel_processor = GrdSurfelProcessor(cfg)
        grdsurfel_processor.process_surfel()
    else:
        print(f"######### [INFO] Skip processing ground surfel")

    ################# Step 9: generate depth image
    print("============================================================")
    print(f"######### [INFO] Start processing depth image of {cfg.clip_id}")
    t7 = time.time()
    if cfg.steps_controller.depth_processor:
        depth_processor = DepthProcessor(cfg)
        # depth_processor.process_depth() # street gussian 深度图，deprecated
        depth_processor.process_enhanced_depth() # 更好的深度图，稠密，深度遮挡，距离限制

        # 使用密集点云生成深度图后，需要降采样ply，降低点数以提升高斯重建速度
        if cfg.steps_controller.point_processor:
            point_processor = PointProcessor(cfg)
            point_processor.resample_ply_points()
    else:
        print(f"######### [INFO] Skip processing depth")

    ################# Step 10: run models/g3r
    print("============================================================")
    print(f"######### [INFO] Start processing models/g3r of {cfg.clip_id}")
    t8 = time.time()
    if cfg.steps_controller.g3r_processor:
        from g3r_processer import G3RProcessor
        g3r_processor = G3RProcessor(cfg)
        g3r_processor.process_g3r()
    else:
        print(f"######### [INFO] Skip processing models/g3r")

    ################# Step 11: generate traffic light point cloud for training
    print("============================================================")
    print(f"######### [INFO] Start processing generate traffic light of {cfg.clip_id}")
    t9 = time.time()
    if cfg.steps_controller.trafficlight_processor:
        lidar_processor = LidarProcessor(cfg)
        lidar_processor.read_all_pcds()  # Populate background_pcds
        extractor = TrafficLightExtractor(cfg, lidar_processor)
        extractor.process_all_frames()
    else:
        print(f"######### [INFO] Skip processing generate traffic light point cloud for training")
    if timing_dict is not None:
        timing_dict['img'] = t2 - t1
        timing_dict['opt'] = t3 - t2
        timing_dict['lidar'] = t4 - t3
        timing_dict['colmap'] = t5 - t4
        timing_dict['points'] = t6 - t5
        timing_dict['grdsurfel'] = t7 - t6
        timing_dict['depth'] = t8 - t7
        timing_dict['g3r'] = t9 - t8
        timing_dict['tfl'] = time.time() - t9
        print(f"######### [INFO] Timing info gpu {timing_dict}")


def pipeline_vision_cpu(cfg, info_dict=None):
    ################# Step 1: fetching mvsnet data
    print("============================================================")
    print(f"######### [INFO] Start fetching mvsnet output of {cfg.clip_id}")
    if cfg.steps_controller.vision_data_fetcher:
        vision_data_fetcher = VisionDataFetcher(cfg)
        vision_data_fetcher.fetch_vision_data()
    else:
        print(f"######### [INFO] Skip fetchinging vision data")

    ################# Step 2: input jsons
    print("============================================================")
    print(f"######### [INFO] Start processing json inputs of {cfg.clip_id}")
    if cfg.steps_controller.json_processor:
        json_processor = JsonProcessor(cfg)
        json_processor.process_input_json(info_dict)
    else:
        print(f"######### [INFO] Skip processing json inputs")

    ################# Step 3: generate range.json 
    if cfg.steps_controller.range_processor:
        from range_processor import RangeProcessor
        range_processor = RangeProcessor(cfg)
        print(f"######### [INFO] generate range over")  
    else:
        print(f"######### [INFO] Skip generate range.json")    

def pipeline_vision_gpu(cfg, timing_dict=None, fast_verification=False):
    t1 = time.time()
    log_resource_status("pipeline_start", cfg.clip_id)
    ################# Step 4: seg, mask
    print("============================================================")
    print(f"######### [INFO] Start processing images of {cfg.clip_id}")
    if cfg.steps_controller.img_processor:
        img_processor = ImgProcessor(cfg, load_seg=True)
        log_resource_status("step4_undistort_start", cfg.clip_id)
        img_processor.process_undistort_parallel()
        log_resource_status("step4_segs_start", cfg.clip_id)
        img_processor.process_segs_vision()
        log_resource_status("step4_lomm_start", cfg.clip_id)
        # img_processor.process_instance_seg_vision()
        img_processor.process_instance_seg_vision_lomm()
    else:
        print(f"######### [INFO] Skip processing images")
    t2 = time.time()
    log_resource_status("step4_img_done", cfg.clip_id)
    print(f"######### [TIMING] Finish processing images in {t2 - t1:.2f}s")

    ################# Step 5: process calib optimization
    print("============================================================")
    print(f"######### [INFO] Start processing calib optimization of {cfg.clip_id}")
    if cfg.steps_controller.opt_processor and not cfg.steps_controller.vision_data_fetcher:
        from opt_processor import OptProcessor
        log_resource_status("step5_opt_start", cfg.clip_id)
        opt_processor = OptProcessor(cfg)
        opt_processor.process_optimization()
        os.system(f"rm -r {os.path.join(cfg.clip_path, 'dyn_mask')}")
    else:
        print(f"######### [INFO] Skip processing calib optimization for vision")
    t3 = time.time()
    log_resource_status("step5_opt_done", cfg.clip_id)
    print(f"######### [TIMING] Finish processing calib optimization in {t3 - t2:.2f}s")

    ################# Step 6: run sam3d
    print("============================================================")
    print(f"######### [INFO] Start processing SAM3DProcessor of {cfg.clip_id}")
    if cfg.steps_controller.sam3d_processor:
        log_resource_status("step6_sam3d_start", cfg.clip_id)
        sam3d_process = SAM3DProcessor(cfg)
        sam3d_process.process()
        print(f"######### [INFO] processing SAM3DProcessor")
    else:
        print(f"######### [INFO] Skip processing SAM3DProcessor")
    t4 = time.time()
    log_resource_status("step6_sam3d_done", cfg.clip_id)
    print(f"######### [TIMING] Finish processing SAM3DProcessor in {t4 - t3:.2f}s")

    ################# Step 7: process mvsnet
    print("============================================================")
    print(f"######### [INFO] Start processing mvsnet of {cfg.clip_id}")
    if cfg.steps_controller.mvsnet_processor and not cfg.steps_controller.vision_data_fetcher:
        old_torch_compile_flag = os.environ.get('TORCH_COMPILE_DISABLE', '1')
        print(f"######### [INFO] Original TORCH_COMPILE flag: {old_torch_compile_flag}")
        old_torch_dynamo_report_flag = os.environ.get('TORCHDYNAMO_REPORT_GUARD_FAILURES', '1')
        print(f"######### [INFO] Original TORCHDYNAMO_REPORT_GUARD_FAILURES flag: {old_torch_dynamo_report_flag}")
        os.environ['TORCH_COMPILE_DISABLE'] = '1' 
        os.environ['TORCHDYNAMO_REPORT_GUARD_FAILURES']='1'
        log_resource_status("step7_mvsnet_start", cfg.clip_id)
        mvsnet_processor = MvsnetProcessor(cfg)
        mvsnet_processor.process_mvsnet()
        os.environ['TORCH_COMPILE_DISABLE'] = old_torch_compile_flag
        os.environ['TORCHDYNAMO_REPORT_GUARD_FAILURES'] = old_torch_dynamo_report_flag
    else:
        print(f"######### [INFO] Skip processing mvsnet processer")
    t5 = time.time()
    log_resource_status("step7_mvsnet_done", cfg.clip_id)
    print(f"######### [TIMING] Finish processing mvsnet in {t5 - t4:.2f}s")

    ################# Step 8: generate fused point cloud
    print("============================================================")
    print(f"######### [INFO] Start generating fused point cloud of {cfg.clip_id}")
    if cfg.steps_controller.pcd_fusion_processor and not cfg.steps_controller.vision_data_fetcher:
        log_resource_status("step8_fuse_start", cfg.clip_id)
        pcd_fusion_processor = PcdFusionProcessor(cfg)
        pcd_fusion_processor.process_pcd_fusion()
    else:
        print(f"######### [INFO] Skip generating fused point cloud")
    t6 = time.time()
    log_resource_status("step8_fuse_done", cfg.clip_id)
    print(f"######### [TIMING] Finish generating fused point cloud in {t6 - t5:.2f}s")

    ################# Step 9: generate point cloud for ground
    print("============================================================")
    print(f"######### [INFO] Start generating ground points of {cfg.clip_id}")
    if cfg.steps_controller.ground_processor and not cfg.steps_controller.vision_data_fetcher:
        log_resource_status("step9_ground_start", cfg.clip_id)
        ground_processor = GroundProcessor(cfg)
        ground_processor.process_ground_points()
        if cfg.ips_deploy:
            os.system(f"rm -r {os.path.join(cfg.clip_path, 'vision')}")
    else:
        print(f"######### [INFO] Skip generating ground points")
    t7 = time.time()
    log_resource_status("step9_ground_done", cfg.clip_id)
    print(f"######### [TIMING] Finish generating ground points in {t7 - t6:.2f}s")

    ################# Step 10: process pose smooth
    print("============================================================")
    print(f"######### [INFO] Start processing pose smooth of {cfg.clip_id}")
    if cfg.steps_controller.pose_processor:
        log_resource_status("step10_pose_start", cfg.clip_id)
        pose_processor = PoseProcessor(cfg)
        pose_processor.process_pose_smooth()
    else:
        print(f"######### [INFO] Skip processing pose processer")
    t8 = time.time()
    log_resource_status("step10_pose_done", cfg.clip_id)
    print(f"######### [TIMING] Finish processing pose smooth in {t8 - t7:.2f}s")

    ################# Step 11: run colmap
    print("============================================================")
    print(f"######### [INFO] Start processing colmap of {cfg.clip_id}")
    if cfg.steps_controller.colmap_processor and not cfg.steps_controller.vision_data_fetcher:
        log_resource_status("step11_colmap_start", cfg.clip_id)
        colmap_processor = ColmapProcessor(cfg)
        colmap_processor.run_colmap()
        os.system(f"rm {os.path.join(cfg.clip_path, 'colmap/database.db')}")
    else:
        print(f"######### [INFO] Skip processing colmap")
    t9 = time.time()
    log_resource_status("step11_colmap_done", cfg.clip_id)
    print(f"######### [TIMING] Finish processing colmap in {t9 - t8:.2f}s")

    ################# Step 12: generate point cloud for training
    print("============================================================")
    print(f"######### [INFO] Start processing points of {cfg.clip_id}")
    if cfg.steps_controller.point_processor:
        log_resource_status("step12_points_start", cfg.clip_id)
        point_processor = PointProcessor(cfg)
        point_processor.process_training_points()
    else:
        print(f"######### [INFO] Skip processing points")
    t10 = time.time()
    log_resource_status("step12_points_done", cfg.clip_id)
    print(f"######### [TIMING] Finish processing points in {t10 - t9:.2f}s")

    ################# Step 13: densify line points
    print("============================================================")
    print(f"######### [INFO] Start processing point_densifier of {cfg.clip_id}")
    if cfg.steps_controller.point_densifier:
        log_resource_status("step13_densify_start", cfg.clip_id)
        point_denser = PointDensifier(cfg)
        point_denser.process_densify()
    else:
        print(f"######### [INFO] Skip densify points")
    t11 = time.time()
    log_resource_status("step13_densify_done", cfg.clip_id)
    print(f"######### [TIMING] Finish densify line points in {t11 - t10:.2f}s")
    
    ################# Step 14: generate depth image
    print("============================================================")
    print(f"######### [INFO] Start processing depth image of {cfg.clip_id}")
    if cfg.steps_controller.depth_processor:
        log_resource_status("step14_depth_start", cfg.clip_id)
        depth_processor = DepthProcessor(cfg)
        depth_processor.process_depth_vision()
    else:
        print(f"######### [INFO] Skip processing depth")
    t12 = time.time()
    log_resource_status("step14_depth_done", cfg.clip_id)
    print(f"######### [TIMING] Finish processing depth image in {t12 - t11:.2f}s")

    ################# Step 15: run evolsplat
    print("============================================================")
    print(f"######### [INFO] Start processing evolsplat of {cfg.clip_id}")
    if cfg.steps_controller.evosplat_processor:
        log_resource_status("step15_evolsplat_start", cfg.clip_id)
        evosplat_process = EvoSplatProcessor(cfg)
        evosplat_process.process()
        print(f"######### [INFO] processing EvoSplatProcessor")
    t13 = time.time()
    log_resource_status("step15_evolsplat_done", cfg.clip_id)
    print(f"######### [TIMING] Finish processing evolsplat in {t13 - t12:.2f}s")

    ################# Step 16: run scube
    print("============================================================")
    print(f"######### [INFO] Start processing GSM background of {cfg.clip_id}")
    if fast_verification and cfg.steps_controller.gsm_processor:
        from gsm_processor import GSMProcessor
        log_resource_status("step16_gsm_start", cfg.clip_id)
        gsm_processor = GSMProcessor(cfg)
        gsm_processor.process()
        print(f"######### [INFO] processing GSM background")
    else:
        print(f"######### [INFO] Skip processing GSM background")
    if cfg.ips_deploy:
        os.system(f"rm -r {os.path.join(cfg.clip_path, 'images_vision')}")
        os.system(f"rm -r {os.path.join(cfg.clip_path, 'segs_vision')}")
    t14 = time.time()
    log_resource_status("step16_gsm_done", cfg.clip_id)
    print(f"######### [TIMING] Finish processing gsm in {t14 - t13:.2f}s")

    ################# Step 16: generate traffic light point cloud for training
    print("============================================================")
    print(f"######### [INFO] Start processing generate traffic light of {cfg.clip_id}")
    if cfg.steps_controller.trafficlight_processor:
        log_resource_status("step16b_tfl_start", cfg.clip_id)
        extractor = TrafficLightExtractor(cfg)
        extractor.process_all_frames()
    else:
        print(f"######### [INFO] Skip processing generate traffic light point cloud for training")
    t15 = time.time()
    log_resource_status("pipeline_done", cfg.clip_id)

    if timing_dict is not None:
        timing_dict['img'] = t2 - t1
        timing_dict['opt'] = t3 - t2
        timing_dict['sam3d'] = t4 - t3
        timing_dict['mvsnet'] = t5 - t4
        timing_dict['fuse'] = t6 - t5
        timing_dict['ground'] = t7 - t6
        timing_dict['smooth'] = t8 - t7
        timing_dict['colmap'] = t9 - t8
        timing_dict['points'] = t10 - t9
        timing_dict['densify'] = t11 - t10
        timing_dict['depth'] = t12 - t11
        timing_dict['evolsplat'] = t13 - t12
        timing_dict['scube'] = t14 - t13
        timing_dict['tfl'] = t15 - t14
        print(f"######### [INFO] Timing info gpu {timing_dict}")


def pipeline_pretrain_images(cfg):
    ################# Step 2a: input jsons
    print("============================================================")
    print(f"######### [INFO] Start processing json inputs of {cfg.clip_id}")
    json_processor = JsonProcessor(cfg)
    json_processor.process_input_json()

    ################# Step 2b: undistorted img
    print("============================================================")
    print(f"######### [INFO] Start processing images of {cfg.clip_id}")
    if cfg.steps_controller.img_processor:
        img_processor = ImgProcessor(cfg, load_seg=False)
        img_processor.process_pretrain_data()
    else:
        print(f"######### [INFO] Skip processing images")
