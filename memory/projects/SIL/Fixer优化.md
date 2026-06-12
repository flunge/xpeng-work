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
- 第一波：ref编码优化(8000步PSNR退化停训)
- 第二波：新架构探索(35K步提升有限)
- 第三波：loss设计优化进行中
- Ref图核心问题：cross-attention过于尖锐→OOD，训练集缺"高对齐+外参小差异"样本

### 2026-05 — SIL difix性能基线
- baseline: difix整卡1:8.8~9.2, MIG 1:17
- EXP_5(非对称分辨率)1:14.8
- EXP_6(低层attn)1:15.5
- HIL侧：v5降分辨率+batch优化→gpu0 193.1ms（baseline 528.7ms）

### 2026-04-29 — 五一前冲刺
- 跨车型106 case CCES任务进行中

### 2026-04-22 — MVSA链路+DIFIX耗时
- 周冯搭建MVSA链路批量化测试，单张DIFIX 75-76ms
- 转TRT engine时遇到问题，预计本周完成
- 计划周五在台架上测试实时运行
- 李坤担心渲染链路branch，建议seal和HIL合并

### 2026-04-20 — Fixer启动
- 周冯负责AIFIX整体流程
- 明后天完成环境和部署，预计周四-周五出第一版结论
- Nvfixer TRT转换多项失败（VAE Encoder、DiT导出问题）
- 推荐改法A（torch patcher + TRT core_encoder）
- fp16前向通过

## 风险
- 🔴 训练集群仅够并行2个实验（每个~2天），9种模式无法并行
- 🔴 缺卡，FF Difix预估需A100 32卡×7天
