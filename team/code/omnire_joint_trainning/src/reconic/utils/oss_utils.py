import os, sys
import subprocess
from pathlib import Path
try:
    import oss2
except ImportError:
    print("oss2 module not found, installing...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "oss2"])
    import oss2

def download_and_extract_tgz_from_oss(
    oss_object_key, 
    local_extract_path, 
    bucket_name='cloudsim-ci-sh', 
    endpoint='http://oss-cn-wulanchabu-internal.aliyuncs.com',
    access_key_id='OSS_ACCESS_KEY_ID_REDACTED',
    access_key_secret='OSS_ACCESS_KEY_SECRET_REDACTED'
):
    try:
        auth = oss2.Auth(access_key_id, access_key_secret)
        bucket = oss2.Bucket(auth, endpoint, bucket_name)

        local_extract_path = Path(local_extract_path)
        local_extract_path.mkdir(parents=True, exist_ok=True)

        filename = Path(oss_object_key).name
        local_tgz_path = local_extract_path / filename

        print(f"download from oss: {oss_object_key} -> {local_tgz_path}")
        bucket.get_object_to_file(oss_object_key, str(local_tgz_path))

        if not local_tgz_path.exists() or local_tgz_path.stat().st_size == 0:
            raise ValueError("file is empty or does not exist.")

        # 读取文件头部判断压缩格式
        with open(local_tgz_path, "rb") as f:
            header = f.read(4)
            if header.startswith(b"\x28\xb5\x2f\xfd"):  # zstd 格式
                subprocess.run(
                    ["tar", "-I", "zstd -d", "--strip-components=1", "-xf", str(local_tgz_path), "-C", str(local_extract_path)],
                    check=True
                )
            elif header.startswith(b"\x1f\x8b"):  # gzip 格式
                subprocess.run(
                    ["tar", "--strip-components=1", "-xzf", str(local_tgz_path), "-C", str(local_extract_path)],
                    check=True
                )
            else:
                raise ValueError("unsupported compression format. Only zstd and gzip are supported.")

        # 删除下载的 .tgz 文件
        local_tgz_path.unlink()
        print(f"download and extract completed: {local_extract_path}")

        return True

    except Exception as e:
        print(f"download or extract failed: {e}")
        return False      

if __name__ == "__main__":
    # 测试参数
    oss_file_key = "sim_engine/datasets/c-5c9d6928-4b4f-3864-b390-763380890923/images_origin/images_origin.tgz"
    local_dir = "/workspace/group_share/adc-sim/users/yangxh7/origin_img/c-5c9d6928-4b4f-3864-b390-763380890923/images_origin"

    # 调用函数
    success = download_and_extract_tgz_from_oss(
        oss_object_key=oss_file_key,
        local_extract_path=local_dir,
    )

    # 输出结果
    if success:
        print("✅ 文件下载并解压成功！")
    else:
        print("❌ 文件下载或解压失败。")