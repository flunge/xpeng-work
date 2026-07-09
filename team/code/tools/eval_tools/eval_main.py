from pathlib import Path
from typing import List, Set

import pandas as pd

from eval_fm_error import collect_model_clip_errors, build_dataframe
from eval_plot import main as plot_main


BASELINE_MODELS: Set[str] = {"origin_png"}
METADATA_COLS = {"clip_id", "outlier_score", "outlier_threshold", "is_outlier"}


def _filter_to_common_error_clips(df: pd.DataFrame) -> pd.DataFrame:
    metric_cols = [c for c in df.columns if c not in METADATA_COLS]
    if not metric_cols:
        return df

    clip_df = df[df["clip_id"] != "AVERAGE"].copy()
    if "is_outlier" in clip_df.columns:
        clip_df = clip_df[~clip_df["is_outlier"].fillna(False)].copy()
    common_clip_df = clip_df.dropna(subset=metric_cols, how="any").copy()
    if common_clip_df.empty:
        return pd.DataFrame(columns=df.columns)

    avg_row = {"clip_id": "AVERAGE"}
    avg_row.update(common_clip_df[metric_cols].mean(numeric_only=True).to_dict())
    if "outlier_score" in df.columns:
        avg_row["outlier_score"] = common_clip_df["outlier_score"].mean()
    if "outlier_threshold" in df.columns:
        avg_row["outlier_threshold"] = (
            df["outlier_threshold"].dropna().iloc[0]
            if df["outlier_threshold"].notna().any()
            else pd.NA
        )
    if "is_outlier" in df.columns:
        avg_row["is_outlier"] = False
    return pd.concat([pd.DataFrame([avg_row]), common_clip_df], ignore_index=True)


def run_eval(
    root_dir: Path,
    input_root: Path,
    output_csv: Path,
    output_png: Path,
    models: List[str],
    n_points: int = 10,
    trigger_lead_seconds: float = 2.0,
    sort_by: str = "",
    topk: int = 0,
    title: str = "PSNR & FM Error Comparison",
    only_common_clips: bool = False,
    outlier_iqr_multiplier: float = 3.0,
) -> None:
    # 用户指定模型 + 3 个 baseline
    target_models: Set[str] = set(models) | BASELINE_MODELS
    print(f"[INFO] root_dir = {root_dir}")
    print(f"[INFO] 用户传入 models: {models}")
    print(f"[INFO] 实际使用的目标模型（包含 baseline）: {sorted(target_models)}")
    
    # 1) 计算 FM 误差
    clip_errors = collect_model_clip_errors(
        root_dir=root_dir,
        n_points=n_points,
        trigger_lead_seconds=trigger_lead_seconds,
        target_models=target_models,
    )
    if not clip_errors:
        print("[ERROR] 没有从 root_dir 中得到任何误差结果")
        return

    # 2) 输出 CSV
    df = build_dataframe(clip_errors, outlier_iqr_multiplier=outlier_iqr_multiplier)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False)
    clip_count = len(df[df["clip_id"] != "AVERAGE"])
    outlier_count = int(df[df["clip_id"] != "AVERAGE"]["is_outlier"].sum()) if "is_outlier" in df.columns else 0
    print(
        f"[DONE] FM 误差 CSV 已输出: {output_csv}，"
        f"包含 {clip_count} 个 clip，其中异常 clip 标记 {outlier_count} 个"
    )

    # 为画图准备 epoch_models：按用户输入传递，允许“只有 PSNR、没有误差”的模型
    non_base_models = [m for m in models if m not in BASELINE_MODELS]

    # 2) 调用画图脚本
    plot_main(
        csv_path=str(output_csv),
        input_root=str(input_root),
        output_path=str(output_png),
        sort_by=sort_by,
        topk=topk,
        title=title,
        epoch_models=non_base_models if non_base_models else None,
        only_common_clips=only_common_clips,
    )


if __name__ == "__main__":
    # ===== 在这里写死参数 =====
    # 根目录：包含 sim_* 子目录的 eval 目录
    root_dir = Path("/workspace/yangxh7@xiaopeng.com/difix3D_train/eval_new").expanduser().resolve()
    # PSNR 结果目录（包含 compare_inference_*），通常与 root_dir 相同
    input_root = root_dir

    # 输出文件
    output_csv = root_dir / "fm_clip_error_selected.csv"
    output_png = root_dir / "fm_clip_error_selected.png"

    # 只评估这些模型（脚本内部会自动加上 3dgs_alone、origin_png、origin_difix）
    models = [
        '3dgs_3w',
        'difix_1bucket',
    ]

    # 其他参数
    n_points = 10
    trigger_lead_seconds = 2.0
    outlier_iqr_multiplier = 3.0
    sort_by = ""  # 比如 "v1_epoch_0042_step_126000" 或 "psnr_v1_epoch_0042_step_126000"
    topk = 0      # 0 表示画全部 clip
    title = "PSNR & FM Error Comparison"
    only_common_clips = True  # True: PSNR 与 FM 误差分别按各自展示模型求 common clips，并各自基于该集合计算平均

    run_eval(
        root_dir=root_dir,
        input_root=input_root,
        output_csv=output_csv,
        output_png=output_png,
        models=models,
        n_points=n_points,
        trigger_lead_seconds=trigger_lead_seconds,
        sort_by=sort_by,
        topk=topk,
        title=title,
        only_common_clips=only_common_clips,
        outlier_iqr_multiplier=outlier_iqr_multiplier,
    )
