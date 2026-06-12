---
name: fixer-opt
track: SIL
status: active
owner: 周冯
contributors:
  - 瞿鑫宇（HIL侧协同）
since: 2026-04
---

# Fixer+Diffsion优化

## 目标
SIL/HIL Fixer性能优化 + Diffsion新模型探索（O4-KR1）。

## 里程碑历史

### 2026-06-11 — V3/V4效果未达预期
- 周冯重构实验：V3挑部分、V4全跑，效果均未达预期
- V4抑制了PSNR优化，V3+V4早期对输出无影响
- 计划：继续训练更多步数，重跑baseline ref，优化loss向PSNR压

### 2026-06-10 — 三波实验并行
- 第一波：ref编码优化，PSNR退化停训
- 第二波：新架构探索，35K步提升有限
- 第三波：loss设计优化进行中
- Ref图模式核心问题：cross-attention过于尖锐→OOD问题

### 2026-05 — 早期实验
- baseline: difix整卡1:8.8~9.2, MIG 1:17
- 最优实验: EXP_5(非对称分辨率)1:14.8, EXP_6(低层attn)1:15.5

## 风险
- 🔴 训练集群仅够并行2个实验（每个~2天）
- 🔴 9种实验模式无法并行验证
