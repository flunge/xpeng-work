import cv2
import numpy as np

def bbox_to_corner3d(bbox: np.ndarray):
    x1, y1, z1 = bbox[0]
    x2, y2, z2 = bbox[1]
    corners = np.array(
        [
            [x1, y1, z1],
            [x2, y1, z1],
            [x1, y2, z1],
            [x2, y2, z1],
            [x1, y1, z2],
            [x2, y1, z2],
            [x1, y2, z2],
            [x2, y2, z2],
        ],
        dtype=np.float64,
    )
    return corners

def quaternion_to_rotation_matrix_wxyz(q: np.ndarray) -> np.ndarray:
    # q = [w, x, y, z]
    w, x, y, z = q
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    R = np.array(
        [
            [1 - 2 * (yy + zz), 2 * (xy - wz), 2 * (xz + wy)],
            [2 * (xy + wz), 1 - 2 * (xx + zz), 2 * (yz - wx)],
            [2 * (xz - wy), 2 * (yz + wx), 1 - 2 * (xx + yy)],
        ],
        dtype=np.float64,
    )
    return R

def compute_3d_proj(bbox_info, cam_info, img_w, img_h):
    K = cam_info["K"]
    R_world2cam = cam_info["R_world2cam"]
    t_world2cam = cam_info["t_world2cam"]

    translation = np.array(bbox_info["translation"])
    size = bbox_info["size"]
    rotation = bbox_info["rotation"]  # wxyz

    length, width, height = size
    bbox_local = np.array([[-length * 0.5, -width * 0.5, -height * 0.5], [length * 0.5, width * 0.5, height * 0.5]], dtype=np.float64)
    corners_local = bbox_to_corner3d(bbox_local)

    # rotate to world/ego and translate
    R_obj = quaternion_to_rotation_matrix_wxyz(rotation)
    corners_3d = (R_obj @ corners_local.T).T + translation.reshape(1, 3)

    cam_pts = corners_3d @ R_world2cam.T + t_world2cam.reshape(1, 3)
    if np.all(cam_pts[:, 2] <= 0):
        return np.zeros((img_h, img_w), dtype=np.uint8), None

    cam_pts[:, 2] = np.clip(cam_pts[:, 2], 1e-3, None)
    proj = cam_pts @ K.T
    uv = proj[:, :2] / proj[:, 2:]
    uv = np.round(uv).astype(np.int32)
    proj_mask = np.zeros((img_h, img_w), dtype=np.uint8)
    faces = [
        [0, 1, 3, 2, 0],
        [4, 5, 7, 6, 5],
        [0, 1, 5, 4, 0],
        [2, 3, 7, 6, 2],
        [0, 2, 6, 4, 0],
        [1, 3, 7, 5, 1],
    ]
    for f in faces:
        poly = uv[f]
        cv2.fillPoly(proj_mask, [poly], 1)

    contours, _ = cv2.findContours(proj_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return proj_mask, None
    cnt = max(contours, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(cnt)
    return proj_mask, (x, y, w, h)

def compute_iou(proj_mask, instance_mask):
    intersection = np.logical_and(proj_mask, instance_mask).sum()
    union = np.logical_or(proj_mask, instance_mask).sum()
    iou = intersection / union if union > 0 else 0.0
    return iou

def overlay_binary_masks_on_image(img_vision, A, B, output_path, alpha=0.5):
    A = A.astype(np.uint8)
    B = B.astype(np.uint8)
    img_vision = img_vision.astype(np.float32)

    H, W = A.shape
    overlay = np.zeros((H, W, 3), dtype=np.float32)
    
    overlay[A == 1] = [0, 0, 255]
    overlay[B == 1] = [255, 0, 0]
    overlap = np.logical_and(A == 1, B == 1)
    overlay[overlap] = [255, 0, 255]

    mask_nonzero = np.any(overlay != 0, axis=-1, keepdims=True).astype(np.float32)
    blended = img_vision * (1 - alpha * mask_nonzero) + overlay * (alpha * mask_nonzero)
    
    blended_uint8 = blended.astype(np.uint8)
    success = cv2.imwrite(output_path, blended_uint8)
    return blended_uint8