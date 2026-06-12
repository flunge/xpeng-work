---
name: fixer-opt
track: SIL
status: active
owner: 周冯
contributors:
  - 瞿鑫宇（HIL侧协同）
  - 杨星昊（技术指导）
  - 朱啸峰（台架测试协助）
since: 2026-04
---

# Fixer+Diffsion优化

## 目标
SIL/HIL Fixer性能优化 + Diffsion新模型探索（O4-KR1）。核心指标：效率比从1:8.8→1:3以内。

## 两条线
1. **SIL difix**：PyTorch链路性能优化（探索架构/loss/量化）
2. **HIL nvfixer**：TRT Engine链路，带/不带ref图双版本

## 里程碑历史

### 2026-06-11 — V3/V4未达预期，loss优化中
- 周冯重构实验：V3挑部分/V4全跑，效果均未达预期
- V4抑制PSNR优化，V3+V4早期对输出无影响
- 继续训练更多步数，重跑baseline ref，优化loss向PSNR压

### 2026-06-10 — 三波实验并行，ref图OOD问题
- 第一波：ref编码优化(8000步PSNR退化停训)
- 第二波：新架构探索(35K步提升有限)
- 第三波：loss设计优化进行中
- Ref图核心问题：cross-attention过于尖锐→OOD

### 2026-06-03 — NVFixer TRT/PyTorch对齐
- 确保TRT和PyTorch两条链路效果一致
- 提升对齐标准，时延略有提升
- 考虑进行量化优化

### 2026-06-02 — difix ref图模式优化+IQA评分
- IQA评分：极速vs普通模式均值差异小
- PSNR/SNIP等打分明显分层

### 2026-06-01 — 车身mask方案+Difix流程修改
- 杨星昊修改渲染流程：Difix接受车身mask且无需重训，测试良好
- 闭环TRT链路回归测试今晚合入
- 本周目标：NVFixer TRT链路渲染质量+光影优化

### 2026-05-28 — FM轨迹评测+环境安装
- NVfixer不带ref图baseline跑闭环仿真，FM轨迹评测效果差
- 需带强制跟随自车和trigger time失效逻辑
- nvfixer trt pytorch版本有diff（core ingorder项最大）

### 2026-05-27 — NVFixer效率1:6.7
- 无参考图版本跑gating数据集闭环仿真，批量化耗时~1:6.7
- 修复TRT推理版本和trt engine生成版本不一致bug
- 修复MA Fixer timestamp设置问题

### 2026-05-26 — 36clip测试，每clip~200s
- NVFixer带Ref/不带Ref baseline跑闭环：36clip，每clip~200s
- 与当前产线difix带ref图版本耗时差异不大
- 李坤要求结果以视频文档发群

### 2026-05-25 — seal链路NVFixer+TRT
- 无参考图baseline跑闭环大批量失败（sim engine bug修复）
- NVFixer带ref图转TRT算子问题全部解决
- 提交批量化闭环仿真FM轨迹评测

### 2026-05-21 — difix效率待测
- difix效果没问题，待链路稳定后测试效率
- 李坤建议啸峰协助测试带/不带difix效率
- 周冯重新打镜像，大批量跑仿真闭环

### 2026-05-20 — NVFix 8%优化+代码质检
- NVFix最高优化项可达8%（有显存风险）
- 切换到Seer Difix实验，TRT Engine生成适配
- 郑丽娜要求用cursor修复代码质量静态检查报错

### 2026-05-19 — CUDA优化+切换Seer
- NVFix批量化优化：CUDA DAF/CUDA graph/固定bining/多batch TRT
- 前两项优化有限，第三项需重构
- 杨星昊建议Seer上测试→周冯切换工作路线

### 2026-05-18 — nvfixer持续优化（40ms→34ms）
- 5080上单张camera从40ms降到34ms
- 还有几百个实验待跑

### 2026-05-14 — 性能基线：NA Fixer 160ms, DeFix 300ms
- NA Fixer单帧（含3DGS渲染）~160ms
- 4 Camera GPU~125ms, DeFix单帧~300ms（未降分辨率）

### 2026-05-13 — EXP_5/6优化明显
- 四个链路Defix Gating数据集结果：EXP_5和EXP_6优化明显
- EXP_4更接近原图（可考虑删cross-attention）
- 本周VAE decoder量化/硬发量化实验

### 2026-05-12 — PyTorch→TRT Engine
- 将Defix性能优化从PyTorch链路转到TRT Engine链路
- 重新生成T2T engine，解决5080编包流程
- 提交所有实验仿真任务

### 2026-05-11 — 显存优化实验
- 杨星昊完成显存优化版本实验
- 周冯明天在MEGA上测试提速

### 2026-04-29 — 上海台架自动化编包
- 自动化编包及轨迹PSNR评测基本完成

### 2026-04-22 — MVSA链路+DIFIX 75-76ms
- 周冯搭建MVSA链路批量化测试，单张DIFIX~75-76ms
- 转TRT engine时遇到问题，预计本周完成
- 李坤担心渲染链路branch，建议seal+HIL合并
- 杨星昊：长期预研nvfixer上加参考图功能

### 2026-04-20 — AIFIX启动
- 周冯负责AIFIX整体流程
- 明后天完成环境部署，预计周四-周五出第一版结论
- Nvfixer TRT转换多项失败（VAE Encoder/DiT导出问题）
- 推荐改法A（torch patcher + TRT core_encoder）

## 当前风险
- 🔴 训练集群仅够并行2个实验（~2天/个），9种模式无法并行
- 🔴 缺卡，FF Difix预估需A100 32卡×7天
- 🟡 ref图OOD问题（cross-attention尖锐）待根本解决
