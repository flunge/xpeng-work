<title>WM-内部探索</title>

<callout emoji="📌">
**结构说明（2026-07-31 重构登记)**：本档为预研知识总览型文档（非标准「一\~四」 ledger 模板）：1.x=背景目标（含关键决策），2.x=架构与关键方案，3.x=各方向现况（≈当前状态），6.x=规划，7.x=外部参考。进度型日更仍以作战表/日报列动作为准回填到本档相应方向；如需把 WM 预研的项目级进度纳入周报证据包采掘，后续可另拆标准 ledger 本。决策建议：保留现结构（不强制 4 段模板）。
</callout>

> **📋 文档属性**
> 
> - **标识**：wm-internal ｜ **所属线**：场景&生产 ｜ **状态**：active
> - **负责人**：杨星昊 ｜ **贡献者**：靳希睿（AI辅助编码）、赵浩南（W28 feedforward线）、张友健（Feedforward方案）、周冯（DVGT-2/重建侧）、谷佳萱（场景泛化）、樊世洲（Smart Agent）
> - **OKR**：Q3——改善场景质量，探索feedforward方法，解决当前3DGS链路新视角问题
> - **起始**：2026-05 ｜ **最近更新**：2026-07-30
> - **相关文档溯源**：本项目相关文档 / 嵌套文档统一在[溯源索引](https://xiaopeng.feishu.cn/docx/SsWCdQbVZohGHFxhE3RcCmJ2nSb)「三、项目维度 → 场景&生产 → WM-内部探索」行维护。

# 一、项目概述

## 1.1 定位与目标

算法组自主的 World Model 探索（区别于张雨/王博阳外部WM团队），规模远小于外部团队。目标：改善场景质量，探索 feedforward 方法，解决当前 3DGS 链路新视角问题。与外部WM团队不是同一赛道竞争——本探索是辅助性的，用于场景质量优化。

## 1.2 核心问题

现有GS闭环渲染存在3个核心问题：

1. 每个场景GS依赖提前训练，验证/仿真周期长；
2. 动态物体轨迹存在跳变；
3. 动态物体轨迹为预先log检测结果，无法在闭环中根据最新自车位置变化。

## 1.3 关键人物与分工

| 方向 | 负责人 | 当前重点 |
|-|-|-|
| Feedforward 点云重建 | 周冯 | DVGT-2 训练与优化、大批量数据生产 |
| Feedforward 方案设计 | 张友健 | 统一3D Latent Voxel方案推进、Scube优化 |
| WM 视频生成微调 | 杨星昊 / 赵浩南 | Wan2.2 训练、7视角可控视频生成 |
| AI 辅助编码 / 模型评估 | 靳希睿 | VGGT-Ω / DVGT-2 / Pi3 模型推理评估 |
| 场景泛化 | 谷佳萱 | AutoAWG 天气风格迁移、Flux day2night |
| Smart Agent 预研 | 樊世洲 | ProSim 交通流仿真复现 |

# 二、技术路线

## 2.1 三层架构概览

| 层 | 技术方案 | 参考工作 |
|-|-|-|
| **静态受控WM（Image Space）** | 将GS渲染的静态背景作为像素级条件注入WM，约束生成结果；技术子方向：2D受控 / 3D受控 | GEN3C、Inspatio-World、Lyra 2.0、StarGen、VidSplat |
| **动态交互（Action Space）** | 单独模块，即插即用，与静态受控解耦可并行推进 | TrafficBots (ICRA2023)、DiffusionPlanner (ICLR2025)、ResWorld (ICLR2026)、DynFlowDrive |
| **3DGS场景泛化（非WM路线）** | 不依赖world model，通过风格迁移构建低照度/雨雪雾可用数据集；主线"2D编辑+3D一致性传播" | WeatherEdit (AAAI2026)、WildGaussians (NeurIPS2024)、AutoWeather4D |

## 2.2 Feedforward 统一方案——3D Latent Voxel

**提出**：张友健，2026-07-13 ｜ **状态**：方案已通过评审，进入实施阶段

**方案文档**：[Feedforward 3DGS + WM方案提案](https://xiaopeng.feishu.cn/wiki/EUWJwcjJPiieN2kTCAoctA58n5c)

核心思路：引入统一的中间模态——**3D Latent Voxel**，将 feedforward 3DGS 与视频生成联系起来，同时兼容未来 World Model 的流式生成范式。

**Pipeline**：

1. **Feedforward 点云重建**：以 3D Foundation Model（Pi3/VGGT-Ω）为起点，得到多帧融合点云；预处理分离静态和动态点云
2. **构建 3D Latent Voxel**：将点云离散化为均匀 voxel grid，将 2D 图像特征反投影到每个 voxel；feature 可选 CNN feature / VGGT feature / Wan VAE feature
3. **下游任务**：A) 从 voxel latent 直接 decode 3DGS attributes（feedforward 3DGS）；B) 基于 Wan2.2 的条件视频生成（latent rendering 作为参考帧）

**阶段性目标**：

| 阶段 | Action | 与业务的关系 |
|-|-|-|
| **Phase 1** | 优化 Pi3 点云重建 + 训练 feedforward 3DGS decoder head + 后训练过渡方案 | 极速模式常规更新；复现率7月目标60% |
| **Phase 2** | 基于 Wan2.2 训练 noisy 3DGS → clean video 生成器，通过 diffusion forcing 训练流式版本 | 长里程场景、天气转换，无需再重建场景 |
| **Phase 3** | 训练 latent rendering → clean video 生成器，跳过显式 Gaussian rendering | 同上，效率与效果进一步提升 |

**风险与回退**：latent rendering 作为条件风险较大→回退到 point cloud / 3DGS rendering 作为条件；feedforward 效果太差→仅作 per-scene 优化加速方案；动静态分离难度大→静态融合+动态沿用 SAM3D。

## 2.3 关键决策讨论（2026-07-13）

李坤对张友健方案的评审意见：

- 方案思路完整，也有前瞻性。现在有几条线在同时跑：周冯 feedforward 选型已定 Pi3/VGGT-Ω 做 baseline、搭了统一 benchmark；希睿在做 VGGT-Ω 和浩南静态 GGS+WM；Scube 点云到高斯链路也在优化。最好能凑到一条主线上。
- 静动态分离在路端场景是难点——Phase 1 先把静态做扎实、动态用现有方案兜底。
- voxel 分辨率、压缩比和显存/耗时的权衡，Phase 1 就定可量化目标（PPU 显存和耗时是硬约束）。
- Phase 2 的 latent rendering 风险大——先用显式 rendering 跑通拿到收益，再走 latent。

Q3 OKR 对齐（2026-07-21）：生产这块和星昊哲成一起讨论，如何把 feedforward 短中期目标和产线重构升级相结合。

# 三、各方向进展与状态

## 3.1 静态受控 WM（Inspatio-world / 视频生成微调）

**负责人**：杨星昊 / 赵浩南 ｜ **状态**：🟡 核心瓶颈未突破，但输入侧现突破口

**目标**：通过 LoRA / 全量微调视频生成模型，使 GS 渲染结果在新视角下保持几何一致性与图像质量。

**Inspatio-world 微调实验关键结论（6/17\~7/1）**：

- 模型确实能从 render latent 学几何、从 ref 学风格和内容（6/25 修复 inference bug 后确认）
- 原位效果好、异位效果差（左移3m高频模糊）——核心瓶颈为**异位/高频缺失时的泛化想象力不足**
- 14b 模型较 1.3b 有提升，但动态异位高频信息缺失问题仍未解决
- 后续改进方向：① 多cam输入提供空间高频；② 保留Wan从纯噪声生成能力；③ 参考artifixer经验

**GS后训练引导零shot实验效果**：行人非刚性可学到、光线变化可学到、车轮旋转可学到。问题：chunk间颜色跳变、无中生有物件、路牌文字扭曲、远处动态物体形变。150帧耗时：初始化290s、VAE Encode 3.97s、DiT 17.89s、VAE Decode 1.07s。

**W30 进展**：赵浩南训练 7 视角可控驾驶视频自回归生成；分别验证 feedforward / 高质量 / nvfixer 优化 3dgs 作为 control video 的效果；尝试 day2night 场景泛化。

**当前风险**：🟡 车的幻觉问题未解决 ｜ 🟡 feedforward方向尚在决策阶段 ｜ 🟡 CAM3 畸变相机有车道线幻觉 ｜ 🟡 异位泛化想象力不足

## 3.2 Feedforward 点云重建（DVGT-2 / Scube）

**负责人**：周冯 / 张友健 ｜ **状态**：🟢 DVGT-2 取得重大突破

**DVGT-2 突破（2026-07-24）**：

- 魔改模型结构、支持全序列流式推理
- <800 clips 训 10+ epoch，feedforward 点云直出效果惊艳（未收敛）
- 单 clip 端到端全序列流式推理（所有 cam 一次输入）仅 10min 出头、显存稳定 20G+
- 泛化细节部分超越 MVSA 伪 GT（远处大楼 MVSA 无点云 DVGT-2 有）
- 已额外申请 100T NAS、开启大批量训练数据生产

**Scube 优化**：用 VGGT feature 替代 Scube 原 CNN feature，未训练前 inference 可行；overfitting 实验一度不佳、7/23 改用原始 Scube 代码后成功但仍偏模糊。

**Pi3 baseline**：Pi3 目前点云重建效果最好，作为统一 benchmark 的 baseline。周冯已搭建统一 benchmark 框架。

**浩南评测问题**（2026-07-30）：张友健反馈浩南路径一致但进度偏快，没太评估就跑到下个阶段，已要求补评测。

## 3.3 场景泛化（WeatherEdit / AutoAWG）

**负责人**：谷佳萱 ｜ **状态**：🟡 部分数据过度风格化，AutoAWG 链路待跑通

**WeatherEdit 进展**：

- 已完成环境构建、开源数据集验证、公司数据集转换及初步结果（snowy/rainy/foggy 三种天气）
- 7/2 打通从头到尾训练链路（fuyao集群跑通）
- 7/3 接入3DGS pipeline渲染效果图（snowy风格），已产出4个case视频
- 引入量化指标：CLIP-S语义相似度 / CLIP-DS方向一致性 / 时间一致性 / 颜色分布相似性
- 待解决：部分公司数据过度风格化；迁移至3DGS可行性验证

**AutoAWG（W30 新方向）**：Weather Palette → Adaptive Fusion → Conditional Canvas → DiT → Diffusion Painter，本周争取跑通拿初步结果；数据集准备计划 7cam 同时输入。

**白天黑夜泛化落地（W30）**：场景泛化开环链路已打通——浩南给出泛化后黑夜效果图作为开环 dds 再跑仿真。初步结论：用 3dgs 作 control video 时夜间画龙少于白天，但用 nvfixer 修复视频作 control video 时夜间画龙与白天相近甚至略多。已重刷为 nvfixer 修复视频用于泛化交付。

## 3.4 动态交互 / Smart Agent

**负责人**：樊世洲 ｜ **状态**：🔴 ProSim 复现效果差

**ProSim 复现（W30）**：复现了 ProSim 论文，但效果在我们数据上很差。张友健推荐该工作的多控制模式框架（设置终点 / prompt 指令 / 给定轨迹）可借鉴用于交通流仿真。

# 四、持续进展（时间线）

同一天若作战表（日报）与日会/纪要都有内容，则并列同一行、按来源分列。

| 时间 | 方向 | 进展 | 来源 |
|-|-|-|-|
| 2026-04-02（W14） | WM | VAE多卡4.5倍提速；GWM闭环6case路面标识未受控；场景泛化方向启动 | WM闭环仿真4/2 |
| 2026-04-09（W15） | WM | 推理440s→355s；风格迁移昼夜切换启动；WM应重泛化非复现率 | WM闭环仿真4/9 |
| 2026-04-16（W16） | WM | motion control接入；caption链路验证完成Cloudsim支持 | WM闭环仿真4/16 |
| 2026-04-23（W17） | WM | WM闭环仿真输出文档；2.1模型车道线更好但变色 | WM闭环仿真4/23 |
| 2026-04-30（W18） | WM | caption最近匹配+首帧即请求WM；新2D模型MC轨迹受控贴近实车 | WM闭环仿真4/30 |
| 2026-05-14（W20） | WM | 2.1模型改善(静态受控+导流线)；caption scenario自动化本周打通 | WM闭环仿真5/14 |
| 2026-05-18（W21） | WM | 轻量级world model方案(非pixel级,输出6DOF数值)；差异化+算力受限 | 每日例会5/18 |
| 2026-05-22（W8） | Feedforward | 动态World model+静态GGS的方案调研中 | PDJ2 W8 |
| 2026-05-29（W9） | WM | WM新模型适配完成；并行推理Re+ASGL+Diffusion+Ray传输 | WM5.28 |
| 2026-06-05（W10） | WM | 代码成型4张H800 serve 12 session；KV cache FP8量化11G→5G；6/7交付MVP闭环 | WM闭环仿真6/4 |
| 2026-06-10（W11） | WM | 极速模式复现率74%；场景泛化因人力搁置 | 仿真核心日会6/10 |
| 2026-06-11（W11） | WM | GWM 26case 4大问题；WM推理4FPS(18session) | WM进展同步6/11 |
| 2026-06-19（W12） | WM / Feedforward | 静态受控WM方案计划已列出；WM作为泛化测试集用CCES指标；昼夜切换实验展示 | PDJ2 W12 / WM闭环仿真6/17-18 |
| 2026-06-22 | WM | inspatio-world微调750步效果一般(依赖ref,feedforward信息不足)；训练代码改善32卡半天10epoch | 每日例会6/22-23 |
| 2026-06-26（W13） | 场景泛化 / WM | 天气迁移cam2时序一致性对齐较好；场景泛化Agent输出初版cut-in结果；multi-batch PSNR 50→20；FP8推理0.8→1.8s | PDJ2 W13 / WM同步6/25 |
| 2026-06-30（W27） | Feedforward | 算法预研列@靳希睿【WM+GGS】 | Q3作战表 W27 |
| 2026-07-02（W27） | WM | WM→CCES链路打通,120case抓约10问题 | WM进展7/2 |
| 2026-07-03（W27） | 场景泛化 | 天气编辑2D实现泛化出视频(雪天过度风格化,拟先雨天) | WM同步7/3 |
| 2026-07-06（W28） | Feedforward | @赵浩南 开始承接feedforward线 | Q3作战表 W28 |
| 2026-07-07（W28） | Feedforward | 靳希睿开始尝试 VGGT-Ω / DVGT-2 / Pi3 模型推理评估；周冯提供数据sample和benchmark | Q3作战表 W28 |
| 2026-07-13 | **里程碑** | 张友健提交 Feedforward 3DGS + WM 方案提案；李坤评审通过，提出静动态分离、voxel 分辨率、latent rendering 风险等关键意见 | 张友健/李坤 1:1 |
| 2026-07-16 | Smart Agent | 张友健推荐 ProSim 交通流仿真框架（多控制模式：终点/prompt/轨迹） | 张友健/李坤 1:1 |
| 2026-07-20\~24（W30） | Feedforward | DVGT-2 重大突破：<800 clips 训10+epoch效果惊艳、流式推理10min显存20G+、泛化超越MVSA伪GT；已申请100T NAS开启大批量训练 | Q3作战表 W30 |
| 2026-07-20\~24（W30） | WM | 赵浩南训练7视角可控驾驶视频自回归生成；验证feedforward/高质量/nvfixer 3dgs作为control video效果 | Q3作战表 W30 |
| 2026-07-20\~24（W30） | 场景泛化 | AutoAWG天气风格转换本周争取跑通；Flux协助day2night；开环链路已打通 | Q3作战表 W30 |
| 2026-07-20（W30） | Smart Agent | 樊世洲复现ProSim，效果在我们数据上很差 | Q3作战表 W30 |
| 2026-07-30 | Feedforward | 张友健与浩南对齐：路径一致但进度偏快，需补评测 | 张友健/李坤 1:1 |

# 五、风险汇总

| 风险 | 影响方向 | 状态 |
|-|-|-|
| Inspatio-world 异位/高频缺失时泛化想象力不足 | WM | 🟡 核心瓶颈，14b模型仍未解决 |
| 车的幻觉问题未解决 | WM | 🟡 LoRA训练仍有瓶颈 |
| CAM3 畸变相机护栏位置不对，有车道线幻觉 | WM | 🟡 |
| feedforward 方向实现路径未定 | Feedforward | 🟡 LoRA+DeepSeek方案待更多实验 |
| 部分公司数据过度风格化 | 场景泛化 | 🟡 需调prompt/alpha强度 |
| ProSim 复现效果差 | Smart Agent | 🔴 在我们数据上效果差 |
| latent rendering 作为条件风险较大 | Feedforward Phase 2+ | 🟡 可回退到显式 rendering |

# 六、后续规划

## 6.1 短期（Q3 正在进行）

- **DVGT-2 大批量训练**：利用 100T NAS 进行大批量数据生产和训练（周冯）
- **Wan2.2 训练**：成对3DGS渲染+真实视频训练Wan2.2并测效果（赵浩南）
- **多实验定输入**：按李坤要求做更多实验确定最优输入选择——3DGS渲染 vs feedforward（杨星昊）
- **浩南评测补充**：补齐 feedforward 线的评测环节（张友健督办）
- **AutoAWG 跑通**：天气风格转换链路跑通拿初步结果（谷佳萱）

## 6.2 中期（Q3\~Q4）

- **feedforward 方向决策**：LoRA+DeepSeek微调方案待更多实验后最终决策
- **解决车辆幻觉**：增加训练轮次或调整训练策略
- **Inspatio-world 改进**：多cam输入提供空间高频；保留Wan从纯噪声生成能力；参考artifixer经验
- **Phase 1 目标**：达到并优于 Scube 的重建效果；复现率7月目标60%

## 6.3 长期（Q4+）

- **Phase 2**：基于 Wan2.2 的 noisy 3DGS → clean video 生成器，支持流式生成
- **Phase 3**：latent rendering → clean video，跳过显式 Gaussian rendering
- **World Model 愿景**：可控的、可拓展到大场景的、可重复仿真的世界模型

# 七、相关论文

## 7.1 Feedforward / 3D Foundation Model

**VGGT: Visual Geometry Grounded Transformer**（CVPR 2025 Best Paper）

Meta 提出的纯前馈 3D 重建 Transformer，从多张图像直接预测相机参数、深度图、点云和 3D 点轨迹，无需 per-scene 优化。连续两年获 CVPR Best Paper，是 feedforward 3D 重建的基石工作。本方案将其作为点云重建的 backbone 之一。

**VGGT-Ω**（内部改进版）

在 VGGT 基础上针对车载多相机场景优化的变体，改进了多视角一致性和深度精度。周冯团队选型确认为 feedforward baseline 之一。

**Pi3: Permutation Invariant 3D Reconstruction**

当前点云重建 SOTA 方法，在统一 benchmark 中效果最佳。采用置换不变性设计，支持任意数量输入视图的多帧融合点云重建。张友健方案将其作为 Phase 1 点云重建的核心模型。

**DVGT-2**（内部突破性工作）

周冯团队开发的 feedforward 点云直出模型，支持全序列流式推理。<800 clips 训练 10+ epoch 即达到惊艳效果，单 clip 全序列推理仅 10min、显存稳定 20G+，局部泛化超越 MVSA 伪 GT。是 WM 输入选型的重要候选。

**Scube: Voxel-based 3DGS Attribute Prediction**

将 3D 点云体素化后，从 voxel feature 直接 decode 3DGS 属性（位置、颜色、不透明度、协方差等）。张友健方案在此基础上改进 feature 来源（用 VGGT feature 替代原 CNN feature），并作为 3D Latent Voxel 的下游 decoder。

**Evolsplat / SparseSplat / Pointworld**

Feedforward 3DGS 的三条技术路线代表：Evolsplat 采用 voxel 化压缩、SparseSplat 和 Pointworld 采用点重要性采样。张友健方案选择 voxel 路线，因其更接近大模型通用 token 表示，便于与生成模型结合。

**MVSNet / MVSAnywhere**

多视角立体视觉网络，用作 feedforward 点云重建的 teacher GT。MVSAnywhere 是其泛化版本，支持跨场景迁移。

## 7.2 World Model / 视频生成

**Inspatio-World: Causal Video Diffusion for In-car World Model**

基于因果视频扩散模型的车内世界模型，支持 LoRA 微调（1.3B/14B）。在本项目中用于静态受控 WM 的核心实验——从 3DGS 渲染+参考图学习新视角生成。核心发现：模型能从 render 学几何、从 ref 学风格，但异位泛化想象力不足。8×A100 训练 4-5 天，推理 10FPS。

**Wan2.1 / Wan2.2**

视频生成基座模型。Wan2.1-14B 用于 Inspatio-world 全量微调实验；Wan2.2 用于赵浩南的成对 3DGS 渲染+真实视频训练，以及张友健方案 Phase 2 的 noisy 3DGS → clean video 生成器。

**DiffSynth**

视频生成模型的 LoRA 训练框架，用于 Inspatio-world 的微调实验。10 epoch 训练后摩托车幻觉有改善，但车的幻觉未消失。

**Xiaomi EV World Model**

小米 EV 团队的世界模型工作，验证了流式重建+生成的可行性：先生成点云 → 辅助生成未来帧 → 再生成点云并 merge 的循环机制。兼顾 3D 一致性和生成质量上限。张友健方案的流式生成范式参考了此工作。

**Gen3C: 3D-Consistent Video Generation**

通过 3D 感知条件注入实现 3D 一致的视频生成。静态受控 WM 的参考方案之一。

**Latent Spatial Memory**

提出 3D latent 作为视频生成的空间记忆条件，保留几何结构一致性和 low-level texture。张友健方案的 latent rendering 思路受此启发。

**Diffusion Forcing**

训练框架，将 clip 级视频生成转为流式生成。张友健方案 Phase 2 计划通过 Diffusion Forcing 实现流式 World Model。

## 7.3 3DGS / 渲染优化

**Difix: Single-Step Diffusion Fixer**

单步扩散模型，用于修复 3DGS 渲染的 artifacts（模糊、噪声、空洞等）。当前链路中用于 3DGS 渲染 → 异位渲染 → 再 Difix 生成参考图。

**Artifixer**

3DGS 渲染 artifact 修复器，比 Difix 更进一步。张友健方案的条件视频生成相当于其进阶版（省掉显式 rendering 再 encode 的过程）。Inspatio-world 后续改进也参考其经验。

**NVFixer**

新视角修复模型，用于优化 3DGS 渲染视频作为 control video 的效果。场景泛化实验中发现 nvfixer 修复视频作 control video 时夜间画龙与白天相近。

**SAM3D**

动态物体 3D 重建方案。张友健方案中用于动态点云的处理（动态物体先用 SAM3D 结果，静态点云做融合）。

## 7.4 动态交互 / 交通仿真

**ProSim: Promptable Traffic Simulation**

支持多种控制模式的交通流仿真框架：设置终点、给 prompt 指令、给定轨迹。张友健推荐用于交通流仿真，樊世洲复现后在我们数据上效果较差，但框架设计（多控制模式）可借鉴。

**TrafficBots**（ICRA 2023）

多智能体交通仿真系统，支持个体行为建模。动态交互层的参考方案之一。

**DiffusionPlanner**（ICLR 2025）

基于扩散模型的规划器，用于动态交互层的动作空间决策。

**ResWorld**（ICLR 2026）

韧性世界模型，处理动态场景中的不确定性和鲁棒性。动态交互层参考方案。

**DynFlowDrive**

动态流驱动方法，用于模拟交通流的动态变化。动态交互层参考方案。

## 7.5 场景泛化 / 风格迁移

**WeatherEdit: 2D Editing + 3D Consistency Propagation**（AAAI 2026，已开源）

天气风格迁移的标杆工作。先在 2D 图像上做天气编辑，再通过 3D 一致性传播到多视角。本项目中作为场景泛化主线方案，已产出 snowy/rainy/foggy 三种天气的初步结果。

**WildGaussians**（NeurIPS 2024，MIT 已开源）

外观建模分支，用于 3DGS 的风格迁移底座。支持在不改变几何的前提下修改场景外观。

**AutoWeather4D**

自动化天气评估方案，用 3D 检测器 IoU 衡量标签可用性 + DepthAnythingV2 si-RMSE 衡量深度一致性。场景泛化的评估方案借鉴此工作。

**AutoAWG: Weather Palette → Adaptive Fusion → Conditional Canvas → DiT → Diffusion Painter**

谷佳萱 W30 引入的新方法，用于天气风格转换。计划 7cam 同时输入做数据集准备。

**Flux I2I**

图像到图像编辑模型，用于白天泛化到黑夜的首帧编辑。W30 场景泛化中用于 day2night 任务。

## 7.6 其他参考

**Lyra 2.0**、**StarGen**、**VidSplat**

静态受控 WM 的参考方案，各具特色但均未在本项目中深入实验。

**DepthAnythingV2**

深度估计模型，用于 AutoWeather4D 评估中的 si-RMSE 深度一致性指标。