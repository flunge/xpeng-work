import os
import sys
import torch
import numpy as np

current_dir = os.path.dirname(__file__)
root_path = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(root_path)
from nail_evolsplat.dataset import Dataset
from nail_evolsplat.utils.data import read_rgb_filename, eval_source_images_from_current_imageid

class Datamanager():
    def __init__(self, case_id, root_data_folder, output_folder):
        dataset = Dataset(case_id, root_data_folder, output_folder)

        self.dataset, self.cam_num = dataset.generate_dataparser_outputs()
        self.points_mask_info = self.dataset["input_pnt"]

        self.num_images_per_cam = len(self.dataset["image_filenames"]) // self.cam_num
        self.num_source_image = 3
        self.device = "cuda"

    def get_seed_points(self):
        return self.dataset["input_pnt"]

    def get_data_length(self):
        return len(self.dataset["image_filenames"])

    def get_next_data(self, image_idx):
        scene_id = torch.tensor([image_idx // self.num_images_per_cam])
        start_index = scene_id * self.num_images_per_cam
        end_index = start_index + self.num_images_per_cam - 1

        all_pose = self.dataset["cameras_info"].camera_to_worlds
        curr_poses = all_pose[start_index:end_index+1,:,:]
        cur_image_filenames = self.dataset["image_filenames"][start_index:end_index+1]
        cur_depth_filenames = self.dataset['depth_filenames'][start_index:end_index+1]
        seg_mask_bkgds = self.dataset['seg_mask_bkgds'][start_index:end_index+1]
        curr_cameras = self.dataset["cameras_info"][start_index:end_index+1]

        tar_image = read_rgb_filename(image_filename=self.dataset["image_filenames"][image_idx],seg_mask_bkgd= self.dataset['seg_mask_bkgds'][image_idx])
        camera = self.dataset["cameras_info"][image_idx:image_idx + 1].to(self.device)

        source_images, src_poses, source_ids, src_depths = eval_source_images_from_current_imageid(
            rgbs=cur_image_filenames, depths=cur_depth_filenames, all_pose = curr_poses.to(self.device),
            num_select=self.num_source_image, eval_pose=camera.camera_to_worlds,seg_mask_bkgds = seg_mask_bkgds)

        source_ids = np.array(sorted(source_ids)) 
        eye = torch.tensor([0., 0., 0., 1.]).to(self.device).unsqueeze(0)
        target_pose = torch.cat([camera.camera_to_worlds,eye.unsqueeze(0)],dim=1)
        intrinsics = camera.get_normal_intrinsics_matrices().cuda()

        batch = {"source": {
                    "extrinsics": src_poses,
                    "intrinsics": intrinsics.repeat(self.num_source_image,1,1),
                    "image": source_images.cuda(),
                    "depth": src_depths.cuda(), # type: ignore
                    "source_id": source_ids
                },
                "target": {
                    "extrinsics": target_pose,
                    "intrinsics": intrinsics,
                    "image": tar_image.unsqueeze(0).cuda(),
                    "target_id": image_idx
                },
                "scene_id": scene_id.to(self.device),
                "points_mask_info": self.points_mask_info
                }
        return camera, batch

