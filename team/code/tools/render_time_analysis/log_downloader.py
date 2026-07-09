      
import argparse
import os
import requests
from urllib.parse import urljoin
import time


####################################################
# 凭据（x-token / x-account）与任务列表不再写死在代码中：
#   - 命令行：通过 --token / --user 及 --candidate / --baseline 传入；
#   - 被 Agent 调用：由 tse.integrations.simworld_tools 以函数参数传入。
# 仅保留输出根目录的默认值，可用 --output-root 覆盖。
OUTPUT_ROOT = "/workspace/time_analysis"
####################################################


def _scenario_sort_key(scenario_id):
    scenario_id_str = str(scenario_id)
    try:
        return (0, int(scenario_id_str))
    except ValueError:
        return (1, scenario_id_str)


def select_task_records_by_scenario(task_records, max_scenario_numbers=None, target_scenario_ids=None):
    """按 scenario_id 排序并选择需要下载的任务记录。"""
    sorted_items = sorted(
        task_records.items(),
        key=lambda item: _scenario_sort_key(item[1].get('scenario_id')),
    )

    selected_records = {}
    selected_scenario_ids = set()
    target_scenario_ids = {str(s) for s in target_scenario_ids} if target_scenario_ids else None

    for e2e_task_id, task_info in sorted_items:
        scenario_id = task_info.get('scenario_id')
        if scenario_id is None:
            continue
        scenario_id_str = str(scenario_id)
        if target_scenario_ids is not None and scenario_id_str not in target_scenario_ids:
            continue
        if scenario_id_str in selected_scenario_ids:
            continue
        selected_records[e2e_task_id] = task_info
        selected_scenario_ids.add(scenario_id_str)
        if max_scenario_numbers is not None and len(selected_scenario_ids) >= max_scenario_numbers:
            break

    return selected_records


def download_all_job_data(
    jobs,
    log_list,
    token,
    user,
    target_scenario_ids=None,
    max_scenario_numbers=None,
    output_root=OUTPUT_ROOT,
):
    """下载所有任务类型的数据"""
    all_job_data = {}
    
    for job_key, job_ids in jobs.items():
        print(f"正在处理任务: {job_key}")
        task_records = {}
        for job_id in job_ids:
            job_task_records = load_data_from_api(
                job_id, token, user, target_scenario_ids=target_scenario_ids)
            for e2e_task_id, task_info in job_task_records.items():
                task_info['job_id'] = job_id
                task_records[e2e_task_id] = task_info
        
        if not task_records:
            print(f"没有找到 {job_key} 的数据")
            continue

        selected_records = select_task_records_by_scenario(
            task_records,
            max_scenario_numbers=max_scenario_numbers,
            target_scenario_ids=target_scenario_ids,
        )
        if not selected_records:
            print(f"{job_key} 没有命中可下载的 scenario")
            continue
        
        print(
            f"找到 {len(task_records)} 个任务，按 scenario_id 排序后选择 "
            f"{len(selected_records)} 个 scenario 下载"
        )
        download_log_files(job_key, selected_records, log_list, output_root=output_root)
        save_scenario_status(job_key, selected_records, output_root=output_root)
        all_job_data[job_key] = selected_records
    
    return all_job_data

def download_log_files(job_key, task_records, log_list, output_root=OUTPUT_ROOT):
    """下载日志文件"""
    # 创建以 jobs key 命名的文件夹
    folder_name = os.path.join(output_root, str(job_key))
    os.makedirs(folder_name, exist_ok=True)
    
    base_url = "https://cloud-sim-web-prod.xiaopeng.link/cloudsim-ci-sh/on_target_pytorch/dds_stores/"
    
    # 遍历log_list中的每个日志文件
    for log_file in log_list:
        for e2e_task_id, task_info in task_records.items():
            if e2e_task_id is None:
                continue
            scenario_id = task_info.get('scenario_id')
            if scenario_id is None:
                continue
            # 构造下载URL
            file_url = urljoin(base_url, f"{e2e_task_id}/{log_file}")
            print(f"正在下载 {file_url} ...")
            # 设置文件名
            filename = f"{scenario_id}_{log_file}"
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

    
def save_scenario_status(job_key, task_records, output_root=OUTPUT_ROOT):
    """保存当前 job 下 target scenario 的状态信息"""
    folder_name = os.path.join(output_root, str(job_key))
    os.makedirs(folder_name, exist_ok=True)
    status_file_path = os.path.join(folder_name, "scenario_status.csv")

    with open(status_file_path, 'w', encoding='utf-8') as f:
        f.write("scenario_id,e2e_task_id,e2e_job_id,task_status\n")
        sorted_items = sorted(
            task_records.items(),
            key=lambda item: _scenario_sort_key(item[1].get('scenario_id')),
        )
        for e2e_task_id, task_info in sorted_items:
            scenario_id = task_info.get('scenario_id')
            task_status = task_info.get('task_status', '')
            job_id = task_info.get('job_id', '')
            if scenario_id is None:
                continue
            f.write(f"{scenario_id},{e2e_task_id},{job_id},{task_status}\n")

    print(f"已保存状态文件: {status_file_path}")


def get_task_results(task_id, token, user, target_scenario_ids=None):
    """通过API获取任务结果，支持分页获取所有数据"""
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
    
    all_e2e_tasks = []
    found_target_scenarios = set()
    page = 1
    page_size = 50
    total = None
    
    while True:
        data = {
            "e2e_job_id": task_id,
            "page": page,
            "page_size": page_size
        }
        
        try:
            response = requests.post(url, headers=headers, json=data)
            if response.status_code != 200:
                print(f"Failed to fetch results for task {task_id}, page {page}. Status code: {response.status_code}")
                break
            
            result = response.json()
            
            # 获取总条数（仅在第一页）
            if total is None and 'data' in result and 'total' in result['data']:
                total = result['data']['total']
                print(f"Task {task_id}: 共 {total} 条数据")
            
            # 获取当前页的数据
            if 'data' in result and 'e2e_tasks' in result['data']:
                e2e_tasks = result['data']['e2e_tasks']
                if not e2e_tasks:
                    break  # 没有更多数据了
                
                all_e2e_tasks.extend(e2e_tasks)
                print(f"  第 {page} 页: 获取到 {len(e2e_tasks)} 条数据")

                # 如果目标 scenario 已全部命中，提前结束分页
                if target_scenario_ids:
                    for task in e2e_tasks:
                        scenario_id = task.get('scenario_id')
                        if scenario_id is None:
                            continue
                        scenario_id_str = str(scenario_id)
                        if scenario_id_str in target_scenario_ids:
                            found_target_scenarios.add(scenario_id_str)
                    if found_target_scenarios.issuperset(target_scenario_ids):
                        print(f"Task {task_id}: 目标 scenario 已全部命中，提前结束分页")
                        break
                
                # 检查是否已获取完所有数据
                if len(all_e2e_tasks) >= total:
                    break
            else:
                break  # 响应格式异常，退出循环
            
            page += 1
            time.sleep(0.2)  # 避免请求过快
            
        except Exception as e:
            print(f"请求 task {task_id}, page {page} 时出错: {str(e)}")
            break
    
    # 构造返回结果，保持与原函数返回格式一致
    if all_e2e_tasks:
        return {
            'data': {
                'e2e_tasks': all_e2e_tasks,
                'total': len(all_e2e_tasks)
            }
        }
    else:
        return None    


def load_data_from_api(task_id, token, user, target_scenario_ids=None):
    
    result = get_task_results(task_id, token, user, target_scenario_ids=target_scenario_ids)

    return parse_task_results_scenario(result)


def parse_task_results_scenario(result):
    """解析任务结果，提取scenario_id、e2e_task_id和task_status"""
    task_records = {}
    
    if result and 'data' in result:
        data = result['data']
        e2e_tasks = data.get('e2e_tasks', [])

        for task in e2e_tasks:
            e2e_task_id = task.get('e2e_task_id')
            if e2e_task_id is None:
                continue
            scenario_id = task.get('scenario_id')
            if scenario_id is None:
                continue
            task_records[e2e_task_id] = {
                'scenario_id': scenario_id,
                'task_status': task.get('task_status', '')
            }
    
    return task_records


def parse_target_scenario_ids(target_scenario_id_text):
    if not target_scenario_id_text:
        return None
    return {s.strip() for s in str(target_scenario_id_text).split(",") if s.strip()}


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
        description="下载闭环仿真渲染日志（凭据 / 任务均由命令行传入，不再写死）。")
    parser.add_argument("--token", required=True, help="cloudsim x-token（JWT）")
    parser.add_argument("--user", required=True, help="cloudsim x-account（账号邮箱）")
    parser.add_argument(
        "--job", action="append", metavar="job_name=job_id", dest="jobs",
        help="待下载的 job：job_name=job_id（同一 job_name 可逗号分隔多个 job_id；"
             "可重复本参数传入候选与基线等多个 job）")
    parser.add_argument("--output-root", default=OUTPUT_ROOT, help="日志下载根目录")
    parser.add_argument(
        "--log-file", action="append", dest="log_files", metavar="NAME",
        help="待下载日志文件名（可重复，默认 3dgs_server1_out.log）")
    parser.add_argument("--max-scenarios", type=int, default=100,
                        help="每个 job 最多下载的 scenario 数")
    parser.add_argument("--target-scenario-ids", default="",
                        help="只下载指定 scenario_id（逗号分隔），留空则自动选取")
    args = parser.parse_args()

    jobs = parse_job_args(args.jobs)
    if not jobs:
        parser.error("至少需提供一个 --job job_name=job_id")
    log_list = args.log_files or ["3dgs_server1_out.log"]
    target_scenario_ids = parse_target_scenario_ids(args.target_scenario_ids)

    # 1. 下载所有任务数据
    all_job_data = download_all_job_data(
        jobs,
        log_list,
        args.token,
        args.user,
        target_scenario_ids=target_scenario_ids,
        max_scenario_numbers=args.max_scenarios,
        output_root=args.output_root,
    )
    if not all_job_data:
        print("没有下载到任何任务数据")
        return


# 运行示例
if __name__ == "__main__":
    main()

    
