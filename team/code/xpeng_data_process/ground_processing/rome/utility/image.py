import cv2
import numpy as np
from scipy.ndimage import distance_transform_edt
from PIL import Image


def undistort_nearest(cv_image, k, d):
    mapx, mapy = cv2.initUndistortRectifyMap(k, d, None, k, (cv_image.shape[1], cv_image.shape[0]), cv2.CV_32FC1)
    cv_image_undistorted = cv2.remap(cv_image, mapx, mapy, cv2.INTER_NEAREST)
    return cv_image_undistorted


def label2mask(label):
    mask = np.ones_like(label)
    label_off_road = ((0 <= label) & (label <= 1)) | ((3 <= label) & (label <= 6)) | ((10 <= label) & (label <= 12)) \
        | ((16 <= label) & (label <= 22)) | ((25 <= label) & (label <= 28)) | ((30 <= label) & (label <= 40)) | (label >= 42)

    # dilate itereation 2 for moving objects
    label_movable = label >= 52
    kernel = np.ones((10, 10), dtype=np.uint8)
    label_movable = cv2.dilate(label_movable.astype(np.uint8), kernel, 2).astype(bool)

    label_off_road = label_off_road | label_movable
    mask[label_off_road] = 0
    label[~(mask.astype(bool))] = 64
    mask = mask.astype(np.float32)

    return mask, label


def remap_semantic(label):
    colors = np.ones((256, 1), dtype="uint8")
    colors *= 6          # background
    colors[7, :] = 1     # Lane marking
    colors[8, :] = 1
    colors[14, :] = 1
    colors[23, :] = 1
    colors[24, :] = 1
    colors[2, :] = 2     # curb
    colors[9, :] = 2     # curb cut
    colors[41, :] = 3    # Manhole
    colors[13, :] = 3    # road
    colors[15, :] = 4    # sidewalk
    colors[29, :] = 5    # terrain

    remaped_label = np.array(cv2.LUT(label.astype('uint8'), colors))
    return remaped_label


def render_semantic(label):
    colors = np.zeros((256, 1, 3), dtype='uint8')
    colors[0, :, :] = [0, 0, 0]         # mask
    colors[1, :, :] = [0, 0, 255]       # all lane
    colors[2, :, :] = [255, 0, 0]       # curb
    colors[3, :, :] = [211, 211, 211]   # road and manhole
    colors[4, :, :] = [0, 191, 255]     # sidewalk
    colors[5, :, :] = [152, 251, 152]   # terrain
    colors[6, :, :] = [157, 234, 50]    # background

    label_bgr = cv2.cvtColor(label.astype("uint8"), cv2.COLOR_GRAY2BGR)
    rendered_label = np.array(cv2.LUT(label_bgr, colors))
    return rendered_label


def blend_img_label(img, label):
    _, label = label2mask(label)
    label = remap_semantic(label)
    label = render_semantic(label)
    blend_img = cv2.addWeighted(img, 0.5, label, 0.5, 0)

    return blend_img


## Replace curb depth with the nearest non-curb depth value, to avoid the depth discontinuity
## which causes labeling projection distortion
## bev_seg should be RGB
def postprocess_curb_depth(bev_seg, bev_depth, curb_radius=10):
    curb_color = np.array([255, 0, 0], dtype=bev_seg.dtype)
    background_color = np.array([0, 0, 0], dtype=bev_seg.dtype)
    bev_curb = np.copy(bev_seg)
    bev_curb[np.any(bev_curb != curb_color, axis=2)] = background_color

    bev_curb_distances, indices = distance_transform_edt(np.all(bev_curb==curb_color, axis=2), return_indices=True)
    indices = indices.transpose(1, 2, 0)
    non_background = np.any(bev_seg[indices[..., 0], indices[..., 1]] != background_color, axis=2)
    bev_curb_distances[bev_curb_distances > curb_radius] = 0
    valid_indices = np.argwhere((bev_curb_distances > 0) * non_background)
    non_curb_indices = indices[valid_indices[:, 0], valid_indices[:, 1]]

    new_bev_depth = np.copy(bev_depth)
    new_bev_depth[valid_indices[:, 0], valid_indices[:, 1]] = new_bev_depth[non_curb_indices[:, 0], non_curb_indices[:, 1]]

    return new_bev_depth

def save_bev_depth_uint16(bev_depth, image_name):
    min_depth, max_depth = bev_depth.min(), bev_depth.max()
    depth_span = max_depth - min_depth
    if depth_span < 1e-6:
        bev_depth = np.zeros_like(bev_depth)
    else:
        bev_depth = ((bev_depth - min_depth) / depth_span) * 65535
    bev_depth = Image.fromarray(bev_depth.astype(np.uint16))
    bev_depth.save(image_name, 'PNG')

    return (min_depth, max_depth)