import os
import time
from pathlib import Path
from typing import OrderedDict
import cv2
import matplotlib.cm as cm
import numpy as np
import torch

from .keypoint import filter_matches_geo, arrange_images, draw_matches
from .sensor import Image
from .utils import get_camera_pairs, get_num_features, get_output_dir, Log
from .vehicle import Vehicle

from optimization.lidaropt.lidar2cam_opt.submodules.Python_VO.Detectors.superpoint.superpoint import SuperPoint
from optimization.lidaropt.lidar2cam_opt.submodules.Python_VO.Matchers.superglue.superglue import SuperGlue


def frame2tensor(frame, device):
    return torch.from_numpy(frame/255.).float()[None, None].to(device)


class AverageTimer:
    """ Class to help manage printing simple timing of code execution. """

    def __init__(self, smoothing=0.3, newline=False):
        self.smoothing = smoothing
        self.newline = newline
        self.times = OrderedDict()
        self.will_print = OrderedDict()
        self.reset()

    def reset(self):
        now = time.time()
        self.start = now
        self.last_time = now
        for name in self.will_print:
            self.will_print[name] = False

    def update(self, name='default'):
        now = time.time()
        dt = now - self.last_time
        if name in self.times:
            dt = self.smoothing * dt + (1 - self.smoothing) * self.times[name]
        self.times[name] = dt
        self.will_print[name] = True
        self.last_time = now

    def print(self, text='Timer'):
        total = 0.
        print('[{}]'.format(text), end=' ')
        for key in self.times:
            val = self.times[key]
            if self.will_print[key]:
                print('%s=%.3f' % (key, val), end=' ')
                total += val
        print('total=%.3f sec {%.1f FPS}' % (total, 1./total), end=' ')
        if self.newline:
            print(flush=True)
        else:
            print(end='\r', flush=True)
        self.reset()


class Frame:
    def __init__(self, image:Image, frame_data:dict, matches:list, confidences:list):
        self.image = image
        self.frame_data = {k: v for k, v in frame_data.items()}
        self.kpts = [cv2.KeyPoint(x, y, 4) for x, y in self.frame_data['keypoints'][0].cpu().numpy()]
        self.matches = matches
        self.confidences = confidences
        self.curr_image_index = -1
        self.prev_image_index = -1

class FramePair:
    def __init__(self, train:int, query:int, matches:list, confidences:list):
        self.train_image_index = train
        self.query_image_index = query
        self.matches = matches
        self.confidences = confidences

class SuperGlueMatch:
    def __init__(self, vehicle:Vehicle=None, model_path:str=None, debug:bool=False, logger=Log(), verbose:bool=False):
        self.verbose = verbose
        self.camera_name = None # camera name
        self.tracks_history = [] # list of tracks history
        self.frames = {} # dict of frames which the key is the image object ID
        self.prev_img_id = None # previous image object ID
        self.curr_img_id = None # current image object ID
        self.curr_gray = None # current grayscale image
        self.vis = None # visualization of tracks on image
        self.debug = True  # debug # debug flag
        self.vehicle = vehicle # vehicle object
        self.reject_dist = 2 # reject distance
        self.logger = logger

        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.logger.info('Running inference on device \"{}\"'.format(self.device))
        config = {
            'superpoint': {
                'nms_radius': 4,
                'keypoint_threshold': 0.005,
                'max_keypoints': -1
            },
            'superglue': {
                'weights': 'outdoor',
                'sinkhorn_iterations': 20,
                'match_threshold': 0.2,
                'path': os.path.join(model_path, "superglue_outdoor.pth")
            }
        }

        self.superpoint = SuperPoint(config.get('superpoint', {})).eval().to(self.device)
        self.superglue = SuperGlue(config.get('superglue', {})).eval().to(self.device)
        self.keys = ['image', 'keypoints', 'scores', 'descriptors', 'image_size']
        self.last_data = None
        self.timer = AverageTimer()

        self.camera_pairs = get_camera_pairs(self.vehicle.camera_names if self.vehicle is not None else None)
        self.frame_pairs = []

    def superglue_matching(self):
        for camera_name in self.vehicle.camera_names:
            self.superglue_matching_single_camera(camera_name)

        # Match images from multiple cameras in a single frame
        self.superglue_matching_multi_camera()

    def superglue_matching_multi_camera(self):
        if self.vehicle.camera_names is not None and len(self.vehicle.camera_names) == 1:
            return
        self.logger.info("Matching multi-view images of single frame by SuperGlue")
        clusters = self.vehicle.cluster_images_by_time()
        clusters = Vehicle.filter_clusters(clusters)
        imagess = list(clusters.values())
        times = list(clusters.keys())
        match_lists = map(self.superglue_matching_single_cluster, imagess, times)
        for match_list in match_lists:
            self.frame_pairs.append(match_list)

    @torch.no_grad()
    def superglue_matching_single_cluster(self, images:list, time:str):
        self.logger.info(f'Starting SuperGlue matching for cluster at time: {time}, images: {len(images)}')
        camera_name2index_dict = {image.camera_name: i for i, image in enumerate(images)}

        if self.debug:
            vis, toplefts = arrange_images(images)

        frame_pairs = []

        for cam_pair in self.camera_pairs:
            if cam_pair[0] not in camera_name2index_dict or cam_pair[1] not in camera_name2index_dict:
                continue
            cam0_index = camera_name2index_dict[cam_pair[0]]
            cam1_index = camera_name2index_dict[cam_pair[1]]
            image0 = images[cam0_index]
            image1 = images[cam1_index]
            self.logger.info(f'Matching images: {image0.time} and {image1.time}')

            img0_id = id(image0)
            img1_id = id(image1)
            if img0_id not in self.frames:
                img0_data = self.detect_keypoints(image0)
                self.frames[img0_id] = Frame(image0, img0_data, [], [])
            if img1_id not in self.frames:
                img1_data = self.detect_keypoints(image1)
                self.frames[img1_id] = Frame(image1, img1_data, [], [])

            img0_data = self.frames[img0_id].frame_data
            img1_data = self.frames[img1_id].frame_data
            data = {}
            data.update({k+'0': img0_data[k] for k in self.keys})
            data.update({k+'1': img1_data[k] for k in self.keys})
            for k in data:
                if isinstance(data[k], (list, tuple)):
                    data[k] = torch.stack(data[k])
            self.timer.update('data')

            pred = self.superglue(data)
            matches = pred['matches0'][0].cpu().numpy()
            confidences = pred['matching_scores0'][0].cpu().numpy()
            self.timer.update('superglue')

            # Filter valid matches
            valid = (matches > -1)
            valid_indices1 = np.where(valid)[0]
            valid_indices2 = matches[valid]

            # Create matches in bulk
            matches21 = [cv2.DMatch(i1, i0, 0) for i1, i0 in zip(valid_indices2, valid_indices1)]
            confidences21 = confidences[valid_indices1]

            # No geometric filtering
            frame_pairs.append(FramePair(images[cam0_index].image_index, images[cam1_index].image_index, matches21, confidences21))

            if self.debug:
                kp_pairs21 = [(self.frames[img1_id].kpts[match.queryIdx], self.frames[img0_id].kpts[match.trainIdx]) for match in frame_pairs[-1].matches]
                draw_matches(vis, kp_pairs21, toplefts[cam0_index], toplefts[cam1_index])
                self.timer.update('viz')

        if self.debug:
            save_dir = get_output_dir(f"temp/superglue_multi_cam")
            stem = '{}'.format(time)
            out_file = str(Path(save_dir, stem + '.jpg'))
            # self.logger.info('Writing image to {}\n'.format(out_file))
            cv2.imwrite(out_file, vis)
        self.timer.print()

        return frame_pairs

    def superglue_matching_single_camera(self, camera_name:str):
        self.last_data = None
        self.prev_img_id = None
        self.camera_name = camera_name
        # Get the image list from the vehicle object if the image list is empty
        image_list = self.vehicle.get_images_by_camera_name(self.camera_name)
        self.logger.info(f'Starting SuperGlue matching for camera: {self.camera_name}, images: {len(image_list)}')
        # Loop through all images in the list
        for image in image_list:
            self.match_image(image)

    @torch.no_grad()
    def match_image(self, image:Image):
        matches = None
        confidences = None
        self.timer.update('data')

        curr_data = self.detect_keypoints(image)
        self.timer.update('superpoint')

        if self.last_data:
            data = {**self.last_data, **curr_data}
            data.update({k+'1': data[k] for k in self.keys})
            for k in data:
                if isinstance(data[k], (list, tuple)):
                    data[k] = torch.stack(data[k])
            self.timer.update('data_merge')

            pred = self.superglue(data)
            matches = pred['matches0'][0].cpu().numpy()
            confidences = pred['matching_scores0'][0].cpu().numpy()
            self.timer.update('superglue')

        self.last_data = {k+'0': curr_data[k] for k in self.keys}

        self.curr_img_id = id(image)
        self.frames[self.curr_img_id] = Frame(image, curr_data,
                                              matches if matches is not None else [],
                                              confidences if confidences is not None else [])
        self.filter_matches()
        self.timer.update('filter')

        # Visualize the matches
        self.visualize()
        self.timer.update('viz')
        self.timer.print()

        self.prev_img_id = self.curr_img_id

    @torch.no_grad()
    def detect_keypoints(self, image:Image):
        # Prepare the image for tracking
        self.prepare_image(image)
        frame_tensor = frame2tensor(self.curr_gray, device=self.device)
        curr_data = self.superpoint({'image': frame_tensor})
        curr_data = self.filter_keypoints(image, curr_data)
        curr_data['image'] = frame_tensor
        curr_data['image_size'] = np.array([self.curr_gray.shape[0], self.curr_gray.shape[1]])
        return curr_data

    def prepare_image(self, image):
        # # Create a mixed mask, which is a mixed version of both the mod mask and the track mask,
        # # from the mod mask of the image
        # mixed_mask = image.mod_mask.copy()
        # mixed_mask = (mixed_mask > 0).astype(np.float32)
        # Get the image data
        frame = image.image
        # Check if the image is a color image
        if frame.ndim == 3 and frame.shape[2] == 3:
            # Convert the image to grayscale
            self.curr_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            # Copy the color image
            if self.debug:
                self.vis = frame.copy()
        else:
            # Copy the grayscale image
            self.curr_gray = frame.copy()
            # Convert the grayscale image to a color image for visualization
            if self.debug:
                self.vis = cv2.cvtColor(self.curr_gray, cv2.COLOR_GRAY2BGR)

        # self.curr_gray = self.curr_gray * mixed_mask

    def filter_keypoints(self, image, keypoint_data):
        # Keypoint filtering
        kpts_data = {k: keypoint_data[k][0].cpu().numpy() for k in self.keys if k in keypoint_data}

        kpts = kpts_data['keypoints']
        valid_flags = image.mod_mask[kpts[:, 1].astype(int), kpts[:, 0].astype(int)] != 0
        kpts_data = {k: np.take(v, np.where(valid_flags)[0], axis=(1 if v.ndim > 1 and v.shape[1] == len(valid_flags) else 0))
                     for k, v in kpts_data.items()}
        kpts_data = {k: [torch.from_numpy(v).to(self.device)] for k, v in kpts_data.items()}

        return kpts_data

    def filter_matches(self):
        # Match filtering (when at least two frames exist)
        if len(self.frames) >= 2 and self.prev_img_id is not None:
            prev_frame, curr_frame = self.frames[self.prev_img_id], self.frames[self.curr_img_id]
            # Ensure org_matches is an integer array
            org_matches = np.array(curr_frame.matches, dtype=np.int32)

            # Filter valid matches
            valid_matches = (org_matches > -1)
            valid_indices = np.where(valid_matches)[0]
            valid_mm = org_matches[valid_matches]

            # Create matches in bulk
            curr_frame.matches = [cv2.DMatch(mm, ii, 0) for mm, ii in zip(valid_mm, valid_indices)]
            curr_frame.confidences = curr_frame.confidences[valid_indices]
            num_matches = len(curr_frame.matches)

            # Geometric constraint filtering
            kpts1 = prev_frame.kpts
            kpts2 = curr_frame.kpts
            matches = curr_frame.matches
            if len(matches) == 0:
                self.logger.info('No matches after filtering, size = 0')
                return

            pts1 = np.array([kpts1[match.trainIdx].pt for match in matches])
            pts2 = np.array([kpts2[match.queryIdx].pt for match in matches])
            cam = self.vehicle.get_virtual_camera(curr_frame.image)
            pts1_un = cam.undistort_points(pts1)
            pts2_un = cam.undistort_points(pts2)
            filter_mode = "and" if self.camera_name == "cam0" else "or"
            valid_matches = filter_matches_geo(pts2_un, pts1_un, matches, filter_mode)
            valid_keys = [match.queryIdx*65536+match.trainIdx for match in valid_matches]
            valid_flags = [match.queryIdx*65536+match.trainIdx in valid_keys for match in matches]
            curr_frame.confidences = curr_frame.confidences[valid_flags]
            curr_frame.matches = valid_matches
            curr_frame.prev_image_index = prev_frame.image.image_index
            curr_frame.curr_image_index = curr_frame.image.image_index
            self.logger.info(f"Initial matches: {org_matches.shape[0]}, after keypoint and match filtering: {num_matches}, after geometric filtering: {len(valid_matches)}\n")

    def visualize(self):
        if len(self.frames) > 0:
            prev_frame = self.frames[self.prev_img_id] if self.prev_img_id is not None else None
            curr_frame = self.frames[self.curr_img_id]
            kpts0 = [[kpt.pt[0], kpt.pt[1]] for kpt in prev_frame.kpts] if prev_frame is not None else []
            kpts1 = [[kpt.pt[0], kpt.pt[1]] for kpt in curr_frame.kpts]

            mkpts0 = [kpts0[m.trainIdx] for m in curr_frame.matches] if prev_frame is not None else []
            mkpts1 = [kpts1[m.queryIdx] for m in curr_frame.matches]

            color = cm.jet(curr_frame.confidences)
            text = [
                'SuperGlue',
                'Keypoints: {}:{}'.format(len(kpts0), len(kpts1)),
                'Matches: {}'.format(len(mkpts0)),
            ]
            k_thresh = self.superpoint.config['keypoint_threshold']
            m_thresh = self.superglue.config['match_threshold']
            small_text = [
                'Keypoint threshold: {:.4f}'.format(k_thresh),
                'Match threshold: {:.2f}'.format(m_thresh),
                'Image: {}:{}'.format(prev_frame.image.time if prev_frame is not None else '', curr_frame.image.time),
            ]
            out = self.make_matching_plot_fast(
                kpts0, kpts1, mkpts0, mkpts1, color, text,
                path=None, show_keypoints=True, small_text=small_text)
            save_dir = get_output_dir(f"temp/superglue_{self.camera_name}")
            stem = '{}'.format(curr_frame.image.time)
            out_file = str(Path(save_dir, stem + '.jpg'))
            # self.logger.info('Writing image to {}\n'.format(out_file))
            cv2.imwrite(out_file, out)

    def make_matching_plot_fast(self, kpts0, kpts1, mkpts0,
                                mkpts1, color, text, path=None,
                                show_keypoints=False, margin=10,
                                opencv_display=False, opencv_title='',
                                small_text=[]):
        H, W, C = self.vis.shape

        if show_keypoints:
            kpts0, kpts1 = np.round(kpts0).astype(int), np.round(kpts1).astype(int)
            white = (255, 255, 255)
            black = (0, 0, 0)
            # for x, y in kpts0:
            #     cv2.circle(self.vis, (x, y), 2, black, -1, lineType=cv2.LINE_AA)
            #     cv2.circle(self.vis, (x, y), 1, white, -1, lineType=cv2.LINE_AA)
            for x, y in kpts1:
                cv2.circle(self.vis, (x, y), 2, black, -1, lineType=cv2.LINE_AA)
                cv2.circle(self.vis, (x, y), 1, white, -1, lineType=cv2.LINE_AA)

        if mkpts0:
            mkpts0, mkpts1 = np.round(mkpts0).astype(int), np.round(mkpts1).astype(int)
            color = (np.array(color[:, :3])*255).astype(int)[:, ::-1]
            for (x0, y0), (x1, y1), c in zip(mkpts0, mkpts1, color):
                c = c.tolist()
                cv2.line(self.vis, (x0, y0), (x1, y1), color=c, thickness=1, lineType=cv2.LINE_AA)
                # display line end-points as circles
                # cv2.circle(self.vis, (x0, y0), 2, c, -1, lineType=cv2.LINE_AA)
                cv2.circle(self.vis, (x1, y1), 2, c, -1, lineType=cv2.LINE_AA)

        # Scale factor for consistent visualization across scales.
        sc = min(H / 640., 2.0)

        # Big text.
        Ht = int(30 * sc)  # text height
        txt_color_fg = (255, 255, 255)
        txt_color_bg = (0, 0, 0)
        for i, t in enumerate(text):
            cv2.putText(self.vis, t, (int(8*sc), Ht*(i+1)), cv2.FONT_HERSHEY_DUPLEX,
                        1.0*sc, txt_color_bg, 2, cv2.LINE_AA)
            cv2.putText(self.vis, t, (int(8*sc), Ht*(i+1)), cv2.FONT_HERSHEY_DUPLEX,
                        1.0*sc, txt_color_fg, 1, cv2.LINE_AA)

        # Small text.
        Ht = int(18 * sc)  # text height
        for i, t in enumerate(reversed(small_text)):
            cv2.putText(self.vis, t, (int(8*sc), int(H-Ht*(i+.6))), cv2.FONT_HERSHEY_DUPLEX,
                        0.5*sc, txt_color_bg, 2, cv2.LINE_AA)
            cv2.putText(self.vis, t, (int(8*sc), int(H-Ht*(i+.6))), cv2.FONT_HERSHEY_DUPLEX,
                        0.5*sc, txt_color_fg, 1, cv2.LINE_AA)

        if path is not None:
            cv2.imwrite(str(path), self.vis)

        if opencv_display:
            cv2.imshow(opencv_title, self.vis)
            cv2.waitKey(1)

        return self.vis
