# Prompt-Agent

> **📋 文档属性**
> 
> - **标识**：agent-prompt ｜ **所属线**：Agents ｜ **状态**：active
> - **负责人**：严潇竹 ｜ **贡献者**：吕文杰（代码指导）、郑丽娜（方向）
> - **OKR**：Q2——调试复现率Agent的prompt，降低误报率
> - **起始**：2026-06-10 ｜ **- 内容现势：截至 2026-07-07（W28）**：截至 2026-06-15（W12）
> - **相关文档溯源**：本项目相关文档 / 嵌套文档统一在[溯源索引](https://xiaopeng.feishu.cn/docx/SsWCdQbVZohGHFxhE3RcCmJ2nSb)「三、项目维度 → Agents → Prompt-Agent」行维护。

## 一、背景目标

**项目定位**：调试复现率 Agent 的 prompt，降低误报率。复现率 Agent 一期上线后，gating 数据集中存在 prompt 误报 case，需要系统分析并针对性调优。严潇竹的第一个独立任务。【来源：Prompt-Agent.md】

**核心方法**：分析 gating 误报 case → 分类（参考AI / 不参考AI / 误判） → 针对 AI 误判 case 进行提示词调优 → 与生产沟通二次核验。【来源：JSON W11】

**OnCall Agent 方向演变（Q3）**：由 prompt 调优延伸到3DGS生产OnCall智能诊断 Agent。该 Agent 定位为「基于 AI Agent 的仿真任务智能诊断方案」，演化路径为：自动错误诊断→单次测试报告→多版本对比分析→智能语义问答。飞书机器人作为入口支持生产报错分析/特定任务状态订阅/人工新增规则加入知识库。【来源：doc [Agent汇总开发计划及跟踪](https://xiaopeng.feishu.cn/wiki/NyZQwAiyQikW2Nk844vcv8zLnYd)（Agent汇总计划）+ Q3作战表W27周一】

**底层环境依赖**：OnCall Agent/Docker Agent 等工具运行于 simworld 仓库，该仓库已完成分层重构（13个平铺模块→4层: pipeline/models/libs/agents），文件-32.5%、IPS脚本-56%。四大核心回归链路为 Fuyao预处理+训练、UCP/IPS生产、difix/nvfixer、闭环仿真。Docker Agent（Phase 1-3已完成）支持一条命令完成镜像自动构建（DeepSeek LLM驱动+9种规则错误诊断）。【来源：doc [3DGS 仓库架构优化对比报告](https://xiaopeng.feishu.cn/wiki/A4UuwYfMmiAZkakUw1QcMrEen4c)（3DGS仓库架构优化报告）+ doc [Docker Agent - 快速使用指南](https://xiaopeng.feishu.cn/wiki/Hsw0wTiRpiync6kkLYlcEhIcnXg)（Docker Agent指南）】

**研发闭环Agent关联**：与 Prompt-Agent 同属一个大组（通用Evaluator/研发Agent），该方向另有研发闭环agent（编包→任务提交→结果分析，Temporal工作流引擎，5080台架server端，2026-06-23已可发起编包任务）和训练仿真评测闭环Agent（Planner/Build/Simulation/Report四Agent架构，状态机驱动可恢复长流程）。【来源：doc [研发闭环agent：编包 - 任务提交 - 结果分析](https://xiaopeng.feishu.cn/wiki/G0BGwftdsiIkKJkLeTKcne5hnhe) + doc [训练仿真评测闭环Agent开发](https://xiaopeng.feishu.cn/wiki/ZUGCwVB3fiDcRDkwqYbcCDyInxf)】

## 二、当前状态（截至 2026-07-07）

**目标达成**：

- 已完成 gating 级 prompt 误报 case 分类（三类：参考AI/不参考AI/误判）。【来源：JSON W11】
- 提取重点 case，针对 AI 误判 case 进行调优中。【来源：JSON W11】
- 识别出 prompt 不对齐的两类系统原因：指令跟随生效配置不一致、多高亮功能导致提示词变化。【来源：JSON W11】

**现有链路**：生产部门分析 gating 误报 case → 严潇竹根据人工+AI 结果调整提示词 → 与生产沟通疑似误报进行人工二次核验。

**风险**：

🟢 **（截至 2026-07-16）Prompt 对齐非当前刚需、暂不强制排期**：工具已达标（多轮抽样一致性验证通过），仅复现调查场景低频使用，待 7 月核心集成事项落地后再评估（原计划 07/24 接场景集自动化）。🟡 仿真车/实车分离导致的因果颠倒误报仍是自身误报根因，待排期从根本解决。（来源：核心日会日报/纪要 7/15）

- 🟡 仿真车和实车分离导致的因果颠倒误报是 Prompt Agent 自身误报根因，待排期改进【来源：JSON W11】
- 🟢 误报分类已完成，调优路径清晰【来源：JSON W11】

**OnCall Agent 当前状态（W28）**：

- 日志改造：已完成代码，耗时问题定位为平台logger；最新镜像可解决，测试中。【来源：Q3作战表W28周二】
- Agent开发（传统方式错误分析）：全流程已通，飞书机器人支持查看生产任务情况+失败分析；未知错误人工辅助判断调试中。【来源：Q3作战表W28周二】
- Simworld Agent模块功能升级：五环节R&D Loop统一模板（T0需求结构化→T6结论），预处理闭环已验证（img_processor提速20.8%），P1阶段Fuyao通用化+渲染试点进行中。【来源：doc [Simworld Agent 模块功能升级](https://xiaopeng.feishu.cn/wiki/Vi7Vw0hTyiVUssk8tivc32m7nDe)】
- XPU编包自动化：已有脚本 upload_binary.py（binary编包/HIL PC/VIL/Xcamera），本地增量编译脚本 + 远程自动部署 hil_full_deploy.sh。【来源：doc [XPU 软件自动编译更新 && binary 编译](https://xiaopeng.feishu.cn/wiki/L41IwsWGTi24f4kYScYcQ4OZnQc)】

## 三、持续进展

> 同一天若作战表（日报）与日会 / 纪要都有内容，则并列同一行、按来源分列；空格表示该来源当日无对应记录。

| 时间 | 作战表（日报进展） | 会议纪要/日会 | 其他来源 |
|-|-|-|-|
| 2026-04-03（W14） | — | 高炳涛提出探索smart agent实现与真实车辆交互（避让），先解决单agent【来源：Q2 OKR会议决策与计划4月3日】 | — |
| 2026-04-09（W15） | — | 李坤Q2：引入smart agent能力增强闭环仿真交互性；探索AI agent工具解放重复事务【来源：仿真部Q2-OKR对齐会议】 | — |
| 2026-04-29（W18） | — | MCP Server初版上线（标准接口+鉴权+限流）；初版agent提job+生成分析报告，5月中下交付【来源：仿真核心日会4月29日】 | — |
| 2026-04-30（W18） | — | 高炳涛要求AI agent形成业务反馈闭环、数字化控TOKEN成本【来源：仿真核心日会4月30日】 | — |
| 2026-05-07（W19） | — | 强提示词模式做AB模型评测对比【来源：闭环复现自动化方案Review 5月7日】 | — |
| 2026-05-08（W19） | — | H01 agent多job比较及结果摘要，本地VS Code自动运行，AI使用比例80-90%【来源：仿真核心日会5月8日】 | — |
| 2026-05-14（W7） | 【simworld仓库agent】正在打通飞书链接，通过将agent同步到飞书进行预处理部分的算法优化互动【来源：PDJ2 W7 05/14列】 | — | — |
| 2026-05-22（W8） | 【simworld仓库agent】新增飞书agent可自动调用飞书文档/算法研发agent生成文档；新增fuyao skill让模型学会fuyao命令；新增全闭环预处理调优链路（改代码→任务提交→跟踪→结果分析→文档总结）；新建AI新鲜事群每日9点半精选AI消息推送【来源：PDJ2 W8 05/22列】 | — | — |
| 2026-05-22（W8） | 【HIL链路agent】新增HIL排障SKILL并通过飞书CLI输出排障指引文档；可将对话内容整理成知识库方便新session调用；飞书接入大模型+HIL相关SKILL可通过飞书了解HIL情况并提出优化需求【来源：PDJ2 W8 05/22列】 | — | — |
| 2026-05-29（W9） | 【HIL Agent】基于优化迭代和debug过程蒸馏代码优化思路和排查log的skill提高效率避免AI重复踩坑【来源：PDJ2 W9】 | — | — |
| 2026-06-05（W10） | FMprompt复现率：用deepseek-v4调试（20训练+40验证）单独训练集准确率80%集成到复现率agent中；摆动复现准确率19/24（79%）；HIL链路Agent尝试claude接入大模型操作本地工作目录可执行简单调度命令【来源：PDJ2 W10】 | — | — |
| 2026-06-09（W10） | 【代码Agent】Simworld仓库整理新架构代码release；清理历史大文件/fuyao 3dgs回归测试/ucp回归测试【来源：PDJ2 W10】 | — | — |
| 2026-06-12（W11） | 【Prompt Agent】gating集prompt误报case分为三类（涉及阈值/不参考ai/误判）针对AI误判进行调优；【算法Agent】simworld仓库MR review agent【来源：PDJ2 W11】 | — | — |
| 2026-06-16（W11） | Prompt Agent自身误报和生产沟通疑似误报case人工二次核验；仿真车和实车分离导致因果颠倒误报待排期改进【来源：PDJ2 W11】 | — | — |
| 2026-06-19（W12） | 【提示词Agent】修复变道方向解析错误bug；将速度分析内容单独设置开关控制；重跑验证case用deepseek判断对齐；针对速度差异导致waypoint偏移误判做代码和prompt修正【来源：PDJ2 W12】 | — | — |
| 2026-06-23（W12） | 【代码Agent】dev_v2回归测试完成ucp/fm仿真可正常运行；【Prompt Agent】新跑4个job所有未复现case的fm prompt【来源：PDJ2 W12】 | 画龙测试集准确率80%+满足上线标准；闭环diff评价与人工复验一致率较低【来源：每日例会6.22/6.23】 | — |
| 2026-06-26（W13） | 【Prompt对齐Agent】飞书机器人支持执行提示词对齐判断指令+可视化前端html；新增置信度不影响判断结果；修复抽帧丢失短时段prompt问题重跑73case证实修复有效；新增定位时间戳便于人工核验【来源：PDJ2 W13】 | prompt对齐agent准确率85%（严潇竹）；metric diff review agent已支持6个metric自动diff review准确率50%，每周可迭代3个【来源：每日例会6.25/核心日会6.26】 | — |
| 2026-06-26（W13） | 【研发/生产/仿真/HIL docker环境构建agent】接入deepseek效果还行；新版ppu a100镜像合入；初步尝试输入base image和必备包a100环境可打通【来源：PDJ2 W13】 | — | — |
| 2026-06-29（周一） | 【OnCall Agent】考虑agent后期演化从自动错误诊断→单次测试报告→多版本对比分析→智能语义问答；本周计划打通rebot能够通过日志进行传统方式错误诊断【来源：Q3作战表W27周一】 | — | — |
| 2026-06-30（周二） | 【OnCall Agent】日志改造跟上游对齐已有日志系统处理方式，已确认修改方案【来源：Q3作战表W27周二】 | — | — |
| 2026-07-01（周三） | 【OnCall Agent】日志改造改了少量日志验证流程从标准日志格式到上传oss已通；接下来处理所有不符合规范的日志【来源：Q3作战表W27周三】 | — | — |
| 2026-07-02（周四） | 【OnCall Agent】日志改造代码完成已跑完一个case达到进mr程度；agent开发传统方式错误分析流程大部分代码完成预计明天串联【来源：Q3作战表W27周四】 | — | — |
| 2026-07-06（周一） | 【OnCall Agent】日志改造耗时确认是平台logger问题；改法2升级镜像已fix正在验证；agent开发传统方式错误分析流程已通飞书机器人支持查看生产任务情况+失败分析【来源：Q3作战表W28周一】 | — | — |
| 2026-07-07（周二） | 【OnCall Agent】日志改造使用平台最新镜像能解决仍使用平台logger测试中；agent开发流程已通基于传统方式查询功能已打通（飞书机器人支持）；未知错误人工辅助判断调试中【来源：Q3作战表W28周二】 | — | — |
| 2026-07-14（W29 周二） | — | 【自动化OnCall·核心日会7/14】已打通「传统规则匹配→大模型兜底→结果入库复用」全流程，将通过扶摇接口拉取日志，覆盖此前无日志、难定位的失败任务问题。（来源：仿真核心日会纪要7/14） | — |
| 2026-07-15（W29 周三） | — | 【Prompt对齐·工具专项7/15】已完成多轮case抽样验证，工具输出与预设Prompt逻辑一致性达标；机器人对话结果可正常输出prompt信息是否一致结论。定位：复现调查时关注、正常生产环节不特别关注，当前低频使用；非当前生产核心刚需，暂不做强制排期，待7月核心集成事项落地后再评估推进节奏（原计划07/24上线接入场景集自动化流程）。（来源：仿真核心日会纪要7/15 + 日报7/15工具专项） | — |

## 四、后续规划

（来源：Prompt-Agent.md + JSON W11）

- **持续调优**：针对识别出的 AI 误判 case 逐项调优提示词，目标降低误报率。
- **解决仿真/实车分离问题**：仿真车和实车分离导致的因果颠倒误报，需排期从根本上解决。
- **配置对齐**：修复指令跟随生效配置不一致问题。
- **多高亮功能适配**：解决多高亮功能导致提示词变化的问题。
- **郑丽娜建议**：先调 scale，不行再看简化处理。

**OnCall Agent 后续规划**：

- 本周目标：上线第一版支持生产报错问题分析/任务状态订阅/人工新增规则入知识库。【来源：Q3作战表W27-W28 + doc [Agent汇总开发计划及跟踪](https://xiaopeng.feishu.cn/wiki/NyZQwAiyQikW2Nk844vcv8zLnYd)】
- 中期演化：自动错误诊断→单次测试报告→多版本对比分析→智能语义问答。【来源：Q3作战表W27周一】
- Simworld仓库治理后续：仓库优化方案9.5天执行（架构0.5d+代码整理2d+四域回归7d），回归验收基线为Fuyao/UCP/difix/闭环仿真四条链路全通。【来源：doc [simworld 仓库优化与回归测试执行方案](https://xiaopeng.feishu.cn/docx/O1CXdGF2HoUJ3axrBHQcTMBHn2d)】