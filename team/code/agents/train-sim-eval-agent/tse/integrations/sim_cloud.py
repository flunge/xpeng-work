import json
import httpx
from tse.config import Settings
from tse.models.domain import SubmitArgs
from tse.switches import build_manual_sim_configuration

# 平台 e2e job 终态字符串（已抓 query_e2e_job_by_id 真实响应校准）。
# 平台返回为小写（实测 job.status="finished"）；classify_terminal 统一 .upper() 后匹配。
# 真实状态词表（task_statistics 分桶 + 实测 job.status）：
#   running / pending → 非终态；finished → 成功；failed / errored / canceled → 失败。
# 其余为其它平台/历史可能值，保留作防御式兼容。
TERMINAL_OK = {"FINISHED", "COMPLETED", "SUCCESS", "SUCCEED", "SUCCEEDED"}
TERMINAL_FAIL = {"FAILED", "ERRORED", "ERROR", "CANCELED", "CANCELLED", "KILLED", "TIMEOUT"}


def classify_terminal(status: str) -> str | None:
    """大小写不敏感地判定终态：返回 'ok' / 'fail' / None（非终态）。"""
    norm = (status or "").strip().upper()
    if norm in TERMINAL_OK:
        return "ok"
    if norm in TERMINAL_FAIL:
        return "fail"
    return None


class SimCloudClient:
    def __init__(self, s: Settings):
        self._s = s
        self._query_path = s.sim_query_path
        self._submit_path = s.sim_submit_path
        headers = {
            "accept": "*/*",
            "content-type": "text/plain;charset=UTF-8",
        }
        # cloudsim 用 x-token / x-account 鉴权；如平台另需 Bearer 也一并带上
        if s.sim_x_token:
            headers["x-token"] = s.sim_x_token
        if s.sim_x_account:
            headers["x-account"] = s.sim_x_account
        if s.sim_api_token:
            headers["Authorization"] = f"Bearer {s.sim_api_token}"
        self._c = httpx.Client(base_url=s.sim_base_url, headers=headers, timeout=30)

    def submit(self, args: "SubmitArgs") -> str:
        """提交（rerun）闭环仿真，返回新的 sim_task_id（即 e2e_job_id）。

        忠实对齐网页端抓包：POST /simulation/pytorch_test/rerun_e2e_job/，
        body 为 text/plain 的 JSON 串；鉴权用 x-token / x-account（见 __init__）。
        """
        s = self._s
        req = args.req

        # 每次提交的「可变项」：rerun 模板 job_id、job_name、stage1_binary_id、全局开关。
        # 其余均为固定配置：
        #   stage1 —— 每次编包输出（args.binary_id）；req 显式给定则优先（用于复跑/覆盖）。
        #   stage2 —— 固定配置值（s.sim_stage2_binary_id）；req 显式给定则优先。
        #   model_id —— 固定配置值（s.sim_model_id）；req 显式给定则优先。
        stage1_binary_id = (req.stage1_binary_id if req.stage1_binary_id is not None
                            else _coerce_binary_id(args.binary_id))
        stage2_binary_id = (req.stage2_binary_id if req.stage2_binary_id is not None
                            else s.sim_stage2_binary_id)
        model_id = req.model_id if req.model_id is not None else s.sim_model_id

        # rerun 唯一必备的外部输入是模板 e2e_job_id：缺失则快速失败，
        # 不静默提交一个无意义任务（其余项均有编包输出 / 配置兜底）。
        if req.template_e2e_job_id is None:
            raise RuntimeError(
                "rerun_e2e_job 缺少必备参数 template_e2e_job_id（rerun 的模板 job_id）；"
                "需由 CLI/API 以 --rerun-job-id 提供")

        manual = req.manual_sim_configuration or build_manual_sim_configuration(req.switches)
        fuyao_config = {
            "priority": s.sim_fuyao_priority,
            "site": s.sim_fuyao_site,
            "partition": s.sim_fuyao_partition,
            "gpus_per_node": s.sim_fuyao_gpus_per_node,
            "fuyao_job_batch_size": s.sim_fuyao_job_batch_size,
            "is_upload_fm_ipc": s.sim_is_upload_fm_ipc,
            "enable_inferserver": s.sim_fuyao_enable_inferserver,
            "enable_closeloop": s.sim_fuyao_enable_closeloop,
            "manual_sim_configuration": manual,
            "fuyao_job_timeout_seconds": s.sim_fuyao_job_timeout_seconds,
        }
        payload = {
            "e2e_job_id": req.template_e2e_job_id,
            "job_name": req.job_name or f"{req.branch}_{req.experiment_id[:8]}",
            "build_version": "",
            "stage2_binary_id": stage2_binary_id,
            "stage1_binary_id": stage1_binary_id,
            "model_id": model_id,
            "invoke_user": s.sim_x_account,
            "source": s.sim_source,
            "is_upload_fm_ipc": s.sim_is_upload_fm_ipc,
            "fuyao_config": json.dumps(fuyao_config, ensure_ascii=False),
        }
        # content-type 为 text/plain：以原始 JSON 串发送（与抓包一致）
        body = json.dumps(payload, ensure_ascii=False)
        r = self._c.post(self._submit_path, content=body)
        r.raise_for_status()
        return _parse_submit_result(r.json())

    def query_status(self, sim_task_id: str) -> str:
        """查询 e2e job 状态，返回平台原始状态字符串（RUNNING/COMPLETED/FAILED/...）。

        对齐真实接口：POST query_e2e_job_by_id/，body 为 text/plain 的 JSON 串。
        已抓真实响应校准信封为 {"result", "data", "msg"}：result="error" 时（如 job
        不存在）由 _parse_job_status 透出平台 msg。
        """
        e2e_job_id = int(sim_task_id)
        body = json.dumps({"e2e_job_id": e2e_job_id, "page": 1, "page_size": 10})
        r = self._c.post(self._query_path, content=body)
        r.raise_for_status()
        return _parse_job_status(r.json(), e2e_job_id)


# —— 响应解析 ——
# 已抓真实响应校准信封：{"result": "ok"/"error", "data": {...}, "msg": "..."}
#   成功样例：{"result": "ok", "data": {"e2e_job_id": 159064, "status": "finished", ...}}
#            —— data 直接是单条 job 记录 dict（e2e_job_id 在其顶层），非分页 list。
#   失败样例：{"result": "error", "data": {}, "msg": "no e2e job found by e2e_job_id:11956581"}
# result 成功标识（大小写不敏感）；其余值（如 "error"）视为失败并透出 msg。
_RESULT_OK = {"ok", "success", "true", "0"}
# 分页 list 兜底键（部分接口/历史结构可能把记录放在 data.list 下）。
_LIST_KEYS = ("list", "items", "records", "rows", "data", "results")
# 已确认 job 级状态字段为 "status"（值小写，如 "finished"）；其余为防御式兜底
# （e2e_tasks 内单任务用 "task_status"）。
_STATUS_KEYS = ("status", "job_status", "e2e_job_status", "state", "task_status")
_ID_KEYS = ("e2e_job_id", "job_id", "id")


def _parse_job_status(payload: dict, e2e_job_id: int) -> str:
    # 信封级错误优先短路：result 非成功（含 job 不存在）时直接抛平台 msg，避免吞掉真实原因。
    if isinstance(payload, dict) and "result" in payload:
        result = str(payload.get("result", "")).strip().lower()
        if result and result not in _RESULT_OK:
            msg = payload.get("msg") or payload.get("message") or ""
            raise RuntimeError(
                f"query_e2e_job_by_id 失败 (result={payload.get('result')!r}, "
                f"e2e_job_id={e2e_job_id}): {msg or payload!r}")
    record = _find_job_record(payload, e2e_job_id)
    if record is None:
        raise RuntimeError(f"e2e job {e2e_job_id} not found in response")
    for key in _STATUS_KEYS:
        val = record.get(key)
        if val is not None:
            return str(val)
    raise RuntimeError(f"cannot parse status from job record: keys={list(record)}")


def _find_job_record(payload, e2e_job_id: int) -> dict | None:
    """从（带 {result,data,msg} 信封与可能的分页 list 的）响应中取出目标 job 记录。"""
    node = payload
    if isinstance(node, dict) and "data" in node and not _looks_like_record(node):
        node = node["data"]

    records = _to_record_list(node)
    if not records:
        return None
    for rec in records:
        for k in _ID_KEYS:
            if k in rec and str(rec[k]) == str(e2e_job_id):
                return rec
    # 未按 id 命中时退回首条（查询本就按 id 过滤）
    return records[0]


def _to_record_list(node) -> list[dict]:
    if isinstance(node, list):
        return [r for r in node if isinstance(r, dict)]
    if isinstance(node, dict):
        if _looks_like_record(node):
            return [node]
        for key in _LIST_KEYS:
            val = node.get(key)
            if isinstance(val, list):
                return [r for r in val if isinstance(r, dict)]
    return []


def _looks_like_record(node) -> bool:
    return isinstance(node, dict) and (
        any(k in node for k in _STATUS_KEYS) or any(k in node for k in _ID_KEYS)
    )


# —— 提交相关 ——
def _coerce_binary_id(binary_id) -> int:
    """编包输出的 binary_id 转为整数 stage1_binary_id（平台要求 int）。"""
    try:
        return int(str(binary_id).strip())
    except (TypeError, ValueError):
        raise RuntimeError(
            f"编包输出 binary_id={binary_id!r} 非数字，无法作为 stage1_binary_id 提交")


def _parse_submit_result(payload) -> str:
    """从 rerun_e2e_job 响应中取出新建/复跑得到的 e2e_job_id。

    TODO: 按真实响应结构校准（未提供响应样例，当前为防御式解析）。
    """
    node = payload
    if isinstance(node, dict) and "data" in node:
        inner = node["data"]
        if isinstance(inner, (dict, list)):
            node = inner
    for rec in _to_record_list(node) or ([node] if isinstance(node, dict) else []):
        for k in _ID_KEYS:
            if isinstance(rec, dict) and rec.get(k) is not None:
                return str(rec[k])
    raise RuntimeError(f"cannot parse e2e_job_id from submit response: {payload!r}")
