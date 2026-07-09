from temporalio import activity
from tse.config import get_settings, effective_settings
from tse.integrations.sim_cloud import SimCloudClient
from tse.models.domain import SubmitArgs
from tse.store.repo import ExperimentRepo


@activity.defn
async def submit_simulation(args: SubmitArgs) -> str:
    s = get_settings()
    repo = ExperimentRepo(s.db_path)

    cached = repo.find_task_by_submit_key(args.submit_key())
    if cached:
        return cached

    # 仿真平台凭据由 client 随请求传入，覆盖 .env 配置后用于提交鉴权。
    eff = effective_settings(args.req.sim_x_token, args.req.sim_x_account)
    return SimCloudClient(eff).submit(args)
