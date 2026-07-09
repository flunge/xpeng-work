import oss2
import os
import sys
import argparse


def download_file_from_oss2(
        local_file_path="/workspace/yangxh7@xiaopeng.com/3dgs_model.tgz",
        object_key = "sim_engine/ips_output_yxh/c-32499217-9887-3618-9119-c0ef4ee6cbb0/preprocess/3dgs_model.tgz",
        bucket = None,
        show_progress = True
    ):
    if not bucket:
        access_key_id = os.getenv("OSS_ACCESS_KEY_ID")
        access_key_secret = os.getenv("OSS_ACCESS_KEY_SECRET")
        bucket_name = "cloudsim-ci-sh"
        endpoint = "http://oss-cn-wulanchabu.aliyuncs.com"

        # Initialize the OSS Auth and Bucket
        auth = oss2.Auth(access_key_id, access_key_secret)
        bucket = oss2.Bucket(auth, endpoint, bucket_name)

    # Progress callback function
    def progress_callback(consumed_bytes, total_bytes):
        if total_bytes:
            progress = int(consumed_bytes * 100 / total_bytes)
            sys.stdout.write(f"\rDownloading: {progress}%")
            sys.stdout.flush()

    try:
        if show_progress:
            bucket.get_object_to_file(object_key, local_file_path, progress_callback=progress_callback)
            print(f"\nFile {object_key} downloaded successfully!")
        else:
            bucket.get_object_to_file(object_key, local_file_path)
        return True
    except oss2.exceptions.AccessDenied as e:
        print("Access denied. Please check your credentials or bucket permissions.")
        return False
    except oss2.exceptions.NoSuchKey:
        print("The specified file does not exist.")
        return False
    except Exception as e:
        print(f"An error occurred: {e}")
        return False


def get_bucket():
    access_key_id = os.getenv("OSS_ACCESS_KEY_ID")
    access_key_secret = os.getenv("OSS_ACCESS_KEY_SECRET")
    bucket_name = "cloudsim-ci-sh"
    endpoint = "http://oss-cn-wulanchabu.aliyuncs.com"
    # Initialize the OSS Auth and Bucket
    auth = oss2.Auth(access_key_id, access_key_secret)
    bucket = oss2.Bucket(auth, endpoint, bucket_name)
    return bucket


def get_bucket_vision():
    access_key_id = os.getenv("OSS_VISION_ACCESS_KEY_ID")
    access_key_secret = os.getenv("OSS_VISION_ACCESS_KEY_SECRET")
    bucket_name = "ips-prediction"
    endpoint = "http://oss-cn-wulanchabu.aliyuncs.com"
    # Initialize the OSS Auth and Bucket
    auth = oss2.Auth(access_key_id, access_key_secret)
    bucket = oss2.Bucket(auth, endpoint, bucket_name)
    return bucket


def listdir_from_oss2(
        bucket,
        object_key = "sim_engine/ips_output_yxh/",
        vision = False
    ):
    # list files in folder of oss
    subfolders = []
    if not vision:
        for obj in oss2.ObjectIterator(bucket, prefix=object_key):
            subfolders.append(obj.key)
    else:
        temp = []
        for obj in oss2.ObjectIterator(bucket, prefix=object_key, delimiter="/"):
            # check if subpath is a folder
            if obj.is_prefix():
                temp.append(obj.key)
        for folder in temp:
            for obj in oss2.ObjectIterator(bucket, prefix=folder, delimiter="/"):
                subfolders.append(obj.key)
    return subfolders


def check_obj_folder_exist(bucket, object_key):
    # check if the object folder exists in bucket
    objects = oss2.ObjectIterator(bucket, prefix=object_key, delimiter='/')
    return any(objects)


if __name__ == "__main__":
    bucket = get_bucket_vision()
    target_folder = "prelabel_gxodips_visionsimips_1736752656/"
    folders = listdir_from_oss2(bucket, target_folder, vision=True)
    print(folders, len(folders))
    