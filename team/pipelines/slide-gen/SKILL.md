---
name: slide-gen
description: 把"项目/进展"内容生成 slide 风格信息图 PNG（深蓝科技风，中文不乱码），用于嵌入飞书答辩/汇报文档。优先按内容自动选版式、并高亮核心指标。
triggers: [生成配图, 出图, 做张图, slide, 信息图, 配图, 可视化这块]
---

# Slide 生成 Skill

## 何时用
用户要给某个项目/进展/方案做一张"一目了然"的图，嵌进飞书文档（答辩、周报、方案）。

## 铁律
1. **不用 gpt-img-gen / 任何扩散模型画图**——它们会把中文渲染成乱码。
2. **用 HTML→无头 Chromium 渲染**：文字是真矢量字（Noto Sans CJK SC），中文 100% 正确、2K 清晰、秒级、免 token、版式完全可控。
3. 生成器：`output/make_slide.py`，输入一个 spec JSON，输出 `output/<name>.png`（2048×1152，16:9）。
   - 渲染命令内部已封装：`chromium --headless --no-sandbox --disable-gpu --window-size=2048,1152 --screenshot`。
   - 字体已装：`Noto Sans CJK SC`（`fc-list :lang=zh` 可验证）。

## 工作流（一个项目一张图）
1. 读该项目的 ledger + `memory/projects/_doc_index.md`，提炼内容。
2. 写 `output/specs/<name>.json`（见下 spec）。**先想"这块内容最适合哪种版式"，别千篇一律。**
3. `cd output && python3 make_slide.py specs/<name>.json`。
4. 自检图（`fs_read` Image 模式）——文字对不对、是否一眼抓住核心。
5. 插入飞书文档：`lark-cli docs +media-insert --doc <DOC> --as user --type image --file output/specs/<name>.png --selection-with-ellipsis "<该项目标题>" --align center --width 820`。
6. 文档对应文字精简为「核心进展 / 现状 / 计划」三条（详情已在图里）。

## 按内容选版式（不要千篇一律）
- **指标型**（有硬数据/达成率/对比数字）→ 顶部放 **highlight 指标带**（大数字+绿色）+ 卡片，核心数字必须最大最显眼。
- **流程/里程碑型**（有时间线、阶段推进）→ 用 `timeline` / `steps` 卡片，按时间或箭头推进。
- **分级/对比型**（适用性分级、A vs B、强/弱）→ 用 `rows`（带色块 tag：绿=强/达成、黄=关注、灰=不适用）。
- **方法/架构型**（链路、模块、原理）→ 用 `steps`（箭头流）或 2 列大卡讲清"做法→效果"。
- **内容很薄的项目**（未启动/阻塞/交叉引用）→ **不要硬凑 6 卡**：用 2–3 张大卡 + 一个醒目的状态标（如"阻塞：metric 不可用"红条），或干脆只留文字不配图。

## 高亮核心（一眼抓人）
- 每张图底部 `stats` 放 **3–4 个核心指标 pill**（key 灰、value 大号绿/青）——挑最能代表"完成/成果"的数字（如 2.6×、1:7.2、92%、786 scenario、80%+）。
- 卡片正文里关键数字/结论用 `<b>` 包成高亮色（青/绿）。
- 用一句 `conclusion` 横幅压轴，讲清"做成了什么 + 当前水位"。
- 完成项用绿色、进行中用青色、阻塞/缺口用黄/红——颜色即状态。

## spec JSON 格式
```json
{
 "name":"文件名",
 "cols":2,                       // 可选: 2列布局(卡片少时更大气); 默认3列
 "title":"标题",
 "subtitle":"一句话副标题/目标",
 "highlight":[["核心指标","2.6×"],["…","…"]],   // 可选: 顶部醒目指标带
 "cards":[
   {"t":"卡片标题","type":"bullets","items":["要点1","可含<b>数字</b>"]},
   {"t":"…","type":"lines","html":"<b>现状</b>：…<br><br><b>目标</b>：…"},
   {"t":"…","type":"rows","rows":[["强适用","g","撞车…"],["不适用","gr","待转区"]]},
   {"t":"…","type":"steps","intro":"根因…","steps":["v1…","v2…","v3…"]}
 ],
 "conclusion":"压轴结论：做成了什么 + 当前水位 + 下一步",
 "stats":[["验证车型","7 款"],["渲染比","1:7.2"]]
}
```
- 卡片类型：`bullets`(默认,带圆点) / `lines`(自由 HTML,讲"现状/目标/价值") / `rows`(色块 tag 分级) / `steps`(箭头流/迭代)。
- 色块 tag 取值：`g`绿(强/达成) `lg`浅绿(较) `y`黄(关注) `gr`灰(不适用) `b`青。

## 踩坑
- 飞书里 `<cite doc-id>` 空标签会被剥掉 → 文档内嵌文档链接要用 `<a href="https://xiaopeng.feishu.cn/docx/<token>">名</a>`。
- `block_replace` 在普通正文 li 安全；**在表格单元格内会清空块**，表格内改用 `block_insert_after` + `block_delete`。
- media-insert 用 `--selection-with-ellipsis "唯一文本"` 定位到目标块后插入。
- 改图：改 `output/specs/<name>.json` 重渲染即可（秒级），再删旧图块、重 insert。

## 模板源
- 生成器：`output/make_slide.py`
- 既有 spec 样例：`output/specs/*.json`（14 个项目）
