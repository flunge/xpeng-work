from pathlib import Path
from lib.utils import colmap_utils as colmap_utils
import numpy as np
import json, yaml
import os
import tqdm


def load_yaml(config_path):
    with open(config_path, 'rb') as f:
        config = yaml.safe_load(f)
    return config


def get_files_in_folder(folder_path):
    file_paths = []
    for root, _, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            file_paths.append(file_path)
    return file_paths


def parser_autolabel_json(files_path, select_box_info):
    file_paths = get_files_in_folder(files_path)
    annotations = {}
    slice2timestamp = {}

    for i in tqdm.tqdm(range(len(file_paths))):
        file = file_paths[i]
        with open(file, "r") as fout:
            meta = json.load(fout)
            time_stamp = meta["frame_info"]["time_stamp"].get("cam2", None)
            slice_id = meta["frame_info"].get("uuid", None)
            slice2timestamp[slice_id] = time_stamp
            if time_stamp == None:
                print(f"file not own time_stamp {file}")
            local_pose = np.eye(4)
            local_pose[:3,:3] = meta["ego_info"]["rotation_enu_to_rig"]
            local_pose[:3,3] = meta["ego_info"]["translation_enu_to_rig"]
            local_pose = np.linalg.inv(local_pose)
            objs = []
            for obj in meta["mod_list"]:
                if "mod_3d" not in obj or select_box_info not in obj["mod_3d"]:
                    continue
                obj_info = obj["mod_3d"][select_box_info]
                size = [obj_info["length"] ,obj_info["width"] ,obj_info["height"]]
                translation = [obj_info["x"] ,obj_info["y"] ,obj_info["z"]]
                rotation = [obj_info["quaternion"]["w"],\
                            obj_info["quaternion"]["x"],\
                            obj_info["quaternion"]["y"],\
                            obj_info["quaternion"]["z"]]
                gid = obj["mod_3d"]["track_id"]
                type = obj["mod_3d"]["category"]

                vx = obj["mod_3d"]["velocity"]["world_formula"]["x"]
                vy = obj["mod_3d"]["velocity"]["world_formula"]["y"]
                credible = obj["mod_3d"]["velocity"]["credible"]
                vector = np.array([vx, vy])
                norm_2 = np.linalg.norm(vector)
                is_moving = True if norm_2 >0.5 and credible else False
                objs.append({"type":type ,\
                    "gid":gid ,\
                    "translation":translation ,\
                    "size":size ,\
                    "rotation":rotation ,\
                    "is_moving":is_moving
                })
            annotations[str(time_stamp)]={
                "objects" : objs,\
                "local_pose" : local_pose.tolist()
            }
    return annotations, file_paths, slice2timestamp


class Calibrations:

    @classmethod
    def __init__(self, config_path, new_mode=False):
        self.config_path = config_path
        self._calibrations = load_yaml(self.config_path)
        self._cam_list = ['cam0', 'cam2', 'cam3', 'cam4', 'cam5', 'cam6', 'cam7']
        self._cam_from_rig = {}
        for cam_id in self._cam_list:
            self._cam_from_rig[cam_id] = np.array(self._calibrations[cam_id]['extrinsic']['transformation_matrix']).reshape(4, 4)
            if new_mode:
                self._calibrations[cam_id]["intrinsic"] = self._calibrations["new"+cam_id]["intrinsic"]

        # lidar_extrinsic = self._calibrations['lidar2']['extrinsic']['transformation_matrix']
        # lidar_extrinsic = np.array(lidar_extrinsic).reshape(4, 4)
        # self._lidar2rig = np.linalg.inv(lidar_extrinsic)

        self._local_pose = self._calibrations['local_pose']

        return


class ColmapConverter:
    def __init__(self, preprocessed_base, src=1):
        self.recon_base = preprocessed_base / "colmap"
        self.calib_path = preprocessed_base / "calib.json"
        
        self.calibrations = Calibrations(self.calib_path, True)

        self.slice2timestamp = None
        if src == 1:
            self.recon_dir = self.recon_base / "triangulated/sparse/model"
            self.im_id_to_image = colmap_utils.read_images_binary(self.recon_dir / "images.bin")
        else:
            self.recon_dir = self.recon_base / "created/sparse/model"
            self.im_id_to_image = colmap_utils.read_images_text(self.recon_dir / "images.txt")

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

    def get_c2w(self, cam_name, timestamp):
        cam_id = self.cam_name2id[cam_name]
        return self.cam2anchor_dict[cam_id][timestamp]

    def _replace_pose_info_with_autolabel(self, annotations, calibrations):
        frames_timestamp = sorted(list(annotations.keys()))
        for frame_timestamp in frames_timestamp:
            auto_label_info = annotations[frame_timestamp]
            calibrations._local_pose[frame_timestamp] = auto_label_info["local_pose"]