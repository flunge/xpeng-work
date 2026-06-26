# 技术设计文档 — ppt-slide-formatter

## 1. 设计概述

将 15 页「小鹏自动驾驶仿真算法」技术分享（深色科技 / HUD 风格，源自 NotebookLM 整页位图 `refs/slide-01.png ~ slide-15.png`）重建为一套**纯前端、可逐字编辑的网页版 PPT**。

核心设计目标（对应 4 项用户诉求）：

1. 首页改造为标准标题页（主/副标题 + 主讲人「仿真算法负责人：Li Kun」，移除碎块标签）。
2. 每页右上角统一放置 XPENG Logo。
3. 删除所有 `DIGITAL TWIN TELEMETRY CONSOLE` 装饰文字。
4. 把以整页位图承载正文的页面，**抽离为结构化、可编辑的 HTML 文本元素**（表格 / 列表 / 分栏 / 卡片 / 流程），原图文字、数值、层级完整保留。

设计原则：**内容即源码可编辑**。每页正文以语义化 HTML 直接书写，文案修改只需在标记中定位文本节点，无需重新出图、无需运行任何生成工具。

---

## 2. 技术选型

| 维度 | 选型 | 理由 |
|------|------|------|
| 形态 | 纯前端静态站点（HTML/CSS/JS） | 需求明确为网页可编辑 PPT，无后端依赖 |
| 构建/开发服务器 | Vite（vanilla，无框架） | 提供 `localhost:5173` 热更新（与测试配置一致）；产物为静态文件，可零依赖部署 |
| 视图组织 | 单页 `index.html`，内含 15 个 `<section class="slide">` | 每页正文直接以 HTML 书写，文本节点可在源码中独立定位编辑（满足 NFR-001 / AC1.4 / AC4.1） |
| 样式 | 原生 CSS + CSS 变量（设计令牌） | 统一配色/字体/边距，保证 15 页视觉一致（NFR-002） |
| 交互 | 原生 JS（无框架） | 仅需翻页、键盘导航、全屏、进度，逻辑轻量 |
| 字体 | 系统等宽（HUD 角标）+ 思源/系统无衬线（中文正文） | 中英混排正确渲染，避免字体缺失乱码 |
| Logo | 内联 SVG 资源 `assets/xpeng-logo.svg` | 矢量清晰、可统一复用；若无官方素材则用文字标识占位并标注（AC2.3） |

不引入 React/Vue 等框架：页面以"内容可手工编辑"为第一目标，框架的组件化反而增加编辑门槛。不实现 .pptx/PDF 导出（超出本轮范围）。

---

## 3. 系统架构

### 3.1 目录结构

```
/workspace/ppt-slide-formatter/
├── index.html              # 15 个 <section class="slide"> 主文档（正文在此编辑）
├── package.json            # vite 依赖与脚本（dev/build/preview）
├── vite.config.js          # base、server.port=5173
├── public/
│   └── assets/
│       ├── xpeng-logo.svg          # 右上角统一 Logo（AC2.x）
│       └── illustrations/          # 难以文本化的纯插画（线框车、流程示意底图）
├── src/
│   ├── styles/
│   │   ├── tokens.css      # 设计令牌：配色/字号/间距/边框（视觉一致性基线）
│   │   ├── base.css        # reset、字体、slide 容器、16:9 缩放
│   │   ├── hud.css         # HUD 边框/角标/扫描线/页眉页脚通用装饰
│   │   └── components.css  # 标题页、对比表、卡片组、分支流程、引语等布局组件
│   └── main.js             # 翻页/键盘/全屏/进度条/Logo 注入
└── README.md               # 编辑指南：如何改文案、换 Logo、新增页
```

### 3.2 页面渲染模型

```
index.html
 └── <main id="deck">
      ├── <section class="slide" data-index="1"> 标题页 (slide-01)
      ├── <section class="slide" data-index="2"> 对比表 (slide-02)
      ├── ...
      └── <section class="slide" data-index="15"> 结尾页 (slide-15)

每个 <section> 结构统一：
 <section class="slide" data-layout="...">
   <header class="slide-hud-top">  ← 左上 data.stream 角标（保留），右上槽位放 Logo
   <div class="slide-body">         ← 正文：可编辑文本/表格/卡片
   <footer class="slide-hud-bottom">← 底部 HUD 状态行（保留风格，去除 CONSOLE 文字）
   <img class="slide-logo">         ← 右上角 XPENG Logo（全局组件，统一注入）
 </section>
```

JS `main.js` 仅负责：
- 启动时把 Logo 注入每个 `.slide`（或 CSS `::` 背景）——保证 15 页 Logo 位置/尺寸一致（AC2.1/AC2.2）；
- 键盘 `←/→/Space/Home/End`、点击边缘、滚轮翻页；
- 顶部进度条、页码 `n / 15`；
- `F` 全屏。

正文不经过 JS 模板渲染，直接写在 HTML 中，确保"源码即所见、可逐字编辑"。

---

## 4. 视觉设计令牌（tokens.css）

提取自源图，作为 15 页统一基线（NFR-002 / AC3.2 视觉协调）：

| Token | 值 | 用途 |
|-------|-----|------|
| `--bg-deep` | `#05080F` ~ `#0A0E17` 径向渐变 | 页面深色背景 |
| `--accent-orange` | `#FF6A00` / hover `#FF8A33` | 强调（旧方案、警示、标签边框、关键词） |
| `--accent-cyan` | `#00B4FF` / `#3DD0FF` | 新方案、数据流、高亮边框 |
| `--text-primary` | `#E8EEF6` | 中文标题/正文 |
| `--text-muted` | `#8A97A8` | 次要说明、被划除的旧概念 |
| `--hud-line` | `rgba(0,180,255,.25)` | HUD 边框/网格/角标 |
| `--font-mono` | `ui-monospace, "JetBrains Mono", Consolas, monospace` | HUD 角标、英文代号、数值 |
| `--font-cn` | `"Source Han Sans SC", "Microsoft YaHei", system-ui, sans-serif` | 中文标题与正文 |
| `--logo-size` | `clamp(28px, 3.2vw, 48px)` | 右上 Logo 统一尺寸 |
| `--logo-inset` | `2.2vw / 2.2vh` | Logo 距右/上边距，统一不遮挡正文 |

舞台采用 16:9 固定宽高比容器，按视口等比缩放（`transform: scale`），保证各页布局稳定。

---

## 5. 布局组件库（components.css）

将 15 页归纳为 6 类可复用布局原型，新内容只需套用原型即可保持一致：

| 原型 | `data-layout` | 适用页 | 结构要点 |
|------|---------------|--------|----------|
| L1 标题页 | `title` | 01、15 | 居中巨标题 + 副标题 + 信息框；01 含主讲人，15 含招聘信息/邮箱 |
| L2 双栏对比 | `compare-2col` | 02、10 | 左「旧/Legacy」灰阶 + 右「新方案」青蓝高亮；逐行维度对照，旧值可加删除线 |
| L3 多卡片并列 | `cards` | 13 及类似 | 等宽「Agent Node」卡片 + 连接线；标题(橙) + 正文(可编辑) |
| L4 分支流程 | `branch-flow` | 08 | 左侧根节点 → 右侧 N 个分支说明卡（标题 + 正文）|
| L5 重建/拓扑管线 | `pipeline` | 07、11 | 横向阶段块 + 连接箭头 + 阶段说明文本 |
| L6 论点/引语 | `statement` | 09、12、14 | 主标题 + 要点列表/大段引语；强调句用青蓝/橙关键词 |

> 03–06 页的精确内容需在开发阶段对照 `refs/slide-03~06.png` 逐字抽取，按其形态归入上述原型（多为 L2/L5/L6）。

### 5.1 关键组件示例 — 双栏对比 (slide-02)

```html
<section class="slide" data-layout="compare-2col">
  <header class="slide-hud-top">
    <span class="hud-tag">DATA.STREAM: VLA-2.0-LIVE</span>
    <!-- 右上 Logo 由全局注入；原 "DIGITAL TWIN TELEMETRY CONSOLE" 已移除 (AC3.1) -->
  </header>
  <h2 class="slide-title">范式转移：VLA 2.0 端到端架构彻底抽离了"安全拐杖"</h2>
  <p class="slide-lead">端到端架构的引入，意味着我们再也无法通过简单的静态代码 <em>Review</em> 确保安全性。</p>

  <div class="compare-grid">
    <div class="compare-col legacy">
      <h3>传统模块化（Legacy）</h3>
      <dl>
        <dt>核心输入 (Core Input)</dt><dd class="struck">BBox / 车道线轨迹</dd>
        <dt>逻辑载体 (Logic Carrier)</dt><dd class="struck">C++ Hard Rules</dd>
        <dt>演进路径 (Evolution)</dt><dd class="struck">人工修 Bug</dd>
      </dl>
    </div>
    <div class="compare-col next">
      <h3>VLA 2.0（端到端）</h3>
      <dl>
        <dt>核心输入 (Core Input)</dt><dd>原始视频流 / 点云流</dd>
        <dt>逻辑载体 (Logic Carrier)</dt><dd>深度神经网络参数</dd>
        <dt>演进路径 (Evolution)</dt><dd>数据闭环驱动参数迭代</dd>
      </dl>
    </div>
  </div>

  <ul class="feature-strip">
    <li><b>隐式物理建模：</b>模型不再依赖硬编码，通过 Transformer 学习空间连贯性。</li>
    <li><b>极低延迟：</b>决策链路极度压缩，端到端推理时延 &lt;80ms。</li>
    <li><b>常识涌现：</b>在无标线乡村路段展现出类人博弈避让能力。</li>
  </ul>
  <footer class="slide-hud-bottom"><span>SYS.STATUS: ACTIVE</span><span>LATENCY: &lt;80MS</span></footer>
</section>
```

每个文字节点（标题、维度名、维度值、要点）都是独立 DOM 文本，直接编辑即可（AC4.1/AC4.2/AC4.3）。`<80ms` 等数值原样保留。

---

## 6. 各诉求的设计落地

### 6.1 首页标题页（FR-001）
- 布局 `title`：巨号主标题「打破工程困局」+ 副标题「如何在"不确定"的物理世界里，为自动驾驶大模型构建"确定"的运行闭环」。
- 主讲人信息框：**「仿真算法负责人：Li Kun」**（替换原 `# PROJECT_LEAD: 仿真算法负责人` 角标的零散表达，统一为标题页正式署名）。
- **移除**碎块胶囊 `#VLA 2.0`、`#3DGS Recon`、`#Gen-Sim`、`#AI Agent`，以及散落的 `# TARGET:`、`RFC-SIM-2024-V2.0` 等碎块（AC1.3）。
- 线框车插画（难以文本化）保留为背景插画元素，但其上叠加的说明文字全部文本化（AC4.4）。
- 团队署名 `XPENG AUTOMOTIVE SIMULATION ALGORITHM TEAM` 默认保留为副信息（如需删除可一行注释切换，开发说明中标注）。

### 6.2 右上角 Logo（FR-002）
- `assets/xpeng-logo.svg` 经全局逻辑注入到每个 `.slide` 右上角固定槽位，使用统一 `--logo-size` / `--logo-inset`，绝对定位于正文之上、不与标题重叠（AC2.1/AC2.2）。
- 若无官方矢量 Logo，使用清晰「XPENG」字标（品牌字形近似）SVG 占位，并在 `README.md` 标注「待替换为官方素材」（AC2.3）。

### 6.3 删除 CONSOLE 文字（FR-003）
- 全量删除各页 `DIGITAL TWIN TELEMETRY CONSOLE`（slide-02 左上、slide-08 右下、slide-13 顶部、slide-10 底部等）。
- HUD 顶/底状态行**保留风格但替换内容**：左上保留 `DATA.STREAM: xxx` 角标，删除 CONSOLE 行后由其余角标补位，边框/网格不塌陷（AC3.2）。

### 6.4 图片内容文本化（FR-004）
- 15 页全部以 HTML 元素承载正文，**不使用整页位图**（AC4.1）。
- 结构化内容按原型还原：对比表→`compare-2col`，分支说明→`branch-flow` 卡片，节点管线→`cards`/`pipeline`（AC4.2）。
- 中英文案、数值（`<80ms`、`<10ms`、`<15ms`、`<5ms`、`<1ms`、邮箱 `sim-algo-lead@xpeng.com` 等）逐字保留，不增删不臆造（AC4.3）。
- 纯插画/连线示意（线框车、3DGS 分裂连线、电路连线）允许保留为 SVG/图片背景，但其承载的说明文字必须抽离为可编辑文本（AC4.4）。
- 移除源图右下角 `NotebookLM` 水印（属生成工具痕迹，非正文）。

---

## 7. 导航与交互（main.js）

| 功能 | 实现 |
|------|------|
| 翻页 | `←/PageUp` 上一页，`→/Space/PageDown` 下一页，`Home/End` 首尾 |
| 当前页定位 | URL hash `#/3` 或 `data-active`，刷新保持 |
| 进度 | 顶部细进度条 + 右下页码 `n / 15` |
| 全屏 | `F` 切换 `requestFullscreen` |
| 缩放 | 监听 resize，按 16:9 等比 `scale` 适配视口 |
| Logo 注入 | DOMContentLoaded 时为每个 `.slide` 追加统一 Logo 节点 |

无网络请求、无第三方运行时依赖（除开发期 Vite）。

---

## 8. 安全与质量

- 纯静态前端，无后端、无认证需求；不收集数据、无外部接口调用，无敏感信息暴露面。
- 邮箱等联系方式为演示文案的一部分，按原图保留。
- 可访问性：标题层级 `h1>h2>h3` 语义化；对比表用 `<dl>/<table>` 表达对照关系；插画 `alt` 描述；正文与背景对比度满足深色主题可读性。
- 兼容性：现代浏览器（Chrome/Edge/Safari/Firefox 最新版）。

---

## 9. 验证策略

1. `npm run dev` 启动，访问 `http://localhost:5173` 逐页核对。
2. 对照 `refs/slide-01~15.png` 校验文案/数值无遗漏、无臆造（FR-004）。
3. 逐项 grep 确认 `DIGITAL TWIN TELEMETRY CONSOLE` 全站 0 命中（FR-003）。
4. 检查 15 页右上角 Logo 位置/尺寸一致（FR-002）。
5. 首页确认仅含主/副标题 + 主讲人，无碎块标签（FR-001）。
6. `npm run build` 通过，产物可静态预览。

---

## 10. 需求追溯（Requirement Traceability）

> 每个验收标准（AC）均映射到具体设计点，确保无遗漏。

| 需求 | 验收标准 | 设计落地位置 | 说明 |
|------|----------|--------------|------|
| FR-001 | AC1.1 主/副标题 | §5(L1)、§6.1 | `title` 布局展示「打破工程困局」+ 副标题 |
| FR-001 | AC1.2 主讲人「仿真算法负责人：Li Kun」 | §6.1 | 标题页信息框正式署名 |
| FR-001 | AC1.3 移除碎块标签胶囊 | §6.1 | 删除 #VLA2.0/#3DGS Recon/#Gen-Sim/#AI Agent 及散块 |
| FR-001 | AC1.4 文本可独立编辑 | §3.2、§5、NFR-001 | 主/副标题/主讲人为独立 HTML 文本节点 |
| FR-002 | AC2.1 全 15 页右上 Logo | §3.2、§6.2、§7 | 全局注入统一 Logo 节点 |
| FR-002 | AC2.2 尺寸/边距一致且不遮挡 | §4(tokens)、§6.2 | `--logo-size`/`--logo-inset` 统一，绝对定位于正文上层 |
| FR-002 | AC2.3 缺素材时占位并标注 | §2、§6.2 | XPENG 字标 SVG 占位 + README 标注待替换 |
| FR-003 | AC3.1 删除全部 CONSOLE 文字 | §6.3 | slide-02/08/10/13 等处删除 |
| FR-003 | AC3.2 删除后布局不塌陷 | §6.3、§4 | HUD 顶/底状态行保留风格、角标补位 |
| FR-004 | AC4.1 全页不用整页位图承载正文 | §2、§3.2、§6.4 | 15 页正文均为 HTML 元素 |
| FR-004 | AC4.2 结构化内容用表/列表/分栏还原 | §5(L2/L3/L4/L5)、§5.1、§6.4 | 对比表/分支卡/节点卡原型 |
| FR-004 | AC4.3 文案/数值/层级完整保留 | §5.1、§6.4、§9.2 | 逐字保留 `<80ms` 等；校验流程兜底 |
| FR-004 | AC4.4 纯插画可保留但说明文字抽离 | §6.1、§6.4 | 线框车/连线作背景，文字文本化 |
| NFR-001 | 可编辑性 | §2、§3.2、§5 | 正文直写 HTML、源码可逐字定位修改 |
| NFR-002 | 视觉一致性 | §4、§5、§6.2 | 设计令牌 + 布局组件库 + 统一 Logo 位 |
| 约束 | 保持 HUD 深色风格 | §4、§5、§6.3 | 配色/等宽字体/边框角标延续 |
| 约束 | 15 页、页序一致 | §3.1、§5 | 15 个 `<section>`，data-index 1~15 与源图同序 |
| 约束 | 网页技术栈可编辑 | §2 | Vite + 原生 HTML/CSS/JS |
| 约束 | 中英混排正确渲染 | §4(字体) | `--font-cn` + `--font-mono` 回退链 |
| 范围 | 不新增页、不改文案实质 | §6.4、§1 | 仅结构化 + 4 项规范化 |
| 范围 | 不实现导出 | §2 | 明确不做 .pptx/PDF |

---

## 11. 待确认事项

1. **Logo 素材**：是否提供官方 XPENG 矢量 Logo？否则用字标 SVG 占位（AC2.3）。
2. **首页团队署名**：`XPENG AUTOMOTIVE SIMULATION ALGORITHM TEAM` 是否保留？默认保留为副信息。
3. **03–06 页内容**：开发阶段将严格对照 `refs/slide-03~06.png` 逐字抽取，如有不清晰处会以源图为准并标注。
