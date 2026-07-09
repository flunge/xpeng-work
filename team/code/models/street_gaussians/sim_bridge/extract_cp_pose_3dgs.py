import os
import sys
import re
import argparse
import csv
import json


def save_list_to_csv(data, file_path):
    try:
        with open(file_path, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            for row in data:
                writer.writerow(row)
        print(f"Data has been successfully saved to {file_path}.")
    except Exception as e:
        print(f"Failed to save data to {file_path}: {e}")



def extract_pose_and_time_with_camera_name_regex(file_path):
    result = []
    pattern = re.compile(r'pose\[(?P<index>\d+)\]: (?P<value>-?\d+\.\d+)|camera_time (?P<time>\d+)|camera_name (?P<name>\w+)')
    try:
        with open(file_path, 'r') as file:
            for line in file:
                pose = [None] * 7  # 初始化 pose 列表，有 7 个元素
                camera_name = None
                camera_time = None
                for match in pattern.finditer(line):
                    if match.group('index') is not None:
                        index = int(match.group('index'))
                        value = float(match.group('value'))
                        pose[index] = value
                    elif match.group('time') is not None:
                        camera_time = int(match.group('time'))
                    elif match.group('name') is not None:
                        camera_name = match.group('name')
                print(f"camera_name {camera_name} pose {pose} camera_time {camera_time}")

                result.append([camera_name]+pose + [camera_time])

    except FileNotFoundError:
        print(f"Error: The file at  {file_path} was not found.")
    except Exception as e:
        print(f"An error occurred: {e}")
    return result

# cmd : like this 
# http://cloud-sim-web-prod.xiaopeng.link/cloudsim-ci-sh/simulation/dds_stores/946467120/logs/sim_engine_out.log 
# python3 ./extract_cp_pose_3dgs.py --simengine_log_path /sandbox/simulation/simulation/auto_grader_v2/sim_engine_out.log 

if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--simengine_log_path", default='', type=str)
    args, unknown_args = parser.parse_known_args()
    # 获取目录
    directory = os.path.dirname(args.simengine_log_path)

    # 示例调用
    result_path = "result"
    result_path = os.path.join(directory, result_path)
    if not os.path.exists(result_path):
        os.mkdir(result_path)

    file_name = '1.txt'
    file_path = os.path.join(result_path, file_name)
    os.system(f'cat {args.simengine_log_path} | grep "3DGS] pose" |tee {file_path}')

    result = extract_pose_and_time_with_camera_name_regex(file_path)
    print(result)
    # 存储为 CSV 文件
    file_path = 'result_cp_pose_time.csv'
    file_path = os.path.join(result_path, file_path)
    save_list_to_csv(result, file_path)
    
    def generate_pose_json(result , result_path):
        file_path = 'local_pose.json'
        file_name = os.path.join(result_path, file_path)
        
        pose_infos = []
        for i, info in enumerate(result):
            if 'camera_front_fisheye' == info[0]:
                if i==0 or i==len(result):
                    continue
                front_info = result[i-1]
                back_info = result[i+1]
                
                if info[1] == front_info[1] or info[1] == back_info[1]:
                    pose_dict = {
                        "time_stamp":{
                            "nsec" : info[-1]
                        },
                        "smooth_pose_info":{
                            "local_pose": {
                                "p": {
                                    "x": info[5],
                                    "y": info[6],
                                    "z": info[7]
                                },
                                "q": {
                                    "w": info[1],
                                    "x": info[2],
                                    "y": info[3],
                                    "z": info[4]
                                }
                            }
                        }
                    }
                    pose_infos.append(pose_dict)
        with open(file_name, 'w') as file:
            json.dump(pose_infos, file)
            
              
    generate_pose_json(result , result_path)  
        
        