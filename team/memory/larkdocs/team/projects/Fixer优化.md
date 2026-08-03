# Fixer优化

> **📋 文档属性**
> 
> - **标识**：fixer-opt ｜ **所属线**：SIL ｜ **状态**：active
> - **负责人**：周冯 ｜ **贡献者**：瞿鑫宇（HIL侧协同）、杨星昊（技术指导）、朱啸峰（台架测试协助）
> - **OKR**：O4-KR1
> - **起始**：2026-04-20 ｜ **内容现势**：截至 2026-07-07（W11）
> - **相关文档溯源**：本项目相关文档 / 嵌套文档统一在[溯源索引](https://xiaopeng.feishu.cn/docx/SsWCdQbVZohGHFxhE3RcCmJ2nSb)「三、项目维度 → SIL → Fixer优化」行维护。

## 一、背景目标

**项目定位（O4-KR1）**：SIL/HIL Fixer 性能优化 + Diffusion 新模型探索。核心效率指标：效率比从 1:8.8 → 1:3 以内。

两条并行线：

- **① SIL difix**：基于 Stable Diffusion UNet + VAE 架构，PyTorch/TRT 链路性能优化（探索架构 / loss / 量化）。各模块耗时占比：VAE Decoder 44.66%、VAE Encoder 34.61%、UNet 20.73%【来源：[SIL & HIL fixer性能优化实验](https://xiaopeng.feishu.cn/wiki/STxrwJBKGi1QPOk1OXrcENZInG6)】。
- **② HIL/SIL nvfixer**：基于 NVIDIA Cosmos Predict2 架构（Cosmos Tokenizer + Pix2Pix Turbo），采用 DiT（Diffusion Transformer 0.6B）+ Fast VAE Tokenizer，**单步扩散推理**（one-step diffusion，固定 timestep）。核心特点：VAE 编解码器 9 层跳跃连接保留结构信息；多损失函数训练（L2+LPIPS+Gram+CLIP+DINO 结构损失）；支持 torch.compile 加速；使用车辆掩码排除自车区域；潜空间压缩比 8×，通道数 16【来源：PlROdzLHNoTVQnxDffVcRoSZnNe】。

**最终目标**：将 Fixer 效率比从 1:8.8 优化到 1:3 以内，同时保证渲染质量（PSNR、轨迹评测）不退化。

**任务缘起**：2026-04-20 项目启动，周冯负责 AIFIX 整体流程【来源：Fixer优化.md】。

## 二、当前状态（截至 2026-07-31）

<callout emoji="📌">
**W31 快照（2026-07-31，来源：Q3 作战表 W31「生产提效/质量效率」列）**：nvfixer 已从实验验证进入生产链路——① 替代 difix 优化新视角代码开发完毕并已打通，Holmes 两种尺寸 .engine 制作完毕；PPU notebook 检测显存最大 18.64GB，单图推理 0.249s vs difix 0.814s，降约 69.41%（效果与 pytorch 版本对比统计中）。② UCP/CloudSim 半卡批量测试通过，单图推理降 70%（≈0.6s）、单 case 平均耗时降 0.2h（2.8h→2.6h），CloudSim 任务未跑完。③ NVFixer 训练数据生产：7200 通过验收 → 10000 clip 已完成（含 8832/10000 中间进度），生产失败 clip 复跑中；对应 NVFixer 生产看板（7/27）：总发起 12,831、成功 9,601、产物通过 7,236、质检失败 2,661。④ nvfixer 训练冒烟跑通。⑤ 5090 主线适配：Nvfix 已跑通，但输出结果异常（FM 无输出）调查调试中。原「效率比 1:3」目标仍以生产链路端到端口径验收。
</callout>

**nvfixer 新架构——快速实验结果优异，进入全量训练阶段**

- **V3C 架构**（DIT 全局 self-attention 拼接 ref+render latent）：+8dB PSNR vs baseline【来源：逐字稿 6/12 组内周会】。
- **V3D 架构**（VAE decoder 后注入 ref）：+6dB PSNR vs baseline【来源：逐字稿 6/12 组内周会】。
- **当前最优 PSNR**（test set）：31【来源：逐字稿 6/12 组内周会】。
- **评测基准**：6 clip 数据集（按时间多样性+版本号多样性重选）。
- **下一步**：V3C+V3D 合并实验 → 全量 64 卡训练 → FM 轨迹评测。
- 🔴 训练集群仅够并行 2 个实验，9 种模式无法并行【来源：Fixer优化.md】。
- 🔴 缺卡，FF Difix 预估需 A100 32 卡×7 天【来源：Fixer优化.md】。
- 🟡 ref 图 OOD 问题（cross-attention 尖锐）待根本解决【来源：Fixer优化.md】。
- 🟡 TRT engine onnx/trt 转换方案复杂，自动化/上手成本高，需重构【来源：Fixer优化.md】。

**关键性能数据（来源：**[**SIL & HIL fixer性能优化实验**](https://xiaopeng.feishu.cn/wiki/STxrwJBKGi1QPOk1OXrcENZInG6)**）**：

- HIL NVFixer TRT 加速：Pytorch GPU0 336.3ms → TRT 167.9ms（约 50% 加速）；显存优化：GPU0 13.3G→5.6G，GPU1 15.0G→6.5G。
- SIL 渲染耗时比（0624 评测，MIG 半卡）：nvfixer_ref 新版本 1:7.2（216s/clip）、nvfixer_ref 旧版本 1:7.0（211s/clip）、difix 1:17.6（527s/clip）。
- 全量 64 卡训练 @80k 结果：V3C LPIPS=0.1496、PSNR=31.33dB，优于 difix_ref（LPIPS=0.1631、PSNR=27.84dB）。
- 消融实验结论：no_detail_adapter 一致优于 detail；128 token 为最优 ref_token_count；λ_lpips=1.0 为单项最大增益（-0.51%）【来源：[SIL & HIL fixer性能优化实验](https://xiaopeng.feishu.cn/wiki/STxrwJBKGi1QPOk1OXrcENZInG6)】。
- NVFixer 可大幅缓解 difix 新视角幻觉问题（通过 pose delay 模拟验证）【来源：[SIL & HIL fixer性能优化实验](https://xiaopeng.feishu.cn/wiki/STxrwJBKGi1QPOk1OXrcENZInG6)】。
- SIL difix 优化实验：EXP_5（非对称 ref 低分辨率）效率比 1:14.8、EXP_6（ref 低分辨率层 attn）1:15.5，baseline MIG 1:17【来源：[SIL & HIL fixer性能优化实验](https://xiaopeng.feishu.cn/wiki/STxrwJBKGi1QPOk1OXrcENZInG6)】。
- 动态物体问题：3 类问题已整理——①遮挡导致新视角检测框丢失（已通过优化缓解）②轨迹抽动（旧版 sensor-fusion→已切 DXNet 解决）③物体新视角效果优化（对称镜像修复+中轴线估计修正）【来源：[动态物体问题整理 & 优化进展](https://xiaopeng.feishu.cn/wiki/GqKCwqNy3iYblXkQabucZxUQn8b)】。

**现有链路**：渲染（3DGS）→ NVFixer（TRT/PyTorch）→ 带/不带 ref 图处理 → FM 轨迹评测 → gating 仿真验证。

**风险小结（截至 2026-07-16）**：🔴 **缺卡仍是首要制约**——训练集群仅够并行 2 个实验（9 种模式无法并行）、FF Difix 预估需 A100 32 卡×7 天，与车型泛化/极速模式争抢公共卡池；🟡 ref 图 OOD（cross-attention 尖锐）待根本解决；🟡 TRT engine onnx/trt 转换方案复杂、自动化与上手成本高需重构。本窗口无新增风险，卡资源缺口由李坤统一协调（与新生产卡到位进度绑定）。

## 三、持续进展

> 同一天若作战表（日报）与日会 / 纪要都有内容，则并列同一行、按来源分列；空格表示该来源当日无对应记录。

| 时间 | 作战表（日报进展） | 会议纪要 / 日会 | 其他来源 |
|-|-|-|-|
| 2026-04-20 | PDJ2 W4：当前链路的效率指标摸底和渲染优化的下一步行动项(收益结论)；；渲染优化方案：【来源：PDJ2 W4】 | feed forward+DIFIX链路目标1h时延；nvfixer训练参数量少1/3加入ref图；DIFIX 5080适配+torchcompile单张降0.8s【来源：OKR会议 4/1-4/3；每日例会 4/9】 | 项目启动：周冯负责 AIFIX 整体流程；Nvfixer TRT 转换多项失败（VAE Encoder/DiT 导出问题）【来源：Fixer优化.md】 |
| 2026-04-22 | — | 极速模式4/30前可用；MVSA Fixer单张75ms待转TRT；nvfix TRT打通GPU0=167ms；seal提速目标1:5【来源：每日例会 4/22-4/24】 | 周冯搭建 MVSA 链路批量化测试，单张 DIFIX\~75-76ms；李坤建议 seal+HIL 合并；杨星昊：长期预研 nvfixer 上加参考图功能【来源：Fixer优化.md】 |
| 2026-04-29 | PDJ2 W5：渲染提速分阶段目标3dgs渲染内参降为difix所需分辨率；UNet cross-attn中ref分支复用main分支对cross attn的结果；Difix模型降低分辨率重训【来源：PDJ2 W5】 | Fixer/显存：运行QAT时显存越来越大导致DefixTRT失败；短期专项排查，长期可能更换框架；生产先用非TRT模式【来源：每日例会 4/30】 | 上海台架自动化编包及轨迹 PSNR 评测基本完成【来源：Fixer优化.md】 |
| 2026-05-11 | PDJ2 W6：【算法优化】Difix性能和效果优化提升gating机制上线；显存优化版本上线；【difix模式下3dgs渲染相关优化】包括降天空分辨率、提高渲染radius clip、仿真渲染分辨率降低与difix同步；【difix模型相关优化】包括模型结构优化和参考图优化【来源：PDJ2 W6】 | UNet/VAE EncoderDecoder耗时优化16%/4%无退化；周冯5080台架批量测试DIFIX优化效果；下周围绕VAE decoder做int8量化【来源：仿真算法组周会 5/9】 | 杨星昊完成显存优化版本实验；周冯明天在 MEGA 上测试提速【来源：Fixer优化.md】 |
| 2026-05-12 | — | — | 将 Defix 性能优化从 PyTorch 链路转到 TRT Engine 链路；重新生成 T2T engine【来源：Fixer优化.md】 |
| 2026-05-13 | — | — | EXP_5/EXP_6 优化明显；EXP_4 更接近原图（可考虑删 cross-attention）；本周 VAE decoder 量化实验【来源：Fixer优化.md】 |
| 2026-05-14 | — | — | 性能基线确定：NA Fixer 单帧（含 3DGS 渲染）\~160ms；4 Camera GPU\~125ms；DeFix 单帧\~300ms【来源：Fixer优化.md】 |
| 2026-05-18 | PDJ2 W8：【算法优化】Difix性能和效果优化提升，阶段性优化到渲染效率1：7。；【算法优化】复现率gating数据集上复现率达成80%以上，效率达到1：25，渲染效率1：5。复现率现状约为60%，当前问题和prompt一致性/pc or mc/trigger time耦合，下一步todo；；渲染效率1：9.2（动态障碍物生产效果调优；3dgs蒸馏difix；difix效果调优；difix效率提升）；【业务交付】：• 车型泛化[车型泛化验证方案]：• [difix ref图模式优化]【来源：PDJ2 W8】 | nvfixer 5080单张40ms→34ms；Defix HIL优化到34ms端到端180→130ms；长期方案用3DGS渲染图经不带ref的difix修复后做ref图【来源：每日例会/核心日会 5/18-5/22】 | 5080 上单张 camera 从 40ms 降到 34ms【来源：Fixer优化.md】 |
| 2026-05-19 | — | — | NVFix 批量化优化（CUDA DAF/CUDA graph/固定 bining/多 batch TRT）；杨星昊建议 Seer 上测试 → 周冯切换工作路线【来源：Fixer优化.md】 |
| 2026-05-20 | — | — | NVFix 最高优化项可达 8%（有显存风险）；切换到 Seer Difix 实验【来源：Fixer优化.md】 |
| 2026-05-21 | — | — | difix 效果没问题，待链路稳定后测试效率；李坤建议朱啸峰协助测试带/不带 difix 效率【来源：Fixer优化.md】 |
| 2026-05-25 | — | — | 无参考图 baseline 大批量失败（sim engine bug 修复）；NVFixer 带 ref 图转 TRT 算子问题全部解决【来源：Fixer优化.md】 |
| 2026-05-26 | — | — | NVFixer 带/不带 Ref baseline 跑闭环：36 clip，每 clip\~200s；李坤要求结果以视频文档发群【来源：Fixer优化.md】 |
| 2026-05-27 | — | — | NVFixer 无参考图版本批量化耗时\~1:6.7；修复 TRT 推理版本和 engine 生成版本不一致 bug【来源：Fixer优化.md】 |
| 2026-05-28 | — | — | NVfixer 不带 ref 图 baseline 跑闭环仿真，FM 轨迹评测效果差；需带强制跟随自车和 trigger time 失效逻辑【来源：Fixer优化.md】 |
| 2026-05-29 (W9) | PDJ2 W9：【算法优化】复现率gating数据集上复现率达成80%以上，效率达到1：25，渲染效率1：5。；【算法优化】SIL链路渲染效率耗时比达到1:7。Nvfixer noref baseline跑通批量闭环仿真：sim engine fix & pythonpath fix，跑完待fm轨迹评测；Nvfixer ref 转换trt engine成功：算子问题fix，今天提交批量仿真；【Difix模型优化】• ref图模型适配换车衣的功能改造，代码已开发完，不需要重训，使用mask在kv query的时候避开mask区域【来源：PDJ2 W9】 | NVFixer NoRef耗时1:17→1:5.8但轨迹效果不佳需重训Ref版；渲染链路改造解决ref图几何干扰【来源：每日例会 W22】 | nvfixer noref 耗时优化到 1:5.8，轨迹评测效果不佳，确认需重训带 ref 版本；TRT 和 PyTorch 版本 diff 最大在 core encoder【来源：Q2 Wiki W9】 |
| 2026-06-01 | — | — | 杨星昊修改渲染流程：Difix 接受车身 mask 且无需重训，测试良好；本周目标：NVFixer TRT 链路渲染质量+光影优化【来源：Fixer优化.md】 |
| 2026-06-02 | — | — | difix ref 图模式优化：极速与普通模式均值差异小；PSNR/SNIP 等打分明显分层【来源：Fixer优化.md】 |
| 2026-06-03 | — | NVFixer TRT与PyTorch链路效果已一致；效率在1:7内(目标1:5)；计划扩大ref token到256-几千个【来源：每日例会 6/3-6/5】 | NVFixer TRT/PyTorch 对齐，确保两条链路效果一致；提升对齐标准，时延略有提升；考虑量化优化【来源：Fixer优化.md】 |
| 2026-06-05 (W10) | PDJ2 W10：【业务交付】【车型泛化-开环】进一步优化算法链路更新渲染链路流程，支持Mask的difix模型上线；设计一版带上ref图的nvfixer模型，并小规模训练验证，在不大幅增加耗时的情况下优化光影效果；【算法优化】复现率gating数据集上复现率达成80%以上，效率达到1：25，渲染效率1：5。；【算法优化】优化渲染耗时以及图像质量• 当前noref / ref版本Nvfixer修复效果量化评估 [SIL & HIL fixer性能优化实验]【来源：PDJ2 W10】 | NVFixer带ref/不带ref PyTorch+TRT同步完成；deefix渲染提速周冯跟进5080搭编包环境【来源：每日例会 6/1-6/5】 | 重训基础版本 nvfixer（小鹏数据 22 个 epoch）；TRT-PyTorch 对齐标准从 PSNR 升级为所有模块 MAE；已提交 nvfixer_ref pytorch & trt 两版本 gating 数据集仿真【来源：Q2 Wiki W10】 |
| 2026-06-10 | — | — | 三波实验并行：①ref 编码优化（8000步 PSNR 退化停训）②新架构探索（35K步提升有限）③loss 设计优化进行中；ref 图 OOD 根因：cross-attention 过于尖锐【来源：Fixer优化.md】 |
| 2026-06-11 | — | — | 周冯重构实验：V3 挑部分/V4 全跑，效果均未达预期；V4 抑制 PSNR 优化；继续优化 loss 向 PSNR 压【来源：Fixer优化.md】 |
| 2026-06-12 (W11) | PDJ2 W11：【算法优化】优化渲染耗时以及图像质量；设计一版带上ref图的nvfixer模型，并小规模训练验证，在不大幅增加耗时的情况下优化光影效果；【算法优化】复现率gating数据集上复现率达成80%以上，效率达到1：25，渲染效率1：5。；【渲染优化】nvfixer ref快速训练实验[SIL & HIL fixer性能优化实验]，目前有两种新模型架构在快速实验上有明显的质量提升，周末正式基于这两个优化进行大批量数据\*64卡训练【来源：PDJ2 W11】 | V3C+V3D 两种新架构快速实验结果优异：V3C +8dB，V3D +6dB PSNR vs baseline；视觉更清晰，LPIPS 明显提升；两架构合并实验提交，若 OK 周末发起 64 卡全量训练；当前 test set 最高 PSNR：31【来源：逐字稿 6/12 组内周会】 | — |
| 2026-06-16 (W12) | nvfixer ref 快速训练实验：两种新模型架构在快速实验上有明显质量提升，周末正式基于最优版本 64 卡大批量训练【来源：Q2 Wiki W12 周三】 | NVFixer效果优于Defix；耗时可降至1:1.5\~1:6目标1:2；带ref效果好；anyfix ref图版本gating评测完成FM轨迹略优【来源：每日例会 6/15-6/17】 | — |
| 2026-06-19 (W12) | PDJ2 W12：【算法优化】优化渲染耗时以及图像质量设计一版带上ref图的nvfixer模型，并小规模训练验证，在不大幅增加耗时的情况下优化光影效果；【算法优化】复现率gating数据集上复现率达成80%以上，效率达到1：25，渲染效率1：5。；Nvfixer ref版本新模型训练 ：[SIL & HIL fixer性能优化实验]• 新仿真镜像 done• 基于上周快速批量消融实验最优版本周末开启正式64卡大批量训练，目前已训完@80k 效果评测优于difix，初步统...；新视角评测链路：新视角渲染 - CLIP-IQA流程接入ucp，ppu是否适配Nvfixer？【来源：PDJ2 W12】  <br/>64 卡大批量训练完成@80k，效果评测优于 difix；初步统计耗时对比 difix 大幅降低；最优版本部署适配推理链路：pytorch 链路 done，5080 台架虚拟机编包 done【来源：Q2 Wiki W12 周五】 | — | — |
| 2026-06-22 | — | Seal 链路已合入 dev 最新 feature（周冯）；台架 TensorRT 转换完成 80%【来源：智能纪要 6/22 每日例会】 | — |
| 2026-06-23 (W13) | HIL Nvfixer ref 新链路搭建：生产 ppu 环境适配镜像制作完成；holmes 替代 trt 用于 ref encoder（耗时提升\~16%，单帧推理 11.7ms）【来源：Q2 Wiki W13 周一】 | nvfixer带ref TRT链路打通与torch对齐；difix ref版本时延增16-20ms排查；tinyVAE蒸馏探索【来源：每日例会 6/24-6/25】 | — |
| 2026-06-24 (W13) | SIL Nvfixer ref：当前闭环仿真 simulation 调用 ref 图不支持 nvfixer 参数，修改 simulation 仓库代码并编包仿真测试 fm 评测通过；尝试 tiny VAE（wan latent 空间和 cosmos 不一致）；HIL Nvfixer ref 新方案优化中【来源：Q2 Wiki W13 周二】 | — | — |
| 2026-06-25 (W13) | SIL Nvfixer ref：重跑闭环仿真轨迹评测，最终 nvfixer ref 新版本 trt 渲染耗时比 1:7.2（之前未优化 1:6.5，Difix 1:17）；PTQ 量化精度敏感；算子融合已达天花板；加入多 stream 异步机制测试中【来源：Q2 Wiki W13 周三】 | — | — |
| 2026-06-26 (W13) | PDJ2 W13：【W13周目标】图像渲染效率1:5方案确认；【算法优化】复现率gating数据集上复现率达成80%以上，效率达到1：25，渲染效率1：5。；【业务交付】630 FM模型实现完全红绿灯通行，需要验证，目前找到10个测试case，已提交生产，生产后review单纯3dgs的效果，后续等zhoufeng的nvfixer上线以后再看一看新效果；HIL Nvfixer ref新链路搭建:[SIL & HIL fixer性能优化实验]• 生产ppu环境适配• 镜像制作完成 infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/...【来源：PDJ2 W13】  <br/>SIL Nvfixer ref 代码合 dev 主分支 done；trt 最新版本转换问题解决；重跑闭环仿真得到最终版本渲染耗时比；HIL 合入 Nvfixer ref 最新分支 & 转 trt 80%；HIL 慢速链路方案：生产线刷一遍 VAE encoder 得 latent，HIL 只读 latent【来源：Q2 Wiki W13 周四】 | — | — |
| 2026-06-27 (W13) | Difix & nvfixer 代码和最新模型权重合入 HIL 最新分支，并测试最新性能【来源：Q2 Wiki W13 周五】 | — | — |
| 2026-06-29 | 【Fixer 渲染优化】HIL nvfixer ref 新链路：生产测代码已完成，已提交 ucp subrun 生产测试（大量任务排队 pending）；HIL 应用测代码 done，适配 nvfixer 从 ceph 自动化下载及解压 latent【来源：Q3 作战表 W27 周一】 | 慢速模式代码合入主线遇FM无输出/CI编包耗时；NVFixer卡在平台OSS→SAVE链路排期【来源：组内日会 6/30】 | — |
| 2026-06-30 | UCP ref latent ppu 生产测：预处理流程已打通 & ref latent 正常输出并上传 oss；解决生产链路 dpvo 不可重复生产 bug；优化 ppu 链路 trt 模型加载流程；修复 difix 兼容新版本 diffuser 问题【来源：Q3 作战表 W27 周二】 | 采用更轻VAE架构+两段式工程改造；参考图特征提前生产渲染时加载latent需后端支持【来源：组内日会 7/1】 | — |
| 2026-07-01 | UCP ref latent ppu 生产链路已全部打通（difix 动态适配高版本 diffuser 库）；HIL XPU 应用测链路全部打通：nvfixer ref trt 效果比原始 3dgs 渲染质量高（但视频中自车启动后画面大幅抖动待修复）【来源：Q3 作战表 W27 周三】 | NVFixer渲染链路已合入主分支；车型泛化新需求适配忽略ref图+车身mask代码完成编包测试【来源：组内日会 7/2】 | — |
| 2026-07-02 | UCP ref latent ppu 生产测已合入主分支；HIL XPU 应用测：生产完一个测试 subrun 用于 HIL 慢速模式测试，数据交给 xinyu 进行批量化时延测试；车型泛化需求代码完成，编包仿真渲染测试中【来源：Q3 作战表 W27 周四】 | 极速模式效果不佳NVFixer未针对优化7月重新设计训练数据；慢速模式多数case极限1:4.86无ref模式1:2.5【来源：7月目标对齐 7/2】 | — |
| 2026-07-03 | 车型泛化需求代码 done，原位 FM 评测（SIL 链路）和 difix mask 渲染策略效果差不多；HIL XPU 应用测修复几个链路问题，重跑批量耗时评估；当前 HIL nvfixer ref trt 效果仍有问题【来源：Q3 作战表 W27 周五】 | 车型泛化生产8个标签筛选车型；difix先行生产nvfixer在测；NVFixer不支持ref图加mask周冯高优修复中【来源：组内日会/7月目标对齐 7/2-7/3】 | — |
| 2026-07-06 | 【Fixer 渲染提速】Nvfixer 生产链路 subrun config 更新：镜像 & tag & 开关打开；Nvfixer carmask 新车型泛化渲染策略增加开关，待合入 dev 主分支【来源：Q3 作战表 W28 周一】 | — | — |
| 2026-07-07 | 【Feedforward】7 月周计划制定；靳希睿开始尝试 VGGT-Ω/DVGT-2/π3 模型推理效果，周冯提供数据 sample 和 benchmark【来源：Q3 作战表 W28 周二】 | — | — |

## 四、后续规划

（来源：逐字稿 6/12 组内周会 + Fixer优化.md 遗留问题）

- **V3C+V3D 合并 → 全量 64 卡训练**：周末启动大批量训练，预计 80-90K 步是最优点。
- **FM 轨迹评测**：全量训练完成后进行变化仿真 FM 轨迹评测。
- **NVfixer 最优版本带 ref 图合入**：PyTorch 链路已完成，TRT 需重新生成 engine（已在 5080 虚拟机编包）。
- **原文渲染批量 gating 测试**：提交 FM 轨迹评测质检。
- **新视角幻觉问题**：杨星昊提出 Difix 新视角有幻觉，周冯将查 NVfixer 最优版本是否缓解并制定优化计划。
- **解决 ref 图 OOD 问题**：cross-attention 过于尖锐的根因待根本解决。
- **HIL ref latent 生产链路完善**：ref latent 在 oss→ceph 拷贝需平台侧支持（陈松排期中）；PPU Holmes 替代 TRT 用于 ref encoder（加速 16%，单帧 11.47ms vs Torch 13.34ms），ref_latent 存储压缩比约 9.4×（2.65MiB→0.281MiB）【来源：[SIL & HIL fixer性能优化实验](https://xiaopeng.feishu.cn/wiki/STxrwJBKGi1QPOk1OXrcENZInG6)】。
- **车型泛化 CarmaskAwareRenderStrategy**：nvfixer 需增加车身 mask 渲染策略（将贴新车身推迟到 nvfixer 之后），SIL pytorch 链路代码 done，待合入 dev 主分支【来源：[SIL & HIL fixer性能优化实验](https://xiaopeng.feishu.cn/wiki/STxrwJBKGi1QPOk1OXrcENZInG6)】。
- **性能优化天花板确认**：PTQ 量化精度敏感（耗时大头层溢出，INT8 GEMM 反而增大延迟），算子融合已达 FMHA 天花板，后续除 QAT 外无量化空间；多 stream 异步机制测试中【来源：[SIL & HIL fixer性能优化实验](https://xiaopeng.feishu.cn/wiki/STxrwJBKGi1QPOk1OXrcENZInG6)】。
- **HIL NVFixer ref TRT 20 项优化路线图（Phase A\~D）**：A 阶段（零精度风险）含 CUDA Graph / pinned bindings / stream overlap / maxAuxStreams / timing cache，实测 stream overlap GPU1 p95 降 8.11%；B 阶段含 VAE IO fp16 / patcher fuse / decoder channels_last / DiT layer precision tune；C 阶段含 FP8 PTQ / INT8 SmoothQuant / strongly typed；D 阶段含 DiT pruning / VAE decoder 蒸馏 / 多 engine 副本调度 / 降分辨率+上采样 / 2:4 structured sparsity【来源：[SIL & HIL fixer性能优化实验](https://xiaopeng.feishu.cn/wiki/STxrwJBKGi1QPOk1OXrcENZInG6)】。