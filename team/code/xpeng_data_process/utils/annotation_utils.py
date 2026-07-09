import json
import math
import numpy as np
import os
from copy import deepcopy

from scipy.spatial.transform import Rotation as R

from utils.misc import parser_autolabel_json
from utils.misc import tranform_to_matrix
from utils.calib_utils import get_localpose_for_lidar_timestamp
from utils.calib_utils import get_localpose_based_on_the_first_frame
from utils.calib_utils import get_localpose_and_anchorpose_from_calib


def check_validity_of_clip(autolabel_json_path, calib_path):
    autolabel_json = parser_autolabel_json(autolabel_json_path, select_box_info=["autolabel_box_info", "detection_box_info"])
    localpose, anchorpose = get_localpose_and_anchorpose_from_calib(calib_path)
    get_annotation_json(autolabel_json, localpose, anchorpose)
    print(f"[INFO] Check validity of clip {os.path.dirname(calib_path)} passed.")
    return


def object_type_size_diff_threshold_map(obj_type):
    # 'car', 'sedan', 'suv', 'van', 'pickup', 'cart'
    # 'bus', 'truck', 'trailer_truck'
    # 'bicycle', 'tricycle', 'motorcycle'
    # 'person', 'animal', 'stroller', 'pushable_obj'
    threshold_map = {
        'car': (1.0, 0.5),
        'sedan': (1.0, 0.5),
        'suv': (1.0, 0.5),
        'van': (1.0, 0.5),
        'pickup': (1.0, 0.5),
        'cart': (1.0, 0.5),
        'bus': (2.0, 1.5),
        'truck': (2.0, 1.5),
        'trailer_truck': (2.0, 1.5),
        'bicycle': (0.7, 0.5),
        'tricycle': (0.7, 0.5),
        'motorcycle': (0.7, 0.5),
        'person': (0.7, 0.3),
        'animal': (0.7, 0.3),
        'stroller': (0.7, 0.5),
        'pushable_obj': (0.7, 0.5)
    }

    return threshold_map.get(obj_type, (1.0, 0.5))

    
def euler_to_quaternion(yaw, pitch, roll):
    """
    将欧拉角（弧度）转换为四元数
    """
    cy = math.cos(yaw * 0.5)
    sy = math.sin(yaw * 0.5)
    cp = math.cos(pitch * 0.5)
    sp = math.sin(pitch * 0.5)
    cr = math.cos(roll * 0.5)
    sr = math.sin(roll * 0.5)

    w = cr * cp * cy + sr * sp * sy
    x = sr * cp * cy - cr * sp * sy
    y = cr * sp * cy + sr * cp * sy
    z = cr * cp * sy - sr * sp * cy

    return [w, x, y, z]


def dynamic_object_mapping(obj_type):
    car_types = {'car', 'sedan', 'suv', 'van', 'pickup', 'cart'}
    truck_types = {'bus', 'truck', 'trailer_truck'}
    cyclist_types = {'bicycle', 'tricycle', 'motorcycle'}
    person_types = {'person', 'animal', 'stroller', 'pushable_obj'}
    static_types = {"cone", "barrel"}

    if obj_type in car_types:
        return 'car'
    elif obj_type in truck_types:
        return 'truck'
    elif obj_type in cyclist_types:
        return 'cyclist'
    elif obj_type in person_types:
        return 'pedestrian'
    elif obj_type in static_types:
        return "static"
    else:
        return 'car'
        

def apply_transformation(rig_translation, rig_rotation, rig2anchor):

    rotation_matrix = R.from_quat([rig_rotation[1], rig_rotation[2], rig_rotation[3], rig_rotation[0]])  # 转换四元数格式
    rot_o2rig = rotation_matrix.as_matrix()
    
    o2rig = np.eye(4)
    o2rig[:3, :3] = rot_o2rig
    o2rig[:3, 3] = rig_translation
    
    o2anchor = rig2anchor @ o2rig
    
    anchor_translation = o2anchor[:3, 3].tolist()
    
    rot_o2anchor = R.from_matrix(o2anchor[:3, :3])
    anchor_rotation_quat = rot_o2anchor.as_quat()
    
    anchor_rotation = [anchor_rotation_quat[3], anchor_rotation_quat[0], 
                    anchor_rotation_quat[1], anchor_rotation_quat[2]]
    
    return anchor_translation, anchor_rotation


def get_closest_frame_annotation_in_auto_label(annotation_in_auto_label, timestamp):
    if annotation_in_auto_label is None or "frames" not in annotation_in_auto_label:
        return None

    frames = annotation_in_auto_label["frames"]
    closest_frame = min(frames, key=lambda x: abs(int(x["timestamp"]) - int(timestamp)))
    return closest_frame


def get_all_frame_obj_ids(frame):
    if frame is None or "objects" not in frame:
        return set()
    return {obj["gid"] for obj in frame["objects"]}


def search_obj_in_frame_by_translation(frame, translation, size, obj_type, timestamp, origin_obj_id):
    if frame is None or "objects" not in frame:
        return None

    obj_type_thresholds = object_type_size_diff_threshold_map(obj_type)
    min_distance = float('inf')
    min_size_diff = float('inf')

    for obj in frame["objects"]:
        distance = np.linalg.norm(np.array(obj["translation"]) - np.array(translation))
        size_diff = np.linalg.norm(np.array(obj["size"]) - np.array(size))
        if distance < min_distance or (distance == min_distance and size_diff < min_size_diff):
            min_distance = distance
            min_size_diff = size_diff
        if distance < obj_type_thresholds[0]:  # Use type-specific translation threshold
            if size_diff < obj_type_thresholds[1]:  # Use type-specific size threshold
                # print(f"[INFO] Match {obj_type} object {origin_obj_id} at timestamp {timestamp} with distance {distance:.2f} and size diff {size_diff:.2f}")
                return obj

    # print(f"[INFO] No matching object {origin_obj_id} found for {obj_type} at timestamp {timestamp}. Closest distance: {min_distance:.2f}, size diff: {min_size_diff:.2f}")
    return None


def dynamic_xnet_to_annotation(dynamic_data, localpose_anchored, annotation_in_auto_label=None):
    annotation_dynamic_xnet = {
        "frames": []
    }

    dynamic_timestamps = list(dynamic_data.keys())
    localpose_anchored = {k: localpose_anchored[k] for k in sorted(localpose_anchored.keys())}
    obj_prev_pos = {}
    gid_dict_in_auto_label = {}
    closest_frame_annotation = None
    is_auto_label_used = annotation_in_auto_label is not None
    all_id_in_auto_label = set()

    for timestamp, rig2anchor in localpose_anchored.items():
        if not dynamic_timestamps:
            continue
        closest_dynamic_timestamp = min(dynamic_timestamps, 
                                    key=lambda x: abs(int(x) - int(timestamp)))
        
        frame_data = dynamic_data[closest_dynamic_timestamp]
        frame = {
            "timestamp": timestamp,
            "objects": []
        }

        if is_auto_label_used:
            closest_frame_annotation = get_closest_frame_annotation_in_auto_label(annotation_in_auto_label, timestamp)
            all_id_set = get_all_frame_obj_ids(closest_frame_annotation)
            all_id_in_auto_label.update(all_id_set)
            
        for obj in frame_data["objects"]:
            obj_id = obj["bbox"]["id"]
            position = obj["bbox"]["bbox3d"]["position"]["pt"]
            ypr = obj["bbox"]["bbox3d"]["ypr_angle"]["pt"]
            yaw, pitch, roll = ypr["x"], ypr["y"], ypr["z"]
            rig_rotation = euler_to_quaternion(yaw, pitch, roll)

            rig_translation = np.array([
                position["x"],
                position["y"],
                position["z"]
            ])
            anchor_translation, anchor_rotation = apply_transformation(rig_translation, rig_rotation, rig2anchor)
            
            dimension = obj["bbox"]["bbox3d"]["dimension"]["pt"]
            size = [
                dimension["x"],
                dimension["y"],
                dimension["z"]
            ]

            mod_type = obj["mod_type"]
            obj_type = mod_type.split("::")[-1]

            match_obj_id = None
            if closest_frame_annotation is not None and obj_id not in gid_dict_in_auto_label:
                matched_obj = search_obj_in_frame_by_translation(
                    closest_frame_annotation, anchor_translation, size, obj_type.lower(), timestamp, obj_id
                )
                if matched_obj is not None:
                    match_obj_id = matched_obj["gid"]
                    gid_dict_in_auto_label[obj_id] = match_obj_id

            is_moving = not obj["bbox"]["bbox3d"]["is_stationary"]["binary_bit"]

            if dynamic_object_mapping(obj_type.lower()) != "pedestrian" and \
                dynamic_object_mapping(obj_type.lower()) != "cyclist":
                if abs(obj["bbox"]["bbox3d"]["absolute_velocity"]["pt"]["x"]) < 0.05 and \
                    abs(obj["bbox"]["bbox3d"]["absolute_velocity"]["pt"]["y"]) < 0.05 and \
                    abs(obj["bbox"]["bbox3d"]["absolute_velocity"]["pt"]["z"]) < 0.05:
                    is_moving = False

                if is_moving and obj_id in obj_prev_pos:
                    delta_translation = np.linalg.norm(np.array(obj_prev_pos[obj_id]) - np.array(anchor_translation))
                    if delta_translation < 0.05:
                        is_moving = False
                obj_prev_pos[obj_id] = anchor_translation

            dynamic_obj = {
                "type": dynamic_object_mapping(obj_type.lower()),
                "gid": obj_id,
                "translation": anchor_translation,
                "size": size,
                "rotation": anchor_rotation,
                "is_moving": is_moving
            }
            
            frame["objects"].append(dynamic_obj)
        
        annotation_dynamic_xnet["frames"].append(frame)

    if is_auto_label_used:
        for frame in annotation_dynamic_xnet["frames"]:
            # replace the obj_id with matched gid in autolabel if exists
            for obj in frame["objects"]:
                origin_obj_id = obj["gid"]
                new_obj_id = gid_dict_in_auto_label.get(origin_obj_id, None)
            
                if new_obj_id is not None:
                    obj["gid"] = new_obj_id

    return annotation_dynamic_xnet


def get_annotation_json(autolabel_json, localpose, anchorpose, check=True):
    annotations = []
    localpose_valid = {}
    autolabel_json_sorted_by_timestamp = deepcopy(dict(sorted(autolabel_json.items())))
    for time_stamp, objs_info in autolabel_json_sorted_by_timestamp.items():
        if time_stamp in localpose:
            pose = localpose[time_stamp]
            localpose_valid[time_stamp] = pose
            for obj in objs_info["objects"]:
                obj_pose = tranform_to_matrix(obj["rotation"], obj["translation"])
                rig2anchor = np.linalg.inv(anchorpose) @ pose 
                obj2anchor = rig2anchor @ obj_pose
                obj["translation"] = obj2anchor[:3,3].tolist()
                r = R.from_matrix(obj2anchor[:3, :3])
                qvec = r.as_quat()
                obj["rotation"] = [qvec[3], qvec[0], qvec[1], qvec[2]]
            annotations.append({"timestamp": time_stamp, "objects": objs_info["objects"]})
    if check:
        assert len(annotations) == len(localpose), \
            "[ERROR] Some localpose timestamps are missing in annotations: " \
            f"len(annotations) {len(annotations)} != len(localpose) {len(localpose)}"
    ### obj coordinate is in the anchor coordinate
    return {"frames": annotations}, localpose_valid


def load_dynamic_xnet_data(input_file):
    if not os.path.exists(input_file):
        return None

    try:
        with open(input_file, 'r') as f:
            dynamic_data = json.load(f)
            if isinstance(dynamic_data, list):
                dynamic_data_dict = {}
                for item in dynamic_data:
                    if "time_stamp" in item and "nsec" in item["time_stamp"]:
                        timestamp_key = str(item["time_stamp"]["nsec"])
                        dynamic_data_dict[timestamp_key] = item
                dynamic_data = dynamic_data_dict
            return dynamic_data
    except Exception as e:
        print(f"[INFO] Failed to parse dynamic_xnet_topic file {input_file}: {e}")
        return None

        
def get_annotation_dynamic_xnet(clip_path, localpose):
    localpose_anchored, _ = get_localpose_based_on_the_first_frame(localpose)
    dynamic_xnet_path = os.path.join(clip_path, 'DynamicXNetTopic.json')
    dynamic_xnet_json = load_dynamic_xnet_data(dynamic_xnet_path)
    if dynamic_xnet_json is None:
        return None
    else:
        return dynamic_xnet_to_annotation(dynamic_xnet_json, localpose_anchored)


def get_annotation_autolabel(
    clip_path,
    use_raw_localpose,
    localpose,
    anchorpose,
    raise_on_smooth_pose_error=True,
):
    autolabel_json_path = os.path.join(clip_path, "autolabel_json")
    autolabel_json = parser_autolabel_json(
        autolabel_json_path, select_box_info=["autolabel_box_info", "detection_box_info"]
    )
    localpose_lidar = get_localpose_for_lidar_timestamp(
        clip_path,
        use_raw_localpose,
        raise_on_smooth_pose_error=raise_on_smooth_pose_error,
    )

    dynamic_xnet_path = os.path.join(clip_path, 'DynamicXNetTopic.json')
    dynamic_xnet_json = load_dynamic_xnet_data(dynamic_xnet_path)
    if dynamic_xnet_json is None:
        print(f"[INFO] No autolabel json needed for lidar clip {clip_path}!, start to autolabel")
        annotation_autolabel_box, _ = get_annotation_json(autolabel_json, localpose, anchorpose)
    else: 
        print(f"[INFO] Autolabel json loaded for lidar clip {clip_path}!, start to autolabel with dynamic xnet")
        localpose_anchored, _ = get_localpose_based_on_the_first_frame(localpose)
        annotation_in_auto_label, _ = get_annotation_json(autolabel_json, localpose, anchorpose)
        annotation_autolabel_box = dynamic_xnet_to_annotation(dynamic_xnet_json, localpose_anchored, annotation_in_auto_label)
    return annotation_autolabel_box
