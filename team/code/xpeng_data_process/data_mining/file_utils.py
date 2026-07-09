import os
import json
import yaml

def read_json_file(file_path):     
    with open(file_path, 'r') as file:
        json_data = json.load(file)
    return json_data

def write_json_file(file_path, json_data):
    with open(file_path, 'w+') as file:
        json.dump(json_data, file, indent=4)

def read_yaml_file(yaml_path):
    with open(yaml_path, 'r') as f:
        yaml_data = yaml.safe_load(f)
    return yaml_data    

def write_yaml_file(yaml_data, yaml_path):
    with open(yaml_path, 'w') as f:
        yaml.dump(yaml_data, f, sort_keys=False)

def get_folder_names(path):
    folder_names = []
    for foldername in os.listdir(path):
        folder_path = os.path.join(path, foldername)
        if os.path.isdir(folder_path) and not foldername.startswith('.'):
            folder_names.append(foldername)
    return folder_names

def get_file_count(path):
    file_count = 0
    for foldername in os.listdir(path):
        folder_path = os.path.join(path, foldername)
        if os.path.isfile(folder_path):
            file_count += 1
    return file_count  

def get_json_files(path):
    json_files = []
    for root, dirs, files in os.walk(path):
        for file in files:
            if file.endswith('.json'):
                json_files.append(os.path.join(root, file))
    return json_files