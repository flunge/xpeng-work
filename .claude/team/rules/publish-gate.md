# 铁律 · 发布前闸（publish-gate）

> 单一事实源。所有对外报告（周报/双周报/GIC）宣布"完成"前必过的闸。

## 0. 交付前必须全量自审，禁止"逐点反应式交付"
一份报告改 10 轮的根因＝每轮只查用户刚指出的那处、改完就说"完成"，让用户当校验器。**宣布"完成"前必须把所有维度自查一遍。** 判据：准备说"完成"时问自己"我是只验了刚被指出那点，还是闸全绿 + 判断项都回源了？"

## 1. ⭐ 唯一入口：preflight
宣布"完成"前必跑：
```
python3 scripts/preflight.py <doc_token> --audience xianming|boss
```
一条命令跑完 ①②闸 + 配图齐全 + 名字泄漏，并列出脚本兜不住的判断类逐条人工过。**preflight 非 0、或人工项没逐条确认，禁止对用户说"完成/好了/搞定"。**

## 2. ① 溯源闸（check_report.py）
```
python3 scripts/check_report.py <doc_token> --audience xianming（双周报）| boss（周报）
```
抓：排除项 / 受众违规 / 内部实验代号(V3C/+8dB/Holmes) / 口头话(预估/测试中/省Nmin) / 黑话 / 重复 / 溯源泄漏(token、"来源："、会议指代写进正文)。**非空即不许发。** 它抓不到的（数字对不对、是否本周）靠 sourcing.md 第 3 条逐条回源兜。

## 3. ② 渲染闸（gen_svg_infographic.py）
生成图时自动几何自检文字是否溢出卡片，越界 `exit 3` 拒绝出图（不靠肉眼看缩略图）。报错就修坐标/收窄 max_px/精简文案，绿了才 `block_replace` 进文档。
**🔴 可编辑性——必须用原生画板节点、别塞 SVG（2026-07-13 血泪）**：飞书 `<whiteboard type="svg">` 会把 SVG 里**每段文字（每个 text run）拆成一个独立文本框**，用户手改时框是碎的，改不动——无论 tspan / 绝对 y / 相对 dy / 每卡一个 `<text>` 都绕不开（拆分在导入器按 run 解析那步）。**正解**：`scripts/push_whiteboard_native.py <topicN> <whiteboard_token>`——形状/标题/KPI 走 `SVG→whiteboard-cli --to openapi`，**每张卡正文合成一个原生 `text_shape`、text 字段用真换行 `\n`**（一个可编辑大文本框、内部换行），再 `lark-cli whiteboard +update --input_format raw --overwrite` 推到画板 token（token 从 `docs +fetch` 的 `<whiteboard token="...">` 取）。验证：`whiteboard +query --output_as image --overwrite` 导出 PNG 自查（导出偶发占位图=重试，非坏）。代价：正文框内颜色统一（丢每条 mark 的高亮色），换来可编辑——用户已拍板要可编辑。
**去人名闸（2026-07-13）**：出图前扫 SVG 是否含组员/领导姓名（`_NAMES` 黑名单），命中 `exit 4` 拒绝——因为溯源闸只扫正文 markdown、扫不到 whiteboard SVG 里的字，图内人名/内部话术("XX定：…")曾漏网。新增组员名要同步进 `_NAMES`（`team_org` 内部架构图豁免）。
**画布溢出闸（2026-07-13）**：所有文字包围盒（KPI/标题/bullet 全登记进 `_ALLBOXES`）必须落在图像画布 `W×H` 内，越界 `exit 5`——原渲染闸只查"卡内"、查不到溢出画布边界的字。
**叠框回归闸（2026-07-13）**：飞书 whiteboard 把每个 `<text>` 导成一个可编辑文本框，框太多则手动改要点很多次。规则：`_wbullets` 把**整张卡的所有 bullet 合并成一个 `<text>`**（每行/每个 mark 都是其中的 `<tspan>`），即"一张卡=一个大文本框、内部换行"。闸扫 SVG 里"无 tspan 的独立 `<text>` 左对齐且纵向间距≈行高"的信号，命中 `exit 6`。改 `_wbullets` 时勿退回按行/按条 `_txt` 拆成多个 `<text>`。

## 3b. 双周报模块配图齐全（2026-07-13）
双周报发布前检查：**每个 Topic/模块都有一张细节结构图**（见 report-writing §7），缺图的模块不算完成。preflight 的配图齐全项覆盖此检查。
- **🔴 作战表贴图机器闸**：`python3 scripts/check_report.py <report_token> --audience boss|xianming --wartable SBUYwm8Lri9aJ6kmexFcBAuGnlh --weeks W28[,W29]` 统计作战表窗口贴图「已读 N/总数」、未读逐张列为拦截项（exit 2）；已读记录维护在 `team/tmp/.img-read-log`（读一张 append 一行 src token）。未读清零才准发。
- **🔴 窗口防串闸（carryover，2026-07-13）**：报告进展**只写窗口内 delta**，禁止从 ledger/记忆直接捞（ledger 含全 history，会把旧工作当本期）。做法：① 先从作战表窗口列 + 各文档 revision-diff(窗口内) 抽一份"本窗口 delta 清单"，只从清单写进展；② 每条带数字/结论的进展**溯源确认其日期落在窗口内**，旧结论只作背景不进"进展"；③ 发布前跑 `check_report.py <本期> --prev <上期报告token>`，揪出与上期高度重合的照搬内容(标"疑似旧内容照搬")。教训：metric 分级(5/19)、G02 侧前标定(6/30)、极速参数精简(6/30) 曾被当本期进展混入。

## 3c. 🔴 双周报图的数据源是脚本，不是 SVG 文件（2026-07-15 血泪）
双周报四张图的**唯一数据源＝`scripts/gen_svg_infographic.py` 里 `topic1()~topic4()` 的硬编码 bullet 文本**。`team/tmp/biweekly_topicN.svg` 只是脚本的**输出产物**——手改这些 .svg 文件毫无意义，因为 `preflight.py`（及任何人再跑渲染闸）会用脚本数据**重新生成、覆盖**你的手改。
- **正确改图数据**：改 `gen_svg_infographic.py` 里对应 `topicN()` 的 `_wbullets`/`_kpi` 文本 → 跑 `preflight.py`（自动重生成 SVG + 过渲染/溢出/人名/叠框闸）→ 再 `lark-cli docs +whiteboard-update --input_format svg --overwrite --source @...svg` 推四个画板 token。这样**脚本＝本地 SVG＝飞书画板**三者一致。
- **反例（别再犯）**：直接 Read/Edit `biweekly_topicN.svg` 改文字→推画板，看似成功，但下次 preflight 一跑就回滚，且脚本数据仍是旧的（埋雷）。判据：要改图内任何字，先问"我改的是 `gen_svg_infographic.py` 还是 .svg 产物？"改产物＝白改。

## 4. ③ 正文改措辞 = 同步改图
凡清理正文（去名字/删口头话/换数据/去黑话）→ 必到 gen_svg_infographic.py 同 topic 改同一处、重跑渲染闸。判据：任何内容规则，问"图里有没有同一句话？"

## 5. 规则拦不住 → 变成能跑的闸
反复被抓不是"不知道规则"，是"知道却没执行、拿跑通冒充做对"。**新踩的坑先问"能不能加进 check_report.py 的正则 / 渲染闸的断言"，能就加脚本，不能才写文字规则。**

> 报告的**写作内容与风格**规范（正式文档/汇报叙事/去AI腔/私下话术/ASR表）见 .claude/team/rules/report-writing.md；周报专属（四件套/本组only/六类禁区/三层法/写前清单）详见 `.claude/skills/weekly-report/SKILL.md`（周报）与 `.claude/team/rules/gic-report-style.md`（GIC 双周报）。

**可编辑性 vs 显示效果——用户最终方案（2026-07-14，方案 C）：双周报图用**原生画板节点**（`scripts/push_whiteboard_native.py <topicN> <当前token>`）——形状/卡/KPI/标题走 SVG→whiteboard-cli openapi；**每条 bullet 拆成两个节点：① 彩色加粗「标签」独立小框（保留分级颜色）② 后面整段内容合成一个多行可编辑 text_shape（
 换行）**。既保留标签彩色格式、内容又是一个可编辑框。⚠️ 推送前必须现取 token（block_replace/新建会换 token，先 docs +fetch 拿 `<whiteboard token=...>`）；推完 `whiteboard +query --output_as image --overwrite` 导 PNG 自查。纯 SVG 塞 whiteboard 会把每行拆成独立小框，弃用。
