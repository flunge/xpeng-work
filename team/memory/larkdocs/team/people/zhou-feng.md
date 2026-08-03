# 周冯

> **📋 文档属性**
> 
> - **标识**：zhou-feng ｜ **状态**：active ｜ **二级部门**：仿真与验证部
> - **核心项目**：Fixer 优化（Owner）、慢速模式（contributor）
> - **内容现势**：截至 2026-07-06（W28）
> - **来源**：W15–W28 每日例会 / 周会 / 组内日会纪要及逐字稿、[simworld 代码提交汇总](https://xiaopeng.feishu.cn/docx/NGx0ddABmoftevxgQxxc29WlnEb)、Fixer ledger（详见各行来源标注）

## 一、角色总览

**基本信息**

- **职级**：P6 ｜ 社招
- **历史绩效**：⚠️ 当前已加载文档中无具体绩效等级记录；如需精确等级需读 H1 绩效表。被杨星昊在李坤面前高度评价"落地快、适合攻坚有挑战性的、像特种部队做斩首任务"（来源：4/13 Q2 分工会逐字稿）。

**角色定位（Q2 OKR 分工）**

- **O2-KR2**：HIL 渲染效果与复现率提升，协同瞿鑫宇。
- **O3-KR1**：长里程 MVP 关键协同（杜思聪执行 Owner）。
- **O4-KR1（执行 Owner）**：Diffusion 新模型探索——轻量化、多摄像头一致性、新视角生成。
- 4/13 Q2 分工会被李坤当场拍板升为 **DIFIX 链路 Owner**（原属王禹丁）。

**性格特点**

- 实验狂热、极其细致、诚实严谨、略显啰嗦、埋头苦干。
- **沟通风格**：被动但刹不住——每个实验讲配置/过程/结论，流水账式。学术诚实——"PSNR 有退化""效果还不如 Difix""提升有限"。
- 典型句式："从昨天到现在又新加了三个实验…"、"效果均未达预期"、"V4 抑制了 PSNR 优化"。
- **坤哥互动**：经常打断重定向——"哪几个能快速拿到验证结果？""你现在连一个对的东西都没有"。反复引导从"学术探索"转向"工程思路"。

**潜力与短板**

- **潜力**：性能优化功底扎实（模块级 profiling、版本对照、memory bound/TRT tactic/kernel fusion 三层分析）；被杨星昊/李坤一致认可为"攻坚型特种部队"；技术闭环能力强（训练→评测→链路适配→TRT 一条龙）；V3C/V3D +8dB 突破为双周会核心成果。
- **短板**：汇报偏流水账需被打断聚焦；6/23 日会缺席被李坤点名"补文档"（到岗/响应负面信号）；缺卡是反复提示的资源瓶颈。
- **成长建议**：汇报练习"先说结论+关键数据、再说实验细节"；将实验方法论（版本对照/消融/全局开关）沉淀为团队规范；对优化路线"天花板判断"能力值得对外分享。

## 二、核心项目

| 项目 | 负责内容 | 项目 ledger |
|-|-|-|
| **Fixer 优化** | Owner：NVFixer/Difix 渲染性能优化（效率从 1:17→1:5 PSNR 持平）、V3C/V3D 新架构（+8dB）、TRT 转换、HIL/SIL 链路适配 | [Fixer ledger](https://xiaopeng.feishu.cn/docx/TBKFdCZLfo3RKJxG2Nzc5ePCned) |
| **慢速模式** | contributor：Seal 链路 NVFixer+TRT 适配 | [慢速模式 ledger](https://xiaopeng.feishu.cn/docx/J138dPjiBoYdBHxAniacGSlWnXe) |

**代码提交记录**（来源：[simworld 代码提交汇总](https://xiaopeng.feishu.cn/docx/NGx0ddABmoftevxgQxxc29WlnEb)，覆盖 2026 年，定期更新）

- **zhouf4**：全分支 **425 commits**，dev **4 commits**，活跃时间 01-04 \~ 07-01，主要方向：NVFixer、Difix 训练、HIL ref 生产、3DGS 自动预处理。
- **6 月单分支直推统计**：4 commits — 3DGS 自动数据预处理与训练、NVFixer Reference Pipeline。
- 关键提交：`[preprocess] add raise_on_smooth_pose_error control`（06-12）、`fix_undistort_module_still_stuck`（06-22）、`[model] add new nvfixer with reference pipeline`（07-01）。
- ⚠️ dev 提交数仅 4，因其大量训练实验不体现在 commit 数中。全分支 425 commits 印证其为渲染优化线主力。

## 三、日常表现

| 时间 | 来源 | 内容 & 分析 |
|-|-|-|
| W15（4/7–4/10） | 每日例会 | 新接手 DIFIX 部署推进快（2 天完成 2/3 目标）；5080 DIFIX 环境适配+TRT engine 生成+渲染链路打通；与朱啸峰上下游协作顺畅。汇报条理清晰（目标拆解+已完成/进行中标注明确）。 |
| W16（4/13–4/16） | Q2 分工会 / 周计划会 / 每日例会 | 被杨星昊力荐、李坤当场拍板升为 DIFIX 链路 Owner。性能优化功底扎实：纯渲染 37ms/baseline 450ms/**V3 去 ref image 降到 326ms**（提速 27%）；模块级 profiling（UNET/encoder/decoder）；被李坤高频追问细节仍应答自如。 |
| W17–W19（4/18–5/8） | 每日例会 / 周会 | **硬核算子/工程优化能力强**：独立啃下 VAE control flow/encoder/decoder TRT 转换深水区；anyfixer 耗时优于 V5（GPU0 167ms）；主动为团队搭共用编包环境+自动化编包+轨迹评测；每个优化项加全局开关+消融实验。是 defix 提速链路稳定执行者。 |
| W20–W22（5/9–5/29） | 每日例会 / 周会 / 离职交接会 | 发现删 cross-attention 反而更接近原图（架构级洞察）；NVFixer 无 ref 图效率优化到 **1:6.7**；**5/18 承接杜思聪 feed forward 及 3DGS 链路**（职责扩大）；效率达标但轨迹评测质量差需重训。 |
| W23–W25（5/30–6/19） | 每日例会 / 周会 | **本期技术战功最突出的人之一**：屡败屡战系统消融（6/8–6/11 连续 4 天实验均未达预期）；**6/12 重大突破——V3C/V3D 架构 PSNR +8dB/+6dB**，李坤当场认可"确实清晰了"；W25 训到 80K 指标优于 Difix 最优版、**耗时 1:17→1:5 PSNR 持平**成为双周会核心亮点。技术闭环能力强。 |
| W26–W27（6/20–6/30） | 每日例会 / 组内日会 | NVFixer 带 ref 链路合入最新 feature、性能数据翔实（单帧仅+2ms、Gating 批量 1:7.2）；果断判断 PTQ 量化否掉、算子融合已天花板→转 VAE 蒸馏；红绿灯 diffusion 验证（"diffusion 对大区域红绿灯处理较好"）。**6/23 日会缺席被李坤点名"补文档"（唯一负面）。** |
| W28（7/1–7/6） | 核心日会 / 组内日会 / 7月目标对齐 | NVFixer 新版 subrun UCP 生产链路+渲染链路合入主分支；车型泛化新策略当天完成编码（SEAL 链路 PyTorch/TRT 全适配、忽略 ref 图+车身 mask）；NVFixer 不支持 ref 图加 mask 高优修复中；极速模式 NVFixer 未针对优化，7 月需重新设计训练数据；NVFixer HIL 适配发现初始化丢帧/抖动问题。交付快、判断实在不吹收益、主动暴露问题。 |
| 2026-07-20\~24（W30） | 作战表 / 核心日会 / WM 同步会 | 🔴 **DVGT-2 重大突破（本周全组最亮点）**：适配 ppu 显卡训练环境、开启大批量消融（7/21）→ 7/24 改模型结构 + 全序列流式推理，用 <800 clips 训 10+ epoch，**feedforward 点云直出效果惊艳**（未收敛已如此），1 clip 端到端全序列流式推理（所有 cam 一次性输入）仅 10min 出头、显存稳定 20G+，泛化细节局部超越 MVSA 伪 GT；已申请 100T NAS 开启大批量训练（LQHuwQvZ）。〔NVFixer 车型泛化链路〕所有 holmes ppu engine 转换完成，端到端单帧 pytorch 141ms vs ppu 104ms、加速 1.35×；新增 USE_NVFIXER_HOLMES_REF_CARMASK 渲染链路待合主线（7/21 STxrwJBK）。〔Robotaxi oncall〕重跑 3dgs/nvfixer/difix 对比 PSNR，结论仿真车与实车不符 case 图片质量本身无问题（7/22）。〔Feedforward〕Scube 改进：VGGT feature 替代 CNN feature、overfitting 实验成功但仍偏模糊、排查 voxel 偏少根因（7/21–24 CHeIwifw）。（来源：Q3作战表 W30、WM 落地闭环同步 7/23） |

> 说明：本表以周为粒度汇总各周综合信号；更细的逐日进展见对应项目 ledger 的「持续进展」。来源均可回溯至溯源索引的会议纪要清单。