# 仿真部 team · 技能与工具用法备忘

> 低频但重要：列出 team 下自研脚本/扩展的调用时机，避免重复造轮子或被遗忘。

## 记忆系统（L0 ↑L3）
- **L0 真源**：飞书 docx + Base；本地 `team/memory/larkdocs/` 只是只读缓存（每天 23:00 来自 `larkdocs_sync.py` revision 增量）
- **L1 事件流**：`Base Episode事件流`（会议逐字 + 日报作战表 + IM），幂等键 = `ledger://{token}#{date}#{cellhash}` 或 `docx:{token}`
- **L2 追踪**：`Base 开口项追踪`（33 条真实开口，含 RC 人员风险 / F57 补充）
- **L3 摘要**：`Base Storyline主线卡`（周五 20:00 生成待确认；项目状态、待办、数字、来源）

## 关键脚本调用时机
| 场景 | 命令 |
|---|---|
| 新增/更新 ledger → 补事件流 | `python3 team/scripts/backfill_episode_from_ledger.py --ledger memory/larkdocs/team/projects/<项目>.md --project <名称>` |
| 🔴🟡 行强制进开口项 | `python3 team/scripts/sync_open_items_from_ledger.py --apply` |
| 周报证据包 | `python3 team/scripts/memory_query.py --start <周一> --end <周日> --out /tmp/evidence_W<N>.json` |
| 生成主线卡 | `python3 team/scripts/storyline_gen.py --date <周五>` |
| 自动闸 | `cron/install.sh` 之后会自动跑：larkdocs_sync 23:00、daily-sync 22:00、risk-push 09:00、storyline-gen 五 20:00 |

## 项目白名单 / 别名归并
见 `team/scripts/storyline_gen.py` 顶部 `_ALIASES` / `_NON_PROJECT`；
`_ALIASES` 漏的别名会导致 storyline 卡找不到 ledger 状态，要靠**非项目标签跳过建卡**的提示发现。
