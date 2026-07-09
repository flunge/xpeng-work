import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from temporalio.contrib.pydantic import pydantic_data_converter

from tse.constants import TASK_QUEUE
from tse.workflows.experiment import ExperimentWorkflow
from tse.models.domain import ExperimentRequest, SubmitArgs, SimResult, EvalArtifacts, EvalArgs, ReportArgs


# —— 同名 stub activities：按活动名替换真实实现，隔离一切 IO ——
@activity.defn(name="mirror_status")
async def stub_mirror_status(experiment_id: str, status: str, fields: dict) -> None:
    return None


@activity.defn(name="build_binary")
async def stub_build_binary(req: ExperimentRequest) -> str:
    return "bin-123"


@activity.defn(name="submit_simulation")
async def stub_submit_simulation(args: SubmitArgs) -> str:
    return "task-456"


@activity.defn(name="monitor_wait")
async def stub_monitor_wait(sim_task_id: str, sim_x_token: str | None = None,
                            sim_x_account: str | None = None) -> SimResult:
    return SimResult(failed=False, status="COMPLETED")


@activity.defn(name="evaluate")
async def stub_evaluate(args: EvalArgs) -> EvalArtifacts:
    return EvalArtifacts(output_dir="/tmp/eval", fm_eval_image="/tmp/eval/fm.png",
                         render_time_summary_csv="/tmp/eval/render.csv",
                         files=["/tmp/eval/fm.png", "/tmp/eval/render.csv"])


@activity.defn(name="generate_and_send_report")
async def stub_report(args: ReportArgs) -> str:
    return "https://feishu/doc/xxx"


_STUBS = [stub_mirror_status, stub_build_binary, stub_submit_simulation,
          stub_monitor_wait, stub_evaluate, stub_report]


@pytest.mark.asyncio
async def test_happy_path():
    async with await WorkflowEnvironment.start_time_skipping(
            data_converter=pydantic_data_converter) as env:
        async with Worker(env.client, task_queue=TASK_QUEUE,
                          workflows=[ExperimentWorkflow], activities=_STUBS):
            req = ExperimentRequest(branch="b", ckpt_path="/c", switches={},
                                    experiment_id="e1")
            res = await env.client.execute_workflow(
                ExperimentWorkflow.run, req, id="w1", task_queue=TASK_QUEUE)
            assert res.status.value == "COMPLETED"
            assert res.report_url == "https://feishu/doc/xxx"


@pytest.mark.asyncio
async def test_simulation_failed_path():
    @activity.defn(name="monitor_wait")
    async def fail_monitor(sim_task_id: str, sim_x_token: str | None = None,
                           sim_x_account: str | None = None) -> SimResult:
        return SimResult(failed=True, status="FAILED", error="sim terminal: FAILED")

    stubs = [stub_mirror_status, stub_build_binary, stub_submit_simulation,
             fail_monitor, stub_evaluate, stub_report]

    async with await WorkflowEnvironment.start_time_skipping(
            data_converter=pydantic_data_converter) as env:
        async with Worker(env.client, task_queue=TASK_QUEUE,
                          workflows=[ExperimentWorkflow], activities=stubs):
            req = ExperimentRequest(branch="b", ckpt_path="/c", switches={},
                                    experiment_id="e2")
            with pytest.raises(Exception):
                await env.client.execute_workflow(
                    ExperimentWorkflow.run, req, id="w2", task_queue=TASK_QUEUE)
