from __future__ import annotations

from app.domain.enums import TaskStatus
from app.domain.models import ExecutionResult, TaskArtifact, TaskRun
from app.executors.base import BaseExecutor
from app.infrastructure.repo_catalog import RepoScriptCatalog


class ReportGenerateExecutor(BaseExecutor):
    task_type_name = "report.generate"

    def execute(self, task: TaskRun) -> ExecutionResult:
        root_dir = task.params.get("root_dir", "/workspace/eval")
        models = task.params.get("models", [])
        preview = f"{RepoScriptCatalog.REPORT.command_preview} -> root_dir={root_dir}, models={models}"
        artifacts = [
            TaskArtifact(task.task_id, "command_preview", preview, {"script": RepoScriptCatalog.REPORT.target_path}),
            TaskArtifact(task.task_id, "report_file", "fm_clip_error_selected.csv", {"root_dir": root_dir}),
            TaskArtifact(task.task_id, "report_plot", "fm_clip_error_selected.png", {"root_dir": root_dir}),
        ]
        return ExecutionResult(
            status=TaskStatus.DONE,
            current_stage="reporting",
            summary=f"已生成评测报告计划，模型数量 {len(models)}，结果根目录 `{root_dir}`。",
            artifacts=artifacts,
            metrics={"root_dir": root_dir, "model_count": len(models)},
        )
