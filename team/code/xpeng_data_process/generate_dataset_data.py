import io
import os
import cv2
import json
import numpy as np
import re
# import pcl

from PIL import Image
from copy import deepcopy

from data_mining import dataset_utils
from data_mining import clip_utils
from utils.general_utils import quaternion_matrix, lookup_pose, pq_pose_to_4x4, get_ecef2enu
from utils.calib_utils import get_pose_buffer_from_localpose_topic, get_pose_buffer_from_mflocalpose_topic
from utils.annotation_utils import check_validity_of_clip
from utils.misc import parser_autolabel_json


def get_current_pose(all_local_pose, slice_metadata):
    # find closest local pose
    tdiff = []
    for lp in all_local_pose:
        tdiff.append((lp["time_stamp"]["nsec"] - slice_metadata["frame_origin_time"]) / 1e9)
    min_idx = np.argmin(np.abs(tdiff))
    if tdiff[min_idx] > 0.1:
        raise Exception("large time diff between camera and local pose")
    lp = all_local_pose[min_idx]

    # transform local pose to 4*4 matrix
    p = lp["smooth_pose_info"]["local_pose"]["p"]
    q = lp["smooth_pose_info"]["local_pose"]["q"]
    rot_q = [q["w"], q["x"], q["y"], q["z"]]
    curr_local_pose = quaternion_matrix(rot_q)
    pos = [p[x] for x in p]
    curr_local_pose[:3, 3] = pos

    p = lp["global_pose"]["world_pose_in_ecef"]["p"]
    q = lp["global_pose"]["world_pose_in_ecef"]["q"]
    rot_q = [q["w"], q["x"], q["y"], q["z"]]
    curr_global_pose = quaternion_matrix(rot_q)
    pos = [p[x] for x in p]
    curr_global_pose[:3, 3] = pos

    return curr_local_pose, curr_global_pose


def get_camera_img(slice, cam, config):
    ### Images in the official dataset are saved in local path
    if config["dataset_name"] == "vision_bases_gt":
        jpg_path = slice[cam].get_jpg_cache_path()
        img = cv2.imread(jpg_path)
    else:
        if slice[cam].has_jpg():
            img = slice[cam].get_jpg()
        elif slice[cam].has_png():
            img = slice[cam].get_png()
        else:
            raise Exception(f'Fail to parse slice image!')
        img = io.BytesIO(img)
        img = np.array(Image.open(img))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    return img

def get_slice_timestamp(slice):
    try: 
        slice_timestamp = slice["cam2"].get_metadata()["frame_origin_time"]
        slice_id = slice["cam2"].get_metadata()["id"]
    except Exception as e:
        raise UserWarning(f"[ERROR] Fail to get slice timestamp or id. slice {slice}")
    return slice_timestamp, slice_id

def is_slice_valid(slice, cam_list, lidar_list, autolabel_json, strict_valid=False):
    for cam in cam_list:
        if cam not in slice or slice[cam] is None:
            return False
    if lidar_list:
        if ("lidar0" in lidar_list or "lidar1" in lidar_list) and (slice['lidar_repack2'] is None or not slice['lidar_repack2'].has_raw()):
            return False
        if "lidar2" in lidar_list and (slice['lidar_repack'] is None or not slice['lidar_repack'].has_raw()):
            return False    
    
    ### use slice only if the timestamp in autolabel
    if strict_valid and len(autolabel_json) > 0:
        slice_timestamp, _ = get_slice_timestamp(slice)
        if str(slice_timestamp) in autolabel_json:
            return True
        else:
            return False
    return True

def is_xminer_data(clip_metadata):
    if 'xminer' in clip_metadata["scenario"]:
        return True
    return False    

def get_calibration_info(loader, vehicle_name, cam_list):
    print(f"Use applicable calibration")
    calibration_info = loader.get_calibration_info(vehicle_name, 1) 
    if not calibration_info:
        raise Exception("[ERROR] applicable calibration is empty")
    for cam in cam_list:
        if not calibration_info[cam]['intrinsic'] or not calibration_info[cam]['extrinsic']:
            raise Exception(f"[ERROR] fail to get applicable calibration intrinsic or extrinsic for {cam}")    
    return calibration_info


def get_local_pose_data(clip_record):
    clip_metadata = clip_record.get_metadata()
    if is_xminer_data(clip_metadata):
        print(f"INFO: get local pose from XminerLocalPoseTopic, clip_id:{clip_record.get_id()}")
        local_pose_topic = clip_record.get_stream('XminerLocalPoseTopic', 'json')
        local_pose = json.loads(local_pose_topic)
    else:
        print(f"INFO: get local pose from LocalPoseTopic, clip_id:{clip_record.get_id()}")
        local_pose_topic = clip_record.get_stream('LocalPoseTopic', 'json')
        local_pose = json.loads(local_pose_topic)
    return local_pose  


def get_pose_buffer(clip_record, ecef2enu):
    use_mf_localpose = False
    clip_id = clip_record.get_id()
    try:
        all_local_pose = get_local_pose_data(clip_record)
    except Exception as e:
        print(f"ERROR: Fail to get local pose data, exception: {e}, clip_id: {clip_id}")
        print(f"WARNING: XminerLocalPoseTopic is empty, fallback to MfLocalPoseTopic, clip_id:{clip_id}")
        local_pose_topic = clip_record.get_stream('MfLocalPoseTopic', 'json')
        mf_localpose = json.loads(local_pose_topic)
        use_mf_localpose = True
    
    clip_id = clip_record.get_id()
    if not use_mf_localpose:
        local_pose_buffer, global_pose_buffer = get_pose_buffer_from_localpose_topic(
            all_local_pose, ecef2enu, clip_id
        )
    else:
        local_pose_buffer, global_pose_buffer, all_local_pose = get_pose_buffer_from_mflocalpose_topic(
            mf_localpose, ecef2enu, clip_id
        )

    return local_pose_buffer, global_pose_buffer, all_local_pose


def fetch_autodata_json(clip_record, save_path):
    user_label_name = 'gxodips_autodata100'
    try:
        all_local_pose = clip_record.get_user_label(user_label_name, suffix='.json', 
            use_cache_only=False, read_content=True, is_binary=False)
        all_local_pose = json.loads(all_local_pose)
        all_local_pose = all_local_pose["cam_pose_list"] + all_local_pose["lidar_pose_list"]
    except Exception as e:
        print(f"ERROR: Fail to get local pose data, exception: {e}, clip_id: {clip_record.get_id()}")
        raise Exception(f'Fail to get local pose data, exception: {e}')
    return all_local_pose


def fetch_posemapping_json(clip_record, clip_path, pose_type):
    save_path = os.path.join(clip_path, "pose_mapping")
    os.makedirs(save_path, exist_ok=True)

    calib_mapping = clip_record.get_user_label(pose_type, suffix=".calib.json")
    pose_mapping = clip_record.get_user_label(pose_type, suffix=".pose.json")
    try:
        calib_mapping = json.loads(calib_mapping)
        json.dump(calib_mapping, open(os.path.join(save_path, f"calib_mapping.json"), 'w+'), indent=4)
    except Exception as e:
        print(f"[ERROR] Fail to load calib_mapping: {e}, clip_id: {clip_record.get_id()}")
    else:
        print("[INFO] calib_mapping dumped successfully")
    try:
        pose_mapping = json.loads(pose_mapping)
        json.dump(pose_mapping, open(os.path.join(save_path, f"pose_mapping.json"), 'w+'), indent=4)
    except Exception as e:
        print(f"[ERROR] Fail to load pose_mapping: {e}, clip_id: {clip_record.get_id()}")
    else:
        print("[INFO] pose_mapping dumped successfully")
    assert pose_mapping['pose_qa'], f"[ERROR] pose_mapping QA not pass, clip_id: {clip_record.get_id()}"
    all_local_pose = pose_mapping["cam_pose_list"] + pose_mapping["lidar_pose_list"]
    return all_local_pose


def get_lidarslam_pose_buffer(clip_record, clip_path, pose_type):
    local_pose_buffer = dict()
    global_pose_buffer = dict()

    all_local_pose = fetch_posemapping_json(clip_record, clip_path, pose_type)
    for local_pose in all_local_pose:
        local_pose_ts = local_pose["time_stamp"]["nsec"]
        # adapt two poses format from dataloader
        if "smooth_pose_info" in local_pose:
            pose = pq_pose_to_4x4(local_pose["smooth_pose_info"]["local_pose"])
        elif "smooth_pose" in local_pose:
            error_code = local_pose["smooth_pose"].get("error_code", 0)
            if error_code != 0:
                print(f"ERROR: smooth_pose error_code: {error_code}, clip_id: {clip_record.get_id()}")
                raise Exception(f"ERROR: smooth_pose error_code: {error_code}, clip_id: {clip_record.get_id()}")
            pose = pq_pose_to_4x4(local_pose["smooth_pose"]["pose"])
        else:
            print(f"ERROR: No smooth_pose_info/smooth_pose found, clip_id: {clip_record.get_id()}")
            raise Exception(f'No smooth_pose_info/smooth_pose found:\n{local_pose}')
        local_pose_buffer[local_pose_ts] = pose

        global_pose_dict = local_pose
        global_pose_ts = global_pose_dict["time_stamp"]["nsec"]
        if "smooth_pose_info" in global_pose_dict:
            pose = pq_pose_to_4x4(global_pose_dict["smooth_pose_info"]["local_pose"])
        elif "smooth_pose" in global_pose_dict:
            pose = pq_pose_to_4x4(global_pose_dict["smooth_pose"])
        else:
            print(f"ERROR: No global pose/world_pose_ecef found, clip_id: {clip_record.get_id()}")
            raise Exception(f'No global pose/world_pose_ecef found:\n{local_pose}')
        global_pose_buffer[global_pose_ts] = pose

    local_pose_buffer = dict(sorted(local_pose_buffer.items(), key=lambda x: x[0]))
    global_pose_buffer = dict(sorted(global_pose_buffer.items(), key=lambda x: x[0]))

    return local_pose_buffer, global_pose_buffer, all_local_pose


def dump_clip_image(valid_slices, calib_info, config, clip_path):
    cam_list = config["cam_list"]
    lidar_list = config["lidar_list"]
    cam_timestamps = {k: [] for k in cam_list}
    lidar_metas = {}
    images_path = os.path.join(clip_path, "images_origin")
    for cam_name in cam_list:
        os.makedirs(os.path.join(images_path, cam_name), exist_ok=True)
    
    if config['steps_controller']['source'] != "vision":
        pcd_path = os.path.join(clip_path, "pcd")
        pcd_timestamps_path = os.path.join(clip_path, "pcd_timestamps")
        os.makedirs(pcd_path, exist_ok=True)
        os.makedirs(pcd_timestamps_path, exist_ok=True)
        
    for slice_idx, slice in enumerate(valid_slices):
        slice_timestamp = slice["cam2"].get_metadata()["frame_origin_time"]
        
        # dump lidar pcd: pointxyzi
        if config['steps_controller']['source'] != "vision":
            lidar_type = 'lidar_repack2' if 'lidar0' in lidar_list and 'lidar1' in lidar_list else 'lidar_repack'
            lidar_frame_meta = slice[lidar_type].get_metadata()
            lidar_metas[slice_timestamp] = lidar_frame_meta

            pcd_name = f"{slice_timestamp}.pcd"
            lidar_raw = slice[lidar_type].get_raw()
            field_names = ("x", "y", "z", "r", "l", "t", "s")    ### s=0: left; s=1: right; s=2: rs128
            lidar_points = lidar_raw['data']
            if lidar_points.dtype.names:
                lidar_points = np.stack([lidar_points[name] for name in field_names], axis=1)
            else:
                lidar_points = lidar_points.reshape(-1, len(field_names))

            if 'lidar0' in lidar_list and 'lidar1' in lidar_list:
                lidar_points_left = lidar_points[np.where(lidar_points[:,-1] == 0)]
                lidar_points_right = lidar_points[np.where(lidar_points[:,-1] == 1)]
                lidar_points_left_timestamp = lidar_points_left[:, 5].copy()
                lidar_points_right_timestamp = lidar_points_right[:, 5].copy()
                lidar_points_left = lidar_points_left[:, :4]
                lidar_points_right = lidar_points_right[:, :4]
                rig2left = calib_info['lidar0']['extrinsic']['transformation_matrix']
                rig2right = calib_info['lidar1']['extrinsic']['transformation_matrix']
                left2right = rig2right @ np.linalg.inv(rig2left)
                origin_r = lidar_points_left[:,-1]
                lidar_points_left[:,-1] = 1
                lidar_points_left2right = (left2right @ lidar_points_left.T).T
                lidar_points_left2right[:,-1] = origin_r
                lidar_points = np.vstack([lidar_points_right, lidar_points_left2right])
                lidar_timestamp = np.hstack([lidar_points_right_timestamp, lidar_points_left_timestamp])
                # np.savez(os.path.join(pcd_timestamps_path, pcd_name.replace('.pcd', '.npy')), lidar_timestamp)
                ### use 'lidar1' extrinsic in the calib info in the late process!
            else:
                lidar_points = lidar_points[:, :4]

            # pointcloud = pcl.PointCloud_PointXYZI()
            # pointcloud.from_array(lidar_points.astype('float32'))
            # pcl.save(pointcloud, os.path.join(pcd_path, pcd_name))
            import open3d as o3d
            # 创建Open3D点云对象
            pointcloud = o3d.geometry.PointCloud()
            # 从numpy数组设置点云坐标（假设lidar_points是Nx3的numpy数组）
            pointcloud.points = o3d.utility.Vector3dVector(lidar_points[:, :3].astype('float32'))
            o3d.io.write_point_cloud(os.path.join(pcd_path, pcd_name), pointcloud)

        for cam_name in cam_list:
            img = get_camera_img(slice, cam_name, config)
            img_timestamp = slice[cam_name].get_metadata()["frame_origin_time"]
            cam_timestamps[cam_name].append(img_timestamp)
            img_name = f"{slice_timestamp}.png"
            cv2.imwrite(os.path.join(images_path, cam_name, img_name), img)

        print(f"[INFO] complete dumping images for: {slice_idx+1}/{len(valid_slices)} frames")
    json.dump(cam_timestamps, open(os.path.join(clip_path, "cam_timestamps.json"), 'w+'), indent=4)
    json.dump(lidar_metas, open(os.path.join(clip_path, "lidar_metas.json"), 'w+'), indent=4)


def dump_clip_localpose(clip_record, calib_info, local_pose_buffer, global_pose_buffer, config, clip_path):
    cam_list = config["cam_list"]
    lidar_list = config["lidar_list"]

    # lookup frame pose
    calib_info["local_pose"] = {}
    calib_info["global_pose"] = {}
    calib_info["slice_id"] = {}
    calib_info["id2timestamp"] = {}

    slices = clip_record.get_all_slices()
    valid_slices = []
    timestamp2slice = {}
    slice_idx_local = 0

    autolabel_json_path = os.path.join(config["clip_path"], "autolabel_json")
    autolabel_json = parser_autolabel_json(autolabel_json_path, select_box_info=["autolabel_box_info", "detection_box_info"])

    for idx, slice in enumerate(slices):
        if not is_slice_valid(slice, cam_list, lidar_list, autolabel_json, config["strict_valid"]):
            continue

        if idx % config["slice_interval"] != 0:
            continue

        slice_timestamp, slice_id = get_slice_timestamp(slice)

        curr_local_pose = lookup_pose(local_pose_buffer, slice_timestamp, 0.1)
        if curr_local_pose is None:
            local_pose_timestamps = list(local_pose_buffer.keys())
            print(f'[WARNING] fail to find local_pose by slice timestamp: {slice_timestamp * 1e-9}, '
                  f'pose_buffer timestamp: {local_pose_timestamps[0] * 1e-9} ~ {local_pose_timestamps[-1] * 1e-9}')
            continue

        curr_global_pose_enu = lookup_pose(global_pose_buffer, slice_timestamp, 0.5)
        if curr_global_pose_enu is None:
            global_pose_timestamps = list(global_pose_buffer.keys())
            print(f'[WARNING] fail to find global_pose by slice timestamp: {slice_timestamp * 1e-9}, '
                  f'pose_buffer timestamp: {global_pose_timestamps[0] * 1e-9} ~ {global_pose_timestamps[-1] * 1e-9}')
            continue

        calib_info["slice_id"][f"{slice_timestamp}"] = slice_id
        calib_info["local_pose"][f"{slice_timestamp}"] = curr_local_pose.tolist()
        calib_info["global_pose"][f"{slice_timestamp}"] = curr_global_pose_enu.tolist()
        calib_info["id2timestamp"][slice_idx_local] = slice_timestamp
        timestamp2slice[slice_timestamp] = slice_idx_local
        slice_idx_local += 1
        valid_slices.append(slice)
        
    # check clip data
    if not clip_utils.is_calib_json_valid(calib_info, cam_list, lidar_list):
        raise Exception(f'invalid calib info, clip id: {clip_record.get_id()}')

    timestamp2slice = dict(sorted(timestamp2slice.items()))
    json.dump(timestamp2slice, open(os.path.join(clip_path, "timestamp2slice.json"), 'w+'), indent=4)

    print(f"[INFO] Found slices: {len(slices)} in total")
    print(f"[INFO] complate get {len(valid_slices)} frames valid_slices")
    return valid_slices


def mv_avm_image(clip_path):
    """Move AVM camera folders (cam9/10/11/12) from images_origin to images_avm,
    then ensure they are deleted from images_origin."""
    import shutil
    avm_cams = ["cam9", "cam10", "cam11", "cam12"]
    src_root = os.path.join(clip_path, "images_origin")
    dst_root = os.path.join(clip_path, "images_avm")
    for cam in avm_cams:
        src = os.path.join(src_root, cam)
        if not os.path.exists(src):
            continue
        dst = os.path.join(dst_root, cam)
        os.makedirs(dst_root, exist_ok=True)
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.move(src, dst)
        print(f"[INFO] mv_avm_image: moved {src} -> {dst}")
        # ensure source is gone even if move behaved unexpectedly
        if os.path.exists(src):
            shutil.rmtree(src)
            print(f"[INFO] mv_avm_image: removed residual {src}")


def update_calib_info(calib_info, cam_list):
    # Convert our calib to standard format
    scale = 0.5  # since dataportal image is resized to 1/2
    for cam in cam_list:
        intrinsic = calib_info[cam]['intrinsic']
        if 'focal_length' in intrinsic:
            # Standard pinhole format
            intrinsic['focal_length'] = intrinsic['focal_length'] * 1000 / 4.2 * scale
            intrinsic['cx'] *= scale
            intrinsic['cy'] *= scale
        else:
            print(f"[WARNING] update_calib_info: unrecognized intrinsic format for {cam}, skipping scale")

def check_clip_exist(config):
    if os.path.exists(os.path.join(config['clip_path'], "metadata.json")):
        return True if not config["steps_controller"]["overwrite_dump"] else False
    else:
        return False

def dump_one_clip(config, clip_record, calib_info, pose_type, skip_images=False):
    clip_path = config["clip_path"]
    os.makedirs(clip_path, exist_ok=True)

    ### get local pose and calib info
    ecef2enu = get_ecef2enu()
    clip_metadata = clip_record.get_metadata()
    if config["steps_controller"]["source"] == "vision" or config["use_raw_localpose"]:
        print("[INFO] Use dds local pose buffer")
        local_pose_buffer, global_pose_buffer, local_pose_data = get_pose_buffer(clip_record, ecef2enu)
        print(f"[INFO] local_pose_buffer size: {len(local_pose_buffer)}, global_pose_buffer size: {len(global_pose_buffer)}")
    else:
        local_pose_buffer, global_pose_buffer, _ = get_lidarslam_pose_buffer(clip_record, clip_path, pose_type)
        local_pose_data = get_local_pose_data(clip_record)
        update_calib_info(calib_info, config["cam_list"])
        json.dump(calib_info, open(os.path.join(clip_path, "calib_origin.json"), 'w+'), indent=4)
        calib_info = json.load(open(os.path.join(clip_path, "pose_mapping/calib_mapping.json")))
        print("[INFO] Use optimized local pose buffer")

    update_calib_info(calib_info, config["cam_list"])
    # dynamic_xnet, static_xnet, mf_localpose, online_map =  get_dds_topic_data(clip_record)
    # dynamic_xnet, static_xnet, mf_localpose =  get_dds_topic_data(clip_record)

    ### dump calib info
    valid_slices = dump_clip_localpose(
        clip_record, calib_info, local_pose_buffer, global_pose_buffer, config, clip_path
    )
    json.dump(calib_info, open(os.path.join(clip_path, "calib.json"), 'w+'), indent=4)

    ### check validity of clip
    if config['steps_controller']['source'] != "vision":
        autolabel_json_path = os.path.join(clip_path, "autolabel_json")
        calib_path = os.path.join(clip_path, "calib.json")
        check_validity_of_clip(autolabel_json_path, calib_path)

    ### dump images and pcd (可跳过，后续仅对 filtered_clip_ids 再执行)
    if not skip_images:
        dump_clip_image(valid_slices, calib_info, config, clip_path)
        mv_avm_image(clip_path)

    ### dump meta files
    json.dump(local_pose_data, open(os.path.join(clip_path, "LocalPoseTopic.json"), 'w+'), indent=4)
    json.dump(clip_metadata, open(os.path.join(clip_path, "metadata.json"), 'w+'), indent=4)
    return True, config["clip_id"]


def dump_clip_images_only(config, clip_record, loader, pose_type="gxodips_posemapping"):
    """仅对单个 clip 执行 dump_clip_image（需已有 calib/timestamp2slice 等，用于在计算完 filtered_clip_ids 后补跑图片）."""
    clip_path = config["clip_path"]
    if not os.path.isdir(clip_path):
        return False
    calib_path = os.path.join(clip_path, "calib.json")
    if not os.path.isfile(calib_path):
        print(f"[WARNING] calib.json not found in {clip_path}, skip dump_clip_image for {config['clip_id']}")
        return False
    calib_info = json.load(open(calib_path))
    ecef2enu = get_ecef2enu()
    if config["steps_controller"]["source"] == "vision" or config["use_raw_localpose"]:
        local_pose_buffer, global_pose_buffer, _ = get_pose_buffer(clip_record, ecef2enu)
    else:
        local_pose_buffer, global_pose_buffer, _ = get_lidarslam_pose_buffer(clip_record, clip_path, pose_type)
        update_calib_info(calib_info, config["cam_list"])
    valid_slices = dump_clip_localpose(
        clip_record, calib_info, local_pose_buffer, global_pose_buffer, config, clip_path
    )
    json.dump(calib_info, open(calib_path, "w"), indent=4)
    dump_clip_image(valid_slices, calib_info, config, clip_path)
    return True


def fetch_canbus_topic(clip_record, config):
    enable_canbus_topic = config.get('enable_canbus_topic', False)
    if not enable_canbus_topic:
        return

    save_path = config['clip_path']
    os.makedirs(save_path, exist_ok=True)

    topics_config = config.get('canbus_topic_list', [])
    print(f"INFO: load topics: {topics_config}")

    for topic_name in topics_config:
        print(f"INFO: get {topic_name} from clip_id:{clip_record.get_id()}")
        topic_content = clip_record.get_stream(topic_name, 'json')
        if topic_content is None:
            raise ValueError(f"Fail to get {topic_name} from clip_id: {clip_record.get_id()}")
        if topic_name == "SensorFusionTopic":
            # 如果是字节串，则先解码为字符串
            if isinstance(topic_content, bytes):
                topic_content_str = topic_content.decode('utf-8', errors='ignore')
            else:
                topic_content_str = topic_content
            
            # 修复 JSON 格式问题
            topic_content_str = re.sub(
                r'"straddle_status"\s*:\s*}(?=\s*[\],])', 
                '"straddle_status": "xpilot::msg::sensor_fusion::StaticObjectStraddleStatus::POSITION_UNKNOWN"}', 
                topic_content_str
            )
            
            # 将处理后的字符串重新赋值
            topic_content = topic_content_str
        try:
            topic_data = json.loads(topic_content)
            file_path = os.path.join(save_path, f"{topic_name}.json")
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(topic_data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            raise RuntimeError(f"Failed to write {topic_name} to file, please check warm up canbus topic. clip_id: {clip_record.get_id()}") from e
    

def dump_clip_data(config, clip_records=None, dataloader=None):
    if check_clip_exist(config):
        print(f"[INFO]: clip {config['clip_id']} already exists in {config['clip_path']}, skip dump...")
        return True, config["clip_id"]

    if clip_records is None or dataloader is None:
        dataset_loader, clip_records = dataset_utils.get_dataset_clips(config)
    
    clip_record = clip_records[0]
    loader = dataloader or dataset_loader
    clip_path = config["clip_path"]
    os.makedirs(clip_path, exist_ok=True)
    clip_calib = process_before_dump(config, clip_record, loader)
    pose_type = "gxodips_posemapping"
    return dump_one_clip(config, clip_record, clip_calib, pose_type), [config['clip_id']]


def dump_subrun_data(config, clip_records=None, dataloader=None, dataset=None, skip_images=False, target_clip_ids=None):
    if dataset is not None:
        record_type = dataset_utils.get_record_type(config["record_type"])
        clip_records = dataset_utils.get_clip_records(dataset, record_type)
    elif clip_records is None or dataloader is None:
        dataset_loader, clip_records = dataset_utils.get_dataset_clips(config)
    else:
        clip_records = clip_records.get_clips()

    if isinstance(target_clip_ids, str):
        target_clip_ids = [target_clip_ids]

    if target_clip_ids is not None and len(target_clip_ids) > 0:
        target_set = set(list(target_clip_ids))
        original_count = len(clip_records)
        clip_records = [r for r in clip_records if r.get_id() in target_set]
        print(f"[INFO] Filtered clip_records by target_clip_ids: {original_count} -> {len(clip_records)} (target: {target_clip_ids})")

    config["subrun_path"] = os.path.join(config["root"], config["subrun_list"][0])
    print("======subrun_path======", config["subrun_path"])

    loader = dataloader or dataset_loader
    status = True
    clip_ids = []
    for clip_record in clip_records:
        config["clip_id"] = clip_record.get_id()
        config["clip_path"] = os.path.join(config["subrun_path"], config["clip_id"])
        clip_ids.append(config["clip_id"])
        if check_clip_exist(config):
            print(f"[INFO]: clip {config['clip_id']} already exists in {config['clip_path']}, skip dump...")
            continue
        clip_calib = process_before_dump(config, clip_record, loader)
        status &= dump_one_clip(config, clip_record, clip_calib, "gxodips_posemapping", skip_images=skip_images)[0]
    return status, clip_ids, clip_records, loader


def dump_source_data(config, clip_records=None, dataloader=None, dataset=None, start_time=None, end_time=None, target_clip_ids=None):
    if config["record_type"] == "SENSOR_CLIP_RECORD_TYPE":
        done, clip_ids = dump_clip_data(config, clip_records, dataloader)
        return done
    elif config["record_type"] == "SUBRUN_RECORD_TYPE":
        # 若指定时间范围：先不 dump 图片，只 dump 元数据以得到 timestamp2slice，再按 filtered_clip_ids 补跑图片
        skip_images = (start_time is not None and end_time is not None)
        done, clip_ids, clip_records, loader = dump_subrun_data(
            config, clip_records, dataloader, dataset, skip_images=skip_images, target_clip_ids=target_clip_ids
        )
        if done:
            # 根据 start_time 和 end_time 对 clip 进行时间范围筛选
            if start_time is not None and end_time is not None:
                start_time = int(start_time)
                end_time = int(end_time)
                filtered_clip_ids = []
                for clip_id in clip_ids:
                    timestamp2slice_path = os.path.join(config["subrun_path"], clip_id, "timestamp2slice.json")
                    if not os.path.exists(timestamp2slice_path):
                        print(f"[WARNING] timestamp2slice.json not found for clip {clip_id}, will be skipped")
                        continue
                    with open(timestamp2slice_path, "r") as f:
                        ts2slice_dict = json.load(f)
                    if not ts2slice_dict:
                        print(f"[WARNING] timestamp2slice.json empty for clip {clip_id}, will be skipped")
                        continue
                    timestamps = [int(ts) for ts in ts2slice_dict.keys()]
                    # 如果所有时间戳都不在区间内, 则跳过该clip
                    in_range = any(start_time <= ts <= end_time for ts in timestamps)
                    if in_range:
                        filtered_clip_ids.append(clip_id)
                    else:
                        print(f"[INFO] All timestamps of clip {clip_id} are not in the range [{start_time}, {end_time}], skipping merge for this clip.")

                if len(filtered_clip_ids) == 0:
                    print("Error, no valid clid ids")

                clip_id_to_record = {r.get_id(): r for r in clip_records}

                # 仅对 filtered_clip_ids 执行 dump_clip_image，在 merge 前完成
                if not config["use_h265_png"]:
                    print(f"[INFO] dump images for {len(filtered_clip_ids)} clips (h265_png: False)")
                    for clip_id in filtered_clip_ids:
                        if clip_id not in clip_id_to_record:
                            print(f"[WARNING] clip_record not found for {clip_id}, skip dump_clip_image")
                            continue
                        config["clip_id"] = clip_id
                        config["clip_path"] = os.path.join(config["subrun_path"], clip_id)
                        dump_clip_images_only(config, clip_id_to_record[clip_id], loader)

                # 只合并在起止时间内的数据（包括 JSON 与图片 <时间戳>.png）
                valid = dataset_utils.merge_subrun_clips(config, filtered_clip_ids, start_time=start_time, end_time=end_time, use_h265_png=config["use_h265_png"])
                print("[INFO] Subrun data merge success")
            else:
                valid = dataset_utils.merge_subrun_clips(config, clip_ids)
            ##### reset config paths
            config["clip_id"] = config["subrun_list"][0]
            config["clip_path"] = config["subrun_path"]
            config["autolabel_json_path"] = os.path.join(config["subrun_path"], "autolabel_json")
            return valid
        else:
            print("[INFO] Subrun data dump false")
            return False
    else:
        raise Exception(f"[ERROR] record_type: {config['record_type']} not supported")


def process_before_dump(config, clip_record, loader):
    save_dir = config["root"]
    os.makedirs(save_dir, exist_ok=True)
    
    # 拉取数据集配置的canbus topic，并转换为json
    fetch_canbus_topic(clip_record, config)
    
    print(f"[INFO]: root for saving outputs: {config['root']}")
    print(f"[INFO]: clip path: {config['clip_path']}")
    print(f"[INFO]: cam_list: {config['cam_list']}")
    print(f"[INFO]: clip_record id: {config['clip_id']}")
    if config['steps_controller']['source'] != "vision":
        print(f"[INFO]: lidar_list: {config['lidar_list']}")
    else:
        print(f"[INFO]: no lidar export for vision")

    # dump autolabel json
    if config['steps_controller']['source'] != "vision":
        save_path = os.path.join(config['clip_path'], "autolabel_json")
        autolabel_labels = ['gxodips_autolabelv680', 'gxodips_autolabelv660', 'END']
        for i in autolabel_labels:
            if i == 'END':
                raise Exception(f"[ERROR] Fail to dump autolabel json for {config['clip_id']}: no autolabel json found")
            catch_count = process_single_clip_autolabel(config['clip_id'], clip_record, save_path, i)
            if catch_count < 80:
                print(f"[WARNING] Try other autolabels....")
            else:
                print(f"[INFO] Autolabel json dumped successfully with label {i}, catch_count: {catch_count} frames")
                break
    
    # Load calibration info in advance to avoid passing unpickleable dataloader in joblib
    clip_metadata = clip_record.get_metadata()
    vehicle_name = clip_metadata["vehicle_name"]
    clip_calib = deepcopy(get_calibration_info(loader, vehicle_name, config["cam_list"]))
    return clip_calib


def process_single_clip_autolabel(clip_id, clip_record, save_path, label='gxodips_autolabelv680'):
    os.makedirs(save_path, exist_ok=True)
    miss_count = 0
    catch_count = 0
    assert len(clip_record.get_all_slices()) > 10, f"[ERROR] No slices found in clip {clip_id}"
    for slice_idx, slice_ in enumerate(clip_record.get_all_slices()):
        if 'cam2' not in slice_ or slice_['cam2'] is None:
            continue
        main_frame_data = slice_['cam2']
        frame_uuid = main_frame_data.get_id()
        
        label_context_bytes = main_frame_data.get_user_label(label, suffix='.json')
        if label_context_bytes is None:
            print(f'[WARNING] Lost JSON for {clip_id} {slice_idx + 1} ...')
            miss_count += 1
            continue
        
        catch_count += 1
        json_context = json.loads(label_context_bytes)
        with open(f"{save_path}/{frame_uuid}.json", "w") as f:
            json.dump(json_context, f, indent=4, sort_keys=True)

    if miss_count > 10:
        print(f'[WARNING] Clip {clip_id} missed {miss_count} frames') 
    else:
        print(f'[INFO] Clip {clip_id} catched {catch_count} frames')

    return catch_count


if __name__ == "__main__":
    from settings.config import make_default_settings, make_case_specific_settings
    clip_ids = {
        "c-3f04d57c-e50d-350d-92f0-c919a5712ac9": "low_quality_251125",
        "c-b685b9d7-8858-3072-8e2b-ee726c7254a0": "low_quality_251125",
        "c-2e015d7b-f593-3c8a-a623-d3218334b712": "low_quality_251125",
        "c-212889df-b09a-3393-af99-5697761649ee": "low_quality_251125"
    }
    for clip, folder in clip_ids.items():
        cfg = make_default_settings()
        cfg.dataset_name = "low_quality_251125"
        cfg.root = f"/workspace/yangxh7@xiaopeng.com/datasets/xpeng/{folder}"
        cfg.clip_id = clip
        cfg.steps_controller.source = "vision"  # "lidar+vision"
        cfg.use_raw_localpose = True
        cfg.enable_canbus_topic = True
        cfg.canbus_topic_list = ["DynamicXNetTopic", "StaticXNetTopic", "MfLocalPoseTopic"]
        cfg.ips_deploy = False
        cfg = make_case_specific_settings(cfg)
        dump_clip_data(cfg)