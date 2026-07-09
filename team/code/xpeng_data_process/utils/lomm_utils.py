import os
import json
import numpy as np
import cv2
import shutil
from scipy import ndimage

def gen_static_obj_segs(clip_path, generate_segs_id_vis = False):
    # corr_2d_3d = json.load(open(os.path.join(clip_path, "2d_3d_corr_filtered.json"), "r"))
    corr_2d_3d = json.load(open(os.path.join(clip_path, "2d_3d_corr.json"), "r"))
    anno_for_train = json.load(open(os.path.join(clip_path, "annotation_for_train.json"), "r"))
    timestamp2slice = json.load(open(os.path.join(clip_path, "timestamp2slice.json"), "r"))
    instance_segs_id_path = os.path.join(clip_path, "instance_segs_id")
    segs_vision_static_path = os.path.join(clip_path, "segs_vision_static")
    
    if os.path.exists(instance_segs_id_path):
        if os.path.exists(segs_vision_static_path):
            shutil.rmtree(segs_vision_static_path)
        shutil.copytree(instance_segs_id_path, segs_vision_static_path, dirs_exist_ok=True)
        print(f"[INFO] Copied instance_segs_id to segs_vision_static")
    
    if not os.path.exists(segs_vision_static_path):
        print(f"[WARNING] segs_vision_static directory not found at {segs_vision_static_path}")
        return

    frames_sorted = sorted(anno_for_train.get("frames", []), key=lambda x: x.get("timestamp", ""))
    
    gid_size_sum = {}  # {gid: {"x": sum_x, "y": sum_y, "z": sum_z, "count": count}}
    for frame in frames_sorted:
        for obj in frame.get("objects", []):
            gid = str(obj.get("gid", ""))
            size = obj.get("size", [])
            if gid not in gid_size_sum:
                gid_size_sum[gid] = {"x": 0.0, "y": 0.0, "z": 0.0, "count": 0}
            gid_size_sum[gid]["x"] += float(size[0])
            gid_size_sum[gid]["y"] += float(size[1])
            gid_size_sum[gid]["z"] += float(size[2])
            gid_size_sum[gid]["count"] += 1
    
    gid_avg_size = {}  # {gid: {"x": avg_x, "y": avg_y, "z": avg_z}}
    for gid, size_data in gid_size_sum.items():
        count = size_data["count"]
        if count > 0:
            gid_avg_size[gid] = {
                "x": size_data["x"] / count,
                "y": size_data["y"] / count,
                "z": size_data["z"] / count
            }

    dxnet2lomm = {}
    for dxnet_id, cam_dict in corr_2d_3d.items():
        # 如果平均size超过6m则跳过
        if dxnet_id in gid_avg_size:
            avg_size = gid_avg_size[dxnet_id]
            if avg_size["x"] > 6.0 or avg_size["y"] > 6.0 or avg_size["z"] > 6.0:
                continue
        
        if dxnet_id not in dxnet2lomm:
            dxnet2lomm[dxnet_id] = []
        added_combinations = set()
        for cam_id, cam_list in cam_dict.items():
            if cam_id == "cam0":
                continue
            if cam_list and len(cam_list) > 0:
                # 根据iou大小选取iou最大的ins_id
                best_item = max(cam_list, key=lambda x: x.get("iou_info", {}).get("iou", 0.0))
                ins_id = best_item["ins_id"]
                combination = (ins_id, cam_id)
                if combination not in added_combinations:
                    dxnet2lomm[dxnet_id].append({"lomm_id": ins_id, "cam_id": cam_id})
                    added_combinations.add(combination)

    # save dxnet2lomm to json
    with open(os.path.join(clip_path, "dxnet2lomm.json"), "w") as f:
        json.dump(dxnet2lomm, f, indent=4)
    
    num_frames = len(frames_sorted)
    
    gid_frame_moving_status = {}  # {gid: [is_moving_frame1, is_moving_frame2, ...]}
    
    all_gids = set()
    for frame in frames_sorted:
        for obj in frame.get("objects", []):
            gid = str(obj.get("gid", ""))
            all_gids.add(gid)
    
    for gid in all_gids:
        gid_frame_moving_status[gid] = [False] * num_frames
    
    for frame_idx, frame in enumerate(frames_sorted):
        for obj in frame.get("objects", []):
            gid = str(obj.get("gid", ""))
            is_moving = obj.get("is_moving", True) == True
            gid_frame_moving_status[gid][frame_idx] = is_moving
    
    gid_has_consecutive_moving = {}  # {gid: bool}
    for gid, moving_status_list in gid_frame_moving_status.items():
        max_consecutive = 0
        current_consecutive = 0
        for is_moving in moving_status_list:
            if is_moving:
                current_consecutive += 1
                max_consecutive = max(max_consecutive, current_consecutive)
            else:
                current_consecutive = 0
        gid_has_consecutive_moving[gid] = (max_consecutive >= 5)
    
    processed_files = {}
    static_obstacle_id = 100 # 临时标记值，表示静态障碍物
    
    for frame in anno_for_train.get("frames", []):
        timestamp = str(frame.get("timestamp", ""))
        if not timestamp:
            continue
        
        for obj in frame.get("objects", []):
            # 删除静态障碍物的抖动帧
            if obj.get("is_moving", True) == True:
                continue
            gid = str(obj.get("gid", ""))
            if gid in dxnet2lomm:
                lomm_info_list = dxnet2lomm[gid]
                for lomm_info in lomm_info_list:
                    cam_id = lomm_info["cam_id"]
                    if cam_id == "cam0":
                        continue
                    lomm_id = lomm_info["lomm_id"]
                    
                    if timestamp not in timestamp2slice:
                        print(f"[WARNING] Timestamp {timestamp} not found in timestamp2slice.json")
                        continue
                    
                    slice_id = timestamp2slice[timestamp]
                    instance_id_filename = f"slice{slice_id}_{cam_id}.npy"
                    instance_id_filepath = os.path.join(segs_vision_static_path, instance_id_filename)
                    
                    if not os.path.exists(instance_id_filepath):
                        print(f"[WARNING] Instance seg file not found: {instance_id_filepath}")
                        continue
                    
                    try:
                        if instance_id_filepath not in processed_files:
                            instance_id_label_original = np.load(instance_id_filepath)
                            instance_id_label_marked = instance_id_label_original.copy()
                            processed_files[instance_id_filepath] = (instance_id_label_original, instance_id_label_marked)
                        else:
                            instance_id_label_original, instance_id_label_marked = processed_files[instance_id_filepath]
                        
                        mask = (instance_id_label_original == lomm_id)
                        instance_id_label_marked[mask] = static_obstacle_id
                        
                    except Exception as e:
                        print(f"[ERROR] Failed to process {instance_id_filepath}: {e}")
    
    processed_count = 0
    if generate_segs_id_vis:
        instance_segs_id_vis_path = os.path.join(clip_path, "instance_segs_id_vis")
        os.makedirs(instance_segs_id_vis_path, exist_ok=True)
    
    static_obs_ids_by_cam = {}  # {cam_id: set of gids}
    
    lomm_cam_to_gids = {}  # {(lomm_id, cam_id): [gid1, gid2, ...]}
    for gid, lomm_info_list in dxnet2lomm.items():
        for lomm_info in lomm_info_list:
            lomm_id = lomm_info["lomm_id"]
            cam_id = lomm_info["cam_id"]
            if cam_id == "cam0":
                continue
            key = (lomm_id, cam_id)
            if key not in lomm_cam_to_gids:
                lomm_cam_to_gids[key] = []
            lomm_cam_to_gids[key].append(gid)
    
    for instance_id_filepath, (instance_id_label_original, instance_id_label_marked) in processed_files.items():
        try:
            filename = os.path.basename(instance_id_filepath)
            if '_' in filename:
                cam_id = filename.split('_')[-1].replace('.npy', '')
            else:
                cam_id = None
                print(f"[WARNING] Cannot extract cam_id from filename: {filename}")
                continue
            
            if cam_id == "cam0":
                continue
            
            instance_id_label_new = np.zeros_like(instance_id_label_marked)
            mask_static = (instance_id_label_marked == static_obstacle_id)
            
            unique_lomm_ids = np.unique(instance_id_label_original[mask_static])
            for lomm_id in unique_lomm_ids:
                if lomm_id == 0: # 跳过背景
                    continue
                key = (lomm_id, cam_id)
                if key in lomm_cam_to_gids:
                    # 当所有对应dxnet_id都有连续移动，才删除对应的lomm_id
                    gids = lomm_cam_to_gids[key]
                    all_have_consecutive_moving = True
                    static_gids = []
                    for gid in gids:
                        has_consecutive_moving = gid_has_consecutive_moving.get(gid, False)
                        if not has_consecutive_moving:
                            static_gids.append(gid)
                            all_have_consecutive_moving = False
                    
                    if all_have_consecutive_moving:
                        mask_lomm_id = (instance_id_label_original == lomm_id)
                        mask_static = mask_static & (~mask_lomm_id)
                    else:
                        if cam_id not in static_obs_ids_by_cam:
                            static_obs_ids_by_cam[cam_id] = set()
                        for gid in static_gids:
                            static_obs_ids_by_cam[cam_id].add(gid)
            
            instance_id_label_new[mask_static] = static_obstacle_id
            
            np.save(instance_id_filepath, instance_id_label_new)
            
            if generate_segs_id_vis:
                # 当前帧有静态障碍物时才生成可视化
                if np.any(instance_id_label_new > 0):
                    vis_filename = os.path.basename(instance_id_filepath).replace('.npy', '_vis.png')
                    vis_filepath = os.path.join(instance_segs_id_vis_path, vis_filename)
                    visualize_instance_id_label(instance_id_label_new, vis_filepath)
            
            processed_count += 1
        except Exception as e:
            print(f"[ERROR] Failed to finalize {instance_id_filepath}: {e}")
    
    static_obs_ids_dict = {}
    for cam_id, gid_set in static_obs_ids_by_cam.items():
        static_obs_ids_dict[cam_id] = sorted(list(gid_set))
    
    static_obs_ids_filepath = os.path.join(clip_path, "static_obs_ids.json")
    with open(static_obs_ids_filepath, "w") as f:
        json.dump(static_obs_ids_dict, f, indent=4)
    print(f"[INFO] Saved static obstacle IDs by camera to {static_obs_ids_filepath}")
    
    print(f"[INFO] Generated static objects segmentation: processed {processed_count} files")

def visualize_instance_id_label(instance_id_label, output_path):
    h, w = instance_id_label.shape
    vis_image = np.zeros((h, w, 3), dtype=np.uint8)
    
    unique_ids = np.unique(instance_id_label)
    unique_ids = unique_ids[unique_ids > 0]
    
    if len(unique_ids) == 0:
        cv2.imwrite(output_path, vis_image)
        return
    
    for instance_id in unique_ids:
        hue = int((instance_id * 137.508) % 180)
        color_hsv = np.uint8([[[hue, 255, 255]]])
        color_bgr = cv2.cvtColor(color_hsv, cv2.COLOR_HSV2BGR)[0][0]
        
        mask = (instance_id_label == instance_id)
        vis_image[mask] = color_bgr
        
        if np.any(mask):
            center_y, center_x = ndimage.center_of_mass(mask.astype(float))
            center_y, center_x = int(center_y), int(center_x)
            
            center_y = max(0, min(h - 1, center_y))
            center_x = max(0, min(w - 1, center_x))
            
            text = str(int(instance_id))
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.6
            thickness = 2
            
            (text_width, text_height), baseline = cv2.getTextSize(text, font, font_scale, thickness)
            
            cv2.rectangle(vis_image,
                        (center_x - text_width // 2 - 2, center_y - text_height - baseline - 2),
                        (center_x + text_width // 2 + 2, center_y + baseline + 2),
                        (255, 255, 255), -1)
            
            cv2.putText(vis_image, text,
                        (center_x - text_width // 2, center_y),
                        font, font_scale, (0, 0, 0), thickness, cv2.LINE_AA)
    
    cv2.imwrite(output_path, vis_image)