from temporalio import activity

from tse.config import get_settings
from tse.integrations.feishu import FeishuClient
from tse.models.domain import ReportArgs
from tse.store.repo import ExperimentRepo


@activity.defn
async def generate_and_send_report(args: ReportArgs) -> str:
    """把评测产物（渲染耗时 CSV + FM 轨迹评测图片）直接发飞书，不经 LLM。"""
    s = get_settings()
    repo = ExperimentRepo(s.db_path)

    # 幂等：已发送过则直接返回旧引用（experiment_id 去重）
    existing = repo.get(args.req.experiment_id)
    if existing and existing.get("report_url") and existing.get("feishu_msg_id"):
        return existing["report_url"]

    title = f"[仿真评测] {args.req.branch} (exp {args.req.experiment_id[:8]})"
    msg_id, report_ref = FeishuClient(s).send_report_files(
        title=title, files=args.artifacts.files, idem_key=args.req.experiment_id)

    repo.upsert_status(args.req.experiment_id, status=_keep_current(existing),
                       report_url=report_ref, feishu_msg_id=msg_id)
    return report_ref


def _keep_current(existing: dict | None):
    from tse.constants import Status
    return Status(existing["status"]) if existing else Status.REPORTING
