import addict
import copy
import glob
import json
import os
import shutil
import subprocess
import sys
import time
import cv2
import numpy as np
import open3d as o3d
import trimesh
import yaml

from utils.file_utils import read_custom_ply_with_colors, NumpyEncoder
from utils.file_utils import download_file_from_oss2
from utils.ground_utils import segment_road_points_local_fast, merge_ground_ply


class GroundProcessor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.out_dir = os.path.join(self.cfg.clip_path, "vision", "recon", "ground_output")
        self.proc_method = self.cfg.ground_processor.method
        self.oss_config_name = self.cfg.ground_processor.oss_config

        os.makedirs(self.out_dir, exist_ok=True)

        self.callback = {
            "rogs": self.process_ground_with_rogs,
            "rome": self.process_ground_with_rome,
        }

    def process_ground_points(self):
        self.callback.get(self.proc_method, self.process_default)()

    def process_ground_with_rogs(self):
        # Prepare the configs
        rogs_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ground_processing", "rogs")

        local_config_path = os.path.join(rogs_path, "configs", "oss_rogs_config.yaml")
        remote_config_path = f'sim_engine/ips_configs/rogs_configs/{self.oss_config_name}'
        if not download_file_from_oss2(local_config_path, object_key=remote_config_path):
            raise UserWarning(f"[ERROR] download config {remote_config_path} from oss failed!\n")

        # Update the system path to include the rogs directory
        sys.path.append(rogs_path)
        from ground_processing.rogs.train import train as rogs_train

        with open(local_config_path, 'r') as f:
            rogs_cfg = yaml.safe_load(f)

        # Update the configs
        rogs_cfg["dataset"]["clip_path"] = self.cfg.clip_path
        rogs_cfg["dataset"]["clip_list"] = [self.cfg.clip_id[:10]]
        rogs_cfg["output"] = self.out_dir
        rogs_cfg["file"] = os.path.join(rogs_cfg["output"], "rogs_config.yaml")

        # Check MVSNet ply file to generate ground point cloud
        merge_rogs_with_mvs_ground = False
        if self.cfg.ground_processor.z_weight_from_mvsnet > 0:
            ground_mvsnet_ply_path = os.path.join(self.cfg.clip_path, "ground_points_new.ply")
            is_generated = True

            if os.path.exists(ground_mvsnet_ply_path):
                ground_ply_path = ground_mvsnet_ply_path
                merge_rogs_with_mvs_ground = True
            else:
                print("[ERROR] Ground mvsnet ply file not found, use rogs_ground_gt.ply")
                ground_ply_path = os.path.join(self.cfg.clip_path, "misc", "rogs_ground_gt.ply")
            
            if not os.path.exists(ground_ply_path):
                is_generated = self._gen_ground_ply(ground_ply_path)
            
            if is_generated:
                rogs_cfg["dataset"]["ground_ply"] = ground_ply_path
                rogs_cfg["optimization"]["z_weight"] = self.cfg.ground_processor.z_weight_from_mvsnet
                rogs_cfg["optimization"]["smooth_loss_weight"] = 1.0
            else:
                print("[ERROR] Ground ply generation failed, skip z weight and smooth loss")

        # Write the updated configs to a temporary file
        with open(rogs_cfg["file"], 'w') as f:
            yaml.dump(rogs_cfg, f, sort_keys=False)

        rogs_cfg = addict.Dict(rogs_cfg)
        rogs_train(rogs_cfg)

        rogs_ply_file = os.path.join(rogs_cfg["output"], 'ply', 'final.ply')
        final_ply_path = os.path.join(self.cfg.clip_path, 'misc','ground_final.ply')
        os.makedirs(os.path.dirname(final_ply_path), exist_ok=True)
        shutil.copy(rogs_ply_file, final_ply_path)
        
        # save affine transform pth
        affine_pth_path = os.path.join(rogs_cfg["output"], 'affine_transform.pth')
        if os.path.exists(affine_pth_path):
            shutil.copy(affine_pth_path, os.path.join(self.cfg.clip_path, 'misc', 'affine_transform.pth'))
            print(f"[INFO] Affine pth saved to {os.path.join(self.cfg.clip_path, 'misc', 'affine_transform.pth')}")
        else:
            print(f"[ERROR][RoGS] Affine pth not found at {affine_pth_path}")

        # If road_mesh_new.ply exists, back it up
        rogs_pcd = read_custom_ply_with_colors(rogs_ply_file)
        if merge_rogs_with_mvs_ground:
            t1 = time.time()
            mvsnet_pcd = o3d.io.read_point_cloud(ground_ply_path)
            rogs_pcd = merge_ground_ply(rogs_pcd, mvsnet_pcd)
            t2 = time.time()
            print(f"[RoGS] Time taken for merge_ground_ply: {t2 - t1} seconds")

        if rogs_pcd is not None:
            old_road_ply = os.path.join(self.cfg.clip_path, 'road_mesh_new.ply')
            if os.path.exists(old_road_ply):
                shutil.move(old_road_ply, os.path.join(self.cfg.clip_path, 'road_mesh_new_backup.ply'))
                print(f"[INFO] Backed up existing road_mesh_new.ply to road_mesh_new_backup.ply")

            o3d.io.write_point_cloud(old_road_ply, rogs_pcd)
            print(f"[INFO] Ground points saved to {os.path.join(self.cfg.clip_path, 'road_mesh_new.ply')}")

        self._generate_rogs_compatible_outputs(rogs_cfg)

    def process_ground_with_rome(self):
        rome_cfg = self._load_rome_config()
        self._prepare_workspace(rome_cfg)
        self._update_calib_info_to_colmap(rome_cfg)
        self._train_bev_mesh(rome_cfg)
        self._transform_pose_coord(rome_cfg)
        self._transform_pointcloud_coord(rome_cfg)

        # Copy to the clip_path if road_mesh_new.ply exists
        new_mesh_save_dir = os.path.join(rome_cfg["exp_dir"], "road_mesh_new.ply")
        if os.path.exists(new_mesh_save_dir):
            old_road_ply = os.path.join(self.cfg.clip_path, 'road_mesh_new.ply')
            if os.path.exists(old_road_ply):
                shutil.move(old_road_ply, os.path.join(self.cfg.clip_path, 'road_mesh_new_backup.ply'))
                print(f"[INFO] Backed up existing road_mesh_new.ply to road_mesh_new_backup.ply")
            shutil.copy(new_mesh_save_dir, old_road_ply)
            print(f"[INFO] Ground points saved to {os.path.join(self.cfg.clip_path, 'road_mesh_new.ply')}")

    def _load_rome_config(self):
        # The following items should be updated from default yaml file
        # base_dir, clip_list, cliprun_id, datarun_id, dataset_name exp_dir, sql_filter, rome_output_dir, trips_json
        rome_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ground_processing", "rome")
        with open(os.path.join(rome_path, "configs", "config.yaml"), "r") as f:
            config = yaml.safe_load(f)

        # Update the configs
        recon_dir = os.path.join(self.cfg.clip_path, "vision", "recon")
        config["base_dir"] = self.cfg.clip_path
        config["clip_list"] = [self.cfg.clip_id]
        config["cliprun_id"] = self.cfg.clip_id
        config["datarun_id"] = self.cfg.clip_id
        config["dataset_name"] = self.cfg.dataset_name
        config["exp_dir"] = recon_dir
        config["sql_filter"] = f"id like '{self.cfg.clip_id}'"
        config["rome_output_dir"] = self.out_dir
        config["trips_json"] = os.path.join(recon_dir, "merged_trips.json")

        # Save the updated configs
        with open(os.path.join(config["exp_dir"], "config.yaml"), "w") as f:
            yaml.dump(config, f, sort_keys=False)

        return config

    def _prepare_workspace(self, config):
        mvsnet_metadata_dir = os.path.join(config["exp_dir"], "mvsnet_metadata")
        mvsnet_output_dir = os.path.join(config["exp_dir"], "mvsnet_output")

        mvsnet_done = (
            os.path.exists(mvsnet_metadata_dir) and
            os.path.exists(mvsnet_output_dir) and
            os.path.exists(os.path.join(config["exp_dir"], "image"))
        )

        if mvsnet_done:
            print("[INFO] Detected existing mvsnet workspace, skipping image link creation")
            with open(os.path.join(config["base_dir"], "metadata.json"), "r") as f:
                meta_info = json.load(f)
            vehicle_name = meta_info["vehicle_name"]
            trip_ts = str(meta_info["start_time"])

            with open(config["trips_json"], "w") as f:
                json.dump({f"image/{vehicle_name}/{trip_ts}": {0: self.cfg.clip_id}}, f, indent=4)

            return

        # Get vehicle name and start timestamp
        with open(os.path.join(config["base_dir"], "metadata.json"), "r") as f:
            meta_info = json.load(f)
        vehicle_name = meta_info["vehicle_name"]
        trip_ts = str(meta_info["start_time"])

        # Generate trips_json
        with open(config["trips_json"], "w") as f:
            json.dump({f"image/{vehicle_name}/{trip_ts}": {0: self.cfg.clip_id}}, f, indent=4)

        with open(os.path.join(config["base_dir"], "timestamp2slice.json"), "r") as f:
            timestamp2slice = json.load(f)

        with open(os.path.join(config["base_dir"], "calib.json"), "r") as f:
            clip_calib_json = json.load(f)

        # Link images and seg masks
        mapping_dict = {}
        link_items = [["images", "image"], ["segs", "seg_mask"]]
        for cam_name in config["cam_list"]:
            for link_item in link_items:
                img_list = glob.glob(os.path.join(config["base_dir"], link_item[0], cam_name, "*.png"))
                img_path = os.path.join(config["exp_dir"], link_item[1], vehicle_name, trip_ts, cam_name)
                os.makedirs(img_path, exist_ok=True)
                for old_img_path in img_list:
                    img_name = os.path.basename(old_img_path)
                    ts = img_name.split(".")[0]
                    if ts not in timestamp2slice:
                        print(f"[WARNING] Timestamp {ts} not found in timestamp2slice.json")
                        continue
                    slice_id = timestamp2slice[ts]
                    new_img_name = f"slice{slice_id}.png"
                    new_img_path = os.path.join(img_path, new_img_name)
                    # If the symlink already exists, remove it
                    if os.path.islink(new_img_path):
                        os.unlink(new_img_path)
                    os.symlink(old_img_path, new_img_path)

                    tmp_info_dict = {}
                    tmp_info_dict["clip_id"] = config["cliprun_id"]
                    tmp_info_dict["slice_idx"] = str(slice_id)
                    tmp_info_dict["cam_id"] = cam_name
                    if "slice_id" in clip_calib_json:
                        tmp_info_dict["slice_id"] = clip_calib_json["slice_id"][ts]
                    else:
                        tmp_info_dict["slice_id"] = "UNKNOWN"
                    mapping_dict[os.path.join(vehicle_name, trip_ts, cam_name, new_img_name)] = tmp_info_dict

        with open(os.path.join(config["exp_dir"], "original_image_mapping.json"), "w+") as f:
            json.dump(mapping_dict, f, indent=4)

    def _update_calib_info_to_colmap(self, config):
        with open(config["trips_json"], "r") as f:
            trips_json = json.load(f)
        trip_path = list(trips_json.keys())[0]
        _, vehicle_name, trip_ts = trip_path.split("/")

        with open(os.path.join(config["base_dir"], "timestamp2slice.json"), "r") as f:
            timestamp2slice = json.load(f)

        with open(os.path.join(config["base_dir"], "transform.json"), "r") as f:
            transform_json = json.load(f)

        with open(os.path.join(config["base_dir"], "calib.json"), "r") as f:
            calib_info = json.load(f)

        # Update local pose with slice index
        localpose_timestamps = list(calib_info["local_pose"].keys())
        for ts in localpose_timestamps:
            if ts not in timestamp2slice:
                print(f"[WARNING] Timestamp {ts} not found in timestamp2slice.json")
                continue
            slice_id = timestamp2slice[ts]
            calib_info["local_pose"][f"slice{slice_id}"] = calib_info["local_pose"].pop(ts)
            if ts in calib_info["slice_id"]:
                calib_info["slice_id"][f"slice{slice_id}"] = calib_info["slice_id"].pop(ts)

        # Update cam_image_size
        calib_info["cam_image_size"] = {}
        trip_dir = os.path.join(config["exp_dir"], "image", vehicle_name, trip_ts)
        for cam in config["cam_list"]:
            image_filename = os.path.join(trip_dir, cam, "slice0.png")
            if os.path.exists(image_filename):
                image = cv2.imread(image_filename)
                calib_info["cam_image_size"][cam] = [image.shape[0], image.shape[1]]

        # Update camera extrinsics
        for cam, cam_data in transform_json["sensor_params"].items():
            if cam not in calib_info:
                print(f"Not found camera {cam} in colmap json")
                continue
            calib_info[cam]["extrinsic"]["transformation_matrix"] = np.linalg.inv(cam_data["extrinsic"]).tolist()

        # Update colmap_extrinsic and colmap_intrinsic
        calib_info["colmap_intrinsic"] = {}
        calib_info["colmap_extrinsic"] = {}

        for frame in transform_json["frames"]:
            _, cam, ts = frame["file_path"].split(".")[0].split("/")
            if ts not in timestamp2slice:
                print(f"Not found timestamp {ts} in timestamp2slice.json")
                continue
            calib_info["colmap_extrinsic"][f"slice{timestamp2slice[ts]}_{cam}"] = frame["transform_matrix"]

            if cam not in calib_info["colmap_intrinsic"] and cam in calib_info:
                calib_info["colmap_intrinsic"][cam] = {
                    "focal_length": calib_info[cam]["intrinsic"]["focal_length"], "cx": frame["cx"], "cy": frame["cy"]
                }

        json_path = os.path.join(trip_dir, "calib.json")
        with open(json_path, "w") as f:
            json.dump(calib_info, f, indent=4)

        print(f"Updated transform.json to {json_path}")

    def _train_bev_mesh(self, config):
        ### BEV mesh training
        print("bev_training")
        curr_path = os.path.dirname(os.path.abspath(__file__))
        rome_path = os.path.join(curr_path, "ground_processing", "rome")
        os.makedirs(config["rome_output_dir"], exist_ok=True)

        # ### For Debugging
        # sys.path.append(rome_path)
        # from ground_processing.rome.train_lightning import main as rome_train
        # rome_train(config)

        module_list = ["python", "-m", "ground_processing.rome.train_lightning", "--config"]
        lowres_config_path = os.path.join(config["exp_dir"], "config.yaml")
        subprocess.run(module_list + [lowres_config_path], check=True, cwd=curr_path)

        ### For high resolution mesh
        if config.get("scene", "driving") == "parking":
            print(f"start to multi resolution mesh rome optimization....")
            bev_seg_path = f"{config['rome_output_dir']}/bev_seg.png"
            assert os.path.exists(bev_seg_path), f"bev_seg_path does not exist: {bev_seg_path}"

            config["bev_seg_path"] = bev_seg_path
            config["old_bev_resolution"] = config["bev_resolution"]
            config["bev_resolution"] = config["bev_resolution_for_parking"]

            highres_config_path = os.path.join(config["exp_dir"], "config.yaml")
            with open(highres_config_path, "w") as f:
                yaml.dump(config, f, sort_keys=False)
            subprocess.run(module_list + [highres_config_path], check=True, cwd=curr_path)

        grid_baseline_path = os.path.join(config["rome_output_dir"], "grid_baseline.pt")
        assert os.path.exists(grid_baseline_path), f"grid baseline does not exist: {grid_baseline_path}"
        print("bev_training finished")

    def _transform_pose_coord(self, config, ref_sliceid='0', ref_camid='cam2'):
        ## print info
        print(f"Transform pose coord, ref_sliceid: {ref_sliceid}, ref_camid: {ref_camid}")

        # Get vehicle name and start timestamp
        with open(config["trips_json"], "r") as f:
            trips_json = json.load(f)
        trip_path = list(trips_json.keys())[0]

        json_path = os.path.join(os.path.join(config["exp_dir"], trip_path), "calib.json")
        with open(json_path, "r") as f:
            calib_info = json.load(f)

        gta_dir = os.path.join(config["exp_dir"], "gta_input")
        interpolated_pose_json_path = os.path.join(gta_dir, "interpolated_pose.json")
        interpolated_pose_js = json.load(open(interpolated_pose_json_path, 'r'))

        bevworld_to_refcamslice0 = None
        for key in interpolated_pose_js.keys():
            camid = key.split('/')[-1]
            assert camid.startswith('cam'), "check slice name in interporated_pose.json in gta input, whose camid is not start with 'cam'"
            if camid != ref_camid:
                continue

            value = interpolated_pose_js[key]
            slice_idx = value['slice_idx']
            if slice_idx == ref_sliceid:
                bevworld_to_refcamslice0 = value['world2camera']
                break

        assert bevworld_to_refcamslice0 is not None, f"bevworld_to_refcamslice0 is None, ref_sliceid: {ref_sliceid}, ref_camid: {ref_camid}"
        rig_to_refcam = np.array(calib_info[ref_camid]["extrinsic"]["transformation_matrix"])
        refcam_to_rig = np.linalg.inv(rig_to_refcam)
        bevworld_to_rig0 = refcam_to_rig @ bevworld_to_refcamslice0

        ## transform pose and save new pose
        new_pose_save_path = os.path.join(gta_dir, "interpolated_pose_new.json")
        new_pose_js = copy.deepcopy(interpolated_pose_js)
        for key, value in new_pose_js.items():
            bevworld_2_camera = value["world2camera"]
            rig0_2_camera =  bevworld_2_camera @ np.linalg.inv(bevworld_to_rig0)
            value["world2camera"] = rig0_2_camera
            value["camera2world"] = np.linalg.inv(rig0_2_camera)

        ## Update bevworld_to_rig0 in config
        config["bevworld_to_rig0"] = bevworld_to_rig0.tolist()

        ## save json
        with open(new_pose_save_path, "w") as f:
            json.dump(new_pose_js, f, cls=NumpyEncoder, indent=4)

    def _transform_pointcloud_coord(self, config):
        ## print info
        print(f"Transform point cloud from rignow to rig0 coord")
        bevworld_to_rig0 = np.array(config["bevworld_to_rig0"])

        rome_output_dir = config["rome_output_dir"]
        new_mesh_save_dir = os.path.join(self.cfg.clip_path, "road_mesh_new.ply")

        # Load the bev_mesh.obj
        try:
            import pymeshlab
            rome_obj_ms = pymeshlab.MeshSet()
            rome_obj_ms.load_new_mesh(os.path.join(rome_output_dir, "bev_mesh.obj"))
            rome_obj_ms.save_current_mesh(os.path.join(rome_output_dir, "road_mesh_old.ply"))
        except ImportError:
            print("pymeshlab not installed, skip converting bev_mesh.obj to road_mesh_old.ply")
            pass

        mesh = trimesh.load(os.path.join(rome_output_dir, "bev_mesh.obj"))
        vertex_colors = None
        texture_uv = None

        if isinstance(mesh.visual, trimesh.visual.ColorVisuals):
            vertex_colors = mesh.visual.vertex_colors
        elif isinstance(mesh.visual, trimesh.visual.TextureVisuals):
            vertex_colors = mesh.visual.vertex_colors
            texture_uv = mesh.visual.uv

        vertices = mesh.vertices
        vertices = np.hstack((vertices, np.ones((len(vertices), 1))))
        transformed_vertices = np.dot(bevworld_to_rig0, vertices.T).T
        transformed_vertices = transformed_vertices[:, :3]

        visual = None
        if texture_uv is not None:
            visual = trimesh.visual.TextureVisuals(uv=texture_uv)
            if vertex_colors is not None:
                visual.vertex_colors = vertex_colors
        else:
            if vertex_colors is not None:
                visual = trimesh.visual.ColorVisuals(vertex_colors=vertex_colors)

        new_mesh = trimesh.Trimesh(
            vertices=transformed_vertices,
            faces=mesh.faces,
            visual=visual
        )
        new_mesh.export(new_mesh_save_dir)

    def _generate_rogs_compatible_outputs(self, rogs_cfg):
        print("[INFO] Generating compatible outputs for pcd_fusion_processor...")

        rogs_output_dir = rogs_cfg["output"]
        final_dir = os.path.join(rogs_output_dir, "images", "final")
        ground_output_dir = self.out_dir

        bev_height_files = glob.glob(os.path.join(final_dir, "bev_height.*"))
        if len(bev_height_files) > 0:
            bev_height_file = bev_height_files[0]

            if bev_height_file.endswith('.npy'):
                bev_height = np.load(bev_height_file)
            elif bev_height_file.endswith('.npz'):
                import scipy.sparse as sp
                loaded = np.load(bev_height_file)
                sp_matrix = sp.csr_matrix((loaded['data'], loaded['indices'], loaded['indptr']), shape=loaded['shape'])
                bev_height = sp_matrix.toarray()

            try:
                valid_heights = bev_height[bev_height > 0]
                if len(valid_heights) > 0:
                    SLACK_Z = 1.0
                    bev_cam_height = np.max(valid_heights) + SLACK_Z

                    bev_depth = bev_cam_height - bev_height
                    bev_depth = np.maximum(bev_depth, 0)
                else:
                    print("[WARNING] No valid heights found, using bev_height as depth")
                    bev_depth = bev_height
            except Exception as e:
                print(f"[WARNING] Failed to calculate depth: {e}, using bev_height as depth")
                bev_depth = bev_height

            np.save(os.path.join(ground_output_dir, "bev_depth.npy"), bev_depth)
            print(f"[INFO] Saved bev_depth.npy to {ground_output_dir}")
        else:
            print("[WARNING] bev_height file not found in rogs output")

        bev_label_vis_file = os.path.join(final_dir, "bev_label_vis.png")
        if os.path.exists(bev_label_vis_file):
            shutil.copy(bev_label_vis_file, os.path.join(ground_output_dir, "bev_seg.png"))
            print(f"[INFO] Saved bev_seg.png to {ground_output_dir}")
        else:
            print(f"[WARNING] bev_label_vis.png not found at {bev_label_vis_file}")

        print("[INFO] Compatible outputs generation completed!")

    def _gen_ground_ply(self, ground_ply_path):
        mvsnet_ply_path = os.path.join(self.cfg.clip_path, "misc", "mvsnet", "mvsnet_final.ply")
        if os.path.exists(mvsnet_ply_path):
            localpose = json.load(open(os.path.join(self.cfg.clip_path, "localpose.json"), 'r'))
            trajectory = np.array([np.array(pose)[:3, 3].tolist() for _, pose in localpose.items()]).reshape(-1, 3)
            point_cloud = o3d.io.read_point_cloud(mvsnet_ply_path)
            t1 = time.time()
            road_points, road_colors = segment_road_points_local_fast(point_cloud, trajectory, window_size=8, dist_threshold=12.0)
            t2 = time.time()
            print(f"Time taken for segment_road_points_local_fast: {t2 - t1} seconds")
            if len(road_points) > 0:
                pcd_total_road = o3d.geometry.PointCloud()
                pcd_total_road.points = o3d.utility.Vector3dVector(road_points)
                pcd_total_road.colors = o3d.utility.Vector3dVector(road_colors / 255.0)
                o3d.io.write_point_cloud(ground_ply_path, pcd_total_road)
                print(f"Road points saved to rogs_ground_gt.ply ({len(road_points)} points)")
                return True
        return False

    def process_default(self):
        raise ValueError(f"Unknown ground processing method: {self.proc_method}. Use 'rogs' instead.")


if __name__ == "__main__":
    from settings.config import make_default_settings, make_case_specific_settings
    clip_ids = {
        # "c-5e32ce2b-5449-33f0-9138-43ba61251e2d": "vision_rogs",
        "c-e76de66e-4e1b-3e9d-9f37-8812526cfe48": "vision_sf_testsets_251208b",
    }
    for clip, folder in clip_ids.items():
        cfg = make_default_settings()
        cfg.ips_deploy = False
        cfg.dataset_name = "vision_rogs"
        cfg.root = f"/workspace/yangxh7@xiaopeng.com/datasets/xpeng/{folder}/"
        cfg.steps_controller.source = "vision"
        cfg.steps_controller.ground_processor = True
        cfg.ground_processor.method = "rogs"
        cfg.ground_processor.z_weight_from_mvsnet = 0.01 # 0.02
        # cfg.ground_processor.oss_config = "hil_rogs_config_dev.yaml"
        cfg.clip_id = clip
        cfg = make_case_specific_settings(cfg)

        grd_processor = GroundProcessor(cfg)
        grd_processor.process_ground_points()