#
# Copyright (C) 2023, Inria
# GRAPHDECO research group, https://team.inria.fr/graphdeco
# All rights reserved.
#
# This software is free for non-commercial, research and evaluation use 
# under the terms of the LICENSE.md file.
#
# For inquiries contact  george.drettakis@inria.fr
#

from errno import EEXIST
from os import makedirs, path
import os
import shutil


def mkdir_p(folder_path):
    # Creates a directory. equivalent to using mkdir -p on the command line
    try:
        makedirs(folder_path)
    except OSError as exc: # Python >2.5
        if exc.errno == EEXIST and path.isdir(folder_path):
            pass
        else:
            raise

def searchForMaxIteration(folder):
    saved_iters = [int(fname.split('.')[0].split("_")[1]) for fname in os.listdir(folder) if 'iteration' in fname]
    return max(saved_iters)


def cleanup_ipy_in_folders(folder_path):
    folder_path_to_remove = []
    file_path_to_remove = []
    for root, folders, files in os.walk(folder_path):
        for folder in folders:
            if ".ipynb" in folder:
                folder_path_to_remove.append(os.path.join(root, folder))
        
        for file in files:
            if "-checkpoint." in file:
                file_path = os.path.join(root, file)
                file_path_to_remove.append(file_path)
    
    for f in file_path_to_remove:
        print("[INFO] Cleanup file: ", f)
        os.remove(f)

    for f in folder_path_to_remove:
        print("[INFO] Cleanup folder: ", f)
        shutil.rmtree(f)


def cleanup_clip_folder(clip_path):
    image_dir = os.path.join(clip_path, "images")
    mask_dir = os.path.join(clip_path, "masks")
    mask_obj_dir = os.path.join(clip_path, "masks_obj")
    pcd_dir = os.path.join(clip_path, "pcd")
    for folder in [image_dir, mask_dir, mask_obj_dir, pcd_dir]:
        if os.path.exists(folder):
            cleanup_ipy_in_folders(folder)