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

## 4. ③ 正文改措辞 = 同步改图
凡清理正文（去名字/删口头话/换数据/去黑话）→ 必到 gen_svg_infographic.py 同 topic 改同一处、重跑渲染闸。判据：任何内容规则，问"图里有没有同一句话？"

## 5. 规则拦不住 → 变成能跑的闸
反复被抓不是"不知道规则"，是"知道却没执行、拿跑通冒充做对"。**新踩的坑先问"能不能加进 check_report.py 的正则 / 渲染闸的断言"，能就加脚本，不能才写文字规则。**

> 报告的**写作内容与风格**规范（正式文档/汇报叙事/去AI腔/私下话术/ASR表）见 memory/rules/report-writing.md；周报专属（四件套/本组only/六类禁区/三层法/写前清单）详见 `.claude/skills/weekly-report/SKILL.md`（周报）与 `memory/gic-report-style.md`（GIC 双周报）。
