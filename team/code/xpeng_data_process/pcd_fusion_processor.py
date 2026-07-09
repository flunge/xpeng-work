import os
import json
import yaml
import numpy as np
import cv2
import open3d as o3d


class PcdFusionProcessor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.clip_path = self.cfg.clip_path
        self.transform_json = json.load(open(os.path.join(self.clip_path, "transform.json"), "r"))
        self.mode = self.cfg.mvsnet_processor.mode
        self.exp_dir = os.path.join(self.clip_path, "vision/recon")
        self.recon_config = os.path.join(self.exp_dir, 'config.yaml')
        
        # mvsnet_config_path = os.path.join(self.exp_dir, 'mvsnet_config.yaml')
        # if os.path.exists(mvsnet_config_path):
        #     self.mvsnet_config = load_mvsnet_config(mvsnet_config_path)
        # else:
        #     print(f"[WARNING] mvsnet_config.yaml not found, using default config")
        #     self.mvsnet_config = None
        
        ori_world_to_new_world_path = os.path.join(self.exp_dir, "ground_output", "ori_world_to_new_world.npy")
        if os.path.exists(ori_world_to_new_world_path):
            mvsnet_to_bev = np.load(ori_world_to_new_world_path)
            self.mvsnet_to_bev_matrix = mvsnet_to_bev
            print("[INFO] Computed mvsnet_to_bev transformation")
        else:
            self.mvsnet_to_bev_matrix = np.eye(4)
            print("[INFO] Using identity matrix for mvsnet_to_bev transformation")
        
        self.save_mvsnet_grd_pcd = True
        self.use_rogs_bev_height = False

    def process_pcd_fusion(self):
        self.read_mvsnet_pcd()
        # self.read_ground_pcd()
        self.fuse_pcds()

    def read_mvsnet_pcd(self):
        mvsnet_pcd_path = os.path.join(self.clip_path, "misc/mvsnet/mvsnet_final.ply")
        mvsnet_pcd = o3d.t.io.read_point_cloud(mvsnet_pcd_path)
        self.mvsnet_pcd = mvsnet_pcd

    def read_ground_pcd(self):
        ground_pcd_path = os.path.join(self.clip_path, 'road_mesh_new.ply')
        ground_pcd = o3d.t.io.read_point_cloud(ground_pcd_path)
        self.ground_pcd = ground_pcd

    def fuse_pcds(self):
        self.split_ground_obstacle_points()

    def split_ground_obstacle_points(self):
        mvsnet_pcd = self.mvsnet_pcd
        pcd_copy = mvsnet_pcd.clone()
        origin_points = pcd_copy.point.positions.cpu().numpy()
        origin_seg = pcd_copy.point.semantic.cpu().numpy()
        
        mvsnet_pcd.transform(self.mvsnet_to_bev_matrix)
        
        valid_ground = np.isin(origin_seg, [10, 13, 41, 7, 8, 14, 23, 24]).all(axis=1)

        bev_height_path_npy = f'{self.exp_dir}/ground_output/images/final/bev_height.npy'
        bev_height_path_npz = f'{self.exp_dir}/ground_output/images/final/bev_height.npz'
        
        if not self.use_rogs_bev_height or (not os.path.exists(bev_height_path_npy) and not os.path.exists(bev_height_path_npz)):
            print(f"[WARNING] Not using rogs bev_height, filter only mvsnet valid ground points")
            valid_ground = origin_points[valid_ground]
            combined = valid_ground
        else:
            if os.path.exists(bev_height_path_npy):
                bev_height_path = bev_height_path_npy
            else:
                print(f"[WARNING] bev_height.npy not found, using bev_height.npz")
                bev_height_path = bev_height_path_npz
            
            if bev_height_path.endswith('.npy'):
                bev_height = np.load(bev_height_path)
            elif bev_height_path.endswith('.npz'):
                import scipy.sparse as sp
                loaded = np.load(bev_height_path)
                sp_matrix = sp.csr_matrix((loaded['data'], loaded['indices'], loaded['indptr']), shape=loaded['shape'])
                bev_height = sp_matrix.toarray()
            
            bev_seg = cv2.imread(f"{self.exp_dir}/ground_output/bev_seg.png", cv2.IMREAD_UNCHANGED)
            
            with open(self.recon_config, 'r') as f:
                recon_config = yaml.safe_load(f)
            bev_resolution = recon_config.get("bev_resolution", 0.02)
            
            scale = 1.0 / bev_resolution
            transformation = o3d.core.Tensor([
                [scale, 0, 0, 0],
                [0, scale, 0, 0],
                [0, 0, 1, 0],
                [0, 0, 0, 1]
            ], dtype=o3d.core.float64)
            
            mvsnet_pcd.transform(transformation)
            points = mvsnet_pcd.point.positions.cpu().numpy()
            points_mask = (points[:,0] > 1) & \
                          (points[:,0] < (bev_height.shape[1] - 2)) & \
                          (points[:,1] > 1) & \
                          (points[:,1] < (bev_height.shape[0] - 2))
            points = points[points_mask]
            
            ground_heights = bev_height[
                ((bev_height.shape[0] - points[:,1]).astype(int)),
                ((points[:,0]).astype(int))
            ]
            seg_labels = bev_seg[
                ((bev_seg.shape[0] - points[:,1]).astype(int)),
                ((points[:,0]).astype(int))
            ]
            
            if seg_labels.shape[-1] == 4:
                seg_labels = seg_labels[:, :3]
            
            ground_mask = np.logical_or(
                (seg_labels == [255, 0, 0]).all(axis=1),
                (seg_labels == [211, 211, 211]).all(axis=1)
            )
            ground_mask = np.logical_and(ground_mask, points[:,2] < (ground_heights + 0.1))
            
            ground_point = origin_points[points_mask][ground_mask]
            valid_ground = origin_points[valid_ground]
            combined = np.vstack((valid_ground, ground_point))
        
        combined_set = set(map(tuple, combined))
        obstacle_point = np.array([tuple(point) not in combined_set for point in origin_points])
        obstacle_pcd = pcd_copy.select_by_index(np.where(obstacle_point)[0])
        # obstacle_pcd = statistic_filter(self.mvsnet_config, obstacle_pcd)
        # obstacle_pcd = cluster_filter(self.mvsnet_config, obstacle_pcd)
        obstacle_pcd.transform(np.linalg.inv(self.mvsnet_to_bev_matrix))
        o3d.t.io.write_point_cloud(f"{self.cfg.clip_path}/obstacle_points_new.ply", obstacle_pcd)

        if self.save_mvsnet_grd_pcd:
            ground_pcd_mvsnet = pcd_copy.select_by_index(np.where(~obstacle_point)[0])
            ground_pcd_mvsnet.transform(np.linalg.inv(self.mvsnet_to_bev_matrix))
            o3d.t.io.write_point_cloud(f"{self.cfg.clip_path}/ground_points_new.ply", ground_pcd_mvsnet)

        print(f"[INFO] Ground and obstacle point clouds separated and saved")

if __name__ == "__main__":
    from settings.config import make_default_settings, make_case_specific_settings
    clip_ids = {
        "c-2ae824c3-c5e8-3204-9ab9-64d9d5dfe595": "vision",
    }
    for clip, folder in clip_ids.items():
        cfg = make_default_settings()
        cfg.ips_deploy = False
        cfg.dataset_name = "reconic_vision_test0925"
        cfg.root = f"/workspace/zhouf4@xiaopeng.com/datasets/xpeng/{folder}"
        cfg.steps_controller.source = "vision"
        cfg.steps_controller.vision_data_fetcher = False
        cfg.steps_controller.pcd_fusion_processor = True
        cfg.steps_controller.ground_processor = True
        cfg.steps_controller.mvsnet_processor = True
        cfg.steps_controller.opt_processor = True
        cfg.clip_id = clip
        cfg.use_raw_localpose = True
        cfg.processor.undistort_crop = True
        cfg.processor.expand_ratio.cam0 = 1.
        cfg.processor.expand_ratio.cam2 = 1.
        cfg.processor.expand_ratio.cam3 = 1.
        cfg.processor.expand_ratio.cam4 = 1.
        cfg.processor.expand_ratio.cam5 = 1.
        cfg.processor.expand_ratio.cam6 = 1.
        cfg.processor.expand_ratio.cam7 = 1.
        cfg = make_case_specific_settings(cfg)

        pcd_fusion_processor = PcdFusionProcessor(cfg)
        pcd_fusion_processor.process_pcd_fusion()
        print(f"[INFO] PcdFusionProcessor finish processing clip {cfg.clip_id} in {cfg.root}")
