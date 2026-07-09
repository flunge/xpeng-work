import os
import numpy as np
import imageio.v2 as imageio
from imageio.plugins import ffmpeg
from glob import glob
import re

def extract_timestamp(filename):
    """从文件名中提取纳秒级时间戳"""
    match = re.match(r'^(\d+)', filename)
    if match:
        return int(match.group(1))
    else:
        raise ValueError(f"无法从文件名 {filename} 中提取时间戳")

def get_fps_from_timestamps(timestamps):
    """根据纳秒时间戳计算帧率"""
    if len(timestamps) < 2:
        return 30  # 若帧数不足，默认30fps
    
    # 计算相邻帧的时间差（纳秒）
    deltas = []
    for i in range(1, len(timestamps)):
        delta = timestamps[i] - timestamps[i-1]
        if delta > 0:  # 只考虑正的时间差
            deltas.append(delta)
    
    if not deltas:
        return 30  # 若没有有效时间差，默认30fps
    
    # 计算平均时间差（纳秒）并转换为秒
    avg_delta_ns = np.mean(deltas)
    avg_delta_sec = avg_delta_ns / 1e9
    
    # 帧率 = 1 / 平均时间间隔
    fps = 1 / avg_delta_sec
    return max(1, min(fps, 120))  # 限制帧率在1-120之间

def process_image_sequence(image_dir, filter_keyword=None):
    """处理图片序列，返回帧列表和计算的帧率
    filter_keyword: 可选参数，只处理包含该关键词的图片
    """
    # 获取所有图片路径
    image_extensions = ['*.jpg', '*.jpeg', '*.png', '*.tiff', '*.tif']
    image_paths = []
    for ext in image_extensions:
        image_paths.extend(glob(os.path.join(image_dir, ext)))
    
    if not image_paths:
        raise ValueError(f"在目录 {image_dir} 中未找到图片文件")
    
    # 过滤出包含关键词的图片（如果指定了关键词）
    if filter_keyword:
        filtered_paths = [path for path in image_paths if filter_keyword in os.path.basename(path)]
        if not filtered_paths:
            raise ValueError(f"在目录 {image_dir} 中未找到包含关键词 '{filter_keyword}' 的图片文件")
        image_paths = filtered_paths
        print(f"在目录 {image_dir} 中找到 {len(image_paths)} 个包含关键词 '{filter_keyword}' 的图片文件")
    
    # 提取文件名和时间戳并排序
    filename_timestamps = []
    for path in image_paths:
        filename = os.path.basename(path)
        try:
            timestamp = extract_timestamp(filename)
            filename_timestamps.append((timestamp, path))
        except ValueError as e:
            print(f"警告: {e}，已跳过该文件")
    
    if not filename_timestamps:
        raise ValueError(f"在目录 {image_dir} 中未找到有效的时间戳图片")
    
    # 按时间戳排序
    filename_timestamps.sort()
    sorted_paths = [path for _, path in filename_timestamps]
    timestamps = [ts for ts, _ in filename_timestamps]
    
    # 计算帧率
    fps = get_fps_from_timestamps(timestamps)
    print(f"根据时间戳计算的帧率: {fps:.2f} fps")
    
    # 读取所有图片
    frames = []
    for path in sorted_paths:
        img = imageio.imread(path)
        if img.dtype != np.uint8:
            img = (img * 255).astype(np.uint8)
        # 确保是3通道RGB格式
        if len(img.shape) == 2:  # 灰度图转RGB
            img = np.stack((img,)*3, axis=-1)
        elif img.shape[2] == 4:  # RGBA转RGB
            img = img[:,:,:3]
        frames.append(img)
    
    return frames, fps, timestamps

def align_and_concatenate_frames(original_frames, modified_frames, original_timestamps, modified_timestamps):
    """根据时间戳对齐两组帧并左右拼接"""
    combined_frames = []
    max_len = max(len(original_frames), len(modified_frames))
    o_idx, m_idx = 0, 0  # 两个序列的当前索引
    
    # 处理时间戳对齐
    while o_idx < len(original_frames) and m_idx < len(modified_frames):
        o_ts = original_timestamps[o_idx]
        m_ts = modified_timestamps[m_idx]
        
        # 取时间戳较近的一帧进行配对
        if abs(o_ts - m_ts) < 1e6:  # 时间差小于1毫秒视为同一时刻
            original_img = original_frames[o_idx]
            modified_img = modified_frames[m_idx]
            o_idx += 1
            m_idx += 1
        elif o_ts < m_ts:
            original_img = original_frames[o_idx]
            modified_img = modified_frames[m_idx]
            o_idx += 1
        else:
            original_img = original_frames[o_idx]
            modified_img = modified_frames[m_idx]
            m_idx += 1
        
        # 确保高度一致
        if original_img.shape[0] != modified_img.shape[0]:
            target_height = max(original_img.shape[0], modified_img.shape[0])
            # 使用OpenCV的resize进行更可靠的尺寸调整
            import cv2
            original_img = cv2.resize(original_img, (original_img.shape[1], target_height))
            modified_img = cv2.resize(modified_img, (modified_img.shape[1], target_height))
        
        # 左右拼接
        combined_frame = np.concatenate([original_img, modified_img], axis=1)
        combined_frames.append(combined_frame)
        
        # 打印进度
        if len(combined_frames) % 50 == 0:
            print(f"已处理 {len(combined_frames)}/{max_len} 帧")
    
    # 处理剩余的帧
    while o_idx < len(original_frames):
        original_img = original_frames[o_idx]
        modified_img = modified_frames[-1] if modified_frames else np.zeros_like(original_img)
        combined_frame = np.concatenate([original_img, modified_img], axis=1)
        combined_frames.append(combined_frame)
        o_idx += 1
    
    while m_idx < len(modified_frames):
        modified_img = modified_frames[m_idx]
        original_img = original_frames[-1] if original_frames else np.zeros_like(modified_img)
        combined_frame = np.concatenate([original_img, modified_img], axis=1)
        combined_frames.append(combined_frame)
        m_idx += 1
    
    return combined_frames

def main():
    # 配置参数 - 请根据实际情况修改
    original_frames_dir = "/workspace/duanzx@xiaopeng.com/code/DCCF/assets/c-b0b0a536-2131-3812-ac64-a99f1c1a62bf-22968102/cam0/composite_images"  # 原视频的图片帧目录
    modified_frames_dir = "/workspace/duanzx@xiaopeng.com/code/DCCF/assets/c-b0b0a536-2131-3812-ac64-a99f1c1a62bf-22968102/cam0/images"  # 修改后的视频图片帧目录
    output_video_path = "/workspace/duanzx@xiaopeng.com/code/DCCF/assets/c-b0b0a536-2131-3812-ac64-a99f1c1a62bf-22968102/cam0/comparison_video.mp4"  # 确保输出为MP4格式
    modified_filter_keyword = "harmonized"  # 只处理包含该关键词的修改后图片
    
    try:
        # 处理原视频图片序列（不使用过滤）
        print("正在处理原视频图片...")
        original_frames, original_fps, original_timestamps = process_image_sequence(
            original_frames_dir, 
            filter_keyword=None  # 原视频图片不过滤
        )
        
        # 处理修改后视频图片序列（只处理包含关键词的）
        print("正在处理修改后视频图片...")
        modified_frames, modified_fps, modified_timestamps = process_image_sequence(
            modified_frames_dir, 
            filter_keyword=None  # 只处理包含指定关键词的图片
        )
        
        # 取两个帧率的平均值作为输出帧率
        output_fps = (original_fps + modified_fps) / 2
        print(f"最终输出视频帧率: {output_fps:.2f} fps")
        
        # 对齐并拼接帧
        print("正在对齐并拼接视频帧...")
        combined_frames = align_and_concatenate_frames(
            original_frames, modified_frames,
            original_timestamps, modified_timestamps
        )
        
        # 强制使用FFMPEG插件写入视频
        writer = imageio.get_writer(
            output_video_path,
            format='FFMPEG',
            mode='I',
            fps=output_fps,
            codec='libx264',
            quality=8
        )
        
        for frame in combined_frames:
            writer.append_data(frame)
        
        writer.close()
        print(f"拼接后的视频已保存至: {output_video_path}")
        print("所有操作完成!")
        
    except Exception as e:
        print(f"发生错误: {str(e)}")

if __name__ == "__main__":
    main()
    