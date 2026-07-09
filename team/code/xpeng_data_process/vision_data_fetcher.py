import os,cv2
import json
import numpy as np
import tarfile, lz4.frame
import oss2
from utils.oss_utils import download_file_from_oss2, listdir_from_oss2, check_obj_folder_exist
from utils.oss_utils import get_bucket_vision, get_bucket


class VisionDataFetcher:
    def __init__(self, cfg):
        self.cfg = cfg
        self.used_files = [
            "colmap_sparse_model.tar.lz4",
            "localpose_and_timestamp.tar.lz4",
            # "fine_dynamic_masks.tar.lz4",
            # "image.tar.lz4",
            "poses_new.tar.lz4",
            
            "obstacle_points_new.ply",
            "road_mesh_new.ply",
            "ground_points_new.ply",
            "interpolated_pose_new.json"
        ]
        if self.cfg.static_recon_oss_path is None or self.cfg.static_recon_oss_path == "prelabel_zf/":
            self.cfg.static_recon_oss_path = "prelabel_zf/"
            self.bucket = get_bucket() # use sim bucket
        else:
            self.bucket = get_bucket_vision()
        target_key = self.check_if_clip_exist()
        assert target_key is not None, f"[ERROR] Clip {self.cfg.clip_id} not exist in vision data"

        self.target_key = os.path.join(target_key, "simulator_render") + "/"
        assert check_obj_folder_exist(self.bucket, self.target_key), \
            f"[ERROR] Clip {self.cfg.clip_id} do not have simulation render"    

    def fetch_vision_data(self):
        self.download_vision_data()
        self.reorganize_vision_data()

    def check_if_clip_exist(self):
        clip_id = self.cfg.clip_id
        object_key = self.cfg.static_recon_oss_path
        
        # 如果路径包含通配符，需要先找到匹配的文件夹
        if "*" in object_key:
            # 获取所有以prelabel_gxodips_visionsimips_开头的文件夹
            prefix = object_key.replace("*", "")
            all_folders = []
            
            # 使用delimiter来获取文件夹列表
            for obj in oss2.ObjectIterator(self.bucket, prefix="", delimiter="/"):
                if obj.is_prefix():
                    folder_name = obj.key.rstrip('/')
                    if folder_name.startswith(prefix):
                        all_folders.append(folder_name + "/")
            
            # 在所有匹配的文件夹中查找clip_id
            for folder in all_folders:
                all_clips_path = listdir_from_oss2(self.bucket, folder, vision=True)
                all_clips = [i.split("/")[-2] for i in all_clips_path]
                if clip_id in all_clips:
                    target = all_clips_path[all_clips.index(clip_id)]
                    target_key = os.path.join(target, "simulator_render") + "/"
                    if check_obj_folder_exist(self.bucket, target_key):
                        return target
        else:
            # 原来的逻辑：直接使用指定的object_key
            all_clips = listdir_from_oss2(self.bucket, object_key, vision=True)
            for i in all_clips:
                if clip_id in i and i[-1] == "/":
                    return i
        return None
    
    def download_vision_data(self):
        clip_id = self.cfg.clip_id
        local_dir = os.path.join(self.cfg.root, clip_id)
        os.makedirs(local_dir, exist_ok=True)
        all_files = listdir_from_oss2(self.bucket, self.target_key)
        for i in all_files:
            if i.split("/")[-1] not in self.used_files:
                continue
            local_filename = os.path.join(local_dir, i.split("/")[-1])
            download_file_from_oss2(local_filename, i, self.bucket, show_progress=False)
            if ".tar.lz4" in i:
                with open(local_filename, 'rb') as lz4_file:
                    with lz4.frame.open(lz4_file, mode='rb') as decompressed_file:
                        # Read the decompressed data and treat it as a tar file
                        with tarfile.open(fileobj=decompressed_file, mode='r') as tar:
                            # Extract all contents to the specified directory
                            tar.extractall(path=local_dir)
                os.system(f"rm {local_filename}")
            print(f"[INFO] Vision data {i.split('/')[-1]} fetch successfully")
        print(f"[INFO] Vision data of {clip_id} downloaded successfully!")

    def reorganize_vision_data(self):
        meta_info = json.load(open(os.path.join(self.cfg.clip_path, "metadata.json")))
        vehicle_name = meta_info["vehicle_name"]
        clip_timestamp = meta_info["start_time"]

        # reoganize the colmap
        mask_path = os.path.join(self.cfg.clip_path, "colmap_sparse_model", vehicle_name, str(clip_timestamp))
        colmap_dir = os.path.join(self.cfg.clip_path, 'colmap','triangulated', 'sparse')
        os.makedirs(colmap_dir, exist_ok=True)
        os.system(f"mv {mask_path} {os.path.join(colmap_dir, 'model')}")
        os.system(f"rm {os.path.join(self.cfg.clip_path, 'colmap_sparse_model')} -r")
        
        os.system(f"cp {os.path.join(self.cfg.clip_path, 'calib.json')} {os.path.join(self.cfg.clip_path, 'calib_origin.json')}")


if __name__ == "__main__":
    from settings.config import make_default_settings, make_case_specific_settings
    cfg = make_default_settings()
    cfg.root = "/workspace/yangxh7@xiaopeng.com/datasets/xpeng/fm_vision/"
    cfg.steps_controller.source = "vision"
    cfg.static_recon_oss_path = None # "prelabel_gxodips_visionsimips_*"
    clip_ids = """
        c-114a3a61-77e3-3e51-a95f-7af5bdaf071d
        c-fbc5c7d2-83c3-3f30-b17a-c134201c6a92
    """
    clip_ids = clip_ids.split()
    valid_clip_ids = []
    for clip_id in clip_ids:
        cfg.clip_id = clip_id
        cfg = make_case_specific_settings(cfg)
        try:
            fetcher = VisionDataFetcher(cfg)
            valid_clip_ids.append(clip_id)
        except Exception as e:
            print(f"[ERROR] Failed to find data for {clip_id}: {e}")
        else:
            print(f"[INFO] Found data for {clip_id}")
        # fetcher.fetch_vision_data()
        # break
    print(f"[INFO] Valid clip ids: {valid_clip_ids}")
