---
name: fixer-opt
track: SIL
status: active
owner: 周冯
contributors:
  - 瞿鑫宇（HIL侧协同）
  - 杨星昊（技术指导）
  - 朱啸峰（台架测试协助）
since: 2026-04-20
last_updated: 2026-06-15
notes_0615: |
  含NVfixer新仿真镜像（冠秋新打）测试OK，可跑通。
  大批量测试已训80K，效果优于Difix当前最优版本；推理耗时也低于Difix带ref图版本（具体比值待推理链路打通后测）。训练未完全收敛，预计80-90K是最优。
  NVfixer最优版本带ref图模型合入：PyTorch链路完成，TRT需重新生成engine（已在5080虚拟机编包）。
  今晚提交原文渲染批量gating测试（FM轨迹评测质检）。
  新视角幻觉问题：杨星昊提出Difix新视角有幻觉，周冯将查NVfixer最优版本是否缓解并制定优化计划。
sources:
  - memory/projects/SIL/Fixer优化.md
  - Q2 Wiki W7–W11
  - 逐字稿 6/12 组内周会 (XhawdZLWBoZawhxypnncy7dJnLg)
  - 逐字稿 6/5 组内周会 (PuXtdJDtTom01qxEUb9cRFyLnFe)
---

# Fixer优化 — 活文档

> 最后更新：2026-06-15 | 来源：memory/projects/SIL/Fixer优化.md + Q2 Wiki W7–W11

## 背景与目标

SIL/HIL Fixer 性能优化 + Diffusion 新模型探索（O4-KR1）。核心效率指标：效率比从 1:8.8 → 1:3 以内。

两条并行线：
1. **SIL difix**：PyTorch 链路性能优化（探索架构 / loss / 量化）
2. **HIL nvfixer**：TRT Engine 链路，带/不带 ref 图双版本

## 当前状态（截至 2026-06-13）

- **nvfixer 新架构快速实验**：V3C（DIT global self-attention 拼接 ref+render latent）和 V3D（VAE decoder 后注入）两种架构均在 6 clip 50K步实验中 PSNR 提升明显（V3C +8dB, V3D +6dB vs baseline）；V3C+V3D 合并实验本周提交；周末预计启动 64 卡全量大批量训练
- **当前最优 PSNR**（test set）：31（周冯）
- **评测基准**：6 clip 数据集（重选，按时间多样性+版本号多样性）
- **耗时**：未正式测，周冯待测（预期仍低于 difix，因无 decoder 逐层注入）
- **下周目标**：合并 V3C+V3D → 全量 64 卡训练 → FM 轨迹评测

## 时间线（按时间倒序）

- **2026-06-12 (W11 周五)**：V3C+V3D 两种新架构快速实验结果优异（来源：逐字稿 6/12 组内周会）
  - V3C（DIT全局 self-attention 拼接 ref+render latent）：+8dB PSNR vs baseline
  - V3D（VAE decoder 后注入 ref）：+6dB PSNR vs baseline  
  - 视觉上更清晰，LPIPS 也有明显提升（vs V3N0Anchor baseline）
  - 两个架构合并实验今天提交；若 OK 则周末发起 64 卡全量训练
  - 下周做变化仿真 FM 轨迹评测
  - **当前 test set 最高 PSNR：31**

- **~2026-06-05 (W10)** — nvfixer ref 图新架构实验有明显质量提升，周末启动 64 卡大批量训练（来源：Q2 Wiki W11）
- **2026-06-11** — 周冯重构实验：V3 挑部分/V4 全跑，效果均未达预期；V4 抑制 PSNR 优化；继续优化 loss 向 PSNR 压（来源：Fixer优化.md）
- **2026-06-10** — 三波实验并行：①ref 编码优化（8000步 PSNR 退化停训）②新架构探索（35K步提升有限）③loss 设计优化进行中；ref 图 OOD 根因：cross-attention 过于尖锐（来源：Fixer优化.md）
- **2026-06-03** — NVFixer TRT/PyTorch 对齐，确保两条链路效果一致；提升对齐标准，时延略有提升；考虑量化优化（来源：Fixer优化.md）
- **2026-06-02** — difix ref 图模式优化：极速与普通模式均值差异小；PSNR/SNIP 等打分明显分层（来源：Fixer优化.md）
- **2026-06-01** — 杨星昊修改渲染流程：Difix 接受车身 mask 且无需重训，测试良好；本周目标：NVFixer TRT 链路渲染质量+光影优化（来源：Fixer优化.md）
- **~2026-06-05 (W10)** — 重训基础版本 nvfixer（小鹏数据 22 个 epoch）；TRT-PyTorch 对齐标准从 PSNR 升级为所有模块 MAE；已提交 nvfixer_ref pytorch & trt 两版本 gating 数据集仿真（来源：Q2 Wiki W10）
- **2026-05-28** — NVfixer 不带 ref 图 baseline 跑闭环仿真，FM 轨迹评测效果差；需带强制跟随自车和 trigger time 失效逻辑（来源：Fixer优化.md）
- **~2026-05-29 (W9)** — nvfixer noref 耗时优化到 1:5.8，轨迹评测效果不佳，确认需重训带 ref 版本；TRT 和 PyTorch 版本 diff 最大在 core encoder（来源：Q2 Wiki W9）
- **2026-05-27** — NVFixer 无参考图版本批量化耗时~1:6.7；修复 TRT 推理版本和 engine 生成版本不一致 bug（来源：Fixer优化.md）
- **2026-05-26** — NVFixer 带/不带 Ref baseline 跑闭环：36 clip，每 clip~200s；李坤要求结果以视频文档发群（来源：Fixer优化.md）
- **2026-05-25** — 无参考图 baseline 大批量失败（sim engine bug 修复）；NVFixer 带 ref 图转 TRT 算子问题全部解决（来源：Fixer优化.md）
- **2026-05-21** — difix 效果没问题，待链路稳定后测试效率；李坤建议朱啸峰协助测试带/不带 difix 效率（来源：Fixer优化.md）
- **2026-05-20** — NVFix 最高优化项可达 8%（有显存风险）；切换到 Seer Difix 实验，TRT Engine 生成适配（来源：Fixer优化.md）
- **2026-05-19** — NVFix 批量化优化：CUDA DAF/CUDA graph/固定 bining/多 batch TRT，前两项有限，第三项需重构；杨星昊建议 Seer 上测试→周冯切换工作路线（来源：Fixer优化.md）
- **2026-05-18** — 5080 上单张 camera 从 40ms 降到 34ms（来源：Fixer优化.md）
- **2026-05-14** — 性能基线确定：NA Fixer 单帧（含 3DGS 渲染）~160ms；4 Camera GPU~125ms；DeFix 单帧~300ms（未降分辨率）（来源：Fixer优化.md）
- **2026-05-13** — EXP_5/EXP_6 优化明显；EXP_4 更接近原图（可考虑删 cross-attention）；本周 VAE decoder 量化实验（来源：Fixer优化.md）
- **2026-05-12** — 将 Defix 性能优化从 PyTorch 链路转到 TRT Engine 链路；重新生成 T2T engine（来源：Fixer优化.md）
- **2026-05-11** — 杨星昊完成显存优化版本实验；周冯明天在 MEGA 上测试提速（来源：Fixer优化.md）
- **2026-04-29** — 上海台架自动化编包及轨迹 PSNR 评测基本完成（来源：Fixer优化.md）
- **2026-04-22** — 周冯搭建 MVSA 链路批量化测试，单张 DIFIX~75-76ms；李坤担心渲染链路 branch，建议 seal+HIL 合并；杨星昊：长期预研 nvfixer 上加参考图功能（来源：Fixer优化.md）
- **2026-04-20** — **项目启动**：周冯负责 AIFIX 整体流程；Nvfixer TRT 转换多项失败（VAE Encoder/DiT 导出问题）（来源：Fixer优化.md）

## Fixer性能优化实验数据

（来源：SIL_HIL_fixer性能优化实验 STxrwJBK）

### SIL difix 模块耗时 Breakdown（整卡 Baseline）

| 模块 | 占比 | 平均耗时 |
|------|------|--------|
| VAE Decoder | 44.66% | 0.156s |
| VAE Encoder | 34.61% | 0.121s |
| UNet | 20.73% | 0.073s |

→ VAE Decoder 是最大耗时瓶颈

### SIL difix 整卡 Baseline 性能（100 cases）

| 实验 | 平均耗时/clip | 效率 | 可用显存(GB) |
|------|--------------|------|-----------|
| 3dgs_3w（无difix） | 45.95s | 1:1.5 | 46.18 |
| difix_2bucket | 277.61s | 1:9.2 | 34.14 |
| difix_1bucket | 264.24s | 1:8.8 | 40.42 |
| difix_1bucket（MIG） | 510.31s | 1:17 | 3.42 |

### SIL difix 优化实验（MIG 模式，0513，100 cases）

| 实验 | 方案 | 耗时/clip | 效率 | 备注 |
|------|------|----------|------|------|
| Baseline | difix_1bucket | 510.31s | 1:17 | — |
| EXP_1 | radius clip | 495.62s | 1:16.5 | 渲染侧 |
| EXP_2 | 天空降分辨率 | 505.85s | 1:16.9 | 渲染侧 |
| EXP_3 | ref分支复用 | 503.00s | 1:16.8 | UNet优化 |
| EXP_4 | 取消cross-attn | 524.36s | 1:17.5 | 反向效果 |
| **EXP_5** | **非对称分辨率（需重训）** | **442.70s** | **1:14.8** | **当前最优** |
| **EXP_6** | **低分辨率层attn（需重训）** | **465.03s** | **1:15.5** | 次优 |

### HIL difix 各版本性能（20 clips）

| 版本 | 描述 | Difix gpu0/gpu1 | 总帧 gpu0/gpu1 |
|------|------|----------------|----------------|
| v0 | 纯渲染 nodifix | — | 31.1ms / 42.9ms |
| v2（baseline） | TRT nobatch + ref | 123.3ms / 125.2ms | 528.7ms / 424.4ms |
| v3 | TRT nobatch + noref | 81.4ms / 82.2ms | 359.1ms / 293.9ms |
| v4 | TRT batch + noref | 92.9ms / 82.1ms | 417.0ms / 289.3ms（显存炸） |
| **v5** | **降分辨率 + 动态算子融合** | **40.7ms / 43.4ms** | **193.1ms / 172.4ms** |

→ v5 vs v2 baseline：difix 耗时下降 ~67%，总帧耗时下降 ~63%

### HIL Batch 推理增益（cam027，nobatch → batch）

| 模块 | nobatch | batch | 变化 |
|------|---------|-------|----- |
| Encoder | 53.7ms | 53.5ms | 无变化 |
| UNet | 52.6ms | 43.1ms | ↓18% |
| Decoder | 115.2ms | 116.3ms | 无变化 |
| Total | 223ms | 213ms | ↓4.5% |

→ Batch 主要增益在 UNet，VAE 无收益

### 关键结论

- SIL 当前最优：EXP_5（效率 1:14.8），需重训
- HIL 当前最优：v5（分辨率降至 768×432 & 640×512 + 动态算子融合，效率约 1:5.7）
- HIL NVFixer TRT 转换难点：VAE Encoder（torch.export 符号形状限制 + ScriptModule 问题）、DiT（dynamo 失败）；推荐改法A（PyTorch patcher + TRT core_encoder 拆分）

## Gating数据集统计

（来源：闭环Gating数据集综合统计 JRmhwSrQ）

### 数据集规模

- 总样本：**376** 例；无效 **56** 例（14.89%）；有效 **320** 例（85.11%）

### MC 未复现归因（73例，占有效样本 22.81%）

| 归因 | 数量 | 占MC未复现 | 占有效样本 |
|------|------|-----------|----------|
| 提示词问题（prompt 不对齐） | 44 | 60.27% | 13.75% |
| 图像问题（PC 未复现） | 14 | 19.18% | 4.38% |
| 控制问题（原图未复现） | 12 | 16.44% | 3.75% |
| MC 流程问题 | 3 | 4.11% | 0.94% |

### 人 vs AI 一致性

| 阶段 | 样本数 | 一致率 |
|------|--------|-------|
| MC | 266 | 81.58% |
| PC | 41 | 82.93% |
| PNG | 41 | 87.80% |
| **合计** | **348** | **82.47%** |

### 按问题类型一致率（代表性类别，子类汇总）

| 类别 | 样本数 | 一致率 |
|------|--------|-------|
| 压线 | 29 | 96.55% |
| 红绿灯相关 | 25 | 92% |
| 撞路沿/障碍物 | 10 | 90% |
| 加减速顿挫 | 42 | 83.33% |
| 摆动/蛇形 | 89 | 86.51% |
| 不加速/加速慢 | 84 | 71.42% |
| 不减速/制动不足 | 44 | 72.72% |

### 费用估算

- 模型：Doubao-Seed-2.0-pro（复现分析）+ DeepSeek-V4-pro（FM prompt 分析）
- 每 300 case 约 65 元（Doubao 每次调用 ~0.02元，DeepSeek 每次调用 ~0.045元）

## 关键技术卡点

1. **ref 图 OOD 问题**：cross-attention 过于尖锐，导致 ref 图分布外泛化差
2. **TRT/PyTorch diff**：core encoder 差异最大，持续对齐中
3. **nvfixer noref 轨迹评测差**：确认需重训带 ref 版本才能达到可用效果
4. **训练资源瓶颈**：集群仅够并行 2 个实验（~2天/个），9 种模式无法并行

## 风险与阻塞（当前）

- 🔴 训练集群仅够并行 2 个实验，9 种模式无法并行
- 🔴 缺卡，FF Difix 预估需 A100 32 卡×7 天
- 🟡 ref 图 OOD 问题（cross-attention 尖锐）待根本解决
- 🟡 TRT engine onnx/trt 转换方案复杂，自动化/上手成本高，需重构

## 关键决策记录

| 时间 | 决策 | 来源 |
|------|------|------|
| 2026-05-19 | 杨星昊建议切换到 Seer 上测试；周冯切换工作路线 | Fixer优化.md |
| ~2026-05-29 | noref 轨迹评测效果差 → 确认必须重训带 ref 版本 | Q2 Wiki W9 |
| ~2026-06-05 (W10) | TRT-PyTorch 对齐标准从 PSNR 升级为所有模块 MAE | Q2 Wiki W10 |
| 2026-04-22 | 李坤：长期预研 nvfixer 上加参考图功能 | Fixer优化.md |
| 2026-06-01 | 杨星昊：Difix 接受车身 mask 无需重训，验证良好 | Fixer优化.md |

## 相关文档

- `memory/projects/SIL/Fixer优化.md`（现有项目文件）
