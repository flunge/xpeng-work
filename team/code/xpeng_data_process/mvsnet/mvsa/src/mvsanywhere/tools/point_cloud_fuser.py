from numpy._typing._array_like import NDArray
import os
import re
import sys
from typing import Any, Dict
import numpy as np
import torch
import open3d as o3d
import cv2
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
import matplotlib.pyplot as plt
from types import SimpleNamespace
import time

try:
    import cupy as cp
    HAS_CUPY = True
except ImportError:
    print("No cupy found, using numpy instead")
    cp = np
    HAS_CUPY = False

from mvsnet.mvsa.src.mvsanywhere.utils.data_io import read_pfm, save_pfm

def random_down_sample_cuda(points, voxel_size):
    num_points = points.shape[0]
    min_values = np.min(points, axis=0)
    points_shifted = points - min_values

    points_shifted = torch.tensor(points_shifted).cuda()
    voxel_size = torch.tensor(voxel_size).cuda()
    voxel_indices = torch.floor((points_shifted) / voxel_size).long()

    _, sampled_indices = torch.unique(voxel_indices, return_inverse=True, dim=0)

    sampled_indices = sampled_indices.cpu()
    arg_indices = torch.argsort(sampled_indices)
    sampled_indices = sampled_indices[arg_indices]
    point_indices = torch.arange(num_points)[arg_indices]

    kept = torch.ones(num_points, dtype=bool)
    kept[:-1] = (sampled_indices[1:] != sampled_indices[:-1])
    kept_indices = torch.where(kept)[0]
    kept_indices = kept_indices.cpu().numpy()
    num_kepts = np.append(kept_indices[1:], num_points) - kept_indices

    random_indices = np.random.randint(0, num_kepts) + kept_indices
    choice_indices = point_indices[random_indices]

    mask = np.zeros(num_points, dtype=bool)
    mask[choice_indices] = True
    return mask

def _get_tensor_device():
    if HAS_CUPY and hasattr(o3d.core.cuda, "device_count") and o3d.core.cuda.device_count() > 0:
        return o3d.core.Device("CUDA:0")
    return o3d.core.Device("CPU:0")


def _write_cam(filepath, K, cam_T_world):
    f = open(filepath, "w")
    f.write('extrinsic\n')
    for i in range(0, 4):
        for j in range(0, 4):
            f.write(str(cam_T_world[i][j]) + ' ')
        f.write('\n')
    f.write('\n')
    
    f.write('intrinsic\n')
    K_3x3 = K[:3, :3] if K.shape[0] == 4 else K
    for i in range(0, 3):
        for j in range(0, 3):
            f.write(str(K_3x3[i][j]) + ' ')
        f.write('\n')
    
    f.write('\n0.0 0.0 0.0 0.0\n')
    f.close()

def _read_cam(filepath):
    with open(filepath) as f:
        lines = f.readlines()
        lines = [line.rstrip() for line in lines]
    
    extrinsics = np.fromstring(' '.join(lines[1:5]), dtype=np.float32, sep=' ').reshape((4, 4))
    intrinsics = np.fromstring(' '.join(lines[7:10]), dtype=np.float32, sep=' ').reshape((3, 3))
    
    if HAS_CUPY:
        return cp.asarray(intrinsics), cp.asarray(extrinsics)
    return intrinsics, extrinsics

class _StatisticFilterWorkspace:
    def __init__(self, chunk_size=2_000_000):
        self.chunk_size = chunk_size
        gpu_device_id = None
        if torch.cuda.is_available():
            gpu_device_id = torch.cuda.current_device()
        elif HAS_CUPY:
            try:
                gpu_device_id = cp.cuda.Device().id
            except Exception:
                pass
        
        if gpu_device_id is not None and hasattr(o3d.core.cuda, "device_count"):
            if o3d.core.cuda.device_count() > gpu_device_id:
                self.gpu_device = o3d.core.Device(f"CUDA:{gpu_device_id}")
            else:
                self.gpu_device = o3d.core.Device("CUDA:0")
        else:
            self.gpu_device = o3d.core.Device("CPU:0")
        
        self.cpu_device = o3d.core.Device("CPU:0")
        self._tmp_indices_host = None
        self._trajectory_points = None
        self._trajectory_kdtree = None

    def ensure_index_buffer(self, length):
        if self._tmp_indices_host is None or self._tmp_indices_host.shape[0] < length:
            self._tmp_indices_host = np.empty(length, dtype=np.int64)
        return self._tmp_indices_host[:length]

    def _ensure_device(self, pointcloud):
        current_device = pointcloud.point.positions.device
        is_cuda_attr = getattr(current_device, "is_cuda", None)
        is_cuda = None
        if callable(is_cuda_attr):
            try:
                is_cuda = is_cuda_attr()
            except Exception:
                is_cuda = None
        elif isinstance(is_cuda_attr, bool):
            is_cuda = is_cuda_attr
        
        if is_cuda is None:
            device_str = (
                current_device.to_string()
                if hasattr(current_device, "to_string")
                else str(current_device)
            )
            is_cuda = "CUDA" in device_str.upper()
        
        if is_cuda:
            if current_device != self.gpu_device:
                self.gpu_device = current_device
        else:
            self.gpu_device = self.cpu_device
        
        target_device = self.gpu_device
        if current_device != target_device:
            return pointcloud.to(target_device, copy=False)
        return pointcloud

    def set_trajectory(self, trajectory_points):
        if trajectory_points is None or len(trajectory_points) == 0:
            self._trajectory_points = None
            self._trajectory_kdtree = None
            return
        
        self._trajectory_points = np.asarray(trajectory_points, dtype=np.float32)
        if self._trajectory_points.shape[1] != 3:
            raise ValueError(f"trajectory points should be (N, 3) shape, but got {self._trajectory_points.shape}")
        
        try:
            from scipy.spatial import cKDTree
            self._trajectory_kdtree = cKDTree(self._trajectory_points)
        except ImportError:
            trajectory_pcd = o3d.geometry.PointCloud()
            trajectory_pcd.points = o3d.utility.Vector3dVector(self._trajectory_points)
            self._trajectory_kdtree = o3d.geometry.KDTreeFlann(trajectory_pcd)

    def _compute_distance_to_trajectory(self, points):
        if self._trajectory_points is None or len(self._trajectory_points) == 0:
            return np.full(len(points), 1e6, dtype=np.float32)
        
        points = np.asarray(points, dtype=np.float32)
        if points.ndim != 2 or points.shape[1] != 3:
            raise ValueError(f"points should be (N, 3) shape, but got {points.shape}")
        
        if hasattr(self._trajectory_kdtree, 'query'):
            distances, _ = self._trajectory_kdtree.query(points, k=1)
            return distances.astype(np.float32)
        else:
            distances = np.zeros(len(points), dtype=np.float32)
            for i, point in enumerate(points):
                [_, idx, dist_sq] = self._trajectory_kdtree.search_knn_vector_3d(point, 1)
                distances[i] = np.sqrt(dist_sq[0])
            return distances

    def _filter_chunk_adaptive(self, pointcloud, args):
        if args.voxel_size > 0:
            if self._trajectory_points is None or len(self._trajectory_points) == 0:
                points = pointcloud.point.positions.numpy().astype(np.float64)
                mask = random_down_sample_cuda(points, voxel_size=args.voxel_size)
                pointcloud = pointcloud.select_by_mask(mask)
        
        filtered_chunk, _ = pointcloud.remove_statistical_outliers(
            nb_neighbors=args.sor_neighbours,
            std_ratio=args.sor_std,
        )
        
        if int(filtered_chunk.point.positions.shape[0]) == 0:
            return None
        return filtered_chunk

    def _filter_chunk(self, pointcloud, args):
        if getattr(args, 'enable_adaptive_filter', False) and self._trajectory_points is not None:
            return self._filter_chunk_adaptive(pointcloud, args)
        
        if args.voxel_size > 0:
            points = pointcloud.point.positions.numpy().astype(np.float64)
            mask = random_down_sample_cuda(points, voxel_size=args.voxel_size)
            pointcloud = pointcloud.select_by_mask(mask)
        filtered_chunk, _ = pointcloud.remove_statistical_outliers(
            nb_neighbors=args.sor_neighbours,
            std_ratio=args.sor_std,
        )
        if int(filtered_chunk.point.positions.shape[0]) == 0:
            return None
        return filtered_chunk

    def _concat_chunks(self, chunks):
        if not chunks:
            return o3d.t.geometry.PointCloud(self.cpu_device)
        if len(chunks) == 1:
            return chunks[0]

        device = chunks[0].point.positions.device
        merged = o3d.t.geometry.PointCloud(device)
        merged.point.positions = self._concat_tensors([chunk.point.positions for chunk in chunks], device)

        sample_attrs = [key for key in chunks[0].point if key != "positions"]
        
        for attr in sample_attrs:
            merged.point[attr] = self._concat_tensors([chunk.point[attr] for chunk in chunks], device)
        return merged

    def _concat_tensors(self, tensors, device):
        if not tensors:
            return o3d.core.Tensor([], device=device)
        if hasattr(o3d.core, "concatenate"):
            return o3d.core.concatenate(tensors, axis=0)
        data = np.concatenate([tensor.cpu().numpy() for tensor in tensors], axis=0)
        return o3d.core.Tensor(data, device=device)

    def _iter_chunks(self, pointcloud):
        num_points = int(pointcloud.point.positions.shape[0])
        if num_points == 0:
            return
        chunk_size = self.chunk_size
        for start in range(0, num_points, chunk_size):
            end = min(num_points, start + chunk_size)
            length = end - start
            host_indices = self.ensure_index_buffer(length)
            host_indices[:length] = np.arange(start, end, dtype=np.int64)
            indices = o3d.core.Tensor(host_indices, dtype=o3d.core.Dtype.Int64, device=pointcloud.point.positions.device)
            yield pointcloud.select_by_index(indices, invert=False)

    def apply(self, args, pointcloud):
        pointcloud = self._ensure_device(pointcloud)
        num_points = int(pointcloud.point.positions.shape[0])
        if num_points <= self.chunk_size:
            filtered = self._filter_chunk(pointcloud, args)
            if filtered is None:
                filtered = o3d.t.geometry.PointCloud(self.cpu_device)
        else:
            filtered_chunks = []
            for chunk in self._iter_chunks(pointcloud):
                filtered_chunk = self._filter_chunk(chunk, args)
                if filtered_chunk is not None:
                    filtered_chunks.append(filtered_chunk)
            filtered = self._concat_chunks(filtered_chunks)
        return filtered.to(self.cpu_device, copy=False)

STATISTIC_FILTER_WORKSPACE = _StatisticFilterWorkspace()

def reverse_imagenet_normalize(image):
    import torchvision.transforms.functional as TF
    image = TF.normalize(
        tensor=image,
        mean=(-2.11790393, -2.03571429, -1.80444444),
        std=(4.36681223, 4.46428571, 4.44444444),
    )
    return image

def to_numpy(arr):
    if HAS_CUPY and isinstance(arr, cp.ndarray):
        return arr.get()
    else:
        return np.asarray(arr)

def statistic_filter(args, pointcloud, trajectory_points=None):
    if trajectory_points is not None:
        STATISTIC_FILTER_WORKSPACE.set_trajectory(trajectory_points)
    return STATISTIC_FILTER_WORKSPACE.apply(args, pointcloud)

def cluster_filter(args, pointcloud):
    cluster_min_point = 3*args.cluster_core_min_point
    pointcloud_legacy = pointcloud.to_legacy()
    points = pointcloud.point.positions.numpy().astype(np.float64)
    mask = random_down_sample_cuda(points, voxel_size=args.dbscan_voxel_size)
    pointcloud_for_dbscan = pointcloud.select_by_mask(mask).to_legacy()
    with o3d.utility.VerbosityContextManager(o3d.utility.VerbosityLevel.Debug) as cm:
        labels = np.array(pointcloud_for_dbscan.cluster_dbscan(eps=args.dbscan_radius, min_points=args.cluster_core_min_point, print_progress=True))
    if len(labels) == 0:
        print("No cluster found.")
        return pointcloud
    max_label = labels.max()
    label_counter = Counter(labels)
    print(f"point cloud has {max_label + 1} clusters")
    colors = plt.get_cmap("tab20")(labels / (max_label if max_label > 0 else 1))
    for i in range(len(labels)):
        if label_counter[labels[i]] < cluster_min_point:
            labels[i] = -1
    colors[labels == -1] = 0
    
    dbscan_outliers_points = np.asarray(pointcloud_for_dbscan.points)[labels == -1]
    voxel_inlier_kdtree = o3d.geometry.KDTreeFlann(pointcloud_legacy)
    outlier_indices = []

    outlier_radius = args.dbscan_voxel_size*0.5 + args.voxel_size
    for point in dbscan_outliers_points:
        [_, idx, _] = voxel_inlier_kdtree.search_radius_vector_3d(point, outlier_radius)
        outlier_indices.extend(idx)
    print('cluster outlier size:{}/{}'.format(len(outlier_indices),len(pointcloud_legacy.points)))
    final_cloud = pointcloud.select_by_index(outlier_indices, invert=True)
    return final_cloud

class PointCloudFuser:
    def __init__(
        self,
        conf_threshold=0.8,
        min_depth=0.5,
        max_depth=100.0,
        save_debug_info=False,
        enable_geometric_consistency=True,
        img_dist_thres=1.0,
        depth_thres=0.01,
        thres_view=3,
        cross_cam_id_threshold=20,
        cross_dist_thres=15.0,
        enable_cross_camera=True,
        **kwargs
    ):
        self.conf_threshold = conf_threshold
        self.min_depth = min_depth
        self.max_depth = max_depth
        self.save_debug_info = save_debug_info
        self.depth_max_buffer = kwargs.get("depth_max_buffer", 5.0)
        self.depth_min_buffer = kwargs.get("depth_min_buffer", 1.0)
        self.cam0_max_depth = 80
        self.cam2_max_depth = 80
        self.cam_back_max_depth = 50
        self.cam_side_max_depth = 50
        
        self.enable_geometric_consistency = enable_geometric_consistency
        self.img_dist_thres = img_dist_thres
        self.depth_thres = depth_thres
        self.thres_view = thres_view
        self.cross_cam_id_threshold = cross_cam_id_threshold
        self.cross_dist_thres = cross_dist_thres
        self.enable_cross_camera = enable_cross_camera
        self.postprocess_num_workers = kwargs.get("postprocess_num_workers") or max(1, min(8, (os.cpu_count() or 1)))
        self.all_points_xyzrgbs = []
        self.cam_to_points_xyzrgbs = {}
        self.frame_infos = []
        self.slice_number_to_view = {}
        self.view_to_slice = {}
        self.save_each_cam_ply = kwargs.get("save_each_cam_ply", False)
        
        self.frame_cache_dir = kwargs.get("frame_cache_dir", None)
        self.use_disk_cache = self.frame_cache_dir is not None
        self._io_executor = None
        if self.use_disk_cache:
            os.makedirs(self.frame_cache_dir, exist_ok=True)
            os.makedirs(os.path.join(self.frame_cache_dir, "depth"), exist_ok=True)
            os.makedirs(os.path.join(self.frame_cache_dir, "cams"), exist_ok=True)
            os.makedirs(os.path.join(self.frame_cache_dir, "images"), exist_ok=True)
            os.makedirs(os.path.join(self.frame_cache_dir, "seg"), exist_ok=True)
            os.makedirs(os.path.join(self.frame_cache_dir, "confidence"), exist_ok=True)
            self.frame_metadata = []
            self._io_executor = ThreadPoolExecutor(max_workers=min(4, (os.cpu_count() or 4) // 2), thread_name_prefix="fuser_io")
        
        self.mask_vehicle = kwargs.get("mask_vehicle", False)
        self.cross_consistence_flag = kwargs.get("cross_consistence_flag", True)
        self.crop_ratio = kwargs.get("crop_ratio", 12)
        
        allowed_cam_ids = kwargs.get("allowed_cam_ids", None)
        if allowed_cam_ids is not None:
            self.allowed_cam_ids = set()
            for cam_id in allowed_cam_ids:
                normalized = self._normalize_cam_id(cam_id)
                if normalized:
                    self.allowed_cam_ids.add(normalized)
            if len(self.allowed_cam_ids) == 0:
                self.allowed_cam_ids = None
        else:
            self.allowed_cam_ids = None

    def __del__(self):
        if hasattr(self, '_io_executor') and self._io_executor is not None:
            self._io_executor.shutdown(wait=True)
    
    def reset(self):
        self.all_points_xyzrgbs = []
        self.cam_to_points_xyzrgbs = {}
        self.frame_infos.clear()
    
    def save_frame_infos(self, save_path):
        import pickle
        os.makedirs(os.path.dirname(save_path) if os.path.dirname(save_path) else '.', exist_ok=True)
        with open(save_path, 'wb') as f:
            pickle.dump(self.frame_infos, f)
        print(f"[INFO] Saved {len(self.frame_infos)} frame_infos to {save_path}", flush=True)
    
    def load_frame_infos(self, load_path):
        import pickle
        with open(load_path, 'rb') as f:
            self.frame_infos = pickle.load(f)
        print(f"[INFO] Loaded {len(self.frame_infos)} frame_infos from {load_path}", flush=True)
    
    def _get_camera_center(self, extrinsics):
        extrinsics_np = np.asarray(extrinsics, dtype=np.float64)
        R = extrinsics_np[:3, :3]
        t = extrinsics_np[:3, 3]
        center = -np.matmul(R.T, t)
        return center
    
    def _extract_trajectory_from_frames(self):
        if len(self.frame_infos) == 0:
            return None
        
        trajectory_points = []
        seen_positions = set()
        
        for frame_info in self.frame_infos:
            try:
                cam_id = frame_info.get('cam_id')
                if cam_id is None:
                    continue
                
                cam_id_str = str(cam_id).lower().replace('cam', '')
                if cam_id_str != '2':
                    continue
                
                frame_data = self._load_frame_data(frame_info, load_depth=False, load_camera=True, load_image=False, load_seg=False)
                cam_T_world = frame_data.get('cam_T_world')
                if cam_T_world is None:
                    continue
                
                camera_center = self._get_camera_center(cam_T_world)
                
                pos_key = tuple(np.round(camera_center, decimals=2))
                if pos_key not in seen_positions:
                    trajectory_points.append(camera_center)
                    seen_positions.add(pos_key)
            except Exception as e:
                continue
        
        if len(trajectory_points) == 0:
            return None
        
        trajectory_points = np.array(trajectory_points, dtype=np.float32)
        if len(trajectory_points) > 1:
            start_point = trajectory_points[0]
            distances = np.linalg.norm(trajectory_points - start_point, axis=1)
            sorted_indices = np.argsort(distances)
            trajectory_points = trajectory_points[sorted_indices]
        
        return trajectory_points
    
    def get_visiable_slice(self, view_id_to_info, ref_frame_id, ref_cam_id, dist_thres):
        ref_frame_id_int = int(ref_frame_id)
        ref_cam_id_str = str(ref_cam_id).replace('cam', '')
        ref_key = (str(ref_frame_id_int), ref_cam_id_str)
        
        if ref_key not in view_id_to_info:
            return str(ref_frame_id_int), str(ref_frame_id_int), ref_frame_id_int, ref_frame_id_int
        
        ref_view = view_id_to_info[ref_key]
        ref_view_data = self._load_frame_data(ref_view, load_depth=False, load_camera=True, load_image=False, load_seg=False)
        ref_center = self._get_camera_center(ref_view_data['cam_T_world'])
        
        same_cam_frames = []
        for (fid, cid) in view_id_to_info.keys():
            if cid != ref_cam_id_str:
                continue
            try:
                same_cam_frames.append(int(fid))
            except ValueError:
                continue
        same_cam_frames = sorted(set(same_cam_frames))
        if ref_frame_id_int not in same_cam_frames:
            same_cam_frames.append(ref_frame_id_int)
            same_cam_frames.sort()
        ref_idx = same_cam_frames.index(ref_frame_id_int)
        
        last_slice_index = ref_frame_id_int
        for fid in reversed(same_cam_frames[:ref_idx]):
            key = (str(fid), ref_cam_id_str)
            view = view_id_to_info.get(key)
            if view is None:
                continue
            center = self._get_camera_center(self._load_frame_data(view, load_depth=False, load_camera=True, load_image=False, load_seg=False)['cam_T_world'])
            dist = np.linalg.norm(center - ref_center)
            if dist > dist_thres:
                break
            last_slice_index = fid
        
        next_slice_index = ref_frame_id_int
        for fid in same_cam_frames[ref_idx + 1:]:
            key = (str(fid), ref_cam_id_str)
            view = view_id_to_info.get(key)
            if view is None:
                continue
            center = self._get_camera_center(self._load_frame_data(view, load_depth=False, load_camera=True, load_image=False, load_seg=False)['cam_T_world'])
            dist = np.linalg.norm(center - ref_center)
            if dist > dist_thres:
                break
            next_slice_index = fid
        
        return last_slice_index, next_slice_index
    
    def get_confidence_mask(self, confidence):
        if isinstance(confidence, torch.Tensor):
            confidence = confidence.cpu().numpy()
        if confidence is None:
            return None
        return cp.asarray(confidence > self.conf_threshold)

    def get_depth_mask(self, depth_map, cam_id):
        if depth_map is None:
            return None
        
        try:
            if isinstance(depth_map, torch.Tensor):
                depth_map = depth_map.cpu().numpy()
            elif isinstance(depth_map, cp.ndarray):
                depth_map = cp.asnumpy(depth_map)
            elif not isinstance(depth_map, np.ndarray):
                depth_map = np.asarray(depth_map)
            
            if depth_map.size == 0:
                print(f"[WARNING] Empty depth_map for cam_id {cam_id}", flush=True)
                return None
            
            if depth_map.ndim == 0:
                print(f"[WARNING] Scalar depth_map for cam_id {cam_id}, shape: {depth_map.shape}", flush=True)
                return None
            
            if np.any(np.isnan(depth_map)) or np.any(np.isinf(depth_map)):
                print(f"[WARNING] depth_map contains NaN or Inf values for cam_id {cam_id}, replacing with 0", flush=True)
                depth_map = np.nan_to_num(depth_map, nan=0.0, posinf=0.0, neginf=0.0)
            
            if not depth_map.flags['C_CONTIGUOUS']:
                depth_map = np.ascontiguousarray(depth_map)
            
            if depth_map.dtype != np.float32:
                depth_map = depth_map.astype(np.float32)
            
            cam_name = str(cam_id)
            if not cam_name.startswith('cam'):
                cam_name = f'cam{cam_name}'

            if cam_name == "cam0":
                depth_max = self.cam0_max_depth
            elif cam_name == "cam2":
                depth_max = self.cam2_max_depth
            elif cam_name == "cam7":
                depth_max = self.cam_back_max_depth
            else:
                depth_max = self.cam_side_max_depth

            try:
                depth_cp = cp.asarray(depth_map, dtype=cp.float32)
            except Exception as e:
                print(f"[ERROR] Failed to convert depth_map to CuPy array for cam_id {cam_id}: {e}", flush=True)
                print(f"  depth_map type: {type(depth_map)}, shape: {depth_map.shape}, dtype: {depth_map.dtype}", flush=True)
                print(f"  depth_map flags: C_CONTIGUOUS={depth_map.flags['C_CONTIGUOUS']}, "
                      f"F_CONTIGUOUS={depth_map.flags['F_CONTIGUOUS']}", flush=True)
                depth_map = np.ascontiguousarray(depth_map.astype(np.float32))
                depth_cp = cp.asarray(depth_map, dtype=cp.float32)
            
            depth_min = self.min_depth + self.depth_min_buffer
            depth_max_threshold = depth_max - self.depth_max_buffer
            depth_mask = cp.logical_and(depth_cp < depth_max_threshold, depth_cp > depth_min)
            return depth_mask
        except Exception as e:
            print(f"[ERROR] Error in get_depth_mask for cam_id {cam_id}: {e}", flush=True)
            print(f"  depth_map type: {type(depth_map)}, shape: {getattr(depth_map, 'shape', 'N/A')}", flush=True)
            import traceback
            traceback.print_exc()
            return None
    
    def compute_depth_gradient(self, depth):
        depth_cp = cp.asarray(depth, dtype=cp.float32)
        grad_x, grad_y = cp.gradient(depth_cp)
        gradient_mag = cp.sqrt(grad_x**2 + grad_y**2)
        return gradient_mag
    
    def reproject_with_depth(self, depth_ref, intrinsics_ref, extrinsics_ref, 
                            depth_src, intrinsics_src, extrinsics_src):
        depth_ref_cp = cp.asarray(depth_ref)
        depth_src_cp = cp.asarray(depth_src)
        
        if intrinsics_ref.shape[0] == 4:
            K_ref = cp.asarray(intrinsics_ref[:3, :3])
        else:
            K_ref = cp.asarray(intrinsics_ref)
        
        if intrinsics_src.shape[0] == 4:
            K_src = cp.asarray(intrinsics_src[:3, :3])
        else:
            K_src = cp.asarray(intrinsics_src)
        
        extrinsics_ref_cp = cp.asarray(extrinsics_ref)
        extrinsics_src_cp = cp.asarray(extrinsics_src)
        
        width, height = depth_ref.shape[1], depth_ref.shape[0]
        
        arange = cp.arange(0, width * height).reshape(height, width)
        x_ref, y_ref = arange % width, arange // width
        x_ref, y_ref = x_ref.reshape([-1]), y_ref.reshape([-1])
        
        xyz_ref = cp.matmul(
            cp.linalg.inv(K_ref),
            cp.vstack((x_ref, y_ref, cp.ones_like(x_ref))) * depth_ref_cp.reshape([-1])
        )
        
        xyz_src = cp.matmul(
            cp.matmul(extrinsics_src_cp, cp.linalg.inv(extrinsics_ref_cp)),
            cp.vstack((xyz_ref, cp.ones_like(x_ref)))
        )[:3]
        
        K_xyz_src = cp.matmul(K_src, xyz_src)
        xy_src = K_xyz_src[:2] / K_xyz_src[2:3]
        
        x_src = xy_src[0].reshape([height, width]).astype(cp.float32)
        y_src = xy_src[1].reshape([height, width]).astype(cp.float32)
        
        sampled_depth_src = cv2.remap(
            to_numpy(depth_src_cp), 
            to_numpy(x_src), 
            to_numpy(y_src), 
            interpolation=cv2.INTER_LINEAR
        )
        sampled_depth_src = cp.asarray(sampled_depth_src)
        
        xyz_src = cp.matmul(
            cp.linalg.inv(K_src),
            cp.vstack((xy_src, cp.ones_like(x_ref))) * sampled_depth_src.reshape([-1])
        )
        
        xyz_reprojected = cp.matmul(
            cp.matmul(extrinsics_ref_cp, cp.linalg.inv(extrinsics_src_cp)),
            cp.vstack((xyz_src, cp.ones_like(x_ref)))
        )[:3]
        
        depth_reprojected = xyz_reprojected[2].reshape([height, width]).astype(cp.float32)
        
        K_xyz_reprojected = cp.matmul(K_ref, xyz_reprojected)
        xy_reprojected = K_xyz_reprojected[:2] / K_xyz_reprojected[2:3]
        x_reprojected = xy_reprojected[0].reshape([height, width]).astype(cp.float32)
        y_reprojected = xy_reprojected[1].reshape([height, width]).astype(cp.float32)
        
        return depth_reprojected, x_reprojected, y_reprojected, x_src, y_src
    
    def check_geometric_consistency_cross(self, depth_ref, intrinsics_ref, 
                                        extrinsics_ref, depth_src, intrinsics_src, extrinsics_src, src_gradient):
        width, height = depth_ref.shape[1], depth_ref.shape[0]
        x_ref, y_ref = cp.meshgrid(cp.arange(0, width), cp.arange(0, height))
        
        depth_reprojected, x2d_reprojected, y2d_reprojected, x2d_src, y2d_src = \
            self.reproject_with_depth(
                depth_ref, intrinsics_ref, extrinsics_ref,
                depth_src, intrinsics_src, extrinsics_src
            )
        
        # check |p_reproj - p_ref| < img_dist_thres
        dist = cp.sqrt((x2d_reprojected - x_ref) ** 2 + (y2d_reprojected - y_ref) ** 2)
        
        # check |d_reproj - d_ref| / d_ref < depth_thres
        depth_ref_cp = cp.asarray(depth_ref)
        depth_diff = cp.abs(depth_reprojected - depth_ref_cp)
        relative_depth_diff = depth_diff / (depth_ref_cp + 1e-6)
        
        mask = cp.logical_and(
            dist < self.img_dist_thres, 
            relative_depth_diff < self.depth_thres
        )
        depth_reprojected[~mask] = 0
        
        MAX_NUM = 9999.0
        src_gradient_cp = cp.asarray(src_gradient)
        gradient_reproj = cp.ones_like(depth_ref_cp) * MAX_NUM
        
        y_idx = cp.clip(cp.around(y2d_reprojected).astype(int), 0, height - 1)
        x_idx = cp.clip(cp.around(x2d_reprojected).astype(int), 0, width - 1)
        y_src_idx = cp.clip(cp.around(y2d_src).astype(int), 0, height - 1)
        x_src_idx = cp.clip(cp.around(x2d_src).astype(int), 0, width - 1)
        
        gradient_reproj[y_idx, x_idx] = src_gradient_cp[y_src_idx, x_src_idx]
        
        return mask, depth_reprojected, gradient_reproj, x2d_src, y2d_src
    
    def _to_int_or_none(self, value):
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValueError(f"Failed to convert value to int: {value}")

    def get_geometric_mask_and_average_depth_cross(
        self, 
        ref_depth, 
        ref_intrinsics, 
        ref_extrinsics,
        src_depths, 
        src_intrinsics_list, 
        src_extrinsics_list,
        ref_frame_id=None,
        src_frame_ids=None,
    ):
        ref_init_depth = cp.asarray(ref_depth, dtype=cp.float32)
        ref_init_gradient = self.compute_depth_gradient(ref_init_depth)

        geometric_mask_sum = cp.zeros_like(ref_init_depth, dtype=cp.int32)
        cross_geometric_mask_sum = cp.zeros_like(ref_init_depth, dtype=cp.int32)

        ref_frame_id_int = self._to_int_or_none(ref_frame_id)

        for i, src_depth in enumerate(src_depths):
            src_intrinsics = src_intrinsics_list[i]
            src_extrinsics = src_extrinsics_list[i]
            src_frame_id = None
            if src_frame_ids and i < len(src_frame_ids):
                src_frame_id = src_frame_ids[i]

            src_depth_cp = cp.asarray(src_depth, dtype=cp.float32)
            src_gradient = self.compute_depth_gradient(src_depth_cp)

            geometric_mask, depth_reprojected, gradient_reproj, x2d_src, y2d_src = \
                self.check_geometric_consistency_cross(
                    ref_init_depth, ref_intrinsics, ref_extrinsics,
                    src_depth_cp, src_intrinsics, src_extrinsics,
                    src_gradient
                )

            condition_min = cp.logical_and(
                cp.abs(gradient_reproj) > 0.001,
                cp.abs(gradient_reproj) < cp.abs(ref_init_gradient)
            )
            ref_init_depth_min = cp.where(condition_min, depth_reprojected, ref_init_depth)
            
            mask_depth_error0 = cp.logical_and(
                cp.abs(depth_reprojected - ref_init_depth) < 0.3,
                cp.abs(depth_reprojected - ref_init_depth) > 0.01
            )
            mask_depth_error1 = cp.logical_and(
                ref_init_gradient < 0.1,
                cp.logical_and(
                    gradient_reproj < 0.1,
                    cp.abs(ref_init_gradient - gradient_reproj) < 0.1
                )
            )
            mask_depth_error = cp.logical_and(mask_depth_error0, mask_depth_error1)
            
            ave_depth = (depth_reprojected + ref_init_depth) / 2
            ref_init_depth = cp.where(mask_depth_error, ave_depth, ref_init_depth_min)
            ref_init_gradient = cp.where(condition_min, gradient_reproj, ref_init_gradient)

            src_frame_id_int = self._to_int_or_none(src_frame_id)

            if ref_frame_id_int is not None and src_frame_id_int is not None:
                if abs(ref_frame_id_int - src_frame_id_int) < self.cross_cam_id_threshold:
                    geometric_mask_sum += geometric_mask.astype(cp.int32)
                else:
                    cross_geometric_mask_sum += geometric_mask.astype(cp.int32)
            else:
                raise ValueError(f"Failed to convert frame_id to int: {src_frame_id}")

        total_votes = geometric_mask_sum + cross_geometric_mask_sum
        geometric_mask = total_votes >= self.thres_view
        average_depth = ref_init_depth

        return geometric_mask, average_depth
    
    def fuse_frame(
        self,
        depth_pred,
        K,
        cam_T_world,
        color_image,
        seg,
        static_seg=None,
        confidence=None,
        cam_id=None,
        frame_id=None
    ):
        """
        Args:
            depth_pred: (1, H, W) or (H, W) invalid set to 0
            K: intrinsics (4, 4)
            cam_T_world: extrinsics (4, 4), world2cam
            color_image: RGB img (3, H, W)
            seg: segmentation (H, W)
            confidence: (H, W)
            src_depths: list of (H, W)
            src_Ks: list of (4, 4)
            src_Ts: list of (4, 4)
            cam_id: int
            src_cam_ids: list of int
            frame_id: str
        """
        if self.allowed_cam_ids is not None:
            cam_id_normalized = self._normalize_cam_id(cam_id)
            if cam_id_normalized not in self.allowed_cam_ids:
                return
        
        depth_pred_np = depth_pred if isinstance(depth_pred, np.ndarray) else depth_pred.cpu().numpy()
        K_np = K if isinstance(K, np.ndarray) else K.cpu().numpy()
        cam_T_world_np = cam_T_world if isinstance(cam_T_world, np.ndarray) else cam_T_world.cpu().numpy()
        
        color_image_np = color_image if isinstance(color_image, np.ndarray) else color_image.cpu().numpy()
        if color_image_np.ndim == 3 and color_image_np.shape[0] == 3:
            color_image_np = color_image_np.transpose(1, 2, 0)
        
        confidence_np = confidence if confidence is None or isinstance(confidence, np.ndarray) else confidence.cpu().numpy()
        
        seg_path = None
        seg_np = None
        if isinstance(seg, str):
            seg_path = seg
        else:
            seg_np = seg if isinstance(seg, np.ndarray) else seg.cpu().numpy()
            if seg_np.ndim == 3:
                if seg_np.shape[0] == 1:
                    seg_np = seg_np[0]
                elif seg_np.shape[2] == 1:
                    seg_np = seg_np[:, :, 0]
                else:
                    seg_np = seg_np[:, :, 0]
            if seg_np.dtype != np.uint8:
                seg_np = seg_np.astype(np.uint8)
        
        static_seg_path = None
        static_seg_np = None
        if static_seg is not None:
            if isinstance(static_seg, str):
                static_seg_path = static_seg
            else:
                static_seg_np = static_seg if isinstance(static_seg, np.ndarray) else static_seg.cpu().numpy()
                if static_seg_np.ndim == 3:
                    if static_seg_np.shape[0] == 1:
                        static_seg_np = static_seg_np[0]
                    elif static_seg_np.shape[2] == 1:
                        static_seg_np = static_seg_np[:, :, 0]
                    else:
                        static_seg_np = static_seg_np[:, :, 0]
                if static_seg_np.dtype != np.uint8:
                    static_seg_np = static_seg_np.astype(np.uint8)
        
        if self.use_disk_cache:
            self._save_frame_to_disk(
                frame_id=frame_id,
                cam_id=cam_id,
                depth_pred=depth_pred_np,
                K=K_np,
                cam_T_world=cam_T_world_np,
                color_image=color_image_np,
                seg=seg_path if seg_path is not None else seg_np,
                static_seg=static_seg_path if static_seg_path is not None else static_seg_np,
                confidence=confidence_np,
            )
        else:
            frame_data = {
                'frame_id': frame_id,
                'cam_id': cam_id,
                'depth_pred': depth_pred_np,
                'K': K_np,
                'cam_T_world': cam_T_world_np,
                'color_image': color_image_np,
                'confidence': confidence_np,
                'seg': seg_path if seg_path is not None else seg_np,
                'static_seg': static_seg_path if static_seg_path is not None else static_seg_np,
            }
            self.frame_infos.append(frame_data)

    def _get_frame_filename(self, frame_id, cam_id, suffix):
        cam_id_str = str(cam_id).replace('cam', '')
        frame_id_str = str(frame_id)
        match = re.search(r'\d+', frame_id_str)
        if match:
            frame_id_num = int(match.group())
            frame_id_formatted = f"{frame_id_num:08d}"
        else:
            frame_id_formatted = frame_id_str.replace('/', '_').replace('\\', '_')
        return f"{frame_id_formatted}_{cam_id_str}{suffix}"
    
    def _save_frame_to_disk(self, frame_id, cam_id, depth_pred, K, cam_T_world, color_image, seg, static_seg=None, confidence=None):
        filename_base = self._get_frame_filename(frame_id, cam_id, "")
        
        depth_filename = os.path.join(self.frame_cache_dir, "depth", f"{filename_base}.pfm")
        if depth_pred.ndim == 3:
            depth_pred_2d = depth_pred[0] if depth_pred.shape[0] == 1 else depth_pred.squeeze()
        else:
            depth_pred_2d = depth_pred
        depth_pred_2d = depth_pred_2d.astype(np.float32)
        if HAS_CUPY:
            depth_pred_2d = cp.asarray(depth_pred_2d)
        
        cam_filename = os.path.join(self.frame_cache_dir, "cams", f"{filename_base}_cam.txt")
        
        img_filename = os.path.join(self.frame_cache_dir, "images", f"{filename_base}.png")
        if HAS_CUPY and isinstance(color_image, cp.ndarray):
            color_image_np = to_numpy(color_image)
        else:
            color_image_np = np.asarray(color_image)
        
        if color_image_np.ndim == 3:
            if color_image_np.shape[0] == 3:  # (3, H, W) -> (H, W, 3)
                color_image_np = color_image_np.transpose(1, 2, 0)
            elif color_image_np.shape[2] == 1:  # (H, W, 1) -> (H, W, 3)
                color_image_np = np.repeat(color_image_np, 3, axis=2)
        elif color_image_np.ndim == 2:  # (H, W) -> (H, W, 3)
            color_image_np = np.stack([color_image_np] * 3, axis=2)
        
        if color_image_np.shape[2] != 3:
            raise ValueError(f"color_image must have 3 channels, but got shape {color_image_np.shape}")
        
        if color_image_np.dtype != np.uint8:
            img_min = float(color_image_np.min())
            img_max = float(color_image_np.max())
            if img_max <= 1.0 and img_min >= 0.0:
                color_image_uint8 = (color_image_np * 255.0).astype(np.uint8)
            elif img_max <= 255.0 and img_min >= 0.0:
                color_image_uint8 = color_image_np.astype(np.uint8)
            else:
                if img_min < 0.0 or img_max > 1.0:
                    try:
                        color_tensor = torch.from_numpy(color_image_np.transpose(2, 0, 1))
                        color_tensor = reverse_imagenet_normalize(color_tensor)
                        color_image_np = color_tensor.numpy().transpose(1, 2, 0)
                        color_image_np = np.clip(color_image_np, 0, 1)
                        color_image_uint8 = (color_image_np * 255.0).astype(np.uint8)
                    except Exception:
                        if img_max > img_min:
                            color_image_uint8 = ((color_image_np - img_min) / (img_max - img_min) * 255.0).astype(np.uint8)
                        else:
                            color_image_uint8 = np.zeros_like(color_image_np, dtype=np.uint8)
                else:
                    if img_max > img_min:
                        color_image_uint8 = ((color_image_np - img_min) / (img_max - img_min) * 255.0).astype(np.uint8)
                    else:
                        color_image_uint8 = np.zeros_like(color_image_np, dtype=np.uint8)
        else:
            color_image_uint8 = color_image_np
        
        color_image_bgr = cv2.cvtColor(color_image_uint8, cv2.COLOR_RGB2BGR)
        
        seg_filename = os.path.join(self.frame_cache_dir, "seg", f"{filename_base}_seg.png")
        seg_path = None
        
        if isinstance(seg, str):
            seg_path = seg
        else:
            seg_np = np.asarray(seg) if not isinstance(seg, np.ndarray) else seg
            if seg_np.dtype != np.uint8:
                seg_np = seg_np.astype(np.uint8)
        
        static_seg_filename = os.path.join(self.frame_cache_dir, "seg", f"{filename_base}_static_seg.png")
        static_seg_path = None
        static_seg_np = None
        if static_seg is not None:
            if isinstance(static_seg, str):
                static_seg_path = static_seg
            else:
                static_seg_np = np.asarray(static_seg) if not isinstance(static_seg, np.ndarray) else static_seg
                if static_seg_np.dtype != np.uint8:
                    static_seg_np = static_seg_np.astype(np.uint8)
        
        conf_data = None
        conf_filename = None
        if confidence is not None:
            conf_filename = os.path.join(self.frame_cache_dir, "confidence", f"{filename_base}.pfm")
            if confidence.ndim == 3:
                confidence_2d = confidence[0] if confidence.shape[0] == 1 else confidence.squeeze()
            else:
                confidence_2d = confidence
            confidence_2d = confidence_2d.astype(np.float32)
            if HAS_CUPY:
                confidence_2d = cp.asarray(confidence_2d)
            conf_data = confidence_2d
        
        if self._io_executor is not None:
            futures = []
            futures.append(self._io_executor.submit(save_pfm, depth_filename, depth_pred_2d))
            futures.append(self._io_executor.submit(_write_cam, cam_filename, K, cam_T_world))
            futures.append(self._io_executor.submit(cv2.imwrite, img_filename, color_image_bgr))
            if seg_path is None:
                futures.append(self._io_executor.submit(cv2.imwrite, seg_filename, seg_np))
            if static_seg_path is None and static_seg_np is not None:
                futures.append(self._io_executor.submit(cv2.imwrite, static_seg_filename, static_seg_np))
            if conf_data is not None:
                futures.append(self._io_executor.submit(save_pfm, conf_filename, conf_data))
            
            # Wait for all I/O operations to complete
            for future in futures:
                future.result()
        else:
            # Fallback to sequential I/O if executor is not available
            save_pfm(depth_filename, depth_pred_2d)
            _write_cam(cam_filename, K, cam_T_world)
            cv2.imwrite(img_filename, color_image_bgr)
            if seg_path is None:
                cv2.imwrite(seg_filename, seg_np)
            if static_seg_path is None and static_seg_np is not None:
                cv2.imwrite(static_seg_filename, static_seg_np)
            if conf_data is not None:
                save_pfm(conf_filename, conf_data)
        
        frame_id_str = str(frame_id)
        cam_id_normalized = self._normalize_cam_id(cam_id)
        if cam_id_normalized is None:
            cam_id_normalized = str(cam_id)
        
        frame_metadata_entry = {
            'frame_id': frame_id_str,
            'cam_id': cam_id_normalized,
            'filename_base': filename_base,
        }
        
        if seg_path is not None:
            frame_metadata_entry['seg_path'] = seg_path
        if static_seg_path is not None:
            frame_metadata_entry['static_seg_path'] = static_seg_path
        
        existing_index = None
        for idx, existing_entry in enumerate(self.frame_metadata):
            existing_frame_id = str(existing_entry.get('frame_id', ''))
            existing_cam_id = existing_entry.get('cam_id', '')
            existing_cam_id_normalized = self._normalize_cam_id(existing_cam_id)
            if existing_cam_id_normalized is None:
                existing_cam_id_normalized = str(existing_cam_id)
            
            if (existing_frame_id == frame_id_str and 
                existing_cam_id_normalized == cam_id_normalized):
                existing_index = idx
                break
        
        if existing_index is not None:
            self.frame_metadata[existing_index] = frame_metadata_entry
        else:
            self.frame_metadata.append(frame_metadata_entry)
    
    def _create_mask(self, mask_hr, static_seg=None):
        if self.mask_vehicle:
            mask_conditions = [(0 <= mask_hr) & (mask_hr <= 1), (19 <= mask_hr) & (mask_hr <= 22), mask_hr >= 52, mask_hr == 27]
        else:
            mask_conditions = [(0 <= mask_hr) & (mask_hr <= 1), (19 <= mask_hr) & (mask_hr <= 22), mask_hr == 27]
        
        if static_seg is not None:
            assert static_seg.shape == mask_hr.shape, f"static_seg shape {static_seg.shape} does not match mask_hr shape {mask_hr.shape}"
            static_seg_zero_mask = (static_seg == 100)
            filtered_regions = np.logical_or.reduce(mask_conditions)
            # 最终要过滤的区域 = 在filtered_regions中，但不在static_seg_zero_mask中
            combined_filter = np.logical_and(filtered_regions, ~static_seg_zero_mask)
            mask_hr = 1 - combined_filter.astype(np.uint8)
        else:
            mask_hr = 1 - np.logical_or.reduce(mask_conditions).astype(np.uint8)
        
        mask_result = cv2.bitwise_not(mask_hr)
        return mask_result
    
    def _dilate_mask(self, mask, kernel_size=(10, 10), iterations=2):
        kernel = np.ones(kernel_size, dtype=np.uint8)
        dilated_mask = cv2.dilate(mask, kernel, iterations=iterations)
        return cv2.bitwise_not(dilated_mask)
    
    def _resize_mask(self, mask, resize_mask_shape):
        s_h, s_w = resize_mask_shape
        return cv2.resize(mask, (s_w, s_h), interpolation=cv2.INTER_NEAREST)
    
    def _depth_edge_mask(self, mask, mask_bin, border_ratio):
        mask_size_x = mask.shape[0]  # h
        mask_size_y = mask.shape[1]  # w
        y_start = mask_size_y // border_ratio
        y_end = mask_size_y - mask_size_y // border_ratio
        center_mask = np.zeros_like(mask)
        center_mask[:, y_start:y_end] = True
        
        mask_road_conditions = [(mask == 13), (center_mask==False)]
        mask_road = np.logical_and.reduce(mask_road_conditions).astype(np.uint8)
        
        return cv2.bitwise_or(center_mask, mask_road)
    
    def get_seg_mask(self, seg_mask_input, resize_mask_shape, static_seg=None):
        if isinstance(seg_mask_input, str):
            mask_hr = cv2.imread(seg_mask_input, cv2.IMREAD_UNCHANGED).astype(cp.uint8)
        elif isinstance(seg_mask_input, np.ndarray):
            mask_hr = cp.asarray(seg_mask_input.astype(np.uint8))
        elif isinstance(seg_mask_input, cp.ndarray):
            mask_hr = seg_mask_input.astype(cp.uint8)
        else:
            raise ValueError(f"seg_mask_input must be str, np.ndarray, or cp.ndarray, got {type(seg_mask_input)}")
        
        mask_hr_np = cp.asnumpy(mask_hr) if isinstance(mask_hr, cp.ndarray) else mask_hr
        mask_raw = mask_hr_np.copy()
        
        static_seg_hr_np = None
        if static_seg is not None:
            if isinstance(static_seg, str):
                if static_seg.endswith('.npy'):
                    static_seg_hr = np.load(static_seg).astype(cp.uint8)
                else:
                    static_seg_hr = cv2.imread(static_seg, cv2.IMREAD_UNCHANGED).astype(cp.uint8)
            elif isinstance(static_seg, np.ndarray):
                static_seg_hr = cp.asarray(static_seg.astype(np.uint8))
            elif isinstance(static_seg, cp.ndarray):
                static_seg_hr = static_seg.astype(cp.uint8)
            else:
                raise ValueError(f"static_seg must be str, np.ndarray, or cp.ndarray, got {type(static_seg)}")
            static_seg_hr_np = cp.asnumpy(static_seg_hr) if isinstance(static_seg_hr, cp.ndarray) else static_seg_hr
        
        mask = self._create_mask(mask_hr_np, static_seg=static_seg_hr_np)
        mask = self._dilate_mask(mask)
        mask = self._resize_mask(mask, resize_mask_shape)
        
        if self.cross_consistence_flag:
            mask_raw = self._resize_mask(mask_raw, resize_mask_shape)
            mask &= self._depth_edge_mask(mask_raw, mask, self.crop_ratio)
        
        mask = mask.astype(bool)
        mask = cp.asarray(mask)
        return mask
    
    def _load_frame_data(self, frame_entry: Dict[str, Any], load_depth=True, load_camera=True, load_image=False, load_seg=False, load_static_seg=False, load_confidence=False) -> Dict[str, Any]:
        if frame_entry is None:
            return {}
        
        if self.use_disk_cache:
            frame_id = str(frame_entry.get('frame_id', ''))
            cam_id = str(frame_entry.get('cam_id', ''))
            filename_base = frame_entry.get('filename_base', None)
            
            if filename_base is None:
                filename_base = self._get_frame_filename(frame_id, cam_id, "")
            
            depth_pred = None
            if load_depth:
                depth_filename = os.path.join(self.frame_cache_dir, "depth", f"{filename_base}.pfm")
                depth_pred, _ = read_pfm(depth_filename)
                if HAS_CUPY and isinstance(depth_pred, cp.ndarray):
                    depth_pred = depth_pred.get()
                if depth_pred.ndim == 2:
                    depth_pred = depth_pred[np.newaxis, ...]
            
            K = None
            cam_T_world = None
            if load_camera:
                cam_filename = os.path.join(self.frame_cache_dir, "cams", f"{filename_base}_cam.txt")
                K, cam_T_world = _read_cam(cam_filename)
                if HAS_CUPY:
                    K = K.get() if isinstance(K, cp.ndarray) else K
                    cam_T_world = cam_T_world.get() if isinstance(cam_T_world, cp.ndarray) else cam_T_world
            
            color_image = None
            if load_image:
                img_filename = os.path.join(self.frame_cache_dir, "images", f"{filename_base}.png")
                color_image = cv2.imread(img_filename, cv2.IMREAD_COLOR)
                if color_image is not None:
                    color_image = cv2.cvtColor(color_image, cv2.COLOR_BGR2RGB)
                    if color_image.ndim != 3 or color_image.shape[2] != 3:
                        raise ValueError(f"Loaded color image has invalid shape: {color_image.shape}, expected (H, W, 3)")
                    color_image = color_image.astype(np.float32) / 255.0
                    if color_image.max() == 0.0:
                        print(f"[WARNING] Loaded color image appears to be all black: {img_filename}")
                else:
                    raise FileNotFoundError(f"Color image not found or could not be read: {img_filename}")
            
            seg = None
            if load_seg:
                seg_path = frame_entry.get('seg_path', None)
                if seg_path is not None and os.path.exists(seg_path):
                    seg = cv2.imread(seg_path, cv2.IMREAD_UNCHANGED).astype(np.uint8)
                    if seg is None:
                        raise FileNotFoundError(f"Segmentation image not found at path: {seg_path}")
                else:
                    seg_filename = os.path.join(self.frame_cache_dir, "seg", f"{filename_base}_seg.png")
                    seg = cv2.imread(seg_filename, cv2.IMREAD_UNCHANGED)
                    if seg is None:
                        raise FileNotFoundError(f"Segmentation image not found: {seg_filename}")
            
            static_seg = None
            if load_static_seg:
                static_seg_path = frame_entry.get('static_seg_path', None)
                if static_seg_path is not None and os.path.exists(static_seg_path):
                    if static_seg_path.endswith('.npy'):
                        static_seg = np.load(static_seg_path).astype(np.uint8)
                    else:
                        static_seg = cv2.imread(static_seg_path, cv2.IMREAD_UNCHANGED).astype(np.uint8)
                        if static_seg is None:
                            raise FileNotFoundError(f"Static segmentation image not found at path: {static_seg_path}")
                else:
                    static_seg_filename_npy = os.path.join(self.frame_cache_dir, "seg", f"{filename_base}_static_seg.npy")
                    static_seg_filename_png = os.path.join(self.frame_cache_dir, "seg", f"{filename_base}_static_seg.png")
                    if os.path.exists(static_seg_filename_npy):
                        static_seg = np.load(static_seg_filename_npy).astype(np.uint8)
                    elif os.path.exists(static_seg_filename_png):
                        static_seg = cv2.imread(static_seg_filename_png, cv2.IMREAD_UNCHANGED)
                        if static_seg is None:
                            print(f"[WARNING] Static segmentation image could not be read: {static_seg_filename_png}")
            
            confidence = None
            if load_confidence:
                conf_filename = os.path.join(self.frame_cache_dir, "confidence", f"{filename_base}.pfm")
                if os.path.exists(conf_filename):
                    confidence, _ = read_pfm(conf_filename)
                    if HAS_CUPY and isinstance(confidence, cp.ndarray):
                        confidence = confidence.get()
            
            frame_data = {
                'frame_id': frame_id,
                'cam_id': cam_id,
            }
            if depth_pred is not None:
                frame_data['depth_pred'] = depth_pred
            if K is not None:
                frame_data['K'] = K
            if cam_T_world is not None:
                frame_data['cam_T_world'] = cam_T_world
            if color_image is not None:
                frame_data['color_image'] = color_image
            if seg is not None:
                frame_data['seg'] = seg
            if static_seg is not None:
                frame_data['static_seg'] = static_seg
            if confidence is not None:
                frame_data['confidence'] = confidence
            
            return frame_data
        else:
            required_keys = []
            if load_depth:
                required_keys.append("depth_pred")
            if load_camera:
                required_keys.extend(["K", "cam_T_world"])
            if load_image:
                required_keys.append("color_image")
            if load_seg:
                required_keys.append("seg")
            if load_confidence:
                required_keys.append("confidence")
            
            if all(key in frame_entry and frame_entry.get(key) is not None for key in required_keys):
                result = {}
                for k in required_keys:
                    if k in frame_entry:
                        value = frame_entry[k]
                        if k == 'seg' and isinstance(value, str):
                            if os.path.exists(value):
                                seg_data = cv2.imread(value, cv2.IMREAD_UNCHANGED)
                                if seg_data is None:
                                    raise FileNotFoundError(f"Segmentation image not found at path: {value}")
                                result[k] = seg_data
                            else:
                                raise FileNotFoundError(f"Segmentation image path does not exist: {value}")
                        else:
                            result[k] = value
                if 'frame_id' in frame_entry:
                    result['frame_id'] = frame_entry['frame_id']
                if 'cam_id' in frame_entry:
                    result['cam_id'] = frame_entry['cam_id']
                return result
            else:
                raise ValueError(f"Missing required keys in frame_entry: {required_keys}")
    
    def _depth_to_points(self, depth, K, cam_T_world, color_image, mask, semantic_image=None):
        depth_cp = cp.asarray(depth)
        mask_cp = cp.asarray(mask)
        
        if K.shape[0] == 4:
            K_3x3 = cp.asarray(K[:3, :3])
        else:
            K_3x3 = cp.asarray(K)
        
        T_cp = cp.asarray(cam_T_world)
        
        height, width = depth.shape
        
        x, y = cp.meshgrid(cp.arange(0, width), cp.arange(0, height))
        
        x_valid = x[mask_cp]
        y_valid = y[mask_cp]
        depth_valid = depth_cp[mask_cp]
        
        if len(x_valid) == 0:
            return None
        
        xyz_cam = cp.matmul(
            cp.linalg.inv(K_3x3),
            cp.vstack((x_valid, y_valid, cp.ones_like(x_valid))) * depth_valid
        )
        
        xyz_world = cp.matmul(
            cp.linalg.inv(T_cp),
            cp.vstack((xyz_cam, cp.ones((1, xyz_cam.shape[1]))))
        )[:3]
        
        color_cp = cp.asarray(color_image)
        if color_cp.ndim == 3:
            if color_cp.shape[0] == 3:  # (3, H, W) -> (H, W, 3)
                color_cp = cp.transpose(color_cp, (1, 2, 0))
            elif color_cp.shape[2] == 1:  # (H, W, 1) -> (H, W, 3)
                color_cp = cp.stack([color_cp[:, :, 0]] * 3, axis=2)
        
        color_valid_cp = color_cp[mask_cp]  # (N, 3)
        
        xyz_world = to_numpy(xyz_world).T  # (N, 3)
        color_valid = to_numpy(color_valid_cp)  # (N, 3)
        
        semantic_valid = None
        if semantic_image is not None:
            semantic_cp = cp.asarray(semantic_image)
            if semantic_cp.ndim == 3:
                if semantic_cp.shape[0] == 1:
                    semantic_cp = semantic_cp[0]
                else:
                    semantic_cp = semantic_cp[:, :, 0]
            
            if semantic_cp.shape != depth.shape:
                print(f"[WARNING] semantic_image shape {semantic_cp.shape} does not match depth shape {depth.shape}, skipping semantic")
            else:
                semantic_valid_cp = semantic_cp[mask_cp]  # (N,)
                semantic_valid = to_numpy(semantic_valid_cp).astype(np.uint8)
        
        if self.save_debug_info:
            if semantic_valid is not None:
                dtypes = [
                    ('xyz', np.float32, 3),
                    ('color', np.uint8, 3),
                    ('semantic', np.uint8),
                    ('depth', np.float32)
                ]
            else:
                dtypes = [
                    ('xyz', np.float32, 3),
                    ('color', np.uint8, 3),
                    ('depth', np.float32)
                ]
            points_xyzrgbs = np.empty(xyz_world.shape[0], dtype=dtypes)
            points_xyzrgbs['xyz'] = xyz_world
            points_xyzrgbs['color'] = (color_valid * 255).astype(np.uint8)
            if semantic_valid is not None:
                points_xyzrgbs['semantic'] = semantic_valid
            points_xyzrgbs['depth'] = to_numpy(depth_valid)
        else:
            if semantic_valid is not None:
                dtypes = [
                    ('xyz', np.float32, 3),
                    ('color', np.uint8, 3),
                    ('semantic', np.uint8)
                ]
            else:
                dtypes = [
                    ('xyz', np.float32, 3),
                    ('color', np.uint8, 3)
                ]
            points_xyzrgbs = np.empty(xyz_world.shape[0], dtype=dtypes)
            points_xyzrgbs['xyz'] = xyz_world
            points_xyzrgbs['color'] = (color_valid * 255).astype(np.uint8)
            if semantic_valid is not None:
                points_xyzrgbs['semantic'] = semantic_valid
        
        return points_xyzrgbs
    
    def _build_frame_index(self):
        """
        frame_id + cam_id → view_info
        """
        view_id_to_info = {}  # (frame_id, cam_id) → view_info
        
        if self.use_disk_cache:
            if not hasattr(self, 'frame_metadata') or len(self.frame_metadata) == 0:
                self.frame_metadata = []
            
            for frame_meta in self.frame_metadata:
                frame_id = str(frame_meta['frame_id'])
                cam_id = str(frame_meta['cam_id'])
                cam_id_normalized = cam_id.replace('cam', '')
                view_id_to_info[(frame_id, cam_id_normalized)] = frame_meta
        else:
            for frame_info in self.frame_infos:
                frame_id = str(frame_info['frame_id'])
                cam_id = str(frame_info['cam_id'])
                
                cam_id_normalized = cam_id.replace('cam', '')
                
                view_id_to_info[(frame_id, cam_id_normalized)] = frame_info
        
        return view_id_to_info
    
    def _normalize_cam_id(self, cam_id):
        if cam_id is None:
            return None
        cam_id_str = str(cam_id)
        match = re.search(r'(\d+)', cam_id_str)
        if match:
            return match.group(1)
        return cam_id_str.replace('cam', '')
    
    def _parse_slice_from_path(self, img_path):
        if not img_path:
            return None, None
        path_norm = str(img_path).replace('\\', '/')
        parts = [p for p in path_norm.split('/') if p]
        cam_name = None
        slice_name = None
        for part in parts:
            if part.startswith('cam') and cam_name is None:
                cam_name = part
            if part.startswith('slice'):
                slice_name = part
        if cam_name is None or slice_name is None:
            return None, None
        match = re.search(r'(\d+)', slice_name)
        if not match:
            return None, None
        slice_index = int(match.group(1))
        cam_id_normalized = self._normalize_cam_id(cam_name)
        return cam_id_normalized, slice_index
    
    def _register_slice_view(self, frame_id, cam_id_normalized, slice_index):
        if frame_id is None or cam_id_normalized is None:
            return
        cam_key = str(cam_id_normalized)
        frame_id_str = str(frame_id)
        if cam_key not in self.slice_number_to_view:
            self.slice_number_to_view[cam_key] = {}
        if slice_index is not None:
            slice_int = int(slice_index)
            self.slice_number_to_view[cam_key][slice_int] = (frame_id_str, cam_key)
            self.view_to_slice[(frame_id_str, cam_key)] = slice_int
        else:
            raise ValueError(f"slice_index is None for frame_id: {frame_id}, cam_id: {cam_id_normalized}")
    
    def _lookup_view_by_slice(self, target_cam_id, slice_index, view_id_to_info):
        if slice_index is None:
            return None, None
        cam_key = str(target_cam_id).replace('cam', '')
        cam_map = self.slice_number_to_view.get(cam_key)
        if not cam_map:
            return None, None
        mapping = cam_map.get(int(slice_index))
        if not mapping:
            return None, None
        frame_id_str, cam_id_normalized = mapping
        src_key = (frame_id_str, cam_id_normalized)
        view_info = view_id_to_info.get(src_key)
        return src_key, view_info
    
    def _get_slice_index_for_view(self, frame_id, cam_id):
        cam_key = str(cam_id).replace('cam', '')
        return self.view_to_slice.get((str(frame_id), cam_key))
    
    def _frame_id_to_slice(self, frame_id, cam_id, default=None):
        slice_index = self._get_slice_index_for_view(frame_id, cam_id)
        if slice_index is not None:
            return slice_index
        try:
            return int(frame_id)
        except (TypeError, ValueError):
            return default
    
    def _load_metadata_src_views(self, metadata_dir):
        """
        load src_views from capture.json
        return: {(frame_id, cam_id): [(src_frame_id, src_cam_id), ...]}
        """
        import json
        metadata_file = os.path.join(metadata_dir, "capture.json")        
        with open(metadata_file, 'r') as f:
            metadata = json.load(f)
        
        src_views_map = {}
        self.slice_number_to_view = {}
        if "frames" in metadata:
            frames = metadata["frames"]
            if isinstance(frames, dict):
                for frame_key, frame_entry in frames.items():
                    frame_id = frame_entry.get('sequence')
                    cam_id = frame_entry.get('camera_id') or frame_entry.get('cam_id')
                    src_views_raw = frame_entry.get('src_views', [])
                    img_path = frame_entry.get('image')
                    
                    if frame_id is not None and cam_id is not None:
                        cam_id_normalized = self._normalize_cam_id(cam_id)
                        if img_path:
                            slice_cam_id, slice_index = self._parse_slice_from_path(img_path)
                            if slice_cam_id is None:
                                slice_cam_id = cam_id_normalized
                            self._register_slice_view(frame_id, slice_cam_id, slice_index)
                        else:
                            raise ValueError(f"img_path is None for frame_id: {frame_id}, cam_id: {cam_id}")
                        
                        src_views_list = []
                        for src_view in src_views_raw:
                            src_frame_id = src_view.get('frame_id')
                            src_cam_id = src_view.get('cam_id')
                            if src_frame_id is not None and src_cam_id is not None:
                                src_cam_id_normalized = self._normalize_cam_id(src_cam_id)
                                src_views_list.append((str(src_frame_id), src_cam_id_normalized))
                        
                        src_views_map[(str(frame_id), cam_id_normalized)] = src_views_list
            else:
                for frame_entry in frames:
                    frame_id = frame_entry.get('sequence')
                    cam_id = frame_entry.get('camera_id') or frame_entry.get('cam_id')
                    src_views_raw = frame_entry.get('src_views', [])
                    img_path = frame_entry.get('image')
                    
                    if frame_id is not None and cam_id is not None:
                        cam_id_normalized = self._normalize_cam_id(cam_id)
                        if img_path:
                            slice_cam_id, slice_index = self._parse_slice_from_path(img_path)
                            if slice_cam_id is None:
                                slice_cam_id = cam_id_normalized
                            self._register_slice_view(frame_id, slice_cam_id, slice_index)
                        else:
                            raise ValueError(f"img_path is None for frame_id: {frame_id}, cam_id: {cam_id}")
                        
                        src_views_list = []
                        for src_view in src_views_raw:
                            src_frame_id = src_view.get('frame_id')
                            src_cam_id = src_view.get('cam_id')
                            if src_frame_id is not None and src_cam_id is not None:
                                src_cam_id_normalized = self._normalize_cam_id(src_cam_id)
                                src_views_list.append((str(src_frame_id), src_cam_id_normalized))
                        
                        src_views_map[(str(frame_id), cam_id_normalized)] = src_views_list
        
        return src_views_map
    
    def _select_source_views_cross_camera(self, ref_frame_id, ref_cam_id, view_id_to_info, 
                                         metadata_src_views, enable_cross_camera=True, fewer_src_views=False):
        src_views = []
        seen_views = set()
        metadata_entries = []

        try:
            ref_frame_id_int = int(ref_frame_id)
        except (TypeError, ValueError):
            ref_frame_id_int = None
        
        if metadata_src_views:
            metadata_seen = set()
            for src_view_id in metadata_src_views:
                # src_view_id (frame_id, cam_id) 
                if isinstance(src_view_id, (list, tuple)) and len(src_view_id) >= 2:
                    src_key = (str(src_view_id[0]), str(src_view_id[1]))
                elif isinstance(src_view_id, str):
                    continue
                else:
                    src_key = (str(src_view_id[0]), str(src_view_id[1]))
                
                if src_key in view_id_to_info and src_key not in metadata_seen:
                    view_info = view_id_to_info[src_key]
                    metadata_entries.append({
                        "src_key": src_key,
                        "view_info": view_info,
                    })
                    metadata_seen.add(src_key)
        # meta_src_views_count = len(metadata_entries)
        # print(f"original src_views count: {meta_src_views_count}")
        
        if fewer_src_views and ref_frame_id_int is not None and metadata_entries:
            target_offsets = [-1, -3, 1, 3]
            frame_to_entries = {}
            for entry in metadata_entries:
                frame_id_raw = entry["view_info"].get('frame_id')
                try:
                    frame_int = int(frame_id_raw)
                except (TypeError, ValueError):
                    continue
                frame_to_entries.setdefault(frame_int, []).append(entry)
            filtered_entries = []
            for offset in target_offsets:
                target_frame = ref_frame_id_int + offset
                candidates = frame_to_entries.get(target_frame)
                if not candidates:
                    continue
                candidate = candidates[0]
                if candidate not in filtered_entries:
                    filtered_entries.append(candidate)
            if filtered_entries:
                metadata_entries = filtered_entries
            # print(f"filtered src_views count: {len(metadata_entries)}")
        
        src_views = []
        seen_views = set()
        for entry in metadata_entries:
            view_info = entry["view_info"]
            src_key = entry["src_key"]
            src_views.append(view_info)
            seen_views.add(src_key)

        if enable_cross_camera:
            cam_name = f"cam{ref_cam_id}" if not str(ref_cam_id).startswith('cam') else str(ref_cam_id)
            ref_cam_key = cam_name.replace('cam', '')
            
            try:
                ref_frame_id_int = int(ref_frame_id)
            except (TypeError, ValueError):
                ref_frame_id_int = None
            ref_slice_index = self._frame_id_to_slice(ref_frame_id, ref_cam_key, default=ref_frame_id_int)
            
            last_frame_index, next_frame_index = self.get_visiable_slice(
                view_id_to_info=view_id_to_info,
                ref_frame_id=ref_frame_id_int,
                ref_cam_id=ref_cam_id,
                dist_thres=self.cross_dist_thres,
            )
            last_slice_index = self._frame_id_to_slice(last_frame_index, ref_cam_key, default=last_frame_index)
            next_slice_index = self._frame_id_to_slice(next_frame_index, ref_cam_key, default=next_frame_index)
            
            if cam_name == "cam2":
                # cam2 → cam3 and cam4
                start_slice = (ref_slice_index + 2) if ref_slice_index is not None else (ref_frame_id_int + 2)
                end_slice = next_slice_index if next_slice_index is not None else (ref_frame_id_int + 2)
                if start_slice is None or end_slice is None:
                    start_slice = 0
                    end_slice = 0
                # print(f"cam2 → cam3 and cam4: slice {start_slice} to {end_slice}")
                for tmp_id in range(start_slice, end_slice):
                    src_key_5, view_info_5 = self._lookup_view_by_slice("3", tmp_id, view_id_to_info)
                    if view_info_5 is None:
                        src_key_5 = (str(tmp_id), "3")
                        view_info_5 = view_id_to_info.get(src_key_5)
                    if view_info_5 is not None and src_key_5 not in seen_views:
                        src_views.append(view_info_5)
                        seen_views.add(src_key_5)
                    src_key_6, view_info_6 = self._lookup_view_by_slice("4", tmp_id, view_id_to_info)
                    if view_info_6 is None:
                        src_key_6 = (str(tmp_id), "4")
                        view_info_6 = view_id_to_info.get(src_key_6)
                    if view_info_6 is not None and src_key_6 not in seen_views:
                        src_views.append(view_info_6)
                        seen_views.add(src_key_6)
            elif cam_name == "cam0":
                # cam0 → cam2
                start_slice = last_slice_index if last_slice_index is not None else ref_frame_id_int
                end_slice = next_slice_index if next_slice_index is not None else ref_frame_id_int
                if start_slice is None or end_slice is None:
                    start_slice = 0
                    end_slice = 0
                # print(f"cam0 → cam2: slice {start_slice} to {end_slice}")
                for tmp_id in range(start_slice, end_slice):
                    src_key_2, view_info_2 = self._lookup_view_by_slice("2", tmp_id, view_id_to_info)
                    if view_info_2 is None:
                        src_key_2 = (str(tmp_id), "2")
                        view_info_2 = view_id_to_info.get(src_key_2)
                    if view_info_2 is not None and src_key_2 not in seen_views:
                        src_views.append(view_info_2)
                        seen_views.add(src_key_2)
            else:
                # cam3/cam4 → cam5/cam6
                if cam_name == "cam3" or cam_name == "cam4":
                    ref_cam_name = "5" if cam_name == "cam3" else "6"
                    start_slice = ref_slice_index if ref_slice_index is not None else ref_frame_id_int
                    end_slice = next_slice_index if next_slice_index is not None else start_slice
                    if start_slice is None or end_slice is None:
                        start_slice = 0
                        end_slice = 0
                    # print(f"cam3/cam4 → cam5/cam6: slice {start_slice} to {end_slice}")
                    for tmp_id in range(start_slice, end_slice):
                        src_key, view_info = self._lookup_view_by_slice(ref_cam_name, tmp_id, view_id_to_info)
                        if view_info is None:
                            src_key = (str(tmp_id), ref_cam_name)
                            view_info = view_id_to_info.get(src_key)
                        if view_info is not None and src_key not in seen_views:
                            src_views.append(view_info)
                            seen_views.add(src_key)
                
                # cam5/cam6 → cam3/cam4
                if cam_name == "cam5" or cam_name == "cam6":
                    ref_cam_name = "3" if cam_name == "cam5" else "4"
                    start_slice = last_slice_index if last_slice_index is not None else ref_frame_id_int
                    end_slice = ref_slice_index if ref_slice_index is not None else ref_frame_id_int
                    if start_slice is None or end_slice is None:
                        start_slice = 0
                        end_slice = 0
                    # print(f"cam5/cam6 → cam3/cam4: slice {start_slice} to {end_slice}")
                    for tmp_id in range(start_slice, end_slice):
                        src_key, view_info = self._lookup_view_by_slice(ref_cam_name, tmp_id, view_id_to_info)
                        if view_info is None:
                            src_key = (str(tmp_id), ref_cam_name)
                            view_info = view_id_to_info.get(src_key)
                        if view_info is not None and src_key not in seen_views:
                            src_views.append(view_info)
                            seen_views.add(src_key)
        # print(f"cross_camera src_views count: {(len(src_views) - meta_src_views_count)}")
        
        return src_views
    
    def _prepare_color_image(self, color):
        if color is None:
            return None
        if HAS_CUPY and isinstance(color, cp.ndarray):
            color_np = color.get()
        else:
            color_np = np.asarray(color)
        if color_np.ndim == 3 and color_np.shape[0] == 3 and color_np.shape[2] != 3:
            color_np = np.transpose(color_np, (1, 2, 0))
        elif color_np.ndim == 3 and color_np.shape[-1] != 3 and color_np.shape[1] == 3:
            color_np = np.transpose(color_np, (0, 2, 1))
        if color_np.ndim != 3 or color_np.shape[2] != 3:
            return None
        if color_np.min() < 0 or color_np.max() > 1:
            color_tensor = torch.from_numpy(color_np.transpose(2, 0, 1))
            color_tensor = reverse_imagenet_normalize(color_tensor)
            color_np = color_tensor.numpy().transpose(1, 2, 0)
        color_np = np.clip(color_np, 0, 1)
        return color_np
    
    def _process_single_view_postprocess(
        self,
        idx,
        ref_view,
        src_views_map,
        view_id_to_info,
        enable_geometric_consistency,
    ):
        ref_view_data = self._load_frame_data(ref_view, load_image=True, load_seg=True, load_static_seg=True)
        ref_frame_id = ref_view_data['frame_id']
        ref_cam_id = ref_view_data['cam_id']
        
        ref_depth = ref_view_data['depth_pred']
        if ref_depth.ndim == 3:
            ref_depth = ref_depth[0]
        
        ref_K = ref_view_data['K']
        ref_T = ref_view_data['cam_T_world']
        
        ref_color_data = ref_view_data['color_image']
        ref_color = ref_color_data
        if ref_color.dtype == np.uint8:
            ref_color = ref_color.astype(np.float32) / 255.0
        elif ref_color.dtype == np.float64:
            ref_color = ref_color.astype(np.float32)
        
        if ref_color.ndim == 3 and ref_color.shape[0] == 3:
            ref_color = ref_color.transpose(1, 2, 0)
        
        if ref_color.min() < 0 or ref_color.max() > 1:
            color_tensor = torch.from_numpy(ref_color.transpose(2, 0, 1))
            color_tensor = reverse_imagenet_normalize(color_tensor)
            ref_color = color_tensor.numpy().transpose(1, 2, 0)
        
        ref_color = np.clip(ref_color, 0, 1)
        
        ref_seg_data = ref_view_data.get('seg', None)
        if ref_seg_data is not None:
            ref_seg = ref_seg_data
            if ref_seg.ndim == 3:
                if ref_seg.shape[0] == 1:
                    ref_seg = ref_seg[0]
                else:
                    ref_seg = ref_seg[:, :, 0]
            
            if ref_seg.shape != ref_depth.shape:
                ref_seg = None
        else:
            ref_seg = None
        
        ref_seg_static_data = ref_view_data.get('static_seg', None)
        if ref_seg_static_data is not None:
            ref_seg_static = ref_seg_static_data
            if ref_seg_static.ndim == 3:
                if ref_seg_static.shape[0] == 1:
                    ref_seg_static = ref_seg_static[0]
                else:
                    ref_seg_static = ref_seg_static[:, :, 0]
            
            if ref_seg_static.shape != ref_depth.shape:
                ref_seg_static = None
        else:
            ref_seg_static = None
        
        ref_cam_id_normalized = str(ref_cam_id).replace('cam', '')
        
        confidence_mask = None
        depth_mask = self.get_depth_mask(ref_depth, ref_cam_id)
        
        metadata_src_views = src_views_map.get((str(ref_frame_id), ref_cam_id_normalized), [])
        
        src_views = self._select_source_views_cross_camera(
            ref_frame_id=ref_frame_id,
            ref_cam_id=ref_cam_id_normalized,
            view_id_to_info=view_id_to_info,
            metadata_src_views=metadata_src_views,
            enable_cross_camera=self.enable_cross_camera,
            fewer_src_views=False,
        )
        
        if len(src_views) == 0:
            print(f"skip frame_{ref_frame_id}_cam_{ref_cam_id}: no source views")
            return None
        
        final_mask = cp.ones_like(cp.asarray(ref_depth), dtype=cp.bool_)
        average_depth = ref_depth
        
        if enable_geometric_consistency:
            src_depths = []
            src_Ks = []
            src_Ts = []
            src_cam_ids_list = []

            src_frame_ids_list = []
            
            for src_view in src_views:
                src_view_data = self._load_frame_data(src_view, load_image=False, load_seg=False, load_confidence=False)
                src_depth = src_view_data['depth_pred']
                if src_depth.ndim == 3:
                    src_depth = src_depth[0]
                src_depths.append(src_depth)
                src_Ks.append(src_view_data['K'])
                src_Ts.append(src_view_data['cam_T_world'])
                src_cam_id_str = str(src_view_data['cam_id']).replace('cam', '')
                try:
                    src_cam_id_int = int(src_cam_id_str)
                except Exception:
                    src_cam_id_int = 0
                src_cam_ids_list.append(src_cam_id_int)
                src_frame_ids_list.append(src_view_data.get('frame_id'))
                del src_view_data
            
            try:
                geometric_mask, average_depth = self.get_geometric_mask_and_average_depth_cross(
                    ref_depth=ref_depth,
                    ref_intrinsics=ref_K,
                    ref_extrinsics=ref_T,
                    src_depths=src_depths,
                    src_intrinsics_list=src_Ks,
                    src_extrinsics_list=src_Ts,
                    ref_frame_id=ref_frame_id,
                    src_frame_ids=src_frame_ids_list,
                )
            except Exception as exc:
                if idx % 10 == 0:
                    print(f"geometric consistency check failed: {exc}")
                    import traceback
                    traceback.print_exc()
                geometric_mask = cp.zeros_like(cp.asarray(ref_depth), dtype=cp.bool_)
                average_depth = cp.asarray(ref_depth, dtype=cp.float32)
            
            final_mask = geometric_mask
            if confidence_mask is not None:
                final_mask = cp.logical_and(final_mask, confidence_mask)
            if depth_mask is not None:
                final_mask = cp.logical_and(final_mask, depth_mask)
            if ref_seg is not None:
                seg_mask = self.get_seg_mask(ref_seg, final_mask.shape, static_seg=ref_seg_static)
                final_mask = cp.logical_and(final_mask, seg_mask)
        
        final_depth = average_depth if enable_geometric_consistency else ref_depth
        
        points_xyzrgbs = self._depth_to_points(
            depth=final_depth,
            K=ref_K,
            cam_T_world=ref_T,
            color_image=ref_color,
            mask=final_mask,
            semantic_image=ref_seg
        )
        
        del ref_depth, ref_K, ref_T, ref_color, ref_seg
        if enable_geometric_consistency:
            del src_depths, src_Ks, src_Ts, src_cam_ids_list, src_frame_ids_list
            del geometric_mask, average_depth, final_mask
        
        if points_xyzrgbs is not None and len(points_xyzrgbs) > 0:
            print(f"generate {len(points_xyzrgbs)} points")
        
        return (ref_cam_id, points_xyzrgbs)
    
    def _postprocess_geometric_consistency(self, metadata_dir, enable_geometric_consistency):
        if self.use_disk_cache:
            if not hasattr(self, 'frame_metadata') or len(self.frame_metadata) == 0:
                self.frame_metadata = []
            
            if self.allowed_cam_ids is not None:
                filtered_frame_metadata = []
                for frame_meta in self.frame_metadata:
                    cam_id = frame_meta.get('cam_id')
                    cam_id_normalized = self._normalize_cam_id(cam_id)
                    if cam_id_normalized in self.allowed_cam_ids:
                        filtered_frame_metadata.append(frame_meta)
                if len(filtered_frame_metadata) != len(self.frame_metadata):
                    print(f"Filtered frame_metadata: {len(self.frame_metadata)} -> {len(filtered_frame_metadata)} (allowed_cam_ids={self.allowed_cam_ids})")
                self.frame_metadata = filtered_frame_metadata
            
            frame_list = self.frame_metadata
        else:
            if self.allowed_cam_ids is not None:
                filtered_frame_infos = []
                for frame_info in self.frame_infos:
                    cam_id = frame_info.get('cam_id')
                    cam_id_normalized = self._normalize_cam_id(cam_id)
                    if cam_id_normalized in self.allowed_cam_ids:
                        filtered_frame_infos.append(frame_info)
                if len(filtered_frame_infos) != len(self.frame_infos):
                    print(f"Filtered frame_infos: {len(self.frame_infos)} -> {len(filtered_frame_infos)} (allowed_cam_ids={self.allowed_cam_ids})")
                self.frame_infos = filtered_frame_infos
            
            frame_list = self.frame_infos
        
        view_id_to_info = self._build_frame_index()
        
        src_views_map = self._load_metadata_src_views(metadata_dir)
        
        total_views = len(frame_list)
        index_view_pairs = [(idx, ref_view) for idx, ref_view in enumerate(frame_list)]
        
        if total_views == 0:
            print("\ngeometric consistency completed: 0 frames of points")
            return
        
        if self.postprocess_num_workers <= 1 or total_views == 1:
            results = []
            for idx, (pair_idx, ref_view) in enumerate(index_view_pairs, start=1):
                result = self._process_single_view_postprocess(
                    pair_idx,
                    ref_view,
                    src_views_map,
                    view_id_to_info,
                    enable_geometric_consistency,
                )
                results.append(result)
        else:
            def _task(pair):
                idx, ref_view = pair
                return self._process_single_view_postprocess(
                    idx,
                    ref_view,
                    src_views_map,
                    view_id_to_info,
                    enable_geometric_consistency,
                )
            
            results = []
            with ThreadPoolExecutor(max_workers=self.postprocess_num_workers) as executor:
                for result in executor.map(_task, index_view_pairs):
                    results.append(result)
        
        for result in results:
            if result is None:
                continue
            
            if isinstance(result, tuple) and len(result) == 2:
                cam_id, points_xyzrgbs = result
            else:
                cam_id = None
                points_xyzrgbs = result
            
            if points_xyzrgbs is not None and len(points_xyzrgbs) > 0:
                if cam_id is not None:
                    cam_id_str = str(cam_id)
                    if not cam_id_str.startswith('cam'):
                        cam_id_str = f'cam{cam_id_str}'
                    
                    if cam_id_str not in self.cam_to_points_xyzrgbs:
                        self.cam_to_points_xyzrgbs[cam_id_str] = []
                    
                    self.cam_to_points_xyzrgbs[cam_id_str].append(points_xyzrgbs)
                else:
                    self.all_points_xyzrgbs.append(points_xyzrgbs)
        
        del results
        del index_view_pairs
        
        total_cam_frames = sum(len(points_list) for points_list in self.cam_to_points_xyzrgbs.values())
        print(f"\ngeometric consistency completed: {total_cam_frames} frames of points (grouped by {len(self.cam_to_points_xyzrgbs)} cameras)")
    
    def export_point_cloud(
        self,
        output_path,
        apply_statistical_filter=True,
        apply_cluster_filter=True,
        voxel_size=0.05,
        stat_nb_neighbors=20,
        stat_std_ratio=2.0,
        cluster_eps=0.02,
        cluster_min_points=10,
        dbscan_voxel_size=0.1,
        metadata_dir=None,
        trajectory_points=None,
        enable_adaptive_filter=True,
        near_distance_threshold=5.0,
        far_distance_threshold=10.0,
    ):
        """
        Args:
            output_path
            apply_statistical_filter
            apply_cluster_filter
            voxel_size: voxel size (m)
            stat_nb_neighbors: number of neighbors for statistical filter
            stat_std_ratio: standard deviation ratio for statistical filter
            cluster_eps: distance threshold for cluster
            cluster_min_points: minimum number of points for cluster
            metadata_dir: metadata directory
            trajectory_points: (N, 3) numpy array, trajectory points
            enable_adaptive_filter: whether to enable adaptive filter based on trajectory distance
            near_distance_threshold
            far_distance_threshold
        """
        print(f"Start exporting point cloud to {output_path}...", flush=True)
        export_start = time.perf_counter()

        self._postprocess_geometric_consistency(metadata_dir, self.enable_geometric_consistency)
        postprocess_elapsed = time.perf_counter() - export_start
        print(f"geometric consistency stage time: {postprocess_elapsed:.2f}s", flush=True)
        
        has_cam_grouped = len(self.cam_to_points_xyzrgbs) > 0
        has_ungrouped = len(self.all_points_xyzrgbs) > 0
        
        if not has_cam_grouped and not has_ungrouped:
            print("no points to fuse and export")
            return
        
        if trajectory_points is None and enable_adaptive_filter:
            trajectory_points = self._extract_trajectory_from_frames()
            if trajectory_points is not None and len(trajectory_points) > 0:
                print(f"extract {len(trajectory_points)} trajectory points for adaptive filter", flush=True)
            else:
                print("extract trajectory points failed, use fixed filter parameters", flush=True)
                enable_adaptive_filter = False
        
        del self.frame_infos
        
        cam_pcds = {}
        if has_cam_grouped:
            if self.allowed_cam_ids is not None:
                filtered_cam_to_points = {}
                for cam_name, points_xyzrgbs_list in self.cam_to_points_xyzrgbs.items():
                    cam_id_normalized = self._normalize_cam_id(cam_name)
                    if cam_id_normalized in self.allowed_cam_ids:
                        filtered_cam_to_points[cam_name] = points_xyzrgbs_list
                if len(filtered_cam_to_points) != len(self.cam_to_points_xyzrgbs):
                    print(f"Filtered cam_to_points_xyzrgbs: {len(self.cam_to_points_xyzrgbs)} -> {len(filtered_cam_to_points)} cameras (allowed_cam_ids={self.allowed_cam_ids})")
                self.cam_to_points_xyzrgbs = filtered_cam_to_points
            
            print(f"Converting point clouds for {len(self.cam_to_points_xyzrgbs)} cameras...")
            for cam_name, points_xyzrgbs_list in self.cam_to_points_xyzrgbs.items():
                if len(points_xyzrgbs_list) == 0:
                    continue
                
                batch_size = max(100, len(points_xyzrgbs_list) // 10)
                cam_points_list = []
                for i in range(0, len(points_xyzrgbs_list), batch_size):
                    batch = points_xyzrgbs_list[i:i+batch_size]
                    batch_points = np.concatenate(batch, axis=0)
                    cam_points_list.append(batch_points)
                    del batch
                
                cam_points = np.concatenate(cam_points_list, axis=0)
                del cam_points_list
                
                cam_pcd = o3d.t.geometry.PointCloud()
                cam_pcd.point.positions = o3d.core.Tensor(cam_points["xyz"].astype(np.float32))
                cam_pcd.point.colors = o3d.core.Tensor(cam_points["color"])
                cam_pcd.point.semantic = o3d.core.Tensor(cam_points["semantic"][..., None])
                
                if self.save_debug_info and "depth" in cam_points.dtype.names:
                    cam_pcd.point.depth = o3d.core.Tensor(cam_points["depth"][..., None].astype(np.float32))
                
                cam_pcds[cam_name] = cam_pcd
                print(f"Converted {cam_name}: {len(cam_points)} points")
                del cam_points
            
            if self.save_each_cam_ply:
                output_dir = os.path.dirname(output_path)
                if output_dir:
                    os.makedirs(output_dir, exist_ok=True)
                for cam_name, cam_pcd in cam_pcds.items():
                    cam_ply_path = os.path.join(output_dir, f'{cam_name}.ply')
                    o3d.t.io.write_point_cloud(cam_ply_path, cam_pcd)
                    print(f"Saved {cam_name} point cloud to {cam_ply_path}")
            
            del self.cam_to_points_xyzrgbs
        
        if has_ungrouped:
            print(f"Merging {len(self.all_points_xyzrgbs)} ungrouped frames of points")
            batch_size = max(100, len(self.all_points_xyzrgbs) // 10)
            all_points_list = []
            for i in range(0, len(self.all_points_xyzrgbs), batch_size):
                batch = self.all_points_xyzrgbs[i:i+batch_size]
                batch_points = np.concatenate(batch, axis=0)
                all_points_list.append(batch_points)
                del batch
            
            all_points = np.concatenate(all_points_list, axis=0)
            del all_points_list
            
            ungrouped_pcd = o3d.t.geometry.PointCloud()
            ungrouped_pcd.point.positions = o3d.core.Tensor(all_points["xyz"].astype(np.float32))
            ungrouped_pcd.point.colors = o3d.core.Tensor(all_points["color"])
            ungrouped_pcd.point.semantic = o3d.core.Tensor(all_points["semantic"][..., None])
            
            if self.save_debug_info and "depth" in all_points.dtype.names:
                ungrouped_pcd.point.depth = o3d.core.Tensor(all_points["depth"][..., None].astype(np.float32))
            
            cam_pcds["ungrouped"] = ungrouped_pcd
            del all_points
        
        cam_priority_order = ['cam2', 'cam3', 'cam4', 'cam5', 'cam6', 'cam7']
        final_pcd = None
        
        for cam_name in cam_priority_order:
            if cam_name in cam_pcds:
                cam_pcd = cam_pcds[cam_name]
                if final_pcd is None:
                    final_pcd = cam_pcd
                else:
                    final_pcd += cam_pcd
                print(f"Added {cam_name} point cloud to final pcd ({len(cam_pcd.point.positions)} points)")
        del cam_pcds
        
        if final_pcd is None:
            print("no points to fuse and export after merging")
            return
        
        pcd = final_pcd
        print(f"total points after merging: {len(pcd.point.positions)}")
        
        filter_args = SimpleNamespace(
            voxel_size=voxel_size,
            sor_neighbours=stat_nb_neighbors,
            sor_std=stat_std_ratio,
            dbscan_voxel_size=dbscan_voxel_size,
            dbscan_radius=cluster_eps,
            cluster_core_min_point=cluster_min_points,
            enable_adaptive_filter=enable_adaptive_filter,
            near_distance_threshold=near_distance_threshold,
            far_distance_threshold=far_distance_threshold,
        )
        
        if apply_statistical_filter:
            print("apply statistical filter...", flush=True)
            filter_start = time.perf_counter()
            
            if enable_adaptive_filter and trajectory_points is not None and voxel_size > 0:
                STATISTIC_FILTER_WORKSPACE.set_trajectory(trajectory_points)
                
                points_np = pcd.point.positions.numpy()
                distances = STATISTIC_FILTER_WORKSPACE._compute_distance_to_trajectory(points_np)
                
                interval1_threshold = near_distance_threshold
                interval2_threshold = near_distance_threshold + (far_distance_threshold - near_distance_threshold) * 0.25
                interval3_threshold = near_distance_threshold + (far_distance_threshold - near_distance_threshold) * 0.5
                interval4_threshold = near_distance_threshold + (far_distance_threshold - near_distance_threshold) * 0.75
                interval5_threshold = far_distance_threshold
                
                voxel_size_interval1 = voxel_size * 0.7
                voxel_size_interval2 = voxel_size * 1.0
                voxel_size_interval3 = voxel_size * 1.25
                voxel_size_interval4 = voxel_size * 1.5
                voxel_size_interval5 = voxel_size * 1.75
                voxel_size_interval6 = voxel_size * 2.0
                
                mask_interval1 = distances < interval1_threshold
                mask_interval2 = (distances >= interval1_threshold) & (distances < interval2_threshold)
                mask_interval3 = (distances >= interval2_threshold) & (distances < interval3_threshold)
                mask_interval4 = (distances >= interval3_threshold) & (distances < interval4_threshold)
                mask_interval5 = (distances >= interval4_threshold) & (distances < interval5_threshold)
                mask_interval6 = distances >= interval5_threshold
                
                downsampled_chunks = []
                
                # 1: < near_distance_threshold
                if np.any(mask_interval1):
                    indices_interval1 = np.where(mask_interval1)[0]
                    pcd_interval1 = pcd.select_by_index(o3d.core.Tensor(indices_interval1, dtype=o3d.core.Dtype.Int64))
                    if len(pcd_interval1.point.positions) > 0:
                        points_interval1 = pcd_interval1.point.positions.numpy().astype(np.float64)
                        mask_interval1_downsample = random_down_sample_cuda(points_interval1, voxel_size=voxel_size_interval1)
                        pcd_interval1 = pcd_interval1.select_by_mask(mask_interval1_downsample)
                        
                        if len(pcd_interval1.point.positions) > 0:
                            print(f"interval1 (distance < {interval1_threshold:.2f}m, voxel_size={voxel_size_interval1:.4f}): {len(pcd_interval1.point.positions)} points")
                            downsampled_chunks.append(pcd_interval1)
                
                # 2: near ~ near + 0.25*(far-near)
                if np.any(mask_interval2):
                    indices_interval2 = np.where(mask_interval2)[0]
                    pcd_interval2 = pcd.select_by_index(o3d.core.Tensor(indices_interval2, dtype=o3d.core.Dtype.Int64))
                    if len(pcd_interval2.point.positions) > 0:
                        points_interval2 = pcd_interval2.point.positions.numpy().astype(np.float64)
                        mask_interval2_downsample = random_down_sample_cuda(points_interval2, voxel_size=voxel_size_interval2)
                        pcd_interval2 = pcd_interval2.select_by_mask(mask_interval2_downsample)
                        
                        if len(pcd_interval2.point.positions) > 0:
                            print(f"interval2 (distance {interval1_threshold:.2f}~{interval2_threshold:.2f}m, voxel_size={voxel_size_interval2:.4f}): {len(pcd_interval2.point.positions)} points")
                            downsampled_chunks.append(pcd_interval2)
                
                # 3: near + 0.25*(far-near) ~ near + 0.5*(far-near)
                if np.any(mask_interval3):
                    indices_interval3 = np.where(mask_interval3)[0]
                    pcd_interval3 = pcd.select_by_index(o3d.core.Tensor(indices_interval3, dtype=o3d.core.Dtype.Int64))
                    if len(pcd_interval3.point.positions) > 0:
                        points_interval3 = pcd_interval3.point.positions.numpy().astype(np.float64)
                        mask_interval3_downsample = random_down_sample_cuda(points_interval3, voxel_size=voxel_size_interval3)
                        pcd_interval3 = pcd_interval3.select_by_mask(mask_interval3_downsample)
                        
                        if len(pcd_interval3.point.positions) > 0:
                            print(f"interval3 (distance {interval2_threshold:.2f}~{interval3_threshold:.2f}m, voxel_size={voxel_size_interval3:.4f}): {len(pcd_interval3.point.positions)} points")
                            downsampled_chunks.append(pcd_interval3)
                
                # 4: near + 0.5*(far-near) ~ near + 0.75*(far-near)
                if np.any(mask_interval4):
                    indices_interval4 = np.where(mask_interval4)[0]
                    pcd_interval4 = pcd.select_by_index(o3d.core.Tensor(indices_interval4, dtype=o3d.core.Dtype.Int64))
                    if len(pcd_interval4.point.positions) > 0:
                        points_interval4 = pcd_interval4.point.positions.numpy().astype(np.float64)
                        mask_interval4_downsample = random_down_sample_cuda(points_interval4, voxel_size=voxel_size_interval4)
                        pcd_interval4 = pcd_interval4.select_by_mask(mask_interval4_downsample)
                        
                        if len(pcd_interval4.point.positions) > 0:
                            print(f"interval4 (distance {interval3_threshold:.2f}~{interval4_threshold:.2f}m, voxel_size={voxel_size_interval4:.4f}): {len(pcd_interval4.point.positions)} points")
                            downsampled_chunks.append(pcd_interval4)
                
                # 5: near + 0.75*(far-near) ~ far_distance_threshold
                if np.any(mask_interval5):
                    indices_interval5 = np.where(mask_interval5)[0]
                    pcd_interval5 = pcd.select_by_index(o3d.core.Tensor(indices_interval5, dtype=o3d.core.Dtype.Int64))
                    if len(pcd_interval5.point.positions) > 0:
                        points_interval5 = pcd_interval5.point.positions.numpy().astype(np.float64)
                        mask_interval5_downsample = random_down_sample_cuda(points_interval5, voxel_size=voxel_size_interval5)
                        pcd_interval5 = pcd_interval5.select_by_mask(mask_interval5_downsample)
                        
                        if len(pcd_interval5.point.positions) > 0:
                            print(f"interval5 (distance {interval4_threshold:.2f}~{interval5_threshold:.2f}m, voxel_size={voxel_size_interval5:.4f}): {len(pcd_interval5.point.positions)} points")
                            downsampled_chunks.append(pcd_interval5)
                
                # 6: >= far_distance_threshold
                if np.any(mask_interval6):
                    indices_interval6 = np.where(mask_interval6)[0]
                    pcd_interval6 = pcd.select_by_index(o3d.core.Tensor(indices_interval6, dtype=o3d.core.Dtype.Int64))
                    if len(pcd_interval6.point.positions) > 0:
                        points_interval6 = pcd_interval6.point.positions.numpy().astype(np.float64)
                        mask_interval6_downsample = random_down_sample_cuda(points_interval6, voxel_size=voxel_size_interval6)
                        pcd_interval6 = pcd_interval6.select_by_mask(mask_interval6_downsample)
                        
                        if len(pcd_interval6.point.positions) > 0:
                            print(f"interval6 (distance >= {interval5_threshold:.2f}m, voxel_size={voxel_size_interval6:.4f}): {len(pcd_interval6.point.positions)} points")
                            downsampled_chunks.append(pcd_interval6)
                
                if len(downsampled_chunks) == 0:
                    print("[WARNING] no points after adaptive voxel downsampling", flush=True)
                elif len(downsampled_chunks) == 1:
                    pcd = downsampled_chunks[0]
                else:
                    pcd = downsampled_chunks[0]
                    for chunk in downsampled_chunks[1:]:
                        pcd += chunk
                
                print(f"after adaptive voxel downsampling: {len(pcd.point.positions)} points")
                filter_args.voxel_size = 0
            
            pcd = statistic_filter(filter_args, pcd, trajectory_points=trajectory_points)

            print(f"after statistical filter: {len(pcd.point.positions)} points", flush=True)
            print(f"statistical filter time: {time.perf_counter() - filter_start:.2f}s", flush=True)
        
        if apply_cluster_filter:
            print("apply cluster filter...", flush=True)
            cluster_start = time.perf_counter()
            pcd = cluster_filter(filter_args, pcd)
            print(f"after cluster filter: {len(pcd.point.positions)} points", flush=True)
            print(f"cluster filter time: {time.perf_counter() - cluster_start:.2f}s", flush=True)
        
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        
        print(f"save point cloud to: {output_path}", flush=True)
        o3d.t.io.write_point_cloud(output_path, pcd)
        print(f"point cloud exported: {len(pcd.point.positions)} points", flush=True)
        print(f"export_point_cloud time: {time.perf_counter() - export_start:.2f}s", flush=True)