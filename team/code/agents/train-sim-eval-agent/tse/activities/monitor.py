import asyncio
from temporalio import activity
from tse.config import effective_settings
from tse.integrations.sim_cloud import SimCloudClient, classify_terminal
from tse.models.domain import SimResult

# 自适应轮询间隔（秒）：前期密，后期退避，降低平台压力
_INTERVALS = [30, 30, 60, 60, 120, 300]


@activity.defn
async def monitor_wait(sim_task_id: str, sim_x_token: str | None = None,
                       sim_x_account: str | None = None) -> SimResult:
    """在 Worker 进程内纯 API 轮询，仅终态返回。等待期间不触碰 LLM、不返回中间态。

    仿真平台凭据由 client 随请求传入（透过工作流），覆盖 .env 配置后用于查询鉴权。
    """
    client = SimCloudClient(effective_settings(sim_x_token, sim_x_account))
    i = 0
    while True:
        status = client.query_status(sim_task_id)
        activity.heartbeat({"sim_task_id": sim_task_id, "status": status})  # 心跳：崩溃后可续起
        terminal = classify_terminal(status)
        if terminal == "ok":
            return SimResult(failed=False, status=status)
        if terminal == "fail":
            return SimResult(failed=True, status=status, error=f"sim terminal: {status}")
        await asyncio.sleep(_INTERVALS[min(i, len(_INTERVALS) - 1)])
        i += 1
