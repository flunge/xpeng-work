import os
import random
import json
from torch.utils.data import Dataset as TorchDataset

from lib.utils.camera_utils import Camera
from lib.utils.camera_utils import camera_to_JSON, cameraList_from_camInfos, cameraList_generated_cams
from lib.utils.camera_utils import load_camera_on_demand
from lib.config import cfg
from lib.datasets.base_readers import storePly, SceneInfo
from lib.datasets.colmap_readers import readColmapSceneInfo
from lib.datasets.blender_readers import readNerfSyntheticInfo
from lib.datasets.waymo_full_readers import readWaymoFullInfo
from lib.datasets.xpeng_full_readers import readXpengFullInfo


sceneLoadTypeCallbacks = {
    "Colmap": readColmapSceneInfo,
    "Blender" : readNerfSyntheticInfo,
    "Waymo": readWaymoFullInfo,
    "Xpeng": readXpengFullInfo
}

class Dataset():
    def __init__(self, load_cameras=True):
        self.cfg = cfg.data
        self.model_path = cfg.model_path
        self.source_path = cfg.source_path
        self.images = self.cfg.images

        self.train_cameras = {}
        self.test_cameras = {}

        dataset_type = cfg.data.get('type', "Colmap")
        assert dataset_type in sceneLoadTypeCallbacks.keys(), 'Could not recognize scene type!'
        
        scene_info: SceneInfo = sceneLoadTypeCallbacks[dataset_type](self.source_path, **cfg.data)

        if cfg.mode == 'train':
            pcd = scene_info.point_cloud_dict
            for name, sub_pcd in pcd.items():
                if sub_pcd is not None:
                    storePly(os.path.join(self.model_path, f"input_{name}.ply"), sub_pcd.points, sub_pcd.colors)

            json_cams = []
            camlist = []
            if scene_info.test_cameras:
                camlist.extend(scene_info.test_cameras)
            if scene_info.train_cameras:
                camlist.extend(scene_info.train_cameras)
            for id, cam in enumerate(camlist):
                json_cams.append(camera_to_JSON(id, cam))

            print(f'Saving input camera to {os.path.join(self.model_path, "cameras.json")}')
            with open(os.path.join(self.model_path, "cameras.json"), 'w') as file:
                json.dump(json_cams, file)
       
        self.scene_info = scene_info
        
        if self.cfg.shuffle and cfg.mode == 'train':
            random.shuffle(self.scene_info.train_cameras)  # Multi-res consistent random shuffling
            random.shuffle(self.scene_info.test_cameras)  # Multi-res consistent random shuffling

        if load_cameras:
            self.load_cameras()

    def load_cameras(self):
        print("========= Start loading camera info and pictures =========")
        resolution_scale = 1
        self.train_cameras[resolution_scale] = self.scene_info.train_cameras
        self.test_cameras[resolution_scale] = cameraList_from_camInfos(self.scene_info.test_cameras, 1)

    def load_cameras_novel_image(self):
        for resolution_scale in cfg.resolution_scales:
            print(f"Loading Training Cameras {len(self.scene_info.train_cameras)}")
            self.train_cameras[resolution_scale] = cameraList_generated_cams(self.scene_info.train_cameras, resolution_scale)
            print(f"Loading Test Cameras {len(self.scene_info.test_cameras)}")
            self.test_cameras[resolution_scale] = cameraList_from_camInfos(self.scene_info.test_cameras, resolution_scale)


class CameraDataset(TorchDataset):
    def __init__(self, dataset: Dataset, split: str = 'train'):
        super().__init__()
        self.dataset = dataset
        self.split = split
        self.cam7_sample_rate = int(cfg.data.get('cam7_sample_rate_before_pos_optim', 1))
        self.cam7_sampled_count = 0
        self.iteration = 0
        
        # 根据 split 获取相机元数据
        if self.split == 'train':
            self.camera_infos = self.dataset.scene_info.train_cameras
        elif self.split == 'test':
            self.camera_infos = self.dataset.scene_info.test_cameras
        else:
            raise ValueError(f"不支持的 split 类型: {self.split}")
    
    def set_iteration(self, iteration):
        self.iteration = iteration

    def __len__(self):
        return len(self.camera_infos)

    def __getitem__(self, idx) -> Camera:
        # 按需加载单个相机数据
        camera_info = self.camera_infos[idx]
        if self.iteration < cfg.optim.position_lr_max_steps and camera_info.metadata['cam'] == 'cam7':
            if self.cam7_sampled_count % self.cam7_sample_rate == 0:
                self.cam7_sampled_count += 1
                return load_camera_on_demand(camera_info, resolution_scale=1) 
            else:
                return None
        else:
            return load_camera_on_demand(camera_info, resolution_scale=1) 
        