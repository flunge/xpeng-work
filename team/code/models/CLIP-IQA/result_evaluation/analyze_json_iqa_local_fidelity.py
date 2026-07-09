"""
analyze_json_iqa_local_fidelity.py - fidelity-only pipeline with gap filtering
==============================================================================

Only supports fidelity mode (requires ref_* fields in clipiqa_scores.json).
Computes gap statistics (mean, std) per case and filters outliers by threshold.

Stage 1: shard (parallel jobs)
  python result/evaluate/analyze_json_iqa_local_fidelity.py \
      --job_dir /workspace/group_share/.../J11910037 \
      --output_dir /workspace/group_share/.../clipiqa_results_J11910037 \
      --num_shards 7 --shard_idx 0

Stage 2: merge (with gap filtering)
  python result/evaluate/analyze_json_iqa_local_fidelity.py \
      --merge \
      --shard_dir /workspace/group_share/.../clipiqa_results_J11910037 \
      --output_dir result/dds/J11910037 \
      --formula v2_weights \
      --gap_mean_threshold 10.0 \
      --gap_std_threshold 5.0

Gap filtering logic:
  - Computes per-case gap_mean = mean(all gap_*_cam* columns)
  - Computes per-case gap_std = std(all gap_*_cam* columns)
  - Filters out cases where gap_mean > threshold OR gap_std > threshold
"""

import argparse
import os
import re
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
from tqdm import tqdm

# matplotlib / seaborn loaded lazily
_plt = None
_sns = None

def _ensure_plot_libs():
    global _plt, _sns
    if _plt is None:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import seaborn as sns
        _plt = plt
        _sns = sns
    return _plt, _sns

_CASE_RE = re.compile(r'^S\d+-J\d+-T\d+$')

# ──────────────────────────────────────────────
# Fidelity formula (same as analyze_json_iqa.py)
# ──────────────────────────────────────────────
CAM_CFG = {
    "cam0": {"w": 0.28, "m": {"Perfect": 0.60, "Clean": 0.25, "Sharp": 0.15}},
    "cam2": {"w": 0.20, "m": {"Perfect": 0.55, "Clean": 0.30, "Sharp": 0.15}},
    "cam7": {"w": 0.18, "m": {"Sharp":  0.40, "Perfect": 0.40, "Clean": 0.20}},
    "cam3": {"w": 0.13, "m": {"Sharp":  0.50, "Perfect": 0.40, "Clean": 0.10}},
    "cam5": {"w": 0.12, "m": {"Sharp":  0.50, "Perfect": 0.40, "Clean": 0.10}},
    "cam6": {"w": 0.06, "m": {"Sharp":  0.60, "Perfect": 0.25, "Clean": 0.15}},
    "cam4": {"w": 0.03, "m": {"Clean":  0.40, "Perfect": 0.40, "Sharp": 0.20}},
}
ATTRS = ['Sharp', 'Clean', 'Perfect']
REF_ATTRS = ['ref_Sharp', 'ref_Clean', 'ref_Perfect']

_FIDELITY_V2 = {
    cam: {attr: w for attr, w in cfg['m'].items()}
    for cam, cfg in CAM_CFG.items()
}
_FIDELITY_EQUAL = {cam: {'Sharp': 1/3, 'Clean': 1/3, 'Perfect': 1/3} for cam in CAM_CFG}
_FIDELITY_PERFECT_ONLY = {cam: {'Perfect': 1.0} for cam in CAM_CFG}

FORMULA_REGISTRY = {
    'v2_weights':   _FIDELITY_V2,
    'equal':        _FIDELITY_EQUAL,
    'perfect_only': _FIDELITY_PERFECT_ONLY,
}


def read_trigger_time(scenario_path: str) -> int:
    """Read triggerTime = triggerTimestamp - 2e9 from scenario.json. Returns 0 if missing."""
    try:
        d = json.load(open(scenario_path))
        ts = d.get('perfectControllerConfig', {}).get('triggerTimestamp')
        if ts is None:
            return 0
        return int(ts) - 2 * 10 ** 9
    except Exception:
        return 0


def aggregate_case(records: list, trigger_time: int) -> dict:
    """
    Return per-cam median for after-trigger frames (fidelity mode only).

    Computes gap_X_cam = median(max(0, ref_X - sim_X)) per camera.
    Also computes overall gap_mean_X and gap_var_X across all cameras.
    """
    df = pd.DataFrame(records)
    if df.empty:
        return {}
    result = {}
    if trigger_time > 0:
        df_before = df[df['timestamp'] < trigger_time]
        df_after  = df[df['timestamp'] >= trigger_time]
    else:
        df_before = pd.DataFrame()
        df_after  = df

    has_ref = all(r in df.columns for r in REF_ATTRS)
    if not has_ref:
        # fidelity mode requires ref_* fields
        return {}

    # after-trigger median (primary signal)
    if not df_after.empty:
        for cam, grp in df_after.groupby('camera'):
            for attr in ATTRS:
                if attr in grp.columns:
                    result[f'{attr}_{cam}'] = float(grp[attr].median())
            for attr in ATTRS:
                ref_col = f'ref_{attr}'
                if attr in grp.columns and ref_col in grp.columns:
                    gap = (grp[ref_col] - grp[attr]).clip(lower=0)
                    result[f'gap_{attr}_{cam}'] = float(gap.median())

    # Compute overall (all cameras) frame-level gap mean and variance per attribute
    if not df_after.empty:
        for attr in ATTRS:
            ref_col = f'ref_{attr}'
            if attr in df_after.columns and ref_col in df_after.columns:
                gap_all = (df_after[ref_col] - df_after[attr]).clip(lower=0)
                result[f'gap_mean_{attr}'] = float(gap_all.mean())
                result[f'gap_var_{attr}'] = float(gap_all.var())

    # before-trigger mean (baseline)
    result['before_frames'] = len(df_before)
    if not df_before.empty:
        for cam, grp in df_before.groupby('camera'):
            for attr in ATTRS:
                if attr in grp.columns:
                    result[f'{attr}_{cam}_before'] = float(grp[attr].mean())
    return result


def compute_fidelity_score(gap_pivot: pd.DataFrame, formula: dict = None,
                            cam_cfg: dict = None):
    """gap 反转归一化为 fidelity_score（gap 小 → 分高，0–100）。"""
    if formula is None:
        formula = FORMULA_REGISTRY['v2_weights']
    if cam_cfg is None:
        cam_cfg = CAM_CFG
    p10_90 = {}
    for cam in cam_cfg:
        p10_90[cam] = {}
        for attr in ATTRS:
            col = f'gap_{attr}_{cam}'
            if col in gap_pivot.columns:
                p10_90[cam][attr] = (gap_pivot[col].quantile(0.10), gap_pivot[col].quantile(0.90))
    fqscore_cols = {}
    for cam, cfg in cam_cfg.items():
        attr_weights = formula.get(cam, {})
        if not attr_weights:
            continue
        fq = pd.Series(0.0, index=gap_pivot.index)
        total_w = sum(attr_weights.values())
        for attr, w in attr_weights.items():
            col = f'gap_{attr}_{cam}'
            if col not in gap_pivot.columns:
                continue
            p10, p90 = p10_90[cam].get(attr, (0, 1))
            span = p90 - p10 if p90 > p10 else 1.0
            normed_inv = (1.0 - ((gap_pivot[col] - p10) / span)).clip(0, 1) * 100
            fq += (w / total_w) * normed_inv
        fqscore_cols[f'fqscore_{cam}'] = fq
    fqscore_df = pd.DataFrame(fqscore_cols, index=gap_pivot.index)
    total_cam_w = sum(cfg['w'] for cam, cfg in cam_cfg.items() if f'fqscore_{cam}' in fqscore_df.columns)
    fidelity = pd.Series(0.0, index=gap_pivot.index)
    for cam, cfg in cam_cfg.items():
        fcol = f'fqscore_{cam}'
        if fcol in fqscore_df.columns:
            fidelity += cfg['w'] * fqscore_df[fcol]
    if total_cam_w > 0:
        fidelity /= total_cam_w
    return fidelity, fqscore_df


def assign_tiers(quality: pd.Series):
    p15 = quality.quantile(0.15)
    p40 = quality.quantile(0.40)
    p75 = quality.quantile(0.75)
    # Guard against degenerate distributions
    if len(set([p15, p40, p75])) < 3:
        tiers = pd.Series('None', index=quality.index, dtype='object')
        tiers[quality >= p75] = 'Gold'
        tiers[(quality >= p40) & (quality < p75)] = 'Silver'
        tiers[(quality >= p15) & (quality < p40)] = 'Bronze'
        return tiers.astype('category'), p15, p40, p75
    tiers = pd.cut(quality, bins=[-np.inf, p15, p40, p75, np.inf],
                   labels=['None', 'Bronze', 'Silver', 'Gold'])
    return tiers, p15, p40, p75


# ──────────────────────────────────────────────
# Plotting helpers
# ──────────────────────────────────────────────

def plot_gap_distributions(gap_pivot: pd.DataFrame, output_dir: str):
    plt, _ = _ensure_plot_libs()
    cams = sorted(set(c.split('_')[2] for c in gap_pivot.columns if c.startswith('gap_')))
    for attr in ATTRS:
        cols = [f'gap_{attr}_{c}' for c in cams if f'gap_{attr}_{c}' in gap_pivot.columns]
        if not cols:
            continue
        fig, axes = plt.subplots(1, len(cols), figsize=(4 * len(cols), 4), sharey=False)
        if len(cols) == 1:
            axes = [axes]
        for ax, col in zip(axes, cols):
            cam = col.split('_')[2]
            data = gap_pivot[col].dropna()
            ax.hist(data, bins=50, color='darkorange', edgecolor='none', alpha=0.8)
            for q, ls in [(0.25, '--'), (0.50, '-'), (0.75, '--')]:
                v = data.quantile(q)
                ax.axvline(v, color='steelblue' if ls == '-' else 'navy', linestyle=ls,
                           linewidth=1.2, label=f'p{int(q*100)}={v:.1f}')
            ax.set_title(f'gap_{attr} {cam}\nn={len(data)}', fontsize=9)
            ax.set_xlabel('gap=max(0,ref−sim)')
            ax.legend(fontsize=6)
        fig.suptitle(f'Fidelity gap: {attr}', fontsize=11)
        fig.tight_layout()
        fig.savefig(os.path.join(output_dir, f'gap_dist_{attr}.png'), dpi=130, bbox_inches='tight')
        plt.close(fig)


def plot_heatmap_gap(gap_pivot: pd.DataFrame, output_dir: str):
    plt, sns = _ensure_plot_libs()
    cams = sorted(set(c.split('_')[2] for c in gap_pivot.columns if c.startswith('gap_')))
    for agg in ('mean', 'median'):
        data = {}
        for attr in ATTRS:
            row = {}
            for cam in cams:
                col = f'gap_{attr}_{cam}'
                if col in gap_pivot.columns:
                    row[cam] = gap_pivot[col].mean() if agg == 'mean' else gap_pivot[col].median()
            data[f'gap_{attr}'] = row
        hm = pd.DataFrame(data).T
        if hm.empty:
            continue
        fig, ax = plt.subplots(figsize=(max(6, len(cams)), 3))
        sns.heatmap(hm, annot=True, fmt='.1f', cmap='Blues', ax=ax)
        ax.set_title(f'Camera × Attribute Gap {agg} (越小 = sim越接近ref)')
        fig.tight_layout()
        fig.savefig(os.path.join(output_dir, f'heatmap_gap_{agg}.png'), dpi=130, bbox_inches='tight')
        plt.close(fig)


def plot_fidelity_dist(fidelity: pd.Series, tiers, p15, p40, p75, output_dir: str):
    plt, _ = _ensure_plot_libs()
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(fidelity, bins=50, color='seagreen', edgecolor='none', alpha=0.8)
    for v, lbl, color in [(p15, f'p15={p15:.1f}', 'orange'),
                          (p40, f'p40={p40:.1f}', 'gold'),
                          (p75, f'p75={p75:.1f}', 'green')]:
        ax.axvline(v, color=color, linestyle='--', linewidth=1.5, label=lbl)
    tc = tiers.value_counts()
    ax.set_title('fidelity_score distribution\n' +
                 '  '.join(f'{t}:{tc.get(t,0)}' for t in ['Gold', 'Silver', 'Bronze', 'None']))
    ax.set_xlabel('fidelity_score (越高 = sim 越接近 ref)')
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(output_dir, 'fidelity_score_dist.png'), dpi=130, bbox_inches='tight')
    plt.close(fig)


def plot_gap_mean_var_scatter(df: pd.DataFrame, output_dir: str):
    """Scatter plot: X=frame-level gap std, Y=frame-level gap mean, per attribute."""
    plt, _ = _ensure_plot_libs()
    for attr in ATTRS:
        mean_col = f'gap_mean_{attr}'
        var_col = f'gap_var_{attr}'
        if mean_col not in df.columns or var_col not in df.columns:
            continue
        data = df[[var_col, mean_col]].dropna().copy()
        data['_std'] = np.sqrt(data[var_col])
        if data.empty:
            continue
        fig, ax = plt.subplots(figsize=(7, 5))
        ax.scatter(data['_std'], data[mean_col], alpha=0.5, s=20,
                   c='darkorange', edgecolors='none')
        ax.set_xlabel(f'gap_{attr} frame-level std (per case, all cams pooled)')
        ax.set_ylabel(f'gap_{attr} frame-level mean (per case, all cams pooled)')
        ax.set_title(f'Case-level gap analysis: {attr}\n'
                     f'gap = max(0, ref-sim), only penalizes sim<ref frames, n={len(data)} cases')
        if len(data) > 2:
            z = np.polyfit(data['_std'], data[mean_col], 1)
            p = np.poly1d(z)
            x_range = np.linspace(data['_std'].min(), data['_std'].max(), 100)
            ax.plot(x_range, p(x_range), 'r--', linewidth=1.5, label='trend')
            corr = data['_std'].corr(data[mean_col])
            ax.legend(title=f'r={corr:.3f}')
        fig.tight_layout()
        fig.savefig(os.path.join(output_dir, f'gap_mean_std_{attr}.png'),
                    dpi=130, bbox_inches='tight')
        plt.close(fig)


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def run_merge(args):
    """Merge all shard CSVs, compute fidelity_score + filter by gap thresholds."""
    import glob
    shard_files = sorted(glob.glob(os.path.join(args.shard_dir, 'shard_*.csv')))
    if not shard_files:
        raise FileNotFoundError(f'No shard_*.csv found in {args.shard_dir}')
    print(f'Merging {len(shard_files)} shard files...')
    dfs = [pd.read_csv(f, index_col='case_id') for f in shard_files]
    df = pd.concat(dfs)
    df = df[~df.index.duplicated(keep='first')]
    print(f'  Total cases: {len(df)}')

    os.makedirs(args.output_dir, exist_ok=True)
    df.to_csv(os.path.join(args.output_dir, 'shard_merged.csv'))

    # Extract gap columns
    gap_cols = [c for c in df.columns if c.startswith('gap_') and '_cam' in c]
    if not gap_cols:
        raise ValueError('No gap_* columns found in shard CSV. Ensure JSON contains ref_* fields.')

    gap_pivot = df[gap_cols].copy()
    valid_mask = gap_pivot.notna().any(axis=1)
    gap_pivot = gap_pivot[valid_mask]
    print(f'  Cases with valid gap scores: {len(gap_pivot)}')

    # ── Compute per-attribute gap statistics ──
    gap_cols_Perfect = [c for c in gap_cols if 'Perfect' in c]
    gap_cols_Sharp = [c for c in gap_cols if 'Sharp' in c]
    gap_cols_Clean = [c for c in gap_cols if 'Clean' in c]

    gap_pivot['gap_mean_Perfect'] = gap_pivot[gap_cols_Perfect].mean(axis=1) if gap_cols_Perfect else 0
    gap_pivot['gap_std_Perfect'] = gap_pivot[gap_cols_Perfect].std(axis=1) if gap_cols_Perfect else 0
    gap_pivot['gap_mean_Sharp'] = gap_pivot[gap_cols_Sharp].mean(axis=1) if gap_cols_Sharp else 0
    gap_pivot['gap_std_Sharp'] = gap_pivot[gap_cols_Sharp].std(axis=1) if gap_cols_Sharp else 0
    gap_pivot['gap_mean_Clean'] = gap_pivot[gap_cols_Clean].mean(axis=1) if gap_cols_Clean else 0
    gap_pivot['gap_std_Clean'] = gap_pivot[gap_cols_Clean].std(axis=1) if gap_cols_Clean else 0

    # ── Compute weighted gap statistics based on filter_mode ──
    print(f'  Filter mode: {args.filter_mode}')

    if args.filter_mode == 'v2_weights':
        # Experiment 1: Use CAM_CFG metric weights (Perfect/Clean/Sharp per cam)
        # gap_mean_weighted = weighted average of gap means
        # gap_std_weighted = weighted average of gap stds (across cameras, for same case)
        gap_mean_weighted = pd.Series(0.0, index=gap_pivot.index)
        # For std: we need the std across cameras per case, not the mean
        # Use gap_std_Perfect/Sharp/Clean computed earlier, weight them by attr
        attr_weights = {}
        for cam, cfg in CAM_CFG.items():
            for attr, w_met in cfg['m'].items():
                attr_weights[attr] = attr_weights.get(attr, 0.0) + w_met

        total_w = 0.0
        for cam, cfg in CAM_CFG.items():
            for attr, w_met in cfg['m'].items():
                col = f'gap_{attr}_{cam}'
                if col in gap_pivot.columns:
                    gap_mean_weighted += w_met * gap_pivot[col]
                    total_w += w_met
        if total_w > 0:
            gap_mean_weighted /= total_w

        # For gap_std_weighted: use the per-attribute std columns, weighted by attr importance
        total_w_std = sum(attr_weights.values())
        gap_std_weighted = (
            attr_weights.get('Perfect', 0) * gap_pivot['gap_std_Perfect'] +
            attr_weights.get('Sharp', 0) * gap_pivot['gap_std_Sharp'] +
            attr_weights.get('Clean', 0) * gap_pivot['gap_std_Clean']
        )
        if total_w_std > 0:
            gap_std_weighted /= total_w_std

        gap_pivot['gap_mean_weighted'] = gap_mean_weighted
        gap_pivot['gap_std_weighted'] = gap_std_weighted
        print(f'  v2_weights: 使用 CAM_CFG 指标权重')

    elif args.filter_mode == 'equal_cam_v2_metric':
        # Experiment 5: Equal cam global weight (1/7 each), but per-cam metric weights from v2 CAM_CFG
        n_cams = len(CAM_CFG)
        cam_w = 1.0 / n_cams  # equal weight per cam
        gap_mean_weighted = pd.Series(0.0, index=gap_pivot.index)
        # accumulate attr-level weights for std computation
        attr_weights = {}
        total_w = 0.0
        for cam, cfg in CAM_CFG.items():
            for attr, w_met in cfg['m'].items():
                col = f'gap_{attr}_{cam}'
                if col in gap_pivot.columns:
                    combined_w = cam_w * w_met  # equal cam weight × v2 metric weight
                    gap_mean_weighted += combined_w * gap_pivot[col]
                    total_w += combined_w
                    attr_weights[attr] = attr_weights.get(attr, 0.0) + combined_w
        if total_w > 0:
            gap_mean_weighted /= total_w

        total_w_std = sum(attr_weights.values())
        gap_std_weighted = (
            attr_weights.get('Perfect', 0) * gap_pivot['gap_std_Perfect'] +
            attr_weights.get('Sharp', 0) * gap_pivot['gap_std_Sharp'] +
            attr_weights.get('Clean', 0) * gap_pivot['gap_std_Clean']
        )
        if total_w_std > 0:
            gap_std_weighted /= total_w_std

        gap_pivot['gap_mean_weighted'] = gap_mean_weighted
        gap_pivot['gap_std_weighted'] = gap_std_weighted
        print(f'  equal_cam_v2_metric: cam 等权 (1/{n_cams})，指标权重沿用 v2 CAM_CFG')

    elif args.filter_mode == 'v2_full_weights':
        # Experiment 6: Full v2 weights = cam global weight (cfg['w']) × per-cam metric weight (cfg['m'])
        gap_mean_weighted = pd.Series(0.0, index=gap_pivot.index)
        attr_weights = {}
        total_w = 0.0
        for cam, cfg in CAM_CFG.items():
            cam_w = cfg['w']
            for attr, w_met in cfg['m'].items():
                col = f'gap_{attr}_{cam}'
                if col in gap_pivot.columns:
                    combined_w = cam_w * w_met
                    gap_mean_weighted += combined_w * gap_pivot[col]
                    total_w += combined_w
                    attr_weights[attr] = attr_weights.get(attr, 0.0) + combined_w
        if total_w > 0:
            gap_mean_weighted /= total_w

        total_w_std = sum(attr_weights.values())
        gap_std_weighted = (
            attr_weights.get('Perfect', 0) * gap_pivot['gap_std_Perfect'] +
            attr_weights.get('Sharp', 0) * gap_pivot['gap_std_Sharp'] +
            attr_weights.get('Clean', 0) * gap_pivot['gap_std_Clean']
        )
        if total_w_std > 0:
            gap_std_weighted /= total_w_std

        gap_pivot['gap_mean_weighted'] = gap_mean_weighted
        gap_pivot['gap_std_weighted'] = gap_std_weighted
        print(f'  v2_full_weights: cam 全局权重 × v2 指标权重（完整 v2）')

    elif args.filter_mode == 'goodcase_score':
        # Experiment 2: Use goodcase formula (0.4*front_clean + 0.3*all_clean + 0.3*all_perfect)
        # 计算 cam0/cam7 均值
        front_clean_cols = [c for c in gap_cols_Clean if 'cam0' in c or 'cam7' in c]
        gap_mean_front_clean = gap_pivot[front_clean_cols].mean(axis=1) if front_clean_cols else 0
        gap_std_front_clean = gap_pivot[front_clean_cols].std(axis=1) if front_clean_cols else 0

        gap_mean_weighted = (0.4 * gap_mean_front_clean +
                            0.3 * gap_pivot['gap_mean_Clean'] +
                            0.3 * gap_pivot['gap_mean_Perfect'])
        gap_std_weighted = (0.4 * gap_std_front_clean +
                           0.3 * gap_pivot['gap_std_Clean'] +
                           0.3 * gap_pivot['gap_std_Perfect'])
        gap_pivot['gap_mean_weighted'] = gap_mean_weighted
        gap_pivot['gap_std_weighted'] = gap_std_weighted
        print(f'  goodcase_score: 0.4×前视Clean + 0.3×全Clean + 0.3×全Perfect')

    elif args.filter_mode == 'single_attr':
        # Experiment 3: Only use one attribute (Perfect, Sharp, or Clean)
        attr = args.single_attr
        gap_pivot['gap_mean_weighted'] = gap_pivot[f'gap_mean_{attr}']
        gap_pivot['gap_std_weighted'] = gap_pivot[f'gap_std_{attr}']
        print(f'  single_attr: 仅使用 {attr} 指标')

    elif args.filter_mode == 'zscore':
        # Experiment 4: Z-score outlier detection
        # 使用默认加权（0.6*Perfect + 0.4*Sharp）计算 mean
        gap_mean_weighted = 0.6 * gap_pivot['gap_mean_Perfect'] + 0.4 * gap_pivot['gap_mean_Sharp']
        gap_std_weighted = 0.6 * gap_pivot['gap_std_Perfect'] + 0.4 * gap_pivot['gap_std_Sharp']

        # 计算 z-score
        z_mean = (gap_mean_weighted - gap_mean_weighted.mean()) / gap_mean_weighted.std()
        z_std = (gap_std_weighted - gap_std_weighted.mean()) / gap_std_weighted.std()

        gap_pivot['gap_mean_weighted'] = gap_mean_weighted
        gap_pivot['gap_std_weighted'] = gap_std_weighted
        gap_pivot['gap_mean_zscore'] = z_mean
        gap_pivot['gap_std_zscore'] = z_std
        print(f'  zscore: 使用 0.6×Perfect + 0.4×Sharp，计算 z-score')
        print(f'    mean z-score range: [{z_mean.min():.2f}, {z_mean.max():.2f}]')
        print(f'    std z-score range: [{z_std.min():.2f}, {z_std.max():.2f}]')

    else:
        # Default: simple average (original behavior)
        gap_pivot['gap_mean_weighted'] = gap_pivot[gap_cols].mean(axis=1)
        gap_pivot['gap_std_weighted'] = gap_pivot[gap_cols].std(axis=1)
        print(f'  default: 所有指标等权重平均')

    # Also compute overall (for reference)
    gap_pivot['gap_mean_overall'] = gap_pivot[gap_cols].mean(axis=1)
    gap_pivot['gap_std_overall'] = gap_pivot[gap_cols].std(axis=1)

    # ── Filter by thresholds ──
    before_filter = len(gap_pivot)
    gap_pivot_before_filter = gap_pivot.copy()  # Save before filtering for plotting

    if args.filter_mode == 'zscore':
        # Z-score filtering: use z-score thresholds
        if args.gap_mean_threshold is not None:
            # Interpret as z-score threshold (e.g., 2.0 = keep within 2 std)
            mask_mean = gap_pivot['gap_mean_zscore'] <= args.gap_mean_threshold
            gap_pivot = gap_pivot[mask_mean]
            print(f'  After gap_mean z-score filter (<= {args.gap_mean_threshold}): {len(gap_pivot)} cases (removed {before_filter - len(gap_pivot)})')
            before_filter = len(gap_pivot)
        if args.gap_std_threshold is not None:
            mask_std = gap_pivot['gap_std_zscore'] <= args.gap_std_threshold
            gap_pivot = gap_pivot[mask_std]
            print(f'  After gap_std z-score filter (<= {args.gap_std_threshold}): {len(gap_pivot)} cases (removed {before_filter - len(gap_pivot)})')
    else:
        # Regular filtering: use weighted mean/std
        if args.gap_mean_threshold is not None:
            gap_pivot = gap_pivot[gap_pivot['gap_mean_weighted'] <= args.gap_mean_threshold]
            print(f'  After gap_mean_weighted filter (<= {args.gap_mean_threshold}): {len(gap_pivot)} cases (removed {before_filter - len(gap_pivot)})')
            before_filter = len(gap_pivot)
        if args.gap_std_threshold is not None:
            gap_pivot = gap_pivot[gap_pivot['gap_std_weighted'] <= args.gap_std_threshold]
            print(f'  After gap_std_weighted filter (<= {args.gap_std_threshold}): {len(gap_pivot)} cases (removed {before_filter - len(gap_pivot)})')

    if len(gap_pivot) == 0:
        print('[ERROR] No cases remain after filtering. Adjust thresholds or check data.')
        return

# Compute fidelity scores for all cases (including filtered)
    print(f'Computing fidelity scores (formula={args.formula})...')
    formula_def = FORMULA_REGISTRY[args.formula]
    
    # Compute for kept cases
    fidelity, fqscore_df = compute_fidelity_score(gap_pivot[gap_cols], formula=formula_def)
    tiers, p15, p40, p75 = assign_tiers(fidelity)
    
    # Compute for filtered-out cases (mark as 'Filtered')
    filtered_out_index = gap_pivot_before_filter.index.difference(gap_pivot.index)
    if len(filtered_out_index) > 0:
        fidelity_filtered, fqscore_filtered = compute_fidelity_score(
            gap_pivot_before_filter.loc[filtered_out_index, gap_cols], formula=formula_def)
        tiers_filtered = pd.Series(['Filtered'] * len(filtered_out_index), index=filtered_out_index)
    else:
        fidelity_filtered = pd.Series(dtype=float)
        fqscore_filtered = pd.DataFrame()
        tiers_filtered = pd.Series(dtype=str)
    
    # Combine kept + filtered
    fidelity_all = pd.concat([fidelity, fidelity_filtered])
    fqscore_all = pd.concat([fqscore_df, fqscore_filtered])
    tiers_all = pd.concat([pd.Series(tiers, index=gap_pivot.index), tiers_filtered])
    gap_pivot_all = pd.concat([gap_pivot, gap_pivot_before_filter.loc[filtered_out_index]])

    meta_cols = [c for c in ['trigger_time', 'total_frames', 'used_frames', 'before_frames'] if c in df.columns]
    result = df.loc[gap_pivot_all.index, meta_cols].copy()
    result = result.join(gap_pivot_all)
    result = result.join(fqscore_all)
    result['fidelity_score'] = fidelity_all
    result['tier'] = tiers_all
    # Rank: Filtered cases get rank=999999
    result['rank'] = 999999
    kept_mask = result['tier'] != 'Filtered'
    result.loc[kept_mask, 'rank'] = fidelity_all.loc[kept_mask].rank(ascending=False, method='min').astype(int)
    result.sort_values('rank', inplace=True)

    out_ranked = os.path.join(args.output_dir, f'fidelity_{args.formula}_ranked.csv')
    result.to_csv(out_ranked)
    print(f'Saved: {out_ranked}  ({len(result)} cases)')

    for tier in ['Gold', 'Silver', 'Bronze']:
        result[result['tier'] == tier].to_csv(
            os.path.join(args.output_dir, f'fidelity_{args.formula}_{tier.lower()}.csv'))

    # gap summary
    g_rows = []
    for col in gap_cols:
        parts = col.split('_'); attr = parts[1]; cam = parts[2]
        vals = gap_pivot[col].dropna()
        g_rows.append({'camera': cam, 'attribute': f'gap_{attr}', 'n': len(vals),
            'mean': round(vals.mean(), 2), 'p50': round(vals.quantile(0.5), 2),
            'p90': round(vals.quantile(0.9), 2)})
    pd.DataFrame(g_rows).to_csv(
        os.path.join(args.output_dir, f'gap_summary_{args.formula}.csv'), index=False)

    print('Generating fidelity plots...')
    plot_gap_distributions(gap_pivot[gap_cols], args.output_dir)
    plot_heatmap_gap(gap_pivot[gap_cols], args.output_dir)
    plot_fidelity_dist(fidelity, tiers, p15, p40, p75, args.output_dir)
    gap_mv_cols = [c for c in df.columns if c.startswith('gap_mean_') or c.startswith('gap_var_')]
    if gap_mv_cols:
        plot_gap_mean_var_scatter(df.loc[gap_pivot.index], args.output_dir)

    # Plot gap_mean vs gap_std scatter per attribute (Perfect/Sharp/Clean)
    plot_gap_mean_std_per_attr(gap_pivot, args.output_dir)

    # Plot gap_mean vs gap_std scatter (weighted)
    # Plot before/after filtering scatter
    filtered_out_df = gap_pivot_before_filter.loc[gap_pivot_before_filter.index.difference(gap_pivot.index)]
    plot_gap_mean_std_scatter(gap_pivot, args.output_dir, args.filter_mode,
                              gap_pivot_before_filter=gap_pivot_before_filter if (args.gap_mean_threshold or args.gap_std_threshold) else None,
                              filtered_out=filtered_out_df if len(filtered_out_df) > 0 else None)

    print('\n=== Fidelity Tier Distribution ===')
    for t in ['Gold', 'Silver', 'Bronze', 'None']:
        n = (result['tier'] == t).sum()
        print(f'  {t:8s}: {n:5d} ({100*n/len(result):.1f}%)')
    print(f'fidelity thresholds: p15={p15:.2f}, p40={p40:.2f}, p75={p75:.2f}')
    print(f'\nGap statistics (filtered cases):')
    print(f'  gap_mean_weighted: min={result["gap_mean_weighted"].min():.2f}, max={result["gap_mean_weighted"].max():.2f}, median={result["gap_mean_weighted"].median():.2f}')
    print(f'  gap_std_weighted: min={result["gap_std_weighted"].min():.2f}, max={result["gap_std_weighted"].max():.2f}, median={result["gap_std_weighted"].median():.2f}')
    print(f'  gap_mean_overall: min={result["gap_mean_overall"].min():.2f}, max={result["gap_mean_overall"].max():.2f}, median={result["gap_mean_overall"].median():.2f}')
    print(f'  gap_std_overall: min={result["gap_std_overall"].min():.2f}, max={result["gap_std_overall"].max():.2f}, median={result["gap_std_overall"].median():.2f}')
    if 'gap_mean_Perfect' in result.columns:
        print(f'  gap_mean_Perfect: min={result["gap_mean_Perfect"].min():.2f}, max={result["gap_mean_Perfect"].max():.2f}, median={result["gap_mean_Perfect"].median():.2f}')
        print(f'  gap_mean_Sharp: min={result["gap_mean_Sharp"].min():.2f}, max={result["gap_mean_Sharp"].max():.2f}, median={result["gap_mean_Sharp"].median():.2f}')
        print(f'  gap_mean_Clean: min={result["gap_mean_Clean"].min():.2f}, max={result["gap_mean_Clean"].max():.2f}, median={result["gap_mean_Clean"].median():.2f}')
    print(f'Output dir: {args.output_dir}')


def plot_gap_mean_std_scatter(gap_pivot: pd.DataFrame, output_dir: str, filter_mode: str,
                              gap_pivot_before_filter: pd.DataFrame = None,
                              filtered_out: pd.DataFrame = None):
    """Scatter plot: gap_mean_weighted vs gap_std_weighted.
    
    Args:
        gap_pivot: Filtered data (after thresholds applied)
        output_dir: Output directory
        filter_mode: Filter mode name
        gap_pivot_before_filter: Data before filtering (optional, for comparison plot)
        filtered_out: Cases that were filtered out (optional)
    """
    plt, _ = _ensure_plot_libs()
    if 'gap_mean_weighted' not in gap_pivot.columns or 'gap_std_weighted' not in gap_pivot.columns:
        return

    # Plot 1: Before filtering (if provided)
    if gap_pivot_before_filter is not None:
        data_all = gap_pivot_before_filter[['gap_std_weighted', 'gap_mean_weighted']].dropna()
        if not data_all.empty:
            fig, ax = plt.subplots(figsize=(8, 6))
            ax.scatter(data_all['gap_std_weighted'], data_all['gap_mean_weighted'],
                       alpha=0.5, s=20, c='lightgray', edgecolors='none', label='All cases')
            ax.set_xlabel('gap_std_weighted (Std Dev)', fontsize=11)
            ax.set_ylabel('gap_mean_weighted (Mean)', fontsize=11)
            ax.set_title(f'Gap Mean vs Std - BEFORE Filtering\n(filter_mode={filter_mode}, n={len(data_all)} cases)', fontsize=12)
            ax.grid(True, alpha=0.3)

            # Add trend line
            if len(data_all) > 2:
                z = np.polyfit(data_all['gap_std_weighted'], data_all['gap_mean_weighted'], 1)
                p = np.poly1d(z)
                x_range = np.linspace(data_all['gap_std_weighted'].min(), data_all['gap_std_weighted'].max(), 100)
                ax.plot(x_range, p(x_range), 'r--', linewidth=1.5, alpha=0.7)
                corr = data_all['gap_std_weighted'].corr(data_all['gap_mean_weighted'])
                ax.text(0.05, 0.95, f'r={corr:.3f}', transform=ax.transAxes, 
                       fontsize=10, verticalalignment='top',
                       bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
            
            ax.legend(fontsize=9, loc='lower right')
            fig.tight_layout()
            fig.savefig(os.path.join(output_dir, 'gap_mean_std_scatter_before_filter.png'), dpi=130, bbox_inches='tight')
            plt.close(fig)

    # Plot 2: After filtering with filtered-out overlay
    data = gap_pivot[['gap_std_weighted', 'gap_mean_weighted']].dropna()
    if data.empty:
        return

    fig, ax = plt.subplots(figsize=(8, 6))
    
    # Plot filtered-out points first (in background)
    if filtered_out is not None and len(filtered_out) > 0:
        data_filtered = filtered_out[['gap_std_weighted', 'gap_mean_weighted']].dropna()
        if not data_filtered.empty:
            ax.scatter(data_filtered['gap_std_weighted'], data_filtered['gap_mean_weighted'],
                       alpha=0.3, s=20, c='red', edgecolors='none', label=f'Filtered out (n={len(data_filtered)})')
    
    # Plot kept points on top
    ax.scatter(data['gap_std_weighted'], data['gap_mean_weighted'],
               alpha=0.6, s=30, c='steelblue', edgecolors='none', label=f'Kept (n={len(data)})')

    ax.set_xlabel('gap_std_weighted (Std Dev)', fontsize=11)
    ax.set_ylabel('gap_mean_weighted (Mean)', fontsize=11)
    ax.set_title(f'Gap Mean vs Std - AFTER Filtering\n(filter_mode={filter_mode})', fontsize=12)
    ax.grid(True, alpha=0.3)

    # Add trend line for kept data
    if len(data) > 2:
        z = np.polyfit(data['gap_std_weighted'], data['gap_mean_weighted'], 1)
        p = np.poly1d(z)
        x_range = np.linspace(data['gap_std_weighted'].min(), data['gap_std_weighted'].max(), 100)
        ax.plot(x_range, p(x_range), 'darkblue', linewidth=1.5, alpha=0.7, linestyle='--')
        corr = data['gap_std_weighted'].corr(data['gap_mean_weighted'])
        ax.text(0.05, 0.95, f'r={corr:.3f}', transform=ax.transAxes, 
               fontsize=10, verticalalignment='top',
               bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.5))

    ax.legend(fontsize=9, loc='lower right')
    fig.tight_layout()
    fig.savefig(os.path.join(output_dir, 'gap_mean_std_scatter_after_filter.png'), dpi=130, bbox_inches='tight')
    plt.close(fig)


def plot_gap_mean_std_per_attr(gap_pivot: pd.DataFrame, output_dir: str):
    """Scatter plots: gap_mean vs gap_std for each attribute (Perfect/Sharp/Clean)."""
    plt, _ = _ensure_plot_libs()

    attrs_to_plot = []
    for attr in ['Perfect', 'Sharp', 'Clean']:
        mean_col = f'gap_mean_{attr}'
        std_col = f'gap_std_{attr}'
        if mean_col in gap_pivot.columns and std_col in gap_pivot.columns:
            attrs_to_plot.append(attr)

    if not attrs_to_plot:
        return

    # Create subplots
    fig, axes = plt.subplots(1, len(attrs_to_plot), figsize=(6*len(attrs_to_plot), 5))
    if len(attrs_to_plot) == 1:
        axes = [axes]

    colors = {'Perfect': 'darkorange', 'Sharp': 'steelblue', 'Clean': 'forestgreen'}

    for idx, attr in enumerate(attrs_to_plot):
        ax = axes[idx]
        mean_col = f'gap_mean_{attr}'
        std_col = f'gap_std_{attr}'

        data = gap_pivot[[std_col, mean_col]].dropna()
        if data.empty:
            continue

        ax.scatter(data[std_col], data[mean_col],
                   alpha=0.6, s=30, c=colors.get(attr, 'gray'), edgecolors='none')
        ax.set_xlabel(f'gap_std_{attr} (Std Dev)', fontsize=11)
        ax.set_ylabel(f'gap_mean_{attr} (Mean)', fontsize=11)
        ax.set_title(f'{attr}: Mean vs Std (n={len(data)} cases)', fontsize=12)
        ax.grid(True, alpha=0.3)

        # Add trend line
        if len(data) > 2:
            z = np.polyfit(data[std_col], data[mean_col], 1)
            p = np.poly1d(z)
            x_range = np.linspace(data[std_col].min(), data[std_col].max(), 100)
            ax.plot(x_range, p(x_range), 'r--', linewidth=1.5, alpha=0.7, label='trend')
            corr = data[std_col].corr(data[mean_col])
            ax.legend(title=f'r={corr:.3f}', fontsize=9)

    fig.tight_layout()
    fig.savefig(os.path.join(output_dir, 'gap_mean_std_per_attr.png'), dpi=130, bbox_inches='tight')
    plt.close(fig)



def main():
    parser = argparse.ArgumentParser(description='Fidelity-only analysis with gap filtering')
    parser.add_argument('--job_dir', default='',
                        help='Root dir containing S<id>-J<id>-T<id>/ case folders (shard mode)')
    parser.add_argument('--output_dir', default='result/dds/J_local_fidelity',
                        help='Output directory for CSVs and plots')
    parser.add_argument('--no_trigger_filter', action='store_true',
                        help='Skip trigger time filtering (use all records)')
    # Shard mode
    parser.add_argument('--num_shards', type=int, default=1,
                        help='Total number of shards (for parallel jobs)')
    parser.add_argument('--shard_idx', type=int, default=0,
                        help='Shard index (0-based)')
    # Merge mode
    parser.add_argument('--merge', action='store_true',
                        help='Merge shard CSVs and compute fidelity scores')
    parser.add_argument('--shard_dir', default='',
                        help='Directory containing shard_*.csv files (merge mode)')
    parser.add_argument('--formula', default='v2_weights',
                        choices=list(FORMULA_REGISTRY.keys()),
                        help='Fidelity formula (default v2_weights)')
    # Gap filtering thresholds
    parser.add_argument('--gap_mean_threshold', type=float, default=None,
                        help='Filter out cases where gap_mean_weighted > threshold (or z-score > threshold in zscore mode)')
    parser.add_argument('--gap_std_threshold', type=float, default=None,
                        help='Filter out cases where gap_std_weighted > threshold (or z-score > threshold in zscore mode)')
    # Filter mode (NEW: 4 experiments)
    parser.add_argument('--filter_mode', default='default',
                        choices=['default', 'v2_weights', 'equal_cam_v2_metric', 'v2_full_weights', 'goodcase_score', 'single_attr', 'zscore'],
                        help='Gap weighting method for filtering:\n'
                             '  default: simple average of all gap columns\n'
                             '  v2_weights: use CAM_CFG metric weights (Perfect/Clean/Sharp per cam)\n'
                             '  equal_cam_v2_metric: equal cam global weight (1/7), v2 metric weights per cam\n'
                             '  v2_full_weights: cam global weight × v2 metric weights (full v2)\n'
                             '  goodcase_score: 0.4×(cam0+cam7)Clean/2 + 0.3×allClean + 0.3×allPerfect\n'
                             '  single_attr: only use one attribute (specify with --single_attr)\n'
                             '  zscore: Z-score outlier detection (0.6×Perfect + 0.4×Sharp)')
    parser.add_argument('--single_attr', default='Perfect',
                        choices=['Perfect', 'Sharp', 'Clean'],
                        help='Attribute to use when filter_mode=single_attr (default: Perfect)')
    args = parser.parse_args()

    if args.merge:
        run_merge(args)
        return
    if not args.job_dir:
        parser.error('--job_dir is required in shard mode')

    os.makedirs(args.output_dir, exist_ok=True)
    job_root = args.job_dir.rstrip('/')

    # ─── Step 1: scan case folders ───
    print('Scanning case folders...')
    all_names = os.listdir(job_root)
    case_names = sorted(n for n in all_names if _CASE_RE.match(n))
    print(f'  Total matching folders: {len(case_names)}')

    valid_cases = []
    for name in case_names:
        scores_path = os.path.join(job_root, name, 'clipiqa_scores.json')
        scenario_path = os.path.join(job_root, name, 'scenario.json')
        valid_cases.append({
            'case_id': name,
            'scores_path': scores_path,
            'scenario_path': scenario_path,
        })
    # Apply sharding
    if args.num_shards > 1:
        valid_cases = valid_cases[args.shard_idx::args.num_shards]
        print(f'  Shard {args.shard_idx}/{args.num_shards}: processing {len(valid_cases)} cases')
    else:
        print(f'  Cases to process: {len(valid_cases)}')

    # ─── Step 2: aggregate per-case (parallel reads) ───
    def process_case(cm):
        if args.no_trigger_filter:
            trigger_time = 0
        else:
            trigger_time = read_trigger_time(cm['scenario_path'])
        try:
            with open(cm['scores_path']) as f:
                d = json.load(f)
            records = d.get('records', [])
        except (FileNotFoundError, json.JSONDecodeError):
            return None, 0
        except Exception:
            return None, 0
        total = len(records)
        agg = aggregate_case(records, trigger_time)
        if not agg:  # no ref_* fields or no valid data
            return None, 0
        kept = (sum(1 for r in records if r['timestamp'] >= trigger_time)
                if trigger_time > 0 else total)
        before_frames = agg.pop('before_frames', 0)
        row = {'case_id': cm['case_id'], 'trigger_time': trigger_time,
               'total_frames': total, 'used_frames': kept,
               'before_frames': before_frames}
        row.update(agg)
        return row, max(0, total - kept)

    print('Aggregating per-case scores (parallel)...')
    rows = []
    n_filtered = 0
    n_missing = 0
    with ThreadPoolExecutor(max_workers=16) as ex:
        futs = {ex.submit(process_case, cm): cm for cm in valid_cases}
        for fut in tqdm(as_completed(futs), total=len(valid_cases),
                        desc='Processing', ncols=80):
            row, filtered = fut.result()
            if row is None:
                n_missing += 1
            else:
                rows.append(row)
                n_filtered += filtered

    print(f'  Cases with fidelity scores: {len(rows)}, missing/no-ref: {n_missing}')
    print(f'  Frames filtered before triggerTime: {n_filtered:,}')

    df = pd.DataFrame(rows).set_index('case_id')

    # ─── Step 3: save shard CSV ───
    suffix = f'shard_{args.shard_idx}' if args.num_shards > 1 else 'shard_0'
    out_csv = os.path.join(args.output_dir, f'{suffix}.csv')
    df.to_csv(out_csv)
    print(f'Saved shard: {out_csv}  ({len(df)} cases)')
    print('[DONE]')


if __name__ == '__main__':
    main()
