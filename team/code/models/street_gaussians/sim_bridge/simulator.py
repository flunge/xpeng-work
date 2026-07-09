import torch 
import os, sys
current_dir = os.path.dirname(__file__) 
relative_path = os.path.join(current_dir, '..')
root_path = os.path.abspath(os.path.join(relative_path, '..'))
print(f"import relative_path {relative_path} {root_path}")
sys.path.extend([relative_path, root_path])

import json
import time
import numpy as np
from scipy.spatial.transform import Rotation as R

from lib.datasets.xpeng_sim_readers import readXpengSimInfo
from lib.datasets.base_readers import CameraInfo
from lib.models.street_gaussian_model import StreetGaussianModel 
from lib.models.street_gaussian_renderer import StreetGaussianRenderer
from lib.utils.colmap_converter import get_files_in_folder
from lib.utils.graphics_utils import focal2fov, fov2focal
from lib.utils.camera_utils import Camera
from lib.utils.xpeng_utils import _label2camera
from lib.utils.system_utils import searchForMaxIteration
from lib.utils.sim_utils import mask_ego_path_gs
from lib.config import cfg

from sim_interface.utils import get_camera_calib, interpolate_pose_with_times
from sim_interface.utils import undistort_image_with_new_intrinc
from sim_interface.utils import lookup_pose
from sim_interface.utils import redistort
from sim_interface.simulator_base import BaseSimulator

from plyfile import PlyData, PlyElement
from scipy.spatial import cKDTree

class StreetGaussianSimulator(BaseSimulator):
    def __init__(self, config, cp_simulation=False, iter=None):
        super(StreetGaussianSimulator, self).__init__(config, cp_simulation, iter)
        
        if self.cp_simulation:
            self._replace_cam2rig_with_origin_calib()
  
            self.ground_xyz = self.gaussians.ground.get_xyz.detach().cpu().numpy()
            self.ground_xy = self.ground_xyz[:, :2]
            self.ground_z = self.ground_xyz[:, 2]
            self.ground_ply_index = cKDTree(self.ground_xy)

    @property
    def _label2camera(self):
        return _label2camera

    @property
    def _camera2label(self):
        return {
                'cam0': 1,
                'cam2': 2,
                'cam3': 3,
                'cam4': 4,
                'cam5': 5,
                'cam6': 6,
                'cam7': 7,
            }
            
    def init_parameters(self, config):
        self.model_path = config.model_path
        self.cameras = config.data.cameras
        self.selected_frames = config.data.get('selected_frames', None)
        self.result_dict = dict(config.results)

        self.timestamps_origin = [int(i) for i in self.result_dict['timestamps']]
        self.egoposes_anchored_origin = np.array(self.result_dict['ego_frame_poses'])
        
        # smooth the ego pose in all origin frames
        self.result_dict['ego_frame_poses_smooth'] = self.smooth_ego_frame_poses(self.egoposes_anchored_origin)
        self.egoposes_anchored_smooth = np.array(self.result_dict['ego_frame_poses_smooth'])
        
        self.anchor_pose = np.array(self.result_dict['anchor_pose'])
        self.cams2rig = np.array(self.result_dict['extrinsics']) # might be changed by _replace_cam2rig_with_origin_calib
        self.intrinsics = np.array(self.result_dict['intrinsics'])
        self.camera_wh = self.result_dict['camera_wh']

    def smooth_ego_frame_poses(self, ego_frame_poses):
        # Apply a simple moving average filter to smooth the ego frame poses
        angle_seq = 'zyx'
        smooth_frame_window = 5
        smoothed_ego_frame_poses = ego_frame_poses.copy()

        all_result_euler = dict()
        origin_result_euler = dict()

        for i in range(ego_frame_poses.shape[0]):
            if i < smooth_frame_window or i >= ego_frame_poses.shape[0] - smooth_frame_window:
                continue
            start_frame = i - smooth_frame_window
            end_frame = i + smooth_frame_window

            ego_frames_in_windows = ego_frame_poses[start_frame:end_frame]

            # only average the rotation: pitch 
            # from start_frame to end_frame, sum all the pitch
            pitches_in_windows = list()
            for j in range(0, len(ego_frames_in_windows) - 1):
                rotation_in_window_frame = ego_frames_in_windows[j, :3, :3]
                euler_in_window_frame = R.from_matrix(rotation_in_window_frame).as_euler(angle_seq, degrees=False)
                pitch = euler_in_window_frame[1]
                pitches_in_windows.append(pitch)

            pitch_mean = np.mean(pitches_in_windows)
            rotation_in_frame = ego_frame_poses[i, :3, :3]
            euler_in_frame = R.from_matrix(rotation_in_frame).as_euler(angle_seq, degrees=False)
            new_euler_in_frame = R.from_euler(angle_seq, [euler_in_frame[0], pitch_mean, euler_in_frame[2]], degrees=False)
            origin_result_euler[i] = [euler_in_frame[0], euler_in_frame[1], euler_in_frame[2]]
            all_result_euler[i] = [euler_in_frame[0], pitch_mean, euler_in_frame[2]] 
            smoothed_ego_frame_poses[i, :3, :3] = new_euler_in_frame.as_matrix()
        
        return smoothed_ego_frame_poses

    def visualize_smoothed_plot(self, all_result_euler, origin_result_euler):
        # plot all_result_euler, every rotation is a subplot
        # radians to degree then display
        import matplotlib.pyplot as plt

        fig, axs = plt.subplots(3, 1, figsize=(10, 8))
        axs[0].plot(all_result_euler.keys(), [v[0] * 180 / np.pi for v in all_result_euler.values()], label='Yaw')
        axs[1].plot(all_result_euler.keys(), [v[1] * 180 / np.pi for v in all_result_euler.values()], label='Pitch')
        axs[2].plot(all_result_euler.keys(), [v[2] * 180 / np.pi for v in all_result_euler.values()], label='Roll')
        for ax in axs:
            ax.legend()
            ax.grid()
        plt.show()
        # save in curr dir
        fig.savefig("smoothed_ego_frame_poses.png")

        # plot origin_result_euler
        fig, axs = plt.subplots(3, 1, figsize=(10, 8))
        axs[0].plot(origin_result_euler.keys(), [v[0] * 180 / np.pi for v in origin_result_euler.values()], label='Yaw')
        axs[1].plot(origin_result_euler.keys(), [v[1] * 180 / np.pi for v in origin_result_euler.values()], label='Pitch')
        axs[2].plot(origin_result_euler.keys(), [v[2] * 180 / np.pi for v in origin_result_euler.values()], label='Roll')
        for ax in axs:
            ax.legend()
            ax.grid()
        plt.show()
        # save in curr dir
        fig.savefig("origin_ego_frame_poses.png")

    def init_models(self, config):
        self.scene_info_metadata = readXpengSimInfo(
            self.cameras, self.selected_frames, self.result_dict
        )
        self.gaussians = StreetGaussianModel(self.scene_info_metadata)
        self.renderer = StreetGaussianRenderer()

        if cfg.render.get("fix", False):
            from difix.fixer import DifixFixer
            self.image_fixer = DifixFixer(cfg.fixer)

    def setup_models(self, config, iter=None):
        self.setup_models_ply(config, iter)
        #self.setup_models_pth(config, iter)

    def setup_models_pth(self, config, iter=None):
        assert(os.path.exists(config.point_cloud_dir)), f"Model gaussians {config.point_cloud_dir} does not exist!"
        self.loaded_iter = searchForMaxIteration(config.point_cloud_dir) if iter is None else iter
        print("[INFO] Loading checkpoint at iteration {}".format(self.loaded_iter))
        checkpoint_path = os.path.join(config.trained_model_dir, f"iteration_{str(self.loaded_iter)}.pth")
        assert os.path.exists(checkpoint_path), f"{checkpoint_path} does not exist!"
        state_dict = torch.load(checkpoint_path)
        self.gaussians.load_state_dict(state_dict=state_dict)
    
    def setup_models_ply(self, config, iter=None):
        assert(os.path.exists(config.point_cloud_dir)), f"Model gaussians {config.point_cloud_dir} does not exist!"
        self.loaded_iter = searchForMaxIteration(config.point_cloud_dir) if iter is None else iter
        print("[INFO] Loading ply at iteration {}".format(self.loaded_iter))
        self.merge_ply_files(os.path.join(cfg.point_cloud_dir, f"iteration_{self.loaded_iter}"))
        ply_path = os.path.join(cfg.point_cloud_dir, f"iteration_{self.loaded_iter}", "point_cloud.ply")
        assert os.path.exists(ply_path), f"PLY file not found: {ply_path}"
        self.gaussians.load_ply(ply_path)
        if (self.gaussians.include_sky == True) and (self.gaussians.sky_cubemap is not None):
            print("[INFO] Loading sky_checkpoint at iteration {}".format(self.loaded_iter))
            checkpoint_path = os.path.join(config.trained_model_dir, f"iteration_{str(self.loaded_iter)}.pth")
            assert os.path.exists(checkpoint_path), f"{checkpoint_path} does not exist!"
            state_dict = torch.load(checkpoint_path)
            self.gaussians.sky_cubemap.load_state_dict(state_dict['sky_cubemap'])
            del state_dict

    def auto_edit(self, ego_radius=1.2, opacity_threshold=0.):
        scales_bkgd = self.gaussians.background.get_scaling.detach().cpu()
        xyz_bkgd = self.gaussians.background.get_xyz.detach().cpu()
        surface_bkgd = (scales_bkgd**2).sum(dim=-1)
        opacity_bkgd = self.gaussians.background.get_opacity.detach().cpu()

        mask_large_gs_bkgd_egopose = (surface_bkgd > 1).detach().cpu().numpy() & \
            mask_ego_path_gs(self.egoposes_anchored_origin, xyz_bkgd, 7)

        mask_large_gs_bkgd = (surface_bkgd > 10).detach().cpu().numpy()
        mask_egopose_gs = mask_ego_path_gs(self.egoposes_anchored_origin, xyz_bkgd, ego_radius)
        mask_low_opacity_bkgd = (opacity_bkgd < opacity_threshold).detach().cpu().numpy().flatten()
        mask_total = mask_large_gs_bkgd | mask_egopose_gs | mask_low_opacity_bkgd | mask_large_gs_bkgd_egopose
        print(f"[INFO] Total prune background {mask_total.sum()}/{self.gaussians.background.get_xyz.shape[0]}")
        self.gaussians.background.prune_points(mask_total)

    def simulate_one_frame(self, timestamp: int, ego_pose_world, profile_dict=None):
        """
        [SIM-API] Simulate one frame at a given timestamp and ego_pose in the shape of [4, 4]
        """
        results = dict()
        for cam_id in self.cameras:
            cam_name = self._label2camera[cam_id]
            t1 = time.time()
            result, camera = self.render(cam_id, timestamp, ego_pose_world)
            # get cam_name from camera
            t2 = time.time()
            img_distort = self.redistort_gpu(cam_name, result['rgb'])
            t3 = time.time()
            if cfg.render.get("fix", False) and cam_id in cfg.fixer.cam:
                img_distort = self.image_fixer.fix_image(img_distort)
                target_height = int(self.calib_info['new' + cam_name]['height'])
                target_width = int(self.calib_info['new' + cam_name]['width'])
                if img_distort.shape[1] != target_height or img_distort.shape[2] != target_width:
                    img_distort = torch.nn.functional.interpolate(
                        img_distort.unsqueeze(0).float(),
                        size=(target_height, target_width), mode='bilinear', align_corners=False
                    ).squeeze(0).clamp(0, 255).to(torch.uint8)
            t4 = time.time()
            results[self._label2camera[cam_id]] = img_distort
            if profile_dict is not None:
                profile_dict[cam_name].append([t2 - t1, t3 - t2, t4 - t3])
            else:
                print(f"[INFO] render {cam_name} {result['rgb'].shape} cost {t2 - t1}, redistort cost {t3 - t2}, fix cost {t4 - t3}")
        return results
    
    def write_to_pth(self):
        state_dict = self.gaussians.save_state_dict(is_final=True)
        state_dict['iter'] = self.loaded_iter
        ckpt_path = os.path.join(cfg.trained_model_dir, f'iteration_{self.loaded_iter}.pth')
        # backup origin
        if os.path.exists(ckpt_path):
            backup_path = os.path.join(cfg.trained_model_dir, f'iteration_{self.loaded_iter}_origin.pth')
            if os.path.exists(backup_path):
                os.remove(backup_path)
            os.rename(ckpt_path, backup_path)
        torch.save(state_dict, ckpt_path)

    def write_to_ply(self):
        point_cloud_path = os.path.join(cfg.model_path, 'point_cloud', f'iteration_{self.loaded_iter}')
        # backup_path = os.path.join(cfg.model_path, 'point_cloud', f'iteration_{self.loaded_iter}_root')
        # # backup origin
        # if os.path.exists(point_cloud_path) and not os.path.exists(backup_path):
        #     # rename directory
        #     os.rename(point_cloud_path, backup_path)
        self.gaussians.save_ply_model(point_cloud_path)
        # os.system(f'mv {backup_path}/point_cloud.ply {point_cloud_path}/point_cloud.ply')

    def merge_ply_files(self, input_dir="", output_path="", exclude_prefix="vis_", remove_prefix="model_"):
        ply_files = [
            f for f in os.listdir(input_dir) 
            if f.endswith(".ply") 
            and not f.startswith(exclude_prefix) 
            and f != "point_cloud.ply"
        ]
        if not ply_files:
            print("[WARNING] No valid PLY files found (excluding vis_*.ply and point_cloud.ply).")
            return
        
        ply_elements = []
        for file in ply_files:
            file_path = os.path.join(input_dir, file)
            try:
                plydata = PlyData.read(file_path)
                model_name = os.path.splitext(file)[0] 
                cleaned_name = model_name.replace(remove_prefix, "")
                for element in plydata.elements:
                    new_element = PlyElement.describe(
                        element.data, 
                        f"vertex_{cleaned_name}"
                    )
                    ply_elements.append(new_element)
            except Exception as e:
                print(f"[Error] Failed to load: {file} ({e})")

        if ply_elements:
            output_path = os.path.join(input_dir, "point_cloud.ply")
            PlyData(ply_elements).write(output_path)
        else:
            print("[WARNING] No valid data to merge")
    
    def remove_unused_files(self):
        iter_ground = int(cfg.train_xpeng.iterations_ground)
        # os.system(f'rm -rf {cfg.model_path}/trained_model/iteration_{iter_ground}.pth')
        # os.system(f'rm -rf {cfg.model_path}/trained_model/iteration_{self.loaded_iter}_origin.pth')
        # os.system(f'rm -rf {cfg.model_path}/point_cloud/iteration_{iter_ground}')

    def reset_render_resolution(self):
        print("[WARNING] -------- !Reset render resolution! --------")
        undistort_crop = self.calib_info.get('undistort_crop', False)
        for i, cam_id in enumerate(self.cameras):
            cam_name = _label2camera[cam_id]
            image_real = self.images_real[cam_name]
            image_real_distort = redistort(self.calib_info, cam_name, image_real, image_real)

            camera_matrix, dist_coeffs = get_camera_calib(self.calib_info[cam_name]['intrinsic'])
            image_real_new, new_camera_matrix, roi = undistort_image_with_new_intrinc(
                image_real_distort, camera_matrix, dist_coeffs, crop=undistort_crop
            )
            self.calib_info["new" + cam_name]["intrinsic"]["focal_length_x"] = new_camera_matrix[0, 0]
            self.calib_info["new" + cam_name]["intrinsic"]["focal_length_y"] = new_camera_matrix[1, 1]
            self.calib_info["new" + cam_name]["intrinsic"]["cx"] = new_camera_matrix[0, 2]
            self.calib_info["new" + cam_name]["intrinsic"]["cy"] = new_camera_matrix[1, 2]
            self.calib_info["new" + cam_name]["intrinsic"]["distortion"] = dist_coeffs.tolist()
            self.calib_info["new" + cam_name]["name"] = "new" + cam_name

            self.images_real[cam_name] = image_real_new
            self.camera_wh[cam_name] = (image_real_new.shape[1], image_real_new.shape[0])
            self.intrinsics[i] = new_camera_matrix

    def render(self, cam_id, timestamp, ego_pose_world):
        camera = self.get_camera(cam_id, timestamp, ego_pose_world)
        with torch.no_grad():
            result = self.renderer.render(camera, self.gaussians) 
        return result, camera

    def render_all(self, cam_id, timestamp, ego_pose_world):
        camera = self.get_camera(cam_id, timestamp, ego_pose_world)
        with torch.no_grad():
            result = self.renderer.render_all(camera, self.gaussians) 
        return result, camera

    def get_camera(self, cam_id, timestamp_sim, ego_pose_world):
        cam_id_local = self.cameras.index(cam_id)
        cam_name = _label2camera[cam_id]
        c2anchor, ego_pose_anchored = self._get_cam2anchor(ego_pose_world, cam_id_local, timestamp_sim)
        RT = np.linalg.inv(c2anchor)
        R_MAT = RT[:3, :3].T
        T = RT[:3, 3]
        if 'undistort_crop' in self.calib_info and self.calib_info['undistort_crop']:
            K, FovX, FovY, width, height = self._get_cam_intrinsic_noncrop(cam_name)
        else:
            K, FovX, FovY, width, height = self._get_cam_intrinsic(cam_id_local, cam_name)

        time_local = (timestamp_sim - self.result_dict['timestamp_offset']) / 1e9
        timestamps = [int(i) for i in self.scene_info_metadata['frames_timestamps_global']]
        frame_id = np.abs(np.array(timestamps) - timestamp_sim).argmin()
        
        print(f"[INFO] timestamp_sim {timestamp_sim} time_local {time_local}")
        metadata = dict()
        metadata['cam'] = cam_name
        metadata['timestamp'] = time_local
        metadata['is_val'] = True
        metadata['frame'] = frame_id
        metadata['frame_idx'] = frame_id
        # metadata['ego_pose'] = self.egoposes_anchored_origin[frame_id]
        pose_buffer = dict(zip(timestamps, self.egoposes_anchored_origin))
        ego_pose = lookup_pose(pose_buffer, timestamp_sim, 0.1)
        metadata['ego_pose'] = ego_pose

        smoothed_pose_buffer = dict(zip(timestamps, self.egoposes_anchored_smooth))
        ego_pose_smoothed = lookup_pose(smoothed_pose_buffer, timestamp_sim, 0.1)
        metadata['ego_pose_smoothed'] = ego_pose_smoothed

        metadata['extrinsic'] = np.array(self.result_dict['extrinsics'][cam_id_local])

        cam = Camera(
            id=frame_id+cam_id_local, RT=RT, R=R_MAT, T=T, K=K, FoVx=FovX, FoVy=FovY, 
            image_name=f"{timestamp_sim}", metadata=metadata,
            image=None, height=height, width=width, c2anchor=c2anchor
        )
        return cam

    def _get_cam_intrinsic(self, cam_id_local, cam_name):
        K = self.intrinsics[cam_id_local].copy()
        fx, fy = K[0, 0], K[1, 1]
        width, height = self.camera_wh[cam_name]
        FovY = focal2fov(fy, height)
        FovX = focal2fov(fx, width)
        return K, FovX, FovY, width, height

    def _get_cam_intrinsic_noncrop(self, cam_name):
        intrinsic = self.calib_info['noncrop'+cam_name]['intrinsic']
        expand_ratio = self.calib_info['expand_ratio'][cam_name]
        fx = intrinsic['focal_length_x'] * expand_ratio
        fy = intrinsic['focal_length_y'] * expand_ratio
        cx = intrinsic['cx'] * expand_ratio
        cy = intrinsic['cy'] * expand_ratio
        K = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]])
        width = int(self.calib_info['noncrop'+cam_name]['width'] * expand_ratio)
        height = int(self.calib_info['noncrop'+cam_name]['height'] * expand_ratio)
        if cam_name == 'cam2':
            height = int(height * 0.68) 
        FovY = focal2fov(fy, height)
        FovX = focal2fov(fx, width)
        return K, FovX, FovY, width, height
    
    def _get_cam2anchor(self, rig2world, cam_id_local, timestamp=-1):
        cam2rig = self.cams2rig[cam_id_local]
        if self.cp_simulation:
            print(f"[INFO] Using anchor pose from transferpose_index for timestamp {timestamp}")
            current_localpose = interpolate_pose_with_times(
                self.dds_localpose, timestamp
            )
            dist = np.linalg.norm(current_localpose[:2, 3] - rig2world[:2, 3])
            print(
                f"[INFO] tiemstamp: {timestamp}, distance with real car and sim car: {dist}"
            )
            anchor_pose = self.get_anchor_pose(rig2world)
            rig2anchor = np.linalg.inv(anchor_pose) @ rig2world
            
            if dist > 3:
                # refine z using ground ply
                xy_query = rig2anchor[:3, 3][:2]
                search_radius = 1.0
                while True:
                    idxs = self.ground_ply_index.query_ball_point(
                        xy_query, r=search_radius
                    )
                    if len(idxs) > 3 or search_radius > 5.0:
                        break
                    search_radius += 0.5

                if len(idxs) > 3:
                    neighbors = self.ground_xyz[idxs]
                    X = neighbors[:, 0]
                    Y = neighbors[:, 1]
                    Z = neighbors[:, 2]
                    A = np.c_[X, Y, np.ones_like(X)]

                    coeffs, _, _, _ = np.linalg.lstsq(A, Z, rcond=None)  # [a, b, c]
                    z_est = coeffs[0] * xy_query[0] + coeffs[1] * xy_query[1] + coeffs[2]
                    print(f"[INFO] tiemstamp: {timestamp}, fix z value, old z : {rig2anchor[2, 3]}, new value {z_est}")
                    rig2anchor[2, 3] = z_est
        else:
            rig2anchor = np.linalg.inv(self.anchor_pose) @ rig2world

        cam2anchor = rig2anchor @ cam2rig
        return cam2anchor, rig2anchor


def numpy_array_to_bytes(image_array):
    # 确保数组是 uint8 类型
    if image_array.dtype != np.uint8:
        image_array = image_array.astype(np.uint8)
    return image_array.tobytes()


def bytes_to_numpy_array(byte_data, shape, dtype=np.uint8):
    array = np.frombuffer(byte_data, dtype=dtype)
    array = array.reshape(shape)
    return array

# Function : this blew function used to generate img for CP simualtion 
def fun(simulator, rendered_timestamp, cam_id, egoposes_anchored):
    print(f"CP timestamp {rendered_timestamp} cam_id {cam_id} egoposes_anchored {egoposes_anchored}", flush=True)
    
    q = egoposes_anchored[:4]
    t = egoposes_anchored[4:7]
    rotation_matrix = R.from_quat([q[1], q[2], q[3], q[0]]).as_matrix()
    rotation_matrix = np.array(rotation_matrix)
    translation_matrix = np.array([t[0],t[1],t[2]])
    rig_to_world =  np.eye(4)
    rig_to_world[:3,:3] = rotation_matrix
    rig_to_world[:3,3] = translation_matrix
    ego_pose_world = rig_to_world
    output_images = []

    t1 = time.time()
    if cam_id[-1]=='0':
        CamIndex = 1
    else:
        CamIndex = int(cam_id[-1])
    
    if CamIndex not in simulator.cameras :
        print("not support camera ", CamIndex)
        return None
    
    result, camera = simulator.render(CamIndex, int(rendered_timestamp), ego_pose_world)
    
    print(f'render cost {time.time() - t1}')
    t2 = time.time()
    result["rgb"] = torch.clamp(result["rgb"] * 255, 0, 255)
    result["rgb"] = result["rgb"].to(torch.uint8)
    img_distort = simulator.redistort_gpu(cam_id, result['rgb'])
    if cfg.render.get("fix", False):    
        print(f" render add fixer")
        img_distort = simulator.image_fixer.fix_image(img_distort)
        target_height = int(simulator.calib_info['new' + cam_id]['height'])
        target_width = int(simulator.calib_info['new' + cam_id]['width'])
        if img_distort.shape[1] != target_height or img_distort.shape[2] != target_width:
            img_distort = torch.nn.functional.interpolate(
                img_distort.unsqueeze(0).float(),
                size=(target_height, target_width), mode='bilinear', align_corners=False
            ).squeeze(0).clamp(0, 255).to(torch.uint8)
    img_distort = img_distort.permute(1, 2, 0).cpu().numpy()
    print(f'img_distort cost {time.time() - t2}')
    height, width = img_distort.shape[0:2]
    # byte_data1 = numpy_array_to_bytes(img_distort)
    info = {
        'cam': cam_id,
        'time_stamp': rendered_timestamp,
        'width': width,
        'height': height,
        'image': img_distort.flatten().astype(np.uint8)
    }
    print(f"Rendering {cam_id} images done", flush=True)
    return info
