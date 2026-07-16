---
name: lark-workflow-gic-report
version: 2.0.0
description: "GIC双周会汇报板块生成。注意：参考风格必须读 /workspace/.claude/team/rules/gic-report-style.md，不要用邓爽的部门报告风格。"
triggers:
  - 双周会
  - GIC双周会
  - 双周报
  - 生成汇报
  - gic report
---

# GIC双周报工作流

**首先：读 /workspace/.claude/team/rules/gic-report-style.md，理解李坤的GIC汇报风格**

## 🔴 存放文件夹：双周报固定放双周会文件夹（2026-06-30 沉淀，放错过一次）

**所有 GIC 双周报必须放在双周会专用文件夹**：`https://xiaopeng.feishu.cn/drive/folder/OGszfSaV4lGkvCdtWuYcQ4p2nke`（历史双周报都在这，如「仿真双周会 20260618 草稿」「仿真算法组双周进展 20260605」）。

- 创建新双周报 → `docs +create` 后立刻 `lark-cli drive +move --file-token <token> --type docx --folder-token OGszfSaV4lGkvCdtWuYcQ4p2nke`，或直接在该文件夹下建。
- ⚠️ **别和周报混放**：周报文件夹是 `JIb3ftcJclQ1DvdHFkIc6gxNnOb`（另一个），双周报 ≠ 周报，不要放进周报文件夹。反例（2026-06-30）：双周报误建在周报文件夹 `JIb3f...`，被用户发现"你写哪儿了"，事后 `drive +move` 挪回 `OGszf...`。
- 写完/移动后用 `drive files list --folder-token OGszf...` 复查，确认在正确文件夹。

## 🔴 团队情况段：组员名单的权威来源（2026-06-30 沉淀）

**「团队情况」段的在岗组员，必须从组员群 `oc_bb2cf097e2d3efc34a4bc37ebd9225d9` 实时拉取，不靠记忆、不靠 `_index.md`（会过时）。**

```bash
lark-cli api GET "/open-apis/im/v1/chats/oc_bb2cf097e2d3efc34a4bc37ebd9225d9/members" --params '{"member_id_type":"open_id","page_size":"100"}'
```

- 群成员 = 当前在岗组员名单（含李坤自己）
- **新入职的一律是实习生**（P0），除非另有明确说明
- 拿到名单后与 `people/_index.md` 比对，找出新增成员补进画像；产假等非在岗状态从 `_index.md` 的 status 字段判断
- 人数/构成只写群名单能支撑的，不编造 P 级分布
- 🔴🔴 **架构图副标题：只写「客观身份」，不写脑补关系、也不写你我沟通信息（2026-07-01 连被抓两次：先脑补"平级"、又把"不汇报"写进去）**：
  - ❌ **不推断关系**：用户说"和我并列"是**图上摆放位置**、"不汇报给我"是**汇报关系**，都**不等于职级平级**——我却写成"平级(不汇报)"，编造了不知道的 P 级。凡"平级/上下级"这类关系词，用户没明说职级就绝不写。
  - ❌ **沟通信息不进图**："刘开拓不汇报给我"是**用户对我说的背景交代**，属"解释给你我之间"的话，跟「删沟通用括注」同类——**不写进给外部看的图**。图上"不与我连线"本身已表达了不汇报，无需标注。
  - ✅ **只留客观身份**：如"生产组 PM""P6·Fixer"这种岗位/职级事实。判据：副标题每个词，是**看图的外部人需要的客观信息**，还是**你我沟通的背景/我推断的关系**？后两者删。
  - "新入职"标绿以用户点名 + HR 群为准，别自己判断谁是新人。

## 🔴 Topic 顺序 = 业务优先级，跟老板最新定调走（2026-07-01 沉淀）

**双周报 Topic 顺序不是技术分类顺序，是业务优先级顺序**——以老板（高炳涛）最新定调为准，最高优先的放 Topic 1、标红角标（如「7 月核心任务」）。定调来源常在**老板与李坤私聊 / 群 `oc_e18d1d68d26c17f45f3ce3492e5143fe`**，写报告前必查。
- 2026-07-01 定调（示例）：① 车型泛化（70% 精力、开环>闭环）② 闭环仿真+HIL（让业务用起来）③ 极速模式（做成产品非 demo）④ Agent（7 月全上线产品化）。据此重排了 Topic + 4 主线表述 + Q3 OKR KR 优先级标注（🥇P0/🥈P1…）+ 7 月目标。
- 优先级变了要**三处同步改**：双周报 Topic 顺序、Q3 OKR（`M8iUwlfAhi190Sk2xIwcHLAWn8f`，O 不动、KR 加优先级角标 + 顶部 callout）、7 月目标（`SBUYwm8...` 第一部分按 4 主线重写 + 最高优先项做「周拆解到人」表 + 标 W27 gap）。
- 从属技术项要**明确挂靠关系**：如 Fixer 渲染 = 车型泛化的"生产提速手段"、CLIP-IQA = 车型泛化的"图像质量卡口"，不再单列为 SIL。

## 🔴 受众导向：刘先明关注算法（2026-06-30 沉淀）

**双周报汇报对象刘先明关注算法**。Topic 内容要**突出本组这两周的技术/算法迭代细节**：
- 多写算法迭代：模型架构变化、训练策略、量化/蒸馏方案、效率比/PSNR/准确率等指标的逐版演进
- 例：NVFixer V3C/V3D 架构、difix MIG 量化路径、LoRA 微调步数对比、Agent prompt 迭代与准确率爬坡——这类算法细节要展开，不要只写"上线了/完成了"
- 工程/运营类（节点部署、流程上线）可压缩，给算法让位
- 仍遵守"只写本组工作、数字可溯源、不报喜不报忧"

**CRITICAL — 历史教训（2026-06-11 踩坑记录）**：
1. ❌ 我先把部门报告（邓爽）当作李坤的风格来学——错了
2. ❌ 我把周报风格当GIC风格——错了，周报给高炳涛，GIC双周报给刘先明，风格不同
3. ❌ 我套模板（计划→差距→价值→进展→风险）——李坤的GIC风格是极简bullet配图
4. ❌ 我生成长篇H2段落——李坤的GIC每节3-5个bullet+1张图
5. ❌ 我没看图——报告中的图都是GPT-Image-2生成的，每节必有

**正确做法**：每节 = title + `<cite>`标签 + whiteboard + 2-5个bullet + 1张GPT-Image-2图

**CRITICAL — 开始前 MUST 先用 Read 工具读取 [`../lark-shared/SKILL.md`](../lark-shared/SKILL.md)，其中包含认证、权限处理**

## 前置条件

仅支持 **user 身份**。执行前需确保已授权以下 scope：

```bash
lark-cli auth login --scope "search:message contact:user.basic_profile:readonly"
```

## 执行方式

```javascript
Workflow({
  scriptPath: 'pipelines/gic-report.js',
  args: {
    today: '2026-06-11',
    targetDoc: 'https://xiaopeng.feishu.cn/docx/xxxx'
  }
})
```

## 报告格式（GIC双周报风格）

**拒绝模板**。每节结构跟着内容走，但必须包含：

1. **标题 + `<cite>李坤</cite>`** — 标题后@作者
2. **`<whiteboard>`** — 可视化讨论概览
3. **2-5个bullet** — 不写段落，不用H2子节
4. **1张GPT-Image-2图** — 数据对比/进度/KPI可视化

### 结构选择（根据内容选一种，不要都用）：
- 目标→现状→挑战（规划型，如HIL）
- 背景→优势→现状→挑战（分析型，如车型泛化）
- 概述→分项→风险（进展型）

### 语言规则
- 🔴🔴 **图承载丰富内容、文字只写要点（2026-07-01 沉淀，反复漏）**：详细展开、数据、方法论都放进 SVG 图里；正文每条 bullet **只写一句要点、不超过 ~40 字**，禁止出现 100+ 字的大段完整句子。图和文字分工——图详、字简。判据：每条正文拎出来看，是不是"一句话说清一个点"？是长段落就砍到要点。（反例 2026-07-01：正文每条都写成 100-219 字完整句、把图里已有的细节又在文字里铺一遍。）
- 短句子，像在说话
- "当前有两台台架，预期达到目标需要至少5台" —— 不是"差距：3台"
- 不写"计划：""当前：""差距：" 这种模板前缀
- bullet开头的词就是内容本身

## 🔴 配图：原生 SVG 信息图 → whiteboard，全自动（2026-06-30 打通，取代 GPT-Image-2）

**GPT-Image-2 走不通**（`pipelines/media_key.txt` 的 SoCheap key 只挂 7 个 Claude 文本模型 + veo 视频，无任何图像模型，实测所有 image model 报 "media model is not supported"）。**不要再试图调图像 API、不要再走"占位符+手动 /image"半自动老路**。

**新方法（已验证、全自动、不烧钱、不依赖任何图像 key）**：写 SVG 信息图 → 飞书 `<whiteboard type="svg">` 直接吃、自动渲染成真图。

**工具**：`scripts/gen_svg_infographic.py` —— 原生 SVG 生成器（深色科技风，对齐李坤述职文档那套：标题条 + 分栏卡片 + KPI 数字块 + 分色 bullet ✓蓝/△橙/→强调/·灰）。每个 Topic 一个函数返回自包含 SVG。

**完整流程**：
1. **数据对齐**：图里的数字/结论必须与清洗后正文一致——先跑 `check_report.py` 让正文过关，再照正文写图，禁止图里出现正文已删的旧数据/排除项/脑补。
2. **生成 SVG**：`python3 scripts/gen_svg_infographic.py topicN` → 落到 `team/tmp/biweekly_topicN.svg`。
3. **本地肉眼验收**（可选但推荐）：`chromium --headless --no-sandbox --screenshot=<png> --window-size=1024,576 <一个 img 指向 svg 的 html>`，Read PNG 确认排版不溢出、中文正常。
4. **插入文档**：把 SVG 包成 `<whiteboard type="svg">…</whiteboard>` 写进 `.xml` 文件（**用 `@file` 喂 `--content`，别内联大段**），`docs +update --command block_insert_after --block-id <占位块>` 插在对应 Topic 后。
5. **清占位**：`block_delete` 删掉 `【此处贴图】` 占位块 + 文末配图清单段（批量传逗号分隔 id）。
6. **验收**：re-fetch 确认 whiteboard 块数 = Topic 数、无残留占位；飞书会把内联 `<svg>` 吸收成 whiteboard token（fetch 回来看到的是 `<whiteboard token=...>` 而非 `<svg>`，文本内容仍在——这是**成功**渲染，不是坏了）。

**satori（HTML→SVG）踩坑**：装了 `satori`+`satori-html` 也能用，但它要求**每个多子节点 div 都显式 `display:flex`**、不认 `background` 简写渐变（要 `backgroundImage`），中文要喂**单体 ttf**（`.ttc` 不吃，用 `fontTools` 从 `NotoSansCJK-Bold.ttc` 提取 SC 面存 `scripts/fonts/`）。**结论：直接手写原生 SVG（gen_svg_infographic.py）比 satori 省心，首选它。**

**SVG 硬约束**（飞书 whiteboard）：自包含、无 `foreignObject`、无 `<br/>`（多行用多个 `<text>` 手算坐标）、禁全角 `≤≥`（用"不超过/以内"文字）。字体 `font-family` 写 `Noto Sans CJK SC, PingFang SC, Microsoft YaHei, sans-serif`。
- 🔴🔴 **原生 SVG 文字不自动折行——长文本必溢出，必须用 `_wbullets`/`_wrap` 按卡片宽度折行（2026-07-01 连踩：叠字+溢出）**。绝不用裸 `_txt`/`_bullets` 塞长句（超过卡片宽就冲出边界、和相邻文字叠）。`_wbullets(x, y, max_px, items)` 按 `max_px`（=卡片宽-左右内边距）折行；`_kpi` 的数字按宽自适应字号、label 自动折行。想让"图丰富"就多写内容 + 折行，不是把长句硬塞一行。
- 🔴 **卡片标题↔正文间距**：`_card` 标题在 +36、分隔线在 +50——正文 bullet 起始 y 必须 ≥ 卡片 y+70（别用 +52，会紧贴分隔线，2026-07-01 被抓）。
- 🔴🔴 **生成后必须放大逐块查（不是看缩略图说 OK）**：`chromium --headless --screenshot` 出全尺寸 PNG，再对每个卡片**裁剪放大**看：① 文字有没有冲出卡片右/下边界 ② 有没有两段文字叠在一起 ③ 标题和首行间距。缩略图看不出溢出/叠字——我就是只看缩略图说"OK"被用户抓了"这个你都不检查？"。
- 🔴🔴 **横向溢出比纵向更隐蔽，必须画卡片边界框核对（2026-07-01 又踩：Topic1 左卡 ①②③ 行冲出右边界）**：`_tw` 是**估算**像素宽，对全角标点（「」；↔·、）系统性**低估**——所以"数值算下来没超"不等于"渲染时没超"，肉眼看整图也容易漏。验收长文本卡时用 PIL 在截图上按卡片坐标 `ImageDraw.rectangle` 画出**右/下边界红框**再裁剪放大，看文字是否贴边/越线。修法：把 `_wbullets` 的 `max_px` 再收窄（如 `lw-60` 而非 `lw-44`）多留右边距——纵向通常有余量，宁可多折一行也不横向顶格。**别信"行末 x 估算 < 边界"就放行**。
- 🔴 **文案里的引号用「」，禁用直双引号 `"…"`**（2026-07-01 已踩 ≥2 次）：bullet 文案是 Python 字符串，内嵌 `"多车共性"`/`"主辅路跟导航"` 会提前终止字符串、语法断裂。**改完先 `python3 -c "import ast;ast.parse(open(...).read())"` 验语法**，再 grep 关键词确认 svg 真的变了（语法错时 gen 静默用旧 svg 不报错）。

**🔴 别再试 PNG 图片直插——lark-cli 上绑不稳（2026-07-01 实测）**：用户可能嫌 whiteboard 是"画板壳"、要求"做成图片"。**PNG 直插这条路在当前 lark-cli 走不通**：`docs +media-upload` 能拿到 file_token，但 `block_insert_after`/`block_replace` 插 `<img src="token">` 时飞书**始终绑定失败、显示占位图 test.jpg**（无 src 的 img 块还会被静默丢弃）。反复删+重插+block_replace 都无效，纯浪费。**认准 whiteboard-SVG**——它不是可编辑画板，飞书就是当一张静态图渲染展示；"丑"是设计问题（去 gen_svg_infographic.py 改卡片/KPI/配色即可），不是格式问题。真要脱离 whiteboard 只剩"PNG 传云空间生成公网 URL + `<img src=url>`"一条，但依赖外链、图存云盘，非必要不用。

**视觉设计要点**（2026-07-01 升级，避免"扁平丑"）：卡片用竖向渐变 `cardgrad` + 左侧强调竖条 + 标题下分隔线；KPI 块左侧加高亮竖条、大号数字（25px）；顶部标题区下加整条分隔线；配色沉稳（卡面 #1e3a63→#152c4d）。高清导出用 `--force-device-scale-factor=2`。
- key 一旦在任何输出里出现，立即用 `sed 's/sk-[A-Za-z0-9]*/sk-***/g'` 脱敏，绝不写进文档/记忆。

## QA自检

- [ ] 每节≤5个bullet
- [ ] 每节有图（SVG 信息图 whiteboard，见上「配图」节；图里数字与清洗后正文一致）
- [ ] 不写段落
- [ ] 标题后`<cite>李坤</cite>`
- [ ] 结构不套模板
- [ ] 语言自然，像在说话
- [ ] 没有"计划→当前→差距→原因"这种模板前缀
- [ ] 没有World Model/张雨/王博洋内容
