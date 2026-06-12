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

| 月份 | 目标 |
|------|------|
| **4月** | 闭环问题集明确上线范畴；开环泛化100case摸底；RC路线指标结论；复现率gating内部测试集 |
| **5月** | 头部问题场景集+RC路线构建；可靠指标集+闭环结论；自动化复现率评测+图像映射；复现率70%+、效率1:35 |
| **6月** | 10+类别场景集输出评测结论；复现率80%+、效率1:25；稳定支撑发版gating |

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
