"""
This script uploads files or directories from a local machine to an Alibaba Cloud OSS (Object Storage
Service) bucket. It includes functionality to track upload state to avoid redundant uploads.

Author: Xinghao Yang
Date: 2024-08-08
"""
import os, sys
import json
import argparse
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
import tarfile
import concurrent.futures
from functools import partial
import time
import random
try:
    import oss2
except ImportError:
    print("oss2 module not found, installing...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "oss2"])
    import oss2



def upload_file(bucket, oss_directory, local_file_path):
    res = bucket.put_object_from_file(oss_directory, local_file_path)
    print(f'Upload {local_file_path} to {oss_directory}: {res}')


# 判断文件是否需要上传
def should_upload(local_file_path, oss_object_key, upload_state):
    if oss_object_key not in upload_state:
        # 文件未上传过，需要上传
        return True
    else:
        # 文件已上传过，检查本地文件的修改时间是否大于上传时间
        local_mtime = os.path.getmtime(local_file_path)
        return local_mtime > upload_state[oss_object_key]


def upload(src, dst, bucket_name='xmotors-fuyao-sync', oss_directory='yangxh7/ips/'):
    # 阿里云 OSS 访问信息
    access_key_id = os.environ.get("OSS_ACCESS_KEY_ID", "")
    access_key_secret = os.environ.get("OSS_ACCESS_KEY_SECRET", "")
    endpoint = 'http://oss-cn-wulanchabu-internal.aliyuncs.com'  
    # bucket_name = 'cloudsim-ci-sh'
    # oss_directory = 'sim_engine/ips_configs/'
    
    upload_oss_directory = os.path.join(oss_directory, dst)
    
    # 创建 OSS 客户端
    auth = oss2.Auth(access_key_id, access_key_secret)
    bucket = oss2.Bucket(auth, endpoint, bucket_name)

    # 开始上传
    print(f'started {upload_oss_directory} {src}')

    upload_file(bucket, upload_oss_directory, src)
    print(f'uploaded {upload_oss_directory} {src}')


def upload_directory_to_oss(local_directory, bucket, oss_directory='sim_engine'):
    for root, dirs, files in os.walk(local_directory):
        for file in files:
            local_file_path = os.path.join(root, file)
            oss_object_key = os.path.join(oss_directory, os.path.relpath(local_file_path, local_directory))

            bucket.put_object_from_file(oss_object_key, local_file_path)
            print(f'Uploaded {local_file_path} to {oss_object_key}')


def upload_train_model_to_oss(save_dir, upload_train_directory):
    # oss config
    auth = oss2.Auth(os.environ.get("OSS_ACCESS_KEY_ID", ""), os.environ.get("OSS_ACCESS_KEY_SECRET", ""))
    bucket = oss2.Bucket(auth, 'http://oss-cn-wulanchabu-internal.aliyuncs.com', 'cloudsim-ci-sh')

    record_dir = save_dir.replace("/output/", "/output/record/")
    temp_output_path = '/root/repo/models/street_gaussians/output/trained_models_temp/'
    os.makedirs(temp_output_path, exist_ok=True)

    transfer_and_compress(save_dir, output_path=os.path.join(temp_output_path, '3dgs_model.tgz'), move=True)
    transfer_and_compress(record_dir, output_path=os.path.join(temp_output_path, 'tensorboards.tgz'), move=True)
    upload_directory_to_oss(temp_output_path, bucket, upload_train_directory)


def compress_and_upload(folder_path, upload_train_directory, tar_name='images_origin.tgz'):
    # oss config
    auth = oss2.Auth(os.environ.get("OSS_ACCESS_KEY_ID", ""), os.environ.get("OSS_ACCESS_KEY_SECRET", ""))
    bucket = oss2.Bucket(auth, 'http://oss-cn-wulanchabu-internal.aliyuncs.com', 'cloudsim-ci-sh')

    temp_output_path = '/root/repo/models/street_gaussians/output/temp_data/'
    os.makedirs(temp_output_path, exist_ok=True)

    transfer_and_compress(
        folder_path, output_path=os.path.join(temp_output_path, tar_name), move=False,
        excluded_dirs=('origin', 'log_images', 'evaluation')
    )
    upload_directory_to_oss(temp_output_path, bucket, upload_train_directory)



def upload_local_dir_to_oss(
    local_directory,
    oss_directory,
    bucket_name="cloudsim-ci-sh",
    endpoint="http://oss-cn-wulanchabu-internal.aliyuncs.com",
    access_key=os.environ.get("OSS_ACCESS_KEY_ID", ""),
    secret_key=os.environ.get("OSS_ACCESS_KEY_SECRET", ""),
    job_num=10,
):
    """Upload all files under local_directory to oss://{bucket_name}/{oss_directory}/."""
    local_directory = os.path.abspath(local_directory)
    if not os.path.isdir(local_directory):
        raise FileNotFoundError(f"local directory not found: {local_directory}")
    return upload_directory_to_oss_fast(
        local_directory,
        oss_directory.rstrip("/"),
        endpoint,
        access_key,
        secret_key,
        job_num,
        bucket_name,
    )


def upload_directory_to_oss_fast(local_directory, oss_directory, var_endpoint, var_access_key, var_secret_key, var_job_num, var_bucket_name):
    """
    Upload directory to OSS using ossutil64

    Returns:
        bool: True if upload succeeded, False otherwise
    """
    try:
        for root, dirs, files in os.walk(local_directory):
            for file in files:
                local_file_path = os.path.join(root, file)
                oss_object_key = os.path.join(oss_directory, os.path.relpath(local_file_path, local_directory))

                # Use subprocess.run instead of os.system to get return code
                cmd = f"ossutil64 -e {var_endpoint} -i {var_access_key} -k {var_secret_key} -j {var_job_num} cp -rf '{local_file_path}' 'oss://{var_bucket_name}/{oss_object_key}'"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=1800)

                # Check if the command succeeded
                if result.returncode != 0:
                    print(f"Failed to upload {local_file_path}: {result.stderr}")
                    return False

        return True

    except Exception as e:
        print(f"Error in upload_directory_to_oss_fast: {e}")
        return False

def upload_train_model_to_oss_fast(save_dir, upload_train_directory, suffix='', move=True, upload_record=False):

    record_dir = save_dir.replace("/output/", "/output/record/")
    temp_output_path = f'/root/repo/models/street_gaussians/output/trained_models_temp_{suffix}/'
    os.makedirs(temp_output_path, exist_ok=True)

    transfer_and_compress_fast(save_dir, output_path=os.path.join(temp_output_path, '3dgs_model.tgz'), move=move)
    if upload_record:
        transfer_and_compress_fast(record_dir, output_path=os.path.join(temp_output_path, 'tensorboards.tgz'), move=move)
    
    access_key = os.environ.get("OSS_ACCESS_KEY_ID", "")
    secret_key = os.environ.get("OSS_ACCESS_KEY_SECRET", "")
    job_num =10
    endpoint = 'http://oss-cn-wulanchabu-internal.aliyuncs.com'
    bucket_name = 'cloudsim-ci-sh'
    
    upload_directory_to_oss_fast(temp_output_path, upload_train_directory, endpoint, access_key, secret_key, job_num, bucket_name)
    return temp_output_path

def compress_and_upload_fast(
        folder_path, upload_train_directory, tar_name='images_origin.tgz', suffix='',
        excluded_dirs=('origin', 'log_images', 'evaluation'),
        included_dirs=()
    ):
    temp_output_path = f'/root/repo/models/street_gaussians/output/temp_data_{suffix}/'
    os.makedirs(temp_output_path, exist_ok=True)
    start = time.time()
    transfer_and_compress_fast(
        folder_path, output_path=os.path.join(temp_output_path, tar_name), move=False,
        excluded_dirs=excluded_dirs,
        included_dirs=included_dirs
    )
    end = time.time()
    print(f"compress_and_upload_fast transfer_and_compress_fast cost {end - start:.6f}")
    start = time.time()
    
    access_key = os.environ.get("OSS_ACCESS_KEY_ID", "")
    secret_key = os.environ.get("OSS_ACCESS_KEY_SECRET", "")
    job_num =10
    endpoint = 'http://oss-cn-wulanchabu-internal.aliyuncs.com'
    bucket_name = 'cloudsim-ci-sh'
    
    upload_directory_to_oss_fast(temp_output_path, upload_train_directory, endpoint, access_key, secret_key, job_num, bucket_name)
    end = time.time()
    print(f"compress_and_upload_fast upload_directory_to_oss_fast cost {end - start:.6f}")
    return temp_output_path

def transfer_and_compress_fast(
        dir1,
        output_path,
        move=True,
        excluded_dirs=('origin', 'log_images', 'evaluation'),
        included_dirs=(),
        max_workers=2
    ):
    current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    random_num = random.randint(1000000, 9999999)
    temp_dir = Path(f'/root/temp/temp_compress_dir_{current_time}_{random_num}')
    temp_dir.mkdir(parents=True, exist_ok=True)
    model1_dir = temp_dir / 'model1'
    model1_dir.mkdir(exist_ok=True)
    try:
        dir1_path = Path(dir1)
        # 1. 高效收集所有有效文件（避免多次遍历）
        valid_files = []
        for root, dirs, files in os.walk(dir1_path):
            root = Path(root)
            rel_root = root.relative_to(dir1_path)

            # ============ 目录过滤逻辑 ============
            # 如果设置了 included_dirs，则优先使用：
            #   只遍历 / 收集目录名在 included_dirs 中的目录及其子目录
            if included_dirs:
                parts = rel_root.parts  # 相对路径的各级目录名
                # 当前 root 是否已经在某个目标目录（其路径中包含 included_dirs 里的名字）
                under_included = any(part in included_dirs for part in parts)

                if not under_included:
                    # 还没进入任何目标目录，只允许继续深入到名字在 included_dirs 中的子目录
                    dirs[:] = [d for d in dirs if d in included_dirs]
                    # 当前 root 不属于目标目录自身，不需要处理这里的文件
                    continue
            else:
                # 未设置 included_dirs 时，按原有 excluded_dirs 逻辑过滤
                rel_path_str = str(rel_root)
                if any(excluded in rel_path_str for excluded in excluded_dirs):
                    dirs.clear()  # 清空子目录，避免递归
                    continue

            # 收集文件并构建目标路径
            for file in files:
                src_file = root / file
                rel_file_path = rel_root / file
                dst_file = model1_dir / rel_file_path
                # 确保目标目录存在
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                valid_files.append((src_file, dst_file, move))
        # 2. 并行处理文件操作（移动/复制）
        def process_file(src_dst_move):
            src_file, dst_file, move = src_dst_move
            try:
                if move:
                    shutil.move(src_file, dst_file)
                else:
                    shutil.copy2(src_file, dst_file)
            except Exception as e:
                print(f"处理文件 {src_file} 时出错: {e}")
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            executor.map(process_file, valid_files)
        # 3. 优化压缩方式：使用系统tar命令（更快）
        output_tar = Path(output_path)
        temp_tar = output_tar.parent / (output_tar.stem + "_temp.tgz")
        try:
            subprocess.run(
                [
                    "tar", "-I", "zstd -T0 -1", "-cf", str(temp_tar),
                    "-C", str(temp_dir), "model1"
                ],
                check=True,
                timeout=3600
            )
            temp_tar.rename(output_tar)

        except subprocess.CalledProcessError:
            # 备用方案：使用Python压缩
            with tarfile.open(output_tar, "w:gz") as tar:
                for file in valid_files:
                    src_file = file[0]
                    rel_path = src_file.relative_to(dir1_path)
                    tar.add(src_file, arcname=rel_path)
        print(f'已将 {dir1} 中的文件处理并压缩为 {output_path}')
    
    except Exception as e:
        print(f"发生错误: {e}")
    finally:
        # 清理临时目录（使用系统命令更快）
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
            
def transfer_and_compress(
        dir1, output_path, move=True, 
        excluded_dirs=('input_ply', 'origin', 'log_images', 'evaluation'),
        excluded_files=('database.db',)
    ):
    """将源目录中的文件转移到临时目录，排除指定的文件夹，并压缩临时目录为 .tgz 文件，保持目录结构一致。"""
    temp_dir = '/root/temp/temp_compress_dir'

    # 创建临时目录（如果不存在）
    os.makedirs(temp_dir, exist_ok=True)    

    try:
        # 处理 dir1
        model1_dir = os.path.join(temp_dir, 'model1')
        os.makedirs(model1_dir, exist_ok=True)
        
        for root, dirs, files in os.walk(dir1):
            # 获取当前相对路径
            rel_path = os.path.relpath(root, dir1)
            if any(excluded in rel_path for excluded in excluded_dirs):
                continue
            
            # 创建目标路径
            target_dir = os.path.join(model1_dir, rel_path)
            os.makedirs(target_dir, exist_ok=True)

            for file in files:
                if file in excluded_files:  # 排除指定的文件
                    continue
                target_file = os.path.join(target_dir, file)
                if os.path.exists(target_file):
                    raise FileExistsError(f"目标路径已存在文件: {target_file}")
                if move:
                    shutil.move(os.path.join(root, file), target_file)
                else:
                    shutil.copy(os.path.join(root, file), target_file)

        # 压缩临时目录为 .tgz 文件
        shutil.make_archive(output_path[:-4], 'gztar', temp_dir)

        os.rename(output_path[:-4] + '.tar.gz', output_path)

        print(f'已将 {dir1} 中的文件转移到 {temp_dir} 并压缩为 {output_path}')
    except Exception as e:
        print(f"发生错误: {e}")
    finally:
        # 清理临时目录
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    # 本地目录路径
    parser.add_argument("--src", type=str, required=True)
    # oss目录路径
    parser.add_argument("--dst", type=str, default="")
    args = parser.parse_args()

    upload(args.src, args.dst)
