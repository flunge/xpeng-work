---
name: gic-report-repo
description: GIC双周会汇报仓库信息、已有报告链接、生成Agent使用方法
metadata: 
  node_type: memory
  type: reference
  originSessionId: 54cbf7c0-d7cb-4d22-9f59-ab426e073719
---

# GIC双周会汇报仓库

## 仓库信息

- **Wiki URL**：https://xiaopeng.feishu.cn/wiki/HrRhw3QHVioc5MkLCnVc0O90nmA
- **Space ID**：`7369389337118507009`
- **根节点 token**：`HrRhw3QHVioc5MkLCnVc0O90nmA`
- **汇报链**：李坤 → 高炳涛（审核）→ 刘先明（GIC双周会）
- **会议频率**：双周五，材料需周四中午前写好
- **素材统筹**：邓爽统筹部门级报告，各组提供各板块内容

## 已有报告

| 期数 | 标题 | Token | 内容方向 |
|------|------|-------|----------|
| 第1期 | 仿真双周会 20260523 | `EyJGdC6efo6w92xczCPcZle0nTg` | 年度方向、六项重点工作、Q2目标、仿真先行、3DGS、AI Agent |
| 第2期 | 仿真双周会 20260605 | `SlNPdcCt5o4bYYxb7X7cGIe4nGc` | 仿真先行落地、Metric可信度、效率优化、闭环仿真、车型泛化 |

## Agent 使用方法

调用 GIC双周会汇报板块生成 Agent：

```
使用 Workflow 工具，scriptPath 为 pipelines/gic-report.js
```

Agent 自动采集两周数据 → 提炼3个大块 → 在汇报仓库下创建新文档。

**Why:** 每次手动收集两周内的日会纪要、IM消息、Wiki变化等数据耗时且容易遗漏。

**How to apply:** 双周四上午调用生成草稿，先审阅 → 告知我确认后 → 我将板块提供给邓爽汇总到部门级报告中。
