import os, sys
import yaml
import json


def get_timestamps(save_dir):
    yaml_path = os.path.join(save_dir, 'configs')
    config_file = os.path.join(yaml_path, 'config_sim.yaml')

    if os.path.isfile(config_file):
        print(f"{config_file} 存在。")
        with open(config_file, 'r') as file:
            config_data = yaml.safe_load(file)

            # 打印所有键名
            print(f"配置文件中的键: {list(config_data.keys())}")

            # 检查 'results' 字段
            if 'results' in config_data:
                results = config_data['results']
                # 检查 'timestamps' 字段
                if 'timestamps' in results:
                    timestamps = results['timestamps']
                    print(f"'timestamps' 字段的长度: {len(timestamps)}")

                    if timestamps:
                        start_timestamp = timestamps[0]
                        end_timestamp = timestamps[-1]
                        print(
                            f"{config_file} 时间戳: 开始 : {start_timestamp}, 结束 : {end_timestamp}"
                        )
                        return start_timestamp, end_timestamp
                    else:
                        print("'timestamps' 字段为空。")
                        return None
                else:
                    print("'timestamps' 字段未找到在 'results' 下。")
                    return None
            else:
                print("'results' 字段未找到。")
                return None
    else:
        print(f"{config_file} 不存在。")
        return None


def get_subrun_adapted_start_timestamp(adapted_start_timestamp):
    timestamp_list = list(adapted_start_timestamp)
    if timestamp_list[10] == '9' and timestamp_list[9] == '9':
        # 设置第9和第10位为0，第8位加1
        timestamp_list[10] = '0'
        timestamp_list[9] = '0'
        timestamp_list[8] = str(int(timestamp_list[8]) + 1)  # 将第8位设置为1
    elif timestamp_list[10] == '9':
        # 仅第10位为9，设置第10位为0，第8位加1
        timestamp_list[10] = '0'
        timestamp_list[9] = str(int(timestamp_list[9]) + 1)
    else:
        # 其他情况，简单加1
        timestamp_list[10] = str(int(timestamp_list[10]) + 1)
    adapted_start_timestamp = ''.join(timestamp_list)
    return adapted_start_timestamp


def load_canbus_topic_json(clip_path, key_field="time_stamp", timestamp_field="nsec"):
    json_path = os.path.join(clip_path, 'StateManagementTopic.json')
    if not os.path.exists(json_path):
        return None

    data_dict = {}

    with open(json_path, 'r', encoding='utf-8') as f:
        json_data = json.load(f)

    if isinstance(json_data, list):
        # 如果数据是列表格式，遍历每个项目
        for item in json_data:
            timestamp = item.get(key_field, {}).get(timestamp_field)
            if timestamp is not None:
                data_dict[timestamp] = item
    elif isinstance(json_data, dict):
        # 如果数据是单个对象，直接提取时间戳
        timestamp = json_data.get(key_field, {}).get(timestamp_field, 0)
        data_dict[timestamp] = json_data
    else:
        # 如果数据既不是列表也不是字典，抛出异常
        raise ValueError(f"Unexpected data format in JSON: {type(json_data)}")

    print(f"Loaded {len(data_dict)} items from {json_path}")
    return data_dict


def get_takeover_timestamps(state_management_data, adapted_start_timestamp):
    """
    根据SM topic数据解析接管状态时间戳，并根据规则计算trigger timestamp

    Args:
        state_management_data (dict): 从SM topic解析出的数据，以时间戳为键
        adapted_start_timestamp (int): 起始时间戳（纳秒）

    Returns:
        list: 接管状态的时间戳列表
    """
    takeover_timestamps = []

    # 解析state_management_data中的接管状态
    for timestamp, data in state_management_data.items():
        mode = data.get('rdmodulecom_ngpflag', -1)  # 获取NGP模式

        is_ngp_mode = mode in [3, 6]  # kNGPMode=3, kCityNGPMode=6
        lka_mode = data.get('rdmodulecom_LKA_MODE', -1)
        is_lcc_mode = lka_mode == 5  # kLCCMode=5

        cur_auto_mode = is_ngp_mode and is_lcc_mode

        # 如果不是自动驾驶模式 → 就是接管状态
        if not cur_auto_mode:
            takeover_timestamps.append(int(timestamp))

    # 排序接管时间戳
    takeover_timestamps.sort()
    return takeover_timestamps


def get_series_time_range(input_time_range, time_delta):
    # 对输入的时间戳进行排序
    input_time_range.sort()

    series_time_range = []

    if not input_time_range:
        return series_time_range

    range_begin_ind = 0

    for i in range(1, len(input_time_range)):
        if input_time_range[i] - input_time_range[i - 1] <= time_delta:
            continue
        else:
            series_time_range.append(
                [input_time_range[range_begin_ind], input_time_range[i - 1]]
            )
            range_begin_ind = i

    # 添加最后一个时间段
    series_time_range.append([input_time_range[range_begin_ind], input_time_range[-1]])

    return series_time_range




def trigger_time_rule(issue_time, offset_config, start_timestamp, current_trigger_timestamp):
    """
    未接管场景下，根据分类偏移规则计算trigger timestamp

    Args:
        issue_time (int/float/None): 问题发生的相对时间（秒）
        offset_config (dict): 分类偏移配置，包含"takeover"和"issue"键
        start_timestamp (int): 起始时间戳（纳秒）
        current_trigger_timestamp (int): 当前trigger timestamp（纳秒），作为fallback

    Returns:
        int: 计算出的trigger timestamp（纳秒）
    """
    if issue_time is None:
        print(f"issue_time is None, using current_trigger_timestamp: {current_trigger_timestamp}")
        return current_trigger_timestamp

    offset = offset_config["issue"]
    print(f"Matched issue offset: {offset}s")

    new_trigger = current_trigger_timestamp
    if issue_time > offset:
        new_trigger = int(start_timestamp) + int((issue_time - offset) * 1e9)
        print(f"issue_time: {issue_time}s, new_trigger: {new_trigger}")
    if (new_trigger - int(start_timestamp)) < 2 * 1000000000:
        new_trigger = current_trigger_timestamp
        print(f"new_trigger too close to start, fallback to start+10s: {new_trigger}")
    return new_trigger


def _resolve_takeover_trigger(takeover_time_ranges, adapted_start_timestamp, adapted_end_timestamp, issue_time, offset_config):
    """
    根据接管时间段和分类规则判断是否使用接管时间计算trigger timestamp

    Args:
        takeover_time_ranges (list): 接管时间段列表
        adapted_start_timestamp (int): 起始时间戳（纳秒）
        adapted_end_timestamp (int): 结束时间戳（纳秒）
        issue_time (int/float/None): 问题发生的相对时间（秒）
        offset_config (dict): 分类偏移配置

    Returns:
        int/None: 接管trigger timestamp，若不使用接管时间则返回None
    """
    takeover_offset = offset_config["takeover"]
    takeover_ref_time = takeover_time_ranges[-1][0]

    # 判断接管时间是否在 [start + issue_time, end] 范围内
    if issue_time is not None:
        issue_start = int(adapted_start_timestamp) + int(issue_time * 1e9)
        if not (issue_start <= takeover_ref_time <= int(adapted_end_timestamp)):
            print(f"Takeover {takeover_ref_time} outside issue range [{issue_start}, {adapted_end_timestamp}], falling back to issue rule")
            return None
        print(f"Takeover {takeover_ref_time} within issue range [{issue_start}, {adapted_end_timestamp}], using takeover rule (offset={takeover_offset}s)")

    # 计算接管trigger: 接管时间 - 偏移量
    adapted_start_timestamp = int(adapted_start_timestamp)
    trigger_timestamp = takeover_ref_time - takeover_offset * 1000000000

    # 保底：trigger距start不足2秒则回退到start+10s
    if trigger_timestamp - adapted_start_timestamp < 2 * 1000000000:
        trigger_timestamp = adapted_start_timestamp + 10 * 1000000000
        print(f"takeover trigger too close to start, fallback to start+10s")

    return trigger_timestamp


def resolve_trigger_timestamp(clip_path, adapted_start_timestamp, adapted_end_timestamp, issue_time=None, issue_description=None, offset_map=None):
    """
    从SM topic获取trigger timestamp，如果没有SM topic或接管时间为空，
    则根据issue_time和issue_description命中规则计算trigger time

    Args:
        clip_path (str): 包含SM topic数据的JSON文件路径
        adapted_start_timestamp (int): 起始时间戳（纳秒）
        adapted_end_timestamp (int): 结束时间戳（纳秒）
        issue_time (int/float/None, optional): 问题发生的相对时间（秒）
        issue_description (str/None, optional): 问题描述类别，用于匹配offset_map
        offset_map (dict, optional): 分类偏移配置，从config.trigger_time_offset_map获取

    Returns:
        int: 计算出的trigger timestamp（纳秒）
    """
    # 初始化trigger_timestamp为start+10s
    trigger_timestamp = int(adapted_start_timestamp) + 10 * 1000000000

    # 查找分类规则
    offset_config = offset_map.get(issue_description) if offset_map else None
    if offset_config is None:
        print(f"No matching rule for '{issue_description}', using default trigger (start+10s)")
        return trigger_timestamp

    # 尝试用接管时间
    state_management_data = load_canbus_topic_json(clip_path)
    if state_management_data:
        takeover_timestamps = get_takeover_timestamps(
            state_management_data, adapted_start_timestamp
        )
        if takeover_timestamps:
            takeover_time_ranges = get_series_time_range(
                takeover_timestamps, int(0.1 * 1000000000)
            )
            print(f"Total takeover timestamps: {len(takeover_timestamps)}")
            for i, (start, end) in enumerate(takeover_time_ranges):
                print(
                    f"Takeover range {i+1}: Start={start}, End={end}, Duration={(end-start)/1000000000:.2f}s"
                )

            takeover_result = _resolve_takeover_trigger(
                takeover_time_ranges, adapted_start_timestamp, adapted_end_timestamp,
                issue_time, offset_config
            )
            if takeover_result is not None:
                trigger_timestamp = takeover_result
                print(f"Takeover trigger: {trigger_timestamp}")
                return trigger_timestamp

    # 没有有效接管时间，按issue规则
    trigger_timestamp = trigger_time_rule(
        issue_time, offset_config, adapted_start_timestamp, trigger_timestamp
    )

    return trigger_timestamp


if __name__ == "__main__":
    root = "/workspace/yangxh7@xiaopeng.com/codes/3dgs/omnire_joint_trainning/output/"
    targets = {
        "c-114a3a61": "runC_39f",
        "c-2ae824c3": "runC_39f",
        "c-d0f02235": "runC_39f",
    }
    results = {}
    for target, exp in targets.items():
        save_dir = os.path.join(root, target, exp)
        start_timestamp, end_timestamp = get_timestamps(save_dir)
        adapted_start_timestamp = get_subrun_adapted_start_timestamp(start_timestamp)
        adapted_end_timestamp = end_timestamp
        results[target] = {
            "adapted_start_timestamp": adapted_start_timestamp,
            "adapted_end_timestamp": adapted_end_timestamp,
        }
    print(f"[INFO] results {results}")