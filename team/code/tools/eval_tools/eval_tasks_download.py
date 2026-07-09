import argparse
import json
import os
import time
import requests
from urllib.parse import urljoin

SCENARIO_INFO_BATCH_SIZE = 50
SCENARIO_INFO_TIMEOUT = 120
SCENARIO_INFO_MAX_RETRIES = 3

####################################################
# 凭据（x-token / x-account）与任务列表不再写死在代码中：
#   - 命令行：通过 --token / --user 及 --candidate / --baseline 传入；
#   - 被 Agent 调用：由 tse.integrations.simworld_tools 以函数参数传入。
# 仅保留输出根目录的默认值，可用 --output-root 覆盖。
OUTPUT_ROOT = '/workspace/difix3D_train/eval_new/'
####################################################


def _chunked(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def download_all_task_data(jobs, token, user, output_root=OUTPUT_ROOT):
    """下载所有任务类型的数据"""
    all_task_data = {}
    
    for task_type in jobs.keys():
        print(f"正在处理任务类型: {task_type}")
        scenario_task_map = {}
        for task_id in jobs[task_type]:
            scenario_task_map = load_data_from_api(task_id, token, user)
            
            if not scenario_task_map:
                print(f"没有找到 {task_type} 的数据")
                continue
            
            print(f"找到 {len(scenario_task_map)} 个任务")
            download_fm_output_files(task_type, scenario_task_map, token, user,
                                     output_root=output_root)
            scenario_task_map.update(scenario_task_map)
        
        all_task_data[task_type] = scenario_task_map
    
    return all_task_data

def download_fm_output_files(task_type, scenario_task_map, token, user,
                             output_root=OUTPUT_ROOT):
    """下载fm_output_comparison.json文件"""
    # 创建以task_type命名的文件夹
    ckpt_folder = "sim_" + task_type
    folder_name = os.path.join(output_root, ckpt_folder)
    os.makedirs(folder_name, exist_ok=True)
    
    base_url = "https://cloud-sim-web-prod.xiaopeng.link/cloudsim-ci-sh/on_target_pytorch/dds_stores/"
    scenario_info = query_3dgs_scenario_info_simple(
        list(scenario_task_map.keys()), token, user)

    for scenario_id, e2e_task_id in scenario_task_map.items():
        # 构造下载URL
        file_url = urljoin(base_url, f"{e2e_task_id}/fm_output_comparison.json")
        
        # 设置文件名
        clip_id = scenario_info[scenario_id]
        filename = f"{clip_id}.json"
        file_path = os.path.join(folder_name, filename)
        
        # 下载文件
        try:
            response = requests.get(file_url)
            if response.status_code == 200:
                with open(file_path, 'wb') as f:
                    f.write(response.content)
                print(f"成功下载: {filename}")
            else:
                print(f"下载失败 {filename}: HTTP {response.status_code}")
        except Exception as e:
            print(f"下载 {filename} 时出错: {str(e)}")


def get_task_results(task_id, token, user):
    """通过API获取任务结果"""
    url = 'https://cloudsim.xiaopeng.link/simulation/pytorch_test/query_e2e_job_by_id/'
    headers = {
        'accept': '*/*',
        'accept-language': 'zh-CN,zh;q=0.9',
        'content-type': 'text/plain;charset=UTF-8',
        'origin': 'https://cloudsim.xiaopeng.link',
        'referer': 'https://cloudsim.xiaopeng.link/',
        'sec-ch-ua': '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Linux"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36',
        'x-account': user,
        'x-token': token
    }
    page_size = 100
    page = 1
    merged_result = None
    all_e2e_tasks = []

    while True:
        data = {
            "e2e_job_id": task_id,
            "page": page,
            "page_size": page_size
        }

        response = requests.post(url, headers=headers, json=data)
        if response.status_code != 200:
            print(f"Failed to fetch results for task {task_id}, page {page}. Status code: {response.status_code}")
            return None if merged_result is None else merged_result

        page_result = response.json()
        if merged_result is None:
            merged_result = page_result

        page_tasks = page_result.get('data', {}).get('e2e_tasks', [])
        if not page_tasks:
            break

        all_e2e_tasks.extend(page_tasks)

        # 当本页不足 page_size，说明已经到最后一页
        if len(page_tasks) < page_size:
            break

        page += 1

    if merged_result is not None:
        merged_result.setdefault('data', {})
        merged_result['data']['e2e_tasks'] = all_e2e_tasks
    return merged_result

def get_json_file_path(task_type, scenario_id):
    """获取特定task_type和scenario_id的JSON文件路径"""
    filename = f"{task_type}_{scenario_id}_fm_output_comparison.json"
    file_path = os.path.join(task_type, filename)
    return file_path if os.path.exists(file_path) else None

def load_json_for_scenario(task_type, scenario_id):
    """为特定scenario_id加载JSON数据"""
    file_path = get_json_file_path(task_type, scenario_id)
    if file_path and os.path.exists(file_path):
        try:
            data = []
            with open(file_path, 'r') as f:
                for line in f:
                    data.append(json.loads(line))
            return data
        except Exception as e:
            print(f"读取文件 {file_path} 时出错: {str(e)}")
    return None


def load_data_from_api(task_id, token, user):
    result = get_task_results(task_id, token, user)
    return parse_task_results(result)
    

def parse_task_results(result):
    """解析任务结果，提取scenario_id和e2e_task_id的映射"""
    scenario_to_task_map = {}
    
    if result and 'data' in result:
        data = result['data']
        e2e_tasks = data.get('e2e_tasks', [])
        
        
        # 遍历e2e_tasks，建立映射关系
        for task in e2e_tasks:
            scenario_id = task.get('scenario_id')
            e2e_task_id = task.get('e2e_task_id')
            if scenario_id and e2e_task_id:
                scenario_to_task_map[scenario_id] = e2e_task_id
    
    return scenario_to_task_map    


def query_3dgs_scenario_info_simple(scenario_ids, token, user):
    """查询3DGS场景信息并提取scenario_id到input_id的映射（分批 + 重试）"""
    scenario_ids = list(scenario_ids)
    if not scenario_ids:
        return {}

    merged_map = {}
    total_batches = (len(scenario_ids) + SCENARIO_INFO_BATCH_SIZE - 1) // SCENARIO_INFO_BATCH_SIZE
    for batch_idx, batch in enumerate(_chunked(scenario_ids, SCENARIO_INFO_BATCH_SIZE), start=1):
        print(f"查询 scenario 信息: 批次 {batch_idx}/{total_batches} ({len(batch)} 个)")
        batch_map = _query_3dgs_scenario_info_batch(batch, token, user, batch_idx, total_batches)
        merged_map.update(batch_map)

    missing_count = len(set(scenario_ids) - set(merged_map.keys()))
    if missing_count:
        print(f"警告: {missing_count} 个 scenario_id 未查到 clip_id")

    return merged_map


def _query_3dgs_scenario_info_batch(scenario_ids, token, user, batch_idx, total_batches):
    url = 'https://cloudsim.xiaopeng.link/simulation/threedgs/query_3dgs_scenario_info_list/'
    headers = {
        'accept': '*/*',
        'accept-language': 'zh-CN,zh;q=0.9',
        'origin': 'https://cloudsim.xiaopeng.link',
        'referer': 'https://cloudsim.xiaopeng.link/',
        'sec-ch-ua': '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Linux"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36',
        'x-account': user,
        'x-token': token
    }
    cookies = {
        'x-token': token,
        'x-account': user
    }
    data = {
        'scenario_ids': json.dumps(scenario_ids),
        'page': '1',
        'size': str(len(scenario_ids))
    }

    for attempt in range(1, SCENARIO_INFO_MAX_RETRIES + 1):
        try:
            response = requests.post(
                url, headers=headers, cookies=cookies, data=data, timeout=SCENARIO_INFO_TIMEOUT
            )
            if response.status_code == 200:
                return extract_scenario_input_mapping(response.json())
            print(f"批次 {batch_idx}/{total_batches} 请求失败，状态码: {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"批次 {batch_idx}/{total_batches} 第 {attempt} 次请求出错: {e}")

        if attempt < SCENARIO_INFO_MAX_RETRIES:
            time.sleep(2 * attempt)

    print(f"批次 {batch_idx}/{total_batches} 在 {SCENARIO_INFO_MAX_RETRIES} 次重试后仍失败")
    return {}


def extract_scenario_input_mapping(api_response):
    """从API响应中提取scenario_id到input_id的映射"""
    scenario_to_input_map = {}
    if api_response and 'data' in api_response:
        data = api_response['data']
        if 'list' in data:
            for item in data['list']:
                scenario_id = item.get('scenario_id')
                input_id_type = item.get('input_id_type')
                if input_id_type != 'clip_id':
                    print(f"scenario_id: {scenario_id} not match any clip_id")
                    continue
                input_id = item.get('input_id')
                if scenario_id and input_id:
                    scenario_to_input_map[scenario_id] = input_id
                    print(f"scenario_id: {scenario_id} -> input_id: {input_id}")
    return scenario_to_input_map


def parse_job_args(values):
    """把 ``--job`` 的 ``job_name=job_id[,job_id...]`` 解析成 jobs 字典。"""
    jobs = {}
    for item in values or []:
        job_name, sep, ids = str(item).partition("=")
        job_name = job_name.strip()
        if not job_name or not sep:
            raise ValueError(f"任务参数格式应为 job_name=job_id，收到: {item!r}")
        id_list = [int(x) for x in ids.split(",") if x.strip()]
        if not id_list:
            raise ValueError(f"任务 {job_name!r} 未提供有效 e2e_job_id: {item!r}")
        jobs.setdefault(job_name, []).extend(id_list)
    return jobs


def main():
    parser = argparse.ArgumentParser(
        description="下载 FM 输出对比文件（凭据 / 任务均由命令行传入，不再写死）。")
    parser.add_argument("--token", required=True, help="cloudsim x-token（JWT）")
    parser.add_argument("--user", required=True, help="cloudsim x-account（账号邮箱）")
    parser.add_argument(
        "--job", action="append", metavar="job_name=job_id", dest="jobs",
        help="待评测的 job：job_name=job_id（同一 job_name 可逗号分隔多个 job_id；"
             "可重复本参数传入候选与基线等多个 job；origin_png 为 eval_main 内置 baseline）")
    parser.add_argument("--output-root", default=OUTPUT_ROOT,
                        help="评测根目录（在其下创建 sim_<job_name> 子目录）")
    args = parser.parse_args()

    jobs = parse_job_args(args.jobs)
    if not jobs:
        parser.error("至少需提供一个 --job job_name=job_id")

    download_all_task_data(jobs, args.token, args.user, output_root=args.output_root)


# 运行示例
if __name__ == "__main__":
    main()