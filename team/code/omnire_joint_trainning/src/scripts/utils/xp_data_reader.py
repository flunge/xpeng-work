import numpy as np
import os
import json

class XP_data_reader(object):
    
    def __init__(self, data_root="/home/par-jiagangzhu/JijiaWork/xp_data/processed_data"):
        self.data_root = data_root
        self.data_ids = [f for f in os.listdir(self.data_root)]

    def read_json(self, calib_file_path):
        try:
            with open(calib_file_path, 'r') as file:
                data = json.load(file)
            print("JSON 数据加载成功")
            return data
        except FileNotFoundError:
            print("文件未找到，请检查文件路径")
        except json.JSONDecodeError:
            print("JSON 格式错误，请检查文件内容")
    

if __name__ == "__main__":
    data_reader = XP_data_reader()
    calib_data = data_reader.read_calib("/home/par-jiagangzhu/JijiaWork/xp_data/processed_data/c-fffbbe20-7c67-3729-a449-f26bc0e9f67e/calib.json")
    print(calib_data)