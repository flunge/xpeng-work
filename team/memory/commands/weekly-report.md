# 命令：周报 / 双周报

> 瘦身入口。触发词与执行细节以 skill 为准，此处只给"用哪个 skill + 窗口 + 闸"的导航。

## 周报（给高炳涛）
- 触发："周报 / 生成周报 / 本周汇报"。
- 窗口：**上周五 00:00 → 本周五 12:00**（2026-07-09 起随算法组周会周五出；未到周五则用当前时间）。
- 执行 skill：`.claude/skills/weekly-report/SKILL.md`（含数据源三步铁则、写前强制清单 Step 0a–0d、四件套结构、六类禁区、ASR 术语清洗、4 找、三层法）。
- 数据源 = 两份日报 + 全部会议纪要/逐字稿 + 嵌套文档(含贴图) + IM/chat-log/组员 p2p，采集纪律见 `rules/sourcing.md`。
- 结构：复用作战表当前 5 线（车型泛化/闭环+HIL/生产链路/Agent/预研），每线「进展 / 现状(与目标 GAP) / 风险」。
- 存放：文件夹 `JIb3ftcJclQ1DvdHFkIc6gxNnOb`，标题 `周报 YYYY-MM-DD`（本周五日期）。
- **发布前必过闸**：`rules/publish-gate.md`（preflight --audience boss）。

## 双周报（给刘先明，经高炳涛审核，双周五）
- 执行 skill：`.claude/skills/lark-workflow-gic-report/SKILL.md` + 风格 `memory/gic-report-style.md`。
- 与周报区别：不提组员名、去内部代号(V3C/Holmes)、突出算法方法论；存双周会文件夹 `OGszfSaV4lGkvCdtWuYcQ4p2nke`。
- 发布前 `preflight --audience xianming`。
