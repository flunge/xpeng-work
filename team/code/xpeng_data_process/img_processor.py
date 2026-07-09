import os
import cv2
import json
import numpy as np
from pathlib import Path
from functools import partial

from seg_generator import SegGenerator
from mask_generator import MaskGenerator
from undistorter import Undistorter
from utils.calib_utils import get_calibration
from utils.misc import get_global_object_moving_status, get_mask_obj_bound
from utils.images2video import images2video
from utils.file_utils import get_semantics_from_path, get_mask_from_semantics
from settings.globals import SemanticType
from concurrent.futures import ThreadPoolExecutor
import functools
import threading
import numpy as np
import cv2
from scipy import ndimage
import torch


def process_single_image(args, cfg, undistort_crop, undistorter, mask_generator, timestamp2slice=None):
    cam_name, img_name = args
    # Read image
    img_path = os.path.join(cfg.clip_path, "images_origin", cam_name, img_name)
    img = cv2.imread(img_path)
    if img is None:
        raise Exception(f"[ERROR] Failed to read image {cam_name}/{img_name}")

    # Undistort image
    undistorted_img, _, roi = undistorter.undistort(img, cam_name, undistort_crop)
    cv2.imwrite(os.path.join(undistorter.images_path, cam_name, img_name), undistorted_img)

    # Generate and save mask
    mask = mask_generator.generate_mask(undistorted_img, roi, cam_name, undistorter)
    cv2.imwrite(os.path.join(mask_generator.masks_path, cam_name, img_name), mask)
    # print(f"[INFO] ImgProcessor finished undistorting {cam_name}/{img_name}")

    # save undistorted image specifically for mvsnet
    if cfg.steps_controller.source == "vision" and not cfg.steps_controller.vision_data_fetcher:
        undistorted_img_vision, _, _ = undistorter.undistort_vision(img, cam_name)
        if timestamp2slice is None:
            with open(os.path.join(cfg.clip_path, "timestamp2slice.json"), "r") as f:
                timestamp2slice = json.load(f)
        timestamp = img_name.rsplit(".", 1)[0]
        slice_id = timestamp2slice[timestamp]
        if cam_name == "cam2":
            cut_ratio = 0.86
            undistorted_img_vision = undistorted_img_vision[:int(undistorted_img_vision.shape[0]*cut_ratio), :]
        cv2.imwrite(os.path.join(undistorter.vision_images_path, f"slice{slice_id}_{cam_name}.png"), undistorted_img_vision)
        # print(f"[INFO] ImgProcessor finished saving undistorted image for mvsnet {cam_name}/{img_name}")


def process_single_mask(transform_frame, cfg, annotation_dict, moving_gids, calibrations, segs_path, ips_deploy):
    file_path = transform_frame["file_path"].replace("images", "masks")
    cam_name = transform_frame["camera"]
    img_name = file_path.split("/")[-1]
    mask_path = os.path.join(cfg.clip_path, "masks", cam_name, img_name)

    # Read and process mask
    if not os.path.exists(mask_path):
        raise Exception(f"[ERROR] Mask file not found: {mask_path}")

    mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
    if mask is None:
        raise Exception(f"[ERROR] Failed to read mask {cam_name}/{img_name}")

    semantics = get_semantics_from_path(Path(os.path.join(segs_path, cam_name, img_name)))
    mask_veh = get_mask_from_semantics(semantics, SemanticType.VEHICLE)
    mask_hum = get_mask_from_semantics(semantics, SemanticType.HUMAN)
    mask_obj = get_mask_obj_bound(annotation_dict, transform_frame, moving_gids, calibrations._calibrations)
    combined_mask = mask * mask_veh * mask_hum * mask_obj

    # Save combined mask
    cv2.imwrite(os.path.join(cfg.clip_path, "masks_obj", cam_name, img_name), combined_mask)

    # Process and save inpainted image if not in pipeline/ucp mode
    if not ips_deploy:
        rgb = cv2.imread(os.path.join(cfg.clip_path, "images", cam_name, img_name))
        if rgb is None:
            raise Exception(f"[ERROR] Failed to read image {cam_name}/{img_name}")
        result = _inpaint_mask_area(rgb, semantics)  # Assume _inpaint_mask_area is defined in the class
        cv2.imwrite(os.path.join(cfg.clip_path, "masks_misc", cam_name, img_name), result)

    # print(f"[INFO] ImgProcessor finished saving combined mask {cam_name}/{img_name}")


def _inpaint_mask_area(rgb_img, semantics):
    mask_ground = get_mask_from_semantics(semantics, SemanticType.GROUND)
    mask_sky = get_mask_from_semantics(semantics, SemanticType.SKY)
    mask_ground = (mask_ground * 255).astype(np.uint8)
    mask_sky = (mask_sky * 255).astype(np.uint8)
    # 配置参数
    colors = {
        "mask_ground": {
            "color": [0, 0, 255],  # 红色(BGR)
            "opacity": 0.3
        },
        "mask_sky": {
            "color": [0, 255, 0],  # 绿色(BGR)
            "opacity": 0.3
        }
    }
    for mask_name in ["mask_ground", "mask_sky"]:
        color_layer = np.zeros_like(rgb_img)
        color_layer[:] = colors[mask_name]["color"]
        masked_color = cv2.bitwise_and(color_layer, color_layer, mask=eval(mask_name))
        result = cv2.addWeighted(rgb_img, 1 - colors[mask_name]["opacity"],
                                    masked_color, colors[mask_name]["opacity"], 0)

    # 可选：处理重叠区域（显示为黄色）
    overlap = cv2.bitwise_and(mask_ground, mask_sky)
    if np.any(overlap):
        yellow_layer = np.zeros_like(rgb_img)
        yellow_layer[:] = [0, 255, 255]  # 黄色
        masked_yellow = cv2.bitwise_and(yellow_layer, yellow_layer, mask=overlap)
        result = cv2.addWeighted(result, 0.7, masked_yellow, 0.3, 0)
    return result


class ImgProcessor:
    def __init__(self, cfg, load_seg=True):
        self.cfg = cfg
        self.undistort_crop = cfg.processor.undistort_crop
        self.undistorter = Undistorter(cfg)
        self.mask_generator = MaskGenerator(cfg)
        self.seg_model = SegGenerator(cfg) if load_seg else None
        self.mvs_mode = (cfg.steps_controller.source == "vision" and not cfg.steps_controller.vision_data_fetcher)

        self.transform_json = None
        self.caibrations = None
        self.annotation_autolabel_box = None
        self.get_scene_parameters()
        self.lomm_cams = ["cam0", "cam2", "cam3", "cam4", "cam5", "cam6", "cam7"]
        self.save_vision_instance_segs = False
        self.generate_segs_id_vis = False

    def process_undistort(self):
        for cam_name in self.cfg.cam_list:
            image_list = [
                i for i in os.listdir(os.path.join(self.cfg.clip_path, "images_origin", cam_name)) if ".png" in i
            ]
            for i, img_name in enumerate(image_list):
                img = cv2.imread(os.path.join(self.cfg.clip_path, "images_origin", cam_name, img_name))
                undistorted_img, _, roi = self.undistorter.undistort(img, cam_name, self.undistort_crop)
                mask = self.mask_generator.generate_mask(undistorted_img, roi, cam_name, self.undistorter)
                cv2.imwrite(os.path.join(self.undistorter.images_path, cam_name, img_name), undistorted_img)
                cv2.imwrite(os.path.join(self.mask_generator.masks_path, cam_name, img_name), mask)
                print(f"[INFO] ImgProcessor finish undistorting {cam_name}/{img_name} in {i+1}/{len(image_list)}")

    def _prewarm_undistort_for_parallel(self):
        for cam_name in self.cfg.cam_list:
            image_dir = os.path.join(self.cfg.clip_path, "images_origin", cam_name)
            image_list = [i for i in os.listdir(image_dir) if i.endswith(".png")]
            if not image_list:
                continue

            img_path = os.path.join(image_dir, image_list[0])
            img = cv2.imread(img_path)
            if img is None:
                raise Exception(f"[ERROR] Failed to read image for prewarm {cam_name}/{image_list[0]}")

            undistorted_img, _, _ = self.undistorter.undistort(img, cam_name, self.undistort_crop)
            if self.mvs_mode:
                self.undistorter.undistort_vision(img, cam_name)

            if cam_name in self.mask_generator.mask_dict and self.mask_generator.mask_dict[cam_name] is None:
                if self.cfg.processor.use_origin_mask:
                    self.mask_generator.setup_default_mask_from_origin(self.undistorter, cam_name)
                else:
                    self.mask_generator.setup_default_mask(undistorted_img, cam_name)

        print(f"[INFO] Prewarmed undistort cache for {len(self.cfg.cam_list)} cameras")

    def process_undistort_parallel(self):
        # Ensure output directories exist
        for cam_name in self.cfg.cam_list:
            os.makedirs(os.path.join(self.undistorter.images_path, cam_name), exist_ok=True)
            os.makedirs(os.path.join(self.mask_generator.masks_path, cam_name), exist_ok=True)
        if self.mvs_mode:
            os.makedirs(self.undistorter.vision_images_path, exist_ok=True)
            os.makedirs(os.path.join(self.seg_model.vision_segs_path), exist_ok=True)

        # Prepare list of tasks (camera name, image name pairs)
        tasks = []
        for cam_name in self.cfg.cam_list:
            image_list = [i for i in os.listdir(os.path.join(self.cfg.clip_path, "images_origin", cam_name)) if i.endswith(".png")]
            tasks.extend([(cam_name, img_name) for img_name in image_list])

        timestamp2slice = None
        if self.mvs_mode:
            timestamp2slice_path = os.path.join(self.cfg.clip_path, "timestamp2slice.json")
            if os.path.exists(timestamp2slice_path):
                with open(timestamp2slice_path, "r") as f:
                    timestamp2slice = json.load(f)

        self._prewarm_undistort_for_parallel()

        num_workers = min(10, len(tasks)) or 1
        worker = partial(
            process_single_image,
            cfg=self.cfg,
            undistort_crop=self.undistort_crop,
            undistorter=self.undistorter,
            mask_generator=self.mask_generator,
            timestamp2slice=timestamp2slice,
        )
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            list(executor.map(worker, tasks))
        print(f"[INFO] Completed processing {len(tasks)} images")

    def process_segs_vision(self):
        timestamp2slice = None
        if self.mvs_mode:
            timestamp2slice_path = os.path.join(self.cfg.clip_path, "timestamp2slice.json")
            if os.path.exists(timestamp2slice_path):
                with open(timestamp2slice_path, "r") as f:
                    timestamp2slice = json.load(f)

        for cam_name in self.cfg.cam_list:
            image_list = [
                i for i in os.listdir(os.path.join(self.cfg.clip_path, "images_origin", cam_name)) 
                if i.endswith(".png")
            ]
            
            for img_name in image_list:
                img_orig_path = os.path.join(self.cfg.clip_path, "images_origin", cam_name, img_name)
                img_orig = cv2.imread(img_orig_path)
                
                if img_orig is None:
                    print(f"[ERROR] Failed to read {img_orig_path}")
                    continue
                
                seg_orig = self.seg_model.generate_segs(img_orig)
                
                map1_normal, map2_normal, new_camera_matrix_normal, roi_normal = \
                    self.undistorter.get_remap_maps(img_orig.shape, cam_name, mode='normal')
                
                seg_normal = cv2.remap(seg_orig, map1_normal, map2_normal, cv2.INTER_NEAREST)
                cv2.imwrite(os.path.join(self.seg_model.segs_path, cam_name, img_name), seg_normal)
                # print(f"[INFO] ImgProcessor finish seg {cam_name}/{img_name}")
                
                if self.mvs_mode and timestamp2slice is not None:
                    map1_vision, map2_vision, _, _ = \
                        self.undistorter.get_remap_maps(img_orig.shape, cam_name, mode='mvs')
                    
                    seg_vision = cv2.remap(seg_orig, map1_vision, map2_vision, cv2.INTER_NEAREST)

                    if cam_name == "cam2":
                        cut_ratio = 0.86
                        seg_vision = seg_vision[:int(seg_vision.shape[0] * cut_ratio), :]
                    
                    timestamp = img_name.rsplit(".", 1)[0]
                    if timestamp in timestamp2slice:
                        slice_id = timestamp2slice[timestamp]
                        output_name = f"slice{slice_id}_{cam_name}.png"
                        cv2.imwrite(os.path.join(self.seg_model.vision_segs_path, output_name), seg_vision)
                        # print(f"[INFO] ImgProcessor finish seg {cam_name}/{img_name} for mvs")
                    else:
                        print(f"[WARNING] Timestamp {timestamp} not found in timestamp2slice")
            print(f"[INFO] ImgProcessor finish seg for cam {cam_name}")
        
        self.process_on_the_end()

    def process_origin_imgs(self):
        for cam_name in self.cfg.cam_list:
            image_list = [
                i for i in os.listdir(os.path.join(self.cfg.clip_path, "images_origin", cam_name)) if ".png" in i
            ]
            for i, img_name in enumerate(image_list):
                img = cv2.imread(os.path.join(self.cfg.clip_path, "images_origin", cam_name, img_name))
                seg = self.seg_model.generate_segs(img)
                undistorted_seg, _1, _2 = self.undistorter.undistort(seg, cam_name, self.undistort_crop, method=cv2.INTER_NEAREST)
                cv2.imwrite(os.path.join(self.seg_model.segs_path, cam_name, img_name), undistorted_seg)
                print(f"[INFO] ImgProcessor finish seg {cam_name}/{img_name} in {i+1}/{len(image_list)}")
        self.process_on_the_end()

    def process_on_the_end(self):
        # self.save_combined_mask_img()
        self.save_combined_mask_img_parallel()
        if not self.cfg.ips_deploy:
            images2video(os.path.join(self.cfg.clip_path, "masks_obj"), dst_folder="masks_obj_videos", log=False)
            images2video(os.path.join(self.cfg.clip_path, "masks_misc"), dst_folder="masks_misc_videos", log=False)
            os.system(f"rm -rf {self.cfg.clip_path}/masks_misc")

    def get_scene_parameters(self):
        self.transform_json = self.get_transform_json()

        calib_path = os.path.join(self.cfg.clip_path, "calib.json")
        self.calibrations = get_calibration(calib_path, self.cfg.target_lidar, vision_mode=self.cfg.steps_controller.source == "vision")

        annotation_path = os.path.join(self.cfg.clip_path, "annotation_for_train.json")
        self.annotation_autolabel_box = json.load(open(annotation_path, "r"))

    def get_transform_json(self):
        transform_path = os.path.join(self.cfg.clip_path, "transform.json")
        return json.load(open(transform_path, "r"))

    def save_combined_mask_img(self):
        ### combine car mask with obj mask
        anno_frames = self.annotation_autolabel_box["frames"]
        all_timestamps = [i['timestamp'] for i in anno_frames]
        assert len(all_timestamps) == len(set(all_timestamps)), \
            "Duplicated timestamps in annotation_autolabel_box!"
        annotation_dict = {i['timestamp']: i for i in anno_frames}
        moving_gids = get_global_object_moving_status(annotation_dict)

        for cam_name in self.cfg.cam_list:
            os.makedirs(os.path.join(self.cfg.clip_path, "masks_obj", cam_name), exist_ok=True)
            os.makedirs(os.path.join(self.cfg.clip_path, "masks_misc", cam_name), exist_ok=True)

        for transform_frame in self.transform_json["frames"]:
            file_path = transform_frame["file_path"].replace("images", "masks")
            cam_name = transform_frame["camera"]
            img_name = file_path.split("/")[-1]
            mask_path = os.path.join(self.cfg.clip_path, "masks", cam_name, img_name)
            assert os.path.exists(mask_path), f"Mask file not found: {mask_path}"

            mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
            semantics = get_semantics_from_path(Path(os.path.join(self.seg_model.segs_path, cam_name, img_name)))
            mask_veh = get_mask_from_semantics(semantics, SemanticType.VEHICLE)
            mask_hum = get_mask_from_semantics(semantics, SemanticType.HUMAN)
            mask_obj = get_mask_obj_bound(
                annotation_dict, transform_frame, moving_gids, self.calibrations._calibrations
            )
            combined_mask = mask * mask_veh * mask_hum * mask_obj
            cv2.imwrite(os.path.join(self.cfg.clip_path, "masks_obj", cam_name, img_name), combined_mask)
            if not self.cfg.ips_deploy:
                rgb = cv2.imread(os.path.join(self.cfg.clip_path, "images", cam_name, img_name))
                result = _inpaint_mask_area(rgb, semantics)
                cv2.imwrite(os.path.join(self.cfg.clip_path, "masks_misc", cam_name, img_name), result)
            print(f"[INFO] ImgProcessor finish saving combined mask {cam_name}/{img_name}")

    def save_combined_mask_img_parallel(self):
        # Preprocess annotations and validate timestamps
        anno_frames = self.annotation_autolabel_box["frames"]
        all_timestamps = [i['timestamp'] for i in anno_frames]
        assert len(all_timestamps) == len(set(all_timestamps)), \
            "Duplicated timestamps in annotation_autolabel_box!"
        annotation_dict = {i['timestamp']: i for i in anno_frames}
        moving_gids = get_global_object_moving_status(annotation_dict)

        # Create output directories
        for cam_name in self.cfg.cam_list:
            os.makedirs(os.path.join(self.cfg.clip_path, "masks_obj", cam_name), exist_ok=True)
            os.makedirs(os.path.join(self.cfg.clip_path, "masks_misc", cam_name), exist_ok=True)

        # Prepare tasks for parallel processing
        tasks = self.transform_json["frames"]


        # 替换原有的multiprocessing.Pool部分
        num_processes = min(5, len(tasks)) or 1  # 线程数保持不变
        with ThreadPoolExecutor(max_workers=num_processes) as executor:
            # 使用functools.partial绑定额外参数（与原逻辑一致）
            worker = functools.partial(
                process_single_mask,
                cfg=self.cfg,
                annotation_dict=annotation_dict,
                moving_gids=moving_gids,
                calibrations=self.calibrations,
                segs_path=self.seg_model.segs_path,
                ips_deploy=self.cfg.ips_deploy
            )
            # 提交所有任务并等待完成
            list(executor.map(worker, tasks))  # list()强制等待所有任务执行完毕

        print(f"[INFO] Completed processing {len(tasks)} frames")


    def process_instance_seg_vision_mask2former(self):
        images_vision_path = os.path.join(self.cfg.clip_path, 'images_vision')
        image_files = [
            f for f in os.listdir(images_vision_path) 
            if f.endswith(('.png'))
        ]
        if len(image_files) == 0:
            print(f"[WARNING] No images found in {images_vision_path}")
            return
        
        def parse_filename(filename):
            try:
                name_without_ext = filename.rsplit('.', 1)[0]
                if name_without_ext.startswith('slice'):
                    parts = name_without_ext.split('_', 1)
                    if len(parts) == 2:
                        slice_id = int(parts[0].replace('slice', ''))
                        cam_name = parts[1]
                        return cam_name, slice_id
            except:
                pass
            return None, None
        
        camera_groups = {}
        for img_file in image_files:
            cam_name, slice_id = parse_filename(img_file)
            if cam_name is not None:
                if cam_name not in camera_groups:
                    camera_groups[cam_name] = []
                camera_groups[cam_name].append((slice_id, img_file))
        if len(camera_groups) == 0:
            print(f"[ERROR] No valid camera images found in {images_vision_path}")
            return
        
        for cam_name, img_list in camera_groups.items():
            img_list.sort(key=lambda x: x[0])
            img_files_for_cam = [item[1] for item in img_list]
            print(f"[INFO] Processing camera {cam_name} with {len(img_files_for_cam)} images...")
            cam_output_path = os.path.join(self.seg_model.vision_instance_segs_path, cam_name)
            os.makedirs(cam_output_path, exist_ok=True)
            vis_output_path = os.path.join(cam_output_path, "visualization")
            os.makedirs(vis_output_path, exist_ok=True)
            
            batch_size = 30
            total_batches = (len(img_files_for_cam) + batch_size - 1) // batch_size
            total_processed = 0
            
            for batch_idx in range(total_batches):
                start_idx = batch_idx * batch_size
                end_idx = min(start_idx + batch_size, len(img_files_for_cam))
                batch_files = img_files_for_cam[start_idx:end_idx]
                print(f"[INFO] Processing batch {batch_idx + 1}/{total_batches} for {cam_name} (frames {start_idx+1}-{end_idx})...")
                
                imgs = []
                valid_image_files = []
                for img_file in batch_files:
                    img_path = os.path.join(images_vision_path, img_file)
                    img = cv2.imread(img_path)
                    if img is None:
                        print(f"[ERROR] Failed to read image: {img_path}")
                        continue
                    imgs.append(img)
                    valid_image_files.append(img_file)
                if len(imgs) == 0:
                    print(f"[WARNING] No valid images in batch {batch_idx + 1} for camera {cam_name}")
                    continue
                
                # do video instance segmentation inference
                result_labels, visualized_outputs = self.seg_model.generate_video_segs_mask2former(imgs, return_visualization=True, save_visualization_path=os.path.join(cam_output_path, "vis.mp4"))
                
                for idx, (img_file, seg_label) in enumerate(zip(valid_image_files, result_labels)):
                    output_path = os.path.join(cam_output_path, img_file)
                    cv2.imwrite(output_path, seg_label)
                    if visualized_outputs is not None and idx < len(visualized_outputs):
                        vis_output = visualized_outputs[idx]
                        vis_image = vis_output.get_image()[:, :, ::-1]  # RGB to BGR
                        vis_output_path_file = os.path.join(vis_output_path, img_file)
                        cv2.imwrite(vis_output_path_file, vis_image)
                total_processed += len(result_labels)
                
                del imgs, result_labels
                if visualized_outputs is not None:
                    del visualized_outputs
                
                torch.cuda.empty_cache()
                
                print(f"[INFO] Completed batch {batch_idx + 1}/{total_batches} for {cam_name}, processed {total_processed} frames so far")
            print(f"[INFO] Completed video instance segmentation for camera {cam_name}: {total_processed} frames")

    def _process_single_camera_lomm_worker(self, cam_name, img_list, images_vision_path, slice2timestamp, clip_path, seg_model, model_lock, save_vision_instance_segs):
        img_list.sort(key=lambda x: x[0])
        img_files_for_cam = [item[1] for item in img_list]
        slice_ids_for_cam = [item[0] for item in img_list]
        
        print(f"[INFO] Processing camera {cam_name} with {len(img_files_for_cam)} images using LOMM", flush=True)
        
        def save_tracker_state(tracker):
            if tracker is None:
                return None
            state = {}
            try:
                if hasattr(tracker, 'instance_memory_tracker'):
                    state['instance_memory_tracker'] = tracker.instance_memory_tracker.clone() if tracker.instance_memory_tracker is not None else None
                if hasattr(tracker, 'instance_memory_segmenter'):
                    state['instance_memory_segmenter'] = tracker.instance_memory_segmenter.clone() if tracker.instance_memory_segmenter is not None else None
                if hasattr(tracker, 'instance_memory'):
                    state['instance_memory'] = tracker.instance_memory.clone() if tracker.instance_memory is not None else None
                if hasattr(tracker, 'occupancy_memory'):
                    state['occupancy_memory'] = tracker.occupancy_memory.clone() if tracker.occupancy_memory is not None else None
            except Exception as e:
                print(f"[WARNING] Failed to save tracker state: {e}", flush=True)
                return None
            return state
        
        def restore_tracker_state(tracker, state):
            if tracker is None or state is None:
                return
            try:
                if 'instance_memory_tracker' in state:
                    tracker.instance_memory_tracker = state['instance_memory_tracker']
                if 'instance_memory_segmenter' in state:
                    tracker.instance_memory_segmenter = state['instance_memory_segmenter']
                if 'instance_memory' in state:
                    tracker.instance_memory = state['instance_memory']
                if 'occupancy_memory' in state:
                    tracker.occupancy_memory = state['occupancy_memory']
            except Exception as e:
                print(f"[WARNING] Failed to restore tracker state: {e}", flush=True)
        
        camera_tracker_state = None
        
        cam_output_path = None
        vis_output_path = None
        if save_vision_instance_segs:
            cam_output_path = os.path.join(seg_model.vision_instance_segs_path, cam_name)
            os.makedirs(cam_output_path, exist_ok=True)
            
            vis_output_path = os.path.join(cam_output_path, "visualization")
            os.makedirs(vis_output_path, exist_ok=True)
        
        instance_segs_id_path = os.path.join(clip_path, "instance_segs_id")
        os.makedirs(instance_segs_id_path, exist_ok=True)
        
        max_width = 640
        max_height = 480
        
        batch_size = 30
        total_batches = (len(img_files_for_cam) + batch_size - 1) // batch_size
        
        total_processed = 0
        cam_lomm_meta = {}
        cam_id_memories = {}
        
        def resize_image_if_needed(img):
            if img is None:
                return img, None
            h, w = img.shape[:2]
            original_size = (h, w)
            scale = min(max_width / w, max_height / h, 1.0)
            if scale < 1.0:
                new_w = int(w * scale)
                new_h = int(h * scale)
                img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
            return img, original_size
        
        for batch_idx in range(total_batches):
            start_idx = batch_idx * batch_size
            end_idx = min(start_idx + batch_size, len(img_files_for_cam))
            batch_files = img_files_for_cam[start_idx:end_idx]
            batch_slice_ids = slice_ids_for_cam[start_idx:end_idx]

            def read_image(img_file_slice_pair):
                img_file, slice_id = img_file_slice_pair
                img_path = os.path.join(images_vision_path, img_file)
                img = cv2.imread(img_path)
                return img, img_file, slice_id, None
            
            imgs = []
            valid_image_files = []
            valid_slice_ids = []
            original_sizes = []
            
            with ThreadPoolExecutor(max_workers=min(10, len(batch_files))) as read_executor:
                read_results = list(read_executor.map(read_image, zip(batch_files, batch_slice_ids)))
            
            for img, img_file, slice_id, original_size in read_results:
                if img is None:
                    print(f"[ERROR] Failed to read image: {os.path.join(images_vision_path, img_file)}")
                    continue
                imgs.append(img)
                valid_image_files.append(img_file)
                valid_slice_ids.append(slice_id)
                original_sizes.append(original_size)
            
            if len(imgs) == 0:
                print(f"[WARNING] No valid images in batch {batch_idx + 1} for camera {cam_name}")
                continue
            
            # keep=True 表示保持状态（用于长视频处理）
            keep = (batch_idx > 0)
            
            if model_lock is not None:
                with model_lock:
                    tracker = None
                    if hasattr(seg_model, 'lomm_model') and seg_model.lomm_model is not None:
                        if hasattr(seg_model.lomm_model, 'tracker'):
                            tracker = seg_model.lomm_model.tracker
                    
                    if tracker is not None:
                        if batch_idx == 0:
                            if hasattr(tracker, '_clear_memory'):
                                tracker._clear_memory()
                        else:
                            if camera_tracker_state is not None:
                                restore_tracker_state(tracker, camera_tracker_state)
                    
                    result_labels, visualized_outputs, frame_instance_ids, instance_id_labels = seg_model.generate_video_segs_lomm(
                        imgs,
                        return_visualization=True,
                        keep=keep,
                        id_memories=cam_id_memories
                    )
                    
                    if tracker is not None:
                        camera_tracker_state = save_tracker_state(tracker)
            else:
                result_labels, visualized_outputs, frame_instance_ids, instance_id_labels = seg_model.generate_video_segs_lomm(
                    imgs, 
                    return_visualization=True, 
                    keep=keep,
                    id_memories=cam_id_memories
                )

            def save_result(idx_img_data):
                idx, (img_file, seg_label, instance_id_list, instance_id_label) = idx_img_data
                
                if save_vision_instance_segs:
                    output_path = os.path.join(cam_output_path, img_file)
                    cv2.imwrite(output_path, seg_label)
                
                slice_id = valid_slice_ids[idx]
                timestamp = slice2timestamp.get(slice_id, None)
                if timestamp is None:
                    print(f"[WARNING] Cannot find timestamp for slice_id {slice_id}, using slice_id as key")
                    timestamp = f"slice_{slice_id}"
                
                cam_lomm_meta[timestamp] = instance_id_list
                
                instance_id_filename = f"slice{slice_id}_{cam_name}.npy"
                instance_id_output_path = os.path.join(instance_segs_id_path, instance_id_filename)
                np.save(instance_id_output_path, instance_id_label)
                
                if save_vision_instance_segs and visualized_outputs is not None and idx < len(visualized_outputs):
                    vis_output = visualized_outputs[idx]
                    vis_image = vis_output.get_image()[:, :, ::-1]  # RGB to BGR
                    vis_output_path_file = os.path.join(vis_output_path, img_file)
                    cv2.imwrite(vis_output_path_file, vis_image)
            
            save_data = list(enumerate(zip(valid_image_files, result_labels, frame_instance_ids, instance_id_labels)))
            with ThreadPoolExecutor(max_workers=min(10, len(save_data))) as save_executor:
                list(save_executor.map(save_result, save_data))
            
            total_processed += len(result_labels)
            
            del imgs, result_labels
            if visualized_outputs is not None:
                del visualized_outputs
            
            # print(f"[INFO] Completed batch {batch_idx + 1}/{total_batches} for {cam_name}, processed {total_processed} frames so far", flush=True)
        
        camera_tracker_state = None
        
        torch.cuda.empty_cache()

        return cam_name, cam_lomm_meta, total_processed

    def process_instance_seg_vision_lomm(self):
        images_vision_path = os.path.join(self.cfg.clip_path, 'images_vision')
        image_files = [
            f for f in os.listdir(images_vision_path) 
            if f.endswith(('.png'))
        ]
        
        if len(image_files) == 0:
            print(f"[WARNING] No images found in {images_vision_path}")
            return
        
        def parse_filename(filename):
            try:
                name_without_ext = filename.rsplit('.', 1)[0]
                if name_without_ext.startswith('slice'):
                    parts = name_without_ext.split('_', 1)
                    if len(parts) == 2:
                        slice_id = int(parts[0].replace('slice', ''))
                        cam_name = parts[1]
                        return cam_name, slice_id
            except:
                pass
            return None, None
        
        camera_groups = {}
        for img_file in image_files:
            cam_name, slice_id = parse_filename(img_file)
            if cam_name is not None:
                if cam_name not in camera_groups:
                    camera_groups[cam_name] = []
                camera_groups[cam_name].append((slice_id, img_file))
        
        if len(camera_groups) == 0:
            print(f"[ERROR] No valid camera images found in {images_vision_path}")
            return
        
        if hasattr(self, 'lomm_cams') and self.lomm_cams is not None:
            lomm_cams = self.lomm_cams if isinstance(self.lomm_cams, list) else [self.lomm_cams]
            camera_groups = {cam_name: img_list for cam_name, img_list in camera_groups.items() if cam_name in lomm_cams}
            if len(camera_groups) == 0:
                print(f"[WARNING] No cameras found matching lomm_cams configuration: {lomm_cams}")
                return
            print(f"[INFO] Processing cameras specified in lomm_cams: {list(camera_groups.keys())}")
        else:
            print(f"[INFO] Processing all available cameras: {list(camera_groups.keys())}")
        
        timestamp2slice_path = os.path.join(self.cfg.clip_path, "timestamp2slice.json")
        slice2timestamp = {}
        if os.path.exists(timestamp2slice_path):
            with open(timestamp2slice_path, "r") as f:
                timestamp2slice = json.load(f)
            slice2timestamp = {}
            for timestamp, slice_id in timestamp2slice.items():
                slice_id_int = int(slice_id) if isinstance(slice_id, str) else slice_id
                slice2timestamp[slice_id_int] = timestamp
        else:
            print(f"[WARNING] timestamp2slice.json not found, cannot convert slice_id to timestamp")
        
        clip_path = self.cfg.clip_path
        
        shared_seg_model = self.seg_model
        model_lock = threading.Lock()
        
        tasks = []
        for cam_name, img_list in camera_groups.items():
            tasks.append((cam_name, img_list))
        
        lomm_meta = {}
        max_workers = min(len(tasks), 6)
        
        def process_camera_task(cam_task):
            cam_name, img_list = cam_task
            try:
                result_cam_name, cam_lomm_meta, total_processed = self._process_single_camera_lomm_worker(
                    cam_name,
                    img_list,
                    images_vision_path,
                    slice2timestamp,
                    clip_path,
                    shared_seg_model,
                    model_lock,
                    self.save_vision_instance_segs
                )
                print(f"[INFO] Successfully completed camera {result_cam_name}: {total_processed} frames", flush=True)
                return result_cam_name, cam_lomm_meta, None
            except Exception as exc:
                print(f"[ERROR] Camera {cam_name} generated an exception: {exc}", flush=True)
                import traceback
                traceback.print_exc()
                return cam_name, None, exc
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(process_camera_task, tasks))
        
        for result_cam_name, cam_lomm_meta, exc in results:
            if exc is None and cam_lomm_meta is not None:
                lomm_meta[result_cam_name] = cam_lomm_meta
            elif exc is not None:
                print(f"[ERROR] Failed to process camera {result_cam_name}")
        
        lomm_meta_path = os.path.join(self.cfg.clip_path, 'lomm_meta.json')

        with open(lomm_meta_path, 'w') as f:
            json.dump(lomm_meta, f, indent=2)
        print(f"[INFO] Saved LOMM metadata to {lomm_meta_path}")


if __name__ == "__main__":
    from settings.config import make_default_settings, make_case_specific_settings
    clip_ids = {
        "c-66260c6e-65d2-3f8f-a2a5-029b885a87b3": "fm_performance_test",
        # "c-c244e2f3-2464-3c67-acbe-045a7924f5a4": "fm_fixed",
        # "c-078f16e4-274f-37a2-97f5-9afe6aa542ed": "fm_fixed",
        # "c-10ce0565-ffaf-378d-bd9c-845893333d1d": "fm_fixed",
        # "c-b0661312-a728-3659-90fa-76088abf192e": "fm_fixed",
    }
    for clip, folder in clip_ids.items():
        cfg = make_default_settings()
        cfg.ips_deploy = False
        cfg.dataset_name = "selected_clips_m1"
        cfg.root = f"/workspace/yangxh7@xiaopeng.com/datasets/xpeng/{folder}"
        cfg.clip_id = clip
        cfg.processor.undistort_crop = True
        cfg.processor.expand_ratio.cam0 = 1.
        cfg.processor.expand_ratio.cam2 = 1.
        cfg.processor.expand_ratio.cam3 = 1.
        cfg.processor.expand_ratio.cam4 = 1.
        cfg.processor.expand_ratio.cam5 = 1.
        cfg.processor.expand_ratio.cam6 = 1.
        cfg.processor.expand_ratio.cam7 = 1.
        cfg = make_case_specific_settings(cfg)

        image_processor = ImgProcessor(cfg)
        image_processor.process_images()
        image_processor.process_on_the_end()
