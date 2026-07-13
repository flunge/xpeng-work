import os, sys
import oss2
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from merge_video_utils import merge_videos, compare_merged_videos



def download_folder_from_oss(local_folder, target_oss_path, keywords=None):
    """
    Downloads a folder from OSS to a local directory, maintaining the file structure.
    """
    access_key_id = "OSS_ACCESS_KEY_ID_REDACTED"
    access_key_secret = "OSS_ACCESS_KEY_SECRET_REDACTED"
    bucket_name = "cloudsim-ci-sh"
    endpoint = "http://oss-cn-wulanchabu.aliyuncs.com"  # Replace with your region
    # Initialize OSS authentication and bucket
    auth = oss2.Auth(access_key_id, access_key_secret)
    bucket = oss2.Bucket(auth, endpoint, bucket_name)
    
    try:
        for obj in oss2.ObjectIterator(bucket, prefix=target_oss_path):
            if keywords is not None and not any(keyword in obj.key for keyword in keywords):
                continue
            
            local_file_path = os.path.join(local_folder, os.path.relpath(obj.key, target_oss_path))
            os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
            
            if os.path.exists(local_file_path):
                print(f"File {local_file_path} already exists, skipping download.")
                continue
            else:
                print(f"Downloading oss://{bucket_name}/{obj.key} to {local_file_path}")
                bucket.get_object_to_file(obj.key, local_file_path)
        
        print("Download completed.")
        return True
    except Exception as e:
        print(f"Error during download: {e}")
        return False


def merge_fuyao_exp_videos(local_folder, exp_names, iter=80000, only_compare=False):
    # get the same part of names in exp_names
    common_exp_name = os.path.commonprefix(exp_names)
    work_folder1 = os.path.join(local_folder, f"merged_{common_exp_name}_256")
    work_folder2 = os.path.join(local_folder, f"merged_{common_exp_name}_034")
    if only_compare:
        return work_folder1, work_folder2
    
    os.makedirs(work_folder1, exist_ok=True)
    os.makedirs(work_folder2, exist_ok=True)
    
    for exp_name in exp_names:
        mode = ["origin", "sin_wave"] # , "ground"
        unique_mode = set()
        file_name_remap = {
            "cam0": "cama",
            "cam2": "cama",
            "cam3": "camb",
            "cam4": "camc",
            "cam5": "camb",
            "cam6": "camc"
        }
        root = os.path.join(local_folder, exp_name)
        if iter is None:
            iter = max(int(d.split('_')[-1]) for d in os.listdir(os.path.join(root, "origin")) if d.startswith("iter_"))
            
        video_root = os.path.join(root, "origin", f"iter_{iter}")
        videos = os.listdir(video_root)

        for file in videos:
            if file.lower().endswith('.mp4'):
                new_filename = file
                for old, new in file_name_remap.items():
                    new_filename = new_filename.replace(old, new)
                local_path = os.path.join(video_root, file)
                work_folder = work_folder1 if any(c in file for c in ['cam2', 'cam5', 'cam6']) else work_folder2
                os.system(f"cp {local_path} {work_folder}/{new_filename}")
                for m in mode:
                    if m in file:
                        unique_mode.add(m)

    merge_videos(work_folder1, unique_mode)
    os.system(f"cd {work_folder1}; rm video_*.mp4")
    for i in os.listdir(work_folder1):
        os.system(f"mv {work_folder1}/{i} {work_folder1}/{i.replace('abc', '256')}")

    merge_videos(work_folder2, unique_mode)
    os.system(f"cd {work_folder2}; rm video_*.mp4")
    for i in os.listdir(work_folder2):
        os.system(f"mv {work_folder2}/{i} {work_folder2}/{i.replace('abc', '034')}")
    return work_folder1, work_folder2



if __name__ == "__main__":
    root = "/workspace/yangxh7@xiaopeng.com/codes/3dgs/street_gaussians/output/m1/"
    compare_base = "merged_runJ_16a"
    targets = {
        # "fm_fixed/c-66260c6e-release": ["runK_16a"],
        # "fm_fixed/c-10ce0565-release": ["runK_16a",],
        "fm_fixed/c-078f16e4-release": ["runK_16a"],
        "fm_fixed/c-c244e2f3-release": ["runK_16a",],
        # "fm_fixed/c-b0661312-release": ["runK_16a",],
    }
    
    for target, exp_names in targets.items():
        local_folder = os.path.join(root, target)
        work_folder1, work_folder2 = merge_fuyao_exp_videos(local_folder, exp_names, iter=80000)
        valid_folders = []
        if any(["output256" in f for f in os.listdir(work_folder1)]):
            valid_folders.append(work_folder1)
        if any(["output034" in f for f in os.listdir(work_folder2)]):
            valid_folders.append(work_folder2)

        for folder in valid_folders:
            compare_folder_tmp = os.path.join("/workspace/yangxh7@xiaopeng.com/tmp/", target, compare_base)
            compare_folder_oss = root.replace(
                "/workspace/yangxh7@xiaopeng.com/codes/3dgs/", "sim_engine/yangxh/"
            )

            compare_group = '256' if "_256" in folder else '034'
            compare_folder_name = compare_base + '_' + compare_group
            compare_folder_oss = os.path.join(compare_folder_oss, target, compare_folder_name)

            possible_local_compared_path = os.path.join(local_folder, compare_folder_name)

            if os.path.exists(possible_local_compared_path):
                compare_folder_local = possible_local_compared_path
            elif download_folder_from_oss(compare_folder_tmp, compare_folder_oss):
                compare_folder_local = compare_folder_tmp
            else:
                print(f"Failed to download {compare_folder_oss}, skipping comparison.")
                continue

            compare_merged_videos(compare_folder_local, folder, ["origin", "sin_wave"]) # ["origin", "sin_wave"]) # , "ground"])
            
