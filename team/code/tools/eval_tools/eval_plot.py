import json
from pathlib import Path
from typing import List, Set

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

BASELINE_MODELS = ["3dgs_alone", "origin_difix", "origin_png", "origin_png_fixed"]
METADATA_COLS = {"clip_id", "outlier_score", "outlier_threshold", "is_outlier"}
POINT_COUNT_TO_PLOT = 3


def load_psnr_df(input_root: str) -> pd.DataFrame:
    root = Path(input_root).expanduser().resolve()
    psnr_rows = {}

    for folder in sorted(root.glob("compare_inference_*")):
        if not folder.is_dir():
            continue
        model_name = folder.name.replace("compare_inference_", "", 1)
        psnr_json = folder / "compare_psnr.json"
        if not psnr_json.exists():
            continue

        try:
            data = json.loads(psnr_json.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[WARN] 读取失败 {psnr_json}: {exc}")
            continue

        per_clip = data.get("per_clip", {})
        for clip_id, clip_vals in per_clip.items():
            row = psnr_rows.setdefault(clip_id, {"clip_id": clip_id})
            row[f"psnr_{model_name}"] = clip_vals.get("mean_psnr_ckpt")
            row["psnr_origin_difix"] = clip_vals.get("mean_psnr_origin")
            row["psnr_3dgs_alone"] = clip_vals.get("mean_psnr_input_origin")
            # origin_png 没有 PSNR，保留空列用于显示
            row["psnr_origin_png"] = np.nan
            row["psnr_origin_png_fixed"] = np.nan

    if not psnr_rows:
        return pd.DataFrame(columns=["clip_id"])

    psnr_df = pd.DataFrame(psnr_rows.values())
    psnr_df = psnr_df.sort_values("clip_id").reset_index(drop=True)
    return psnr_df


def _resolve_models(requested_models: List[str], available_models: Set[str]) -> List[str]:
    """将请求模型名尽量映射到可用模型名（用于 PSNR / 误差解耦场景）。"""
    resolved = []
    seen = set()

    def _try_add(name: str) -> bool:
        if name in available_models and name not in seen:
            resolved.append(name)
            seen.add(name)
            return True
        return False

    for model in requested_models:
        if _try_add(model):
            continue
        if model.startswith("sim_") and _try_add(model[len("sim_") :]):
            continue
        if "_epoch_" in model and "_origin_epoch_" not in model:
            alias = model.replace("_epoch_", "_origin_epoch_", 1)
            if _try_add(alias):
                continue
        if "_origin_epoch_" in model:
            alias = model.replace("_origin_epoch_", "_epoch_", 1)
            if _try_add(alias):
                continue
    return resolved


def _filter_to_common_clips(
    df: pd.DataFrame,
    required_cols: List[str],
    metric_name: str,
) -> pd.DataFrame:
    raw_clip_count = len(df)
    if required_cols:
        df = df.dropna(subset=required_cols, how="any").copy()
    common_clip_count = len(df)
    print(
        f"[INFO] only_common_clips=True，{metric_name} 从 {raw_clip_count} 个 clip 过滤到 {common_clip_count} 个共有 clip"
    )
    return df


def _sort_clip_df(
    clip_df: pd.DataFrame,
    psnr_df: pd.DataFrame,
    sort_psnr_col: str,
) -> pd.DataFrame:
    if sort_psnr_col in clip_df.columns:
        return clip_df.sort_values(by=sort_psnr_col, ascending=False)

    if sort_psnr_col in psnr_df.columns:
        sort_df = psnr_df[["clip_id", sort_psnr_col]].copy()
        merged = clip_df.merge(sort_df, on="clip_id", how="left")
        merged = merged.sort_values(by=sort_psnr_col, ascending=False, na_position="last")
        return merged.drop(columns=[sort_psnr_col])

    return clip_df.sort_values(by="clip_id", ascending=True)


def _build_plot_df(clip_df: pd.DataFrame) -> pd.DataFrame:
    numeric_cols = [c for c in clip_df.columns if c not in METADATA_COLS]
    avg_row = {"clip_id": "AVERAGE"}
    if numeric_cols:
        avg_row.update(clip_df[numeric_cols].mean(numeric_only=True).to_dict())
    avg_df = pd.DataFrame([avg_row])
    return pd.concat([avg_df, clip_df], ignore_index=True)


def _summarize_columns(df: pd.DataFrame, cols: List[str], label_map: dict) -> pd.DataFrame:
    rows = []
    for col in cols:
        vals = pd.to_numeric(df[col], errors="coerce").dropna()
        if vals.empty:
            continue
        rows.append(
            {
                "model": label_map.get(col, col.replace("pos_", "").replace("psnr_", "")),
                "mean": vals.mean(),
                "median": vals.median(),
                "p90": vals.quantile(0.9),
                "std": vals.std(ddof=0),
                "count": int(vals.count()),
            }
        )
    return pd.DataFrame(rows)


def _is_point_metric_col(col: str) -> bool:
    return col.startswith(("acc_p", "pos_p", "long_p", "lat_p"))


def _metric_col(metric_name: str, model_name: str) -> str:
    return model_name if metric_name == "acc" else f"{metric_name}_{model_name}"


def _column_model_name(col: str, metric_name: str) -> str:
    prefix = f"{metric_name}_"
    return col[len(prefix) :] if col.startswith(prefix) else col


def main(
    csv_path: str,
    input_root: str,
    output_path: str = "fm_clip_error.png",
    sort_by: str = "",
    topk: int = 0,
    title: str = "PSNR & FM Error Comparison",
    epoch_models = None,
    only_common_clips: bool = False,
):
    error_df = pd.read_csv(csv_path)
    if "clip_id" not in error_df.columns:
        raise ValueError("CSV 缺少 clip_id 列")

    error_model_cols = [c for c in error_df.columns if c not in METADATA_COLS]
    if not error_model_cols:
        raise ValueError("CSV 不包含模型误差列")
    acc_model_cols = [
        c for c in error_model_cols
        if not c.startswith(("pos_", "long_", "lat_")) and not _is_point_metric_col(c)
    ]
    pos_model_cols = [c for c in error_model_cols if c.startswith("pos_") and not c.startswith("pos_p")]
    long_model_cols = [c for c in error_model_cols if c.startswith("long_") and not c.startswith("long_p")]
    lat_model_cols = [c for c in error_model_cols if c.startswith("lat_") and not c.startswith("lat_p")]

    error_clip_df = error_df[error_df["clip_id"] != "AVERAGE"].copy()
    raw_error_clip_count = len(error_clip_df)
    if "is_outlier" in error_clip_df.columns:
        outlier_mask = (
            error_clip_df["is_outlier"]
            .fillna(False)
            .astype(str)
            .str.lower()
            .isin({"true", "1", "yes"})
        )
        outlier_count = int(outlier_mask.sum())
        error_clip_df = error_clip_df[~outlier_mask].copy()
        print(
            f"[INFO] 可视化过滤异常 clip: {outlier_count}/{raw_error_clip_count}，"
            f"保留 {len(error_clip_df)} 个 clip"
        )
    psnr_df = load_psnr_df(input_root)
    if not psnr_df.empty and not error_clip_df.empty:
        psnr_df = psnr_df[psnr_df["clip_id"].isin(set(error_clip_df["clip_id"]))].copy()

    psnr_model_cols = [c for c in psnr_df.columns if c.startswith("psnr_")]
    psnr_models = sorted([c[len("psnr_") :] for c in psnr_model_cols])
    acc_models = sorted(acc_model_cols)
    pos_models = {_column_model_name(c, "pos") for c in pos_model_cols}
    long_models = {_column_model_name(c, "long") for c in long_model_cols}
    lat_models = {_column_model_name(c, "lat") for c in lat_model_cols}
    available_models = set(psnr_models) | set(acc_models)
    available_models |= pos_models | long_models | lat_models

    # 模型选择：PSNR 与误差独立。epoch_models 为空时自动取可用模型（排除 baseline）。
    if epoch_models is None:
        epoch_models = sorted(
            [m for m in available_models if m not in BASELINE_MODELS and m.startswith("v") and "epoch" in m]
        )
    else:
        epoch_models = _resolve_models(list(epoch_models), available_models)

    model_order = ["3dgs_alone", "origin_difix"] + epoch_models
    error_order = ["3dgs_alone", "origin_difix"] + epoch_models + ["origin_png"] + ["origin_png_fixed"]
    psnr_cols = [f"psnr_{m}" for m in model_order if f"psnr_{m}" in psnr_df.columns]
    acc_plot_cols = [m for m in error_order if m in acc_model_cols]
    pos_plot_cols = [f"pos_{m}" for m in error_order if f"pos_{m}" in pos_model_cols]
    long_plot_cols = [f"long_{m}" for m in error_order if f"long_{m}" in long_model_cols]
    lat_plot_cols = [f"lat_{m}" for m in error_order if f"lat_{m}" in lat_model_cols]

    if only_common_clips:
        psnr_df = _filter_to_common_clips(psnr_df, psnr_cols, "PSNR 统计")
        error_clip_df = _filter_to_common_clips(
            error_clip_df,
            acc_plot_cols + pos_plot_cols + long_plot_cols + lat_plot_cols,
            "FM 误差统计",
        )
        if psnr_cols and psnr_df.empty:
            raise ValueError("开启 only_common_clips 后，没有任何 clip 同时包含所有待展示模型的 PSNR 结果")
        if (acc_plot_cols or pos_plot_cols) and error_clip_df.empty:
            raise ValueError("开启 only_common_clips 后，没有任何 clip 同时包含所有待展示模型的 FM 误差结果")

    psnr_label_map = {
        "psnr_3dgs_alone": "3dgs",
        "psnr_origin_difix": "Origin Difix",
    }
    acc_label_map = {
        "origin_png": "Origin png",
        "origin_png_fixed": "Origin png fixed",
        "3dgs_alone": "3dgs",
        "origin_difix": "Origin Difix",
    }
    pos_label_map = {
        "pos_origin_png": "Origin png",
        "pos_origin_png_fixed": "Origin png fixed",
        "pos_3dgs_alone": "3dgs",
        "pos_origin_difix": "Origin Difix",
    }

    psnr_cols = [c for c in psnr_cols if c in psnr_df.columns]
    psnr_summary = _summarize_columns(psnr_df, psnr_cols, psnr_label_map)
    acc_summary = _summarize_columns(error_clip_df, acc_plot_cols, acc_label_map)
    pos_summary = _summarize_columns(error_clip_df, pos_plot_cols, pos_label_map)

    fig, axes = plt.subplots(6, 1, figsize=(15, 26), sharex=False)
    ax1, ax2, ax3, ax4, ax5, ax6 = axes

    if not psnr_summary.empty:
        x = np.arange(len(psnr_summary))
        ax1.bar(x, psnr_summary["mean"], color="#5DADE2", label="mean")
        ax1.errorbar(
            x,
            psnr_summary["mean"],
            yerr=psnr_summary["std"].fillna(0),
            fmt="none",
            ecolor="#1B4F72",
            capsize=4,
            label="std",
        )
        ax1.set_xticks(x)
        ax1.set_xticklabels(psnr_summary["model"], rotation=20, ha="right")
        ax1.set_ylabel("PSNR (dB)", fontsize=12, fontweight="bold")
        ax1.set_title("PSNR Summary", fontsize=15)
        ax1.legend(loc="best")
        ax1.grid(axis="y", linestyle="--", alpha=0.3)
    else:
        ax1.text(0.5, 0.5, "No PSNR data found", ha="center", va="center", transform=ax1.transAxes)
        ax1.set_title(title, fontsize=15)

    def _plot_error_summary(ax, summary_df: pd.DataFrame, ylabel: str, chart_title: str, colors: List[str]) -> None:
        if summary_df.empty:
            ax.text(0.5, 0.5, "No error data found", ha="center", va="center", transform=ax.transAxes)
            ax.set_title(chart_title, fontsize=15)
            return
        stat_names = ["mean", "median", "p90"]
        x = np.arange(len(stat_names))
        width = min(0.8 / max(len(summary_df), 1), 0.25)
        for idx, (_, row) in enumerate(summary_df.iterrows()):
            offset = (idx - (len(summary_df) - 1) / 2) * width
            values = [row[stat_name] for stat_name in stat_names]
            ax.bar(
                x + offset,
                values,
                width,
                label=row["model"],
                color=colors[idx % len(colors)],
            )
        ax.set_xticks(x)
        ax.set_xticklabels(stat_names)
        ax.set_ylabel(ylabel, fontsize=12, fontweight="bold")
        ax.set_title(chart_title, fontsize=15)
        ax.legend(loc="best")
        ax.grid(axis="y", linestyle="--", alpha=0.3)

    def _plot_point_summary(
        ax,
        metric_prefix: str,
        models: List[str],
        label_map: dict,
        ylabel: str,
        chart_title: str,
        colors: List[str],
    ) -> None:
        x = np.arange(POINT_COUNT_TO_PLOT)
        rows = []
        for model_name in models:
            values = []
            for point_idx in range(POINT_COUNT_TO_PLOT):
                col = f"{metric_prefix}_p{point_idx}_{model_name}"
                if col not in error_clip_df.columns:
                    values.append(np.nan)
                    continue
                values.append(pd.to_numeric(error_clip_df[col], errors="coerce").mean())
            if not all(pd.isna(v) for v in values):
                rows.append((model_name, values))

        if not rows:
            ax.text(0.5, 0.5, "No point error data found", ha="center", va="center", transform=ax.transAxes)
            ax.set_title(chart_title, fontsize=15)
            return

        width = min(0.8 / max(len(rows), 1), 0.25)
        for idx, (model_name, values) in enumerate(rows):
            offset = (idx - (len(rows) - 1) / 2) * width
            label = label_map.get(_metric_col(metric_prefix, model_name), model_name)
            ax.bar(x + offset, values, width, label=label, color=colors[idx % len(colors)])
        ax.set_xticks(x)
        ax.set_xticklabels([f"p{idx}" for idx in range(POINT_COUNT_TO_PLOT)])
        ax.set_ylabel(ylabel, fontsize=12, fontweight="bold")
        ax.set_title(chart_title, fontsize=15)
        ax.legend(loc="best")
        ax.grid(axis="y", linestyle="--", alpha=0.3)

    def _plot_axis_summary(ax, models: List[str], colors: List[str]) -> None:
        stat_names = ["long_mean", "lat_mean", "long_p90", "lat_p90"]
        x = np.arange(len(stat_names))
        rows = []
        for model_name in models:
            long_col = f"long_{model_name}"
            lat_col = f"lat_{model_name}"
            if long_col not in error_clip_df.columns and lat_col not in error_clip_df.columns:
                continue
            long_vals = pd.to_numeric(error_clip_df.get(long_col), errors="coerce").dropna() if long_col in error_clip_df.columns else pd.Series(dtype=float)
            lat_vals = pd.to_numeric(error_clip_df.get(lat_col), errors="coerce").dropna() if lat_col in error_clip_df.columns else pd.Series(dtype=float)
            values = [
                long_vals.mean() if not long_vals.empty else np.nan,
                lat_vals.mean() if not lat_vals.empty else np.nan,
                long_vals.quantile(0.9) if not long_vals.empty else np.nan,
                lat_vals.quantile(0.9) if not lat_vals.empty else np.nan,
            ]
            rows.append((model_name, values))

        if not rows:
            ax.text(0.5, 0.5, "No longitudinal/lateral data found", ha="center", va="center", transform=ax.transAxes)
            ax.set_title("Longitudinal / Lateral Position Error (Outliers Removed)", fontsize=15)
            return

        width = min(0.8 / max(len(rows), 1), 0.25)
        for idx, (model_name, values) in enumerate(rows):
            offset = (idx - (len(rows) - 1) / 2) * width
            ax.bar(x + offset, values, width, label=model_name, color=colors[idx % len(colors)])
        ax.set_xticks(x)
        ax.set_xticklabels(stat_names)
        ax.set_ylabel("Axis Pos Diff [m]", fontsize=12, fontweight="bold")
        ax.set_title("Longitudinal / Lateral Position Error (Outliers Removed)", fontsize=15)
        ax.legend(loc="best")
        ax.grid(axis="y", linestyle="--", alpha=0.3)

    _plot_error_summary(
        ax2,
        acc_summary,
        "Acceleration Diff [m/s2] (Lower is better)",
        "Acceleration Error Summary (10 Points Average, Outliers Removed)",
        ["#F9E79F", "#EC7063", "#943126", "#F5B7B1", "#7B241C", "#641E16"],
    )
    _plot_error_summary(
        ax3,
        pos_summary,
        "Pos Diff [m] (Lower is better)",
        "Position Error Summary (10 Points Average, Outliers Removed)",
        ["#D6EAF8", "#5DADE2", "#1B4F72", "#A9CCE3", "#2E86C1", "#154360"],
    )
    point_models = [m for m in error_order if m in available_models]
    _plot_point_summary(
        ax4,
        "acc",
        point_models,
        acc_label_map,
        "Acceleration Diff [m/s2]",
        "Per-Point Acceleration Error p0-p2 (Outliers Removed)",
        ["#F9E79F", "#EC7063", "#943126", "#F5B7B1", "#7B241C", "#641E16"],
    )
    _plot_point_summary(
        ax5,
        "pos",
        point_models,
        pos_label_map,
        "Pos Diff [m]",
        "Per-Point Position Error p0-p2 (Outliers Removed)",
        ["#D6EAF8", "#5DADE2", "#1B4F72", "#A9CCE3", "#2E86C1", "#154360"],
    )
    _plot_axis_summary(
        ax6,
        point_models,
        ["#ABEBC6", "#27AE60", "#145A32", "#82E0AA", "#1E8449", "#0B5345"],
    )

    plt.tight_layout()
    plt.savefig(output_path, dpi=200)
    plt.show()

    print("\n" + "=" * 70)
    print(
        f"{'Model':<25} | {'Avg PSNR':<12} | {'Avg Acc Err':<12} | "
        f"{'P90 Acc':<12} | {'Avg Pos Err':<12} | {'P90 Pos':<12} | "
        f"{'Avg Long':<12} | {'Avg Lat':<12}"
    )
    print("-" * 70)
    summary_models = []
    for m in error_order:
        if m not in summary_models:
            summary_models.append(m)
    for m in epoch_models:
        if m not in summary_models:
            summary_models.append(m)

    for model_name in summary_models:
        psnr_col = f"psnr_{model_name}"
        psnr_val = pd.to_numeric(psnr_df[psnr_col], errors="coerce").mean() if psnr_col in psnr_df.columns else np.nan
        acc_vals = pd.to_numeric(error_clip_df[model_name], errors="coerce").dropna() if model_name in error_clip_df.columns else pd.Series(dtype=float)
        acc_val = acc_vals.mean() if not acc_vals.empty else np.nan
        acc_p90 = acc_vals.quantile(0.9) if not acc_vals.empty else np.nan
        pos_col = f"pos_{model_name}"
        pos_vals = pd.to_numeric(error_clip_df[pos_col], errors="coerce").dropna() if pos_col in error_clip_df.columns else pd.Series(dtype=float)
        pos_val = pos_vals.mean() if not pos_vals.empty else np.nan
        pos_p90 = pos_vals.quantile(0.9) if not pos_vals.empty else np.nan
        long_col = f"long_{model_name}"
        long_vals = pd.to_numeric(error_clip_df[long_col], errors="coerce").dropna() if long_col in error_clip_df.columns else pd.Series(dtype=float)
        long_val = long_vals.mean() if not long_vals.empty else np.nan
        lat_col = f"lat_{model_name}"
        lat_vals = pd.to_numeric(error_clip_df[lat_col], errors="coerce").dropna() if lat_col in error_clip_df.columns else pd.Series(dtype=float)
        lat_val = lat_vals.mean() if not lat_vals.empty else np.nan
        psnr_text = f"{psnr_val:.6f}" if pd.notna(psnr_val) else "N/A"
        acc_text = f"{acc_val:.6f}" if pd.notna(acc_val) else "N/A"
        acc_p90_text = f"{acc_p90:.6f}" if pd.notna(acc_p90) else "N/A"
        pos_text = f"{pos_val:.6f}" if pd.notna(pos_val) else "N/A"
        pos_p90_text = f"{pos_p90:.6f}" if pd.notna(pos_p90) else "N/A"
        long_text = f"{long_val:.6f}" if pd.notna(long_val) else "N/A"
        lat_text = f"{lat_val:.6f}" if pd.notna(lat_val) else "N/A"
        print(
            f"{model_name:<25} | {psnr_text:<12} | {acc_text:<12} | "
            f"{acc_p90_text:<12} | {pos_text:<12} | {pos_p90_text:<12} | "
            f"{long_text:<12} | {lat_text:<12}"
        )
    print("=" * 70)


if __name__ == "__main__":
    input_root = "/workspace/yangxh7@xiaopeng.com/difix3D_train/eval"
    csv_path = f"{input_root}/fm_clip_error_selected.csv"
    output_path = f"{input_root}/fm_clip_error_selected.png"
    sort_by = ""  # 不填则按第一个 epoch 模型排序
    topk = 0      # 0 表示全部
    title = "PSNR & FM Error Comparison"
    # 只展示这些模型（3dgs_alone / origin_difix / origin_png 会自动加入）
    epoch_models = [
        # "v1_epoch_0042_step_126000",
        # "v2_epoch_0030_step_090000",
    ]

    main(
        csv_path=csv_path,
        input_root=input_root,
        output_path=output_path,
        sort_by=sort_by,
        topk=topk,
        title=title,
        epoch_models=epoch_models if epoch_models else None,
    )