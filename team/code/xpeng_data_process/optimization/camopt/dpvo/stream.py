import os
import json
import cv2
import numpy as np
from multiprocessing import Process, Queue
from pathlib import Path
from itertools import chain

def image_stream(queue, imagedir, calib, stride, skip=0):
    """ image generator """
    import traceback as _tb
    import faulthandler
    import sys
    faulthandler.enable(file=sys.stderr, all_threads=True)
    _dummy_intrinsics = np.array([0.0, 0.0, 0.0, 0.0])
    _dummy_image = np.zeros((16, 16, 3), dtype=np.uint8)
    try:
        calib = np.loadtxt(calib, delimiter=" ")
        fx, fy, cx, cy = calib[:4]

        K = np.eye(3)
        K[0,0] = fx
        K[0,2] = cx
        K[1,1] = fy
        K[1,2] = cy

        img_exts = ["*.png", "*.jpeg", "*.jpg"]
        image_list = sorted(chain.from_iterable(Path(imagedir).glob(e) for e in img_exts))[skip::stride]
        if not os.path.exists(imagedir):
            print(f"[image_stream][ERROR] imagedir does not exist: {imagedir}")
            queue.put((-1, _dummy_image, _dummy_intrinsics))
            return

        print(f"[image_stream] Found {len(image_list)} images in {imagedir}")
        for t, imfile in enumerate(image_list):
            image = cv2.imread(str(imfile))
            if image is None:
                print(f"[image_stream][ERROR] Failed to read image: {imfile}, skipping.")
                continue
            if len(calib) > 4:
                image = cv2.undistort(image, K, calib[4:])

            intrinsics = np.array([fx, fy, cx, cy])
            h, w, _ = image.shape
            image = image[:h-h%16, :w-w%16]

            queue.put((t, image, intrinsics))

        queue.put((-1, image, intrinsics))
        print(f"[image_stream] Finished processing all {len(image_list)} images.")
    except Exception as e:
        print(f"[image_stream][FATAL] Exception in image_stream subprocess: {type(e).__name__}: {e}")
        print(f"[image_stream][FATAL] Traceback:\n{_tb.format_exc()}")
        try:
            queue.put((-1, _dummy_image, _dummy_intrinsics))
        except Exception:
            pass


def video_stream(queue, imagedir, calib, stride, skip=0):
    """ video generator """
    import traceback as _tb
    import faulthandler
    import sys
    faulthandler.enable(file=sys.stderr, all_threads=True)
    _dummy_intrinsics = np.array([0.0, 0.0, 0.0, 0.0])
    _dummy_image = np.zeros((16, 16, 3), dtype=np.uint8)
    try:
        calib = np.loadtxt(calib, delimiter=" ")
        fx, fy, cx, cy = calib[:4]

        K = np.eye(3)
        K[0,0] = fx
        K[0,2] = cx
        K[1,1] = fy
        K[1,2] = cy

        if not os.path.exists(imagedir):
            print(f"[video_stream][ERROR] video file does not exist: {imagedir}")
            queue.put((-1, _dummy_image, _dummy_intrinsics))
            return

        cap = cv2.VideoCapture(imagedir)
        t = 0

        for _ in range(skip):
            ret, image = cap.read()

        while True:
            # Capture frame-by-frame
            for _ in range(stride):
                ret, image = cap.read()
                # if frame is read correctly ret is True
                if not ret:
                    break

            if not ret:
                break

            if len(calib) > 4:
                image = cv2.undistort(image, K, calib[4:])

            image = cv2.resize(image, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
            h, w, _ = image.shape
            image = image[:h-h%16, :w-w%16]

            intrinsics = np.array([fx*.5, fy*.5, cx*.5, cy*.5])
            queue.put((t, image, intrinsics))

            t += 1

        queue.put((-1, image, intrinsics))
        cap.release()
        print(f"[video_stream] Finished processing {t} frames from {imagedir}.")
    except Exception as e:
        print(f"[video_stream][FATAL] Exception in video_stream subprocess: {type(e).__name__}: {e}")
        print(f"[video_stream][FATAL] Traceback:\n{_tb.format_exc()}")
        try:
            queue.put((-1, _dummy_image, _dummy_intrinsics))
        except Exception:
            pass


def cam0_stream(queue, clip_path, transform_name, stride, skip=0):
    """ image generator """
    import traceback as _tb
    import faulthandler
    import sys
    # Enable faulthandler so SIGSEGV/SIGABRT/SIGFPE will dump Python traceback to stderr
    faulthandler.enable(file=sys.stderr, all_threads=True)

    _dummy_intrinsics = np.array([0.0, 0.0, 0.0, 0.0])
    _dummy_mask = np.zeros((16, 16), dtype=bool)
    _dummy_image = np.zeros((16, 16, 3), dtype=np.uint8)
    try:
        transform_path = os.path.join(clip_path, transform_name)
        print(f"[cam0_stream] Loading transform from: {transform_path}")
        transform_json = json.load(open(transform_path, "r"))
        cam0_intrinsics_K_3x3 = np.array(transform_json["sensor_params"]["cam0"]["camera_intrinsic"])
        imagedir = os.path.join(clip_path, "dyn_mask")
        fx, fy = cam0_intrinsics_K_3x3[0,0], cam0_intrinsics_K_3x3[1,1]
        cx, cy = cam0_intrinsics_K_3x3[0,2], cam0_intrinsics_K_3x3[1,2]

        img_exts = ["*.png", "*.jpeg", "*.jpg"]
        image_list = sorted(chain.from_iterable(Path(imagedir).glob(e) for e in img_exts))[skip::stride]
        if not os.path.exists(imagedir):
            print(f"[cam0_stream][ERROR] imagedir does not exist: {imagedir}")
            queue.put((-1, _dummy_image, _dummy_intrinsics, _dummy_mask))
            return
        if len(image_list) == 0:
            print(f"[cam0_stream][ERROR] No images found in: {imagedir}")
            queue.put((-1, _dummy_image, _dummy_intrinsics, _dummy_mask))
            return

        print(f"[cam0_stream] Found {len(image_list)} images in {imagedir}")
        for t, imfile in enumerate(image_list):
            image = cv2.imread(str(imfile))
            if image is None:
                print(f"[cam0_stream][ERROR] Failed to read image: {imfile}, skipping.")
                continue
            intrinsics = np.array([fx, fy, cx, cy])
            h, w, _ = image.shape
            image = image[:h-h%16, :w-w%16]
            mask = np.all(image > 0, axis=-1)
            queue.put((t, image, intrinsics, mask))

        queue.put((-1, image, intrinsics, mask))
        print(f"[cam0_stream] Finished processing all {len(image_list)} images.")
    except Exception as e:
        print(f"[cam0_stream][FATAL] Exception in cam0_stream subprocess: {type(e).__name__}: {e}")
        print(f"[cam0_stream][FATAL] Traceback:\n{_tb.format_exc()}")
        # Always send termination signal so the main process won't hang
        try:
            queue.put((-1, _dummy_image, _dummy_intrinsics, _dummy_mask))
        except Exception:
            pass
