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
                return None, None
            
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
                time_cost = time_match.group(1)
                preprocessing_cost = preprocessing_match.group(1)
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
        search_paths = [os.path.join(directory, folder) 
                       for folder in target_folders 
                       if os.path.exists(os.path.join(directory, folder))]
    
    # 在确定的路径中查找所有log.txt文件
    for path in search_paths:
        for root, dirs, files in os.walk(path):
            for file in files:
                if file == 'log.txt':
                    log_files.append(os.path.join(root, file))
    
    return log_files

def main():
    # 获取用户输入的目录路径
    print("log目录为/workspace/group_share/adc-sim/users/xuzh2/logs/[你提job填的model_version]/")
    directory = input("请输入log目录路径: ")
    
    if not os.path.isdir(directory):
        print("错误: 提供的路径不是一个有效的目录")
        return

    target_folders = [
    ]    
    
    # 查找所有log.txt文件
    log_files = find_log_files(directory, target_folders)
    
    if not log_files:
        print("在指定目录及其子目录中未找到任何log.txt文件")
        return
    
    print(f"找到了 {len(log_files)} 个log.txt文件")
    
    # 提取信息
    results = []
    results_preprocessing = []
    for log_file in log_files:
        clip_id, time_cost, preprocessing_cost = extract_info_from_log(log_file)
        if clip_id and time_cost:
            results.append([clip_id, float(time_cost) /3600])
            results_preprocessing.append([clip_id, float(preprocessing_cost) / 3600])
    
    # 按clip id排序结果
    results.sort(key=lambda x: x[0])
    results_preprocessing.sort(key=lambda x: x[0])
    timing_list = []
    timing_preprocessing_list = []

    # 输出到CSV文件
    if results and results_preprocessing:
        for result1 in results:
            timing_list.append(result1[1])

        for result2 in results_preprocessing:
            timing_preprocessing_list.append(result2[1])

        csv_filename = "log_analysis_results.csv"
        with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
            csv_writer = csv.writer(csvfile)
            csv_writer.writerow(["Clip ID", "Time Cost (hours)"])
            csv_writer.writerows(results)
        
        print(f"结果已保存到 {csv_filename}")
        
        # 在控制台也显示结果
        print(f"\n提取的结果: 平均{np.mean(timing_list)}")
        print(f"提取的预处理结果: 平均{np.mean(timing_preprocessing_list)}")
        print("Clip ID, Time Cost (s)")
        for idx in range(len(results)):
            print(f"{results[idx][0]}, {results[idx][1]}, {results_preprocessing[idx][1]}")
    else:
        print("未能从任何log.txt文件中提取到有效信息")

if __name__ == "__main__":
    main()