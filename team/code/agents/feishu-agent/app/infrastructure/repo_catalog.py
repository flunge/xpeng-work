from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RepoCommand:
    name: str
    command_preview: str
    target_path: str


class RepoScriptCatalog:
    PREPROCESS = RepoCommand(
        name="submit_preprocess",
        command_preview="bash pipeline/fuyao/preprocess/deploy_preproc.bash <config_file> <job_name>",
        target_path="pipeline/fuyao/preprocess/deploy_preproc.bash",
    )
    TRAIN = RepoCommand(
        name="submit_train",
        command_preview="bash pipeline/fuyao/deploy_reconic.sh <config> <clip_id> <cameras_id> <output_path> <priority>",
        target_path="pipeline/fuyao/deploy_reconic.sh",
    )
    LOGS = RepoCommand(
        name="download_logs",
        command_preview="python tools/render_time_analysis/log_downloader.py",
        target_path="tools/render_time_analysis/log_downloader.py",
    )
    REPORT = RepoCommand(
        name="generate_eval_report",
        command_preview="python tools/eval_tools/eval_main.py",
        target_path="tools/eval_tools/eval_main.py",
    )
