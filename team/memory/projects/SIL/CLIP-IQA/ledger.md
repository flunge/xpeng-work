---
name: clipiqa
track: SIL
status: active
owner: 王禹丁
contributors: []
since: 2026-05-06
last_updated: 2026-06-15
notes_0615: |
  A100+PPU Gisplan镜像打制完成，合入主线（与杨星昊对接AVM鱼眼cam9训练计划）。
  CLIP-IQA主镜像构建好（需手动替换模型），今晚开始代码开发（集成指标review）。
  HIL链路接入CLIP-IQA：与朱啸峰启动前期评估（HIL侧无ref图，讨论IQ评测实现方式）。
  仍需人工适配模型完成计算替换。
sources:
  - memory/projects/SIL/CLIP-IQA.md
  - Q2 Wiki W7–W11
---

# CLIP-IQA — 活文档

> 最后更新：2026-06-15 | 来源：memory/projects/SIL/CLIP-IQA.md + Q2 Wiki W7–W11

## 背景与目标

自动化评测仿真图像质量，替代人工看渲染质量。核心设计：3 维度评估（Sharp/Clean/Perfect）+ 5 级分级（Gold/Silver/Bronze/None/Filtered），通过反义词 prompt 配对策略（Good/Bad → Softmax 归一化）实现评分。

主要用途：过滤 SIL 长里程仿真中渲染质量差的 case，提升仿真与实车对齐率。

## 当前状态（截至 2026-06-15）

- **链路状态**：clip-iqa 仿真链路及测评部分均已合入；使用文档已整理
- **评测指标**：召回率~90%（28/31），精确度~75%；阈值过滤约 5.2% 异常 case
- **已接入**：SIL 长里程评测（W11 确认合入）
- **待完成**：HIL 链路接入；常规模式需精调
- **1000km 验证**：对齐率 61%，使用 clip-iqa 过滤后提升不明显（W10 结论）

## 时间线（按时间倒序）

- **~2026-06-12 (W11)** — clip-iqa 仿真链路及测评部分均已合入；整理使用文档，出使用说明（来源：Q2 Wiki W11）
- **2026-06-11** — 集成推进中；HIL 链路未接入；常规模式需精调；等待王禹丁编包完成后集成上线（来源：CLIP-IQA.md）
- **2026-06-10** — 确认反义词 prompt 配对策略（Good/Bad → Softmax 归一化）；3 维度：Sharp/Clean/Perfect，5 级分级：Gold/Silver/Bronze/None/Filtered；阈值过滤~5.2% 异常，召回率~90%、精确度~75%；已接入 SIL 长里程并合入（来源：CLIP-IQA.md）
- **~2026-06-05 (W10)** — 七千多 case 过滤 300 多个（5.2%）；召回率 90%（28/31），精确度 76%；clip-iqa 代码准备好，待合入 dev_v2；1000km 仿真车实车对齐率 61%，clip-iqa 过滤后提升不明显（来源：Q2 Wiki W10）
- **~2026-05-29 (W9)** — 1000km 长里程仿真结果完毕；双维度阈值实验：位移差相关阈值 + 图像质量阈值，取交集可筛掉约 10% 质量差 case（来源：Q2 Wiki W9）
- **~2026-05-22 (W8)** — stage1 保存得分 json 链路打通；通过 stage2 remerge 方式过滤 case；采用影子模式开发：渲染后对每张图评测，将得分存入 json（来源：Q2 Wiki W8）
- **2026-05-21** — 郑丽娜提出将 HIL 链路与实车链路运行结果进行对比（来源：CLIP-IQA.md）
- **2026-05-20** — 王禹丁用 CLIP-IQA 检测 896 个 case，排除 119 个（~13%）；人工质检：多为仿真车和实车差距大的 case；杨星昊认可：可筛出与实车距离远的 case，先上线边用边调（来源：CLIP-IQA.md）
- **2026-05-19** — 200km RC 路线 seal 平台和实车对比：AI 总体认为模型对实车更优，主要失真点在安全碰撞/不居中/顿挫；李坤要求约业务组讨论报告呈现方式（来源：CLIP-IQA.md）
- **2026-05-18** — 200 个数据集测试：仅 8 个通过所有 CCES metric；该阈值可全部筛选出这 8 个 good case；与平台组讨论抽帧实时测评方案（来源：CLIP-IQA.md）
- **2026-05-14** — 发现 CLIP-IQA 得分与位移差关联性不强；Cam7 和 Cam6 与位移差呈明显负相关（来源：CLIP-IQA.md）
- **2026-05-13** — 长里程和复现率数据集分布有差异，不同相机分布也不同；需单独设定长里程阈值（来源：CLIP-IQA.md）
- **2026-05-12** — 王禹丁打通 job ID→DDS→PNG 整个链路，加入 trigger time 判断；每个 case 评测约 5 分钟（来源：CLIP-IQA.md）
- **2026-05-11** — 完成 CLIP-IQA 镜像环境与 3DGS 镜像合并；批量测试启动；本周目标：打通自动跑评价镜像链路，结合闭环离线数据评测敲定阈值（来源：CLIP-IQA.md）
- **2026-05-06** — **实验启动**：王禹丁开始 CLIP-IQA 实验，判断模型是否适用于新视角自动化质量校验；数据集构建和环境搭建阶段（来源：CLIP-IQA.md）

## CLIP-IQA实验结论

（来源：CLIP-IQA实验文档 HUSiwSNq）

### 实验目标

替代人工抽检，对每批仿真任务进行全量 IQA 评分，识别渲染质量差的 case，提升仿真与实车对齐率。核心设计：反义词 Prompt 配对（Good/Bad → Softmax 归一化），去掉 CLIP 位置编码以支持任意分辨率（选 ResNet 变体）。

### 三维度 Prompt 对

| 属性 | Prompt 对 | 含义 |
|------|----------|------|
| Sharp | 'Sharp photo.' / 'Blurry photo.' | 图像清晰度/运动模糊 |
| Clean | 'Clean photo.' / 'Messy photo.' | 噪声/伪影/渲染异常 |
| Perfect | 'Perfect photo.' / 'Degraded photo.' | 综合视觉质量 |

### 各摄像头得分分布（J131659 复现率数据集，346 cases，case 级中位数）

- cam0/cam7 质量明显优于 cam3/cam4/cam5/cam6
- cam0 Sharp 中位数：7.1；cam2：8.5；cam3：~2.6；cam4：~1.1
- Clean prompt 对天气依赖性高（亮光环境下评分偏高）
- Sharp 与车速相关（速度过快易模糊）

### 关键指标 AUC（长里程数据集 J130408，图片级）

| 预测器 | AUC | 最优阈值 | Recall |
|--------|-----|---------|-------|
| Perfect | 0.586 | ≤29.1 | 85% |
| Sharp+Perfect | 0.586 | — | — |
| Sharp | 0.551 | — | — |
| Sharp+Clean+Perfect | 0.502 | — | — |
| Clean | 0.420 | — | — |

→ Perfect 和 Sharp 是判别力最强的两个指标

### 变道距离实验结论

| 变道距离 | Sharp | Clean | Perfect |
|---------|-------|-------|---------|
| 1m | 23.05 | 51.70 | 48.81 |
| 3m | 24.65 | 51.34 | 47.73 |
### 各摄像头 CLIP-IQA 评分中位数（来源：sheet LqKgMb）

| 摄像头 | Sharp | Clean | Perfect |
|--------|-------|-------|--------|
| cam0 | 18.1 | 73.6 | 44.7 ↑ |
| cam2 | 15.3 | 61.9 | 26.4 |
| cam3 | 3.8 | 44.5 | 16.2 |
| cam4 | 4.8 | 45.6 | 18.3 |
| cam5 | 7.5 | 55.5 | 25.0 |
| cam6 | 7.6 | 52.7 | 26.1 |
| cam7 | 17.6 | 73.8 | 35.6 |

### Prompt 模板对比（来源：sheet YZI5it）

| Prompt 模板 | SROCC |
|------------|-------|
| [text] photo. | **0.695 ✅** |
| A photo of [text]. | 0.116 ❌ |
| There is [text] in the photo. | 0.214 ❌ |

### 反义词配对效果对比（来源：sheet AycXpv/lwq9La）

| 方法 | KonIQ-10k SROCC |
|------|----------------|
| 单 prompt（朴素） | 0.01 |
| 反义词配对 | 0.383 |
| 反义词配对 + 去位置编码 | **0.695** |

### 各摄像头阈值与 AUC（来源：sheet eKlWTy）

| Camera | Sharp 阈值 | AUC | Clean 阈值 | AUC | Perfect 阈值 | AUC |
|--------|----------|-----|----------|-----|------------|-----|
| cam0 | 13.2 | 0.64 ⚠️ | 39.1 | 0.82 ✅ | 44.8 | 0.53 ❌ |
| cam2 | 19.0 | 0.93 ✅ | 39.5 | 0.88 ✅ | 58.6 | 0.88 ✅ |
| cam3 | 14.8 | 0.75 | 37.9 | 0.79 | 59.1 | 0.83 ✅ |
| cam4 | 15.9 | 0.64 ⚠️ | 36.0 | 0.84 ✅ | 42.4 | 0.83 ✅ |
| cam5 | 13.4 | 0.75 | 36.3 | 0.79 | 71.8 | 0.73 |
| cam6 | 20.1 | 0.59 ❌ | 31.4 | 0.74 | 48.3 | 0.79 |
| cam7 | 25.1 | 0.96 ✅ | 44.3 | 0.98 ✅ | 59.7 | 0.88 ✅ |

### Difix 对 CLIP-IQA 分数的影响（来源：sheet rjUMxe）

| 指标 | 趋势 | 支撑数据 |
|------|------|--------|
| Sharp ✅ | Difix 普遍显著高于 3DGS | cam2 Sharp: 11.83→40.11、cam5: 12.85→47.33 |
| Perfect ✅ | Difix 几乎全面高于 3DGS | cam7 Perfect: 53.75→88.39、cam4: 37.34→74.47 |
| Clean ⚠️ 部分正 | 1m 近端提升明显，远端有衰减 | cam0 1m: 31.20→46.10 ✅；cam5 3m: 13.70→33.26 ✅ || 6m | 23.96 | 47.96 | 44.38 |
| 9m | 22.85 | 46.31 | 42.39 |

→ Clean/Perfect 随变道距离增大下降，Sharp 相对稳定；CLIP-IQA 可感知变道引起的渲染质量劣化

### 分级阈值（自适应百分位）

| 等级 | 阈值条件 | 占比 | 说明 |
|------|---------|------|------|
| Gold | ≥ p75 | ~25% | 优质场景，可直接用于训练 |
| Silver | p40 ~ p75 | ~35% | 可用场景 |
| Bronze | p15 ~ p40 | ~25% | 边缘场景，需谨慎使用 |
| None | < p15 | ~15% | 低质场景，建议排除 |
| Filtered | 固定阈值 | ~5% | 不进入 CCES 评测 |

### 0604 验证实验结果（v2_full_weights，std:15 / mean:22 阈值）

- 过滤量：J11918778（379 cases）+ J11918659（355 cases）= 共 734 cases（5.2%）
- **判对召回率：90%**（28/31）
- 判错召回率：63%
- **精确度：75%**

### 位移差与得分关联

- 位移差与 CLIP-IQA 得分**无显著关联**（各摄像头 Pearson r 均不显著）
- 得分可筛选渲染质量好的 case，但**无法可靠识别位移差大的 bad case**
- 1000km 验证：clip-iqa 过滤后对齐率提升不明显（W10 结论），阈值仍需迭代

## CLIP-IQA使用方法

（来源：clip-iqa用法说明 XYd0wkz1）

### 镜像

| 场景 | 镜像标签 |
|------|--------|
| A100 生产 | `fuyao:sim-clipiqa_a100` |
| A100 仿真 | `fuyao:sim-clip-iqa_sim_5` |

仿真前需更新对应 model 的镜像（在 Copy Pytorch Model 窗口中替换 Docker Image）

### 接入方式（影子模式）

1. 渲染 fun 函数中调用 clip-iqa，每帧评分
2. 结果写入 `clipiqa_scores.json`（含 Sharp/Clean/Perfect 及 ref_Sharp/Clean/Perfect）
3. 环境变量 `CLIPIQA_ENABLED=true`（默认开启）

### 测评 Pipeline

**输入**：CCES job_id（stage2）+ E2E job_id binary_id + GPU 卡数（默认 8，需小于 case 数量）

```
1. 双源数据下载（CCES → scenario.json，E2E → clipiqa_scores.json）
2. 质量评分 & 分级（Gap计算 → Case级聚合 → 归一化反转 → 加权）
3. ReMerge + CCES 回归测评
```

**主脚本**：`simworld/models/CLIP-IQA/result_evaluation/analyze_json_iqa_local_fidelity.py`

### 加权公式（v2_full_weights，默认，召回率 ~90%）

| 相机 | 全局权重 | 指标权重 |
|------|---------|--------|
| cam0 前视长焦 | 28% | Perfect:60%, Clean:25%, Sharp:15% |
| cam2 前视广角 | 20% | Perfect:55%, Clean:30%, Sharp:15% |
| cam7 后视 | 18% | Sharp:40%, Perfect:40%, Clean:20% |
| cam3 左前侧 | 13% | Sharp:50%, Perfect:40%, Clean:10% |
| cam5 右后侧 | 12% | Sharp:50%, Perfect:40%, Clean:10% |
| cam6 左后侧 | 6% | Sharp:60%, Perfect:25%, Clean:15% |
| cam4 右前侧 | 3% | Clean:40%, Perfect:40%, Sharp:20% |

### 其他加权公式

- `v2_weights`：与 v2_full_weights 指标权重相同，各相机权重相等
- `goodcase_score`：0.4×(cam0+cam7均值Clean)/2 + 0.3×全cam均值Clean + 0.3×全cam均值Perfect（仅用 Clean+Perfect，与图像质量相关度最高）
- `single_attr`：单指标模式

### 主要参数说明

| 参数 | 说明 | 默认值 |
|------|------|-------|
| CCES_job_id | stage2 job id | 必填 |
| e2e_job_id binary_id | stage1 job 对应 binary | 必填 |
| GPU 卡数 | 分块拉取数据的并行度 | 8（需低于 case 数量） |
| filter_mode | 加权公式选择 | v2_full_weights |

### 使用限制

- HIL 链路尚未接入，常规模式需精调
- 1000km 长里程验证：clip-iqa 过滤后对齐率提升不明显，阈值仍需迭代
- 得分与位移差无直接因果关系，可筛好 case，无法可靠识别 bad case

## 关键技术卡点

1. **阈值设定**：得分与位移差关联性不强，双维度策略（位移差相关阈值 × 图像质量阈值取交集）作为当前方案
2. **1000km 验证**：clip-iqa 过滤后对齐率提升不明显（W10 结论），说明过滤阈值需继续调优
3. **HIL 链路未接入**：常规模式接入待完成

## 风险与阻塞（当前）

- 🟡 HIL 链路未接入，常规模式需精调（W11 遗留）
- 🟡 1000km 长里程验证 clip-iqa 过滤效果有限，阈值仍需迭代

## 关键决策记录

| 时间 | 决策 | 来源 |
|------|------|------|
| 2026-05-20 | 杨星昊认可先上线边用边调 | CLIP-IQA.md |
| ~2026-05-22 (W8) | 采用影子模式：stage1 渲染后保存得分 json，stage2 remerge 过滤 | Q2 Wiki W8 |
| 2026-06-10 | 确认反义词 prompt 配对策略（Good/Bad → Softmax 归一化）为正式方案 | CLIP-IQA.md |
| ~2026-05-29 (W9) | 双维度阈值策略：位移差相关阈值 + 图像质量阈值，取交集 | Q2 Wiki W9 |

## 相关文档

- `memory/projects/SIL/CLIP-IQA.md`（现有项目文件）
