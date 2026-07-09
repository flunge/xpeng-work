import os
import sys
import json
from tqdm import tqdm

from data_mining import file_utils           


def is_calib_json_valid(calib_info, cam_list, lidar_list):
    if (not calib_info["local_pose"] or not calib_info["global_pose"] or 
        len(calib_info["local_pose"]) != len(calib_info["global_pose"])):
        print(f"[ERROR] localpose len: {len(calib_info['local_pose'])}, globalpose len: {len(calib_info['global_pose'])}")
        return False
    
    slice_num = len(calib_info["local_pose"])
    if slice_num < 20:
        print(f"[WARNING] slice num: {slice_num} too few!")
        return False

    for cam_name in cam_list:
        if not calib_info[cam_name]:
            print(f"[ERROR] fail to check {cam_name} in calib.json")
            return False    
    
    for lidar_name in lidar_list:
        if not calib_info[lidar_name]:
            print(f"[ERROR] fail to check {lidar_name} in calib.json")
            return False    
    return True

def is_image_exist(image_path, slice_name, cam_list):
    for cam_name in cam_list:
        image_name = slice_name + "_" + cam_name + ".png"
        image_name = os.path.join(image_path, image_name)
        if not os.path.exists(image_name):
                return False, image_name
    return True, ""                

def check_clip_data(dataset_path, clip_id, config):
    clip_path = os.path.join(dataset_path, clip_id)
    calib_path = os.path.join(clip_path, "calib.json")
    local_pose_topic_path = os.path.join(clip_path, "LocalPoseTopic.json")
    metadata_path = os.path.join(clip_path, "metadata.json")
    image_path = os.path.join(clip_path, "image")
    seg_mask_path = os.path.join(clip_path, "seg_mask")
    
    clip_check_info = []
    
    # check path exist
    for path in [clip_path, local_pose_topic_path, calib_path, metadata_path, image_path, seg_mask_path]:
        if not os.path.exists(path):
            clip_check_info.append(f"fail to check path exist: {path}") 
            return clip_check_info     
    
    # check image num
    image_num = file_utils.get_file_count(image_path)
    seg_mask_num = file_utils.get_file_count(seg_mask_path)
    if image_num  != seg_mask_num:
        clip_check_info.append(f"fail to check image num equal: {image_num}, {seg_mask_num}")      
        return clip_check_info
    
    # check calib
    cam_list = config.get("cam_list", ["cam0", "cam2", "cam3", "cam4", "cam5", "cam6", "cam7"])
    lidar_list = config.get("lidar_list", [])

    calib_info = json.load(open(calib_path, 'r'))
    if not is_calib_json_valid(calib_info, cam_list, lidar_list):
        clip_check_info.append(f"fail to check calib json file")
        return clip_check_info
    
    all_local_pose = calib_info["local_pose"]
    for slice_name in all_local_pose.keys():
        for path in [image_path, seg_mask_path]:
            check_flag, failed_image_name = is_image_exist(path, slice_name, cam_list)
            if not check_flag:
                clip_check_info.append(f"fail to check image data: {failed_image_name}")
    return clip_check_info

def get_clip_id(clip_record):
    clip_metadata = clip_record.get_metadata()
    return clip_metadata['id']

def get_clip_poi_ids(clip_record):
    clip_metadata = clip_record.get_metadata()
    return clip_metadata['poi_ids']

def get_clip_global_pose(clip_record): 
    global_pose_buffer = dict()
    try:
        all_local_pose = json.loads(clip_record.get_stream("LocalPoseTopic", "json"))
        for local_pose in all_local_pose:
            global_pose_dict = local_pose["global_pose"]
            global_pose_ts = global_pose_dict["time_stamp"]["nsec"]
            global_pose_buffer[global_pose_ts] = [global_pose_dict['world_pose']['lng'], global_pose_dict['world_pose']['lat']]
    except Exception as e:
        clip_id = get_clip_id(clip_record)
        print(f'!!!!!!!!!!!!!!!failed clip id: {clip_id}, local pose extraction Warning: {e}')
        return dict()  
    global_pose_buffer = dict(sorted(global_pose_buffer.items(), key=lambda x: x[0]))   
    return global_pose_buffer        

if __name__ == '__main__':
    dataset_name = "sxnet_3d_benchmark"
    dataset_path = '/workspace/liuzy10@xiaopeng.com/adc-perception-sdcp/3d_data_intersection_17'
    # dataset_path = '/workspace/liuzy10@xiaopeng.com/adc-perception-sdcp/new_data_collection_vision_based'

    folder_names = file_utils.get_folder_names(dataset_path)
    print(f"dataset clips num: {len(folder_names)}")

    dataset_check_info = {}
    for clip_id in tqdm(folder_names):
        clip_check_info = check_clip_data(dataset_path, clip_id)
        if len(clip_check_info) > 0: 
            dataset_check_info[clip_id] = clip_check_info

    if len(dataset_check_info) <= 0:
        print(f"all data is perfect!")
        sys.exit()
    print(f"dataset_check_info: {dataset_check_info}")
    
    fix_clip_ids = list(dataset_check_info.keys())
    print(f"need to fix clips num: {len(fix_clip_ids)}, clip_id: {fix_clip_ids}")
