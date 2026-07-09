# -*- coding: utf-8 -*-
import json
from ctypes import c_char_p, c_double, c_int, c_bool, c_uint64, POINTER
from .ctypes_utilis import (  # 导入 ctypes_utilis.py 中的必要类和函数
    CDataset, CDatasetNums, CImage, CLandmark, CPose, CVisibility, CCamera, CLidar,
    CPointMatch, CCrossMatch, convert_images_to_ctypes, convert_landmarks_to_ctypes,
    convert_poses_to_ctypes, convert_visibilities_to_ctypes, convert_cameras_to_ctypes,
    convert_lidars_to_ctypes, convert_point_matches_to_ctypes, convert_cross_matches_to_ctypes,
    convert_clouds_to_ctypes, convert_images_from_ctypes, convert_landmarks_from_ctypes,
    convert_poses_from_ctypes, convert_visibilities_from_ctypes, convert_cameras_from_ctypes,
    convert_lidars_from_ctypes, convert_point_matches_from_ctypes, convert_cross_matches_from_ctypes,
    convert_clouds_from_ctypes
)

class CTypesJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        # 处理 CDatasetNums
        if isinstance(obj, CDatasetNums):
            return {
                'num_images': obj.num_images,
                'num_landmarks': obj.num_landmarks,
                'num_poses': obj.num_poses,
                'num_visibilities': obj.num_visibilities,
                'num_cameras': obj.num_cameras,
                'num_lidars': obj.num_lidars,
                'num_point_matches': obj.num_point_matches,
                'num_cross_matches': obj.num_cross_matches,
                'num_clouds': obj.num_clouds
            }

        # 处理 CDataset
        elif isinstance(obj, CDataset):
            main_sensor = obj.main_sensor.decode('utf-8') if obj.main_sensor else None
            images = convert_images_from_ctypes(obj.images, obj.nums.num_images) if obj.images else []
            landmarks = convert_landmarks_from_ctypes(obj.landmarks, obj.nums.num_landmarks) if obj.landmarks else []
            poses = convert_poses_from_ctypes(obj.poses, obj.nums.num_poses) if obj.poses else []
            visibilities = convert_visibilities_from_ctypes(obj.visibilities, obj.nums.num_visibilities) if obj.visibilities else []
            cameras = convert_cameras_from_ctypes(obj.cameras, obj.nums.num_cameras) if obj.cameras else []
            lidars = convert_lidars_from_ctypes(obj.lidars, obj.nums.num_lidars) if obj.lidars else []
            point_matches = convert_point_matches_from_ctypes(obj.point_matches, obj.nums.num_point_matches) if obj.point_matches else []
            cross_matches = convert_cross_matches_from_ctypes(obj.cross_matches, obj.nums.num_cross_matches) if obj.cross_matches else []
            clouds = convert_clouds_from_ctypes(obj.clouds, obj.nums.num_clouds) if obj.clouds else []
            return {
                'main_sensor': main_sensor,
                'images': images,
                'landmarks': landmarks,
                'poses': poses,
                'visibilities': visibilities,
                'cameras': cameras,
                'lidars': lidars,
                'point_matches': point_matches,
                'cross_matches': cross_matches,
                'clouds': clouds,
                'time_delay': obj.time_delay
            }

        # 处理 c_char_p
        elif isinstance(obj, c_char_p):
            return obj.decode('utf-8') if obj else None

        # 处理 c_double 数组
        elif isinstance(obj, (c_double * 3)) or isinstance(obj, (c_double * 9)):
            return list(obj)

        # 处理其他 ctypes 指针类型
        elif isinstance(obj, POINTER):
            return None

        # 回退到默认 JSON 编码器
        return super().default(obj)

def dump_dataset_to_json(dataset, indent=None):
    """
    将 CDataset 结构体序列化为JSON字符串
    :param dataset: CDataset 结构体实例
    :param indent: JSON格式化缩进（可选，默认None）
    :return: JSON字符串
    """
    return json.dumps(dataset, cls=CTypesJSONEncoder, indent=indent)

def dump_dataset_to_json_file(dataset, file_path, indent=None):
    """
    将 CDataset 结构体序列化为JSON并写入文件
    :param dataset: CDataset 结构体实例
    :param file_path: 目标JSON文件路径
    :param indent: JSON格式化缩进（可选，默认None）
    """
    try:
        json_str = dump_dataset_to_json(dataset, indent=indent)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(json_str)
    except IOError as e:
        raise IOError(f"无法写入文件 {file_path}: {str(e)}")
    except Exception as e:
        raise Exception(f"序列化或写入JSON时出错: {str(e)}")

def load_dataset_from_json(json_data):
    """
    从JSON数据加载并转换为CDataset结构体
    :param json_data: JSON字符串或Python字典
    :return: CDataset 结构体实例
    """
    if isinstance(json_data, str):
        data = json.loads(json_data)
    else:
        data = json_data

    dataset_nums = CDatasetNums(
        num_images=len(data.get('images', [])),
        num_landmarks=len(data.get('landmarks', [])),
        num_poses=len(data.get('poses', [])),
        num_visibilities=len(data.get('visibilities', [])),
        num_cameras=len(data.get('cameras', [])),
        num_lidars=len(data.get('lidars', [])),
        num_point_matches=len(data.get('point_matches', [])),
        num_cross_matches=len(data.get('cross_matches', [])),
        num_clouds=len(data.get('clouds', []))
    )

    dataset = CDataset()
    main_sensor = data.get('main_sensor')
    dataset.main_sensor = main_sensor.encode('utf-8') if main_sensor else None
    dataset.images = convert_images_to_ctypes(data.get('images', [])) if data.get('images') else None
    dataset.landmarks = convert_landmarks_to_ctypes(data.get('landmarks', [])) if data.get('landmarks') else None
    dataset.poses = convert_poses_to_ctypes(data.get('poses', [])) if data.get('poses') else None
    dataset.visibilities = convert_visibilities_to_ctypes(data.get('visibilities', [])) if data.get('visibilities') else None
    dataset.cameras = convert_cameras_to_ctypes(data.get('cameras', [])) if data.get('cameras') else None
    dataset.lidars = convert_lidars_to_ctypes(data.get('lidars', [])) if data.get('lidars') else None
    dataset.point_matches = convert_point_matches_to_ctypes(data.get('point_matches', [])) if data.get('point_matches') else None
    dataset.cross_matches = convert_cross_matches_to_ctypes(data.get('cross_matches', [])) if data.get('cross_matches') else None
    dataset.clouds = convert_clouds_to_ctypes(data.get('clouds', [])) if data.get('clouds') else None
    dataset.time_delay = data.get('time_delay', 0.0)
    dataset.nums = dataset_nums

    return dataset

def load_dataset_from_json_file(file_path):
    """
    从JSON文件加载并转换为CDataset结构体
    :param file_path: JSON文件路径
    :return: CDataset 结构体实例
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        return load_dataset_from_json(json_data)
    except IOError as e:
        raise IOError(f"无法读取文件 {file_path}: {str(e)}")
    except Exception as e:
        raise Exception(f"解析JSON或转换数据时出错: {str(e)}")

# 使用示例
def test_dataset_json_utils():
    # 示例数据
    data_list = [
        {
            'camera_name': 'cam2',
            'time': 1673195284742401792,
            'points_undistorted': [
                [857.9024047851562, 1336.4898681640625],
                [1204.8282470703125, 1319.7369384765625]
            ]
        },
        {
            'camera_name': 'cam3',
            'time': 1673195284742401793,
            'points_undistorted': [
                [1107.47265625, 1342.04833984375],
                [947.9561767578125, 1281.47802734375],
                [1207.47265625, 1342.04833984375]
            ]
        }
    ]

    # 创建 CDatasetNums 实例
    dataset_nums = CDatasetNums(
        num_images=2,
        num_landmarks=0,
        num_poses=0,
        num_visibilities=0,
        num_cameras=0,
        num_lidars=0,
        num_point_matches=0,
        num_cross_matches=0,
        num_clouds=0
    )

    # 创建 CDataset 实例
    dataset = CDataset(
        main_sensor="cam2".encode('utf-8'),
        images=convert_images_to_ctypes(data_list),
        landmarks=None,
        poses=None,
        visibilities=None,
        cameras=None,
        lidars=None,
        point_matches=None,
        cross_matches=None,
        clouds=None,
        time_delay=0.1
    )
    dataset.nums = dataset_nums

    # 写入JSON文件
    json_file_path = 'dataset.json'
    dump_dataset_to_json_file(dataset, json_file_path, indent=2)

    # 验证：加载文件并打印 images 字段
    loaded_dataset = load_dataset_from_json_file(json_file_path)
    if loaded_dataset.images:
        images_data = convert_images_from_ctypes(loaded_dataset.images, loaded_dataset.nums.num_images)
        for img in images_data:
            print(f"Camera Name: {img['camera_name']}")
            print(f"Time: {img['time']}")
            print(f"Points: {img['points_undistorted']}")
            print()


if __name__ == '__main__':
    test_dataset_json_utils()
    # 这里可以添加更多测试代码来验证其他功能
    # 例如：load_dataset_from_json, dump_dataset_to_json等