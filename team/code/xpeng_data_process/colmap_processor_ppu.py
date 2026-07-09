import json
import os
import sqlite3
import numpy as np
from scipy.spatial.transform import Rotation as R
from copy import deepcopy

from utils.fuyao_utils import run_cmd_and_log
from utils.colmap_parser import ColmapParser


class PPUColmapProcessor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.images_moved = False
        self.colmap_dir = os.path.join(cfg.clip_path, "colmap")
        self.colmap_model_dir = f'{self.colmap_dir}/created/sparse/model'
        os.makedirs(self.colmap_model_dir, exist_ok=True)

        self.transform_json = None
        self.camera_infos = dict()
        self.c2w_dict = dict()
        self.unique_cams = dict()
        
        self.db_id_names = []
        self.db_cam_to_id = dict()
    
    def run_colmap(self):
        self.load_transform_json()
        self.run_feature_extractor()
        self.overwrite_colmap_db()
        self.create_colmap_inputs()
        self.run_sequential_matcher()
        self.run_point_triangulator()
        self.run_rig_bundle_adjuster()
        self.replace_transform_json_with_colmap()

    def load_transform_json(self):
        self.transform_json = json.load(open(os.path.join(self.cfg.clip_path, "transform.json")))
        self.unique_cams = self.transform_json['sensor_params']['camera_order']

        if self.cfg.processor.colmap_pose_threshold > 0.:
            # localpose is a list of dicts with key, a string of int timestamp, and 'transform_matrix' of list as value
            localpose = json.load(open(os.path.join(self.cfg.clip_path, "localpose.json")))
            all_timestamps = sorted([int(i) for i in list(localpose.keys())])
            # find poses with translation > threshold
            valid_timestamps = [all_timestamps[0]]
            for i in range(1, len(all_timestamps)):
                pose1 = np.array(localpose[str(valid_timestamps[-1])])[:3, 3]
                pose2 = np.array(localpose[str(all_timestamps[i])])[:3, 3]
                if np.linalg.norm(pose2 - pose1) > self.cfg.processor.colmap_pose_threshold:
                    valid_timestamps.append(all_timestamps[i])
            print(f"[INFO] ColmapProcessor: valid timestamps after filtering: {len(valid_timestamps)}/{len(all_timestamps)}")
            if len(valid_timestamps) < 2:
                raise ValueError(f"[ERROR] ColmapProcessor valid timestamps after filtering is less than 2, "\
                                 f"please check the threshold {self.cfg.processor.colmap_pose_threshold}.")
            elif len(valid_timestamps) != len(all_timestamps):
                self.images_moved = True
                images_dir = os.path.join(self.cfg.clip_path, "images")
                for cam_name in self.unique_cams:
                    os.makedirs(os.path.join(self.cfg.clip_path, "images_temp", cam_name), exist_ok=True)
                    
                for timestamp in all_timestamps:
                    if timestamp not in valid_timestamps:
                        for cam_name in self.unique_cams:
                            # move images to colmap folder
                            name = f'{timestamp:010d}.png'
                            src_path = os.path.join(images_dir, cam_name, name)
                            dst_path = os.path.join(self.cfg.clip_path, "images_temp", cam_name)
                            os.system(f'mv {src_path} {dst_path}')
                
        for frame in self.transform_json['frames']:
            timestamp = frame['timestamp']
            if self.cfg.processor.colmap_pose_threshold > 0 and timestamp not in valid_timestamps:
                continue
            name = frame['file_path'].replace('images/', '')
            self.c2w_dict[name] = frame['transform_matrix']
        
        for cam_name in self.unique_cams:
            img_h = self.transform_json['sensor_params'][cam_name]['height']
            img_w = self.transform_json['sensor_params'][cam_name]['width']
            ixt = np.array(self.transform_json['sensor_params'][cam_name]['camera_intrinsic'])
            self.camera_infos[cam_name] = {
                'ixt': ixt,
                'img_h': img_h,
                'img_w': img_w,
            }

    def run_feature_extractor(self):
        mask_dir = os.path.join(self.cfg.clip_path, "masks_obj")
        images_dir = os.path.join(self.cfg.clip_path, "images")
        cmd = f'/tmp/colmap/build/src/colmap/exe/colmap feature_extractor \
            --SiftExtraction.max_num_features {self.cfg.processor.colmap_features} \
            --ImageReader.mask_path {mask_dir} \
            --ImageReader.camera_model PINHOLE  \
            --ImageReader.single_camera_per_folder 1 \
            --database_path {self.colmap_dir}/database.db \
            --image_path {images_dir}'
        print("[INFO] Colmap run feature_extractor:", flush=True)
        run_cmd_and_log(cmd)
        if self.images_moved:
            # move images back to original folder
            for cam_name in self.unique_cams:
                src_path = os.path.join(self.cfg.clip_path, "images_temp", cam_name)
                dst_path = os.path.join(images_dir, cam_name)
                os.system(f'mv {src_path}/* {dst_path}')
            os.system(f'rm -rf {self.cfg.clip_path}/images_temp')
            self.images_moved = False

    def overwrite_colmap_db(self):
        # read database
        db = f'{self.colmap_dir}/database.db'
        conn = sqlite3.connect(db)
        c = conn.cursor()
        c.execute('SELECT * FROM images')
        result = c.fetchall()
        for i in result:
            name = i[1]
            cam = name.split('/')[0]
            cam_id = i[2]
            self.db_cam_to_id[cam] = cam_id
            self.db_id_names.append([int(i[0]), name])

        # update database
        for cam_name in self.unique_cams:
            cam_id = self.db_cam_to_id[cam_name]
            ixt = self.camera_infos[cam_name]['ixt']
            fx, fy, cx, cy = ixt[0, 0], ixt[1, 1], ixt[0, 2], ixt[1, 2]
            params = np.array([fx, fy, cx, cy]).astype(np.float64)
            c.execute("UPDATE cameras SET params = ? WHERE camera_id = ?",
                (params.tobytes(), cam_id))
        conn.commit()
        conn.close()

    def create_colmap_inputs(self):
        # create images.txt
        with open(f'{self.colmap_model_dir}/images.txt','w') as f_w:
            for i in range(len(self.db_id_names)):
                id_ = self.db_id_names[i][0]
                name = self.db_id_names[i][1]
                transform = self.c2w_dict[name]
                transform = np.linalg.inv(transform)

                r = R.from_matrix(transform[:3,:3])
                rquat = r.as_quat()  # The returned value is in scalar-last (x, y, z, w) format.
                rquat[0], rquat[1], rquat[2], rquat[3] = rquat[3], rquat[0], rquat[1], rquat[2]
                out = np.concatenate((rquat, transform[:3, 3]), axis=0)

                cam = name.split('/')[0]

                f_w.write(f'{id_} ')
                f_w.write(' '.join([str(a) for a in out.tolist()] ) )
                f_w.write(f' {self.db_cam_to_id[cam]} {name}')
                f_w.write('\n\n')
        
        # create cameras.txt
        with open(os.path.join(self.colmap_model_dir, 'cameras.txt'), 'w') as f_w:
            for cam_name in self.unique_cams:
                camera_info = self.camera_infos[cam_name]
                ixt = camera_info['ixt']
                img_w = camera_info['img_w']
                img_h = camera_info['img_h']
                fx = ixt[0, 0]
                fy = ixt[1, 1]
                cx = ixt[0, 2]
                cy = ixt[1, 2]
                f_w.write(f'{self.db_cam_to_id[cam_name]} PINHOLE {img_w} {img_h} {fx} {fy} {cx} {cy}')
                f_w.write('\n')
        
        # create points3D.txt
        points3D_fn = os.path.join(self.colmap_model_dir, 'points3D.txt')
        os.system(f'touch {points3D_fn}')

        # create rid ba config
        cam_rigid = dict()
        rigid_cam_list = []
        ref_camera_name = self.unique_cams[1]   # cam2
        cam_rigid["ref_camera_id"] = self.db_cam_to_id[ref_camera_name] 
        extrinsics = self.transform_json['sensor_params']
        for cam_name in self.unique_cams:
            rigid_cam = dict()
            rigid_cam["camera_id"] = self.db_cam_to_id[cam_name]

            ref_extrinsic = extrinsics[ref_camera_name]['extrinsic']
            cur_extrinsic = extrinsics[cam_name]['extrinsic']
            rel_extrinsic = np.linalg.inv(cur_extrinsic) @ ref_extrinsic

            r = R.from_matrix(rel_extrinsic[:3, :3])
            qvec = r.as_quat()

            rigid_cam["image_prefix"] = cam_name
            rigid_cam['cam_from_rig_rotation'] = [qvec[3], qvec[0], qvec[1], qvec[2]]
            rigid_cam['cam_from_rig_translation'] = [rel_extrinsic[0, 3], rel_extrinsic[1, 3], rel_extrinsic[2, 3]]
            
            rigid_cam_list.append(rigid_cam)

        cam_rigid["cameras"] = rigid_cam_list
        rigid_config_path = os.path.join(self.colmap_dir, "cam_rigid_config.json")
        with open(rigid_config_path, "w+") as f:
            json.dump([cam_rigid], f, indent=4)

    def run_exhaustive_matcher(self):
        cmd = f'/tmp/colmap/build/src/colmap/exe/colmap exhaustive_matcher \
            --SiftMatching.max_num_matches {self.cfg.processor.colmap_features*2} \
            --database_path {self.colmap_dir}/database.db'
        print("[INFO] Colmap run exhaustive_matcher:", flush=True)
        run_cmd_and_log(cmd)
    
    def run_sequential_matcher(self):
        cmd = f'/tmp/colmap/build/src/colmap/exe/colmap sequential_matcher \
            --SiftMatching.max_num_matches {self.cfg.processor.colmap_features*2} \
            --database_path {self.colmap_dir}/database.db'
        print("[INFO] Colmap run sequential_matcher:", flush=True)
        run_cmd_and_log(cmd)

    def run_point_triangulator(self):
        triangulated_dir = os.path.join(self.colmap_dir, 'triangulated/sparse/model')
        images_dir = os.path.join(self.cfg.clip_path, "images")
        os.makedirs(triangulated_dir, exist_ok=True)

        cmd = f'/tmp/colmap/build/src/colmap/exe/colmap point_triangulator \
            --database_path {self.colmap_dir}/database.db \
            --image_path {images_dir} \
            --input_path {self.colmap_model_dir} \
            --output_path {triangulated_dir} \
            --Mapper.ba_refine_focal_length 0 \
            --Mapper.ba_refine_principal_point 0 \
            --Mapper.ba_refine_extra_params 0 \
            --Mapper.max_extra_param 0 \
            --clear_points 0 \
            --Mapper.ba_global_max_num_iterations 1'
            # --Mapper.ba_global_max_num_iterations 30 \
            # --Mapper.filter_max_reproj_error 4 \
            # --Mapper.filter_min_tri_angle 0.5 \
            # --Mapper.tri_min_angle 0.5 \
            # --Mapper.tri_ignore_two_view_tracks 1 \
            # --Mapper.tri_complete_max_reproj_error 4 \
            # --Mapper.tri_continue_max_angle_error 4'
        print("[INFO] Colmap run point_triangulator:", flush=True)
        run_cmd_and_log(cmd)
    
    def run_rig_bundle_adjuster(self):
        if self.cfg.steps_controller.run_rig_bundle_adjuster and self.cfg.processor.colmap_pose_threshold < 1e-8:
            triangulated_dir = os.path.join(self.colmap_dir, 'triangulated/sparse/model')
            rigid_config_path = os.path.join(self.colmap_dir, "cam_rigid_config.json")
            cmd = f'/tmp/colmap/build/src/colmap/exe/colmap rig_bundle_adjuster \
                --input_path {triangulated_dir} \
                --output_path {triangulated_dir} \
                --rig_config_path {rigid_config_path} \
                --estimate_rig_relative_poses 0 \
                --RigBundleAdjustment.refine_relative_poses 1 \
                --BundleAdjustment.max_num_iterations 50 \
                --BundleAdjustment.refine_focal_length 0 \
                --BundleAdjustment.refine_principal_point 0 \
                --BundleAdjustment.refine_extra_params 0'
            print("[INFO] Colmap run rig_bundle_adjuster:", flush=True)
            run_cmd_and_log(cmd)
        else:
            print("[INFO] steps_controller.run_rig_bundle_adjuster is False, skip colmap rig_bundle_adjuster.")
    
    def replace_transform_json_with_colmap(self):
        if self.cfg.steps_controller.run_rig_bundle_adjuster:
            os.system(f"cp {self.cfg.clip_path}/transform.json {self.cfg.clip_path}/transform_before_colmap.json")
            transform_json_new = deepcopy(self.transform_json)
            colmap_parser = ColmapParser(self.cfg, src='triangulated')
            colmap_parser.compute_localpose_from_colmap()
            for transform_frame in self.transform_json['frames']:
                cam2world = colmap_parser.get_camera2anchor(transform_frame, use_colmap=True)
                transform_json_new['transform_matrix'] = cam2world.tolist()
            json.dump(transform_json_new, open(os.path.join(self.cfg.clip_path, "transform.json"), 'w'), indent=4)
