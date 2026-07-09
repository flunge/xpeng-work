import os
import re
import csv
import numpy as np


def extract_info_from_log(file_path):
    """从log.txt文件中提取耗时和clip id"""
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()
            if not lines:
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
                print(f"警告: 无法从文件 {file_path} 中提取信息")
                return None, None, None

    except Exception as e:
        print(f"处理文件 {file_path} 时出错: {e}")
        return None, None, None


def find_log_files(directory, target_folders=None):
    """递归查找目录中的所有log.txt文件，可选择性地只在指定文件夹中查找"""
    log_files = []

    # 确定要搜索的文件夹列表
    if not target_folders:
        # 如果没有指定目标文件夹，则搜索整个目录
        search_paths = [directory]
    else:
        # 如果指定了目标文件夹，则只搜索这些文件夹（如果存在）
        search_paths = [
            os.path.join(directory, folder)
            for folder in target_folders
            if os.path.exists(os.path.join(directory, folder))
        ]

    # 在确定的路径中查找所有log.txt文件
    for path in search_paths:
        for root, dirs, files in os.walk(path):
            for file in files:
                if file == 'log.txt':
                    log_files.append(os.path.join(root, file))

    return log_files


def collect_clip_times(directory, target_folders=None):
    """从一个目录收集所有clip的训练耗时和预处理耗时（单位：小时）"""
    log_files = find_log_files(directory, target_folders)
    if not log_files:
        print(f"在目录 {directory} 中未找到任何log.txt文件")
        return {}, {}

    clip_time = {}  # clip_id -> train time (hours)
    clip_pre_time = {}  # clip_id -> preprocessing time (hours)

    for log_file in log_files:
        clip_id, time_cost, preprocessing_cost = extract_info_from_log(log_file)
        if clip_id is not None and time_cost is not None:
            clip_time[clip_id] = time_cost
            clip_pre_time[clip_id] = preprocessing_cost

    return clip_time, clip_pre_time


def main():
    # 获取用户输入的两个目录路径
    print("log目录示例: /workspace/group_share/adc-sim/users/yangxh7/logs/[model_version]/")
    dir1 = input("请输入第一个log目录路径: ").strip()
    dir2 = input("请输入第二个log目录路径: ").strip()

    if not os.path.isdir(dir1):
        print(f"错误: 路径1 [{dir1}] 不是一个有效的目录")
        return
    if not os.path.isdir(dir2):
        print(f"错误: 路径2 [{dir2}] 不是一个有效的目录")
        return

    target_folders = [
        # 如需限定子目录，在这里填名字
    ]

    print("\n开始统计第一个目录的clip耗时...")
    clip_time_1, clip_pre_time_1 = collect_clip_times(dir1, target_folders)

    print("\n开始统计第二个目录的clip耗时...")
    clip_time_2, clip_pre_time_2 = collect_clip_times(dir2, target_folders)

    if not clip_time_1:
        print(f"目录1 [{dir1}] 中未提取到任何有效clip耗时信息")
        return
    if not clip_time_2:
        print(f"目录2 [{dir2}] 中未提取到任何有效clip耗时信息")
        return

    # 找到两个目录下同名的clip
    common_clips = sorted(set(clip_time_1.keys()) & set(clip_time_2.keys()))

    if not common_clips:
        print("两个目录下没有同名的clip，无法比较")
        return

    print(f"\n两个目录下共有 {len(common_clips)} 个同名clip用于比较")

    times_1 = [clip_time_1[c] for c in common_clips]
    times_2 = [clip_time_2[c] for c in common_clips]

    pre_times_1 = [clip_pre_time_1[c] for c in common_clips if c in clip_pre_time_1]
    pre_times_2 = [clip_pre_time_2[c] for c in common_clips if c in clip_pre_time_2]

    avg_time_1 = float(np.mean(times_1)) if times_1 else 0.0
    avg_time_2 = float(np.mean(times_2)) if times_2 else 0.0

    avg_pre_time_1 = float(np.mean(pre_times_1)) if pre_times_1 else 0.0
    avg_pre_time_2 = float(np.mean(pre_times_2)) if pre_times_2 else 0.0

    print("\n===== 训练耗时(小时)对比（只统计两个目录均存在的clip）=====")
    print(f"目录1 [{dir1}] 平均训练耗时: {avg_time_1:.4f} 小时, clip数量: {len(times_1)}")
    print(f"目录2 [{dir2}] 平均训练耗时: {avg_time_2:.4f} 小时, clip数量: {len(times_2)}")

    print("\n===== 预处理耗时(小时)对比（只统计两个目录均存在的clip）=====")
    print(f"目录1 [{dir1}] 平均预处理耗时: {avg_pre_time_1:.4f} 小时, clip数量: {len(pre_times_1)}")
    print(f"目录2 [{dir2}] 平均预处理耗时: {avg_pre_time_2:.4f} 小时, clip数量: {len(pre_times_2)}")

    # 将详细对比结果写入CSV
    csv_filename = "log_compare_results.csv"
    with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
        csv_writer = csv.writer(csvfile)
        csv_writer.writerow([
            "Clip ID",
            "Dir1 Train Time (hours)",
            "Dir2 Train Time (hours)",
            "Train Time Diff (Dir2-Dir1, hours)",
            "Dir1 Preprocess Time (hours)",
            "Dir2 Preprocess Time (hours)",
            "Preprocess Time Diff (Dir2-Dir1, hours)",
        ])

        for cid in common_clips:
            t1 = clip_time_1.get(cid, 0.0)
            t2 = clip_time_2.get(cid, 0.0)
            p1 = clip_pre_time_1.get(cid, 0.0)
            p2 = clip_pre_time_2.get(cid, 0.0)
            csv_writer.writerow([
                cid,
                t1,
                t2,
                t2 - t1,
                p1,
                p2,
                p2 - p1,
            ])

    print(f"\n详细对比结果已保存到 {csv_filename}")


if __name__ == "__main__":
    main()