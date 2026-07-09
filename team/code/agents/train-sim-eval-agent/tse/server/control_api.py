from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from temporalio.client import Client
from tse.config import get_settings
from tse.request.builder import build_request, plan_text, start_experiment
from tse.store.repo import ExperimentRepo

router = APIRouter()


class RunBody(BaseModel):
    switches: dict[str, bool] = {}
    template_e2e_job_id: int | None = None   # rerun 的模板 job_id（每次提交可变）
    job_name: str | None = None              # 任务名（每次提交可变）
    manifest_branch: str | None = None       # pipeline 清单分支（缺省走配置）
    baseline_jobs: dict[str, list[int]] = {}  # 评测基线 job（每次对比可不同；client CLI 传入）
    sim_x_token: str | None = None           # 仿真平台 x-token（client CLI 传入）
    sim_x_account: str | None = None         # 仿真平台 x-account（client CLI 传入）


def build_router(client: Client) -> APIRouter:
    repo = ExperimentRepo(get_settings().db_path)

    @router.post("/plan")
    async def plan(body: RunBody):
        req = build_request(body.switches,
                            template_e2e_job_id=body.template_e2e_job_id,
                            job_name=body.job_name,
                            manifest_branch=body.manifest_branch,
                            sim_x_token=body.sim_x_token,
                            sim_x_account=body.sim_x_account)
        return {"experiment_id": req.experiment_id, "plan": plan_text(req)}

    @router.post("/run")
    async def run(body: RunBody):
        req = build_request(body.switches,
                            template_e2e_job_id=body.template_e2e_job_id,
                            job_name=body.job_name,
                            manifest_branch=body.manifest_branch,
                            sim_x_token=body.sim_x_token,
                            sim_x_account=body.sim_x_account)
        await start_experiment(client, req, body.baseline_jobs)
        return {"experiment_id": req.experiment_id}

    @router.get("/status/{eid}")
    async def status(eid: str):
        row = repo.get(eid)
        if not row:
            raise HTTPException(404, "not found")
        return row

    @router.get("/list")
    async def list_(limit: int = 50):
        return repo.list(limit)

    @router.post("/cancel/{eid}")
    async def cancel(eid: str):
        await client.get_workflow_handle(f"exp-{eid}").cancel()
        return {"ok": True}

    # TODO: /watch 用 SSE/WebSocket 推送状态跃迁；/resume 见 §13
    return router
