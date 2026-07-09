
import subprocess
import os


def generate_timestamp_records(dds_metadata_path: str, event_path: str):
    """生成timestamp_records.json"""
    # 使用run_camera_decoder函数的json模式来生成timestamp_records.json
    run_camera_decoder(dds_metadata_path, event_path, "json")


def decode_h265_to_png(dds_metadata_path: str, images_origin_path: str):
    """h265解析为png"""
    # 使用run_camera_decoder函数的png模式来将h265解析为png
    run_camera_decoder(dds_metadata_path, images_origin_path, "png")



def update_h265_results_to_dds(dds_metadata_path: str, output_dds_path: str, h265_input_path: str):
    """将h265的结果更新到dds中"""
    
    # 调用run_camera_decoder函数的replace模式
    run_camera_decoder(dds_metadata_path, output_dds_path, "replace", h265_input_path=h265_input_path)


def run_camera_decoder(input_metadata: str, output_path: str, mode: str, h265_input_path: str = None):
    """
    根据 task_info 中的信息调用 camera_video_xp5_decoder
    
    Args:
        input_metadata (str): 输入元数据路径
        output_path (str): 输出路径
        mode (str): 运行模式 (json, png, replace)
        h265_input_path (str, optional): H265文件输入路径，仅在replace模式下使用
    """
    
    # 检查输入路径是否存在
    if not os.path.exists(input_metadata):
        raise ValueError(f"输入路径不存在: {input_metadata}")
        return False
    
    print(f"  输入路径: {input_metadata}")
    print(f"  输出路径: {output_path}")
    

    print(f"    运行模式: {mode}")
    
    decoder_path = os.environ.get("CAMERA_VIDEO_DECODER", "/usr/local/bin/camera_video_xp5_decoder")
    # 构建命令
    cmd = [
        decoder_path,
        f"--input_path={input_metadata}",
        f"--output_path={output_path}",
        f"--mode={mode}"
    ]
    
    # 对于 replace 模式，需要额外的参数
    if mode == "replace" and h265_input_path:
        cmd.extend([f"--h265_input_path={h265_input_path}"])
    
    # 执行命令
    try:
        print(f"    执行命令: {' '.join(cmd)}")
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"    {mode} 模式执行成功")
    except subprocess.CalledProcessError as e:
        print(f"    错误: {mode} 模式执行失败")
        print(f"    返回码: {e.returncode}")
        if e.stdout:
            print(f"    标准输出: {e.stdout}")
        if e.stderr:
            print(f"    标准错误: {e.stderr}")
        raise
    except Exception as e:
        print(f"    错误: {mode} 模式执行失败: {e}")
        raise



def png_to_video(images_origin_path: str, rendered_redistort_rgb_path: str, output_video_path: str):
    """
    通过ffmpeg分别把原始图像与渲染图像合成一个分屏视频
    左边是原始图像png合成的视频，右边是渲染后图像png合成的视频
    """
    
    # 定义输出目录
    os.makedirs(output_video_path, exist_ok=True)
    
    # 摄像头列表
    cameras = ["cam0", "cam2", "cam3", "cam4", "cam5", "cam6", "cam7"]
    
    for camera in cameras:
        # 定义输入路径
        original_camera_path = os.path.join(images_origin_path, camera)
        rendered_camera_path = os.path.join(rendered_redistort_rgb_path, camera)
        
        # 检查路径是否存在
        if not os.path.exists(original_camera_path):
            print(f"警告: 原始图像路径不存在 {original_camera_path}")
            continue
            
        if not os.path.exists(rendered_camera_path):
            print(f"警告: 渲染图像路径不存在 {rendered_camera_path}")
            continue
        
        # 输出视频文件路径
        output_video_file = os.path.join(output_video_path, f"{camera}.mp4")
        
        # 使用ffmpeg进行分屏视频合成
        cmd = [
            "ffmpeg",
            "-y",  # 覆盖输出文件
            "-framerate", "30",  # 设置帧率
            "-pattern_type", "glob",
            "-i", f"{original_camera_path}/*.png",  # 原始图像输入
            "-framerate", "30",
            "-pattern_type", "glob",
            "-i", f"{rendered_camera_path}/*.png",  # 渲染图像输入
            "-filter_complex", 
            "[0:v][1:v]hstack=inputs=2",
            "-c:v", "hevc_nvenc",
            "-r", "30",  # 输出帧率
            "-pix_fmt", "yuv420p",
            output_video_file
        ]
        
        print(f"正在合成 {camera} 视频...")
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            print(f"{camera} 视频合成完成: {output_video_file}")
        except subprocess.CalledProcessError as e:
            print(f"{camera} 视频合成失败: {e}")
            if e.stderr:
                print(f"错误信息: {e.stderr}")        