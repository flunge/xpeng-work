import os
import cv2
import json
import time
import copy
import torch
import random
import numpy as np
from PIL import Image
from typing import List, Dict
from scipy.ndimage import zoom
from concurrent.futures import ThreadPoolExecutor, as_completed

from dataclasses import dataclass, asdict
from collections import Counter, defaultdict

from sam3d.notebook.inference import Inference
from utils.sam3d_utils import compute_3d_proj, compute_iou, overlay_binary_masks_on_image
from utils.lomm_utils import gen_static_obj_segs

@dataclass
class IoUInfo:
    cam: str
    timestamp: int
    seg_ratio: float
    iou: float
    rect_info: tuple

@dataclass
class IoUInfoWithId:
    ins_id: int
    iou_info: IoUInfo

class SAM3DProcessor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.npy_folder = "instance_segs_id"
        self.ins_json_name = "lomm_meta.json"
        self.static_id_json = "static_obs_ids.json"
        self.debug_folder = "sam3d_debug"
        self.set_attention_backend()

        self.save_ply_folder = os.path.join(self.cfg.clip_path, "input_ply")
        os.makedirs(self.save_ply_folder, exist_ok=True)

        self.min_valid_iou = 0.3
        self.min_seg_ratio = 0.013
        self.com_ratio = 1.5
        self.frame_interval = 3
        self.huge_threshold = 6.0

        self.min_iou_for_sam3d = 0.5
        self.max_observation_each_cam = 3
        self.min_observation_for_sam3d = 2
        self.max_observation_for_sam3d = 3
        self.cam_list_for_corr = ["cam0", "cam2", "cam3", "cam4", "cam5", "cam6", "cam7"]

        self.debug_proj = False
        self.consistent_instance_id = True

        self.cameras_size = self.obtain_cameras_size()
        self.timestamp_slice_id = self.get_timestamp_with_slice_id()

        self.gid_3d_info = {}
        self.read_3d_object_info()

        self.cam_frames_info = {}
        self.read_cam_info()

        self.instance_seg_info = {}
        self.get_instance_seg_id()

        t1 = time.time()
        self.corr_id_dict = {} # dxnet-id : cam-name : IoUInfoWithId
        self.obtain_corr_id()
        self.save_2d_3d_corr(self.corr_id_dict, "2d_3d_corr.json")

        self.corr_id_dict_filter = copy.deepcopy(self.corr_id_dict)
        if self.consistent_instance_id:
            self.filter_with_instance_id()

        self.corr_id_dict_key_frames = {} # dxnet-id : cam-name : IoUInfoWithId
        self.select_key_frames()
        self.save_2d_3d_corr(self.corr_id_dict_key_frames, "2d_3d_corr_filtered.json")

        self.rect_id_dict = {}  # dxnet-id : IoUInfo
        self.add_no_consistency_rect()
        self.add_postprocess_rect()
        t2 = time.time()
        print("[SAM3D] Compute 2d 3d corr time: ", t2 - t1)

        self.sam3d_config_path = "/workspace/group_share/adc-sim/users/wangyd13/checkpoints/pipeline.yaml"
        self.init_sam3d()
        t3 = time.time()
        print("[SAM3D] Model init time: ", t3 - t2)

    def obtain_cameras_size(self):
        cameras_size = {}
        for cam in self.cam_list_for_corr:
            img_vision = cv2.imread(os.path.join(self.cfg.clip_path, "images_vision", "slice0_" + cam + ".png"))
            height, width, _ = img_vision.shape
            cameras_size[cam] = (width, height, width * height)
        return cameras_size

    def set_attention_backend(self):
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)

        # logger.info(f"GPU name is {gpu_name}")
        if "A100" in gpu_name or "H100" in gpu_name or "H200" in gpu_name:
            # logger.info("Use flash_attn")
            os.environ["ATTN_BACKEND"] = "flash_attn"
            os.environ["SPARSE_ATTN_BACKEND"] = "flash_attn"

    def produce_fake_data(self):
        ins_dir = os.path.join(self.cfg.clip_path, "instance_seg")
        img_list = os.listdir(ins_dir)
        for img_name in img_list:
            timestamp = img_name.split("_")[0]
            cam_name = img_name.split("_")[1]
            slice_id = self.timestamp_slice_id[timestamp]
            npy_path = os.path.join(ins_dir, f"slice{slice_id}_{cam_name}.npy")

            img_path = os.path.join(ins_dir, img_name)
            mask = cv2.imread(img_path)
            mask = mask[:, :, 0]
            mask[mask == 255] = 2
            np.save(npy_path, mask)

    def extract_unique_ids(self):
        json_path = os.path.join(self.cfg.clip_path, self.static_id_json)
        if not os.path.exists(json_path):
            return []

        with open(json_path, 'r') as f:
            data = json.load(f)
        all_ids = []
        for cam_list in data.values():
            all_ids.extend([int(id_str) for id_str in cam_list])

        unique_ids = sorted(list(set(all_ids)))
        return unique_ids

    def save_2d_3d_corr(self, id_dict, json_name):
        with open(os.path.join(self.cfg.clip_path, json_name), "w") as f:
            serialized_dict = self.serialize_dataclass(id_dict)
            json.dump(serialized_dict, f, indent=4, ensure_ascii=False)
        return

    def serialize_dataclass(self, obj):
        if isinstance(obj, dict):
            return {k: self.serialize_dataclass(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self.serialize_dataclass(item) for item in obj]
        elif hasattr(obj, '__dataclass_fields__'):
            return asdict(obj)
        else:
            return obj

    def init_sam3d(self):
        self.sam3d_inference = Inference(self.sam3d_config_path, compile=False)
        if self.sam3d_inference._pipeline.rendering_engine != "pytorch3d":
            self.sam3d_inference._pipeline.rendering_engine = "pytorch3d"

    def get_timestamp_with_slice_id(self):
        cam_folder = os.path.join(self.cfg.clip_path, "images/cam0")
        timestamps = []
        files = os.listdir(cam_folder)
        for filename in files:
            if filename.endswith('.png'):
                timestamps.append(int(filename.split(".")[0]))
        sorted_timestamps = sorted(timestamps)
        return {ts: sorted_timestamps.index(ts) for ts in timestamps}

    def get_instance_seg_id(self):
        with open(os.path.join(self.cfg.clip_path, self.ins_json_name), 'r') as file:
            self.instance_seg_info = json.load(file)
        return

    def read_3d_object_info(self):
        with open(os.path.join(self.cfg.clip_path, "annotation_for_train.json"), 'r') as file:
            annotation_data = json.load(file)

        for frame in annotation_data['frames']:
            timestamp = int(frame['timestamp'])
            for obj in frame['objects']:
                if obj['type'] == "pedestrian" or obj['type'] == "cyclist":
                    continue

                gid = obj['gid']
                if gid not in self.gid_3d_info:
                    self.gid_3d_info[gid] = {}

                self.gid_3d_info[gid][timestamp] = {
                    'translation': obj['translation'],
                    'size': obj['size'],
                    'rotation': obj['rotation']
                }
        return

    def read_cam_info(self):
        with open(os.path.join(self.cfg.clip_path, "calib.json"), 'r', encoding='utf-8') as file:
            calib_info = json.load(file)
        with open(os.path.join(self.cfg.clip_path, "transform.json"), 'r') as file:
            transform_data = json.load(file)

        for f in transform_data["frames"]:
            timestr = f.get("timestamp")
            cam_id = f.get("camera")
            if timestr is None or not cam_id:
                continue

            timestamp = int(timestr)
            T = np.array(f.get("transform_matrix", np.eye(4)), dtype=np.float64)
            R_cw = T[:3, :3]
            t_cw = T[:3, 3]
            R_world2cam = R_cw.T
            t_world2cam = -R_cw.T @ t_cw
 
            fl_x = calib_info[cam_id]["intrinsic"]["focal_length"]
            fl_y = calib_info[cam_id]["intrinsic"]["focal_length"]
            cx = calib_info[cam_id]["intrinsic"]["cx"]
            cy = calib_info[cam_id]["intrinsic"]["cy"]
            K = np.array([[fl_x, 0.0, cx], [0.0, fl_y, cy], [0.0, 0.0, 1.0]], dtype=np.float64)

            if timestamp not in self.cam_frames_info:
                self.cam_frames_info[timestamp] = {}
            self.cam_frames_info[timestamp][cam_id] = {
                "K": K,
                "R_world2cam": R_world2cam,
                "t_world2cam": t_world2cam,
            }
        return

    def _process_corr_task(self, gid, cam, timestr):
        timestamp = int(timestr)
        if timestamp not in self.cam_frames_info or cam not in self.cam_frames_info[timestamp]:
            return None

        slice_name = f"slice{self.timestamp_slice_id[timestamp]}_{cam}"
        # 0: background
        npy_path = os.path.join(self.cfg.clip_path, self.npy_folder, slice_name + ".npy")
        if not os.path.exists(npy_path):
            return None

        seg_img = np.load(npy_path)
        height, width = seg_img.shape
        proj_mask, rect_info = compute_3d_proj(self.gid_3d_info[gid][timestamp], self.cam_frames_info[timestamp][cam], width, height)
        if rect_info is None:
            return None
        rect_ratio = float(rect_info[2] * rect_info[3]) / float(seg_img.size)
        if rect_ratio < self.min_seg_ratio:
            return None

        ins_iou_dict = {}
        instance_id_list = self.instance_seg_info[cam][timestr]
        for ins_id in instance_id_list:
            if ins_id == 0:
                print("Error! 0 is background")
                continue

            instance_mask = (seg_img == ins_id)
            seg_ratio = float(np.count_nonzero(instance_mask == 1)) / float(instance_mask.size)
            if seg_ratio < self.min_seg_ratio:
                continue

            curr_iou = compute_iou(proj_mask, instance_mask)
            if curr_iou > self.min_valid_iou:
                ins_iou_dict[ins_id] = IoUInfo(cam, timestamp, seg_ratio, curr_iou, rect_info)

                if self.debug_proj:
                    img_vision = cv2.imread(os.path.join(self.cfg.clip_path, "images_vision", slice_name + ".png"))
                    os.makedirs(os.path.join(self.cfg.clip_path, self.debug_folder), exist_ok=True)
                    overlay_binary_masks_on_image(
                        img_vision,
                        proj_mask,
                        instance_mask,
                        os.path.join(self.cfg.clip_path, self.debug_folder, f"{gid}_{timestamp}_{cam}.png"),
                    )

        if len(ins_iou_dict) == 0:
            return None

        best_ins_id = None
        best_iou = 0
        for ins_id, iou_info in ins_iou_dict.items():
            if iou_info.iou > best_iou:
                best_iou = iou_info.iou
                best_ins_id = ins_id

        if best_ins_id is None:
            return None

        return gid, cam, IoUInfoWithId(best_ins_id, ins_iou_dict[best_ins_id])

    def obtain_corr_id(self):
        tasks = []
        for gid in self.gid_3d_info:
            gid_timestamps = set(self.gid_3d_info[gid].keys())

            for cam in self.cam_list_for_corr:
                if cam not in self.instance_seg_info:
                    continue

                sorted_timelist = sorted(self.instance_seg_info[cam].keys())
                for timeid in range(0, len(sorted_timelist), self.frame_interval):
                    timestr = sorted_timelist[timeid]
                    timestamp = int(timestr)
                    if timestamp not in gid_timestamps:
                        continue
                    tasks.append((gid, cam, timestr))

        max_workers = min(32, (os.cpu_count() or 1))
        results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_task = {
                executor.submit(self._process_corr_task, gid, cam, timestr): (gid, cam, timestr)
                for gid, cam, timestr in tasks
            }

            for future in as_completed(future_to_task):
                res = future.result()
                if res is not None:
                    results.append(res)

        for gid, cam, iou_info_with_id in results:
            if gid not in self.corr_id_dict:
                self.corr_id_dict[gid] = {}
            if cam not in self.corr_id_dict[gid]:
                self.corr_id_dict[gid][cam] = []
            self.corr_id_dict[gid][cam].append(iou_info_with_id)
        return


    def filter_with_instance_id(self):
        for gid in list(self.corr_id_dict_filter.keys()):
            for cam in list(self.corr_id_dict_filter[gid].keys()):
                item_list: List[IoUInfoWithId] = self.corr_id_dict_filter[gid][cam]
                ins_groups = defaultdict(list)
                for item in item_list:
                    ins_groups[item.ins_id].append(item.iou_info.iou)

                ins_stats = {}
                for ins_id, iou_values in ins_groups.items():
                    count = len(iou_values)
                    avg_iou = sum(iou_values) / count if count > 0 else 0.0
                    ins_stats[ins_id] = {'count': count, 'avg_iou': avg_iou}

                max_count = max(stats['count'] for stats in ins_stats.values())
                candidates = [ins_id for ins_id, stats in ins_stats.items() if stats['count'] == max_count]
                if len(candidates) > 1:
                    self.corr_id_dict_filter[gid][cam] = []
                    continue

                most_common_ins_id = candidates[0]
                most_avg_iou = ins_stats[most_common_ins_id]['avg_iou']
                satisfies_condition = all(
                    most_avg_iou > other_avg * self.com_ratio
                    for other_ins_id, stats in ins_stats.items()
                    if other_ins_id != most_common_ins_id
                    for other_avg in [stats['avg_iou']]
                )

                if satisfies_condition:
                    self.corr_id_dict_filter[gid][cam] = [
                        item for item in item_list
                        if item.ins_id == most_common_ins_id and item.iou_info.iou > self.min_iou_for_sam3d
                    ]
                else:
                    self.corr_id_dict_filter[gid][cam] = []
        return

    def select_key_frames(self):
        for gid in self.corr_id_dict_filter:
            self.corr_id_dict_key_frames[gid] = {}

            observation_counts = 0
            for cam, item_list in self.corr_id_dict_filter[gid].items():
                if not item_list:
                    self.corr_id_dict_key_frames[gid][cam] = []
                    continue

                sorted_by_time = sorted(item_list, key=lambda x: x.iou_info.timestamp)
                downsampled = []
                prev_timestamp = sorted_by_time[0].iou_info.timestamp
                downsampled.append(sorted_by_time[0])
                for item in sorted_by_time[1:]:
                    if item.iou_info.timestamp - prev_timestamp >= 0.5 * 1e9:
                        downsampled.append(item)
                        prev_timestamp = item.iou_info.timestamp

                if len(downsampled) > self.max_observation_each_cam:
                    sorted_by_seg_ratio = sorted(
                        downsampled, key=lambda x: x.iou_info.seg_ratio, reverse=True
                    )
                    downsampled = sorted_by_seg_ratio[:self.max_observation_each_cam]
                self.corr_id_dict_key_frames[gid][cam] = downsampled
                observation_counts += len(downsampled)

            if observation_counts < self.min_observation_for_sam3d:
                del self.corr_id_dict_key_frames[gid]
        return

    def add_no_consistency_rect(self):
        missing_gids = set(self.corr_id_dict.keys()) - set(self.corr_id_dict_key_frames.keys())
        for gid in missing_gids:
            all_items = []

            for cam in self.corr_id_dict[gid]:
                item_list = self.corr_id_dict[gid][cam]
                filtered_list = [
                    item for item in item_list
                    if item.iou_info.iou > self.min_iou_for_sam3d
                ]
                all_items.extend(filtered_list)

            if len(all_items) < self.min_observation_for_sam3d:
                continue

            sorted_all = sorted(all_items, key=lambda x: (x.iou_info.seg_ratio, x.iou_info.iou), reverse=True)
            top_3 = sorted_all[:3]
            self.rect_id_dict[gid] = [item.iou_info for item in top_3]
        return


    def add_postprocess_rect(self):
        all_gids = set(self.gid_3d_info.keys())
        huge_gids = []
        for gid in all_gids:
            if gid in self.rect_id_dict or gid in self.corr_id_dict_key_frames:
                continue

            avg_length = 0
            for ts in self.gid_3d_info[gid]:
                length, width, height = self.gid_3d_info[gid][ts]['size']
                avg_length += length
            avg_length /= float(len(self.gid_3d_info[gid]))
            if avg_length > self.huge_threshold:
                huge_gids.append(gid)

        if len(huge_gids) == 0:
            return

        tasks = []
        for gid in huge_gids:
            gid_timestamps = set(self.gid_3d_info[gid].keys())
            for timestamp in gid_timestamps:
                for cam in self.cam_frames_info[timestamp]:
                    tasks.append((gid, cam, timestamp))

        max_workers = min(32, (os.cpu_count() or 1))
        results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_task = {
                executor.submit(self._postprocess_task, gid, cam, timestamp): (gid, cam, timestamp)
                for gid, cam, timestamp in tasks
            }

            for future in as_completed(future_to_task):
                res = future.result()
                if res is not None:
                    results.append(res)

        res_id_dict = {}
        for gid, iou_info in results:
            if gid not in res_id_dict:
                res_id_dict[gid] = []
            res_id_dict[gid].append(iou_info)

        huge_counts = 0
        cam0_counts = 0
        for gid in res_id_dict:
            item_list = res_id_dict[gid]
            if len(item_list) < 30:
                continue
            timestamps = [item.timestamp for item in item_list]
            delta_time = (max(timestamps) - min(timestamps)) * 1e-9
            if delta_time < 3.0:
                continue

            if gid in huge_gids:
                huge_counts += 1
            else:
                cam0_counts += 1
            sorted_all = sorted(item_list, key=lambda x: x.seg_ratio, reverse=True)
            self.rect_id_dict[gid] = sorted_all[:3]

        print(f"[SAM3D] Huge gids num before filter: {len(huge_gids)}, after filter: {huge_counts}")
        return

    def _postprocess_task(self, gid, cam, timestamp):
        slice_name = f"slice{self.timestamp_slice_id[timestamp]}_{cam}"
        img_path = os.path.join(self.cfg.clip_path, "images_vision", slice_name + ".png")
        if not os.path.exists(img_path):
            return None

        width, height, pix_num = self.cameras_size[cam]
        proj_mask, rect_info = compute_3d_proj(self.gid_3d_info[gid][timestamp], self.cam_frames_info[timestamp][cam], width, height)
        if rect_info is None:
            return None
        rect_ratio = float(rect_info[2] * rect_info[3]) / float(pix_num)
        if rect_ratio < self.min_seg_ratio:
            return None

        if self.debug_proj:
            img_vision = cv2.imread(os.path.join(self.cfg.clip_path, "images_vision", slice_name + ".png"))
            os.makedirs(os.path.join(self.cfg.clip_path, self.debug_folder), exist_ok=True)
            instance_mask = np.zeros((height, width), dtype=np.uint8)
            overlay_binary_masks_on_image(
                img_vision,
                proj_mask,
                instance_mask,
                os.path.join(self.cfg.clip_path, self.debug_folder, f"{gid}_{timestamp}_{cam}.png"),
            )
        return gid, IoUInfo(cam, timestamp, rect_ratio, 0, rect_info)

    def _process_sam3d(self, gid, view_images, view_masks):
        t1 = time.time()
        num_views = len(view_images)
        if num_views > self.max_observation_for_sam3d:
            indices = random.sample(range(num_views), 3)
            view_images = [view_images[i] for i in indices]
            view_masks = [view_masks[i] for i in indices]

        result = self.sam3d_inference._pipeline.run_multi_view(
            view_images=view_images,
            view_masks=view_masks,
            seed=42,
            mode="multidiffusion",
            stage1_inference_steps=30,
            stage2_inference_steps=15,
            decode_formats=["gaussian"],
            with_mesh_postprocess=False,
            with_texture_baking=False,
            use_vertex_color=True,
        )

        ply_save_path = os.path.join(self.save_ply_folder, str(gid) + ".ply")
        if 'gs' in result:
            result['gs'].save_ply(ply_save_path)
        elif 'gaussian' in result:
            if isinstance(result['gaussian'], list) and len(result['gaussian']) > 0:
                result['gaussian'][0].save_ply(ply_save_path)
        t2 = time.time()
        print(f"[SAM3D] Sam3d process ID: {gid}, views: {len(view_images)}, time: {t2 - t1}")
        return

    def process(self):
        gen_static_obj_segs(self.cfg.clip_path, generate_segs_id_vis=False)
        static_ids = self.extract_unique_ids()
        print("[SAM3D] All static ids: ", static_ids)

        for gid in self.corr_id_dict_key_frames:
            if gid in static_ids:
                print(f"[SAM3D] Skip ID: {gid}")
                continue

            view_images = []
            view_masks = []
            for cam in self.corr_id_dict_key_frames[gid]:
                for curr_info in self.corr_id_dict_key_frames[gid][cam]:
                    slice_name = f"slice{self.timestamp_slice_id[curr_info.iou_info.timestamp]}_{cam}"
                    img_path = os.path.join(self.cfg.clip_path, "images_vision", slice_name + ".png")
                    img = Image.open(img_path)
                    img = np.array(img).astype(np.uint8)
                    view_images.append(img)

                    npy_path = os.path.join(self.cfg.clip_path, self.npy_folder, slice_name + ".npy")
                    mask = np.load(npy_path)
                    mask = (mask == curr_info.ins_id) # H*W, 0 OR 1
                    view_masks.append(mask)
            self._process_sam3d(gid, view_images, view_masks)

        for gid in self.rect_id_dict:
            if gid in static_ids:
                print(f"[SAM3D] Skip ID: {gid}")
                continue

            view_images = []
            view_masks = []
            for curr_info in self.rect_id_dict[gid]:
                slice_name = f"slice{self.timestamp_slice_id[curr_info.timestamp]}_{curr_info.cam}"
                img_path = os.path.join(self.cfg.clip_path, "images_vision", slice_name + ".png")
                img = Image.open(img_path)
                img = np.array(img).astype(np.uint8)
                view_images.append(img)

                H, W = img.shape[:2]
                mask = np.zeros((H, W), dtype=np.uint8)
                x, y, w, h = curr_info.rect_info
                cv2.rectangle(mask, (int(x), int(y)), (int(x + w), int(y + h)), 1, -1)
                mask = mask.astype(bool)
                view_masks.append(mask)
            self._process_sam3d(gid, view_images, view_masks)

        print((
            f"[SAM3D]:"
            f"reconstruct num with corr: {len(self.corr_id_dict_key_frames)}, "
            f"reconstruct num with rect: {len(self.rect_id_dict)}"
        ))
        return


if __name__ == "__main__":
    from settings.config import make_default_settings, make_case_specific_settings
    cfg = make_default_settings()

    cfg.ips_deploy = False
    cfg.dataset_name = "selected_clips_m1"
    cfg.root = "/workspace/dusc@xiaopeng.com/online_data/data_sam3d"
    cfg.clip_id = "c-ce0cc37f-d31b-3ea3-937b-ff3d5ba0218b"
    cfg.steps_controller.source = "vision"
    cfg = make_case_specific_settings(cfg)

    sam_3d_processor = SAM3DProcessor(cfg)
    sam_3d_processor.process()
