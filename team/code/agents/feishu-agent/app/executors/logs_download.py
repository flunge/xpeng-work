from __future__ import annotations

from app.domain.enums import TaskStatus
from app.domain.models import ExecutionResult, TaskArtifact, TaskRun
from app.executors.base import BaseExecutor
from app.infrastructure.repo_catalog import RepoScriptCatalog


class LogsDownloadExecutor(BaseExecutor):
    task_type_name = "logs.download"

    def execute(self, task: TaskRun) -> ExecutionResult:
        job_id = task.params.get("job_id", "unknown")
        scenarios = task.params.get("scenario_ids", [])
        preview = f"{RepoScriptCatalog.LOGS.command_preview} -> job_id={job_id}, scenario_ids={scenarios}"
        artifacts = [
            TaskArtifact(task.task_id, "command_preview", preview, {"script": RepoScriptCatalog.LOGS.target_path}),
            TaskArtifact(task.task_id, "status_schema", "scenario_status.csv", {"source": "tools/render_time_analysis/log_downloader.py"}),
        ]
        return ExecutionResult(
            status=TaskStatus.DONE,
            current_stage="evaluating",
            summary=f"已为 job `{job_id}` 生成日志下载计划，目标场景数 {len(scenarios)}。",
            artifacts=artifacts,
            metrics={"job_id": job_id, "scenario_count": len(scenarios)},
        )
