import uuid
from temporalio.client import Client
from tse.constants import (TASK_QUEUE, SWITCH_WHITELIST,
                           SIMULATION_BRANCH, SIMWORLD_BRANCH)
from tse.models.domain import ExperimentRequest
from tse.workflows.experiment import ExperimentWorkflow
from tse.errors import RequestValidationError


def build_request(switches: dict | None = None,
                  template_e2e_job_id: int | None = None,
                  job_name: str | None = None,
                  manifest_branch: str | None = None,
                  sim_x_token: str | None = None,
                  sim_x_account: str | None = None) -> ExperimentRequest:
    """结构化参数 → 校验（含开关白名单）→ ExperimentRequest。不涉及 LLM。

    每次提交的可变项：template_e2e_job_id（rerun 模板 job_id）、job_name、
    stage1_binary_id（编包输出，运行时回填）、switches（全局开关）。
    编包多仓分支已 hardcode：simulation -> SIMULATION_BRANCH、simworld -> SIMWORLD_BRANCH
    （见 tse.constants），不再由 CLI / 请求传入；manifest_branch 缺省走服务端配置。
    注：评测基线 baseline_jobs 不属于本请求（编包/提交无关），单独随工作流启动传入。
    """
    switches = switches or {}
    bad = set(switches) - SWITCH_WHITELIST           # 开关白名单
    if bad:
        raise RequestValidationError(f"未知开关: {bad}")
    switches = {k: bool(v) for k, v in switches.items()}
    return ExperimentRequest(branch=SIMULATION_BRANCH, switches=switches,
                             experiment_id=str(uuid.uuid4()),
                             template_e2e_job_id=template_e2e_job_id,
                             job_name=(job_name or None),
                             simworld_branch=SIMWORLD_BRANCH,
                             manifest_branch=((manifest_branch or "").strip() or None),
                             sim_x_token=((sim_x_token or "").strip() or None),
                             sim_x_account=((sim_x_account or "").strip() or None))


def plan_text(req: ExperimentRequest) -> str:
    """供 CLI 预览的可读执行步骤。pipeline 固定，非 LLM 生成。"""
    simworld = (f"checkout simworld branch {req.simworld_branch}"
                if req.simworld_branch else "simworld branch unchanged")
    return "\n".join([
        f"1. (vm) checkout simulation branch {req.branch}; {simworld}",
        "2. (container) pipeline checkout_repo (manifest)",
        "3. build binary", "4. get binary id",
        "5. submit simulation", "6. wait completion (monitor, no LLM polling)",
        "7. eval: download + analyze (render-time csv + FM trajectory image)",
        "8. send report files to feishu (no LLM)",
    ])


async def start_experiment(client: Client, req: ExperimentRequest,
                           baseline_jobs: dict[str, list[int]] | None = None) -> str:
    """启动固定的 ExperimentWorkflow，返回 experiment_id。

    baseline_jobs 是评测期才用的运行时参数（来自 client CLI），作为工作流第二个入参传入，
    不混入 ExperimentRequest（编包/提交与基线无关）。
    """
    await client.start_workflow(
        ExperimentWorkflow.run, args=[req, baseline_jobs or {}],
        id=f"exp-{req.experiment_id}", task_queue=TASK_QUEUE)
    return req.experiment_id
