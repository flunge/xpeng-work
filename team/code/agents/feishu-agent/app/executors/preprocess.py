from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

from app.domain.enums import TaskStatus
from app.domain.models import ExecutionResult, TaskArtifact, TaskRun
from app.executors.base import BaseExecutor
from app.infrastructure.repo_catalog import RepoScriptCatalog


class PreprocessExecutor(BaseExecutor):
    task_type_name = "pipeline.preprocess"

    def __init__(self, repo_root: str | None = None) -> None:
        if repo_root:
            self.repo_root = Path(repo_root).resolve()
        else:
            self.repo_root = Path(__file__).resolve().parents[3]

    def execute(self, task: TaskRun) -> ExecutionResult:
        config_path = task.params.get("config") or task.params.get("config_path") or "xpeng_data_process/configs/config_vision.yaml"
        clip_id = task.params.get("clip_id")
        if not clip_id:
            return ExecutionResult(
                status=TaskStatus.BLOCKED,
                current_stage="blocked",
                summary=(
                    "我已识别到你要提交 3DGS 预处理 Fuyao 任务，但还缺少必要参数。\n"
                    "请补充目标 `clip_id`，例如：\n"
                    "启动预处理 clip_id=c-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx job_name=test_preprocess_001"
                ),
                metrics={"reason": "missing_clip_id", "config_path": config_path},
            )

        job_name = self._safe_job_name(task.params.get("job_name") or f"preprocess_{task.task_id.lower()}")
        generated_config = self._generate_task_config(task, config_path=config_path, clip_id=clip_id)
        script_path = self.repo_root / RepoScriptCatalog.PREPROCESS.target_path
        if not script_path.is_file():
            return ExecutionResult(
                status=TaskStatus.FAILED,
                current_stage="failed",
                summary=f"预处理部署脚本不存在：{RepoScriptCatalog.PREPROCESS.target_path}",
                metrics={"script": str(script_path)},
            )

        command = ["bash", str(script_path), str(generated_config), job_name]
        completed = subprocess.run(command, cwd=str(self.repo_root), capture_output=True, text=True, check=False, timeout=120)
        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        output = "\n".join(part for part in [stdout, stderr] if part)
        artifacts = [
            TaskArtifact(
                task.task_id,
                "generated_config",
                str(generated_config),
                {"clip_id": clip_id, "source_config": config_path},
            ),
            TaskArtifact(
                task.task_id,
                "fuyao_submit_output",
                output[:8000] or "<empty>",
                {"returncode": completed.returncode, "job_name": job_name},
            ),
        ]
        metrics: dict[str, Any] = {
            "clip_id": clip_id,
            "config_path": config_path,
            "generated_config": str(generated_config),
            "job_name": job_name,
            "returncode": completed.returncode,
        }
        job_id = self._extract_job_id(output)
        if job_id:
            metrics["job_id"] = job_id

        if completed.returncode != 0:
            return ExecutionResult(
                status=TaskStatus.FAILED,
                current_stage="failed",
                summary=(
                    "预处理 Fuyao 任务提交失败。\n"
                    f"- Task: {task.task_id}\n"
                    f"- clip_id: {clip_id}\n"
                    f"- job_name: {job_name}\n"
                    f"- generated_config: {generated_config.relative_to(self.repo_root).as_posix()}\n"
                    f"- command: {' '.join(command)}\n"
                    f"- returncode: {completed.returncode}\n"
                    f"- 错误输出: {(stderr or stdout)[:1000]}"
                ),
                artifacts=artifacts,
                metrics=metrics,
            )

        return ExecutionResult(
            status=TaskStatus.PREPROCESSING,
            current_stage="preprocessing",
            summary=(
                "预处理 Fuyao 任务已提交。\n"
                f"- Task: {task.task_id}\n"
                f"- clip_id: {clip_id}\n"
                f"- job_name: {job_name}\n"
                f"- source_config: {config_path}\n"
                f"- generated_config: {generated_config.relative_to(self.repo_root).as_posix()}\n"
                f"- command: {' '.join(command)}\n"
                "- fuyao_site: fuyao_b1_prod2\n"
                "- status_cmd: fuyao view --site fuyao_b1_prod2 --only-me"
                + (f"\n- job_id: {job_id}" if job_id else "")
            ),
            artifacts=artifacts,
            metrics=metrics,
        )

    def _generate_task_config(self, task: TaskRun, *, config_path: str, clip_id: str) -> Path:
        source = (self.repo_root / config_path).resolve()
        source.relative_to(self.repo_root)
        with source.open("r", encoding="utf-8") as fp:
            config = yaml.safe_load(fp) or {}

        datasets = config.setdefault("datasets", [{}])
        if not datasets:
            datasets.append({})
        datasets[0]["clip_id"] = clip_id
        if task.params.get("dataset_name"):
            datasets[0]["dataset_name"] = task.params["dataset_name"]
        if task.params.get("root"):
            datasets[0]["root"] = task.params["root"]

        output_dir = self.repo_root / "agents" / "data" / "generated_configs"
        output_dir.mkdir(parents=True, exist_ok=True)
        generated = output_dir / f"preprocess_{task.task_id.lower()}.yaml"
        with generated.open("w", encoding="utf-8") as fp:
            yaml.safe_dump(config, fp, allow_unicode=True, sort_keys=False)
        return generated

    def _safe_job_name(self, value: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
        return safe[:80] or "preprocess_job"

    def _extract_job_id(self, output: str) -> str | None:
        patterns = [
            r"job[_ -]?id[:=]\s*([A-Za-z0-9_.:-]+)",
            r"job[:=]\s*([A-Za-z0-9_.:-]+)",
            r"(fy[a-zA-Z0-9_.:-]{6,})",
        ]
        for pattern in patterns:
            match = re.search(pattern, output, flags=re.IGNORECASE)
            if match:
                return match.group(1)
        return None
