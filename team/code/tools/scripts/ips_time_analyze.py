import os
import re
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed


def extract_info_from_log_fast(file_path):
    """快速从log.txt文件中提取耗时和clip id（只读取最后几行）"""
    try:
        # 只读取文件的最后2KB，通常足够包含最后两行
        with open(file_path, 'rb') as file:
            file.seek(0, 2)  # 移动到文件末尾
            file_size = file.tell()
            read_size = min(2048, file_size)  # 读取最后2KB
            file.seek(max(0, file_size - read_size), 0)
            content = file.read().decode('utf-8', errors='ignore')
        
        lines = content.strip().split('\n')
        if len(lines) < 2:
            return None, None, None

        last_second_line = lines[-2].strip()
        last_line = lines[-1].strip()

        # 使用正则表达式匹配耗时和clip id
        time_pattern = r'reconic train time cost ([\d.]+) s'
        preprocessing_pattern = r'reconic gpu pipeline time cost ([\d.]+) s'
        clip_pattern = r'clip(c-[a-f0-9-]+)'

        time_match = re.search(time_pattern, last_line)
        preprocessing_match = re.search(preprocessing_pattern, last_second_line)
        clip_match = re.search(clip_pattern, last_line)

        if time_match and clip_match and preprocessing_match:
            time_cost = float(time_match.group(1)) / 3600.0  # 转小时
            preprocessing_cost = float(preprocessing_match.group(1)) / 3600.0
            clip_id = clip_match.group(1)
            return clip_id, time_cost, preprocessing_cost
        else:
            return None, None, None

    except Exception as e:
        return None, None, None


def find_log_files_optimized(directory, target_clips, target_folders=None):
    """优化版：查找log.txt文件，优先检查路径中是否包含目标clip_id"""
    priority_files = []  # 包含目标clip_id的文件（优先处理）
    other_files = []  # 其他文件
    target_clips_set = set(target_clips)
    found_clips = set()
    
    # 确定要搜索的文件夹列表
    if not target_folders:
        search_paths = [directory]
    else:
        search_paths = [
            os.path.join(directory, folder)
            for folder in target_folders
            if os.path.exists(os.path.join(directory, folder))
        ]

    # 在确定的路径中查找log.txt文件
    for path in search_paths:
        for root, dirs, files in os.walk(path):
            # 如果已经找到所有目标clips，提前停止
            if len(found_clips) >= len(target_clips_set):
                break
                
            for file in files:
                if file == 'log.txt':
                    file_path = os.path.join(root, file)
                    # 快速检查：如果路径中包含目标clip_id，优先处理
                    path_str = file_path
                    matched = False
                    for clip_id in target_clips_set:
                        if clip_id in path_str:
                            priority_files.append(file_path)
                            found_clips.add(clip_id)
                            matched = True
                            break
                    
                    if not matched:
                        # 路径中不包含目标clip_id，但也加入列表（可能log文件内容中有）
                        other_files.append(file_path)
            
            # 如果已经找到所有目标clips，提前停止
            if len(found_clips) >= len(target_clips_set):
                break

    # 优先文件在前，其他文件在后
    return priority_files + other_files


def collect_specific_clip_times(directory, target_clips, target_folders=None, max_workers=8):
    """从目录中收集指定clips的训练耗时和预处理耗时（单位：小时）- 并行优化版"""
    print("正在搜索log文件...")
    log_files = find_log_files_optimized(directory, target_clips, target_folders)
    
    if not log_files:
        print(f"在目录 {directory} 中未找到任何log.txt文件")
        return {}, {}

    print(f"找到 {len(log_files)} 个log文件，开始并行解析...")
    
    clip_time = {}  # clip_id -> train time (hours)
    clip_pre_time = {}  # clip_id -> preprocessing time (hours)
    target_clips_set = set(target_clips)
    found_count = 0

    # 使用多线程并行处理
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {executor.submit(extract_info_from_log_fast, log_file): log_file 
                          for log_file in log_files}
        
        for future in as_completed(future_to_file):
            clip_id, time_cost, preprocessing_cost = future.result()
            if clip_id is not None and clip_id in target_clips_set:
                if clip_id not in clip_time:  # 避免重复
                    clip_time[clip_id] = time_cost
                    clip_pre_time[clip_id] = preprocessing_cost
                    found_count += 1
                    # 如果已经找到所有目标clips，可以提前退出（但继续处理已提交的任务）
                    if found_count >= len(target_clips):
                        break

    return clip_time, clip_pre_time


def main():
    # 指定的clips列表
    target_clips = [
        "c-9a7c12cd-eee5-395f-9883-59de29f5a766",
        "c-11039866-5dfb-3c0a-a31e-78abce461a15"
    ]

    # 获取用户输入的log目录路径
    print("log目录示例: /workspace/group_share/adc-sim/users/yangxh7/logs/[model_version]/")
    log_dir = input("请输入log目录路径: ").strip()

    if not os.path.isdir(log_dir):
        print(f"错误: 路径 [{log_dir}] 不是一个有效的目录")
        return

    target_folders = [
        # 如需限定子目录，在这里填名字
    ]

    print(f"\n开始分析 {len(target_clips)} 个指定clips的耗时...")
    clip_time, clip_pre_time = collect_specific_clip_times(log_dir, target_clips, target_folders)

    if not clip_time:
        print(f"在目录 [{log_dir}] 中未找到任何指定clips的耗时信息")
        return

    # 找到的clips
    found_clips = sorted(clip_time.keys())
    not_found_clips = sorted(set(target_clips) - set(found_clips))

    print(f"\n找到 {len(found_clips)} 个clips的耗时信息")
    if not_found_clips:
        print(f"未找到 {len(not_found_clips)} 个clips: {', '.join(not_found_clips)}")

    # 打印详细信息
    print("\n" + "=" * 100)
    print(f"{'Clip ID':<50} {'预处理耗时(小时)':<20} {'训练耗时(小时)':<20}")
    print("=" * 100)

    for clip_id in found_clips:
        pre_time = clip_pre_time.get(clip_id, 0.0)
        train_time = clip_time.get(clip_id, 0.0)
        print(f"{clip_id:<50} {pre_time:<20.4f} {train_time:<20.4f}")

    # 统计信息
    if found_clips:
        pre_times = [clip_pre_time.get(c, 0.0) for c in found_clips]
        train_times = [clip_time.get(c, 0.0) for c in found_clips]

        avg_pre_time = float(np.mean(pre_times)) if pre_times else 0.0
        avg_train_time = float(np.mean(train_times)) if train_times else 0.0
        total_pre_time = float(np.sum(pre_times)) if pre_times else 0.0
        total_train_time = float(np.sum(train_times)) if train_times else 0.0

        print("\n" + "=" * 100)
        print("统计信息:")
        print(f"  找到的clips数量: {len(found_clips)}")
        print(f"  平均预处理耗时: {avg_pre_time:.4f} 小时")
        print(f"  平均训练耗时: {avg_train_time:.4f} 小时")
        print(f"  总预处理耗时: {total_pre_time:.4f} 小时")
        print(f"  总训练耗时: {total_train_time:.4f} 小时")
        print(f"  总耗时: {total_pre_time + total_train_time:.4f} 小时")
        print("=" * 100)


if __name__ == "__main__":
    main()
