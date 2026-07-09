from datetime import timedelta
from temporalio import workflow
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from tse.constants import (Status, BUILD_RETRY, SUBMIT_RETRY, MONITOR_RETRY,
                               EVAL_RETRY, REPORT_RETRY, INFRA_RETRY)
    from tse.models.domain import (ExperimentRequest, ExperimentResult, SubmitArgs,
                                   ReportArgs, SimResult, EvalArtifacts, EvalArgs)
    from tse.activities.infra import mirror_status
    from tse.activities.build import build_binary
    from tse.activities.submit import submit_simulation
    from tse.activities.monitor import monitor_wait
    from tse.activities.evaluate import evaluate
    from tse.activities.report import generate_and_send_report


@workflow.defn
class ExperimentWorkflow:
    @workflow.run
    async def run(self, req: ExperimentRequest,
                  baseline_jobs: dict[str, list[int]] | None = None) -> ExperimentResult:
        # baseline_jobs 是评测期才用的运行时参数（来自 client CLI），不放进 ExperimentRequest。
        baseline_jobs = baseline_jobs or {}
        await self._set_status(req, Status.CREATED, branch=req.branch,
                               switches=req.switches,
                               temporal_workflow_id=workflow.info().workflow_id)

        # 1) 编包
        await self._set_status(req, Status.BUILDING, build_key=req.build_key())
        try:
            binary_id = await workflow.execute_activity(
                build_binary, req, start_to_close_timeout=timedelta(hours=1),
                retry_policy=BUILD_RETRY)
        except ApplicationError as e:
            await self._set_status(req, Status.BUILD_FAILED, error=str(e))
            raise
        await self._set_status(req, Status.BUILD_SUCCESS, binary_id=binary_id)

        # 2) 提交仿真
        args = SubmitArgs(binary_id=binary_id, req=req)
        sim_task_id = await workflow.execute_activity(
            submit_simulation, args, start_to_close_timeout=timedelta(minutes=10),
            retry_policy=SUBMIT_RETRY)
        await self._set_status(req, Status.SUBMITTED,
                               sim_task_id=sim_task_id, submit_key=args.submit_key())
        await self._set_status(req, Status.RUNNING)

        # 3) 监视等待：纯 API 轮询，封装在后台 Activity，仅终态返回（不触碰 LLM）
        #    仿真平台凭据由 client 随请求传入，透传给 monitor 用于查询鉴权。
        final: SimResult = await workflow.execute_activity(
            monitor_wait, args=[sim_task_id, req.sim_x_token, req.sim_x_account],
            start_to_close_timeout=timedelta(hours=12),
            heartbeat_timeout=timedelta(minutes=5), retry_policy=MONITOR_RETRY)
        if final.failed:
            await self._set_status(req, Status.SIMULATION_FAILED, error=final.error)
            raise ApplicationError("simulation failed", non_retryable=True)

        # 4) 评测拉取：跑 simworld 工具，产出渲染耗时 CSV + FM 轨迹评测图片
        #    候选 job = 本次 rerun 的 job（sim_task_id == --rerun-job-id），
        #    其 job_name 与提交 submit 时一致；基线 job 由 client CLI 携带。
        await self._set_status(req, Status.EVALUATING)
        candidate_job_name = req.job_name or f"{req.branch}_{req.experiment_id[:8]}"
        artifacts: EvalArtifacts = await workflow.execute_activity(
            evaluate, EvalArgs(sim_task_id=sim_task_id,
                               candidate_job_name=candidate_job_name,
                               baseline_jobs=baseline_jobs,
                               sim_x_token=req.sim_x_token,
                               sim_x_account=req.sim_x_account),
            start_to_close_timeout=timedelta(minutes=30), retry_policy=EVAL_RETRY)

        # 5) 报告 + 飞书：直接发送 CSV + 图片，不经 LLM
        await self._set_status(req, Status.REPORTING)
        report_url = await workflow.execute_activity(
            generate_and_send_report, ReportArgs(req=req, artifacts=artifacts),
            start_to_close_timeout=timedelta(minutes=15), retry_policy=REPORT_RETRY)
        await self._set_status(req, Status.COMPLETED, report_url=report_url)

        return ExperimentResult(experiment_id=req.experiment_id,
                                status=Status.COMPLETED, report_url=report_url)

    # —— 状态镜像：作为 Activity 执行（写 DB 是副作用，不能在 workflow 内直接做）——
    async def _set_status(self, req: ExperimentRequest, status: Status, **fields) -> None:
        await workflow.execute_activity(
            mirror_status, args=[req.experiment_id, status.value, fields],
            start_to_close_timeout=timedelta(seconds=30), retry_policy=INFRA_RETRY)
