"""simworld 评测工具适配层。

把 simworld 仓库 ``tools/`` 下的四个独立脚本封装为 Agent 可调用的函数：

  - 渲染耗时：``render_time_analysis/log_downloader``（下载日志）
              + ``render_time_analysis/time_analyze``（统计 CSV）
  - FM 轨迹评测：``eval_tools/eval_tasks_download``（下载 fm_output_comparison.json）
              + ``eval_tools/eval_main``（评测 + 画图）

这些脚本原为「写死配置 + ``__main__``」的单文件工具，含模块级 ``TOKEN`` / ``USER`` /
输出路径 / 任务 id。本适配层在调用前注入凭据与输出路径（来自 :class:`Settings`），
并以参数化方式调用其内部函数，**不修改 simworld 仓库源码**。

重依赖（pandas / matplotlib / requests）由各工具按需引入：本模块只在函数体内
延迟 import 工具模块，导入本模块本身不触发这些依赖，便于无重依赖环境下做单测。
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

from tse.config import Settings

# time_analyze 汇总表字段（与 tools/render_time_analysis/time_analyze.py 的 main 对齐）。
# 显式列出以便 folder_rows 为空时仍能写出带表头的 CSV。
_RENDER_SUMMARY_FIELDNAMES = [
    "folder",
    "scenario_count",
    "total_frames",
    "avg_scenario_total_render_cost_sec",
    "avg_gpu_before_allocated_gib",
    "avg_gpu_after_allocated_gib",
    "max_gpu_before_allocated_gib",
    "max_gpu_after_allocated_gib",
    "avg_gpu_before_reserved_gib",
    "avg_gpu_after_reserved_gib",
    "avg_gpu_before_cuda_free_gib",
    "avg_gpu_after_cuda_free_gib",
    "min_gpu_before_cuda_free_gib",
    "min_gpu_after_cuda_free_gib",
    "max_gpu_after_peak_allocated_gib",
]


def _render_tools_dir(s: Settings) -> str:
    return str(Path(s.simworld_repo_root) / "tools" / "render_time_analysis")


def _eval_tools_dir(s: Settings) -> str:
    return str(Path(s.simworld_repo_root) / "tools" / "eval_tools")


def _load_module(tools_dir: str, module_name: str):
    """把工具目录加入 sys.path 后导入模块（重依赖在工具模块内按需引入）。"""
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    return importlib.import_module(module_name)


def run_render_time_analysis(s: Settings, jobs: dict[str, list[int]],
                             output_dir: Path) -> dict[str, str]:
    """下载渲染日志并统计渲染耗时，输出汇总/明细两张 CSV。

    :param jobs: 标签 -> e2e_job_id 列表（候选 + 基线一起统计对比）。
    :returns: ``{"summary_csv": ..., "detail_csv": ...}``（绝对/相对路径字符串）。
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    log_mod = _load_module(_render_tools_dir(s), "log_downloader")

    download_root = output_dir / "time_analysis"
    download_root.mkdir(parents=True, exist_ok=True)
    # 凭据（x-token / x-account）与任务均以函数参数传入，工具脚本不再写死。
    log_mod.download_all_job_data(
        jobs,
        [s.eval_render_log_file],
        s.sim_x_token,
        s.sim_x_account,
        target_scenario_ids=None,
        max_scenario_numbers=s.eval_render_max_scenarios,
        output_root=str(download_root),
    )

    ta = _load_module(_render_tools_dir(s), "time_analyze")
    folder_rows, detail_rows = ta.analyze_folders(download_root, s.eval_render_log_glob)

    summary_csv = output_dir / "render_time_summary.csv"
    detail_csv = output_dir / "render_time_detail.csv"
    ta.write_csv(folder_rows, summary_csv, _RENDER_SUMMARY_FIELDNAMES)
    pivot_rows, pivot_fieldnames = ta.build_detail_pivot_rows(detail_rows)
    ta.write_csv(pivot_rows, detail_csv, pivot_fieldnames)

    return {"summary_csv": str(summary_csv), "detail_csv": str(detail_csv)}


def run_fm_eval(s: Settings, jobs: dict[str, list[int]], eval_root: Path,
                models: list[str]) -> dict[str, str]:
    """下载 FM 输出对比文件并评测画图，输出逐 clip 误差 CSV + 对比图片。

    :param jobs: 标签 -> e2e_job_id 列表（候选 + 基线；``origin_png`` 为内置 baseline）。
    :param eval_root: 评测根目录（``eval_tasks_download`` 在其下创建 ``sim_<标签>`` 子目录）。
    :param models: 参与画图的模型标签（``eval_main`` 内部会自动并入 baseline）。
    :returns: ``{"fm_csv": ..., "fm_png": ...}``。
    """
    eval_root = Path(eval_root)
    eval_root.mkdir(parents=True, exist_ok=True)

    etd = _load_module(_eval_tools_dir(s), "eval_tasks_download")
    # 凭据与任务均以函数参数传入，工具脚本不再写死。
    etd.download_all_task_data(jobs, s.sim_x_token, s.sim_x_account,
                               output_root=str(eval_root))

    em = _load_module(_eval_tools_dir(s), "eval_main")
    output_csv = eval_root / "fm_clip_error_selected.csv"
    output_png = eval_root / "fm_clip_error_selected.png"
    em.run_eval(
        root_dir=eval_root,
        input_root=eval_root,
        output_csv=output_csv,
        output_png=output_png,
        models=models,
        only_common_clips=True,
    )
    return {"fm_csv": str(output_csv), "fm_png": str(output_png)}
