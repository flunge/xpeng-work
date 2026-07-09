import json
from math import sqrt
from pathlib import Path
from typing import Dict, List, Optional, Set

import pandas as pd


BASELINE_MODELS: Set[str] = {"3dgs_alone", "origin_png", "origin_difix"}
METADATA_COLS = {"clip_id", "outlier_score", "outlier_threshold", "is_outlier"}
CACHE_VERSION = 1


def load_json_data(file_path: Path):
    """兼容两种格式：JSON 数组 / JSONL。"""
    text = file_path.read_text(encoding="utf-8").strip()
    if not text:
        return []

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        pass

    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _resolve_target_models(target_models: Set[str], available_models: List[str]) -> Set[str]:
    """将用户传入模型名尽量映射到目录中的真实模型名。"""
    available_set = set(available_models)
    resolved: Set[str] = set()
    unresolved: List[str] = []

    for model in sorted(target_models):
        if model in available_set:
            resolved.add(model)
            continue

        # 允许用户写 sim_xxx
        if model.startswith("sim_"):
            stripped = model[len("sim_") :]
            if stripped in available_set:
                resolved.add(stripped)
                continue

        # 兼容 v*_epoch_* -> v*_origin_epoch_*
        if "_epoch_" in model and "_origin_epoch_" not in model:
            alias = model.replace("_epoch_", "_origin_epoch_", 1)
            if alias in available_set:
                resolved.add(alias)
                print(f"[INFO] 模型名自动映射: {model} -> {alias}")
                continue

        unresolved.append(model)

    if unresolved:
        print(f"[WARN] 以下模型在 sim_* 目录中不存在，已跳过: {sorted(unresolved)}")

    return resolved


def _infer_seconds_scale(timestamp_value: float) -> float:
    """按时间戳量级推断 1 秒对应单位。"""
    abs_v = abs(timestamp_value)
    if abs_v > 1e17:
        return 1e9  # ns
    if abs_v > 1e14:
        return 1e6  # us
    if abs_v > 1e11:
        return 1e3  # ms
    return 1.0  # s


def _to_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_trigger_source_time(sim_data: Dict) -> Optional[float]:
    """从 sim 帧中提取 trigger 对应的 source_time（pass_trigger_timestamp=True）。"""
    trigger_times: List[float] = []
    for source_time, sim_item in sim_data.items():
        if sim_item.get("pass_trigger_timestamp"):
            source_ts = _to_float(source_time)
            if source_ts is not None:
                trigger_times.append(source_ts)
    if not trigger_times:
        return None
    # 若存在多个 trigger 帧，使用最早一个作为 trigger 时刻
    return min(trigger_times)


def match_frames(data: List[dict], trigger_lead_seconds: Optional[float] = 0.0) -> List[dict]:
    """根据 source_time 匹配 real 和 sim 数据帧。"""
    real_data = {item["source_time"]: item for item in data if item.get("type") == "real"}
    sim_data = {item["source_time"]: item for item in data if item.get("type") == "sim"}
    trigger_source_time = _extract_trigger_source_time(sim_data)

    window_start = None
    if trigger_lead_seconds is not None:
        if trigger_source_time is None:
            return []
        scale = _infer_seconds_scale(trigger_source_time)
        window_start = trigger_source_time - trigger_lead_seconds * scale

    matched = []
    for source_time, real_item in real_data.items():
        sim_item = sim_data.get(source_time)
        if not sim_item:
            continue
        if window_start is not None:
            source_ts = _to_float(source_time)
            if source_ts is None or source_ts < window_start:
                continue
        matched.append({"real": real_item, "sim": sim_item})
    return matched


def extract_first_n_points(trajectory_points: List, n: int = 5) -> List:
    return trajectory_points[:n]


def calculate_acc_rmse(real_points: List, sim_points: List) -> Optional[float]:
    """加速度 RMSE，轨迹点等权。"""
    squared_errors = []
    for real_point, sim_point in zip(real_points, sim_points):
        try:
            a_real = real_point[1]["a"]
            a_sim = sim_point[1]["a"]
        except (IndexError, KeyError, TypeError):
            continue
        squared_errors.append((a_real - a_sim) ** 2)

    if not squared_errors:
        return None
    return sqrt(sum(squared_errors) / len(squared_errors))


def calculate_xy_rmse(real_points: List, sim_points: List) -> Optional[float]:
    squared_errors = []
    for real_point, sim_point in zip(real_points, sim_points):
        try:
            x_real = real_point[1]["x"]
            y_real = real_point[1]["y"]
            x_sim = sim_point[1]["x"]
            y_sim = sim_point[1]["y"]
        except (IndexError, KeyError, TypeError):
            continue
        squared_errors.append((x_real - x_sim) ** 2 + (y_real - y_sim) ** 2)

    if not squared_errors:
        return None
    return sqrt(sum(squared_errors) / len(squared_errors))


def calculate_axis_rmse(real_points: List, sim_points: List, axis: str) -> Optional[float]:
    squared_errors = []
    for real_point, sim_point in zip(real_points, sim_points):
        try:
            real_value = real_point[1][axis]
            sim_value = sim_point[1][axis]
        except (IndexError, KeyError, TypeError):
            continue
        squared_errors.append((real_value - sim_value) ** 2)

    if not squared_errors:
        return None
    return sqrt(sum(squared_errors) / len(squared_errors))


def _rmse(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return sqrt(sum(values) / len(values))


def calculate_clip_metrics(
    json_data: List[dict],
    n_points: int = 10,
    trigger_lead_seconds: Optional[float] = 0.0,
) -> Dict[str, float]:
    matched_frames = match_frames(
        json_data, trigger_lead_seconds=trigger_lead_seconds
    )
    if not matched_frames:
        return {}

    frame_acc_errors: List[float] = []
    frame_pos_errors: List[float] = []
    frame_long_errors: List[float] = []
    frame_lat_errors: List[float] = []
    point_acc_squared = [[] for _ in range(n_points)]
    point_pos_squared = [[] for _ in range(n_points)]
    point_long_squared = [[] for _ in range(n_points)]
    point_lat_squared = [[] for _ in range(n_points)]

    for frame in matched_frames:
        real_traj = frame["real"].get("trajectory_points", [])
        sim_traj = frame["sim"].get("trajectory_points", [])
        real_points = extract_first_n_points(real_traj, n=n_points)
        sim_points = extract_first_n_points(sim_traj, n=n_points)

        min_len = min(len(real_points), len(sim_points))
        if min_len == 0:
            continue
        real_points = real_points[:min_len]
        sim_points = sim_points[:min_len]

        acc_err = calculate_acc_rmse(real_points, sim_points)
        pos_err = calculate_xy_rmse(real_points, sim_points)
        long_err = calculate_axis_rmse(real_points, sim_points, "x")
        lat_err = calculate_axis_rmse(real_points, sim_points, "y")
        if acc_err is not None:
            frame_acc_errors.append(acc_err)
        if pos_err is not None:
            frame_pos_errors.append(pos_err)
        if long_err is not None:
            frame_long_errors.append(long_err)
        if lat_err is not None:
            frame_lat_errors.append(lat_err)

        for idx, (real_point, sim_point) in enumerate(zip(real_points, sim_points)):
            try:
                a_real = real_point[1]["a"]
                a_sim = sim_point[1]["a"]
                point_acc_squared[idx].append((a_real - a_sim) ** 2)
            except (IndexError, KeyError, TypeError):
                pass

            try:
                x_real = real_point[1]["x"]
                y_real = real_point[1]["y"]
                x_sim = sim_point[1]["x"]
                y_sim = sim_point[1]["y"]
            except (IndexError, KeyError, TypeError):
                continue
            dx = x_real - x_sim
            dy = y_real - y_sim
            point_long_squared[idx].append(dx ** 2)
            point_lat_squared[idx].append(dy ** 2)
            point_pos_squared[idx].append(dx ** 2 + dy ** 2)

    metrics: Dict[str, float] = {}
    for name, values in (
        ("acc", frame_acc_errors),
        ("pos", frame_pos_errors),
        ("long", frame_long_errors),
        ("lat", frame_lat_errors),
    ):
        if values:
            metrics[name] = sum(values) / len(values)

    for idx in range(n_points):
        for name, squared_errors in (
            (f"acc_p{idx}", point_acc_squared[idx]),
            (f"pos_p{idx}", point_pos_squared[idx]),
            (f"long_p{idx}", point_long_squared[idx]),
            (f"lat_p{idx}", point_lat_squared[idx]),
        ):
            err = _rmse(squared_errors)
            if err is not None:
                metrics[name] = err

    return metrics


def calculate_clip_error(
    json_data: List[dict],
    metric_type: str = "acceleration",
    n_points: int = 10,
    trigger_lead_seconds: Optional[float] = 0.0,
) -> Optional[float]:
    metrics = calculate_clip_metrics(
        json_data,
        n_points=n_points,
        trigger_lead_seconds=trigger_lead_seconds,
    )
    if metric_type == "acceleration":
        return metrics.get("acc")
    if metric_type == "position":
        return metrics.get("pos")
    if metric_type == "longitudinal":
        return metrics.get("long")
    if metric_type == "lateral":
        return metrics.get("lat")
    raise ValueError(f"不支持的 metric_type: {metric_type}")


def collect_model_clip_errors(
    root_dir: Path,
    n_points: int = 10,
    trigger_lead_seconds: Optional[float] = 0.0,
    target_models: Optional[Set[str]] = None,
) -> Dict[str, Dict[str, float]]:
    """返回结构: {clip_id: {metric_model_name: error}}"""
    result: Dict[str, Dict[str, float]] = {}
    sim_dirs = sorted([p for p in root_dir.iterdir() if p.is_dir() and p.name.startswith("sim_")])
    cache_path = root_dir / ".fm_clip_metrics_cache.json"
    cache_entries: Dict[str, Dict] = {}
    cache_dirty = False

    if cache_path.exists():
        try:
            cache_payload = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cache_payload, dict) and cache_payload.get("version") == CACHE_VERSION:
                cache_entries = cache_payload.get("entries", {}) or {}
            else:
                print(f"[INFO] 缓存版本不匹配，忽略旧缓存: {cache_path}")
        except Exception as exc:
            print(f"[WARN] 读取缓存失败，忽略缓存 {cache_path}: {exc}")

    if not sim_dirs:
        raise FileNotFoundError(f"在目录 {root_dir} 下未找到 sim_ 开头文件夹")

    available_models = sorted([p.name[len("sim_") :] for p in sim_dirs])
    if target_models is not None:
        target_models = _resolve_target_models(target_models, available_models)
        print(f"[INFO] 所有可用模型名: {available_models}")
        print(f"[INFO] 本次仅计算模型: {sorted(target_models)}")
        if not target_models:
            return {}

    for sim_dir in sim_dirs:
        model_name = sim_dir.name[len("sim_") :]
        if target_models is not None and model_name not in target_models:
            continue
        json_files = sorted(sim_dir.glob("*.json"))
        print(f"[INFO] 模型 {model_name}: 发现 {len(json_files)} 个 json")

        for json_file in json_files:
            clip_id = json_file.stem
            try:
                stat = json_file.stat()
                cache_key = str(json_file.relative_to(root_dir))
                cache_sig = {
                    "mtime_ns": stat.st_mtime_ns,
                    "size": stat.st_size,
                    "n_points": n_points,
                    "trigger_lead_seconds": trigger_lead_seconds,
                }
                cached = cache_entries.get(cache_key)
                if cached and cached.get("sig") == cache_sig:
                    metrics = cached.get("metrics", {}) or {}
                else:
                    json_data = load_json_data(json_file)
                    metrics = calculate_clip_metrics(
                        json_data,
                        n_points=n_points,
                        trigger_lead_seconds=trigger_lead_seconds,
                    )
                    cache_entries[cache_key] = {
                        "sig": cache_sig,
                        "metrics": metrics,
                    }
                    cache_dirty = True
            except Exception as exc:
                print(f"[WARN] 读取或计算失败 {json_file}: {exc}")
                continue

            row = result.setdefault(clip_id, {})
            for metric_name, error in metrics.items():
                if metric_name == "acc":
                    col_name = model_name
                else:
                    col_name = f"{metric_name}_{model_name}"
                row[col_name] = error

    if cache_dirty:
        try:
            cache_path.write_text(
                json.dumps(
                    {
                        "version": CACHE_VERSION,
                        "entries": cache_entries,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            print(f"[INFO] 已更新缓存: {cache_path}")
        except Exception as exc:
            print(f"[WARN] 写入缓存失败 {cache_path}: {exc}")

    return result


def _mark_outlier_clips(
    df: pd.DataFrame,
    metric_cols: List[str],
    iqr_multiplier: float = 3.0,
) -> pd.DataFrame:
    clip_df = df.copy()
    if not metric_cols or len(clip_df) < 4:
        clip_df["outlier_score"] = clip_df[metric_cols].max(axis=1, skipna=True) if metric_cols else pd.NA
        clip_df["outlier_threshold"] = pd.NA
        clip_df["is_outlier"] = False
        return clip_df

    clip_df["outlier_score"] = clip_df[metric_cols].max(axis=1, skipna=True)
    scores = clip_df["outlier_score"].dropna()
    if len(scores) < 4:
        clip_df["outlier_threshold"] = pd.NA
        clip_df["is_outlier"] = False
        return clip_df

    q1 = scores.quantile(0.25)
    q3 = scores.quantile(0.75)
    iqr = q3 - q1
    if pd.isna(iqr) or iqr <= 0:
        clip_df["outlier_threshold"] = pd.NA
        clip_df["is_outlier"] = False
        return clip_df

    threshold = q3 + iqr_multiplier * iqr
    clip_df["outlier_threshold"] = threshold
    clip_df["is_outlier"] = clip_df["outlier_score"] > threshold
    outlier_count = int(clip_df["is_outlier"].sum())
    if outlier_count:
        print(
            f"[INFO] 异常 clip 过滤阈值: outlier_score > {threshold:.6f}，"
            f"标记 {outlier_count}/{len(clip_df)} 个 clip"
        )
    else:
        print(f"[INFO] 异常 clip 过滤阈值: outlier_score > {threshold:.6f}，未标记异常 clip")
    return clip_df


def build_dataframe(
    clip_errors: Dict[str, Dict[str, float]],
    outlier_iqr_multiplier: float = 3.0,
) -> pd.DataFrame:
    df = pd.DataFrame.from_dict(clip_errors, orient="index")
    df.index.name = "clip_id"
    df = df.sort_index().reset_index()

    metric_cols = [c for c in df.columns if c != "clip_id"]
    df = _mark_outlier_clips(df, metric_cols, iqr_multiplier=outlier_iqr_multiplier)
    valid_df = df[~df["is_outlier"]].copy()
    avg_row = {"clip_id": "AVERAGE"}
    avg_row.update(valid_df[metric_cols].mean(numeric_only=True).to_dict())
    avg_row["outlier_score"] = valid_df["outlier_score"].mean()
    avg_row["outlier_threshold"] = df["outlier_threshold"].dropna().iloc[0] if df["outlier_threshold"].notna().any() else pd.NA
    avg_row["is_outlier"] = False
    df = pd.concat([pd.DataFrame([avg_row]), df], ignore_index=True)
    return df


def main(
    root_dir: str,
    output_csv: str,
    n_points: int = 10,
    trigger_lead_seconds: Optional[float] = 0.0,
    models: Optional[List[str]] = None,
    outlier_iqr_multiplier: float = 3.0,
):
    root_dir = Path(root_dir).expanduser().resolve()
    output_csv = Path(output_csv).expanduser().resolve()

    target_models: Optional[Set[str]] = None
    if models:
        target_models = set(models) | BASELINE_MODELS
        print(f"[INFO] root_dir = {root_dir}")
        print(f"[INFO] 用户传入 models: {models}")
        print(f"[INFO] 实际使用的目标模型（包含 baseline）: {sorted(target_models)}")

    clip_errors = collect_model_clip_errors(
        root_dir=root_dir,
        n_points=n_points,
        trigger_lead_seconds=trigger_lead_seconds,
        target_models=target_models,
    )
    if not clip_errors:
        if target_models is not None:
            print(
                "[ERROR] 目标模型没有得到任何结果，请检查模型名称是否与 sim_ 前缀目录一致"
            )
        else:
            print("[ERROR] 没有得到任何可用误差结果")
        return

    df = build_dataframe(clip_errors, outlier_iqr_multiplier=outlier_iqr_multiplier)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False)
    acc_cols = [c for c in df.columns if c not in METADATA_COLS and not c.startswith(("pos_", "long_", "lat_", "acc_p"))]
    pos_cols = [c for c in df.columns if c.startswith("pos_")]
    print(f"[DONE] CSV 已输出: {output_csv}")
    outlier_count = int(df[df["clip_id"] != "AVERAGE"]["is_outlier"].sum())
    print(
        f"[DONE] clip 数: {len(df) - 1}, 异常 clip 数: {outlier_count}, "
        f"acceleration模型数: {len(acc_cols)}, position模型数: {len(pos_cols)}"
    )


if __name__ == "__main__":
    root_dir = "/workspace/yangxh7@xiaopeng.com/difix3D_train/eval"
    output_csv = "/workspace/yangxh7@xiaopeng.com/difix3D_train/eval/fm_clip_error_selected.csv"
    n_points = 10
    trigger_lead_seconds = 2.0  # 从 trigger frame 前 n 秒开始统计；None 表示不过滤
    outlier_iqr_multiplier = 3.0
    # 只评估这些模型（脚本内部会自动加上 3dgs_alone、origin_png、origin_difix）
    models = [
        # "v1_epoch_0042_step_126000",
        # "v2_epoch_0030_step_090000",
    ]

    main(
        root_dir=root_dir,
        output_csv=output_csv,
        n_points=n_points,
        trigger_lead_seconds=trigger_lead_seconds,
        models=models,
        outlier_iqr_multiplier=outlier_iqr_multiplier,
    )
