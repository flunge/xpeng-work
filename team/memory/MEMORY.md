# 仿真算法组 — 李坤的数字分身记忆索引

> 🔴 **高频内容已迁飞书（2026-07-06）**：项目 ledger、人物画像、chat-log、周报等**内容型文档**现以飞书云文档为准，
> 供本地定时 agent 每日汇总写入、AI 助手读取，实现多 agent 协作。
> **飞书总索引**：https://xiaopeng.feishu.cn/docx/UwiEdTJJ2oRGokxtkE2cJXjwnyb
> （根文件夹 https://xiaopeng.feishu.cn/drive/folder/W7rqfwqnnlzSfUdEcIGcjcTNnqe ，下设 projects / people / teams / insights / weekly-reports 五层，共 50 篇）
>
> **本地仅保留**：铁律 `rules/`、命令 `commands/`、速查 `refs/`、内容级规则 `insights/{doc-rules,quality-rules,meeting-rules}.md`、`gic-*`、本索引 + 各 `_index`。
>
> 🧭 **规则/命令导航（2026-07-09 重构，单一事实源）**：入口见 `CLAUDE.md`（导航页）。
> - 命令 `commands/`：[update-memory](commands/update-memory.md)（唯一记忆同步命令，原三套流程已合并）、[weekly-report](commands/weekly-report.md)
> - 铁律 `rules/`：[sourcing](rules/sourcing.md)（溯源/回源/读图/数字口径/读逐字稿/跨会议信号）、[writing](rules/writing.md)（飞书写作/工具/画图/认证）、[memory-model](rules/memory-model.md)（golden模板/三线/不写边界/两索引维护/记忆质检/回填/绩效）、[publish-gate](rules/publish-gate.md)（发布前闸）、[report-writing](rules/report-writing.md)（对外文档/汇报叙事/私下话术/ASR表）
> - 速查 `refs/`：[tokens](refs/tokens.md)（群ID/组员p2p/文档token）
> 下方本地链接为迁移前的历史索引，最新内容请以上方飞书文档为准。

## 线1：人物 (people/)

### 我方（组内+老板）
- [likun](people/likun.md) — 李坤 P8 组长 | active
- [gaobingtao](people/gaobingtao.md) — 高炳涛 P9 老板 🔴 | active
- [zheng-lina](people/zheng-lina.md) — 郑丽娜 P7 4OKR业务Owner | active
- [yang-xinghao](people/yang-xinghao.md) — 杨星昊 P6A 4OKR技术Owner | active
- [zhou-weixu](people/zhou-weixu.md) — 周蔚旭 P6A 极速模式 | active
- [pei-jianhong](people/pei-jianhong.md) — 裴健宏 P6 场景编辑 | active
- [zhou-feng](people/zhou-feng.md) — 周冯 P6 Fixer+Diffusion | active
- [lv-wenjie](people/lv-wenjie.md) — 吕文杰 P5 复现率Agent | active
- [wang-yuding](people/wang-yuding.md) — 王禹丁 P5 AVM鱼眼 | active
- [zhu-xiaofeng](people/zhu-xiaofeng.md) — 朱啸峰 P5 HIL部署 | active
- [qu-xinyu](people/qu-xinyu.md) — 瞿鑫宇 P5 慢速模式 | active
- [jin-xirui](people/jin-xirui.md) — 靳希睿 P0 新人 | active
- [yan-xiaozhu](people/yan-xiaozhu.md) — 严潇竹 P0 Prompt Agent | active
- [feng-meihui](people/feng-meihui.md) — 冯美慧 P6 | on-leave

### 管理层
- [liuxianming](people/liuxianming.md) — 刘先明 GIC负责人
- [zhouyue](people/zhouyue.md) — 周月 HRBP

### 上下游
- [dengshuang](people/dengshuang.md) — 邓爽 业务组
- [xulinkun](people/xulinkun.md) — 徐林鵾 平台组 P8
- [xiazhixun](people/xiazhixun.md) — 夏志勋 评估组
- [yangxuezhi](people/yangxuezhi.md) — 杨雪智 AI引擎
- [laixihu](people/laixihu.md) — 赖西湖 引擎组
- [zhangchi](people/zhangchi.md) — 张驰 硬件组
- [wuyimin](people/wuyimin.md) — 吴益民 生产组
- [liukaituo](people/liukaituo.md) — 刘开拓 闭环场景集PM
- [huangbaimin](people/huangbaimin.md) — 黄佰民 平台组PM

### 竞争
- [zhangyu-wangboyang](people/zhangyu-wangboyang.md) — 张雨/王博洋 WM独立团队

### 已离职
- [du-sicong](people/_departed/du-sicong.md) — 杜思聪 6/5离职 O3技术Owner

### 索引
- [人物总览+交叉矩阵](people/_index.md)
- [团队性格画像总集](people/personality-profiles.md)

---

## 线2：团队 (teams/)

- [org-structure](teams/org-structure.md) — 仿真部8组架构+汇报线+会议体系
- [algo-team](teams/algo-team.md) — 算法组13人+OKR+分工
- [collaboration](teams/collaboration.md) — 上下游协作+依赖+痛点

---

## 线3：事情 (projects/)

### 场景&生产
- [_index](projects/场景&生产/_index.md) — Track总览+月目标
- [极速模式](projects/场景&生产/极速模式/ledger.md) — 周蔚旭
- [场景编辑](projects/场景&生产/场景编辑/ledger.md) — 裴健宏
- [AVM鱼眼](projects/场景&生产/AVM鱼眼/ledger.md) — 王禹丁/杨星昊
- [RC路线](projects/场景&生产/RC路线/ledger.md) — 杨星昊
- [闭环场景集推进](projects/场景&生产/闭环场景集推进/ledger.md) — 刘开拓
- [WM-内部探索](projects/场景&生产/WM-内部探索/ledger.md) — 杨星昊

### SIL
- [_index](projects/SIL/_index.md)
- [车型泛化](projects/SIL/车型泛化/ledger.md) — 杨星昊/裴健宏
- [Fixer优化](projects/SIL/Fixer优化/ledger.md) — 周冯
- [CLIP-IQA](projects/SIL/CLIP-IQA/ledger.md) — 王禹丁

### HIL
- [_index](projects/HIL/_index.md)
- [HIL链路部署](projects/HIL/HIL链路部署/ledger.md) — 朱啸峰
- [慢速模式](projects/HIL/慢速模式/ledger.md) — 瞿鑫宇

### Agents
- [_index](projects/Agents/_index.md)
- [复现率Agent](projects/Agents/复现率Agent/ledger.md) — 吕文杰/郑丽娜
- [TopDiff-Agent](projects/Agents/TopDiff-Agent/ledger.md) — 吕文杰
- [Prompt-Agent](projects/Agents/Prompt-Agent/ledger.md) — 严潇竹

---

## 洞察 (insights/)

- [chat-log](insights/chat-log.md) — 群聊关键事件时间线
- [meeting-rules](insights/meeting-rules.md) → 已并入 [rules/sourcing §9](rules/sourcing.md)
- [doc-rules](insights/doc-rules.md) → 已并入 [rules/report-writing](rules/report-writing.md)
- [quality-rules](insights/quality-rules.md) → 已并入 [rules/memory-model §8-10](rules/memory-model.md) + [report-writing](rules/report-writing.md)（记忆质检/回填/绩效/汇报叙事，2026-07-09 重构）

---

## 参考 (refs/)

- [frequent-docs](refs/frequent-docs.md) — 已读文档全量索引
- [lark-cli](refs/lark-cli.md) — lark-cli命令速记
- [image-agent](refs/image-agent.md) — 图像全流程
- [project-context](refs/project-context.md) — lark-cli工作方式

---

## 汇报

- [gic-report-repo](gic-report-repo.md) — GIC双周会仓库
- [gic-report-style](gic-report-style.md) — 李坤汇报风格（周报/GIC/日会）
- [gic-report-judgment](gic-report-judgment.md) — GIC汇报判断校准
- [weekly-report-doc](weekly-report-doc.md) — 周报文档追踪

## 归档

- [weekly-reports/](weekly-reports/) — 每期周报存档
- [daily-sync/](daily-sync/) — 每日采集数据
