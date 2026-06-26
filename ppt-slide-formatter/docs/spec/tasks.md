# 开发任务

## 概览
- **Feature**: ppt-slide-formatter（小鹏自动驾驶仿真算法 15 页可编辑网页 PPT）
- **任务数**: 5（含 Task 0）
- **项目大类**: Web 前端（新项目）
- **技术栈**: Vite + 原生 HTML / CSS / JS（无框架）
- **API 策略**: 无后端 API；纯前端静态站点，Logo 为静态资源依赖

## 需求覆盖矩阵
| 验收标准 | 对应任务 | 覆盖状态 |
|----------|----------|----------|
| AC1.1: 首页显示主标题「打破工程困局」与副标题 | Task 1 | ✅ |
| AC1.2: 首页显示主讲人「仿真算法负责人：Li Kun」 | Task 1 | ✅ |
| AC1.3: 移除首页碎块标签胶囊及零散装饰块 | Task 1 | ✅ |
| AC1.4: 首页主/副标题/主讲人为可独立编辑文本元素 | Task 1 | ✅ |
| AC2.1: 全部 15 页右上角统一展示 XPENG Logo | Task 2 | ✅ |
| AC2.2: Logo 大小/边距各页一致且不遮挡正文 | Task 2 | ✅ |
| AC2.3: 缺官方素材时用 XPENG 字标占位并标注待替换 | Task 2 | ✅ |
| AC3.1: 删除全部 DIGITAL TWIN TELEMETRY CONSOLE 文字 | Task 2 | ✅ |
| AC3.2: 删除后 HUD 边框/布局不塌陷、视觉协调 | Task 2 | ✅ |
| AC4.1: 全 15 页不用整页位图承载正文，正文为可编辑文本 | Task 3 | ✅ |
| AC4.2: 结构化内容用表格/列表/分栏还原且可逐项编辑 | Task 3 | ✅ |
| AC4.3: 完整保留中英文案、数值、层级，不遗漏不臆造 | Task 3 | ✅ |
| AC4.4: 纯插画可保留为图片，但其上说明文字须文本化 | Task 3 | ✅ |
| NFR-001: 可编辑性（源码可逐字定位修改，无需重新出图） | Task 0, Task 1, Task 3 | ✅ |
| NFR-002: 视觉一致性（配色/字体/Logo位/HUD 边框统一） | Task 0, Task 4 | ✅ |
| 约束: 保持 HUD 深色科技风格 | Task 0, Task 4 | ✅ |
| 约束: 15 页、页序与源图一致 | Task 0, Task 3 | ✅ |
| 约束: 网页技术栈可编辑实现 | Task 0 | ✅ |
| 约束: 中英混排正确渲染 | Task 0, Task 4 | ✅ |
| 范围: 不新增页、不改文案实质、不实现导出 | Task 3, Task 4 | ✅ |

> 覆盖率：全部 14 条 AC + 2 条 NFR + 全部约束/范围说明 100% 覆盖。

## 任务列表

### Task 0: 项目基础准备 ⬜（新项目必须）
**关联需求**: 全部（NFR-001、NFR-002、网页技术栈/页序/中英混排约束的基础）
**目标**: 搭建 Vite 纯前端脚手架，建立设计令牌与 HUD 视觉基线、导航交互骨架，以及 15 个空 `<section>` 页面框架（页序 1~15），为后续逐页填充内容提供统一地基。
**依赖**: 无
**实施**:
1. 在 `/workspace/ppt-slide-formatter/` 初始化 Vite（vanilla 模板）：`package.json`（dev/build/preview 脚本）、`vite.config.js`（`server.port=5173`、`base`）。
2. 创建目录结构：`index.html`、`src/styles/{tokens,base,hud,components}.css`、`src/main.js`、`public/assets/`。
3. 编写 `tokens.css`：落地 design §4 设计令牌（`--bg-deep`、`--accent-orange #FF6A00`、`--accent-cyan #00B4FF`、文本色、`--hud-line`、`--font-mono`、`--font-cn`、`--logo-size`、`--logo-inset`）。
4. 编写 `base.css`：reset、16:9 舞台容器、等比 `scale` 适配；`hud.css`：HUD 边框/角标/扫描线/页眉页脚通用装饰。
5. 编写 `main.js` 导航骨架：键盘 `←/→/Space/Home/End` 翻页、URL hash 定位、顶部进度条、页码 `n/15`、`F` 全屏。
6. 在 `index.html` 中放置 15 个 `<section class="slide" data-index="1..15">` 占位骨架（含统一 `slide-hud-top`/`slide-body`/`slide-hud-bottom` 结构槽位）。
**文件**: `package.json`、`vite.config.js`、`index.html`、`src/styles/tokens.css`、`src/styles/base.css`、`src/styles/hud.css`、`src/styles/components.css`、`src/main.js`
**验证**: `npm install && npm run build` 通过；`npm run dev` 后 `http://localhost:5173` 可渲染 15 页空框架、可键盘翻页、页码显示 `n / 15`；深色 HUD 基线样式生效。

### Task 1: 首页改造为标准 PPT 标题页 ⬜
**关联需求**: FR-001 (AC1.1, AC1.2, AC1.3, AC1.4)、NFR-001
**目标**: 将 slide-01 重建为标准标题页，呈现主/副标题与主讲人，去除碎块标签，所有文案为可独立编辑文本节点。
**依赖**: Task 0
**实施**:
1. 套用 `title` 布局：巨号主标题「打破工程困局」+ 副标题「如何在"不确定"的物理世界里，为自动驾驶大模型构建"确定"的运行闭环」（AC1.1）。
2. 添加主讲人信息框「仿真算法负责人：Li Kun」（AC1.2）。
3. 移除碎块胶囊 `#VLA 2.0`、`#3DGS Recon`、`#Gen-Sim`、`#AI Agent` 及 `# TARGET:`、`RFC-SIM-2024-V2.0` 等散块（AC1.3）。
4. 团队署名 `XPENG AUTOMOTIVE SIMULATION ALGORITHM TEAM` 默认保留为副信息（可一行注释切换，README 标注）。
5. 线框车插画如保留则作背景，其上说明文字文本化。
6. 确保主标题/副标题/主讲人均为独立 HTML 文本节点，可逐字定位修改（AC1.4、NFR-001）。
**文件**: `index.html`（slide-01 区块）、`src/styles/components.css`（`title` 布局）、`refs/slide-01.png`（对照）
**验证**: 对照 `refs/slide-01.png`，首页仅含主/副标题 + 主讲人 + 团队署名；无任何碎块标签胶囊；在源码中可直接编辑三处文本。

### Task 2: 全页 XPENG Logo 注入 + 删除 CONSOLE 装饰文字 ⬜
**关联需求**: FR-002 (AC2.1, AC2.2, AC2.3)、FR-003 (AC3.1, AC3.2)
**目标**: 为全部 15 页右上角统一注入 XPENG Logo，并彻底删除所有 `DIGITAL TWIN TELEMETRY CONSOLE` 文字，保持 HUD 布局不塌陷。
**依赖**: Task 0
**实施**:
1. 准备 `public/assets/xpeng-logo.svg`：有官方矢量则用之，否则用清晰 XPENG 字标 SVG 占位，并在 README 标注「待替换为官方素材」（AC2.3）。
2. `main.js` 在 `DOMContentLoaded` 时为每个 `.slide` 注入统一 Logo 节点，使用 `--logo-size`/`--logo-inset` 绝对定位于右上、置于正文之上（AC2.1、AC2.2）。
3. 校验 Logo 不与各页标题/正文重叠，必要时调整页眉内边距。
4. 全量删除各页 `DIGITAL TWIN TELEMETRY CONSOLE`（slide-02 左上、slide-08 右下、slide-13 顶部、slide-10 底部等所有出现处）（AC3.1）。
5. HUD 顶/底状态行保留风格，删除 CONSOLE 行后由其余角标补位，边框/网格不塌陷（AC3.2）。
**文件**: `public/assets/xpeng-logo.svg`、`src/main.js`、`src/styles/hud.css`、`index.html`、`README.md`
**验证**: 全站 `grep "DIGITAL TWIN TELEMETRY CONSOLE"` 0 命中；15 页右上 Logo 位置/尺寸一致且不遮挡正文；HUD 边框无塌陷。

### Task 3: 图片型内容抽离为结构化可编辑元素（slide-02~15） ⬜
**关联需求**: FR-004 (AC4.1, AC4.2, AC4.3, AC4.4)、NFR-001、约束（15 页/页序一致、不改文案实质）
**目标**: 将 slide-02~15 的整页位图正文逐页抽离为语义化 HTML，对照源图逐字还原文案、数值与层级，结构化内容套用对应布局原型。
**依赖**: Task 0（建议在 Task 1/2 之后并行细化）
**实施**:
1. 逐页对照 `refs/slide-02~15.png` 抽取文案、数值（`<80ms`/`<10ms`/`<15ms`/`<5ms`/`<1ms`、邮箱 `sim-algo-lead@xpeng.com` 等）与层级，禁止臆造（AC4.3）。
2. 套用 design §5 布局原型：双栏对比（02、10）→ `compare-2col`；多卡片（13）→ `cards`；分支流程（08）→ `branch-flow`；重建/拓扑管线（07、11）→ `pipeline`；论点/引语（09、12、14）、结尾页（15）→ `statement`/`title`；03~06 对照源图归入相应原型（AC4.2）。
3. 确保 15 页全部以 HTML 元素承载正文，不使用整页位图（AC4.1）。
4. 纯插画/连线示意（线框车、3DGS 连线、电路连线）允许保留为 SVG/图片背景，但其上说明文字抽离为可编辑文本（AC4.4）。
5. 移除源图右下角 `NotebookLM` 水印（非正文）。
6. 完善 `components.css` 中各布局原型样式。
**文件**: `index.html`（slide-02~15 区块）、`src/styles/components.css`、`public/assets/illustrations/`、`refs/slide-02~15.png`（对照）
**验证**: 逐页与源图核对文案/数值/层级无遗漏无臆造；全 15 页均无整页位图承载正文；结构化内容可逐项编辑；页数 15、页序与源图一致。

### Task 4: 视觉一致性收口与全量验证 ⬜
**关联需求**: NFR-002、约束（HUD 风格/中英混排）、范围说明（不新增页、不导出）
**目标**: 统一 15 页视觉规范，校验中英混排渲染，完成需求逐条验收并补充编辑指南。
**依赖**: Task 1、Task 2、Task 3
**实施**:
1. 巡检 15 页配色、字体、字号、间距、页眉 Logo 位、HUD 边框样式是否统一，修正偏差（NFR-002）。
2. 校验中英混排无字体缺失/乱码，确认 `--font-cn`/`--font-mono` 回退链生效（约束）。
3. 确认未新增超出 15 页的内容、未改写文案实质、未引入导出功能（范围说明）。
4. 编写 `README.md` 编辑指南：如何改文案、替换 Logo、新增页、Logo 待替换标注。
5. 执行 design §9 验证清单（dev 逐页核对、`npm run build` 通过、CONSOLE 0 命中、Logo 一致、首页无碎块）。
**文件**: `src/styles/*.css`、`index.html`、`README.md`
**验证**: `npm run build` 通过；15 页视觉一致、中英混排正常；design §9 验证清单全部通过。

## 进度
| 任务 | 关联需求 | 状态 |
|------|----------|------|
| Task 0: 项目基础准备 | 全部（基础） | ⬜ |
| Task 1: 首页标题页 | FR-001 (AC1.1~1.4) | ⬜ |
| Task 2: Logo 注入 + 删除 CONSOLE | FR-002, FR-003 | ⬜ |
| Task 3: 内容文本化 02~15 | FR-004 (AC4.1~4.4) | ⬜ |
| Task 4: 视觉收口与验证 | NFR-002, 约束, 范围 | ⬜ |
