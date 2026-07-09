import json
import os

import cv2
import numpy as np
import open3d as o3d

from .bundle_adjustment import BundleAdjustment
from .sensor import FeatureMatch, Image, ImageKeyPoint, Landmark, Visibility
from .superglue_match import SuperGlueMatch
from .triangulation import triangulate_points_process, Triangulator
from .utils import get_output_dir, Log, pose_vec_to_dict, save_both_poses_to_json_file, save_calib_to_json_file, set_output_dir
from .vehicle import Vehicle


class CalibProcessor:
    def __init__(self, clip_path: str, out_path: str = None, model_path: str = None):
        self.clip_path = clip_path
        self.model_path = model_path
        self.logger = Log()
        self.optimized = False
        self.max_point_count = 500000
        self.vehicle = None
        self.camera_names = ['cam2', 'cam3', 'cam4', 'cam5', 'cam6', 'cam7', 'cam0']
        self.repack_names = ['lidar_repack2']

        set_output_dir(os.path.join(self.clip_path, out_path if out_path is not None else "vslam"))

    def run_vslam(self):
        self.vehicle = Vehicle(self.clip_path, self.camera_names, self.repack_names, logger=self.logger)
        self.load_visual_data(os.path.join(get_output_dir(), "visual_data.json"))
        if not self.vehicle.visual_match_list:
            self.superglue_matching()
            self.pack_keypoints_matches()
            self.undistort_images_keypoints()
            self.save_visual_data(os.path.join(get_output_dir(), "visual_data.json"))
        self.triangulate_points_nb()
        self.trim_points()
        self.bundle_adjustment()
        self.update_calib_info()

    def superglue_matching(self):
        superglue_match = SuperGlueMatch(self.vehicle, model_path=self.model_path, debug=True, logger=self.logger)
        superglue_match.superglue_matching()
        self._take_superglue_results(superglue_match)

        # Clear SuperGlueMatch memory data
        del superglue_match.frames
        del superglue_match.frame_pairs
        superglue_match.superpoint = None
        superglue_match.superglue = None
        superglue_match.last_data = None
        import gc
        gc.collect()
        import torch
        torch.cuda.empty_cache()
        self.logger.info("SuperGlue matching completed and memory cleared")

    def _take_superglue_results(self, super_glue: SuperGlueMatch):
        match_list = []
        for _, frame in super_glue.frames.items():
            image = frame.image
            image.keypoints = frame.kpts
            curr_image_index = frame.curr_image_index
            prev_image_index = frame.prev_image_index
            for flow_match in frame.matches:
                curr_kpt_idx = flow_match.queryIdx
                prev_kpt_idx = flow_match.trainIdx
                curr_img_kpt = ImageKeyPoint(curr_image_index, curr_kpt_idx)
                prev_img_kpt = ImageKeyPoint(prev_image_index, prev_kpt_idx)
                match = FeatureMatch(curr_img_kpt, prev_img_kpt)
                match_list.append(match)

        for frame_pairs in super_glue.frame_pairs:
            for frame_pair in frame_pairs:
                prev_img_index = frame_pair.train_image_index
                curr_img_index = frame_pair.query_image_index
                for match in frame_pair.matches:
                    curr_kpt_idx = match.queryIdx
                    prev_kpt_idx = match.trainIdx
                    curr_img_kpt = ImageKeyPoint(curr_img_index, curr_kpt_idx)
                    prev_img_kpt = ImageKeyPoint(prev_img_index, prev_kpt_idx)
                    match = FeatureMatch(curr_img_kpt, prev_img_kpt)
                    match_list.append(match)

        self.vehicle.visual_match_list.extend(match_list)

    def pack_keypoints_matches(self):
        self.logger.info(f"Packing {len(self.vehicle.visual_match_list)} matches")
        matched_keypoints = self.vehicle.count_matched_keypoints()
        img_kpt_map = self.vehicle.pack_images_keypoints(matched_keypoints)
        self.vehicle.reindex_matches(img_kpt_map)

    def undistort_image_keypoints(self, image: Image):
        camera = self.vehicle.get_camera_by_name(image.camera_name)
        image.undistort_keypoints(camera)
        for kpt in image.keypoints_undistorted:
            if not np.isfinite(kpt.pt[0]) or not np.isfinite(kpt.pt[1]):
                self.logger.warning("Undistorted keypoint has non-finite coordinates: %s" % kpt.pt)
                self.logger.warning("Image time: %d, camera name: %s" % (image.time, image.camera_name))
        if len(image.keypoints_undistorted) == 0:
            self.logger.warning(f"No undistorted keypoints found in Image time: {image.time}, camera name: {image.camera_name}")

    def undistort_images_keypoints(self):
        self.logger.info("Undistorting keypoints")
        image_list = self.vehicle.image_list
        for image in image_list:
            self.undistort_image_keypoints(image)
        return

    def triangulate_single_point(self, chain):
        triangulator = Triangulator(self.vehicle)
        point3d_estimated = triangulator.triangulate_keypoints(chain)
        if point3d_estimated is None:
            return None
        if os.name == 'posix':
            landmark = Landmark(0, point3d_estimated)
        else:
            color = self.vehicle.average_keypoints_color(chain) / 255.0
            landmark = Landmark(0, point3d_estimated, True, color)
        return landmark

    def triangulate_points_nb(self):
        # self.vehicle.image_list = self.vehicle.image_list[:2]
        # self.vehicle.visual_match_list = self.vehicle.visual_match_list[:1]
        chains = self._chains_from_matches()
        self.logger.info(f"Triangulating {len(chains)} points")
        point4d_list = triangulate_points_process(chains, self.vehicle)
        # point4d_list = [self.triangulate_single_point(chain) for chain in chains]
        self.vehicle.landmark_list.clear()
        self.vehicle.visibility_list.clear()
        num_zero_data = 0
        for i, chain in enumerate(chains):
            point4d = point4d_list[i]
            if point4d[3] == 0:
                num_zero_data += 1
                continue
            landmark_index = len(self.vehicle.landmark_list)
            if os.name == 'posix':
                landmark = Landmark(landmark_index, point4d[:3])
            else:
                color = self.vehicle.average_keypoints_color(chain) / 255.0
                landmark = Landmark(landmark_index, point4d[:3], True, color)
            self.vehicle.landmark_list.append(landmark)
            visibility = Visibility(landmark_index, chain)
            self.vehicle.visibility_list.append(visibility)
        self.logger.info(f"Landmarks: {len(self.vehicle.landmark_list)}")
        self.logger.info(f"Visibilities: {len(self.vehicle.visibility_list)}")
        self.logger.info(f"Num zero data: {num_zero_data}")

    @staticmethod
    def merge_chains(chain1:list, chain2:list, keypoint_to_chain:dict):
        chain1.extend(chain2)
        for keypoint in chain2:
            keypoint_to_chain[keypoint] = chain1
        return chain1

    def _chains_from_matches(self):
        chains = []
        keypoint_to_chain = {}
        for match in self.vehicle.visual_match_list:
            prev_img_kpt = match.train_img_kpt
            curr_img_kpt = match.query_img_kpt
            if prev_img_kpt in keypoint_to_chain:
                chain = keypoint_to_chain[prev_img_kpt]
                if curr_img_kpt in keypoint_to_chain:
                    chain2 = keypoint_to_chain[curr_img_kpt]
                    if chain2 != chain:
                        chain = self.merge_chains(chain, chain2, keypoint_to_chain)
                else:
                    chain.append(curr_img_kpt)
                    keypoint_to_chain[curr_img_kpt] = chain
            else:
                chain = [prev_img_kpt, curr_img_kpt]
                chains.append(chain)
                keypoint_to_chain[prev_img_kpt] = chain
                keypoint_to_chain[curr_img_kpt] = chain
        self.vehicle.visual_match_list.clear()
        return chains

    def trim_points(self):
        orig_count = len(self.vehicle.landmark_list)
        if orig_count < self.max_point_count:
            return
        count_stats = np.zeros((10,), dtype=np.int32)
        landmarks = self.vehicle.landmark_list
        visibilities = self.vehicle.visibility_list
        for landmark in landmarks:
            if not landmark.valid:
                count_stats[0] += 1
                continue
            landmark_index = landmark.index
            chains = visibilities[landmark_index].img_kpts
            count = len(chains)
            if count < len(count_stats):
                count_stats[count] += 1
        count_to_be_deleted = orig_count - self.max_point_count
        min_count = 0
        for count, num in enumerate(count_stats):
            if num > count_to_be_deleted:
                break
            count_to_be_deleted -= num
            min_count = count
        deleted_count = 0
        for landmark in landmarks:
            if not landmark.valid:
                continue
            landmark_index = landmark.index
            chains = visibilities[landmark_index].img_kpts
            count = len(chains)
            if count <= min_count:
                landmark.valid = False
                deleted_count += 1
        self.logger.info(f"Trimmed {deleted_count} points with less than {min_count} observations")

    def bundle_adjustment(self):
        ba = BundleAdjustment(self.vehicle, use_visual=True, use_lidar=False, logger=self.logger,
                              proc_str="visual_mapping")
        ba.run_bundle_adjustment()
        self.optimized = ba.optimized
        self.logger.info(f"Bundle adjustment finished with result: {self.optimized}")

    def save_visual_data(self, file_path: str):
        """
        将 visual_match_list 保存到 JSON 文件
        """
        # 转换为字典列表
        matches_dict = [match.to_dict() for match in self.vehicle.visual_match_list]

        cam_img_pts = {}
        for image in self.vehicle.image_list:
            if image.camera_name not in cam_img_pts:
                cam_img_pts[image.camera_name] = {}
            cam_img_pts[image.camera_name][image.time] = [kp.pt for kp in image.keypoints_undistorted]

        json_data = {
            "visual_match_list": matches_dict,
            "keypoints_undistorted": cam_img_pts
        }

        # 保存到文件
        with open(file_path, 'w') as f:
            json.dump(json_data, f, indent=2)

    def load_visual_data(self, file_path: str):
        """
        从 JSON 文件加载 visual_match_list
        """
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                json_data = json.load(f)

            # 从字典重建对象
            self.vehicle.visual_match_list = [FeatureMatch.from_dict(match_dict)
                                              for match_dict in json_data["visual_match_list"]]

            num_img_pts = 0
            cam_img_pts = json_data.get("keypoints_undistorted", {})
            for camera_name, img_pts in cam_img_pts.items():
                cam_images = self.vehicle.get_images_by_camera_name(camera_name)
                for image in cam_images:
                    if image is not None and str(image.time) in img_pts:
                        num_img_pts += len(img_pts[str(image.time)])
                        image.keypoints_undistorted = [cv2.KeyPoint(pt[0], pt[1], 4) for pt in img_pts[str(image.time)]]
                        # image.keypoints = image.keypoints_undistorted

            self.logger.info(f"Restored visual matches: {len(self.vehicle.visual_match_list)}, keypoints: {num_img_pts}")

    def update_calib_info(self):
        # Convert our calib to standard format
        for cam in self.vehicle.camera_names:
            focal = self.vehicle.calib_dict[cam]['intrinsic']['focal_length']
            scale = 0.5 # since dataportal image is resized to 1/2
            self.vehicle.calib_dict[cam]['intrinsic']['focal_length'] = focal * 1000 / 4.2 * scale
            self.vehicle.calib_dict[cam]['intrinsic']['cx'] *= scale
            self.vehicle.calib_dict[cam]['intrinsic']['cy'] *= scale

        self.vehicle.interpolate_main_poses()
        save_calib_to_json_file(os.path.join(get_output_dir(), 'calib_opt.json'), self.vehicle.calib_dict)
        save_both_poses_to_json_file(os.path.join(get_output_dir(), 'poses_opt.json'), self.vehicle.pose_list,
                                     self.vehicle.lidar_poses)

        # # Backup the original calib file
        # org_calib_path = os.path.join(self.cfg.clip_path, "calib.json")
        # with open(org_calib_path, 'r') as f:
        #     org_calib = json.load(f)

        # os.system(f"cp {org_calib_path} {org_calib_path.replace('.json', '_origin.json')}")

        # # Update the extrinsic and local pose
        # for cam, calib_dict in self.vehicle.calib_dict.items():
        #     if cam in org_calib:
        #         org_calib[cam]['extrinsic'] = calib_dict['extrinsic']

        # org_calib["local_pose"] = []
        # # Iterate through each camera pose in the list of camera poses
        # for p in self.vehicle.pose_list:
        #     # Get the timestamp, position and quaternion from the camera pose
        #     pose = p.get_t_q_vector()
        #     # Convert the pose vector to a pose dictionary
        #     pose_item = pose_vec_to_dict(pose)
        #     # Append the pose item to the list of camera poses
        #     org_calib["local_pose"].append(pose_item)

        # org_calib["global_pose"] = org_calib["local_pose"]

        # # Save the updated calibration to a new file
        # json.dump(org_calib, open(os.path.join(self.cfg.clip_path, "calib.json"), 'w'), indent=4)
        # self.logger.info(f"Updated calib.json with optimized extrinsics and local poses")


def main(clip_path: str, out_path: str = None, model_path: str = None):
    CalibProcessor(clip_path, out_path, model_path).run_vslam()


if __name__ == "__main__":
    clip_path = "/workspace/chenm8@xiaopeng.com/dataset/3dgs_debug/c-a00de8b8-05ae-356e-a00d-ac49cc6a2b42"
    out_path = "vslam"
    model_path = "/root/workspace/chenm8@xiaopeng.com/SuperGluePretrainedNetwork/models/weights/superglue_outdoor.pth"
    main(clip_path, out_path, model_path)