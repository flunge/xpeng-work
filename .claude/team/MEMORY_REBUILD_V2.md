# 数字分身记忆工程 · 重建 v2（2026-08-03）

## 问题根因（对照症状）

| 症状 | 根因 |
|---|---|
| 已完成事项（慢速模式）记忆仍是 PENDING | 「【更新记忆】窗口增量型」只抓新进展，**无状态机**：开口项的"关闭判定"无人负责 |
| 最新内容非最新 | 临时区/主表/作战表/内部索引多头写，**真源裁决规则**不彻底 |
| 记忆混乱叠加、数字存疑 | 同一事实多处重复写、互不引用；数字无唯一归属 |
| 分身不忠实 | 记忆中是"被选择的摘要"，非"你获取过的一切"，无法回答 L0 检索类问题 |

## 三层架构（已建）

- **L0 原始层** = 飞书真源（docx 本体），不进 repo。
- **L1 Episode 事件流** = Base `NkIZb7eU7azZIEsegJ7cl2bfnUd` 表「Episode事件流」：每条事件一行（时间/来源类型/来源定位 token/涉及项目/关键数字/动作）。→ 已种 23 条（会议纪要机器人群 7/16–7/31 全量 docx token）。增量脚本：`team/scripts/seed_episode.py` 模式（每日从机器人转群列表 + 日报/周报重按 revision 垫文件差入格式）。
- **L2 追踪闭环** = 同 Base 表「承诺追踪」（人机承诺）+ 表「开口项追踪」（项目 pending/风险/遗留，33 条，单状态机 open→suspected-close→closed，关闭必填来源）。入库脚本 `team/scripts/harvest_open_items.py`（ITEMS 为策展清单）。
- **L3 摘要层** = 现有项目 ledger/作战表/人物档案，**只存状态与判断**，事件一律挂 L1/L2。

## 数字治理规则

1. 开口项是**唯一待办真源**：ledger 中的 🔴🟡 必须同步进入「开口项追踪」，ledger 里保留叙述口径。
2. 状态转移**必须有来源**：suspected-close → closed 需逐字稿/纪要/日报断言；无可判来源则保留 open 并在风险哨兵中浮现。
3. 数字唯一归属：叙事性数字只存在于 Episode（关键数字字段）；ledger/报告引用 episode 行。
4. 慢速模式案例（2026-08-03 修正）作为范式：7/16 判定 PENDING（等实车答辩）→ 实际 7/21 已恢复推进，记忆未捕捉出入 → 以逐字稿 token 链（Rxbgd…/Qrbdd…/VzlV…）修正并入库。
5. **延续性铁律（2026-08-03 补，用户口径）**：项目跨多季度运行，**ledger「三、持续推进」=人类可读全量历史**，永久保留、不削减；**Episode = 从 ledger 派生的机读索引**（backfill 幂等反推）。权威在 L0 飞书原文，ledger 与 Episode 都是派生物；新事件单边走 ledger → L1，Episode 不回写 ledger。

## 日常流（目标态）

- 每日 09:00 `risk_sentinel.py --push`（承诺逾期）+ （待加）开口项追踪中 suspected-close/stale 条目的提示推送。
- 【更新记忆】= 消化 L0 新料 → 落 L1 → 改 L2 状态 → 只改 L3 的"当前状态"。
- 报告写作 = `memory_query.py` 证据包（L1 数字 + L2 状态）+ `check_report.py --evidence` 数字闸。

## 工具链状态（2026-08-03 核盘）

- `team/scripts/harvest_open_items.py`：开口项策展清单 + 入库。
- `team/scripts/seed_episode.py`：Episode 首批种子（模板=可跑模式）。
- ✅ Episode 每日增量 ingestion：`team/scripts/episode_ingest.py`（挂 daily-sync 22:00）。
- ✅ risk_sentinel 接入开口项追踪（stale 检测：最近核查日期>N 天）+ **项目级停摆哨兵**。
- ✅ **backfill 范式**：`team/scripts/backfill_episode_from_ledger.py`+`backfill_all.py` — 从 ledger「持续进展」逆推 L1，幂等键 `ledger://`，防重跑；挂 larkdocs_sync 23:00 后自动跑，storyline W32 不缺失。
- ✅ 强制开口项闸：`team/scripts/sync_open_items_from_ledger.py [--apply]`。
- ✅ Storyline：`team/scripts/storyline_gen.py`，周五 20:00 生成、周六李坤 DM 审；W31 已入 5 张；`_ALIASES` 交并：RC路线≠RC路线SIL验证 拆分不交并。
- ✅ 文档库 RAG：`team/scripts/larkdocs_sync.py`（23:00 镜像）+ `doc_rag.py`（检索）+ xai extension `~/.pi/agent/extensions/lark-rag.ts`（`docs_search`/`docs_locate` tool）。

## 附：Storyline主线卡设计（P2，已建表）

**表**：`Storyline主线卡` @ 追踪Base（NkIZb7eU7azZIEsegJ7cl2bfnUd）。

**字段**：项目 / 周期（W##）/ ①定位一句话 / ②本周发生了什么（必引 Episode record_id）/ ③数字与证据（引 Episode 关键数字）/ ④状态与风险（引开口项 record_id）/ ⑤下周预判 / 生成依据EpisodeIDs / 人工确认（已确认|待确认）/ 生成时间。

**生产流程（v1 人审半自动）**：
1. 每周五 20:00：命令生成器拉取当周 Week element（项目级），用 `memory_query.py` 恩证据包集会产出候选卡；（自动化可接 xai -p ）
2. 周六：李坤人审（IM 推送 URL），点掉错误、落到 ledger 可读界面；
3. ledger 引用 storyline，不在 ledger 重复写叙事。

**与 ledger 分工**：故事性事件/数字只在 Episode；Suspension 类判断在开口项；ledger 只在「当前状态」读 storyline，不再手写 叙述。
