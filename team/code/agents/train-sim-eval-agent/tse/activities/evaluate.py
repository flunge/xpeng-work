from pathlib import Path

from temporalio import activity

from tse.config import Settings, effective_settings
from tse.integrations import simworld_tools
from tse.models.domain import EvalArgs, EvalArtifacts


def _candidate_job_id(sim_task_id: str) -> int:
    """候选 job 的 e2e_job_id（== 本次 rerun 的 --rerun-job-id；平台要求整数）。"""
    try:
        return int(str(sim_task_id).strip())
    except (TypeError, ValueError):
        raise RuntimeError(f"sim_task_id={sim_task_id!r} 非整数 e2e_job_id，无法评测")


def build_artifacts(s: Settings, sim_task_id: str, candidate_job_name: str,
                    baseline_jobs: dict[str, list[int]]) -> EvalArtifacts:
    """运行 simworld 工具产出报告物料：渲染耗时 CSV + FM 轨迹评测图片。

    1) 渲染耗时：log_downloader 下载日志 → time_analyze 统计汇总/明细 CSV。
    2) FM 评测：eval_tasks_download 下载 fm_output_comparison.json → eval_main 评测画图。
    返回所有产物路径；报告阶段据此直接发飞书（不经 LLM）。

    jobs 以 job_name 为键：候选 job（待评测，job_name=candidate_job_name，
    e2e_job_id=sim_task_id）与基线 job（baseline_jobs，仅来自 client CLI）合并为同一份，
    渲染耗时与 FM 评测复用之（两个下载脚本任务集合一致）。
    """
    candidate_id = _candidate_job_id(sim_task_id)
    output_dir = Path(s.eval_output_root) / str(sim_task_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    jobs = {name: list(ids) for name, ids in baseline_jobs.items()}
    jobs[candidate_job_name] = [candidate_id]   # 候选 job 覆盖同名基线

    render = simworld_tools.run_render_time_analysis(s, jobs, output_dir)
    fm = simworld_tools.run_fm_eval(
        s, jobs, output_dir / "fm_eval", models=list(jobs))

    # 飞书发送顺序：FM 评测图片在前（消息可预览），其后附 CSV 文件。
    files = [p for p in (fm.get("fm_png"), render.get("summary_csv"),
                         render.get("detail_csv"), fm.get("fm_csv")) if p]
    return EvalArtifacts(
        output_dir=str(output_dir),
        render_time_summary_csv=render.get("summary_csv"),
        render_time_detail_csv=render.get("detail_csv"),
        fm_eval_image=fm.get("fm_png"),
        fm_eval_csv=fm.get("fm_csv"),
        files=files,
    )


@activity.defn
async def evaluate(args: EvalArgs) -> EvalArtifacts:
    # 仿真平台凭据由 client 随请求传入，覆盖 .env 配置后供下载工具鉴权。
    s = effective_settings(args.sim_x_token, args.sim_x_account)
    return build_artifacts(s, args.sim_task_id,
                           args.candidate_job_name, args.baseline_jobs)
