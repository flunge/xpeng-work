import numpy as np
from pathlib import Path

from utils.calib_utils import get_calibration, load_localpose_and_anchorpose_from_json
from utils import colmap_utils
from utils.file_utils import timer


class ColmapParser:
    def __init__(self, cfg, src=None, vision_mode=False):
        self.cfg = cfg
        self.recon_base = Path(cfg.clip_path) / "colmap"
        self.calib_path = Path(cfg.clip_path) / "calib.json"
        self.autolabe_path = Path(cfg.clip_path) / "autolabel_json"
        self.src = cfg.processor.colmap_parser_src if src is None else src
        self.target_lidar = cfg.target_lidar
        
        self.localpose, self.anchorpose = load_localpose_and_anchorpose_from_json(cfg.clip_path)
        self.calibrations = get_calibration(self.calib_path, cfg.target_lidar, vision_mode=vision_mode)

        self.recon_dir = self.recon_base / f"{self.src}/sparse/model"
        if self.src == "triangulated":
            self.im_id_to_image = colmap_utils.read_images_binary(self.recon_dir / "images.bin")
        elif self.src == "created":
            self.im_id_to_image = colmap_utils.read_images_text(self.recon_dir / "images.txt")
        else:
            raise ValueError(f"Unknown colmap source: {self.src}. Use 'triangulated' or 'created' instead.")

        self.timestamps = {}
        for im in self.im_id_to_image:
            cam_id = self.im_id_to_image[im].camera_id
            if cam_id not in self.timestamps:
                self.timestamps[cam_id] = {}

            timestamp = Path(self.im_id_to_image[im].name).stem
            self.timestamps[cam_id][timestamp] = im

        self.cam2anchor_dict = {cam_id: {} for cam_id in self.timestamps}
        self.rig2anchor_dict = {cam_id: {} for cam_id in self.timestamps}
        self.anchor2rig_dict = {cam_id: {} for cam_id in self.timestamps}
        self.cam_name2id = {
            self.calibrations._cam_list[i]: i+1 for i in range(len(self.calibrations._cam_list))
        }

    def compute_localpose_from_colmap(self):
        for cam_id in self.timestamps:
            cam_name = self.calibrations._cam_list[cam_id-1]
            for timestamp in self.timestamps[cam_id]:
                im_id = self.timestamps[cam_id][timestamp]
                im_data = self.im_id_to_image[im_id]            
                rotation = colmap_utils.qvec2rotmat(im_data.qvec)
                translation = im_data.tvec.reshape(3, 1)
                anchor2cam = np.concatenate([rotation, translation], 1)
                anchor2cam = np.concatenate([anchor2cam, np.array([[0, 0, 0, 1]])], 0)
                cam2anchor = np.linalg.inv(anchor2cam)
                rig2cam = self.calibrations._cam_from_rig[cam_name]
                rig2anchor = cam2anchor @ rig2cam

                self.cam2anchor_dict[cam_id][timestamp] = cam2anchor
                self.rig2anchor_dict[cam_id][timestamp] = rig2anchor
                self.anchor2rig_dict[cam_id][timestamp] = np.linalg.inv(rig2anchor)

    def get_lidar2anchor(self, lidar_frame, used_cam_id=2):
        if used_cam_id == None:
            return np.array(lidar_frame["transform_matrix"])
        timestamp = str(lidar_frame["timestamp"])
        rig2anchor = self.rig2anchor_dict[used_cam_id][timestamp]
        lidar2rig = self.calibrations._lidar2rig
        lidar2anchor = rig2anchor @ lidar2rig
        return lidar2anchor, rig2anchor

    def get_camera2anchor(self, camera_frame, use_colmap=True):
        if not use_colmap:
            return np.array(camera_frame["transform_matrix"])
        timestamp = str(camera_frame["timestamp"])
        cam_id = self.cam_name2id[camera_frame["camera"]]
        cam2anchor = self.cam2anchor_dict[cam_id][timestamp]
        return cam2anchor

    @timer
    def get_colmap_points_as_points3D(self, file_name="points3D.bin"):
        path = self.recon_dir / file_name
        if path.suffix == ".bin":
            return colmap_utils.read_points3D_binary_as_points3D(path)
        elif path.suffix == ".txt":
            return colmap_utils.read_points3D_text_as_points3D(path)
        else:
            raise ValueError(f"Unknown file extension {path.suffix}")

    @timer
    def get_colmap_points(self, file_name="points3D.bin"):
        path = self.recon_dir / file_name
        if path.suffix == ".bin":
            return colmap_utils.read_points3D_binary(path)
        elif path.suffix == ".txt":
            return colmap_utils.read_points3D_text(path)
        else:
            raise ValueError(f"Unknown file extension {path.suffix}")

    def _plot_localpose_colmap(self):
        from matplotlib import pyplot as plt
        plt.rcParams.update({'font.size': 15})
        fig, axs = plt.subplots(2, 2, figsize=(19.2, 10.8), dpi=100)
        
        # local pose from transform json
        timestamps = sorted(list(self.timestamps[2].keys()))
        local_time = np.array([(int(i) - int(timestamps[0])) / 1e9 for i in timestamps])
        local_poses = []

        world2anchor = np.linalg.inv(self.anchorpose)
        for timestamp in timestamps:
            rig2world = np.array(self.localpose[timestamp]).reshape(4, 4)
            # anchor2rig = np.linalg.inv(world2anchor @ rig2world)
            rig2anchor = world2anchor @ rig2world
            local_poses.append(rig2anchor[:3, 3])
        local_poses = np.array(local_poses)
        axs[0, 0].scatter(local_poses[:,0], local_poses[:,1], label=f"local pose", s=5)
        axs[0, 1].scatter(local_time, local_poses[:,0], label=f"local pose", s=5)
        axs[1, 0].scatter(local_time, local_poses[:,1], label=f"local pose", s=5)
        axs[1, 1].scatter(local_time, local_poses[:,2], label=f"local pose", s=5)

        for cam_id in self.rig2anchor_dict:
            timestamps = sorted(list(self.rig2anchor_dict[cam_id].keys()))
            translations = []
            for timestamp in timestamps:
                translations.append(self.rig2anchor_dict[cam_id][timestamp][:3, 3])
                
            translations = np.array(translations)

            axs[0, 0].plot(translations[:,0], translations[:,1], label=f"cam{cam_id}")
            axs[0, 0].set_title('translation x-y')
            axs[0, 1].plot(local_time, translations[:,0], label=f"cam{cam_id}")
            axs[0, 1].set_title('translation x in local time [s]')
            axs[1, 0].plot(local_time, translations[:,1], label=f"cam{cam_id}")
            axs[1, 0].set_title('translation y in local time [s]')
            axs[1, 1].plot(local_time, translations[:,2], label=f"cam{cam_id}")
            axs[1, 1].set_title('translation z in local time [s]')

        for a in axs.flatten():
            a.legend()

        plt.savefig("colmap_localpose.png")
        plt.close()
