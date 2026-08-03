# 仿真部 team 规则索引

> 单一导航源。本目录（`/workspace/.claude/team/`）存**规则/命令/参考**；**记忆内容一律在飞书**，本地不保存。
> 处理 `team/` 下工作时，先读本索引定位到具体规则文件。触发词见下表。

## 🧭 遇到什么 → 读哪个

| 场景 / 触发词 | 文件 |
|---|---|
| **【更新记忆】** | `commands/update-memory.md`（唯一记忆同步命令） |
| **文档库检索**（工程/项目文档事实、规范参数、设计细节） | 用 `docs_search` / `docs_locate` 工具（xai extension `~/.pi/agent/extensions/lark-rag.ts`），底层= `team/scripts/larkdocs_sync.py` 每日 23:00 镜像 + `team/scripts/doc_rag.py` 建索引；镜像根 `team/memory/larkdocs/`（96篇=jiangji 星际骑遇 46 + team 记忆库 50，只读缓存禁止手编）；拿到 token 需原文精读用 `docs +fetch` |
| **lid 叙事反哺 L1**（从 ledger 持续进展表逆推 Episode） | `team/scripts/backfill_episode_from_ledger.py --ledger memory/larkdocs/team/projects/<项目>.md --project <项目名> [--dry-run]`（每周五 23:00 自动跑全项目） |
| **ledger 🔴🟡 → 开口项**（强制互查） | `team/scripts/sync_open_items_from_ledger.py [--apply]`（同步开口项 Base，防 ledger 空谈） |
| **Storyline 主线卡** | `team/scripts/storyline_gen.py --date <周五> [--dry-run]`（周五 20:00 生成候选待确认） |
| **【风险哨兵】** | `team/scripts/risk_sentinel.py --push`（承诺逾期 + 开口项失联 + **项目级停摆**） |
| **【风险哨兵】**（承诺/逾期每日推送） | `team/scripts/risk_sentinel.py` — 读承诺追踪 Base（`NkIZb7eU7azZIEsegJ7cl2bfnUd` 表「承诺追踪」），每日 09:00 判级推送李坤 DM |
| 写**周报 / 双周报** | `commands/weekly-report.md`；写之前先跑证据包：`python3 team/scripts/memory_query.py --start ... --end ... --out ...`，写完跑 `check_report.py <token> --evidence <包>` 做数字回查 [LOWCONF] |
| 报告/修改前**信息获取**（溯源/回源/读图/数字口径/不懂就问） | `rules/sourcing.md` |
| 写**飞书文档/表格/@人/超链接/画图**、lark-cli、身份认证 | `rules/writing.md` |
| 记忆**写哪里/golden 模板/三线关联/什么不写/两索引** | `rules/memory-model.md` |
| 对外报告**发布前必过闸** | `rules/publish-gate.md` |
| 写**对外文档/汇报/述职**内容与风格 | `rules/report-writing.md` |
| **GIC 双周报**风格 | `rules/gic-report-style.md`（+ `gic-report-judgment.md` / `gic-report-repo.md`） |
| **周报**内容规范 | `rules/weekly-report-doc.md` |
| 群 ID / 组员 p2p / **文档 token** 速查 | `refs/tokens.md` |
| 常用文档 / 图片 agent / 项目上下文 | `refs/frequent-docs.md`、`refs/image-agent.md`、`refs/project-context.md` |
| 文档/会议/质量**洞察规则** | `insights/doc-rules.md`、`insights/meeting-rules.md`、`insights/quality-rules.md` |
| lark-cli 命令与参数 | `lark-cli skills read lark-doc`（各 service skill 自带，本仓不重复维护） |

## 📚 记忆内容在飞书（本地不存）

| 资源 | token / 链接 |
|---|---|
| **根文件夹**（projects/people/teams/insights/weekly-reports） | [`W7rqfwqnnlzSfUdEcIGcjcTNnqe`](https://xiaopeng.feishu.cn/drive/folder/W7rqfwqnnlzSfUdEcIGcjcTNnqe) |
| 内部索引（记了什么） | `UwiEdTJJ2oRGokxtkE2cJXjwnyb` |
| 溯源索引（从哪读的） | `SsWCdQbVZohGHFxhE3RcCmJ2nSb` |
| 名称 → 飞书文档 token 映射 | `/workspace/team/memory/_feishu_map.json` |
| 承诺追踪 Base（P0 风险哨兵） | `NkIZb7eU7azZIEsegJ7cl2bfnUd`（表「承诺追踪」：承诺内容/承诺人/Deadline/状态/证据来源/最近核查日期；表「开口项追踪」tblZ7Mp5mLhY2Cnw：各项目 PENDING/风险/遗留事项的开口+状态闭坏，与 ledger 互锁） |

- 项目 ledger / 人物画像 / chat-log / 周报 **全部在飞书**，读写靠 `_feishu_map.json` 定位。
- **需要修改内容 = 直接改飞书文档**；本地不留任何中间产物，修改轮次结束即删。

## 🔀 信息路由（先判断问什么，再选工具）

| 问题类型 | 首选 |
|---|---|
| 工程/项目文档事实、规范、参数、设计细节 | `docs_search`（关键词）→ 必要时 `docs +fetch` 读原文 |
| 动态进展、本周发生了什么、承诺/开口项状态 | `team/scripts/memory_query.py` 证据包 + 追踪 Base |
| 对话历史、谁在哪天说过什么 | daily-sync JSONL + Episode 事件流 |
| 个人习惯、环境事实、跨会话偏好 | xai memory 热内存（`~/.pi/agent/memories/`，只留指针+高频条目，详见 MEMORY.md 分层注释） |

## 🔑 最高铁律

1. **溯源先行**：先吃透全貌再动笔（`rules/sourcing.md` §1-2）。
2. **理解→协调→修订**：更新记忆是新增/修订/解除/关联（`commands/update-memory.md`）。
3. **只重述不脑补**，缺数据如实标注（`rules/sourcing.md` §6）。
4. **他组的事不进本组记忆**（`rules/memory-model.md` §5）。
5. **对外报告发布前必过 preflight 闸**（`rules/publish-gate.md`）。
