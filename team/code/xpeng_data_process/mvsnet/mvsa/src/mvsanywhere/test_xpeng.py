import datetime
import gc
import json
import os
import random
import re
import string
import threading
import time
from multiprocessing import Manager
from pathlib import Path
from queue import Queue, Empty
import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data._utils.collate import default_collate
from tqdm import tqdm

import mvsnet.mvsa.src.mvsanywhere.options as options
from mvsnet.mvsa.src.mvsanywhere.tools.tuple_generator import crawl_subprocess_long
from mvsnet.mvsa.src.mvsanywhere.datasets.xpeng_dataset import XPengDataset
from mvsnet.mvsa.src.mvsanywhere.tools.point_cloud_fuser import PointCloudFuser
from mvsnet.mvsa.src.mvsanywhere.utils.generic_utils import to_gpu
from mvsnet.mvsa.src.mvsanywhere.utils.metrics_utils import (
    ResultsAverager,
)
from mvsnet.mvsa.src.mvsanywhere.utils.data_io import save_pfm
from mvsnet.mvsa.src.mvsanywhere.utils.model_utils import get_model_class, load_model_inference

def _clone_structure(value):
    if isinstance(value, torch.Tensor):
        return value.clone().contiguous()
    if isinstance(value, np.ndarray):
        return torch.from_numpy(value).clone().contiguous()
    if isinstance(value, (list, tuple)):
        return [_clone_structure(v) for v in value]
    if isinstance(value, dict):
        return {k: _clone_structure(v) for k, v in value.items()}
    return value

def mvsa_collate_fn(batch):
    cur_data_list, src_data_list = zip(*batch)
    cloned_cur = [_clone_structure(item) for item in cur_data_list]
    cloned_src = [_clone_structure(item) for item in src_data_list]
    collated_cur = {}
    collated_src = {}

    special_keys_as_list = {
        "high_res_color_b3hw",
        "high_res_seg_bhw",
        "full_res_depth_b1hw",
        "full_res_mask_b1hw",
        "full_res_mask_b_b1hw",
        "full_res_seg_ego_mask_b1hw",
    }

    if cloned_cur:
        keys = cloned_cur[0].keys()
        for key in keys:
            values = [item[key] for item in cloned_cur]
            try:
                if key in special_keys_as_list:
                    collated_cur[key] = values
                else:
                    collated_cur[key] = default_collate(values)
            except Exception as exc:
                sample_types = [type(v) for v in values[: min(5, len(values))]]
                sample_shapes = []
                for v in values[: min(5, len(values))]:
                    if isinstance(v, torch.Tensor):
                        sample_shapes.append(tuple(v.shape))
                    elif isinstance(v, np.ndarray):
                        sample_shapes.append(("np",) + v.shape)
                    else:
                        sample_shapes.append(None)
                raise RuntimeError(
                    f"[COLLATE-DEBUG] cur_data key='{key}', len={len(values)}, "
                    f"sample types={sample_types}, sample shapes={sample_shapes}"
                ) from exc

    if cloned_src:
        keys = cloned_src[0].keys()
        for key in keys:
            values = [item[key] for item in cloned_src]
            try:
                if key in special_keys_as_list:
                    collated_src[key] = values
                else:
                    collated_src[key] = default_collate(values)
            except Exception as exc:
                sample_types = [type(v) for v in values[: min(5, len(values))]]
                sample_shapes = []
                for v in values[: min(5, len(values))]:
                    if isinstance(v, torch.Tensor):
                        sample_shapes.append(tuple(v.shape))
                    elif isinstance(v, np.ndarray):
                        sample_shapes.append(("np",) + v.shape)
                    else:
                        sample_shapes.append(None)
                raise RuntimeError(
                    f"[COLLATE-DEBUG] src_data key='{key}', len={len(values)}, "
                    f"sample types={sample_types}, sample shapes={sample_shapes}"
                ) from exc

    return collated_cur, collated_src


class FusionAsyncSaver:
    def __init__(self, fuser, max_queue_size=32, sleep_interval=0.01, num_workers=None):
        self.fuser = fuser
        self.max_queue_size = max_queue_size
        self.sleep_interval = sleep_interval
        
        self.queue = Queue(maxsize=max_queue_size * 2)
        
        if num_workers is None:
            num_workers = min(8, max(2, (os.cpu_count() or 4) // 2))
        self.num_workers = num_workers
        
        self.event = threading.Event()
        self.event.set()
        self.errors = []
        self.processed_count = 0
        self.total_enqueued = 0
        self._lock = threading.Lock()
        
        self._worker_threads = []
        for i in range(self.num_workers):
            worker = threading.Thread(
                target=self._worker_loop,
                name=f"fusion_async_saver_worker_{i}",
                daemon=True,
            )
            worker.start()
            self._worker_threads.append(worker)
        
        print(f"[FusionSaver] Started {self.num_workers} worker threads", flush=True)

    def _worker_loop(self):
        thread_name = threading.current_thread().name
        while self.event.is_set() or not self.queue.empty():
            try:
                task = self.queue.get(timeout=0.1)
            except Empty:
                continue
            
            try:
                self.fuser.fuse_frame(**task)
                with self._lock:
                    self.processed_count += 1
                    if self.processed_count % 100 == 0:
                        remaining = self.queue.qsize()
                        print(f"[FusionSaver] Processed {self.processed_count} frames, {remaining} remaining in queue", flush=True)
            except Exception as exc:
                print(f"[ERROR] Fusion worker {thread_name} failed: {exc}", flush=True)
                import traceback
                traceback.print_exc()
                with self._lock:
                    self.errors.append(exc)
            finally:
                self.queue.task_done()
        
        self.event.clear()

    def enqueue(self, task):
        self.queue.put(task, block=True, timeout=None)
        with self._lock:
            self.total_enqueued += 1

    def close(self):
        if not self.event.is_set() and self.queue.empty():
            return
        
        queue_size = self.queue.qsize()
        if queue_size > 0:
            print(f"[FusionSaver] Waiting for {queue_size} queued fusion tasks to complete using {self.num_workers} workers...", flush=True)
        
        self.event.clear()
        
        # Wait for queue to be empty
        self.queue.join()
        
        # Wait for all worker threads to finish
        for i, worker in enumerate(self._worker_threads):
            worker.join(timeout=60.0)  # Timeout after 60 seconds per thread
            if worker.is_alive():
                print(f"[WARNING] Worker thread {i} did not finish in time", flush=True)
        
        with self._lock:
            print(f"[FusionSaver] All {self.processed_count} fusion tasks completed using {self.num_workers} workers", flush=True)
        
        if self.errors:
            error_msg = f"Fusion workers encountered {len(self.errors)} errors"
            print(f"[ERROR] {error_msg}", flush=True)
            raise RuntimeError(error_msg) from self.errors[0]


def prepare_scan_files(opts):
    dataset_opts = opts.datasets[0]

    parent_path = Path(opts.scan_parent_directory)
    scan_name = opts.scan_name

    predefined_tuple_file = os.path.join(parent_path, "mvsnet_metadata", f"{dataset_opts.split}_xpeng_tuple.txt")
    if os.path.exists(predefined_tuple_file):
        print(f"Using predefined tuple file directly: {predefined_tuple_file}", flush=True)
        
        predefined_tuple_dir = os.path.dirname(predefined_tuple_file)
        predefined_tuple_basename = os.path.basename(predefined_tuple_file)
        
        if predefined_tuple_basename.startswith(f"{dataset_opts.split}_"):
            mv_tuple_file_suffix = predefined_tuple_basename[len(f"{dataset_opts.split}_"):]
            if not mv_tuple_file_suffix.startswith("_"):
                mv_tuple_file_suffix = "_" + mv_tuple_file_suffix
        else:
            mv_tuple_file_suffix = "_xpeng_tuple.txt"
        
        dataset_scan_split_file = os.path.join(predefined_tuple_dir, "scans.txt")
        os.makedirs(predefined_tuple_dir, exist_ok=True)
        
        with open(dataset_scan_split_file, "w") as f:
            f.write(scan_name + "\n")
        single_debug_scan_id = scan_name

        dataset_opts.dataset_path = str(parent_path)
        dataset_opts.single_debug_scan_id = single_debug_scan_id
        dataset_opts.tuple_info_file_location = predefined_tuple_dir
        dataset_opts.dataset_scan_split_file = str(dataset_scan_split_file)
        dataset_opts.mv_tuple_file_suffix = mv_tuple_file_suffix
        opts.dataset_opts = dataset_opts

        return dataset_opts
    else:
        print(f"Predefined tuple file not found: {predefined_tuple_file}", flush=True)
        print("Falling back to dynamic tuple generation...", flush=True)
        
        current_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        random_string = "".join(random.choices(string.ascii_letters + string.digits, k=10))
        tmp_metadata_folder = Path("/tmp") / f"fxpeng_{random_string}_{current_time}"
        tmp_metadata_folder.mkdir(parents=True, exist_ok=True)
        dataset_scan_split_file = tmp_metadata_folder / "scans.txt"
        tuple_info_file_location = tmp_metadata_folder / "tuples"
        tuple_info_file_location.mkdir(parents=True, exist_ok=True)
        frame_tuple_type = (
            "dense_offline" if dataset_opts.frame_tuple_type is None else dataset_opts.frame_tuple_type
        )
        mv_tuple_file_suffix = f"_xpeng_{frame_tuple_type}.txt"
        with open(dataset_scan_split_file, "w") as f:
            f.write(scan_name + "\n")
        single_debug_scan_id = scan_name

        dataset_opts.dataset_path = str(parent_path)
        dataset_opts.single_debug_scan_id = single_debug_scan_id
        dataset_opts.tuple_info_file_location = str(tuple_info_file_location)
        dataset_opts.dataset_scan_split_file = str(dataset_scan_split_file)
        dataset_opts.mv_tuple_file_suffix = mv_tuple_file_suffix
        opts.dataset_opts = dataset_opts

        # compute tuples
        tuples = crawl_subprocess_long(
            opts,
            single_debug_scan_id,
            0,
            Manager().Value("i", 0),
        )
        with open(
            tuple_info_file_location / f"{dataset_opts.split}{mv_tuple_file_suffix}", "w"
        ) as f:
            for line in tuples:
                f.write(line + "\n")
        return dataset_opts

def init_model(opts, device):
    model_class_to_use = get_model_class(opts)
    model = load_model_inference(opts, model_class_to_use)
    model = model.to(device).eval()
    return model

def init_options():
    option_handler = options.OptionsHandler()
    option_handler.parse_and_merge_options()
    option_handler.pretty_print_options()
    opts = option_handler.options
    if opts.gpus == 0:
        opts.precision = 32
    return opts

def main(opts=None):
    with torch.inference_mode():
        if opts is None:
            opts = init_options()
        
        if torch.cuda.is_available():
            current_device_index = torch.cuda.current_device()
            device = torch.device(f"cuda:{current_device_index}")
            torch.cuda.set_device(current_device_index)
        else:
            device = torch.device("cpu")
        use_cuda = device.type == "cuda"

        def clear_cuda_cache():
            if use_cuda:
                torch.cuda.empty_cache()

        # get dataset
        dataset_opts = prepare_scan_files(opts)
        opts.datasets[0] = dataset_opts

        assert len(opts.datasets) == 1, f"Expected only one dataset but got {len(opts.datasets)}"
        
        dataset_class = XPengDataset
        scans = [dataset_opts.single_debug_scan_id]
        results_path = opts.output_base_path

        if opts.run_fusion:
            mesh_output_dir = os.path.join(results_path, "meshes")
            Path(mesh_output_dir).mkdir(parents=True, exist_ok=True)
        
        if opts.dump_depth_visualization:
            viz_output_folder_name = "quick_viz"
            viz_output_dir = os.path.join(results_path, "viz", viz_output_folder_name)
            Path(viz_output_dir).mkdir(parents=True, exist_ok=True)
        
        if opts.run_fusion:
            mask_viz_output_dir = os.path.join(results_path, "viz", "mask")
            Path(mask_viz_output_dir).mkdir(parents=True, exist_ok=True)
        
        scores_output_dir = os.path.join(results_path, "scores")
        Path(scores_output_dir).mkdir(parents=True, exist_ok=True)

        model = init_model(opts, device)
        gc.collect()
        clear_cuda_cache()
        
        # all_frame_metrics = ResultsAverager(opts.name, f"frame metrics")
        # all_scene_metrics = ResultsAverager(opts.name, f"scene metrics")

        allowed_cam_ids = None
        if getattr(opts, "filter_cam_ids", None):
            allowed_cam_ids = [cid.strip() for cid in opts.filter_cam_ids.split(',') if cid.strip()]

        # start_time = torch.cuda.Event(enable_timing=True)
        # end_time = torch.cuda.Event(enable_timing=True)

        fuser = None
        scan = scans[0]
        fusion_saver = None
        
        save_frame_infos = getattr(opts, 'save_frame_infos', False)
        frame_infos_save_path = None
        if opts.run_fusion:
            frame_infos_save_path = os.path.join(mesh_output_dir, f"{scan.replace('/', '_')}_frame_infos.pkl")
            if save_frame_infos and os.path.exists(frame_infos_save_path):
                print(f"[INFO] Found saved frame_infos at {frame_infos_save_path}, skipping inference and directly exporting point cloud", flush=True)
                fusion_type = getattr(opts, 'fusion_type', 'pointcloud')
                
                if fusion_type == 'pointcloud':
                    fuser = PointCloudFuser(
                        conf_threshold=getattr(opts, 'fusion_conf_threshold', 0.8),
                        min_depth=getattr(opts, 'fusion_min_depth', 0.5),
                        max_depth=opts.fusion_max_depth,
                        enable_geometric_consistency=getattr(opts,'fusion_enable_geometric_consistency', True),
                        img_dist_thres=getattr(opts, 'fusion_img_dist_thres', 1.0),
                        depth_thres=getattr(opts, 'fusion_depth_thres', 0.01),
                        thres_view=getattr(opts, 'fusion_thres_view', 3),
                        cross_cam_id_threshold=getattr(opts, 'fusion_cross_cam_id_threshold', 20),
                        cross_dist_thres=getattr(opts, 'fusion_cross_dist_thres', 15.0),
                        save_debug_info=getattr(opts, 'fusion_save_debug_info', False),
                        enable_cross_camera=getattr(opts, 'fusion_enable_cross_camera', True),
                        cross_selection_debug_dir=os.path.join(mesh_output_dir, "cross_camera_debug"),
                        cross_selection_max_samples=getattr(opts, 'fusion_cross_debug_max_samples', 5),
                        cross_selection_debug_limit=getattr(opts, 'fusion_cross_debug_limit', 50),
                        frame_cache_dir=os.path.join(mesh_output_dir, "frame_cache"),
                        debug_image_dir=os.path.join(mesh_output_dir, "debug_images"),
                        allowed_cam_ids=allowed_cam_ids,
                    )
                    fuser.load_frame_infos(frame_infos_save_path)
                else:
                    from mvsnet.mvsa.src.mvsanywhere.tools import fusers_helper
                    fuser = fusers_helper.get_fuser(opts, scan)
                
                if fusion_type == 'pointcloud':
                    output_ply_path = os.path.join(mesh_output_dir, f"{scan.replace('/', '_')}.ply")
                    parent_path = Path(opts.scan_parent_directory)
                    metadata_dir = os.path.join(parent_path, "mvsnet_metadata")
                    fuser.export_point_cloud(
                        output_ply_path,
                        apply_statistical_filter=getattr(opts, 'fusion_apply_stat_filter', True),
                        apply_cluster_filter=getattr(opts, 'fusion_apply_cluster_filter', True),
                        voxel_size=getattr(opts, 'fusion_voxel_size', 0.05),
                        stat_nb_neighbors=getattr(opts, 'fusion_stat_nb_neighbors', 40),
                        stat_std_ratio=getattr(opts, 'fusion_stat_std_ratio', 2.0),
                        cluster_eps=getattr(opts, 'fusion_cluster_eps', 0.5),
                        cluster_min_points=getattr(opts, 'fusion_cluster_min_points', 10),
                        dbscan_voxel_size=getattr(opts, 'fusion_dbscan_voxel_size', 0.1),
                        metadata_dir=metadata_dir,
                    )
                    print(f"point cloud exported to: {output_ply_path}", flush=True)
                else:
                    fuser.export_mesh(
                        os.path.join(mesh_output_dir, f"{scan.replace('/', '_')}.ply"),
                    )
                    fuser.save_tsdf(
                        os.path.join(mesh_output_dir, f"{scan.replace('/', '_')}_tsdf.npz"),
                    )
                    print(f"TSDF mesh exported to: {mesh_output_dir}", flush=True)
                
                del fuser, parent_path, metadata_dir
                if fusion_type == 'pointcloud':
                    del output_ply_path
                gc.collect()
                torch.cuda.empty_cache()
                return
        
        if opts.run_fusion:
            fusion_type = getattr(opts, 'fusion_type', 'pointcloud')
            
            if fusion_type == 'pointcloud':
                enable_async_fusion = getattr(opts, 'fusion_enable_async_fusion', False)
                fusion_queue_size = getattr(opts, 'fusion_queue_size', 4)
                fuser = PointCloudFuser(
                    conf_threshold=getattr(opts, 'fusion_conf_threshold', 0.8),
                    min_depth=getattr(opts, 'fusion_min_depth', 0.5),
                    max_depth=opts.fusion_max_depth,
                    enable_geometric_consistency=getattr(opts,'fusion_enable_geometric_consistency', True),
                    img_dist_thres=getattr(opts, 'fusion_img_dist_thres', 1.0),
                    depth_thres=getattr(opts, 'fusion_depth_thres', 0.01),
                    thres_view=getattr(opts, 'fusion_thres_view', 3),
                    cross_cam_id_threshold=getattr(opts, 'fusion_cross_cam_id_threshold', 20),
                    cross_dist_thres=getattr(opts, 'fusion_cross_dist_thres', 15.0),
                    save_debug_info=getattr(opts, 'fusion_save_debug_info', False),
                    enable_cross_camera=getattr(opts, 'fusion_enable_cross_camera', True),
                    cross_selection_debug_dir=os.path.join(mesh_output_dir, "cross_camera_debug"),
                    cross_selection_max_samples=getattr(opts, 'fusion_cross_debug_max_samples', 5),
                    cross_selection_debug_limit=getattr(opts, 'fusion_cross_debug_limit', 50),
                    frame_cache_dir=os.path.join(mesh_output_dir, "frame_cache"),
                    debug_image_dir=os.path.join(mesh_output_dir, "debug_images"),
                    allowed_cam_ids=allowed_cam_ids,
                    enable_async_fusion=enable_async_fusion,
                    fusion_queue_size=fusion_queue_size,
                    mask_vehicle=True,
                )
                fusion_async_queue_size = getattr(opts, 'fusion_async_queue_size', 2)
                fusion_sleep_interval = getattr(opts, 'fusion_async_sleep_interval', 0.01)
                fusion_num_workers = getattr(opts, 'fusion_num_workers', None)  # None = auto-detect
                fusion_saver = FusionAsyncSaver(
                    fuser,
                    max_queue_size=max(1, fusion_async_queue_size),
                    sleep_interval=max(0.001, fusion_sleep_interval),
                    num_workers=fusion_num_workers,
                )
            else:
                from mvsnet.mvsa.src.mvsanywhere.tools import fusers_helper
                fuser = fusers_helper.get_fuser(opts, scan)

        dataset = dataset_class(
            dataset_opts.dataset_path,
            split=dataset_opts.split,
            mv_tuple_file_suffix=dataset_opts.mv_tuple_file_suffix,
            limit_to_scan_id=scan,
            include_full_res_depth=False,
            tuple_info_file_location=dataset_opts.tuple_info_file_location,
            num_images_in_tuple=None,
            shuffle_tuple=opts.shuffle_tuple,
            include_high_res_color=(
                (opts.fuse_color and opts.run_fusion) or opts.dump_depth_visualization
            ),
            include_full_depth_K=True,
            skip_frames=opts.skip_frames,
            skip_to_frame=opts.skip_to_frame,
            image_width=opts.image_width,
            image_height=opts.image_height,
            high_res_image_width=getattr(dataset_opts, 'high_res_image_width', None),
            high_res_image_height=getattr(dataset_opts, 'high_res_image_height', None),
            pass_frame_id=True,
            disable_flip=True,
            rotate_images=opts.rotate_images,
            matching_scale=opts.matching_scale,
            prediction_scale=opts.prediction_scale,
            prediction_num_scales=opts.prediction_num_scales,
            allowed_cam_ids=allowed_cam_ids,
        )

        assert len(dataset) > 0, f"Dataset {scan} is empty."
        
        gc.collect()

        dataloader = torch.utils.data.DataLoader(
            dataset,
            batch_size=opts.batch_size,
            shuffle=False,
            num_workers=opts.num_workers,
            drop_last=False,
            collate_fn=mvsa_collate_fn,
            pin_memory=False,
        )

        # if opts.compute_metrics:
        #     scene_frame_metrics = ResultsAverager(opts.name, f"scene {scan} metrics")
        
        depth_save_dir = None
        cam_save_dir = None
        if opts.run_fusion and opts.fusion_enable_geometric_consistency:
            depth_save_dir = os.path.join(opts.output_base_path, "depth_pred")
            cam_save_dir = os.path.join(opts.output_base_path, "cameras")
            os.makedirs(depth_save_dir, exist_ok=True)
            os.makedirs(cam_save_dir, exist_ok=True)
        
        for batch_ind, batch in enumerate(tqdm(dataloader)):
            cur_data, src_data = batch
            valid_cam_list = []

            if allowed_cam_ids is not None:
                if "cam_id" in cur_data and cur_data["cam_id"] is not None:
                    cam_id = cur_data["cam_id"]
                    if isinstance(cam_id, list):
                        valid_cam_list = []
                        for i in range(len(cam_id)):
                            cam_id_item = cam_id[i]
                            cam_id_normalized = str(cam_id_item).replace('cam', '').strip()
                            if cam_id_normalized in allowed_cam_ids:
                                valid_cam_list.append(cam_id_item)
                    else:
                        cam_id_normalized = str(cam_id).replace('cam', '').strip()
                        if cam_id_normalized in allowed_cam_ids:
                            valid_cam_list = [cam_id]
                    if len(valid_cam_list) == 0:
                        del cur_data, src_data
                        continue
                else:
                    raise ValueError(f"cam_id not found in cur_data, skipping batch {batch_ind}...")
            
            cur_data = to_gpu(cur_data, key_ignores=["frame_id_string", "cam_id"], device=device)
            src_data = to_gpu(src_data, key_ignores=["frame_id_string", "cam_id"], device=device)
            
            # inference
            outputs = model(
                phase="test",
                cur_data=cur_data,
                src_data=src_data,
                unbatched_matching_encoder_forward=(not opts.fast_cost_volume),
                return_mask=True,
                num_refinement_steps=1,
            )
            if use_cuda:
                torch.cuda.synchronize()
            
            del src_data
            
            # pcd fusion
            if opts.run_fusion:
                
                if fusion_type == 'pointcloud':
                    depth_pred_list = outputs["depth_pred_s0_b1hw"]
                    for elem_ind in range(len(depth_pred_list)):
                        cam_id_str = cur_data.get("cam_id")[elem_ind] 
                        if cam_id_str not in valid_cam_list: 
                            continue
                        
                        cur_depth_pred_s0_b1hw = depth_pred_list[elem_ind]
                        cur_full_res_mask_b1hw = cur_data.get("full_res_mask_b1hw")[elem_ind]
                        cur_full_res_H, cur_full_res_W = cur_full_res_mask_b1hw.shape[-2:]
                        
                        cur_upsampled_depth_pred_b1hw = F.interpolate(
                            cur_depth_pred_s0_b1hw.unsqueeze(0),
                            size=(cur_full_res_H, cur_full_res_W),
                            mode="nearest",
                        ).squeeze(0)

                        if opts.fusion_enable_geometric_consistency and depth_save_dir is not None and cam_save_dir is not None:
                            frame_id = cur_data.get("frame_id_string")[elem_ind]
                            try:
                                if isinstance(frame_id, str):
                                    match = re.search(r'\d+', frame_id)
                                    frame_id_num = int(match.group()) if match else int(frame_id)
                                else:
                                    frame_id_num = int(frame_id)
                                frame_id_formatted = f"{frame_id_num:08d}"
                            except (ValueError, AttributeError):
                                frame_id_formatted = str(frame_id)
                            
                            depth_2d = cur_depth_pred_s0_b1hw.cpu().numpy().squeeze(0).astype(np.float32)
                            save_pfm(os.path.join(depth_save_dir, f"{frame_id_formatted}.pfm"), depth_2d)
                            del depth_2d
                            
                            K_elem = cur_data["K_full_depth_b44"][elem_ind] if "K_full_depth_b44" in cur_data else None
                            T_elem = cur_data["cam_T_world_b44"][elem_ind] if "cam_T_world_b44" in cur_data else None
                            world_T_elem = cur_data["world_T_cam_b44"][elem_ind] if "world_T_cam_b44" in cur_data else None
                            
                            cam_data = {
                                "frame_id": frame_id,
                                "cam_id": cam_id_str,
                                "K_full_depth_b44": K_elem.cpu().numpy().tolist() if K_elem is not None else None,
                                "cam_T_world_b44": T_elem.cpu().numpy().tolist() if T_elem is not None else None,
                                "world_T_cam_b44": world_T_elem.cpu().numpy().tolist() if world_T_elem is not None else None,
                            }
                            with open(os.path.join(cam_save_dir, f"{frame_id}_{cam_id_str}.json"), 'w') as f:
                                json.dump(cam_data, f, indent=2)
                            del cam_data, K_elem, T_elem, world_T_elem

                        if opts.mask_pred_depth:
                            overall_mask_b1hw = outputs["overall_mask_bhw"][elem_ind]
                            if overall_mask_b1hw.device != device:
                                overall_mask_b1hw = overall_mask_b1hw.to(device)
                            overall_mask_b1hw = F.interpolate(
                                overall_mask_b1hw.unsqueeze(0).unsqueeze(0).float(),
                                size=(cur_full_res_H, cur_full_res_W),
                                mode="nearest",
                            ).squeeze(0).bool()
                            cur_upsampled_depth_pred_b1hw[~overall_mask_b1hw] = 0
                            del overall_mask_b1hw

                        if opts.fusion_use_raw_lowest_cost:
                            cur_upsampled_depth_pred_b1hw = F.interpolate(
                                outputs["lowest_cost_bhw"][elem_ind].unsqueeze(0).unsqueeze(0),
                                size=(cur_full_res_H, cur_full_res_W),
                                mode="nearest",
                            ).squeeze(0)
                            
                            overall_mask_b1hw = outputs["overall_mask_bhw"][elem_ind]
                            if overall_mask_b1hw.device != device:
                                overall_mask_b1hw = overall_mask_b1hw.to(device)
                            overall_mask_b1hw = F.interpolate(
                                overall_mask_b1hw.unsqueeze(0).unsqueeze(0).float(),
                                size=(cur_full_res_H, cur_full_res_W),
                                mode="nearest",
                            ).squeeze(0).bool()
                            cur_upsampled_depth_pred_b1hw[~overall_mask_b1hw] = 0
                            del overall_mask_b1hw

                        # if "full_res_seg_ego_mask_b1hw" in cur_data:
                        #     full_res_seg_ego_mask_b1hw = cur_data["full_res_seg_ego_mask_b1hw"][elem_ind]
                        #     if full_res_seg_ego_mask_b1hw.shape[-2:] != cur_upsampled_depth_pred_b1hw.shape[-2:]:
                        #         full_res_seg_ego_mask_b1hw = F.interpolate(
                        #             full_res_seg_ego_mask_b1hw.unsqueeze(0).float(),
                        #             size=(cur_full_res_H, cur_full_res_W),
                        #             mode="nearest",
                        #         ).bool()
                        #         full_res_seg_ego_mask_b1hw = full_res_seg_ego_mask_b1hw.squeeze(0)
                        #     else:
                        #         full_res_seg_ego_mask_b1hw = full_res_seg_ego_mask_b1hw.bool()
                        #     cur_upsampled_depth_pred_b1hw[~full_res_seg_ego_mask_b1hw] = 0

                        nan_mask = torch.isnan(cur_upsampled_depth_pred_b1hw)
                        num_nan = nan_mask.sum().item()
                        
                        if num_nan > 0:
                            total_pixels = cur_upsampled_depth_pred_b1hw.numel()
                            print(f"WARNING: Found {num_nan}/{total_pixels} ({num_nan/total_pixels*100:.1f}%) nan pixels in depth prediction", flush=True)
                            del total_pixels
                        
                        valid_depth_mask = ~nan_mask & (cur_upsampled_depth_pred_b1hw > 0) & (cur_upsampled_depth_pred_b1hw < opts.fusion_max_depth)
                        num_valid_depth = valid_depth_mask.sum().item()
                        del nan_mask, valid_depth_mask
                        
                        if num_valid_depth == 0:
                            if num_nan == cur_upsampled_depth_pred_b1hw.numel():
                                print(f"Skipping frame {batch_ind}: all pixels are nan")
                            else:
                                print(f"WARNING: No valid depth values for fusion (all pixels filtered or out of range), skipping frame {batch_ind}")
                            del cur_upsampled_depth_pred_b1hw, cur_depth_pred_s0_b1hw, cur_full_res_mask_b1hw
                            continue
                        
                        K_single = cur_data["K_full_depth_b44"][elem_ind]
                        T_single = cur_data["cam_T_world_b44"][elem_ind]
                        color_single = cur_data.get("high_res_color_b3hw")[elem_ind]
                        frame_id = cur_data.get("frame_id_string")[elem_ind] if "frame_id_string" in cur_data else None
                        
                        seg_single = None
                        static_seg_single = None
                        if frame_id is not None:
                            seg_path, static_seg_path = dataset.get_cached_seg_filepath(scan, frame_id)
                            if seg_path and os.path.exists(seg_path):
                                    seg_single = seg_path
                            else:
                                if "high_res_seg_bhw" in cur_data:
                                    seg_single = cur_data.get("high_res_seg_bhw")[elem_ind]
                                    if isinstance(seg_single, torch.Tensor):
                                        seg_single = seg_single.detach().cpu()
                                    elif isinstance(seg_single, np.ndarray):
                                        seg_single = seg_single

                            if static_seg_path and os.path.exists(static_seg_path):
                                static_seg_single = static_seg_path
                        
                        confidence_single = None
                        if "confidence_bhw" in outputs:
                            confidence_single = F.interpolate(
                                outputs["confidence_bhw"][elem_ind].unsqueeze(0).unsqueeze(0),
                                size=(cur_full_res_H, cur_full_res_W),
                                mode="nearest",
                            ).squeeze()
                        
                        ref_cam_id = int(cur_data["cam_id"][elem_ind]) if "cam_id" in cur_data else None
                        
                        fusion_task = {
                            "depth_pred": cur_upsampled_depth_pred_b1hw.detach().cpu(),
                            "K": K_single.detach().cpu(),
                            "cam_T_world": T_single.detach().cpu(),
                            "color_image": color_single.detach().cpu(),
                            "seg": seg_single,
                            "static_seg": static_seg_single,
                            "cam_id": ref_cam_id,
                            "frame_id": frame_id,
                        }
                        
                        del cur_upsampled_depth_pred_b1hw, cur_depth_pred_s0_b1hw, cur_full_res_mask_b1hw
                        del K_single, T_single, color_single
                        if not isinstance(seg_single, str):
                            del seg_single
                        if not isinstance(static_seg_single, str):
                            del static_seg_single
                        if confidence_single is not None:
                            del confidence_single
                        
                        if fusion_saver is not None:
                            fusion_saver.enqueue(fusion_task)
                        else:
                            fuser.fuse_frame(**fusion_task)
                        
                        del fusion_task

            del outputs, cur_data
            if (batch_ind + 1) % max(1, getattr(opts, "cuda_cache_flush_interval", 10)) == 0:
                clear_cuda_cache()
                if (batch_ind + 1) % max(10, getattr(opts, "cuda_cache_flush_interval", 10) * 2) == 0:
                    gc.collect()

        del dataset, dataloader
        gc.collect()
        clear_cuda_cache()

        if fusion_saver is not None:
            fusion_saver.close()
            fusion_saver = None
            gc.collect()
        
        if opts.run_fusion and fuser is not None and hasattr(fuser, 'enable_async_fusion') and fuser.enable_async_fusion:
            while len(fuser.fusion_queue) > 0 and fuser.fusion_thread_running:
                time.sleep(0.01)
            time.sleep(0.1)
        
        if opts.run_fusion and fuser is not None and len(fuser.frame_infos) > 0 and save_frame_infos:
            frame_infos_save_path = os.path.join(mesh_output_dir, f"{scan.replace('/', '_')}_frame_infos.pkl")
            fuser.save_frame_infos(frame_infos_save_path)
            del frame_infos_save_path

        if fuser is not None and hasattr(fuser, 'use_disk_cache') and fuser.use_disk_cache:
            frame_data_count = len(getattr(fuser, 'frame_metadata', []))
        else:
            frame_infos_snapshot = getattr(fuser, "frame_infos", None) if fuser is not None else []
            frame_infos_snapshot = frame_infos_snapshot or []
            frame_data_count = len(frame_infos_snapshot)
        
        should_export_fusion = (
            opts.run_fusion
            and fuser is not None
            and frame_data_count > 0
        )
        if should_export_fusion:
            if fusion_type == 'pointcloud':
                output_ply_path = os.path.join(mesh_output_dir, f"{scan.replace('/', '_')}.ply")
                parent_path = Path(opts.scan_parent_directory)
                metadata_dir = os.path.join(parent_path, "mvsnet_metadata")
                fuser.export_point_cloud(
                    output_ply_path,
                    apply_statistical_filter=getattr(opts, 'fusion_apply_stat_filter', True),
                    apply_cluster_filter=getattr(opts, 'fusion_apply_cluster_filter', True),
                    voxel_size=getattr(opts, 'fusion_voxel_size', 0.05),
                    stat_nb_neighbors=getattr(opts, 'fusion_stat_nb_neighbors', 40),
                    stat_std_ratio=getattr(opts, 'fusion_stat_std_ratio', 2.0),
                    cluster_eps=getattr(opts, 'fusion_cluster_eps', 0.5),
                    cluster_min_points=getattr(opts, 'fusion_cluster_min_points', 10),
                    dbscan_voxel_size=getattr(opts, 'fusion_dbscan_voxel_size', 0.1),
                    metadata_dir=metadata_dir,
                )
                print(f"point cloud exported to: {output_ply_path}", flush=True)
                del output_ply_path, parent_path, metadata_dir
            else:
                mesh_ply_path = os.path.join(mesh_output_dir, f"{scan.replace('/', '_')}.ply")
                tsdf_path = os.path.join(mesh_output_dir, f"{scan.replace('/', '_')}_tsdf.npz")
                fuser.export_mesh(mesh_ply_path)
                fuser.save_tsdf(tsdf_path)
                print(f"TSDF mesh exported to: {mesh_output_dir}", flush=True)
                del mesh_ply_path, tsdf_path

            # if opts.compute_metrics:
            #     scene_frame_metrics.compute_final_average()
            #     all_scene_metrics.update_results(scene_frame_metrics.final_metrics)
            #     print("\nScene metrics:", flush=True)
            #     scene_frame_metrics.print_sheets_friendly(include_metrics_names=True)
            #     scene_frame_metrics.output_json(
            #         os.path.join(scores_output_dir, f"{scan.replace('/', '_')}_metrics.json")
            #     )
            #     print("\nRunning frame metrics:", flush=True)
            #     all_frame_metrics.print_sheets_friendly(
            #         include_metrics_names=False,
            #         print_running_metrics=True,
            #     )
            #     del scene_frame_metrics

            if hasattr(fuser, 'enable_async_fusion') and fuser.enable_async_fusion:
                while len(fuser.fusion_queue) > 0 and fuser.fusion_thread_running:
                    time.sleep(0.01)
                fuser.fusion_event.clear()
                if fuser.fusion_thread.is_alive():
                    fuser.fusion_thread.join(timeout=5.0)
                fuser.fusion_thread_running = False
            
            if hasattr(fuser, "all_points_xyzrgbs"):
                fuser.all_points_xyzrgbs = []
            if hasattr(fuser, "cam_to_points_xyzrgbs"):
                fuser.cam_to_points_xyzrgbs = {}
            if hasattr(fuser, "frame_infos"):
                frame_infos_ref = getattr(fuser, "frame_infos")
                if isinstance(frame_infos_ref, list):
                    frame_infos_ref.clear()
                else:
                    setattr(fuser, "frame_infos", [])
            del fuser
            fuser = None
            gc.collect()
            clear_cuda_cache()

        # if opts.compute_metrics:
        #     print("\nFinal metrics:", flush=True)
        #     all_scene_metrics.compute_final_average()
        #     all_scene_metrics.pretty_print_results(print_running_metrics=False)
        #     all_scene_metrics.print_sheets_friendly(
        #         include_metrics_names=True,
        #         print_running_metrics=False,
        #     )
        #     all_scene_metrics.output_json(
        #         os.path.join(scores_output_dir, f"all_scene_avg_metrics_{dataset_opts.split}.json")
        #     )
        #     all_frame_metrics.compute_final_average()
        #     all_frame_metrics.pretty_print_results(print_running_metrics=False)
        #     all_frame_metrics.print_sheets_friendly(
        #         include_metrics_names=True, print_running_metrics=False
        #     )
        #     all_frame_metrics.output_json(
        #         os.path.join(scores_output_dir, f"all_frame_avg_metrics_{dataset_opts.split}.json")
        #     )
        #     del all_scene_metrics, all_frame_metrics
        #     if 'scene_frame_metrics' in locals():
        #         del scene_frame_metrics
        #     gc.collect()
        
        del model
        if 'dataset_opts' in locals():
            del dataset_opts
        gc.collect()
        clear_cuda_cache()


if __name__ == "__main__":
    main()