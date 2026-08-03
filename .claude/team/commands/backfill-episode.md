# 手册：【记忆深挖回填】命令

当【更新记忆】写完 ledger 后，把 ledger 里「三、持续进展」的时间线**逆推**回到
Base「Episode事件流」（L1）。
这是**强制的**——你不跑本命令，storyline 主线卡就看不到细颗粒度数字/叙事。

## 用法

```bash
# 1. 不缺新事件时（幂等，跳过）
python3 team/scripts/backfill_all.py

# 2. 新增某个项目 → 只补该项目
python3 team/scripts/backfill_episode_from_ledger.py \
  --ledger memory/larkdocs/team/projects/<项目>.md \
  --project <名称>

# 3. 只想看不写库（手动验收前）
python3 team/scripts/backfill_episode_from_ledger.py \
  ... --dry-run
```

## 幂等键 + 排除原则

| 键 | 会重复？ |
|---|---|
| `ledger://<token>#<date>#<cellhash>` | 同 cell 同 hash 重复跑 |
| `docx:<token>` | 同 doc token 重复跑 |
| 本 cell 拆开自「会议纪要/作战表/其他来源」多个格 | **会重复**（同一个 cell 被拆成 多行 新米） |

cell 拆开是为了把「作战表进展 + 会议纪要 + 其他来源」各成为独立事件，**代价是
同一 cell 可能产生多行**，只要这三类部分存在不重复，多行是**正常复用**。
本命令会先拉 Episode 全部既有 `来源定位`（前 500 条），幂等匹配，你里面净重
写库；**你别手动改** `来源定位` 列格式，改了就会导致重复入。

## 出手原则

1. **每个**项目 ledger 进入【更新记忆】流程后，都要跑一次 `--project <该项目>`
2. 周五 `larkdocs_sync.py` LaunchAgent 跑完会自动跑 `backfill_all.py` 全项目兜底
3. 周五 `storyline_gen.py` LaunchAgent 会先自查 Episode，发现为零会自己触发
   backfill 补米，再生成主线卡——**所以 W32 不会漏**
4. WM-内部探索 这种**没有「三、持续进展」**的研究型 ledger 自动跳过，不算缺

## 里程碑型 vs 讨论型

- 「持续进展表」是里程碑型 ✅ 喂 Episode
- 「讨论/悬念」型是讨论型 ❌ 不喂 Episode，只记在 ledger（靠 Episode 本身配开
  口项「项目停摆哨兵」兜底）

## 手动补救脚本（诗痕）

```bash
python3 team/scripts/sync_open_items_from_ledger.py --apply   # 🔴🟡 → 开口项 Base
```
