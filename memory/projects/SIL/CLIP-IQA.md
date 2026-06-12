---
name: clipiqa
track: SIL
status: active
owner: 王禹丁
since: 2026-05
---

# CLIP-IQA 图像质量评估

## 目标
自动化评测仿真图像质量，替代人工看渲染质量。3维度评估+5级分级筛选。

## 里程碑历史

### 2026-06-11 — 集成推进中
- Pill链路未接入，常规模式需精调
- 等禹丁编包完成后集成上线

### 2026-06-10 — 周报数据
- 反义词prompt配对策略（Good/Bad→Softmax）
- 3维度：Sharp/Clean/Perfect
- 5级分级：Gold/Silver/Bronze/None/Filtered
- 阈值过滤~5.2%异常，召回率~90%、精确度~75%
- 已接入SIL长里程并合入

### 2026-05 — 开发阶段
- 5/15 组织全组人工review CLIP-IQA数据集
- 5/19 同步200km广州RC路线结论
