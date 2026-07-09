import os
import json
import shutil

from xdata.dataset_v2.data_record import SENSOR_CLIP_RECORD_TYPE, SUBRUN_RECORD_TYPE, POI_SUBRUN_RECORD_TYPE
from xdata.dataset_v2.dataset_loader import DatasetLoader


def prepare_dataset(dataset_name, sql_filter="", slice_freq = 2, record_type=SENSOR_CLIP_RECORD_TYPE, cache_dir='/dataset'):
    config = {'data_dir': "/dataset/downloader_v2/repository", 
             'data_cache': cache_dir, 
             "allow_use_cache_only": False}
    loader = DatasetLoader(config)
    extra_filter={
        'aligned_sensors': ['cam0', 'cam2', 'cam3', 'cam4', 'cam5', 'cam6', 'cam7'],
        'key_frame_start': 1,
        'key_frame_frequency': slice_freq
    }
    dataset = loader.load_dataset_v2(
        dataset_name,
        sql_filter=sql_filter,
        extra_filter=extra_filter,
        record_type=record_type,
    )
    return loader, dataset  


def prepare_dataset_by_split(dataset_name, splits, sub, sql_filter = "", slice_freq = 2, record_type=SENSOR_CLIP_RECORD_TYPE, cache_dir='/dataset'):
    config = {  'data_dir': "/dataset/downloader_v2/repository",
                'data_cache': cache_dir,
                "allow_use_cache_only": False,
                "world_size": splits,
                "curr_rank": sub}
    loader = DatasetLoader(config)
    dataset = loader.load_dataset_v2(
        dataset_name,
        sql_filter=sql_filter,
        extra_filter={
            'aligned_sensors': ['cam0', 'cam2', 'cam3', 'cam4', 'cam5', 'cam6', 'cam7'],
            'key_frame_start': 1,
            'key_frame_frequency': slice_freq
        },
        world_size=splits,
        curr_rank=sub,
        record_type=record_type,
    )    
    return loader, dataset


def get_record_type(record_type_cfg):
    if record_type_cfg == "SENSOR_CLIP_RECORD_TYPE": 
        record_type = SENSOR_CLIP_RECORD_TYPE
    elif record_type_cfg == "SUBRUN_RECORD_TYPE": 
        record_type = SUBRUN_RECORD_TYPE
    elif record_type_cfg == "POI_SUBRUN_RECORD_TYPE":
        record_type = POI_SUBRUN_RECORD_TYPE
    else:
        raise Exception(f"ERROR: invalid record_type: {record_type_cfg}")
    return record_type


def get_clip_query(config):
    if "clip_id" not in config:
        return ""
    clip_id = config["clip_id"]
    clip_query = f"id == '{clip_id}'"
    return clip_query


def get_sql_filter(config, record_type):
    sql_filter = ""
    if "sql_filter" in config:
        sql_filter = config["sql_filter"]
    elif record_type == SENSOR_CLIP_RECORD_TYPE and "clip_id" in config:
        clip_id = config["clip_id"]
        sql_filter = f"id == '{clip_id}'"
    elif record_type == SUBRUN_RECORD_TYPE and "subrun_list" in config and len(config["subrun_list"]) > 0:
        sql_filter = ' OR '.join([f"id == '{subrun_id}'" for subrun_id in config["subrun_list"]])
    elif record_type == POI_SUBRUN_RECORD_TYPE and "poi_id" in config:
        sql_filter = f"id like '{config['poi_id']}'"
    return sql_filter


def get_clip_records(dataset, record_type):
    clip_records = []
    for idx in range(dataset.count()):
        record = dataset.get_record(idx)
        print(f"record type at idx {idx}: {type(record)}")
        if record_type == SENSOR_CLIP_RECORD_TYPE:
            clip_records.append(record) 
        elif record_type == SUBRUN_RECORD_TYPE:
            clips = record.get_clips()
            clip_records.extend(clips)
        elif record_type == POI_SUBRUN_RECORD_TYPE:
            subruns = record.get_subruns()
            for subrun in subruns:
                clips = subrun.get_clips()
                if clips is None or len(clips) == 0:
                    continue
                clip_records.extend(clips)
        else:
            raise Exception(f'record_type: {record_type} not supported')

    if len(clip_records) == 0:
        raise Exception("Error: No clip record found.")

    return clip_records


def get_dataset_clips(config):
    """
    Build dataset and return all clip records.
    """
    record_type = get_record_type(config["record_type"])
    cam_list = config["cam_list"]
    lidar_list = config["lidar_list"]

    sensor_list = cam_list[:] 
    if config['steps_controller']['source'] != "vision" and lidar_list:
        if "lidar0" in lidar_list or "lidar1" in lidar_list:
            sensor_list.append("lidar_repack2")
        if "lidar2" in lidar_list:
            sensor_list.append("lidar_repack")
    extra_filter={'aligned_sensors': sensor_list}             

    clip_query = get_clip_query(config)
    if clip_query:
        extra_filter.update({"clip_query": clip_query})

    sql_filter = get_sql_filter(config, record_type)
    if "data_cache_saving_dir" in config:
        config["XData"]["config"]["data_cache"] = config["data_cache_saving_dir"]    

    loader = DatasetLoader(config["XData"]["config"])
    dataset = loader.load_dataset_v2(
        config["dataset_name"],
        sql_filter = sql_filter,
        extra_filter = extra_filter,
        record_type = record_type,
    )

    clip_records = get_clip_records(dataset, record_type)

    return loader, clip_records


def _in_time_range(ts, start_time, end_time):
    """Check if timestamp ts is in [start_time, end_time]. If either bound is None, treat as no bound."""
    if start_time is not None and ts < start_time:
        return False
    if end_time is not None and ts > end_time:
        return False
    return True


def merge_subrun_jsons(config, clip_ids, start_time=None, end_time=None):
    ##### copy the first clip's metadata.json to subrun
    clip_id = clip_ids[0]
    clip_path = os.path.join(config["subrun_path"], clip_id)
    os.system(f"cp {clip_path}/metadata.json {config['subrun_path']}")

    def filter_by_time(items, get_ts):
        if start_time is None and end_time is None:
            return items
        return [x for x in items if _in_time_range(get_ts(x), start_time, end_time)]

    get_nsec = lambda x: x["time_stamp"]["nsec"]

    ##### merge LocalPoseTopic.json
    localpose_jsons = []
    for clip_id in clip_ids:
        lp_json = json.load(open(os.path.join(config["subrun_path"], clip_id, "LocalPoseTopic.json")))
        localpose_jsons.append(lp_json)
    localpose_merged = []
    for lp_json in localpose_jsons:
        localpose_merged.extend(filter_by_time(lp_json, get_nsec))
    localpose_sorted = sorted(localpose_merged, key=get_nsec)
    if localpose_sorted:
        timestamps = [localpose["time_stamp"]["nsec"] for localpose in localpose_sorted]
        time_diff = [float(timestamps[i] - timestamps[i-1]) / 1e9 for i in range(1, len(timestamps))]
        print(f"[INFO] Max and min time diff in merged LocalPoseTopic.json: {max(time_diff)}, {min(time_diff)}")
    with open(os.path.join(config["subrun_path"], "LocalPoseTopic.json"), "w") as f:
        json.dump(localpose_sorted, f, indent=4)

    ##### merge DynamicXNetTopic.json
    dynamic_xnet_jsons = []
    for clip_id in clip_ids:
        lp_json = json.load(open(os.path.join(config["subrun_path"], clip_id, "DynamicXNetTopic.json")))
        dynamic_xnet_jsons.append(lp_json)
    dynamic_xnet_merged = []
    for lp_json in dynamic_xnet_jsons:
        dynamic_xnet_merged.extend(filter_by_time(lp_json, get_nsec))
    dynamic_xnet_sorted = sorted(dynamic_xnet_merged, key=get_nsec)
    with open(os.path.join(config["subrun_path"], "DynamicXNetTopic.json"), "w") as f:
        json.dump(dynamic_xnet_sorted, f, indent=4)

    ##### merge StaticXNetTopic.json
    static_xnet_jsons = []
    for clip_id in clip_ids:
        lp_json = json.load(open(os.path.join(config["subrun_path"], clip_id, "StaticXNetTopic.json")))
        static_xnet_jsons.append(lp_json)
    static_xnet_merged = []
    for lp_json in static_xnet_jsons:
        static_xnet_merged.extend(filter_by_time(lp_json, get_nsec))
    static_xnet_sorted = sorted(static_xnet_merged, key=get_nsec)
    with open(os.path.join(config["subrun_path"], "StaticXNetTopic.json"), "w") as f:
        json.dump(static_xnet_sorted, f, indent=4)

    ##### merge MfLocalPoseTopic.json
    mflocal_pose = []
    for clip_id in clip_ids:
        lp_json = json.load(open(os.path.join(config["subrun_path"], clip_id, "MfLocalPoseTopic.json")))
        mflocal_pose.append(lp_json)
    mflocal_pose_merged = []
    for lp_json in mflocal_pose:
        mflocal_pose_merged.extend(filter_by_time(lp_json, get_nsec))
    mflocal_pose_sorted = sorted(mflocal_pose_merged, key=get_nsec)
    with open(os.path.join(config["subrun_path"], "MfLocalPoseTopic.json"), "w") as f:
        json.dump(mflocal_pose_sorted, f, indent=4)

    ##### merge timestamp2slice.json (only timestamps in [start_time, end_time])
    timestamp2slice = {}
    for clip_id in clip_ids:
        ts2slice = json.load(open(os.path.join(config["subrun_path"], clip_id, "timestamp2slice.json")))
        for ts_str, idx in ts2slice.items():
            ts = int(ts_str)
            if _in_time_range(ts, start_time, end_time):
                timestamp2slice[ts_str] = idx
    timestamp2slice_sorted = sorted(timestamp2slice.items(), key=lambda x: int(x[0]))
    timestamp2slice_reindexed = {ts: idx for idx, (ts, _) in enumerate(timestamp2slice_sorted)}
    with open(os.path.join(config["subrun_path"], "timestamp2slice.json"), "w") as f:
        json.dump(timestamp2slice_reindexed, f, indent=4)

    ##### merge calib.json: only keep local_pose, global_pose, slice_id, id2timestamp for timestamps in range
    first_calib = json.load(open(os.path.join(config["subrun_path"], clip_ids[0], "calib.json")))
    for key in ["local_pose", "global_pose", "slice_id", "id2timestamp"]:
        first_calib[key] = {}
    for clip_id in clip_ids:
        calib = json.load(open(os.path.join(config["subrun_path"], clip_id, "calib.json")))
        for ts_str, val in calib.get("local_pose", {}).items():
            ts = int(ts_str)
            if _in_time_range(ts, start_time, end_time):
                first_calib["local_pose"][ts_str] = val
        for ts_str, val in calib.get("global_pose", {}).items():
            ts = int(ts_str)
            if _in_time_range(ts, start_time, end_time):
                first_calib["global_pose"][ts_str] = val
        for ts_str, val in calib.get("slice_id", {}).items():
            ts = int(ts_str)
            if _in_time_range(ts, start_time, end_time):
                first_calib["slice_id"][ts_str] = val
    all_ts_in_range = []
    for clip_id in clip_ids:
        calib = json.load(open(os.path.join(config["subrun_path"], clip_id, "calib.json")))
        for idx, ts in calib.get("id2timestamp", {}).items():
            if _in_time_range(ts, start_time, end_time):
                all_ts_in_range.append(ts)
    first_calib["id2timestamp"] = {str(i): ts for i, ts in enumerate(sorted(all_ts_in_range))}
    with open(os.path.join(config["subrun_path"], "calib.json"), "w") as f:
        json.dump(first_calib, f, indent=4)

    return True


def merge_subrun_images(config, clip_ids, start_time=None, end_time=None):
    ##### merge images: only move images with filename <timestamp>.png where timestamp in [start_time, end_time]
    target_path = os.path.join(config["subrun_path"], "images_origin")
    os.makedirs(target_path, exist_ok=True)
    for clip_id in clip_ids:
        for cam in config["cam_list"]:
            src_dir = os.path.join(config["subrun_path"], clip_id, "images_origin", cam)
            os.makedirs(os.path.join(target_path, cam), exist_ok=True)
            if not os.path.isdir(src_dir):
                continue
            for fname in os.listdir(src_dir):
                stem, ext = os.path.splitext(fname)
                if ext.lower() != ".png":
                    continue
                try:
                    ts = int(stem)
                except ValueError:
                    continue
                if not _in_time_range(ts, start_time, end_time):
                    continue
                src = os.path.join(src_dir, fname)
                dst = os.path.join(target_path, cam, fname)
                if os.path.isfile(src):
                    shutil.move(src, dst)
    return True


def merge_subrun_pcds(config, clip_ids):
    ##### merge pcds
    target_path = os.path.join(config["subrun_path"], "pcd")
    os.makedirs(target_path, exist_ok=True)
    for clip_id in clip_ids:
        os.system(f"mv {os.path.join(config['subrun_path'], clip_id, 'pcd')}/* {target_path}/")
    return True


def merge_subrun_autolabels(config, clip_ids):
    ##### merge autolabel_json
    target_path = os.path.join(config["subrun_path"], "autolabel_json")
    os.makedirs(target_path, exist_ok=True)
    for clip_id in clip_ids:
        os.system(f"mv {os.path.join(config['subrun_path'], clip_id, 'autolabel_json')}/* {target_path}/")
    return True


def merge_subrun_clips(config, clip_ids, start_time=None, end_time=None, use_h265_png=False):
    status = merge_subrun_jsons(config, clip_ids, start_time=start_time, end_time=end_time)
    print("[INFO] merge_subrun_jsons done")
    if not use_h265_png:
        status &= merge_subrun_images(config, clip_ids, start_time=start_time, end_time=end_time)
        print("[INFO] merge_subrun_images done")
    return status

if __name__ == "__main__":
    config = {}
    config["subrun_path"] = "/workspace/dusc@xiaopeng.com/code/simworld_subrun/datasets/c-000"
    config["cam_list"] = ["cam0", "cam2", "cam3", "cam4", "cam5", "cam6", "cam7"]
    clip_ids = ["c-7ab6f066-9cc5-3ac7-9dcb-19443ad232e2", "c-a9edc137-dfaf-3feb-a60f-02a35ad65785"]
    merge_subrun_clips(config, clip_ids)