import argparse
import hashlib
import hmac
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Optional
from urllib.parse import urlparse

import requests
import oss2
import lz4.frame as lz4frame

OSS_ACCESS_KEY_ID = 'OSS_ACCESS_KEY_ID_REDACTED'
OSS_ACCESS_KEY_SECRET = 'OSS_ACCESS_KEY_SECRET_REDACTED'
SIM_BUCKET = 'cloudsim-ci-sh'

CLOUDSIM_API_URL = 'https://cloudsim.xiaopeng.link/simulation/pytorch_test/query_e2e_job_by_id/'
CLOUDSIM_QUERY_FAILED_URL = 'https://cloudsim.xiaopeng.link/simulation/scenarioresult/query_failed_tasks/'
SCENARIO_QUERY_URL = 'https://cloudsim.xiaopeng.link/simulation/scenario/query/'
QUERY_ALL_TASKS_URL = 'https://cloudsim.xiaopeng.link/simulation/scenarioresult/query_all_tasks/'

# HMAC-SHA256 认证（与 cloudsim_request.py 保持一致）
_ACCOUNT = 'cloudsim-engine@xiaopeng.com'
_SECRETS = {
    'cloudsim.xiaopeng.link': '%mMFcTWlzJOe',
    'cloudsim-dev.xiaopeng.link': 'vl@H%KtbzeYa',
    'wl-cloudsim-dev.xiaopeng.link': 'vl@H%KtbzeYa',
    'cloudsim-staging.xiaopeng.link': 'ggvfelQJRMjb',
}


def _sign_header(url: str) -> dict:
    domain = urlparse(url).netloc
    secret = _SECRETS.get(domain)
    if not secret:
        raise ValueError(f'No HMAC secret for domain: {domain}')
    ts = str(int(time.time() * 1000))
    sign_message = '/'.join(['simulation-auth', '1.0', _ACCOUNT, ts])
    sig = hmac.new(secret.encode(), sign_message.encode(), hashlib.sha256).hexdigest()
    return {'X-Sign': f'{sign_message}/{sig}'}


def fetch_cases_by_job_id(job_id: int) -> List[Tuple[str, str]]:
  """通过 CloudSim API 查询 job_id 下的所有 case，返回 [(task_id_str, case_id_str), ...]"""
  page = 1
  page_size = 50
  total: Optional[int] = None
  all_tasks = []

  print(f'正在从 CloudSim API 查询 job_id={job_id} 的所有 case ...')
  while True:
    payload = {'e2e_job_id': job_id, 'page': page, 'page_size': page_size}
    result = None
    for retry in range(5):
      try:
        resp = requests.post(CLOUDSIM_API_URL, headers=_sign_header(CLOUDSIM_API_URL), json=payload, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        break
      except Exception as e:
        wait = 2 ** retry
        print(f'  第 {page} 页请求失败（retry {retry+1}/5）: {e}，{wait}s 后重试...')
        time.sleep(wait)
    if result is None:
      print(f'  第 {page} 页重试 5 次均失败，终止查询')
      break

    data = result.get('data', {})
    if total is None:
      total = data.get('total', 0)
      print(f'  共 {total} 条 case')

    tasks = data.get('e2e_tasks', [])
    if not tasks:
      break
    all_tasks.extend(tasks)
    print(f'  第 {page} 页: {len(tasks)} 条')

    if len(all_tasks) >= total:
      break
    page += 1
    time.sleep(0.2)

  # 构造 (task_id_str, case_id_str) 列表
  result_list = []
  for task in all_tasks:
    e2e_task_id = task.get('e2e_task_id')
    scenario_id = task.get('scenario_id')
    if e2e_task_id is None or scenario_id is None:
      continue
    case_id = f'S{scenario_id}-J{job_id}-T{e2e_task_id}'
    result_list.append((str(e2e_task_id), case_id))

  print(f'共获取到 {len(result_list)} 个有效 case')
  return result_list


def fetch_cases_by_cces_job_id(cces_job_id: int) -> List[Tuple[str, str]]:
  """通过 CCES CI job_id 两步查询 case 列表:
  Step1: get_miles_list(job_id) 确认该 job 有 sim 数据
  Step2: query_all_tasks(id=job_id) 分页获取全部 scenario_id + sim_task_id
         （注意：query_failed_tasks 只返回失败条目，必须用 query_all_tasks）
  返回 [(sim_task_id_str, case_id_str), ...]
  """
  GET_MILES_URL = 'https://cloudsim.xiaopeng.link/simulation/simjob/get_miles_list/'

  # Step 1: 验证该 CCES job 存在 sim 里程数据
  print(f'[Step1] get_miles_list(job_id={cces_job_id}) ...')
  try:
    r = requests.post(GET_MILES_URL, headers=_sign_header(GET_MILES_URL),
                      files={'job_id': (None, str(cces_job_id))}, timeout=15)
    r.raise_for_status()
    miles_data = r.json().get('data', [])
    print(f'  miles 条数: {len(miles_data)}')
    if not miles_data:
      print(f'  [warn] job_id={cces_job_id} get_miles_list 返回空，可能不是 CCES sim job')
  except Exception as e:
    print(f'  [warn] get_miles_list 失败: {e}（继续尝试 query_all_tasks）')

  # Step 2: 分页查询所有 scenario 的 sim_task_id（使用 query_all_tasks，包含全部状态）
  print(f'[Step2] query_all_tasks(id={cces_job_id}) ...')
  page_size = 100
  page_no = 0
  total: Optional[int] = None
  all_tasks = []

  while True:
    try:
      r2 = requests.post(
        QUERY_ALL_TASKS_URL,
        headers=_sign_header(QUERY_ALL_TASKS_URL),
        files={
          'page_no': (None, str(page_no)),
          'page_size': (None, str(page_size)),
          'id': (None, str(cces_job_id)),
        },
        timeout=30,
      )
      r2.raise_for_status()
      body = r2.json()
      if body.get('result') != 'success':
        print(f'  第 {page_no} 页失败: {body.get("reason", body)}')
        break
    except Exception as e:
      print(f'  第 {page_no} 页请求失败: {e}')
      break

    if total is None:
      total = body.get('total', 0)
      print(f'  共 {total} 条 task')

    tasks = body.get('data', [])
    if not tasks:
      break
    all_tasks.extend(tasks)
    print(f'  第 {page_no} 页: {len(tasks)} 条（已累计 {len(all_tasks)}/{total}）')

    if len(all_tasks) >= total:
      break
    page_no += 1
    time.sleep(0.1)

  result_list = []
  for task in all_tasks:
    scenario_id = task.get('scenario_id')
    sim_task_id = task.get('sim_task_id')
    if scenario_id is None or sim_task_id is None:
      continue
    case_id = f'S{scenario_id}-J{cces_job_id}-T{sim_task_id}'
    result_list.append((str(sim_task_id), case_id))

  print(f'共获取到 {len(result_list)} 个有效 case')
  return result_list


def parse_ids(ids_str: str) -> List[Tuple[str, str]]:
  result = []
  for raw in ids_str.split(','):
    case_id = raw.strip()
    if not case_id:
      continue
    parts = case_id.split('-')
    if len(parts) < 3:
      raise ValueError(f'invalid case id: {case_id}')
    if len(parts) > 3:
      parts = parts[-3:]
    scenario, job, task = parts
    if not (scenario.startswith('S') and job.startswith('J') and task.startswith('T')):
      raise ValueError(f'invalid case id: {case_id}')
    if not (scenario[1:].isdigit() and job[1:].isdigit() and task[1:].isdigit()):
      raise ValueError(f'invalid case id: {case_id}')
    normalized = f'{scenario}-{job}-{task}'
    result.append((task[1:], normalized))
  return result


def detect_internal_endpoint() -> bool:
  cmd = 'curl -s -I --connect-timeout 1 http://oss-cn-wulanchabu-internal.aliyuncs.com >/dev/null 2>&1'
  return os.system(cmd) == 0


def make_bucket(bucket_name: str, use_internal_endpoint: bool) -> oss2.Bucket:
  endpoint = 'http://oss-cn-wulanchabu-internal.aliyuncs.com' if use_internal_endpoint else 'http://oss-cn-wulanchabu.aliyuncs.com'
  auth = oss2.Auth(OSS_ACCESS_KEY_ID, OSS_ACCESS_KEY_SECRET)
  return oss2.Bucket(auth, endpoint, bucket_name)


def query_scenario_desc_single(scenario_id: int) -> str:
  """调用 /simulation/scenario/query/ 查询单个 scenario 的 Scenario Description。
  参考 query_scenario_desc.py 的 _extract_description 逻辑。
  """
  resp = requests.post(
    SCENARIO_QUERY_URL,
    headers=_sign_header(SCENARIO_QUERY_URL),
    files={'id': (None, str(scenario_id))},
    timeout=30,
  )
  resp.raise_for_status()
  raw = resp.json()
  data = raw.get('data') or {}
  for key in ('Scenario Description', 'scenario_description', 'description', 'scenarioDescription', 'desc'):
    if isinstance(data, dict) and key in data:
      return str(data[key]).strip()
    if key in raw:
      return str(raw[key]).strip()
  if isinstance(data, list) and data:
    item = data[0]
    for key in ('Scenario Description', 'scenario_description', 'description'):
      if key in item:
        return str(item[key]).strip()
  return ''


def query_e2e_by_desc(e2e_job_id: int, scenario_desc: str, page_size: int = 100) -> List[dict]:
  """向 /simulation/scenarioresult/query_all_tasks/ 按 scenarioDesc 过滤，
  返回匹配的 task 列表（字段包含 scenario_id / sim_task_id 等）。
  小写参考 search_by_desc.py query_by_desc。
  """
  all_tasks: List[dict] = []
  page_no = 0
  while True:
    resp = requests.post(
      QUERY_ALL_TASKS_URL,
      headers=_sign_header(QUERY_ALL_TASKS_URL),
      files={
        'page_no':      (None, str(page_no)),
        'page_size':    (None, str(page_size)),
        'id':           (None, str(e2e_job_id)),
        'scenarioDesc': (None, scenario_desc),
      },
      timeout=30,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get('result') != 'success':
      break
    data = body.get('data', [])
    if isinstance(data, dict):
      for v in data.values():
        if isinstance(v, list):
          data = v
          break
    if not isinstance(data, list):
      break
    all_tasks.extend(data)
    total = int(body.get('total') or 0)
    if total and len(all_tasks) >= total:
      break
    if len(data) < page_size:
      break
    page_no += 1
  return all_tasks


def build_mapping_via_desc(
  cces_ids: List[Tuple[str, str]],
  e2e_job_id: int,
  delay: float = 0.2,
) -> dict:
  """通过 scenarioDesc 构建 CCES scenario_id → e2e task_id 的映射表。

  步骤：
    1. 对每个 CCES scenario_id 调用 /simulation/scenario/query/ 获取描述
    2. 用该描述向 e2e job 调用 query_all_tasks，取第一条匹配结果
    3. 返回 {cces_scenario_id_int: e2e_task_id_str}
  """
  mapping: dict = {}
  total = len(cces_ids)
  print(f'[mapping-via-desc] 开始，共 {total} 个 CCES scenario 待匹配...')
  for i, (sim_task_id, case_id) in enumerate(cces_ids, 1):
    s_part = case_id.split('-')[0]
    if not (s_part.startswith('S') and s_part[1:].isdigit()):
      continue
    cces_sid = int(s_part[1:])
    print(f'  [{i}/{total}] CCES scenario_id={cces_sid} 查询描述...', end=' ', flush=True)
    try:
      desc = query_scenario_desc_single(cces_sid)
      if not desc:
        print('描述为空，跳过')
        if delay > 0:
          time.sleep(delay)
        continue
      tasks = query_e2e_by_desc(e2e_job_id, desc)
      if not tasks:
        print(f'在 e2e job {e2e_job_id} 中无匹配')
        if delay > 0:
          time.sleep(delay)
        continue
      t = tasks[0]
      e2e_sid = t.get('scenario_id')
      e2e_tid = t.get('sim_task_id') or t.get('e2e_task_id')
      if e2e_tid is None:
        print(f'返回结果缺少 task_id，跳过（原始: {t}）')
        if delay > 0:
          time.sleep(delay)
        continue
      mapping[cces_sid] = str(e2e_tid)
      print(f'→ e2e_scenario_id={e2e_sid}, e2e_task_id={e2e_tid}')
    except Exception as exc:
      print(f'ERROR: {exc}')
    if delay > 0:
      time.sleep(delay)
  print(f'[mapping-via-desc] 完成，成功匹配 {len(mapping)}/{total} 个 scenario')
  return mapping


def build_mapping_by_job_desc(
  cces_job_id: int,
  e2e_job_id: int,
) -> dict:
  """直接用两个 job API 返回的 scenario_description 字段做 in-memory 匹配。

  步骤：
    1. 拉取 CCES job 全量 tasks，建 {description: (cces_scenario_id, sim_task_id)}
    2. 拉取 e2e job 全量 tasks，建 {description: e2e_task_id}
    3. 按描述交集得到 {cces_scenario_id_int: e2e_task_id_str}

  优点：完全 in-memory，不需要任何外部 API 调用，速度快。
  """
  CCES_URL = QUERY_ALL_TASKS_URL   # query_all_tasks 返回全部状态；query_failed_tasks 只返回失败条目
  E2E_URL  = CLOUDSIM_API_URL

  # Step1: 拉取 CCES job 全量 tasks
  print(f'[mapping-by-job-desc] Step1: 拉取 CCES job {cces_job_id} 全量 tasks...')
  cces_desc2info: dict = {}  # {desc: (cces_scenario_id_int, sim_task_id_str)}
  page_no = 0
  total_cces: Optional[int] = None
  while True:
    try:
      r = requests.post(CCES_URL, headers=_sign_header(CCES_URL),
                        files={'page_no': (None, str(page_no)), 'page_size': (None, '100'),
                               'id': (None, str(cces_job_id))}, timeout=30)
      r.raise_for_status()
      body = r.json()
    except Exception as exc:
      print(f'  第 {page_no} 页失败: {exc}')
      break
    if body.get('result') != 'success':
      print(f'  第 {page_no} 页 result={body.get("result")}: {body.get("reason", "")}')
      break
    if total_cces is None:
      total_cces = int(body.get('total', 0))
      print(f'  CCES job 共 {total_cces} 条')
    tasks = body.get('data', [])
    if not tasks:
      break
    for t in tasks:
      desc = str(t.get('scenario_description', '') or '').strip()
      sid  = t.get('scenario_id')
      stid = t.get('sim_task_id')
      if desc and sid is not None and stid is not None:
        cces_desc2info[desc] = (int(sid), str(stid))
    if len(cces_desc2info) >= total_cces:
      break
    page_no += 1
    time.sleep(0.05)
  print(f'  CCES 有效描述 {len(cces_desc2info)} 条')

  # Step2: 拉取 e2e job 全量 tasks
  print(f'[mapping-by-job-desc] Step2: 拉取 e2e job {e2e_job_id} 全量 tasks...')
  e2e_desc2tid: dict = {}  # {desc: e2e_task_id_str}
  page = 1
  total_e2e: Optional[int] = None
  while True:
    try:
      r2 = requests.post(E2E_URL, headers=_sign_header(E2E_URL),
                         json={'e2e_job_id': e2e_job_id, 'page': page, 'page_size': 100}, timeout=30)
      r2.raise_for_status()
      data = r2.json().get('data', {})
    except Exception as exc:
      print(f'  第 {page} 页失败: {exc}')
      break
    if total_e2e is None:
      total_e2e = int(data.get('total', 0))
      print(f'  e2e job 共 {total_e2e} 条')
    tasks2 = data.get('e2e_tasks', [])
    if not tasks2:
      break
    for t in tasks2:
      desc = str(t.get('scenario_description', '') or '').strip()
      tid  = t.get('e2e_task_id')
      if desc and tid is not None:
        e2e_desc2tid[desc] = str(tid)
    if total_e2e and len(e2e_desc2tid) >= total_e2e:
      break
    page += 1
    time.sleep(0.05)
  print(f'  e2e 有效描述 {len(e2e_desc2tid)} 条')

  # Step3: 按描述交集匹配
  mapping: dict = {}
  for desc, (cces_sid, _stid) in cces_desc2info.items():
    e2e_tid = e2e_desc2tid.get(desc)
    if e2e_tid:
      mapping[cces_sid] = e2e_tid
  print(f'[mapping-by-job-desc] 完成，匹配 {len(mapping)} 个 scenario'
        f'（CCES {len(cces_desc2info)}，e2e {len(e2e_desc2tid)}，交集 {len(mapping)}）')
  return mapping


def build_mapping_via_csv(
  csv_path: str,
  e2e_job_id: int,
) -> dict:
  """通过 CSV 文件构建 CCES scenario_id → e2e sim_task_id 的映射表。

  CSV 格式要求：
    - 列 `Scenario`         : CCES 新 scenario_id（72xxx / 73xxx …）
    - 列 `orig_scenario_id` : 对应 e2e job 中的 scenario_id（6xxx …）

  步骤：
    1. 读 CSV，建 {Scenario → orig_scenario_id}
    2. 拉取 e2e job 全量 tasks，建 {e2e_scenario_id → sim_task_id}
    3. 合并得到 {cces_scenario_id_int → e2e_sim_task_id_str}，供双源下载使用
  """
  import csv as _csv

  # Step1: 读 CSV
  print(f'[mapping-via-csv] 读取 CSV: {csv_path}')
  cces2orig: dict = {}  # {cces_sid_str: orig_sid_str}
  with open(csv_path, newline='', encoding='utf-8-sig') as fh:
    for row in _csv.DictReader(fh):
      cces_sid = row.get('Scenario', '').strip()
      orig_sid = row.get('orig_scenario_id', '').strip()
      if cces_sid and orig_sid:
        cces2orig[cces_sid] = orig_sid
  print(f'  CSV 共 {len(cces2orig)} 行有效映射')

  # Step2: 拉取 e2e job 全量 tasks，建 orig_scenario_id → sim_task_id
  print(f'[mapping-via-csv] 拉取 e2e job {e2e_job_id} 全量 tasks...')
  E2E_URL = 'https://cloudsim.xiaopeng.link/simulation/pytorch_test/query_e2e_job_by_id/'
  page = 1
  page_size = 100
  orig2e2etask: dict = {}  # {orig_sid_str: sim_task_id_str}
  total_e2e: Optional[int] = None
  while True:
    try:
      r = requests.post(
        E2E_URL,
        headers=_sign_header(E2E_URL),
        json={'e2e_job_id': e2e_job_id, 'page': page, 'page_size': page_size},
        timeout=30,
      )
      r.raise_for_status()
      data = r.json().get('data', {})
    except Exception as exc:
      print(f'  第 {page} 页请求失败: {exc}，跳过剩余页')
      break
    if total_e2e is None:
      total_e2e = data.get('total', 0)
      print(f'  e2e job 共 {total_e2e} 条 task')
    tasks = data.get('e2e_tasks', [])
    if not tasks:
      break
    for t in tasks:
      sid = str(t.get('scenario_id', ''))
      stid = t.get('sim_task_id')
      if sid and stid is not None:
        orig2e2etask[sid] = str(stid)
    print(f'  第 {page} 页: {len(tasks)} 条（已累计 {len(orig2e2etask)}/{total_e2e}）')
    if total_e2e and len(orig2e2etask) >= total_e2e:
      break
    page += 1
    time.sleep(0.1)
  print(f'  e2e job 有效映射 {len(orig2e2etask)} 条')

  # Step3: 合并
  mapping: dict = {}
  miss_csv = 0
  miss_e2e = 0
  for cces_sid_str, orig_sid_str in cces2orig.items():
    try:
      cces_sid_int = int(cces_sid_str)
    except ValueError:
      continue
    e2e_stid = orig2e2etask.get(orig_sid_str)
    if e2e_stid is None:
      miss_e2e += 1
      continue
    mapping[cces_sid_int] = e2e_stid
  print(f'[mapping-via-csv] 完成，成功匹配 {len(mapping)} 个 scenario'
        f'（CSV 有 {len(cces2orig)}，e2e 未命中 {miss_e2e}）')
  return mapping


def exists_or_unpacked(local_path: str) -> bool:
  return os.path.exists(local_path) or (local_path.endswith('.lz4') and os.path.exists(local_path[:-4]))


def extract_lz4(local_path: str) -> str:
  if not local_path.endswith('.lz4'):
    return local_path
  dst = local_path[:-4]
  if os.path.exists(dst) and os.path.getsize(dst) > 0:
    return dst
  with open(local_path, 'rb') as f_in, open(dst, 'wb') as f_out:
    decompressor = lz4frame.LZ4FrameDecompressor()
    for chunk in iter(lambda: f_in.read(1024 * 1024), b''):
      f_out.write(decompressor.decompress(chunk))
  return dst


def filter_metrics(scenario_file: str, mini_scenario_metrics: str) -> None:
  if not mini_scenario_metrics:
    return
  metric_names = [item.strip() for item in mini_scenario_metrics.split(',') if item.strip()]
  if not metric_names:
    return
  with open(scenario_file, 'r') as f:
    scenario = json.load(f)
  scenario['metrics'] = [metric for metric in scenario.get('metrics', []) if metric.get('name') in metric_names]
  mini_scenario_file = os.path.join(os.path.dirname(scenario_file), 'scenario-mini.json')
  with open(mini_scenario_file, 'w') as f:
    json.dump(scenario, f, indent=2, ensure_ascii=False)


def download_objects(bucket: oss2.Bucket, object_keys: List[str], local_root: str, prefix: str = '') -> int:
  count = 0
  for object_key in object_keys:
    rel_path = os.path.relpath(object_key, prefix) if prefix else os.path.basename(object_key)
    local_path = os.path.join(local_root, rel_path)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    if not exists_or_unpacked(local_path):
      bucket.get_object_to_file(object_key, local_path)
    if local_path.endswith('.lz4'):
      extract_lz4(local_path)
    count += 1
  return count


def collect_sim_objects(bucket: oss2.Bucket, task_id: str, dds_prefix: str = '', only_files: Optional[set] = None) -> Tuple[List[str], str]:
  """返回 (object_keys, matched_prefix)。
  dds_prefix: 如果为空，依次尝试旧新两种路径；
              否则直接使用展开后的完整前缀。
  only_files: 若指定（set of str），则只下载文件名在其中的对象，忽略默认白名单。
  """
  _WANTED_NAMES = {
    'discovery', 'metadata', 'scenario.json',
    'scenario_evaluator_result.json', 'scenario_evaluator.log',
  }
  def _list(prefix: str) -> List[str]:
    keys = []
    for obj in oss2.ObjectIterator(bucket, prefix=prefix):
      if obj.key.endswith('/'):
        continue
      base_name = os.path.basename(obj.key)
      if only_files is not None:
        if base_name in only_files:
          keys.append(obj.key)
      elif base_name in _WANTED_NAMES or base_name.startswith('recording_'):
        keys.append(obj.key)
    return keys

  if dds_prefix:
    full_prefix = dds_prefix if dds_prefix.endswith('/') else dds_prefix + '/'
    return _list(full_prefix), full_prefix

  # 未指定前缀时，依次尝试两种路径（兴趣兼容）
  for template in ['on_target_pytorch/dds_stores/{}/', 'simulation/dds_stores/{}/']:
    p = template.format(task_id)
    keys = _list(p)
    if keys:
      return keys, p
  return [], ''


def download_one_case(task_id: str, case_id: str, out_dir: str, use_internal_endpoint: bool, not_download_real: bool, mini_scenario_metrics: str, dds_prefix: str = '', only_files: Optional[set] = None, e2e_task_id: Optional[str] = None) -> Tuple[str, int, int]:
  case_dir = os.path.join(out_dir, case_id)
  os.makedirs(case_dir, exist_ok=True)

  sim_bucket = make_bucket(SIM_BUCKET, use_internal_endpoint)

  # ── 双源模式：CCES job + only_files + e2e_task_id ──────────────────────────
  # 从 CCES sim 路径下载 scenario.json，从 e2e 路径下载 only_files 指定的文件
  if e2e_task_id is not None and only_files is not None:
    # 1. 从 CCES sim 路径拉 scenario.json
    scenario_only = {'scenario.json'}
    sim_keys, sim_prefix = collect_sim_objects(sim_bucket, task_id, dds_prefix, only_files=scenario_only)
    sim_count = download_objects(sim_bucket, sim_keys, case_dir, sim_prefix) if sim_keys else 0
    if not sim_keys:
      print(f'  [warn] {case_id}: CCES 路径未找到 scenario.json（task_id={task_id}）')

    # 2. 从 e2e 路径拉 only_files 指定的文件（固定前缀）
    e2e_prefix = f'on_target_pytorch/dds_stores/{e2e_task_id}/'
    e2e_keys, e2e_p = collect_sim_objects(sim_bucket, e2e_task_id, e2e_prefix, only_files=only_files)
    e2e_count = download_objects(sim_bucket, e2e_keys, case_dir, e2e_p) if e2e_keys else 0
    if not e2e_keys:
      print(f'  [warn] {case_id}: e2e 路径未找到 {only_files}（e2e_task_id={e2e_task_id}）')

    return case_id, sim_count + e2e_count, 0
  # ──────────────────────────────────────────────────────────────────────────

  sim_keys, sim_prefix = collect_sim_objects(sim_bucket, task_id, dds_prefix, only_files=only_files)
  if not sim_keys:
    raise RuntimeError(f'no simulation files found for {case_id}')
  sim_count = download_objects(sim_bucket, sim_keys, case_dir, sim_prefix)

  scenario_file = os.path.join(case_dir, 'scenario.json')
  if only_files is None:
    print(f'  scenario_file: {scenario_file}')
    if not os.path.exists(scenario_file):
      raise RuntimeError(f'scenario.json missing for {case_id}')
  filter_metrics(scenario_file, mini_scenario_metrics) if (only_files is None and mini_scenario_metrics) else None

  real_count = 0
  if not not_download_real and only_files is None:
    with open(scenario_file, 'r') as f:
      scenario = json.load(f)
    dds_data_source = scenario['ddsDataSource']
    real_bucket = make_bucket(dds_data_source['bucket'], use_internal_endpoint)
    real_keys = sorted(set(dds_data_source['dds_files']) | {dds_data_source['metadata'], dds_data_source['discovery']})
    real_dir = os.path.join(case_dir, 'real')
    os.makedirs(real_dir, exist_ok=True)
    real_count = download_objects(real_bucket, real_keys, real_dir)

  return case_id, sim_count, real_count


def main() -> None:
  parser = argparse.ArgumentParser(description='download cases through OSS directly')
  # 来源方式一：直接指定 case id 列表
  parser.add_argument('--ids', type=str, default=None, help='逗号分隔的 case id 列表，格式: S<s>-J<j>-T<t>')
  # 来源方式二：通过 job_id 自动查询所有 case
  parser.add_argument('--job_id', type=int, default=None, help='CloudSim job id，自动查询该 job 下所有 case')
  parser.add_argument('--out_dir', type=str, required=True,
                      help='输出根目录。使用 --job_id 时，数据实际写入 <out_dir>/J<job_id>/；使用 --ids 时直接写入 <out_dir>/')
  parser.add_argument('--not_download_real', action='store_true', help='跳过 real 数据下载')
  parser.add_argument('--mini_scenario_metrics', type=str, default=None,
                      help='生成只含指定 metric 的 scenario-mini.json（逗号分隔 metric 名称）')
  parser.add_argument('--workers', type=int, default=4, help='下载并发数')
  parser.add_argument('--limit', type=int, default=0, help='最多下载的 case 数量，0 表示全部（默认: 0）')
  parser.add_argument('--use_ali_internal_endpoint', choices=['auto', 'true', 'false'], default='auto',
                      help='是否使用阿里云内网 endpoint：auto / true / false')
  parser.add_argument('--shard_idx', type=int, default=0, help='当前分片索引（0-based，配合 --num_shards 使用）')
  parser.add_argument('--num_shards', type=int, default=1, help='总分片数，用于多 job 并行下载')
  parser.add_argument('--only_files', type=str, default=None,
                      help='只下载指定文件名（逗号分隔），例如 clipiqa_scores.json。指定后跳过默认白名单和 scenario.json 校验')
  parser.add_argument('--e2e_job_id', type=int, default=None,
                      help='e2e job ID（5-6 位）。配合 CCES 长 job_id + --only_files 使用：'
                           '从 CCES 路径下载 scenario.json，同时从该 e2e job 对应 case 下载 only_files 文件。'
                           '当两个 job 的 scenario_id 相同时使用；'
                           '如果两个 job scenario_id 不同，请配合 --mapping_csv 或 --mapping_via_desc 使用。')
  parser.add_argument('--mapping_by_job_desc', action='store_true',
                      help='配合 --e2e_job_id 使用（推荐）。'
                           '直接拉取两个 job 全量数据，按 scenario_description 字段做 in-memory 匹配，'
                           '得到 CCES scenario_id → e2e task_id 映射。无需 CSV，速度快。')
  parser.add_argument('--mapping_csv', default=None, metavar='CSV_PATH',
                      help='配合 --e2e_job_id 使用。CSV 文件需包含列 Scenario（CCES scenario_id）'
                           '和 orig_scenario_id（对应 e2e job 的 scenario_id）。'
                           '脚本通过 CSV 建立 CCES scenario→e2e sim_task_id 映射，适用于两个 job '
                           'scenario_id 不同的情况（推荐，比 --mapping_via_desc 快）。')
  parser.add_argument('--mapping_via_desc', action='store_true',
                      help='配合 --e2e_job_id 使用。'
                           '对每个 CCES scenario 查询其 Scenario Description，'
                           '再到 e2e job 中按描述匹配，获取对应 e2e task_id（适用于两个 job scenario_id 不同的情况）。')
  args = parser.parse_args()

  if args.workers < 1:
    raise ValueError('--workers must be >= 1')
  if args.ids is None and args.job_id is None:
    parser.error('必须指定 --ids 或 --job_id 之一')
  if args.ids is not None and args.job_id is not None:
    parser.error('--ids 与 --job_id 不能同时指定')

  if args.use_ali_internal_endpoint == 'auto':
    use_internal_endpoint = detect_internal_endpoint()
  else:
    use_internal_endpoint = args.use_ali_internal_endpoint == 'true'

  # 确定实际输出目录和 case id 列表
  # 自动识别 job 类型：5-6 位 → CloudSim e2e job；7+ 位 → CCES CI job
  if args.job_id is not None:
    if len(str(args.job_id)) >= 7:
      print(f'[auto] job_id={args.job_id} 为 CCES CI job（{len(str(args.job_id))} 位），使用 query_failed_tasks 路径')
      ids = fetch_cases_by_cces_job_id(args.job_id)
      dds_prefix_template = 'simulation/dds_stores/{}/'
    else:
      print(f'[auto] job_id={args.job_id} 为 CloudSim e2e job（{len(str(args.job_id))} 位），使用 query_e2e_job_by_id 路径')
      ids = fetch_cases_by_job_id(args.job_id)
      dds_prefix_template = 'on_target_pytorch/dds_stores/{}/'
    out_dir = os.path.join(args.out_dir, f'J{args.job_id}')
    print(f'输出目录（按 job 隔离）: {out_dir}')
  else:
    ids = parse_ids(args.ids)
    out_dir = args.out_dir
    dds_prefix_template = ''  # --ids 模式：自动扫描两种 OSS 路径前缀


  # 多分片过滤：取模选出本 shard 负责的 case
  if args.num_shards > 1:
    ids = [item for i, item in enumerate(ids) if i % args.num_shards == args.shard_idx]
    print(f'[shard {args.shard_idx}/{args.num_shards}] 本分片负责 {len(ids)} 个 case')

  if args.limit > 0 and len(ids) > args.limit:
    ids = ids[:args.limit]
    print(f'[limit] 限制为前 {args.limit} 个 case')

  os.makedirs(out_dir, exist_ok=True)
  print(f'use_internal_endpoint={use_internal_endpoint}')
  print(f'workers={args.workers}')
  print(f'共 {len(ids)} 个 case 待下载')

  # 将 case id 列表保存到输出目录，方便后续重跑脚本直接读取
  case_ids_file = os.path.join(out_dir, 'case_ids.txt')
  with open(case_ids_file, 'w') as f:
    f.write('\n'.join(case_id for _, case_id in ids) + '\n')
  print(f'case id 列表已保存到: {case_ids_file}')

  only_files_set = {f.strip() for f in args.only_files.split(',') if f.strip()} if args.only_files else None
  if only_files_set:
    print(f'[only_files] 只下载以下文件: {only_files_set}')

  # ── 双源模式：CCES 长 job + only_files + e2e_job_id ──────────────────────────
  # e2e_scenario_map: {cces_scenario_id_int: e2e_task_id_str}
  # 对应关系来源：
  #   --mapping_via_desc：对每个 CCES scenario 查询 scenarioDesc，再通过描述搜 e2e job（适用于 scenario_id 不同）
  #   默认：两个 job scenario_id 相同，直接匹配
  e2e_scenario_map: dict = {}
  is_cces_job = args.job_id is not None and len(str(args.job_id)) >= 7
  is_dual_source = (
    args.e2e_job_id is not None
    and is_cces_job
    and only_files_set is not None
  )
  if is_dual_source:
    if getattr(args, 'mapping_by_job_desc', False):
      # ① 直接用两个 job 的 scenario_description 做 in-memory 匹配（推荐）
      e2e_scenario_map = build_mapping_by_job_desc(args.job_id, args.e2e_job_id)
    elif getattr(args, 'mapping_csv', None):
      # ② CSV 文件映射（CCES scenario_id → orig_scenario_id → e2e sim_task_id）
      e2e_scenario_map = build_mapping_via_csv(args.mapping_csv, args.e2e_job_id)
    elif getattr(args, 'mapping_via_desc', False):
      # ① 通过 scenarioDesc 匹配（scenario_id 不同）
      e2e_scenario_map = build_mapping_via_desc(ids, args.e2e_job_id)
    else:
      # ② scenario_id 相同，直接匹配 e2e job 的 task_id
      print(f'[dual-source] 查询 e2e job {args.e2e_job_id} 的 case 列表，构建 scenario_id 映射...')
      for e2e_tid, e2e_cid in fetch_cases_by_job_id(args.e2e_job_id):
        s_part = e2e_cid.split('-')[0]
        if s_part.startswith('S') and s_part[1:].isdigit():
          e2e_scenario_map[int(s_part[1:])] = e2e_tid
      print(f'[dual-source] e2e job 共 {len(e2e_scenario_map)} 个 scenario 映射')
  # ──────────────────────────────────────────────────────────────────────────

  failed = []
  with ThreadPoolExecutor(max_workers=args.workers) as executor:
    futures = {}
    for task_id, case_id in ids:
      # 解析本 case 的 scenario_id，查找对应 e2e_task_id
      e2e_tid_for_case: Optional[str] = None
      if is_dual_source:
        s_part = case_id.split('-')[0]
        if s_part.startswith('S') and s_part[1:].isdigit():
          sid = int(s_part[1:])
          e2e_tid_for_case = e2e_scenario_map.get(sid)
          if e2e_tid_for_case is None:
            print(f'  [warn] {case_id}: scenario_id={sid} 在 e2e job {args.e2e_job_id} 中无对应，跳过 only_files 下载')
      futures[executor.submit(
        download_one_case,
        task_id,
        case_id,
        out_dir,
        use_internal_endpoint,
        args.not_download_real,
        args.mini_scenario_metrics,
        dds_prefix_template.format(task_id) if dds_prefix_template else '',
        only_files_set,
        e2e_tid_for_case,
      )] = case_id
    for idx, future in enumerate(as_completed(futures), 1):
      case_id = futures[future]
      try:
        downloaded_case_id, sim_count, real_count = future.result()
        print(f'[{idx}/{len(futures)}] {downloaded_case_id} status=ok sim_files={sim_count} real_files={real_count}')
      except Exception as exc:
        print(f'[{idx}/{len(futures)}] {case_id} status=failed error={exc}')
        failed.append(case_id)

  print(f'\nall downloads done. success={len(futures) - len(failed)} failed={len(failed)}')
  if failed:
    failed_file = os.path.join(out_dir, 'failed_cases.txt')
    with open(failed_file, 'w') as f:
      f.write('\n'.join(failed) + '\n')
    print(f'失败 case 已记录到: {failed_file}')


if __name__ == '__main__':
  main()

    