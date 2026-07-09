import argparse
import csv
import re
from pathlib import Path


RENDER_COST_PATTERN = re.compile(r"^render cost\s+([0-9]+(?:\.[0-9]+)?)$")
GPU_MEMORY_PATTERN = re.compile(
    r"\[GPU memory (?P<phase>before|after) strategy\.render\]\s+"
    r"allocated=(?P<allocated>[0-9]*\.?[0-9]+)\s+GiB\s+"
    r"reserved=(?P<reserved>[0-9]*\.?[0-9]+)\s+GiB\s+"
    r"cuda_free=(?P<cuda_free>[0-9]*\.?[0-9]+)\s+GiB\s+"
    r"cuda_total=(?P<cuda_total>[0-9]*\.?[0-9]+)\s+GiB"
    r"(?:\s+peak_allocated=(?P<peak_allocated>[0-9]*\.?[0-9]+)\s+GiB)?"
)


def _avg(values):
    return sum(values) / len(values) if values else 0.0


def _max(values):
    return max(values) if values else 0.0


def analyze_log_file(log_file_path: Path):
    """统计单个场景日志的总渲染耗时与帧数。"""
    render_costs = []
    gpu_before_allocated = []
    gpu_before_reserved = []
    gpu_before_cuda_free = []
    gpu_after_allocated = []
    gpu_after_reserved = []
    gpu_after_cuda_free = []
    gpu_after_peak_allocated = []

    try:
        with log_file_path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                render_match = RENDER_COST_PATTERN.match(line)
                if render_match:
                    render_costs.append(float(render_match.group(1)))
                    continue

                gpu_match = GPU_MEMORY_PATTERN.search(line)
                if not gpu_match:
                    continue

                phase = gpu_match.group("phase")
                allocated = float(gpu_match.group("allocated"))
                reserved = float(gpu_match.group("reserved"))
                cuda_free = float(gpu_match.group("cuda_free"))
                if phase == "before":
                    gpu_before_allocated.append(allocated)
                    gpu_before_reserved.append(reserved)
                    gpu_before_cuda_free.append(cuda_free)
                else:
                    gpu_after_allocated.append(allocated)
                    gpu_after_reserved.append(reserved)
                    gpu_after_cuda_free.append(cuda_free)
                    peak_allocated = gpu_match.group("peak_allocated")
                    if peak_allocated is not None:
                        gpu_after_peak_allocated.append(float(peak_allocated))
    except OSError as exc:
        print(f"读取失败: {log_file_path} ({exc})")
        return None

    return {
        "file": log_file_path,
        "total_cost": sum(render_costs),
        "frame_count": len(render_costs),
        "metric_type": "render_cost_line_start",
        "avg_gpu_before_allocated_gib": _avg(gpu_before_allocated),
        "avg_gpu_after_allocated_gib": _avg(gpu_after_allocated),
        "max_gpu_before_allocated_gib": _max(gpu_before_allocated),
        "max_gpu_after_allocated_gib": _max(gpu_after_allocated),
        "avg_gpu_before_reserved_gib": _avg(gpu_before_reserved),
        "avg_gpu_after_reserved_gib": _avg(gpu_after_reserved),
        "avg_gpu_before_cuda_free_gib": _avg(gpu_before_cuda_free),
        "avg_gpu_after_cuda_free_gib": _avg(gpu_after_cuda_free),
        "min_gpu_before_cuda_free_gib": min(gpu_before_cuda_free) if gpu_before_cuda_free else 0.0,
        "min_gpu_after_cuda_free_gib": min(gpu_after_cuda_free) if gpu_after_cuda_free else 0.0,
        "max_gpu_after_peak_allocated_gib": _max(gpu_after_peak_allocated),
    }


def analyze_folders(root_dir: Path, log_glob: str):
    """
    遍历 root_dir 下一级子目录，统计每个文件夹内所有场景日志：
    1) 每个日志文件总渲染耗时（按帧求和）
    2) 每个文件夹平均每场景总渲染耗时
    """
    folder_rows = []
    detail_rows = []
    folder_to_rows = {}
    folder_to_finished_scenarios = {}

    subdirs = sorted([p for p in root_dir.iterdir() if p.is_dir()], key=lambda p: p.name)
    for folder in subdirs:
        log_files = sorted(folder.glob(log_glob))
        if not log_files:
            continue

        status_file = folder / "scenario_status.csv"
        if status_file.exists():
            with status_file.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                finished_scenarios = {
                    str(row.get("scenario_id", "")).strip()
                    for row in reader
                    if str(row.get("task_status", "")).strip().lower() == "finished"
                    and str(row.get("scenario_id", "")).strip()
                }
        else:
            print(f"警告: 未找到状态文件，按无 finished 场景处理: {status_file}")
            finished_scenarios = set()
        folder_to_finished_scenarios[folder.name] = finished_scenarios

        folder_detail_rows = []

        for log_file in log_files:
            stat = analyze_log_file(log_file)
            if stat is None:
                continue

            scenario_id = log_file.name.split("_")[0]
            folder_detail_rows.append(
                {
                    "folder": folder.name,
                    "scenario_id": scenario_id,
                    "log_file": str(log_file),
                    "frame_count": stat["frame_count"],
                    "metric_type": stat["metric_type"],
                    "scenario_total_render_cost_sec": round(stat["total_cost"], 6),
                    "avg_gpu_before_allocated_gib": round(stat["avg_gpu_before_allocated_gib"], 6),
                    "avg_gpu_after_allocated_gib": round(stat["avg_gpu_after_allocated_gib"], 6),
                    "max_gpu_before_allocated_gib": round(stat["max_gpu_before_allocated_gib"], 6),
                    "max_gpu_after_allocated_gib": round(stat["max_gpu_after_allocated_gib"], 6),
                    "avg_gpu_before_reserved_gib": round(stat["avg_gpu_before_reserved_gib"], 6),
                    "avg_gpu_after_reserved_gib": round(stat["avg_gpu_after_reserved_gib"], 6),
                    "avg_gpu_before_cuda_free_gib": round(stat["avg_gpu_before_cuda_free_gib"], 6),
                    "avg_gpu_after_cuda_free_gib": round(stat["avg_gpu_after_cuda_free_gib"], 6),
                    "min_gpu_before_cuda_free_gib": round(stat["min_gpu_before_cuda_free_gib"], 6),
                    "min_gpu_after_cuda_free_gib": round(stat["min_gpu_after_cuda_free_gib"], 6),
                    "max_gpu_after_peak_allocated_gib": round(stat["max_gpu_after_peak_allocated_gib"], 6),
                }
            )

        if not folder_detail_rows:
            continue

        folder_to_rows[folder.name] = folder_detail_rows

    if not folder_to_rows:
        return folder_rows, detail_rows

    # 只保留所有 folder 都有数据的 scenario（即全量 finished 的交集）
    folder_names = sorted(folder_to_rows.keys())
    common_scenario_ids_by_status = None
    for folder_name in folder_names:
        finished_ids = folder_to_finished_scenarios.get(folder_name, set())
        if common_scenario_ids_by_status is None:
            common_scenario_ids_by_status = finished_ids
        else:
            common_scenario_ids_by_status &= finished_ids

    common_scenario_ids_by_status = common_scenario_ids_by_status or set()
    common_scenario_ids_by_log = None
    for folder_name in folder_names:
        scenario_ids = {
            row["scenario_id"]
            for row in folder_to_rows[folder_name]
            if row["frame_count"] > 0
        }
        if common_scenario_ids_by_log is None:
            common_scenario_ids_by_log = scenario_ids
        else:
            common_scenario_ids_by_log &= scenario_ids

    common_scenario_ids_by_log = common_scenario_ids_by_log or set()
    common_scenario_ids = common_scenario_ids_by_status & common_scenario_ids_by_log

    for folder_name in folder_names:
        filtered_rows = [
            row for row in folder_to_rows[folder_name]
            if row["scenario_id"] in common_scenario_ids
        ]
        detail_rows.extend(filtered_rows)

        if not filtered_rows:
            continue

        total_frames_in_folder = sum(row["frame_count"] for row in filtered_rows)
        total_cost_in_folder = sum(row["scenario_total_render_cost_sec"] for row in filtered_rows)
        avg_total_cost = total_cost_in_folder / len(filtered_rows)
        avg_gpu_before_allocated = sum(row["avg_gpu_before_allocated_gib"] for row in filtered_rows) / len(filtered_rows)
        avg_gpu_after_allocated = sum(row["avg_gpu_after_allocated_gib"] for row in filtered_rows) / len(filtered_rows)
        max_gpu_before_allocated = max(row["max_gpu_before_allocated_gib"] for row in filtered_rows)
        max_gpu_after_allocated = max(row["max_gpu_after_allocated_gib"] for row in filtered_rows)
        avg_gpu_before_reserved = sum(row["avg_gpu_before_reserved_gib"] for row in filtered_rows) / len(filtered_rows)
        avg_gpu_after_reserved = sum(row["avg_gpu_after_reserved_gib"] for row in filtered_rows) / len(filtered_rows)
        avg_gpu_before_cuda_free = sum(row["avg_gpu_before_cuda_free_gib"] for row in filtered_rows) / len(filtered_rows)
        avg_gpu_after_cuda_free = sum(row["avg_gpu_after_cuda_free_gib"] for row in filtered_rows) / len(filtered_rows)
        min_gpu_before_cuda_free = min(row["min_gpu_before_cuda_free_gib"] for row in filtered_rows)
        min_gpu_after_cuda_free = min(row["min_gpu_after_cuda_free_gib"] for row in filtered_rows)
        max_gpu_after_peak_allocated = max(row["max_gpu_after_peak_allocated_gib"] for row in filtered_rows)
        folder_rows.append(
            {
                "folder": folder_name,
                "scenario_count": len(filtered_rows),
                "total_frames": total_frames_in_folder,
                "avg_scenario_total_render_cost_sec": round(avg_total_cost, 6),
                "avg_gpu_before_allocated_gib": round(avg_gpu_before_allocated, 6),
                "avg_gpu_after_allocated_gib": round(avg_gpu_after_allocated, 6),
                "max_gpu_before_allocated_gib": round(max_gpu_before_allocated, 6),
                "max_gpu_after_allocated_gib": round(max_gpu_after_allocated, 6),
                "avg_gpu_before_reserved_gib": round(avg_gpu_before_reserved, 6),
                "avg_gpu_after_reserved_gib": round(avg_gpu_after_reserved, 6),
                "avg_gpu_before_cuda_free_gib": round(avg_gpu_before_cuda_free, 6),
                "avg_gpu_after_cuda_free_gib": round(avg_gpu_after_cuda_free, 6),
                "min_gpu_before_cuda_free_gib": round(min_gpu_before_cuda_free, 6),
                "min_gpu_after_cuda_free_gib": round(min_gpu_after_cuda_free, 6),
                "max_gpu_after_peak_allocated_gib": round(max_gpu_after_peak_allocated, 6),
            }
        )

    return folder_rows, detail_rows


def write_csv(rows, output_path: Path, fieldnames):
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_detail_pivot_rows(detail_rows):
    """
    将明细转为宽表：每行一个 scenario，每个 folder 各有耗时和帧数两列。
    """
    folder_names = sorted({row["folder"] for row in detail_rows})
    scenario_ids = sorted({row["scenario_id"] for row in detail_rows}, key=lambda x: int(x))

    scenario_folder_map = {}
    for row in detail_rows:
        scenario_folder_map[(row["scenario_id"], row["folder"])] = row

    pivot_rows = []
    for scenario_id in scenario_ids:
        pivot_row = {"scenario_id": scenario_id}
        for folder in folder_names:
            key = (scenario_id, folder)
            if key in scenario_folder_map:
                src = scenario_folder_map[key]
                pivot_row[f"{folder}_cost_sec"] = src["scenario_total_render_cost_sec"]
                pivot_row[f"{folder}_frame_count"] = src["frame_count"]
                pivot_row[f"{folder}_avg_gpu_before_allocated_gib"] = src["avg_gpu_before_allocated_gib"]
                pivot_row[f"{folder}_avg_gpu_after_allocated_gib"] = src["avg_gpu_after_allocated_gib"]
                pivot_row[f"{folder}_avg_gpu_before_cuda_free_gib"] = src["avg_gpu_before_cuda_free_gib"]
                pivot_row[f"{folder}_avg_gpu_after_cuda_free_gib"] = src["avg_gpu_after_cuda_free_gib"]
                pivot_row[f"{folder}_min_gpu_after_cuda_free_gib"] = src["min_gpu_after_cuda_free_gib"]
                pivot_row[f"{folder}_max_gpu_after_peak_allocated_gib"] = src["max_gpu_after_peak_allocated_gib"]
            else:
                pivot_row[f"{folder}_cost_sec"] = ""
                pivot_row[f"{folder}_frame_count"] = ""
                pivot_row[f"{folder}_avg_gpu_before_allocated_gib"] = ""
                pivot_row[f"{folder}_avg_gpu_after_allocated_gib"] = ""
                pivot_row[f"{folder}_avg_gpu_before_cuda_free_gib"] = ""
                pivot_row[f"{folder}_avg_gpu_after_cuda_free_gib"] = ""
                pivot_row[f"{folder}_min_gpu_after_cuda_free_gib"] = ""
                pivot_row[f"{folder}_max_gpu_after_peak_allocated_gib"] = ""
        pivot_rows.append(pivot_row)

    pivot_fieldnames = ["scenario_id"]
    for folder in folder_names:
        pivot_fieldnames.append(f"{folder}_cost_sec")
        pivot_fieldnames.append(f"{folder}_frame_count")
        pivot_fieldnames.append(f"{folder}_avg_gpu_before_allocated_gib")
        pivot_fieldnames.append(f"{folder}_avg_gpu_after_allocated_gib")
        pivot_fieldnames.append(f"{folder}_avg_gpu_before_cuda_free_gib")
        pivot_fieldnames.append(f"{folder}_avg_gpu_after_cuda_free_gib")
        pivot_fieldnames.append(f"{folder}_min_gpu_after_cuda_free_gib")
        pivot_fieldnames.append(f"{folder}_max_gpu_after_peak_allocated_gib")

    return pivot_rows, pivot_fieldnames


def print_table(rows):
    if not rows:
        print("没有可统计的数据。")
        return

    headers = [
        "folder",
        "scenario_count",
        "total_frames",
        "avg_scenario_total_render_cost_sec",
        "avg_gpu_before_allocated_gib",
        "avg_gpu_after_allocated_gib",
        "avg_gpu_before_cuda_free_gib",
        "avg_gpu_after_cuda_free_gib",
    ]
    print("| " + " | ".join(headers) + " |")
    print("|" + "|".join(["---"] * len(headers)) + "|")
    for row in rows:
        print(
            f"| {row['folder']} | {row['scenario_count']} | {row['total_frames']} | "
            f"{row['avg_scenario_total_render_cost_sec']:.6f} | "
            f"{row['avg_gpu_before_allocated_gib']:.6f} | "
            f"{row['avg_gpu_after_allocated_gib']:.6f} | "
            f"{row['avg_gpu_before_cuda_free_gib']:.6f} | "
            f"{row['avg_gpu_after_cuda_free_gib']:.6f} |"
        )


def main():
    parser = argparse.ArgumentParser(description="统计各任务文件夹下场景日志的平均总渲染耗时。")
    parser.add_argument(
        "--root-dir",
        default="/workspace/yangxh7@xiaopeng.com/time_analysis/",
        help="日志根目录（默认当前目录）",
    )
    parser.add_argument(
        "--log-glob",
        default="*_3dgs_server1_out.log",
        help="日志文件匹配模式（默认: *_3dgs_server1_out.log）",
    )
    parser.add_argument(
        "--summary-csv",
        default="render_time_summary.csv",
        help="按文件夹汇总结果 CSV 输出路径",
    )
    parser.add_argument(
        "--detail-csv",
        default="render_time_detail.csv",
        help="按场景明细结果 CSV 输出路径",
    )
    args = parser.parse_args()

    root_dir = Path(args.root_dir).resolve()
    folder_rows, detail_rows = analyze_folders(root_dir, args.log_glob)

    summary_csv = Path(args.summary_csv)
    detail_csv = Path(args.detail_csv)

    write_csv(
        folder_rows,
        summary_csv,
        [
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
        ],
    )

    pivot_rows, pivot_fieldnames = build_detail_pivot_rows(detail_rows)
    write_csv(
        pivot_rows,
        detail_csv,
        pivot_fieldnames,
    )

    print_table(folder_rows)
    print(f"\n已输出汇总表: {summary_csv.resolve()}")
    print(f"已输出明细表: {detail_csv.resolve()}")


if __name__ == "__main__":
    main()
    
"""
python3 time_analyze.py --root-dir /home/xpeng/codes/log_analysis
"""
