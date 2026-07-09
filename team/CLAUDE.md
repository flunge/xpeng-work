# 仿真部 - 飞书工作空间交互（导航页）

> **核心定位**：通过 `lark-cli`（默认 `--as user`）读写飞书，维护仿真算法组（李坤 P8 视角）的团队记忆系统。
> 本文件是**导航页**：只说"有什么、去哪读"。具体规则/流程在下方各文件里（单一事实源，别处只引用不复制）。
> 🔴 每次工具调用先自查 `antml:invoke`/`antml:parameter` 前缀——断了先查前缀（详见 rules/writing §0）。

## 🧭 遇到什么，读哪个文件

| 场景 | 读 |
|---|---|
| 用户发 **【更新记忆】** | `memory/commands/update-memory.md`（唯一记忆同步命令） |
| 写**周报 / 双周报** | `memory/commands/weekly-report.md` → skill |
| 任何**报告/修改前**的信息获取（溯源/回源/读图/数字口径/不懂就问） | `memory/rules/sourcing.md` |
| 写**飞书文档/表格/@人/超链接/画图**、lark-cli 工具、身份认证 | `memory/rules/writing.md` |
| 记忆**写哪里、golden 模板、三线关联、什么不写、两索引维护** | `memory/rules/memory-model.md` |
| 对外报告**发布前必过的闸** | `memory/rules/publish-gate.md` |
| 写**对外文档/汇报/述职**的内容与风格（不写晋升/@人名/scope/去AI腔/STAR/私下话术/ASR表） | `memory/rules/report-writing.md` |
| 常用**群 ID / 组员 p2p / 文档 token** | `memory/refs/tokens.md` |
| 报告**内容规范**细节 | 周报 `.claude/skills/weekly-report/SKILL.md`；GIC `memory/gic-report-style.md` |
| lark-cli **命令与参数** | `lark-cli skills read lark-doc`（及各 service skill）——本仓库不再维护重复手册 |

## 📚 记忆系统在哪
- **内容型记忆以飞书为准**（项目 ledger/人物画像/chat-log/周报）：总索引 `UwiEdTJJ2oRGokxtkE2cJXjwnyb`，根文件夹 `W7rqfwqnnlzSfUdEcIGcjcTNnqe`（projects/people/teams/insights/weekly-reports）；定位用 `memory/_feishu_map.json`。
- **本地只留规则与索引**：`memory/rules/`（铁律单一源）、`memory/commands/`（命令手册）、`memory/refs/`（速查）、`memory/insights/{doc-rules,quality-rules,meeting-rules}.md`、`memory/gic-*`、`MEMORY.md`、各 `_index`、`_feishu_map.json`。
- **两大索引**：内部索引=我记什么、溯源索引 `SsWCdQbVZohGHFxhE3RcCmJ2nSb`=我从哪读的（维护规则见 memory-model §6）。

## ⚙️ 自动采集
macOS LaunchAgent 每天 22:07 跑 `scripts/daily-sync.sh` → `memory/daily-sync/YYYY-MM-DD.json`（**只是索引/指针，不是事实源**，严禁从 JSON 摘要直接写记忆）。

## 🔑 最高铁律（详见对应 rules 文件）
1. **溯源先行**：先吃透全貌再动笔，不在字面上删改（sourcing §1-2）。
2. **理解→协调→修订**：更新记忆是新增/修订/解除/关联，不是粗暴增量（update-memory §一）。
3. **只重述不脑补**，缺数据如实标注；不懂就问（sourcing §6）。
4. **他组的事不进本组记忆**；茶水间/口头预估是参考不是进展（memory-model §5 / sourcing §8）。
5. **对外报告发布前必过 preflight 闸**，禁逐点反应式交付（publish-gate）。
