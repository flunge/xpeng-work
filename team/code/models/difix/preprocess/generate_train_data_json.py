import json
import oss2
import re
from typing import Optional
import os


# 合法 version：vXXX 或 vXXX[a-z]?，且后面只能接 _数字 到结尾
VERSION_PATTERN = re.compile(r"(v\d{3}[a-z]?)(?=_\d+$)")

def extract_version(s: str) -> Optional[str]:
    m = VERSION_PATTERN.search(s)
    return m.group(1) if m else None


def version_key(v: str):
    """
    v414   -> (414, False, "")
    v414b  -> (414, True, "b")
    """
    m = re.fullmatch(r"v(\d{3})([a-z]?)", v)
    if not m:
        raise ValueError(f"invalid version: {v}")

    num = int(m.group(1))
    suffix = m.group(2)
    return (num, suffix != "", suffix)


def get_latest_model_name(model_versions):
    """
    返回 version 最大的那个完整字符串
    """
    candidates = []

    for name in model_versions:
        v = extract_version(name)
        if v:
            candidates.append((name, v))

    if not candidates:
        return None

    # 按 version 排序，取最大的
    return max(candidates, key=lambda x: version_key(x[1]))[0]


def get_bucket():
    # Replace these with your actual values
    access_key_id = "OSS_ACCESS_KEY_ID_REDACTED"
    access_key_secret = "OSS_ACCESS_KEY_SECRET_REDACTED"
    bucket_name = "cloudsim-ci-sh"
    endpoint = "http://oss-cn-wulanchabu-internal.aliyuncs.com"  # Replace with your region
    # Initialize the OSS Auth and Bucket
    auth = oss2.Auth(access_key_id, access_key_secret)
    bucket = oss2.Bucket(auth, endpoint, bucket_name)
    return bucket


def get_model_version_from_oss2(
        bucket,
        object_key = "sim_engine/ips_output_reconic/"
    ):
    # list only one level of subfolders
    subfolders = []
    for obj in oss2.ObjectIterator(bucket, prefix=object_key, delimiter="/"):
        model_version = obj.key.split("/")[-2]
        subfolders.append(model_version)
    return subfolders


def get_clip_ids_from_oss2(
        bucket,
        object_key="sim_engine/ips_output_reconic/"
    ):
    # list only one level of clip folders
    clip_ids = []
    for obj in oss2.ObjectIterator(bucket, prefix=object_key, delimiter="/"):
        clip_id = obj.key.split("/")[-2]
        if clip_id:
            clip_ids.append(clip_id)
    return clip_ids


def check_obj_exist(bucket, key):
    objects = oss2.ObjectIterator(bucket, prefix=key, delimiter='/')
    return any(objects)


if __name__ == "__main__":
    #############################  设置开始  ######################################
    ### 新建debug_clips.py文件，把clip_ids_str设置成如下字符串，则只收集这些clip_ids：
    # clip_ids_str = """
    # c-4b1dcb83-dd7f-3c65-8579-d53ad9dcee5d
    # c-4ca...
    # """
    from debug_clips import clip_ids_str
    clip_ids = [clip_id.strip() for clip_id in clip_ids_str.split("\n") if clip_id.strip()]

    ### 把clip_ids设置为空，则自动扫描所有clip_ids
    clip_ids = []

    skip_clip_wo_images_origin_in_oss = True if len(clip_ids) == 0 else False # 如果clip_ids不为空，则不跳过没有images_origin的clip
    max_number_of_clips = 15000  # 设置为5000，则只收集5000个clip
    min_model_version = "v415"  # 设置为v414，则只收集v414及之后的模型
    # 输出文件夹
    output_folder = "/workspace/yangxh7@xiaopeng.com/codes/3dgs/models/difix/utils/train_data_415_0421"
    #############################  设置结束  ######################################

    res_json = []
    res_csv = []
    bucket = get_bucket()
    os.makedirs(output_folder, exist_ok=True)

    # If no clip_ids provided, auto scan all clip folders in ips_output_reconic.
    if not clip_ids:
        clip_ids = get_clip_ids_from_oss2(bucket, "sim_engine/ips_output_reconic/")
        print(f"auto discovered clip_ids count: {len(clip_ids)}")

    for clip_id in clip_ids:
        if len(clip_id) == 0:
            continue

        object_key = f"sim_engine/ips_output_reconic/{clip_id}/"
        model_versions = get_model_version_from_oss2(bucket, object_key)
        # extract version from string like "trained_model_sim3dgs_v414_1347"
        # and choose the max version
        largest_model_version = get_latest_model_name(model_versions)
        if largest_model_version is None:
            print(f"no model version found for clip_id: {clip_id}")
            continue

        largest_version = extract_version(largest_model_version)
        if largest_version is None:
            print(f"failed to parse version for clip_id: {clip_id}, model: {largest_model_version}")
            continue

        if version_key(largest_version) < version_key(min_model_version):
            continue

        images_origin_key = f"sim_engine/datasets/{clip_id}/images_origin/images_origin.tgz"
        images_origin_exist_in_oss = check_obj_exist(bucket, images_origin_key)
        if not images_origin_exist_in_oss and skip_clip_wo_images_origin_in_oss:
            print(f"images_origin not exist in oss for clip_id: {clip_id}")
            continue
        
        res_json.append({
            "clip_id": clip_id,
            "model_version": largest_model_version,
            "images_origin_exist_in_oss": images_origin_exist_in_oss,
        })
        if len(res_json) % 100 == 0:
            print(f"progress: collected {len(res_json)} clips")

        if len(res_json) >= max_number_of_clips:
            print(f"reach max_number_of_clipsd={max_number_of_clips}, stop collecting")
            break

        if not images_origin_exist_in_oss and skip_clip_wo_images_origin_in_oss:
            res_csv.append(f"{clip_id}")
        
    with open(os.path.join(output_folder, "train_data.json"), "w", encoding="utf-8") as f:
        for item in res_json:
            f.write(json.dumps(item, ensure_ascii=False))
            f.write("\n")
    print(f"{os.path.join(output_folder, 'train_data.json')} generated")
    
    # write csv with header "clip_id"
    with open(os.path.join(output_folder, "train_data.csv"), "w") as f:
        f.write("clip_id\n")
        for clip_id in res_csv:
            f.write(f"{clip_id}\n")
    print(f"{os.path.join(output_folder, 'train_data.csv')} with length {len(res_csv)} generated")
    