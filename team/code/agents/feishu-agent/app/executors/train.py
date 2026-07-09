from __future__ import annotations

from app.domain.enums import TaskStatus
from app.domain.models import ExecutionResult, TaskArtifact, TaskRun
from app.executors.base import BaseExecutor
from app.infrastructure.repo_catalog import RepoScriptCatalog


class TrainExecutor(BaseExecutor):
    task_type_name = "pipeline.train"

    def execute(self, task: TaskRun) -> ExecutionResult:
        config_path = task.params.get("config") or task.params.get("config_path") or "pipeline/configs/sim3dgs_v416.yaml"
        clip_id = task.params.get("clip_id", "unknown_clip")
        cameras = task.params.get("cameras") or task.params.get("cameras_id") or "023456"
        output_path = task.params.get("output_path", "/workspace/output")
        priority = task.params.get("priority", "normal")
        preview = (
            f"{RepoScriptCatalog.TRAIN.command_preview} -> clip_id={clip_id}, "
            f"config={config_path}, cameras={cameras}, output_path={output_path}, priority={priority}"
        )
        artifact = TaskArtifact(task.task_id, "command_preview", preview, {"script": RepoScriptCatalog.TRAIN.target_path})
        return ExecutionResult(
            status=TaskStatus.DONE,
            current_stage="training",
            summary=f"已为 clip `{clip_id}` 生成训练执行计划，camera_group=`{cameras}`。",
            artifacts=[artifact],
            metrics={
                "clip_id": clip_id,
                "config_path": config_path,
                "cameras": cameras,
                "output_path": output_path,
                "priority": priority,
            },
        )
