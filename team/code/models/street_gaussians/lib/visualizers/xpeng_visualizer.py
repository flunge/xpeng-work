import os
import torchvision
import cv2
import torch
import imageio
import numpy as np
from PIL import Image

from lib.utils.camera_utils import Camera
from lib.utils.img_utils import visualize_depth_numpy
from lib.config import cfg


class XpengVisualizer():
    def __init__(self, save_dir):
        
        self.result_dir = save_dir
        os.makedirs(self.result_dir, exist_ok=True)
        
        self.save_video = cfg.render.save_video
        self.save_image = cfg.render.save_image
        self.save_misc_images = cfg.render.save_misc_images
        
        self.rgbs_gt = []
        self.rgbs = []
        self.accs = []
        self.rgbs_bkgd = []
        self.rgbs_grd = []
        self.rgbs_obj = []

        # harmonize visualize
        self.rgbs_harmonized = []
        self.rgbs_mask = []

        self.accs_bkgd = []
        self.accs_obj = []
        self.depths = []
        self.diffs = []
        self.normals = []
        self.cams = []
        
        self.depth_visualize_func = lambda x: visualize_depth_numpy(x, cmap=cv2.COLORMAP_JET)[0][..., [2, 1, 0]]
        self.diff_visualize_func = lambda x: visualize_depth_numpy(x, cmap=cv2.COLORMAP_TURBO)[0][..., [2, 1, 0]]

            
    def visualize(self, result, camera: Camera):
        self.cams.append(camera.meta['cam'])
        name = camera.image_name
        cam_name = camera.meta['cam']

        rgb = result['rgb']
        acc = result['acc']
        if 'rgb_ground' in result.keys():
            rgb_bkgd = result['rgb_ground']
        else:
            rgb_bkgd = result['rgb_background']
        rgb_obj = result['rgb_object']
        acc_bkgd = result['acc_background']
        acc_obj = result['acc_object']

        os.makedirs(os.path.join(self.result_dir, "gt-rgb", cam_name), exist_ok=True)
        os.makedirs(os.path.join(self.result_dir, "rgb", cam_name), exist_ok=True)
        os.makedirs(os.path.join(self.result_dir, "acc", cam_name), exist_ok=True)
        os.makedirs(os.path.join(self.result_dir, "rgb_bkgd", cam_name), exist_ok=True)
        os.makedirs(os.path.join(self.result_dir, "rgb_obj", cam_name), exist_ok=True)
        os.makedirs(os.path.join(self.result_dir, "acc_bkgd", cam_name), exist_ok=True)
        os.makedirs(os.path.join(self.result_dir, "acc_obj", cam_name), exist_ok=True)
        os.makedirs(os.path.join(self.result_dir, "diff", cam_name), exist_ok=True)
        os.makedirs(os.path.join(self.result_dir, "depth", cam_name), exist_ok=True)
        
        if self.save_image:
            torchvision.utils.save_image(rgb, os.path.join(self.result_dir, "rgb", cam_name, f'{name}.png'))
            torchvision.utils.save_image(acc, os.path.join(self.result_dir, "acc", cam_name, f'{name}.png'))
            torchvision.utils.save_image(rgb_bkgd, os.path.join(self.result_dir, "rgb_bkgd", cam_name, f'{name}.png'))
            torchvision.utils.save_image(rgb_obj, os.path.join(self.result_dir, "rgb_obj", cam_name, f'{name}.png'))
            torchvision.utils.save_image(acc_bkgd, os.path.join(self.result_dir, "acc_bkgd", cam_name, f'{name}.png'))
            torchvision.utils.save_image(acc_obj.float(), os.path.join(self.result_dir, "acc_obj", cam_name, f'{name}_acc_obj.png'))
            torchvision.utils.save_image(camera.original_image[:3], os.path.join(self.result_dir, "gt-rgb", cam_name, f'{name}.png'))
    
        if self.save_video:
            rgb_gt = (camera.original_image[:3].detach().cpu().numpy().transpose(1, 2, 0) * 255).astype(np.uint8)
            self.rgbs_gt.append(rgb_gt)
            rgb = (rgb.detach().cpu().numpy().transpose(1, 2, 0) * 255).astype(np.uint8)                                            
            self.rgbs.append(rgb)            
            acc = (acc.detach().cpu().numpy().transpose(1, 2, 0) * 255).astype(np.uint8)                                            
            self.accs.append(acc)
            rgb_bkgd = (rgb_bkgd.detach().cpu().numpy().transpose(1, 2, 0) * 255).astype(np.uint8)
            self.rgbs_bkgd.append(rgb_bkgd)
            rgb_obj = (rgb_obj.detach().cpu().numpy().transpose(1, 2, 0) * 255).astype(np.uint8)
            self.rgbs_obj.append(rgb_obj)
            acc_bkgd = (acc_bkgd.detach().cpu().numpy().transpose(1, 2, 0) * 255).astype(np.uint8)
            self.accs_bkgd.append(acc_bkgd)
            acc_obj = (acc_obj.detach().cpu().numpy().transpose(1, 2, 0) * 255).astype(np.uint8)
            self.accs_obj.append(acc_obj)

        if self.save_misc_images:
            self.visualize_diff(result, camera)
            self.visualize_depth(result, camera)
            self.visualize_normal(result, camera)

    def visualize_redistort_harmonized(self, result, camera: Camera):
        self.cams.append(camera.meta['cam'])
        name = camera.image_name
        cam_name = camera.meta['cam']

        rgb = result['redistort_rgb']
        rgb_harmonized = result['redistort_rgb_harmonized']
        rgb_mask = result['redistort_rgb_mask']

        os.makedirs(os.path.join(self.result_dir, "redistort_rgb", cam_name), exist_ok=True)
        os.makedirs(os.path.join(self.result_dir, "redistort_rgb_harmonized", cam_name), exist_ok=True)
        os.makedirs(os.path.join(self.result_dir, "redistort_rgb_mask", cam_name), exist_ok=True)
        
        if self.save_image:
            print(f"[visualize_redistort_harmonized] write image， cam: {cam_name}, image: {name}.png")
            cv2.imwrite(os.path.join(self.result_dir, "redistort_rgb_harmonized", cam_name, f'{name}.png'), cv2.cvtColor(rgb_harmonized, cv2.COLOR_RGB2BGR))
            
        if self.save_video:
            self.rgbs.append(rgb)
            self.rgbs_harmonized.append(rgb_harmonized)
            self.rgbs_mask.append(rgb_mask)
    
    def visualize_redistort(self, result, camera: Camera):
        self.cams.append(camera.meta['cam'])
        name = camera.image_name
        cam_name = camera.meta['cam']

        rgb_gt = result['redistort_rgb_gt']
        rgb = result['redistort_rgb']
        rgb_bkgd = result['redistort_rgb_background']
        rgb_grd = result['redistort_rgb_ground']
        rgb_obj = result['redistort_rgb_object']

        os.makedirs(os.path.join(self.result_dir, "redistort_rgb_gt", cam_name), exist_ok=True)
        os.makedirs(os.path.join(self.result_dir, "redistort_rgb", cam_name), exist_ok=True)
        os.makedirs(os.path.join(self.result_dir, "redistort_rgb_bkgd", cam_name), exist_ok=True)
        os.makedirs(os.path.join(self.result_dir, "redistort_rgb_grd", cam_name), exist_ok=True)
        os.makedirs(os.path.join(self.result_dir, "redistort_rgb_obj", cam_name), exist_ok=True)
        
        if self.save_image:
            cv2.imwrite(os.path.join(self.result_dir, "redistort_rgb_gt", cam_name, f'{name}.png'), cv2.cvtColor(rgb_gt, cv2.COLOR_RGB2BGR))
            cv2.imwrite(os.path.join(self.result_dir, "redistort_rgb", cam_name, f'{name}.png'), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
            cv2.imwrite(os.path.join(self.result_dir, "redistort_rgb_bkgd", cam_name, f'{name}.png'), cv2.cvtColor(rgb_bkgd, cv2.COLOR_RGB2BGR))
            cv2.imwrite(os.path.join(self.result_dir, "redistort_rgb_grd", cam_name, f'{name}.png'), cv2.cvtColor(rgb_grd, cv2.COLOR_RGB2BGR))
            cv2.imwrite(os.path.join(self.result_dir, "redistort_rgb_obj", cam_name, f'{name}.png'), cv2.cvtColor(rgb_obj, cv2.COLOR_RGB2BGR))
            
        if self.save_video:
            self.rgbs_gt.append(rgb_gt)
            self.rgbs.append(rgb)            
            self.rgbs_bkgd.append(rgb_bkgd)
            self.rgbs_grd.append(rgb_grd)
            self.rgbs_obj.append(rgb_obj)

    def visualize_evaluator(self, rgb, camera: Camera, folder_name):
        self.cams.append(camera.meta['cam'])
        name = camera.image_name
        cam_name = camera.meta['cam']

        output_path = os.path.join(self.result_dir, folder_name, cam_name, f'{name}.png')
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        cv2.imwrite(output_path, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        self.rgbs.append(rgb)   

    def visualize_novel_view(self, result, camera: Camera):
        self.cams.append(camera.meta['cam'])
        id = camera.id
        rgb = result['rgb']
        depth = result['depth']
        depth = depth.permute(1, 2, 0).detach().cpu().numpy() # [H, W, 1]
        # np.save(os.path.join(self.result_dir, f'{id}_depth.npy'), depth)

        if self.save_image:
            torchvision.utils.save_image(rgb, os.path.join(self.result_dir, f'{id:06d}_rgb.png'))
            imageio.imwrite(os.path.join(self.result_dir, f'{id:06d}_depth.png'), self.diff_visualize_func(depth))

        if self.save_video:
            rgb = (rgb.detach().cpu().numpy().transpose(1, 2, 0) * 255).astype(np.uint8)
            self.rgbs.append(rgb)
            self.depths.append(depth)
                
    def visualize_diff(self, result, camera: Camera):
        name = camera.image_name
        cam_name = camera.meta['cam']

        rgb_gt = camera.original_image[:3]
        rgb = result['rgb'].detach().cpu()
        
        if hasattr(camera, 'original_mask'):
            mask = camera.original_mask.bool()
        else:
            mask = torch.ones_like(rgb[0]).bool()
            
        rgb = torch.where(mask, rgb, torch.zeros_like(rgb))
        rgb_gt = torch.where(mask, rgb_gt, torch.zeros_like(rgb_gt))
        
        rgb = rgb.permute(1, 2, 0).numpy() # [H, W, 3]
        rgb_gt = rgb_gt.permute(1, 2, 0).numpy() # [H, W, 3]
        diff = ((rgb - rgb_gt) ** 2).sum(axis=-1, keepdims=True) # [H, W, 1]
        
        if self.save_image:
            imageio.imwrite(os.path.join(self.result_dir, "diff", cam_name, f'{name}.png'), 
                self.diff_visualize_func(diff))
        
        if self.save_video:
            self.diffs.append(diff)

    def visualize_depth(self, result, camera: Camera):
        name = camera.image_name
        cam_name = camera.meta['cam']

        depth = result['depth']

        depth = depth.detach().permute(1, 2, 0).detach().cpu().numpy() # [H, W, 1]
        
        if self.save_image:
            imageio.imwrite(os.path.join(self.result_dir, "depth", cam_name, f'{name}.png'), 
                self.diff_visualize_func(depth))

        if self.save_video:
            self.depths.append(depth)
            
    def visualize_normal(self, result, camera: Camera):
        if 'normals' in result.keys():            
            name = camera.image_name
            normals = result['normals'].detach().permute(1, 2, 0) # [H, W, 3]
            
            # transform normal to camera space
            # R_w2c = camera.world_view_transform[:3, :3]
            # normals = torch.matmul(normals, R_w2c.T)
            
            normals = (normals + 1) / 2.0 # to 0 - 1
            normals = (normals.cpu().numpy() * 255).astype(np.uint8)

            if self.save_image:
                imageio.imwrite(os.path.join(self.result_dir, f'{name}_normal.png'), normals)

            if self.save_video:
                self.normals.append(normals)

    def save_video_from_frames(self, frames, name, visualize_func=None):
        if len(frames) == 0:
            return
        
        unqiue_cams = sorted(list(set(self.cams)))
        if len(unqiue_cams) == 1:
            if visualize_func is not None:
                frames = [visualize_func(frame) for frame in frames]
            imageio.mimwrite(os.path.join(self.result_dir, f'{name}.mp4'), frames, fps=cfg.render.fps)
        else:
            concat_cameras = cfg.render.get('concat_cameras', [])
            if len(concat_cameras) == len(unqiue_cams):
                frames_cam_all = []
                for cam in concat_cameras:
                    frames_cam = [frame for frame, c in zip(frames, self.cams) if c == cam]
                    frames_cam_all.append(frames_cam)
                
                frames_cam_len = [len(frames_cam) for frames_cam in frames_cam_all]
                assert len(list(set(frames_cam_len))) == 1, 'all cameras should have same number of frames'
                num_frames = frames_cam_len[0]

                frames_concat_all = []
                for i in range(num_frames):
                    frames_concat = []
                    for j in range(len(concat_cameras)):
                        frames_concat.append(frames_cam_all[j][i])
                    frames_concat = np.concatenate(frames_concat, axis=1)
                    frames_concat_all.append(frames_concat)
                
                if visualize_func is not None:
                    frames_concat_all = [visualize_func(frame) for frame in frames_concat_all]    
        
                imageio.mimwrite(os.path.join(self.result_dir, f'{name}.mp4'), frames_concat_all, fps=cfg.render.fps)
            
            else:
                for cam in unqiue_cams:
                    frames_cam = [frame for frame, c in zip(frames, self.cams) if c == cam]
                    
                    if visualize_func is not None:
                        frames_cam = [visualize_func(frame) for frame in frames_cam]
                    
                    imageio.mimwrite(os.path.join(self.result_dir, f'{name}_{str(cam)}.mp4'), frames_cam, fps=cfg.render.fps)

    def save_video_merged(self, mode='origin', fps=None):
        fps = cfg.render.fps if fps is None else fps
        unqiue_cams = sorted(list(set(self.cams)))
        for cam in unqiue_cams:
            frames_cam = []
            rgb_cam = []
            for i, c in zip(range(len(self.rgbs)), self.cams):
                if c == cam:
                    # row1 = np.concatenate([self.rgbs_gt[i], self.rgbs[i], self.rgbs_bkgd[i]], axis=1)
                    # row2 = np.concatenate([np.repeat(self.accs[i], 3, axis=-1), self.rgbs_obj[i], np.repeat(self.accs_obj[i], 3, axis=-1)], axis=1)
                    row1 = np.concatenate([self.rgbs_gt[i], self.rgbs[i]], axis=1)
                    row2 = np.concatenate([self.rgbs_bkgd[i], self.rgbs_obj[i]], axis=1)
                    image_to_show = np.concatenate([row1, row2], axis=0).astype(np.uint8)
                    frames_cam.append(image_to_show)
                    rgb_cam.append(np.concatenate([self.rgbs_gt[i], self.rgbs[i]], axis=1).astype(np.uint8))
            
            imageio.mimwrite(os.path.join(self.result_dir, f'video_{str(cam)}_{mode}_merged.mp4'), frames_cam, fps=fps)
            imageio.mimwrite(os.path.join(self.result_dir, f'video_{str(cam)}_{mode}_rgb.mp4'), rgb_cam, fps=fps)
    
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
    
    def save_video_eval(self, mode='eval', fps=None):
        fps = cfg.render.fps if fps is None else fps
        unqiue_cams = sorted(list(set(self.cams)))
        for cam in unqiue_cams:
            target_rgbs = []
            for i, c in zip(range(len(self.rgbs)), self.cams):
                if c == cam:
                    target_rgbs.append(self.rgbs[i])
            imageio.mimwrite(os.path.join(self.result_dir, f'video_{str(cam)}_{mode}_rgb.mp4'), target_rgbs, fps=fps)

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

    def summarize(self):                
        if cfg.render.get('save_video', True):
            if cfg.render.get('save_video_merged', True):
                self.save_video_merged()
            else:
                self.save_video_from_frames(self.rgbs_gt, 'rgb_gt')
                self.save_video_from_frames(self.rgbs, 'rgb')
                self.save_video_from_frames(self.accs, 'acc')
                self.save_video_from_frames(self.rgbs_bkgd, 'rgb_bkgd')
                self.save_video_from_frames(self.rgbs_obj, 'rgb_obj')
                self.save_video_from_frames(self.accs_bkgd, 'acc_bkgd')
                self.save_video_from_frames(self.accs_obj, 'acc_obj')
                try:
                    self.save_video_from_frames(self.depths, 'depth', visualize_func=self.depth_visualize_func)
                    self.save_video_from_frames(self.diffs, 'diff', visualize_func=self.diff_visualize_func)
                except Exception as e:
                    print('[ERROR] Error in saving depth and diff video:\n', e)
