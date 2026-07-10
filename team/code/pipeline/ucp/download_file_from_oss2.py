import oss2
import sys
import argparse


def download_file_from_oss2(
        local_file_path="/workspace/yangxh7@xiaopeng.com/3dgs_model.tgz",
        object_key = "sim_engine/ips_output_yxh/c-32499217-9887-3618-9119-c0ef4ee6cbb0/preprocess/3dgs_model.tgz",
        show_progress=True,
        bucket_name=None
    ):
    # Replace these with your actual values
    access_key_id = os.environ.get("OSS_ACCESS_KEY_ID", "")
    access_key_secret = os.environ.get("OSS_ACCESS_KEY_SECRET", "")
    if bucket_name is None:
        bucket_name = "cloudsim-ci-sh"
    endpoint = "http://oss-cn-wulanchabu-internal.aliyuncs.com"  # Replace with your region

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
    # Replace these with your actual values
    access_key_id = os.environ.get("OSS_ACCESS_KEY_ID", "")
    access_key_secret = os.environ.get("OSS_ACCESS_KEY_SECRET", "")
    bucket_name = "cloudsim-ci-sh"
    endpoint = "http://oss-cn-wulanchabu-internal.aliyuncs.com"  # Replace with your region
    # Initialize the OSS Auth and Bucket
    auth = oss2.Auth(access_key_id, access_key_secret)
    bucket = oss2.Bucket(auth, endpoint, bucket_name)
    return bucket


def listdir_from_oss2(
        bucket,
        object_key = "sim_engine/ips_output_yxh/"
    ):
    # list files in folder of oss
    subfolders = []
    for obj in oss2.ObjectIterator(bucket, prefix=object_key):
        subfolders.append(obj.key)
    return subfolders


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    # 本地目录路径
    parser.add_argument("--local_file_path", type=str, required=True)
    # oss目录路径
    parser.add_argument("--object_key", type=str, default="")
    args = parser.parse_args()

    download_file_from_oss2(args.local_file_path, args.object_key)