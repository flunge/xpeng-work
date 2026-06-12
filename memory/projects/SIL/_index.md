---
name: track-sil
track: SIL
status: active
since: 2026-03
owner: 郑丽娜（业务Owner）/ 杨星昊（技术Owner）
projects:
  - 车型泛化
  - Fixer优化
  - CLIP-IQA
---

# SIL Track

## Q2 目标演进

| 月份 | 目标 | 实际对齐 |
|------|------|---------|
| **4月** | 闭环问题集+开环泛化+RC路线指标+复现率gating | ✅ gating数据集初版；Fixer基线(1:8.8)；AIFIX启动 |
| **5月** | 复现率70%+/效率1:35；自动化复现率评测+图像映射 | 🟡 车型泛化5阶段验证；复现Agent 4模型评测(5/12)；Fixer EXP_5达1:14.8；ClipIQA 200数据集验证 |
| **6月** | 10+类别场景集；复现率80%+/效率1:25 | 🔴 进行中：车型泛化6/18交付；Fixer 9模式并行未突破；ClipIQA已接入SIL |

## 里程碑时间线

| 时间 | 事件 |
|------|------|
| 4月 | Fixer baseline: difix整卡1:8.8~9.2；Nvfixer TRT转换探索 |
| 5月 | 车型泛化5阶段验证启动；CLIP-IQA开发（3维度5级分级）；Fixer EXP_5达1:14.8 |
| 6/5 | 复现Agent阶段性验证报告 |
| 6/10 | 车型泛化5阶段已过4，结论正向；Fixer 9模式并行探索；CLIP-IQA已接入SIL |
| 6/12 | 车型泛化Camera Mask优化温和改善；Cloudsim 6/18交付 |

## 当前状态 (6/12)

- 🟢 车型泛化5阶段已过4，6/18交付
- 🟡 Fixer实验多线并行但未突破，训练资源受限
- 🟡 CLIP-IQA已接入SIL长里程，Pill链路未接入
