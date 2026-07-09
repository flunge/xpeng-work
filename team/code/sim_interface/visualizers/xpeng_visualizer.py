import os
import cv2
import imageio
import numpy as np

class XpengVisualizer():
    def __init__(self, save_dir, save_img=False, save_video=True):
        
        self.result_dir = save_dir
        os.makedirs(self.result_dir, exist_ok=True)
        
        self.save_video = save_video
        self.save_image = save_img
        
        self.rgbs_gt = []
        self.rgbs = []
        self.accs = []
        self.rgbs_bkgd = []
        self.rgbs_grd = []
        self.rgbs_obj = []
        self.accs_bkgd = []
        self.accs_obj = []
        self.depths = []
        self.diffs = []
        self.normals = []
        self.cams = []

        # harmonize visualize
        self.rgbs_harmonized = []
        self.rgbs_mask = []

    def visualize_redistort(self, result, cam_name, image_name):
        self.cams.append(cam_name)
        keys = ['redistort_rgb_gt', 'redistort_rgb', 'redistort_rgb_background', 'redistort_rgb_ground', 'redistort_rgb_object']

        for key in keys:
            if key in result and result[key] is not None:
                os.makedirs(os.path.join(self.result_dir, key, cam_name), exist_ok=True)
                if self.save_image and key == 'redistort_rgb':
                    cv2.imwrite(
                        os.path.join(self.result_dir, key, cam_name, f'{image_name}.png'), 
                        cv2.cvtColor(result[key], cv2.COLOR_RGB2BGR))
                if self.save_video:
                    if key == 'redistort_rgb_gt':
                        self.rgbs_gt.append(result[key])
                    elif key == 'redistort_rgb':
                        self.rgbs.append(result[key])
                    elif key == 'redistort_rgb_background':
                        self.rgbs_bkgd.append(result[key])
                    elif key == 'redistort_rgb_ground':
                        self.rgbs_grd.append(result[key])
                    elif key == 'redistort_rgb_object':
                        self.rgbs_obj.append(result[key])
                    else:
                        raise ValueError(f"Invalid key: {key}")

    def save_video_merged(self, mode='origin', fps=None, save_merged=True):
        fps = cfg.render.fps if fps is None else fps
        unqiue_cams = sorted(list(set(self.cams)))
        for cam in unqiue_cams:
            frames_cam = []
            rgb_cam = []
            for i, c in zip(range(len(self.rgbs)), self.cams):
                if c == cam:
                    if save_merged:
                        row1 = np.concatenate([self.rgbs_grd[i], self.rgbs[i]], axis=1)
                        row2 = np.concatenate([self.rgbs_bkgd[i], self.rgbs_obj[i]], axis=1)
                        image_to_show = np.concatenate([row1, row2], axis=0).astype(np.uint8)
                        frames_cam.append(image_to_show)
                        rgb_cam.append(np.concatenate([self.rgbs_gt[i], self.rgbs[i]], axis=1).astype(np.uint8))
                    else:
                        rgb_cam.append(self.rgbs[i])
            if save_merged:
                imageio.mimwrite(os.path.join(self.result_dir, f'video_{str(cam)}_{mode}_merged.mp4'), frames_cam, fps=fps)
            imageio.mimwrite(os.path.join(self.result_dir, f'video_{str(cam)}_{mode}_rgb.mp4'), rgb_cam, fps=fps)

    def save_video_ground(self, fps=None):
        fps = cfg.render.fps if fps is None else fps
        unqiue_cams = sorted(list(set(self.cams)))
        for cam in unqiue_cams:
            frames_cam = []
            ground_cam = []
            for i, c in zip(range(len(self.rgbs)), self.cams):
                if c == cam:
                    ground_cam.append(
                        np.concatenate([self.rgbs_gt[i], self.rgbs_grd[i]], axis=1).astype(np.uint8)
                    )
            imageio.mimwrite(os.path.join(self.result_dir, f'video_{str(cam)}_ground_rgb.mp4'), ground_cam, fps=fps)

    def visualize_redistort_harmonized(self, result, cam_name, image_name):
        self.cams.append(cam_name)

        rgb = result['redistort_rgb']
        rgb_harmonized = result['redistort_rgb_harmonized']
        rgb_mask = result['redistort_rgb_mask']

        os.makedirs(os.path.join(self.result_dir, "redistort_rgb_harmonized", cam_name), exist_ok=True)
        
        print(f"[visualize_redistort_harmonized] write image， cam: {cam_name}, image: {image_name}.png")
        cv2.imwrite(os.path.join(self.result_dir, "redistort_rgb_harmonized", cam_name, f'{image_name}.png'), cv2.cvtColor(rgb_harmonized, cv2.COLOR_RGB2BGR))
                    
        if self.save_video:
            self.rgbs.append(rgb)
            self.rgbs_harmonized.append(rgb_harmonized)
            self.rgbs_mask.append(rgb_mask)

    def save_video_harmonized(self, mode='origin', fps=None):
        # row 1: harmonized rgb | mask
        # row 2 : original rgb | empty
        fps = cfg.render.fps if fps is None else fps
        unqiue_cams = sorted(list(set(self.cams)))
        for cam in unqiue_cams:
            frames_cam = []
            for i, c in zip(range(len(self.rgbs_harmonized)), self.cams):
                if c == cam:
                    row1 = np.concatenate([self.rgbs_harmonized[i], self.rgbs_mask[i]], axis=1)
                    row2 = np.concatenate([self.rgbs[i], np.zeros_like(self.rgbs_mask[i])], axis=1)
                    image_to_show = np.concatenate([row1, row2], axis=0).astype(np.uint8)
                    frames_cam.append(image_to_show)
            
            imageio.mimwrite(os.path.join(self.result_dir, f'video_{str(cam)}_{mode}_harmonized.mp4'), frames_cam, fps=fps)
    