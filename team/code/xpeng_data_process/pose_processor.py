import os
import json
import numpy as np
import open3d as o3d
from scipy.spatial import KDTree
from dataclasses import dataclass
from utils.calib_utils import get_localpose_based_on_the_first_frame


@dataclass
class PoseInfo:
    timestamp: str
    translation: list
    rotation: list
    is_moving: bool


class PoseProcessor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.pose_info_dict = {}
        self.annotation_autolabel_box = None

    def process_pose_smooth(self):
        self.read_annotation()
        self.get_obj_pose_info()
        # for static object
        self.average_static_poses()
        # for dynamic object
        if self.cfg.steps_controller.source == "vision":
            self.process_sliding_window_smooth()

        if self.cfg.processor.object_bbox_src == 'sf':
            self.compute_obj_height()

        self.dump_annotation_json()

    def read_annotation(self):
        with open(os.path.join(self.cfg.clip_path, "annotation_for_train.json"), 'r') as file:
            self.annotation_autolabel_box = json.load(file)
        return

    def get_obj_pose_info(self):
        for frame in self.annotation_autolabel_box['frames']:
            timestamp = int(frame['timestamp'])
            for obj in frame['objects']:
                gid = obj['gid']
                if gid not in self.pose_info_dict:
                    self.pose_info_dict[gid] = []
                self.pose_info_dict[gid].append(PoseInfo(timestamp, obj['translation'], obj['rotation'], obj['is_moving']))

        for gid in self.pose_info_dict:
            self.pose_info_dict[gid].sort(key=lambda x: x.timestamp)
        return

    def compute_robust_speed_threshold(self, pose_infos, k_mad=3.0):
        if len(pose_infos) < 3:
            return 30.0  # fallback

        speeds = []
        for i in range(1, len(pose_infos)):
            dt = (pose_infos[i].timestamp - pose_infos[i-1].timestamp) * 1e-9
            if dt < 1e-6:
                continue
            disp = np.linalg.norm(
                np.array(pose_infos[i].translation) - np.array(pose_infos[i-1].translation)
            )
            speed = disp / dt
            speeds.append(speed)
        
        if len(speeds) == 0:
            return 30.0

        speeds = np.array(speeds)
        
        # 鲁棒估计：中位数 + MAD（正态分布下 1 MAD ≈ 0.6745 σ）
        median_speed = np.median(speeds)
        mad = np.median(np.abs(speeds - median_speed))
        sigma_est = 1.4826 * mad

        # 动态阈值：中位数 + k * sigma_est
        dynamic_threshold = median_speed + k_mad * sigma_est
        
        return max(dynamic_threshold, 10.0)  # 至少 10 m/s

    def process_sliding_window_smooth(self):
        window_length = 7
        for gid, pose_infos in self.pose_info_dict.items():
            pose_infos.sort(key=lambda x: x.timestamp)

            max_speed = self.compute_robust_speed_threshold(pose_infos, k_mad=3.0)
            max_speed_buffer_thres = max_speed * 1.2

            sum_count = 0
            sum_trans = np.array([0.0, 0.0, 0.0])
            prev_time = None
            for idx in range(0, len(pose_infos)):
                curr_trans = np.array(pose_infos[idx].translation)
                curr_time = pose_infos[idx].timestamp

                if not pose_infos[idx].is_moving:
                    sum_count = 0
                    sum_trans = np.array([0.0, 0.0, 0.0])
                if prev_time is not None and (pose_infos[idx].timestamp - prev_time) * 1e-9 > 0.15:
                    sum_count = 0
                    sum_trans = np.array([0.0, 0.0, 0.0])
                
                if prev_time is not None and prev_trans is not None:
                    dt = (curr_time - prev_time) * 1e-9
                    if dt > 1e-6:
                        disp = np.linalg.norm(curr_trans - prev_trans)
                        speed = disp / dt
                        if speed > max_speed_buffer_thres:
                            sum_count = 0
                            sum_trans = np.zeros(3)

                prev_time = curr_time
                prev_trans = curr_trans
                sum_count += 1
                sum_trans += np.array(pose_infos[idx].translation)

                if sum_count == window_length:
                    smooth_xyz = sum_trans / window_length
                    smooth_time = pose_infos[idx - int(window_length // 2)].timestamp

                    for frame in self.annotation_autolabel_box['frames']:
                        if frame['timestamp'] == str(smooth_time):
                            for obj in frame['objects']:
                                if obj['gid'] == gid:
                                    obj['translation'] = smooth_xyz.tolist()
                                    break
                            break

                    sum_count -= 1
                    sum_trans -= np.array(pose_infos[idx - window_length + 1].translation)
        return

    def average_static_poses(self):
        for gid, pose_infos in self.pose_info_dict.items():
            pose_infos.sort(key=lambda x: x.timestamp)

            static_group = []
            static_start_idx = None
            for idx, pose_info in enumerate(pose_infos):
                if pose_info.is_moving:
                    if static_group:
                        self.average_and_update(gid, static_group, static_start_idx)
                        static_group = []
                        static_start_idx = None
                else:
                    if not static_group:
                        static_start_idx = idx
                    static_group.append(pose_info)

            if static_group:
                self.average_and_update(gid, static_group, static_start_idx)

    def average_and_update(self, gid, static_group, start_idx):
        if len(static_group) > 1:
            translations = np.array([pose.translation for pose in static_group])
            max_xyz = np.max(translations, axis=0)
            min_xyz = np.min(translations, axis=0)
            delta_xyz = max_xyz - min_xyz

            if (self.cfg.steps_controller.source == "lidar" and delta_xyz[0] < 0.3 and delta_xyz[1] < 0.3 and delta_xyz[0] < 0.2) or\
                self.cfg.steps_controller.source == "vision":
                self.average_pose_helper(static_group, translations, gid)
            else:
                # check multi-stage static
                sub_group = []
                for pose in static_group:
                    smooth_tag = self.checkpose_smooth(sub_group, np.array(pose.translation))
                    if smooth_tag:
                        sub_group.append(pose)
                    else:
                        # smooth sub group
                        self.process_sub_group(sub_group, gid)

                        # process curr pose
                        self.change_pose_moving(pose.timestamp, gid)
                        sub_group.clear()
                
                if len(sub_group) > 0:
                    self.process_sub_group(sub_group, gid)
        return

    def process_sub_group(self, sub_group, gid):
        if len(sub_group) > 2:
            translations = np.array([curr_pose.translation for curr_pose in sub_group])
            self.average_pose_helper(sub_group, translations, gid)
        else:
            for curr_pose in sub_group:
                self.change_pose_moving(curr_pose.timestamp, gid)
        return

    def change_pose_moving(self, timestamp, gid):
        for frame in self.annotation_autolabel_box['frames']:
            if frame['timestamp'] == str(timestamp):
                for obj in frame['objects']:
                    if obj['gid'] == gid:
                        obj['is_moving'] = True
        return

    def average_pose_helper(self, pose_group, trans_xyz, gid):
        avg_translation = trans_xyz.mean(axis=0).tolist()
        quaternions = np.array([pose.rotation for pose in pose_group])
        avg_quaternion = np.mean(quaternions, axis=0)
        norm = np.sqrt(np.sum(avg_quaternion ** 2))
        if norm > 0:
            avg_quaternion /= norm

        for pose in pose_group:
            for frame in self.annotation_autolabel_box['frames']:
                if frame['timestamp'] == str(pose.timestamp):
                    for obj in frame['objects']:
                        if obj['gid'] == gid:
                            obj['translation'] = avg_translation
                            obj['rotation'] = avg_quaternion.tolist()
                            break
                    break
        return

    def checkpose_smooth(self, sub_pose_group, curr_xyz):
        if len(sub_pose_group) == 0:
            return True

        translations = np.array([pose.translation for pose in sub_pose_group])
        max_xyz = np.max(translations, axis=0)
        min_xyz = np.min(translations, axis=0)
        delta_max = np.linalg.norm(max_xyz - curr_xyz)
        delta_min = np.linalg.norm(min_xyz - curr_xyz)
        if delta_max > 0.05 or delta_min > 0.05:
            return False

        if len(sub_pose_group) > 1:
            prev_xyz = np.array(sub_pose_group[-2].translation)
            curr_xyz = np.array(sub_pose_group[-1].translation)
            delta_length = np.linalg.norm(curr_xyz - prev_xyz)
            if delta_length > 0.03:
                return False
        return True

    def compute_obj_height(self, max_radius = 8, knn = 10):
        localpose = json.load(open(os.path.join(self.cfg.clip_path, "localpose.json"), "r"))
        localpose_anchored, _ = get_localpose_based_on_the_first_frame(localpose)

        ground_points_pcd = o3d.io.read_point_cloud(os.path.join(self.cfg.clip_path, "road_mesh_new.ply"))
        ground_points_xyz = np.asarray(ground_points_pcd.points, dtype=np.float32)
        xy_points = ground_points_xyz[:, :2]
        ground_kdtree = KDTree(xy_points)

        object_previous_heights = {}

        for frame in self.annotation_autolabel_box['frames']:
            timestamp = frame["timestamp"]
            rig_xyz = np.array(localpose_anchored[timestamp])[:3, 3]

            for obj in frame['objects']:
                gid = obj['gid']
                obj_xyz = np.array(obj['translation'])
                if np.linalg.norm(obj_xyz - rig_xyz) < 10.0:
                    continue
    
                queries_xy = obj_xyz[:2].reshape(1, -1)
                dists, idx = ground_kdtree.query(queries_xy, k = knn)
                output_height = []
                for i in range(len(dists[0])):
                    if dists[0][i] <= max_radius:
                        output_height.append(ground_points_xyz[idx[0][i], 2])
                
                if len(output_height) > 5:
                    obj['translation'][2] = float((sum(output_height) / len(output_height) + obj['size'][2] * 0.5))
                    object_previous_heights[gid] = obj['translation'][2]
                elif gid in object_previous_heights:
                    obj['translation'][2] = object_previous_heights[gid]
                # 如果gid不在缓存中且没有足够地面点，则保持原高度不变
        return


    def dump_annotation_json(self):
        with open(os.path.join(self.cfg.clip_path, "annotation_for_train.json"), "w") as f:
            json.dump(self.annotation_autolabel_box, f, indent=4)


if __name__ == "__main__":
    from settings.config import make_default_settings, make_case_specific_settings
    clip_ids = {
        "c-00492193-5f4c-37c4-9f61-cde8acf79eb3": "fm_pose",
    }

    for clip, folder in clip_ids.items():
        cfg = make_default_settings()
        cfg.ips_deploy = False
        cfg.dataset_name = "selected_clips_m1"
        cfg.root = "/workspace/dusc@xiaopeng.com/online_data/data_1209_sf"
        cfg.steps_controller.source = "vision"
        cfg.clip_id = clip
        cfg.processor.object_bbox_src = "sf"
        cfg = make_case_specific_settings(cfg)

        pose_processor = PoseProcessor(cfg)
        pose_processor.process_pose_smooth()
        print(f"[INFO] PoseProcessor finish processing clip {cfg.clip_id} in {cfg.root}")