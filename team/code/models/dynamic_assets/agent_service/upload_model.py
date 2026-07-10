#!/usr/bin/env python3
import os
import shutil
import tarfile
import subprocess
import tempfile
from pathlib import Path

try:
    import oss2
except ImportError:
    print("oss2 module not found, installing...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "oss2"])
    import oss2

# apt install unzip
# curl https://gosspublic.alicdn.com/ossutil/install.sh | bash

# 配置参数
# CLIP_ID = "c-94a8e6e8-5f73-3440-a863-2316c3036a35"
CLIP_ID = "c-4155db0f-0930-3e4b-bda2-56555b893ee5"
# CLIP_ID = "c-a53d86bf-ae24-3cb6-a681-6531fd903545"
# 自动生成当前时间戳
from datetime import datetime
TIMESTAMP = datetime.now().strftime("%Y%m%d%H%M")  # 当前时间戳
# SOURCE_DIR = "/workspace/duanzx@xiaopeng.com/simworld/street_gaussians/output/m1/subrun/c-94a8e6e8-5f73-3440-a863-2316c3036a35/test_07221020"  # 源目录
SOURCE_DIR = f"/workspace/duanzx@xiaopeng.com/3dgs/online_data/3dgs/{CLIP_ID}/model1"  # 源目录
# SOURCE_DIR = f"/workspace/duanzx@xiaopeng.com/3dgs/online_data/3dgs/{CLIP_ID}/model1"  # 源目录
TGZ_NAME = "3dgs_model.tgz"  # 目标压缩文件名
# OSS_PATH = f"oss://cloudsim-ci-sh/sim_engine/ips_output_clip_depth/{CLIP_ID}/trained_model_{TIMESTAMP}/3dgs_model.tgz"  # OSS存储桶地址
OSS_PATH = f"oss://cloudsim-ci-sh/sim_engine/artificially_created_scenes/{CLIP_ID}/trained_model_{TIMESTAMP}/3dgs_model.tgz"  # OSS存储桶地址
# Artificially created scenes

# 需要包含的目录和文件列表（根据截图补充完整）
INCLUDE_DIRS = [
    "autolabel_json",
    "configs",
    "images",
    "point_cloud",
    "surfel_ground",
    "trained_model",
]

INCLUDE_FILES = [
    "LocalPoseTopic.json",
    "anchorpose.json",
    "annotation_for_train.json",
    "calib.json",
    "calib_origin.json",
    "cameras.json",
    "cfg_args",
    "ground_mask.npy",
    "input_background.ply",
    "input_ground.ply",
    "localpose.json",
    "metadata.json",
    "sky_latlong.png",
    "transform.json",
]

def create_temporary_structure(source_dir, include_dirs, include_files):
    """创建临时目录结构，仅包含需要的文件和目录"""
    temp_dir = tempfile.mkdtemp()
    print("temp_dir: ", temp_dir)
    
    try:
        # 复制需要的目录
        for dir_name in include_dirs:
            source_path = os.path.join(source_dir, dir_name)
            dest_path = os.path.join(temp_dir, dir_name)
            
            if os.path.isdir(source_path):
                shutil.copytree(source_path, dest_path, dirs_exist_ok=True)
                print(f"已复制目录: {source_path}")
            else:
                print(f"警告: 目录 '{source_path}' 不存在，将跳过")
        
        # 复制需要的文件
        for file_name in include_files:
            source_path = os.path.join(source_dir, file_name)
            dest_path = os.path.join(temp_dir, file_name)
            
            if os.path.isfile(source_path):
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                shutil.copy2(source_path, dest_path)
                print(f"已复制文件: {source_path}")
            else:
                print(f"警告: 文件 '{source_path}' 不存在，将跳过")
        
        return temp_dir
    except Exception as e:
        # 出错时清理临时目录
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise e

def create_tgz_archive(source_dir, output_file):
    """创建tar.gz归档文件"""
    with tarfile.open(output_file, "w:gz") as tar:
        for item in os.listdir(source_dir):
            item_path = os.path.join(source_dir, item)
            # 在arcname前加上model1目录
            arcname = os.path.join("model1", item)
            tar.add(item_path, arcname=arcname)
    print(f"已创建归档文件: {output_file}")

def upload_to_oss(local_file, oss_path):
    # 阿里云 OSS 访问信息
    access_key_id = os.environ.get("OSS_ACCESS_KEY_ID", "")
    access_key_secret = os.environ.get("OSS_ACCESS_KEY_SECRET", "")
    endpoint = 'http://oss-cn-wulanchabu-internal.aliyuncs.com'
    bucket_name = 'cloudsim-ci-sh'
    
    try:
        # 1. 检查本地文件是否存在且可读
        if not os.path.exists(local_file):
            raise FileNotFoundError(f"本地文件不存在: {local_file}")
        if not os.access(local_file, os.R_OK):
            raise PermissionError(f"没有本地文件读取权限: {local_file}")
        
        # 2. 检查oss_path格式（不应包含bucket名称或oss://前缀）
        if oss_path.startswith(('oss://', f'{bucket_name}/')):
            raise ValueError(f"oss_path格式错误，不应包含bucket名称或oss://前缀: {oss_path}")
        
        # 3. 创建OSS客户端
        auth = oss2.Auth(access_key_id, access_key_secret)
        bucket = oss2.Bucket(auth, endpoint, bucket_name)
        
        # 4. 执行上传
        print(f'开始上传: 本地文件={local_file} -> OSS路径={oss_path}')
        res = bucket.put_object_from_file(oss_path, local_file)
        
        # 5. 验证上传结果（HTTP状态码200表示成功）
        if res.status != 200:
            raise OSSException(f"上传返回非成功状态码: {res.status}")
        
        print(f'上传成功: {local_file} -> {oss_path} (状态码: {res.status})')
        return True
    
    except FileNotFoundError as e:
        print(f"上传失败：{str(e)}")
        return False
    except PermissionError as e:
        print(f"上传失败：{str(e)}")
        return False
    except ValueError as e:
        print(f"参数错误：{str(e)}")
        return False
    except OSSException as e:
        print(f"OSS服务错误：{str(e)}")  # 包含OSS返回的具体错误信息（如权限不足、路径错误等）
        return False
    except Exception as e:
        print(f"未知错误：{str(e)}")
        return False

def main():
    try:
        # 1. 创建临时结构
        temp_dir = create_temporary_structure(SOURCE_DIR, INCLUDE_DIRS, INCLUDE_FILES)
        
        # 2. 创建压缩文件
        create_tgz_archive(temp_dir, TGZ_NAME)
        
        # 3. 上传到OSS
        upload_to_oss(TGZ_NAME, OSS_PATH)
        
        print("所有操作已完成")
    except Exception as e:
        print(f"执行过程中发生错误: {str(e)}")
        exit(1)
    finally:
        # 清理临时目录
        if 'temp_dir' in locals() and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            print(f"已清理临时目录: {temp_dir}")

if __name__ == "__main__":
    main()