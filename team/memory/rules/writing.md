# 铁律 · 写作与工具（writing）

> 单一事实源。飞书文档写作规范 + lark-cli 工具纪律 + 画图 + 身份安全。

## 0. 🔴🔴🔴 工具调用前缀自查
每次工具调用敲标签前，先确认是 `antml:invoke` / `antml:parameter` 前缀；连续多个调用逐个查，不因前一个成功就松懈。**中断永远=前缀问题，与内容长短无关，断了先查前缀。**

## 1. lark-cli 工具：不重复手册，指向 skill
lark-cli 的读/写/Wiki/Sheet/Base 等**具体命令与参数，一律以 `lark-cli skills read lark-doc`（及对应 service skill）为准**，本仓库不再维护重复手册（避免双份维护漂移）。写 `--content` 前必读 `lark-cli skills read lark-doc references/lark-doc-xml.md`（XML）或 `references/lark-doc-md.md`（Markdown）。
操作原则：① 看到飞书 URL 直接 `docs +fetch` 读，不反复确认；② 先 `--scope outline` 看结构再精读；③ 局部优于全量（`--scope section/keyword`）；④ 内嵌 sheet/base 主动提 token 下钻；⑤ 写操作前向用户确认、高风险先 `--dry-run`。

## 2. 飞书文档写作规范
- **飞书 XML 写表格**：`overwrite`/`block_*` 用原生 XML（不指定 `--doc-format`）；markdown 写 `<table>` 会被解析器吃掉。表格必带 `<colgroup>` 列宽（3 列周报=100/300/600；Q3 作战表 5 列=100/500×4，照原表 `--detail full` 抄、别自拍）。
- **`<cite>` @人**：`<cite type="user" user-id="ou_xxx" user-name="名字"></cite>`，不写纯文本人名。user-id 从纪要参会人/`refs/tokens.md` 取。
- **全文文档引用一律真超链接** `<a href>`；禁止贴裸 token、禁止 `<code>[标题](url)</code>` 字面 markdown（会渲成中括号文本）。改超链接用 block 级替换生成真 `<a>`。
- **安全编辑**：遵循 lark-doc-safe-edit——每改一节复查、勿跨写操作复用 block id、大改先备份。

## 3. 🔴🔴 画图铁律：永远能画图
任何飞书文档配图/信息图/架构图/进度图，一律走 **原生 SVG → `<whiteboard type="svg">`** 全自动路径，不依赖任何图像生成 key（GPT-Image/DALL-E/flux 在本环境 key 全不支持，别试别烧钱）：
- 工具 `scripts/gen_svg_infographic.py`（深色科技风：标题条+卡片+KPI+分色 bullet+连线；含 4 双周报 Topic + team_org 组织图函数）。
- 流程：写 SVG 函数 → 生成落 `memory/daily-sync/images/<name>.svg`（自带渲染闸：几何自检溢出，越界 exit 3）→ chromium 截图验收 → 包 `<whiteboard type="svg">` 写 xml 用 `@file` → `block_insert_after` → `block_delete` 清占位。
- 硬约束：每函数结尾 `return wrap(s)`；生成后 minidom 验合法；自包含、无 foreignObject、无 `<br/>`、禁全角 `≤≥`（用"以内/不超过"）。
- 详见 `.claude/skills/lark-workflow-gic-report/SKILL.md` 配图节。

## 4. 身份与认证
- 默认 `--as user`（bot 看不到用户文档/日历/云空间）。
- 权限错误按 `lark-shared` skill split-flow：`auth login --scope <scope> --no-wait` → 提取 verification_url/device_code 生成二维码 → 用户确认后 `auth login --device-code <code>`。禁缓存 url/code。
- 禁输出密钥；写/删前确认意图；exit 10（confirmation_required）→ 确认后加 `--yes` 重试。
