# DDS CLIP-IQA Fidelity Pipeline Skill

输入一个 CCES job ID + e2e job ID，完成从数据下载到 Fidelity 评分分析的全流程（仅支持含 ref_* 字段的新版 JSON）。

---

## ⚠️ Agent 必读：执行前必须收集以下信息

**在执行任何步骤之前，Agent 必须先向用户确认以下参数（缺一不可）：**

| 参数 | 说明 | 是否必填 |
|------|------|----------|
| `CCES_job_id` | CCES CI job ID（7-8 位，stage2 job id） | 必填 |
| `e2e_job_id` | CloudSim e2e job ID（5-6 位，stage1 job id） | 必填 |
| `binary_id` | 目标 binary ID（用于 Step 3 remerge 提交，可在 CloudSim 页面查看） | 必填 |
| `num_shards` | adc-sim 集群 GPU 卡数（默认 8），数量多速度快，但必须 ≤ case 数量 | 用户指定或确认默认值 |

> 📌 **Agent 行为规则**：
> 1. 若用户未提供 `binary_id`，**必须立即询问**，不得跳过或延后到 Step 3 才问。
> 2. 若用户未指定 `num_shards`，告知默认值 8 并请用户确认（或根据 `fuyao view` 的 Free GPUs 建议调整）。
> 3. **所有参数确认后才可开始 Step 1**。

---

## 环境配置

### 用户工作目录设置

**重要**：不同用户需要配置自己的工作目录。设置环境变量：

```bash
# 在 ~/.bashrc 或 ~/.zshrc 中添加
export USER_WORKSPACE="/workspace/${USER}@xiaopeng.com"
export USER_SHARED="/workspace/group_share/adc-sim/users/${USER}"
```

或在运行脚本前临时设置：

```bash
export USER_WORKSPACE="/workspace/your_username@xiaopeng.com"
export USER_SHARED="/workspace/group_share/adc-sim/users/your_username"
```

### 项目路径结构

```
${USER_WORKSPACE}/
├── simworld/
│   └── models/
│       └── CLIP-IQA/              # CLIP-IQA 项目根目录
│           └── result_evaluation/  # 本评测流程所在目录
│               ├── dds_clipiqa_fidelity_pipeline.md  # 本文档
│               ├── analyze_json_iqa_local_fidelity.py # 分析脚本
│               ├── download_cases_oss1.py             # 下载脚本
│               └── deploy_cmd/                        # 提交脚本目录
│                   ├── download_dual_source.sh        # 下载提交脚本
│                   └── clip-iqa-local_fidelity_job.sh # Fidelity 提交脚本
└── clip_iqa_result/               # 结果输出目录（与 simworld 同级）
    └── dds/
        ├── J<job_id>_exp1_v2full/
        ├── J<job_id>_exp2_v2weights/
        └── ...
```

---

## 流程总览

```
CCES job_id + e2e job_id
        │
        ▼
Step 1: 提交 fuyao 并行下载（download_dual_source.sh）
        ├─ scenario.json       ← CCES simulation/dds_stores/{sim_task_id}/
        └─ clipiqa_scores.json ← e2e   on_target_pytorch/dds_stores/{e2e_task_id}/
        │  输出: ${USER_SHARED}/jobid_dds/J<cces_job_id>/<case_id>/
        │
        ▼
Step 2: 提交 fidelity-only 分析（clip-iqa-local_fidelity_job.sh）
        ├─ Stage 1: 8 卡并行 shard，计算 gap 统计
        └─ Stage 2: 本地 merge，根据 gap mean/std 阈值过滤异常 case
        │  输出: ${USER_WORKSPACE}/clip_iqa_result/dds/J<cces_job_id>_fidelity/
        │         fidelity_v2_weights_ranked.csv（含 gap_mean_overall、gap_std_overall）
        │
        ▼
Step 3（可选）: 提交 remerge（Gold/Silver/Bronze + CCES 测评）
```

---

## Step 1：提交下载 fuyao job

### 脚本

```
simworld/models/CLIP-IQA/result_evaluation/deploy_cmd/download_dual_source.sh
```

### 用法

```bash
# deploy_cmd 与本文档（dds_clipiqa_fidelity_pipeline.md）同级，无需依赖 USER_WORKSPACE
# 若在本文档目录执行：
cd "$(dirname "$(realpath dds_clipiqa_fidelity_pipeline.md)")/deploy_cmd"
# 或直接使用本文档的绝对路径：
# PIPELINE_MD="/absolute/path/to/dds_clipiqa_fidelity_pipeline.md"
# cd "$(dirname "$PIPELINE_MD")/deploy_cmd"

# 标准：N 分片并行，下载 scenario.json + clipiqa_scores.json
nohup bash download_dual_source.sh <CCES_job_id> <e2e_job_id> [num_shards] [only_files=clipiqa_scores.json] [limit=0] \
    > /tmp/submit_dual_C<CCES_job_id>_E<e2e_job_id>.log 2>&1 &
echo "PID=$!"
```

### 参数说明

| 参数 | 位置 | 默认值 | 说明 |
|------|------|--------|------|
| `CCES_job_id` | $1 | 必填 | 7-8 位 CCES CI job |
| `e2e_job_id` | $2 | 必填 | 5-6 位 CloudSim e2e job |
| `num_shards` | $3 | 8 | fuyao 并行 job 数 |
| `only_files` | $4 | `clipiqa_scores.json` | 从 e2e 下载的文件名 |
| `limit` | $5 | 0（全部） | 每个分片最多处理的 case 数，测试用 |

### 确定并行分片数（num_shards）

提交前先查看可用 GPU 和 case 数量，由用户指定 `num_shards`：

```bash
# 1. 查看 adc-sim partition 可用 GPU
#    输出末尾表格中最后一列 Free GPUs 即可用数量：
#    | fuyao_b1_prod2 | adc-sim | training | 72 | <Free_GPUs> |
fuyao view --site fuyao_b1_prod2 --partition adc-sim

# 2. 统计 case 数量（下载完成后）
ls ${USER_SHARED}/jobid_dds/J<cces_job_id>/ | grep -v 'case_ids\|failed' | wc -l
```

> 📌 **Agent 行为**：解析上述输出后，告知用户：
> - 当前 `Free GPUs = X`，`CASE_COUNT = Y`
> - **建议 `NUM_SHARDS = min(X, Y)`**，且必须满足 `case 数量 ≥ NUM_SHARDS`
> - 请用户确认具体分片数后再提交

### 示例

```bash
# deploy_cmd 与本文档（dds_clipiqa_fidelity_pipeline.md）同级
cd "$(dirname "$(realpath dds_clipiqa_fidelity_pipeline.md)")/deploy_cmd"

# 正式跑（11918778 + 146175，按实际 Free GPU 数决定分片数）
NUM_SHARDS=8   # 替换为用户确认的 min(CASE_COUNT, Free GPUs)
nohup bash download_dual_source.sh 11918778 146175 ${NUM_SHARDS} \
    > /tmp/submit_dual_C11918778_E146175.log 2>&1 &

# 验证提交是否完成（期望输出 = NUM_SHARDS）
sleep 120 && grep "JOB SUBMIT RECEIPT" /tmp/submit_dual_C11918778_E146175.log | wc -l

# 查看最后 NUM_SHARDS 条 job 状态
fuyao history --limit ${NUM_SHARDS} 2>/dev/null | grep -E 'label|status'
# status 含义：
#   JOB_PENDING  → 排队中，等待 GPU 资源
#   JOB_RUNNING  → 运行中
#   JOB_COMPLETE → 已完成，可进行下一步 ✓
#   JOB_FAILED   → 运行异常，请自行查看日志排查原因 ✗
# 全部 JOB_COMPLETE 后再执行下一步
```

### 内部映射机制

脚本使用 `--mapping_by_job_desc`（推荐）：分别拉取两个 job 的全量 task 列表，通过 `scenario_description` 字段做 in-memory 匹配，建立 `CCES scenario_id → e2e task_id` 映射。

> ⚠️ 确保 e2e job 已输出 **ref_Sharp / ref_Clean / ref_Perfect** 字段，否则 fidelity 模式无法工作。

### 输出目录结构

```
${USER_SHARED}/jobid_dds/J<cces_job_id>/
    <case_id>/
        scenario.json          ← CCES 路径
        clipiqa_scores.json    ← e2e 路径（必须含 ref_* 字段）
    case_ids.txt               ← 所有 case_id 列表
    failed_cases.txt           ← 下载失败的 case（若有）
```

---

## Step 2：Fidelity-only 分析（两阶段：并行 shard + 本地 merge）

使用 **`clip-iqa-local_fidelity_job.sh`** 脚本，分两阶段完成：

| 阶段 | 操作 | 耗时估计 |
|------|------|---------|
| **Stage 1**：提交分片 job | 8 卡并行读取 JSON、计算 per-cam gap 中位数 | 视 case 数而定 |
| **Stage 2**：本地合并 | 合并 shard CSV、计算 fidelity_score、根据 gap mean/std 过滤异常值 | 1–2 分钟 |

### 评分模式说明

**Fidelity Score**：基于仿真图像（sim）与参考图（ref，真实录制）的差距评分。

- **gap 计算**：`gap_X_cam = median(max(0, ref_X - sim_X))`（只惩罚 sim < ref 方向）
- **gap_mean_overall**：每个 case 所有 `gap_*_cam*` 列的均值
- **gap_std_overall**：每个 case 所有 `gap_*_cam*` 列的标准差
- **fidelity_score**：gap 越小 → 分数越高（0–100），表示仿真与真实越接近

### Stage 1：提交分片 job

> **确定 num_shards**：
> 1. `fuyao view --site fuyao_b1_prod2 --partition adc-sim` 查看输出末尾表格中 `Free GPUs` 列（最后一列）
> 2. 统计 case 数量：`ls ${USER_SHARED}/jobid_dds/J<job_id>/ | grep -v 'case_ids\|failed' | wc -l`
> 3. 告知用户 `Free GPUs` 和 `CASE_COUNT`，建议 `num_shards = min(CASE_COUNT, Free_GPUs)`，请用户确认后提交

```bash
# deploy_cmd 与本文档（dds_clipiqa_fidelity_pipeline.md）同级
cd "$(dirname "$(realpath dds_clipiqa_fidelity_pipeline.md)")/deploy_cmd"

# 查看 Free GPU 数（Free GPUs 在输出末尾表格最后一列）
fuyao view --site fuyao_b1_prod2 --partition adc-sim

# 基础用法（无过滤，后续 merge 时再决定阈值）
NUM_SHARDS=8   # 替换为用户确认的 min(CASE_COUNT, Free GPUs)
nohup bash clip-iqa-local_fidelity_job.sh J<cces_job_id> ${NUM_SHARDS} \
    > /tmp/submit_fidelity_J<cces_job_id>.log 2>&1 &
echo "PID=$!"

# 或：提交时指定阈值（会在 merge 提示中预填）
nohup bash clip-iqa-local_fidelity_job.sh J<cces_job_id> ${NUM_SHARDS} 20.0 15.0 \
    > /tmp/submit_fidelity_J<cces_job_id>.log 2>&1 &

# 验证提交（期望输出 = NUM_SHARDS）
sleep 60 && grep "JOB SUBMIT RECEIPT" /tmp/submit_fidelity_J<cces_job_id>.log | wc -l

# 查看最后 NUM_SHARDS 条 job 状态（关注 status 字段）
fuyao history --limit ${NUM_SHARDS} 2>/dev/null | grep -E 'label|status'
# status 含义：
#   JOB_PENDING  → 排队中，等待 GPU 资源
#   JOB_RUNNING  → 运行中
#   JOB_COMPLETE → 已完成，可进行下一步 ✓
#   JOB_FAILED   → 运行异常，请自行查看日志排查原因 ✗
# 全部 JOB_COMPLETE 后再执行 Stage 2 merge
```

**参数说明：**

| 位置 | 参数 | 默认值 | 说明 |
|------|------|--------|------|
| $1 | `job_id` | 必填 | CCES job ID（如 J11918778） |
| $2 | `num_shards` | 7 | 并行分片数（推荐 8） |
| $3 | `gap_mean_threshold` | 可选 | gap_mean_overall 过滤阈值（预设值，merge 时可调整） |
| $4 | `gap_std_threshold` | 可选 | gap_std_overall 过滤阈值（预设值，merge 时可调整） |

> 分片 CSV 输出到：`${USER_SHARED}/jobid_dds/J<cces_job_id>_clipiqa_fidelity_shards/shard_*.csv`

### Stage 2：本地合并（Stage 1 全部完成后执行）

**脚本末尾会自动生成 merge 命令**，根据是否提供阈值参数显示不同提示。

#### 核心参数：`--filter_mode`（5 种实验模式）

| 模式 | 加权公式 | 适用场景 | 推荐阈值 |
|------|---------|---------|---------|
| `default` | 所有 gap 列简单平均 | 基线对比 | mean=10, std=5 |
| `v2_weights` | CAM_CFG 指标权重（各 cam 的 Perfect/Clean/Sharp 权重） | 推荐，符合 fidelity_score 逻辑 | mean=8, std=4 |
| `v2_full_weights` | CAM_CFG 全量指标权重（所有 cam 的所有指标权重） | **推荐默认**，完整考虑所有摄像头和指标 | mean=20, std=15 |
| `goodcase_score` | 0.4×(cam0+cam7)Clean/2 + 0.3×allClean + 0.3×allPerfect | 参考 goodcase 评分公式 | mean=10, std=5 |
| `single_attr` | 只使用指定指标（Perfect/Sharp/Clean）的 mean/std | 单指标实验 | mean=8, std=4 |

**所有模式的过滤逻辑**：`gap_mean_weighted > thr_mean` **OR** `gap_std_weighted > thr_std` → 排除

---

#### 实验流程（推荐）

**Step 1：先看分布（不带阈值）**

```bash
# CLIP-IQA 根目录为本文档（result_evaluation/）的上一级
cd "$(dirname "$(dirname "$(realpath dds_clipiqa_fidelity_pipeline.md)")")"

# v2_full_weights 模式，不带阈值
python result_evaluation/analyze_json_iqa_local_fidelity.py \
    --merge \
    --shard_dir ${USER_SHARED}/jobid_dds/J<cces_job_id>_clipiqa_fidelity_shards \
    --output_dir ${USER_WORKSPACE}/clip_iqa_result/dds/J<cces_job_id>_explore \
    --filter_mode v2_full_weights
```

**输出终端会打印：**
```
Filter mode: v2_full_weights
  v2_full_weights: 使用 CAM_CFG 全量指标权重
  Cases with valid gap scores: 5742

Gap statistics (filtered cases):
  gap_mean_weighted: min=1.23, max=7.98, median=4.56
  gap_std_weighted: min=0.45, max=3.99, median=2.12
  gap_mean_Perfect: min=0.89, max=9.12, median=5.01
  gap_mean_Sharp: min=1.45, max=11.23, median=6.78
  gap_mean_Clean: min=2.34, max=8.45, median=5.23
```

**查看可视化**：
- `gap_mean_std_scatter.png`：gap_mean_weighted vs gap_std_weighted 散点图（含趋势线）
- 根据散点图和统计量，确定过滤阈值（建议从 p75 或 p90 开始）

---

**Step 2：运行 4 种实验模式**

#### 实验 1：v2_full_weights（推荐默认）

```bash
python result_evaluation/analyze_json_iqa_local_fidelity.py \
    --merge \
    --shard_dir ${USER_SHARED}/jobid_dds/J<cces_job_id>_clipiqa_fidelity_shards \
    --output_dir ${USER_WORKSPACE}/clip_iqa_result/dds/J<cces_job_id>_exp1_v2full \
    --filter_mode v2_full_weights \
    --gap_mean_threshold 22.0 \
    --gap_std_threshold 15.0
```

**说明**：使用 CAM_CFG 中定义的全量指标权重，完整考虑所有摄像头和所有指标（Perfect/Clean/Sharp）的权重，最全面的评估方式。

---

#### 实验 2：v2_weights（基础权重版本）

```bash
python result_evaluation/analyze_json_iqa_local_fidelity.py \
    --merge \
    --shard_dir ${USER_SHARED}/jobid_dds/J<cces_job_id>_clipiqa_fidelity_shards \
    --output_dir ${USER_WORKSPACE}/clip_iqa_result/dds/J<cces_job_id>_exp2_v2weights \
    --filter_mode v2_weights \
    --gap_mean_threshold 25.0 \
    --gap_std_threshold 15.0
```

**说明**：使用 CAM_CFG 中定义的指标权重（如 cam0 Perfect:60%, Clean:25%, Sharp:15%），与 fidelity_score 计算逻辑一致，相比 v2_full_weights 更简化。

---

#### 实验 3：goodcase_score

```bash
python result_evaluation/analyze_json_iqa_local_fidelity.py \
    --merge \
    --shard_dir ${USER_SHARED}/jobid_dds/J<cces_job_id>_clipiqa_fidelity_shards \
    --output_dir ${USER_WORKSPACE}/clip_iqa_result/dds/J<cces_job_id>_exp3_goodcase \
    --filter_mode goodcase_score \
    --gap_mean_threshold 15.0 \
    --gap_std_threshold 10.0
```

**说明**：参考历史实验中的 goodcase 评分公式（0.4×前视Clean均值 + 0.3×全Clean + 0.3×全Perfect）。

---

#### 实验 4：single_attr（只看 Perfect）

```bash
# Perfect only（推荐，历史实验显示 Perfect 与 dist 相关性最强）
python result_evaluation/analyze_json_iqa_local_fidelity.py \
    --merge \
    --shard_dir ${USER_SHARED}/jobid_dds/J<cces_job_id>_clipiqa_fidelity_shards \
    --output_dir ${USER_WORKSPACE}/clip_iqa_result/dds/J<cces_job_id>_exp4_perfect \
    --filter_mode single_attr \
    --single_attr Perfect \
    --gap_mean_threshold 22.0 \
    --gap_std_threshold 30.0

# 对比：Sharp only（侧视摄像头 Sharp 与 dist 相关性强）
python result_evaluation/analyze_json_iqa_local_fidelity.py \
    --merge \
    --shard_dir ${USER_SHARED}/jobid_dds/J<cces_job_id>_clipiqa_fidelity_shards \
    --output_dir ${USER_WORKSPACE}/clip_iqa_result/dds/J<cces_job_id>_exp4_sharp \
    --filter_mode single_attr \
    --single_attr Sharp \
    --gap_mean_threshold 30.0 \
    --gap_std_threshold 20.0

# 对比：Clean only（历史实验显示 Clean 与 dist 无关，作为负面对照）
python result_evaluation/analyze_json_iqa_local_fidelity.py \
    --merge \
    --shard_dir ${USER_SHARED}/jobid_dds/J<cces_job_id>_clipiqa_fidelity_shards \
    --output_dir ${USER_WORKSPACE}/clip_iqa_result/dds/J<cces_job_id>_exp4_clean \
    --filter_mode single_attr \
    --single_attr Clean \
    --gap_mean_threshold 12.0 \
    --gap_std_threshold 12.0
```

**说明**：只使用单一指标的 mean/std 过滤，用于验证各指标的独立效果。

---

### 实验对比建议

对比不同实验的以下指标：

| 指标 | 说明 |
|------|------|
| 过滤后 case 数量 | 过滤比例是否合理（建议保留 70-90%） |
| Gold/Silver/Bronze 分布 | 分级是否均衡 |
| gap_mean_weighted 中位数 | 过滤后质量是否提升 |
| gap_std_weighted 中位数 | 波动是否降低 |
| `gap_mean_std_scatter.png` | 散点图分布是否合理 |

**推荐实验顺序**：
1. 实验 1（v2_full_weights）→ 默认推荐，完整考虑所有权重
2. 实验 2（v2_weights）→ 简化版本，与 fidelity_score 逻辑一致
3. 实验 4（Perfect only）→ 验证最强指标的效果
4. 实验 3（goodcase_score）→ 参考历史公式

### `--formula` 可选值

| 值 | 说明 |
|----|------|
| `v2_weights`（默认）| 沿用 v2 各摄像头 Perfect/Clean/Sharp 权重 |
| `equal` | 三属性等权重 |
| `perfect_only` | 仅 Perfect gap |

> **自定义公式**：在 `analyze_json_iqa_local_fidelity.py` 的 `FORMULA_REGISTRY` 字典中添加一项，`--formula` 传对应 key 即可。

---

## 输出文件

### 核心输出（位于 `${USER_WORKSPACE}/clip_iqa_result/dds/J<cces_job_id>_exp*_*/`）

| 文件 | 说明 |
|------|------|
| **`fidelity_v2_weights_ranked.csv`** | 全量排名（含 gap_*、gap_mean_weighted、gap_std_weighted、gap_mean_Perfect/Sharp/Clean、gap_std_Perfect/Sharp/Clean、fqscore_*、fidelity_score、tier、rank） |
| `fidelity_v2_weights_{gold,silver,bronze}.csv` | 三级筛选结果 |
| `gap_summary_v2_weights.csv` | 各 cam/指标 gap 百分位统计 |
| `shard_merged.csv` | 原始 shard 合并表（未过滤） |

**新增列（实验模式专用）**：
- `gap_mean_Perfect`, `gap_std_Perfect`（Perfect 指标的 mean/std）
- `gap_mean_Sharp`, `gap_std_Sharp`（Sharp 指标的 mean/std）
- `gap_mean_Clean`, `gap_std_Clean`（Clean 指标的 mean/std）
- `gap_mean_weighted`, `gap_std_weighted`（根据 filter_mode 加权计算）
- `gap_mean_zscore`, `gap_std_zscore`（仅 zscore 模式）
- `gap_mean_overall`, `gap_std_overall`（所有 gap 列简单平均，参考用）

### 可视化图表

| 文件 | 说明 |
|------|------|
| **`gap_mean_std_scatter.png`** | **新增**：gap_mean_weighted vs gap_std_weighted 散点图（含趋势线和相关系数，用于确定阈值） |
| `gap_dist_{Sharp,Clean,Perfect}.png` | gap 分布直方图（橙色，越小越好） |
| `heatmap_gap_{mean,median}.png` | 摄像头 × gap 热图（蓝色，越浅越好） |
| `fidelity_score_dist.png` | fidelity_score 分布图（绿色） |
| `gap_mean_std_{Sharp,Clean,Perfect}.png` | 各指标 gap 均值 vs 标准差散点图（用于识别异常值） |

### 分级阈值（基于各批数据自适应）

| 等级 | 阈值 | 说明 |
|------|------|------|
| Gold | ≥ p75 | 约 25% |
| Silver | p40 ~ p75 | 约 35% |
| Bronze | p15 ~ p40 | 约 25% |
| None | < p15 | 约 15% |

---

## Step 3（可选）：提交 remerge（Gold/Silver/Bronze + CCES 测评）

使用 `remerge_id.py` 提交 Gold/Silver/Bronze case 的 remerge job，并自动触发 CCES 测评。

```bash
BINARY_ID=1734021   # 替换为实际 binary_id
CCES_JOB=11918778

cd ${USER_WORKSPACE}
python CLIP_test/remerge_id.py \
    --binary_id ${BINARY_ID} \
    --job_id ${CCES_JOB} \
    --csv ${USER_WORKSPACE}/clip_iqa_result/dds/J${CCES_JOB}_exp1_v2full/fidelity_v2_weights_ranked.csv \
    --clip_id_col case_id \
    --rerun_cces

# 成功返回：{"result": "success", "data": {"job_id": <remerge_job_id>}}
```

**参数说明：**

| 参数 | 说明 |
|------|------|
| `--binary_id` | 目标 binary（可在 CloudSim 页面查看） |
| `--job_id` | CCES job ID |
| `--csv` | fidelity_v2_weights_ranked.csv 路径（含 case_id 列） |
| `--clip_id_col` | CSV 中 case_id 列名（ranked CSV 用 `case_id`，不是 `clip_id`） |
| `--rerun_cces` | 自动添加 `cces_job_types:[1,2]`，触发 CCES 测评 |

---

## 完整命令（复制即用）

```bash
CCES_JOB=11918778
E2E_JOB=146175

# deploy_cmd 与本文档同级，以本文档绝对路径为基准（无需 USER_WORKSPACE / CLIP_IQA）
DEPLOY_CMD_DIR="$(dirname "$(realpath dds_clipiqa_fidelity_pipeline.md)")/deploy_cmd"
# 若不在本文档目录执行，替换为绝对路径：
# DEPLOY_CMD_DIR="/absolute/path/to/result_evaluation/deploy_cmd"

# ── 确定 NUM_SHARDS ───────────────────────────────────────────
# 1. 查看 Free GPUs（在输出末尾表格最后一列）
fuyao view --site fuyao_b1_prod2 --partition adc-sim
# 示例输出：| fuyao_b1_prod2 | adc-sim | training | <Total GPUs> | <Free_GPUs> |
# 2. 统计 case 数量（下载完成后）
# CASE_COUNT=$(ls ${USER_SHARED}/jobid_dds/J${CCES_JOB}/ | grep -v 'case_ids\|failed' | wc -l)
# echo "case 数量: $CASE_COUNT"
# 3. 告知用户 Free GPUs 和 CASE_COUNT，请用户确认 NUM_SHARDS（建议 = min(CASE_COUNT, Free_GPUs)）
NUM_SHARDS=8   # ← 用户确认后填写

# ── Step 1：提交下载 ──────────────────────────────────────────
cd "$DEPLOY_CMD_DIR"
nohup bash download_dual_source.sh ${CCES_JOB} ${E2E_JOB} ${NUM_SHARDS} \
    > /tmp/submit_dual_C${CCES_JOB}_E${E2E_JOB}.log 2>&1 &

# 验证（等待约 2-4 分钟，期望 = NUM_SHARDS）
sleep 180 && grep "JOB SUBMIT RECEIPT" /tmp/submit_dual_C${CCES_JOB}_E${E2E_JOB}.log | wc -l

# 查看最后 NUM_SHARDS 条 job 状态
fuyao history --limit ${NUM_SHARDS} 2>/dev/null | grep -E 'label|status'
# status 含义：
#   JOB_PENDING  → 排队中，等待 GPU 资源
#   JOB_RUNNING  → 运行中
#   JOB_COMPLETE → 已完成，可进行下一步 ✓
#   JOB_FAILED   → 运行异常，请自行查看日志排查原因 ✗
# 全部 JOB_COMPLETE 后再执行 Step 2

# ── Step 2 (Stage 1)：下载完成后，提交 fidelity 分析 job ────
cd "$DEPLOY_CMD_DIR"
nohup bash clip-iqa-local_fidelity_job.sh J${CCES_JOB} ${NUM_SHARDS} \
    > /tmp/submit_fidelity_J${CCES_JOB}.log 2>&1 &

# 验证（期望 = NUM_SHARDS）
sleep 60 && grep "JOB SUBMIT RECEIPT" /tmp/submit_fidelity_J${CCES_JOB}.log | wc -l

# 查看最后 NUM_SHARDS 条 job 状态
fuyao history --limit ${NUM_SHARDS} 2>/dev/null | grep -E 'label|status'
# status 含义：
#   JOB_PENDING  → 排队中，等待 GPU 资源
#   JOB_RUNNING  → 运行中
#   JOB_COMPLETE → 已完成，可进行下一步 ✓
#   JOB_FAILED   → 运行异常，请自行查看日志排查原因 ✗
# 全部 JOB_COMPLETE 后再执行 Stage 2 merge

# ── Step 2 (Stage 2)：所有分片 job 完成后本地合并 ────────────
# CLIP-IQA 根目录为本文档上一级（result_evaluation/ 的父目录）
CLIP_IQA_DIR="$(dirname "$(dirname "$(realpath dds_clipiqa_fidelity_pipeline.md)")")"
cd "$CLIP_IQA_DIR"

# Step 2a: 先看分布（不带阈值）
python result_evaluation/analyze_json_iqa_local_fidelity.py \
    --merge \
    --shard_dir ${USER_SHARED}/jobid_dds/J${CCES_JOB}_clipiqa_fidelity_shards \
    --output_dir ${USER_WORKSPACE}/clip_iqa_result/dds/J${CCES_JOB}_explore \
    --filter_mode v2_full_weights

# 查看 gap_mean_std_scatter.png 和终端统计，确定阈值

# Step 2b: 运行 4 个实验（根据分布调整阈值）

# 实验 1：v2_full_weights（推荐默认）
python result_evaluation/analyze_json_iqa_local_fidelity.py \
    --merge \
    --shard_dir ${USER_SHARED}/jobid_dds/J${CCES_JOB}_clipiqa_fidelity_shards \
    --output_dir ${USER_WORKSPACE}/clip_iqa_result/dds/J${CCES_JOB}_exp1_v2full \
    --filter_mode v2_full_weights \
    --gap_mean_threshold 22.0 \
    --gap_std_threshold 15.0

# 实验 2：v2_weights
python result_evaluation/analyze_json_iqa_local_fidelity.py \
    --merge \
    --shard_dir ${USER_SHARED}/jobid_dds/J${CCES_JOB}_clipiqa_fidelity_shards \
    --output_dir ${USER_WORKSPACE}/clip_iqa_result/dds/J${CCES_JOB}_exp2_v2weights \
    --filter_mode v2_weights \
    --gap_mean_threshold 25.0 \
    --gap_std_threshold 15.0

# 实验 3：goodcase_score
python result_evaluation/analyze_json_iqa_local_fidelity.py \
    --merge \
    --shard_dir ${USER_SHARED}/jobid_dds/J${CCES_JOB}_clipiqa_fidelity_shards \
    --output_dir ${USER_WORKSPACE}/clip_iqa_result/dds/J${CCES_JOB}_exp3_goodcase \
    --filter_mode goodcase_score \
    --gap_mean_threshold 15.0 \
    --gap_std_threshold 10.0

# 实验 4：single_attr (Perfect only)
python result_evaluation/analyze_json_iqa_local_fidelity.py \
    --merge \
    --shard_dir ${USER_SHARED}/jobid_dds/J${CCES_JOB}_clipiqa_fidelity_shards \
    --output_dir ${USER_WORKSPACE}/clip_iqa_result/dds/J${CCES_JOB}_exp4_perfect \
    --filter_mode single_attr \
    --single_attr Perfect \
    --gap_mean_threshold 35.0 \
    --gap_std_threshold 24.0

# ── Step 3：提交 remerge（选择实验效果最好的输出）────
BINARY_ID=1734021   # 替换为实际 binary_id
cd ${USER_WORKSPACE}

# 使用实验 1 的结果（根据实际情况选择）
python CLIP_test/remerge_id.py \
    --binary_id ${BINARY_ID} \
    --job_id ${CCES_JOB} \
    --csv ${USER_WORKSPACE}/clip_iqa_result/dds/J${CCES_JOB}_exp1_v2full/fidelity_v2_weights_ranked.csv \
    --clip_id_col case_id \
    --rerun_cces
```

---

## 常见问题

| 现象 | 原因 | 解决 |
|------|------|------|
| merge 提示 `No gap_* columns found` | JSON 无 ref_* 字段 | 确认 e2e job 已输出 ref_Sharp/ref_Clean/ref_Perfect |
| 大量 case 的 gap 列为 NaN | JSON records 为空或 ref_* 全为 null | 检查 e2e job 日志，确认 IQA 打分正常 |
| `No cases remain after filtering` | 阈值设置过严 | 调高阈值或先不带阈值运行查看分布 |
| fuyao 提交脚本被 Ctrl+C 中断 | AI Agent 超时 | 始终用 `nohup ... &` 后台运行 |
| `shard_merged.csv` 行数 < case 目录数 | 部分 case 缺少 `clipiqa_scores.json` 或无 ref_* | 检查 `failed_cases.txt`，补下载 |
| 过滤后 Gold/Silver/Bronze 比例失衡 | 过滤改变了分布形态 | 阈值过滤 **先于** 分级，分级基于过滤后的分布 |

---

## 关键路径速查

| 用途 | 路径 |
|------|------|
| 下载提交脚本 | `simworld/models/CLIP-IQA/result_evaluation/deploy_cmd/download_dual_source.sh` |
| 下载主脚本 | `simworld/models/CLIP-IQA/result_evaluation/download_cases_oss1.py` |
| **Fidelity 提交脚本（推荐）** | `simworld/models/CLIP-IQA/result_evaluation/deploy_cmd/clip-iqa-local_fidelity_job.sh` |
| **Fidelity 分析脚本** | `simworld/models/CLIP-IQA/result_evaluation/analyze_json_iqa_local_fidelity.py` |
| 下载输出根目录 | `${USER_SHARED}/jobid_dds/` |
| Fidelity 分析结果根目录 | `${USER_WORKSPACE}/clip_iqa_result/dds/` |
| **remerge 提交脚本** | `CLIP_test/remerge_id.py` |

---

## 与原 Pipeline 的区别

| 项目 | 原 Pipeline (dds_clipiqa_pipeline.md) | Fidelity Pipeline（本文档） |
|------|----------------------------------------|------------------------------|
| **适用场景** | 旧版 JSON（仅 Sharp/Clean/Perfect） | 新版 JSON（含 ref_* 字段） |
| **评分依据** | sim 侧指标绝对值（v2 quality） | sim 与 ref 的差距（fidelity） |
| **核心指标** | quality_score（基于 cam 权重归一化） | fidelity_score（gap 反转归一化） + gap_mean_overall / gap_std_overall |
| **异常值过滤** | 无 | 支持 gap mean/std 阈值过滤 |
| **提交脚本** | `clip-iqa-local_job.sh` | `clip-iqa-local_fidelity_job.sh` |
| **分析脚本** | `analyze_json_iqa_local.py --fidelity` | `analyze_json_iqa_local_fidelity.py` |
| **输出目录后缀** | `J<job_id>` | `J<job_id>_fidelity` |

---

## 版本记录

| 日期 | 变更 |
|------|------|
| 2026-06-03 | 初版：基于 `dds_clipiqa_pipeline.md` 创建 fidelity-only 专用流程，新增 gap 统计过滤功能 |
| 2026-06-03 | v2：新增 4 种实验模式（v2_weights / goodcase_score / single_attr / v2_full_weights），支持不同 gap 加权策略 |
| 2026-06-08 | v3：移除 zscore 异常检测模式，新增 v2_full_weights 作为默认推荐模式 |
| 2026-06-08 | v4：重组文件结构至 `simworld/models/CLIP-IQA/result_evaluation/`，支持多用户配置（通过环境变量 `USER_WORKSPACE` 和 `USER_SHARED`），结果输出改为 `clip_iqa_result/` 目录 |
| 2026-06-08 | v5：1) `cd deploy_cmd` 改为以本文档所在目录为基准，不再依赖 `USER_WORKSPACE`；2) 提交前增加 `fuyao view` 查看 Free GPU（末尾表格最后列），agent 应解析 `Free GPUs` 值告知用户，由用户确认 `NUM_SHARDS = min(CASE_COUNT, Free_GPUs)`；3) 提交后增加 `fuyao history --limit <num_shards>` 检查 job status，并注明各状态含义：`JOB_COMPLETE` 可进下一步，`JOB_FAILED` 提醒用户自行查看日志 |
