---
name: lark-doc-safe-edit
description: 用 lark-cli 批量编辑飞书云文档（docx）时，防止 block 丢失/错位的安全规约。沉淀自 2026-06-26 述职文档第3/4/5节内容大范围丢失事故。
---

# 飞书文档安全编辑规约

> **事故教训（2026-06-26）**：用一连串 `block_replace` / `block_insert_after` 改写述职文档的「深度反思」6 个 `<li>` 和「文化融入」多个 `<p>` 后，复查发现这两节内容**大范围丢失**——只剩标题和首句。根因是**基于过期 block id 连续做 block 级操作**，叠加列表 block 重排，导致后续操作改到错误位置或连带删除。

## 〇、画流程图/框图必须用 whiteboard，不要用 `<pre lang="mermaid">`

> **事故教训（2026-06-26）**：在述职文档里用 `<pre lang="mermaid"><code>flowchart…</code></pre>` 画链路图，结果**全部渲染成一堆 code block 原文**，而非图。原因：`<pre>` 只是代码块、飞书不会把它渲染成图；且我还在节点标签里写了 `<br/>`，被当成真换行把 mermaid 源码打散，更彻底坏掉。

- **要图就用 `<whiteboard>`**：简单可控的图直接写自包含 SVG —— `<whiteboard type="svg"><svg …>…</svg></whiteboard>`，所见即所得、稳定渲染成真正的图。
- SVG 里**不要嵌 `<br/>`**；多行文字用多个 `<text>` 元素分行摆放（手算 x/y 坐标）。
- 复杂图才用 `<whiteboard type="blank">` 占位 + `lark-whiteboard` skill 写入。
- 观众要的是「结构清晰的图 + 关键文字」：图为主、配一句话定位即可，**禁止把流程写成一大段 ①②③④ 纯文字**塞进文档。
- ⚠️ **删块/替换块的两个深坑**（沉淀自 2026-06-26 反复误删事故）：
  1. **mermaid 块在 fetch XML 里不是 `<pre>`、而是 `<whiteboard>` 或 `<p>` 类型**，内容是 `flowchart…`；它和你自己插入的 SVG `<whiteboard>` 长得一样，**靠 id 区分、不能靠"是不是 whiteboard"判断**。删之前先 fetch 该块内容确认含 `flowchart`（是 mermaid）还是空/SVG（是你的图）。
  2. **`block_replace` 一个 `<whiteboard>` 块会失败**（degrade 2107 "Whiteboard content parse failed"）；要改用 `block_delete` 旧块 + `block_insert_after` 新块，且删前务必核对 id，删后立即 fetch 确认删对了。
- whiteboard SVG 内**禁用全角符号 `≤≥` 等**（曾触发 parse failed），用"≤"改写为"不超过/以内"等文字。

## 一、核心铁律：写后必复查（最重要）

- **每改完一节（不是每改完整篇），立即重新 fetch 该节，肉眼确认内容在、且正确。** 不要连改十几个 block 后才检查——错位会层层累积，最后无法定位是哪一步丢的。
- 复查用 `--scope section --start-block-id <该节标题id> --detail with-ids`，对比字符数与关键句。

## 二、block id 会失效，不可跨写操作复用

- `block_replace` / `block_delete` / `overwrite` 之后，**受影响范围的旧 block id 立即失效**；继续操作前**必须重新 fetch 拿新 id**。
- 尤其 `<ul>`/`<ol>` 里逐个 `block_replace` 多个 `<li>`：改完一个，整个列表的 id 可能重排，**旧 fetch 里其余 li 的 id 已不可信**。
- 不要一次 fetch、然后拿着这批 id 连续打 5+ 个 block 写操作。**一次写 → 一次 fetch → 再下一次写**。
- 🔴 **失效 id 上的写操作会返回 `ok:true` 假象，不报错**（沉淀自 2026-06-30，同一坑两次）：用过期 id 做 `block_replace`/`block_insert_after`，lark-cli 照样返回 success，但文档实际没变。**不能信返回值，必须写后 fetch 复查内容真的变了**。判断 id 是否新鲜：`block_replace` 一个块后，该块**自身 id 也会变**——想再在它后面 insert，必须先重新 fetch 拿它的新 id，绝不能用 replace 之前记下的 id。
- 🔴 **`str_replace` 删不掉"空块结构"，会返回 `ok:true` 但没删**（沉淀自 2026-06-30 删车衣块事故）：`str_replace` 只改**块内的行内文本**，删不掉块本身。删块级内容（整段 `<p>`、`<ul>`、空 `<li></li>`、空 cite 段）**必须用 `block_delete --block-id`**。
  - **正确删整块的姿势**：`docs +fetch --detail with-ids` 拿到目标块 id → `block_delete --block-id "id1,id2,id3"`（逗号分隔可批量）→ fetch 复查。
  - **反例**：想删一个【小节】时，用 `str_replace` 逐条把标题、bullet 文字替换成空字符串——结果文字没了但 `<b></b>`/`<ul><li></li></ul>`/空 cite 的**空壳标签全留下**，且 str_replace 对纯结构标签返回 ok:true 却无效，越删越乱。**删小节 = 先 fetch with-ids 定位该节所有块 id，一次 block_delete 批量删**。
- 🔴 **`block_replace --content` 必须用合法块标签，非法标签会静默吞掉整块（沉淀自 2026-07-01 双周报事故）**：把段落 `<p>` 块 replace 成 `<text>…</text>` —— `<text>` 不是 docx 合法块元素，lark-cli 返回 `ok:true`，但飞书**直接把该块删掉、内容丢失**（一次连删标题+3bullet 整段消失，靠对比才发现）。合法块标签：`<p>`、`<h1~h9>`、`<ul><li>`、`<ol><li>`、`<callout>`、`<whiteboard>`、`<img>`、`<table>`、`<hr/>` 等（见 lark-doc-xml.md）；行内强调用 `<b>`/`<i>` 包在 `<p>` 里。**block_replace/insert 后必须 fetch 复查该块内容真的在、且是预期文本**——ok:true 不等于成功。
  - **markdown 模式 str_replace 的 `**加粗**` 匹配不到 XML 里的 `<b>`**：正文粗体在 docx 里是 `<b>`，用 `--doc-format markdown --pattern "**xxx**"` 匹配会失败（返回 ok:true 但没改，又一个假成功）。改 bold 段落优先走 block_replace + `<p><b>…</b></p>`。

## 三、优先整块替换，少做碎片化逐条改

- 改写一整节的多个段落/列表项时，**优先 fetch 整节、在本地拼好完整新 XML，用一次 `block_replace`（替换该节容器）或先 `block_delete` 旧内容再 `block_insert_after` 一次性插入**，而不是对每个子 block 分别 replace。
- 碎片化逐条改 = 多次 id 失效窗口 = 高丢失风险。

## 四、大改前先备份原文

- 对正式文档（述职/周报/OKR）做大范围改写前，**先把整篇 fetch 成 markdown 存到工作区**（如 `/workspace/<doc>-backup-<日期>.md`），万一丢失可据此恢复。
- 改完与备份做一次 diff/字符数对比，节数、关键段落不应凭空减少。

## 五、用 revision-id 防协同覆盖

- 飞书文档是协同编辑。批量写入时，关注返回的 `revision_id` 是否连续递增；如中途有他人编辑导致跳变，停下重新 fetch，不要盲目继续。

## 自查清单（每次批量编辑飞书文档前后）
```
□ 改前：整篇已备份到工作区？
□ 每节改完：重新 fetch 该节，内容在且正确？
□ 没有跨写操作复用旧 block id？
□ 多段改写：用了整块替换而非碎片化逐条 replace？
□ 改后：与备份对比，节数/字数无异常减少？
```
