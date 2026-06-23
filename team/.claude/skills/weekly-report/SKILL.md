---
name: weekly-report
description: 生成仿真算法组周报。采集过去7天的日会纪要（含逐字稿）、群聊消息、Wiki上下文，按高炳涛偏好格式生成结构化周报，写入飞书文档。每周三上午使用。
triggers:
  - 周报
  - weekly report
  - 本周汇报
  - 每周汇报
  - 生成周报
---

# Weekly Report Agent

生成李坤（仿真算法组 P8）的每周进展汇报，汇报对象为高炳涛（仿真部 P9）。

## 触发时机

每周三上午触发。覆盖周期：**上周三 00:00 → 本周三 12:00**。

## 执行方式

直接调用 Workflow 脚本 `pipelines/weekly-report.js`：

```
使用 Workflow 工具，scriptPath 为 pipelines/weekly-report.js
```

## 工作流程

1. **Collect** — 按优先级顺序串行采集（不可跳过任何一步）：
   - **Step 1【必须】Q2 Wiki**：遍历 `https://xiaopeng.feishu.cn/wiki/SBUYwm8Lri9aJ6kmexFcBAuGnlh` 中本周时间窗口（上周三→本周二）的进展列——Wiki 是表格格式，每一天是一列（如 0609 列），逐列读完；再读所有嵌套链接文档全文
   - **Step 2【必须】会议纪要+逐字稿**：遍历本周时间窗口内所有核心日会、组内日会、其他会议的智能纪要 **+** 文字记录（逐字稿），两者都要读，缺一不可
   - **Step 3【必须】聊天记录**：遍历本周时间窗口内的群聊消息和 p2p 消息
   - **⚠️ Memory 文件仅供背景理解，不是数据源**：memory/people/*.md、memory/projects/*.md 用于理解人和项目背景，不能替代上面三步直接编写周报内容
2. **Analyze** — 逐轨提取：场景&生产 / SIL / HIL / Agents 的结构化进展
3. **Synthesize** — 合成报告：按高炳涛偏好格式
4. **Output** — 写入飞书文档 + 本地存档

---

## 格式约束（2026.06.11 对话沉淀）

### 核心格式：必须用部门日会 Wiki 的表格

**不要自行设计报告结构。** 李坤在部门日会 wiki 里已经有一套固定格式，直接复用：

```
表格：链路 | 月目标 | 核心进展

4行：
  场景&生产 | [月目标，不改] | [本周进展更新]
  SIL      | [月目标，不改] | [本周进展更新]
  HIL      | [月目标，不改] | [本周进展更新]
  Agents   | [月目标，不改] | [本周进展更新]
```

- **月目标列**：从部门日会 wiki 李坤的上一条 entry 直接复制，不修改
- **核心进展列**：只更新内容，保持结构（【业务交付】→【算法优化】的分组）
- **不要用8章节的"AI报告格式"**（总体脉络→四轨→跨轨关注→风险→依赖→下周重点）——这种格式AI痕迹明显，高炳涛会觉得"不像李坤写的"

### 🔑 飞书 XML 格式写表格（2026.06.11 关键教训）

**问题**：`--doc-format markdown` 写 HTML `<table>` → 飞书 markdown 解析器吃掉表格标签 → 四轨内容变成扁平文本，月目标列丢失。

**正确做法**：用飞书原生 XML 格式（`lark-cli` 默认 `--doc-format xml`）：

```xml
<table><colgroup><col width="100"/><col width="180"/><col width="420"/></colgroup><tbody>
<tr><td><b>链路</b></td><td><b>月目标</b></td><td><b>核心进展</b></td></tr>
<tr><td><b>场景&amp;生产</b></td>
  <td><ul><li>月目标1</li><li>月目标2</li></ul></td>
  <td><ul><li>进展1</li><li>进展2</li></ul></td>
</tr>
</tbody></table>
```

- `--command overwrite --content "<xml内容>"` 不指定 `--doc-format`（默认就是 xml）
- `<td>` 内可以嵌套 `<ul><li>`、`<b>`、`<img>`、`<cite>`
- `&amp;` 转义 `&`，`&lt;` 转义 `<`

### 🔑 用 `<cite>` 标签 @人（2026.06.11 关键教训）

**问题**：写"杨星昊"纯文本 → 高炳涛看到的只是名字，不能点击跳转。

**正确做法**：用飞书 `<cite>` 标签：

```xml
<cite type="user" user-id="ou_b41c33085d2e629fbdff0c555cae0a3f" user-name="杨星昊"></cite>
```

- `user-id` 从哪儿来：会议纪要 doc 的参会人列表（`<cite type="user" ...>`）、memory 文件 `team-members.md`
- 全组13人的 user-id 已知，可直接复用
- 飞书渲染后显示为可点击的 @人名
- **注意**：`<cite>` 是自闭合标签，后面紧跟冒号或空格时需要额外处理，否则可能粘连。建议格式：`<cite ...></cite>：`

### 怎么"增加高炳涛感兴趣的内容"

不另开章节，而是在核心进展列里自然融入：
- AI 使用：在相关条目后加一句"（AI辅助xxx）"或标注模型/成本
- 代码质量：有重构/清理/审计时显式写出
- 时间节点：每条进展都带上具体日期，不写"近期""下周"
- 闭环：每条进展说清楚"做了什么→结论是什么→下一步是什么"

### 图片处理

用 image-agent 的搬图流程：
1. 从会议纪要 doc 下载图片（`docs +media-download --token <src>`）
2. 上传到个人文档（`docs +media-upload --file ./img --doc-id <id> --parent-node <id> --parent-type docx_image`）
3. 用 `block_insert_after` 在占位文本后插入 `<img src="file_token" mime="..."/>`
4. **插入后删除占位文本 block**（否则图文重复，显脏）

注意：API 直接插入的图可能显示为方形框，已知限制。

---

## 质量门禁（写入前必须自检）

```
□ 【硬规则】Q2 Wiki 本周所有进展列（逐列）读完，嵌套文档全部打开读全文
□ 【硬规则】本周所有会议的智能纪要+逐字稿都读了（缺场次需标注）
□ 【硬规则】数据覆盖时间窗口（上周三→本周二），缺了几天标注几天
□ 【硬规则】逐字稿读了——能说出老板本周在核心日会上具体说了什么
□ 【硬规则】每条进展可溯源到某天的会议纪要（不是编的）
□ 【硬规则】没有凭空编造的风险（如"三线并行"）
□ 【硬规则】报告中零次出现"高炳涛""炳涛"
□ 【硬规则】表外零字符——没有开头小结、没有结尾风险列表、没有 blockquote
□ 【硬规则】月目标颜色准确——🔴仅用于严重阻塞（IT、缺卡），不滥用
□ 表格结构完整：<table><tr><td> 四行都在，每行有链路标签
□ 月目标列存在且内容完整（不是几个字的缩写）
□ 每条进展有具体数字或时间节点
□ 人名用 <cite> 标签（可点击 @），不用纯文本
□ 图片用 block_insert_after 插入（media-upload 2>/dev/null）
□ 没有"【贴图：xxx】"占位残留
□ 没有"赋能""抓手""已具备独立交付能力"等AI腔
□ 没有"近期""下周""尽快"等模糊时间词
□ 内容用飞书 XML 格式（不指定 --doc-format）
```

---

## 🔴 硬规则（不可违反，2026.06.11 对话沉淀）

### 数据采集
1. **三步铁则，按序执行，不可跳过**：
   - **Step 1 — Q2 Wiki**：`https://xiaopeng.feishu.cn/wiki/SBUYwm8Lri9aJ6kmexFcBAuGnlh`，读本周时间窗口（上周三→本周二）内所有进展列（表格每列=一天，如 0609 列），再逐一打开每列里所有嵌套链接文档读全文
   - **Step 2 — 会议纪要+逐字稿**：本周窗口内核心日会+组内日会+其他会议，每场都要读智能纪要 **和** 文字记录，缺逐字稿等于没读
   - **Step 3 — 聊天记录**：本周窗口内群聊+p2p
2. **时间窗口**：上周三 00:00 → 本周二 23:59（周三早上汇报，截至周二）。不能只读最近2-3天
3. **逐字稿必须读**：AI 纪要约等于摘要，原话、追问、当场决策只在逐字稿里。即使最后报告不提名字
4. **上周三核心日会是第一优先级**：对上次汇报的反馈和改进要求都在里面。API 报错也要标注 gap
5. **只写数据里有的事**：不凭空编造风险，每句话都要能在源文档里溯源
6. **Memory 不是数据源**：memory 文件帮助你理解组的背景，不能替代 Step 1-3 直接当写报告的依据

### 内容
6. **不提老板名字**：出于尊重，报告中不出现"高炳涛""炳涛"任何形式。他的要求直接写内容即可
7. **纯表格，无表外文字**：文档只有 `<table>`，表上方和下方一个字不留。不写开头小结、不写结尾风险列表
8. **风险只从数据来**：每条风险在会议纪要里有原文支撑。风险标注要准确——🔴 是严重阻塞，🟡 是关注项，不要过度标红
9. **每条进展可溯源**：谁说的、哪天说的、在哪个会上说的。宁可少写不漏写

### 格式
10. **飞书 XML 写表格**：`--command overwrite` 不指定 `--doc-format`，用 `<table><tr><td>` 原生 XML
11. **`<cite>` 标签 @人**：不写纯文本 "杨星昊"，写 `<cite type="user" user-id="ou_xxx" user-name="杨星昊"></cite>`
12. **图片用 `block_insert_after`**：media-upload（`2>/dev/null` 抑制 stderr）→ block_insert_after `<img src="file_token">`。docx 不方形框，XML inline 才方形框
13. **月目标颜色标注**：🟢正常 🟡关注 🔴阻塞，判断要准确——只有 IT 阻塞、缺卡这类才标红

---

## 关键原则

- **每条进展有数字+Owner+时间节点+闭环**
- **AI使用和代码质量显式列出**（最关注的两项）
- **零 AI 腔**（禁止"赋能""抓手""已具备独立交付能力"等）
- **写短、写判断、写结论**
- **格式对齐已有汇报**，不过度设计

---

## 常见踩坑

| 坑 | 表现 | 修法 | 发现日期 |
|----|------|------|---------|
| 自创报告结构 | 8章节"AI报告"格式，不像李坤写的 | 复用部门日会 wiki 的表格格式 | 6/11 |
| markdown 写 HTML table | `<table>` 被飞书解析器吃掉，四轨扁平化 | **用 XML 格式（默认），不指定 `--doc-format`** | 6/11 |
| 纯文本人名 | "杨星昊"不能点击，不像飞书文档 | 用 `<cite type="user" user-id="ou_xxx" user-name="名字"></cite>` | 6/11 |
| 图片占位没删 | "【贴图：xxx】"和图同时出现 | `block_delete` 删占位；或在 XML 里直接写 `<img>` 不要占位 | 6/11 |
| 图片用错插入方式 | XML overwrite 的 `<img>` → 方形框；之前尝试的 `block_insert_after` 在 docx 里其实是正常的 | **正确：media-upload（2>/dev/null 抑制 stderr）→ block_insert_after `<img src="file_token">`。** image-agent 的方形框警告针对的是 Wiki，docx 不受影响。XML overwrite 创建的图片块被飞书内部重新编码导致方形框 | 6/11 |
| @了老板 | 汇报文档里 `<cite>` 高炳涛 → 他是收件人不是执行人 | 汇报对象不 @，老板交代的事直接写内容即可 | 6/11 |
| 月目标太简略 | 就写"复现率80%+"几个字，没有上下文 | 每条月目标写完整句，对齐Q2 wiki的6月目标描述（谁、做到什么程度、什么时间） | 6/11 |
| 风险没应对 | 只列🔴缺卡，没说怎么办 | 每条风险加 `→ 应对：xxx` | 6/11 |
| 没有高炳涛原话 | 报告和他本周的追问脱节 | 核心日会逐字稿提取他直接说的话，以引述形式写（不用 @） | 6/11 |
| AI腔太重 | "总体脉络""跨轨关注"等章节标题 | 回到表格格式，自然融入 | 6/11 |
| 凭空编造风险 | "三线并行"——数据里完全没有 | **只写数据里有的事。每条风险都要能溯源到某天某会议** | 6/11 |
| 表外写内容 | 开头小结 + 结尾风险列表 | 纯表格，零表外字符 | 6/11 |
| 数据窗口不完整 | 只读最近2-3天纪要 | 完整7天窗口（上周三→本周三），缺几天标几天 | 6/11 |
| 不提老板名字但也不读他原话 | 报告没写名字，但也不知道他这周关心什么 | **读逐字稿提取原话 → 融入报告内容，不提名字** | 6/11 |
| 月目标滥用红色 | 🔴标了3项，实际只有IT部署是真正的阻塞 | 仅严重阻塞标红，夸大风险反而是报忧不准 | 6/11 |
| 老板原话贴进报告 | "6/8核心日会要求xxx"——这是你的背景情报不是报告内容 | **老板的话消化后再写：他的关注 → 你的风险判断 → 你的应对。不直接引述会议来源** | 6/11 |
| 不同话题混在一段 | RC路线把采集恢复和生产链路丢失混在一起写 | 采集归采集，生产归生产。一件事一段，不乱掺 | 6/11 |
| 问题写了但修复没写 | RC路线只写677→290丢失，没写4辆车已冻结采集200KM | **先写最新状态，再回溯历史问题。读者第一眼应该看到的是"现在怎样了"** | 6/11 |
| 用 memory 写周报 | 没读 Q2 Wiki 和会议纪要，直接从 memory/people/*.md 或 memory/projects/*.md 提取进展写报告 | **memory 是背景理解，不是数据源。必须先读 Q2 Wiki→会议纪要→聊天，再动笔** | 6/12 |
| 跳过 Q2 Wiki 进展列 | 只读了 wiki 概要，没有按天列逐一读每列的进展和嵌套文档 | Q2 Wiki 表格每天一列，必须逐列读完本周时间窗口（上周三→本周二）内所有列，所有嵌套链接文档都要打开读全文 | 6/12 |
| 生成 narrative section | 在表格下方追加 `## 周报更新` 等文字段落 | **增量内容必须合并进表格的核心进展列，文档只有 `<table>`，零表外字符** | 6/12 |

---

## 参考文件

- 部门日会 wiki：`https://xiaopeng.feishu.cn/wiki/Wu6ywIOM6iEucDkmx3hcEgLHnmg`
- Q2 wiki：`https://xiaopeng.feishu.cn/wiki/SBUYwm8Lri9aJ6kmexFcBAuGnlh`
- 个人周报 doc：`https://xiaopeng.feishu.cn/docx/La9FdsXajoEgETxzTNCcvZFUn2b`
- 高炳涛画像：`memory/boss-gaobingtao.md`
- 文档规范：`memory/doc-writing-rules.md`
- 纪要规则：`memory/meeting-reading-rules.md`
- 图像Agent：`memory/image-agent.md`

---

## Q2 Wiki 文档结构（已验证，2026-06-15）

**URL**：`https://xiaopeng.feishu.cn/wiki/SBUYwm8Lri9aJ6kmexFcBAuGnlh`（wiki token：`BWtPdvQ3EoJtwExVpUPcs69qnRc`）

### 一级结构
- `周目标&进展` — 主章节，block_id：`STymdPgAJorwXvxjsrWcJKTMnDe`

### 每周 H4 block_ids（固定，无需每次重新查）

| 周次 | 起始日 | block_id |
|------|--------|----------|
| W4  | 04/24 | `UJwddDxJPohuGlxswiXcWdrrnqn` |
| W5  | 04/30 | `YeBmd2zSMoWG6qxjeoHcGZvCnbe` |
| W6  | 05/09 | `Tsjqd8HcCoFS4WxWgNzcnoFtnwc` |
| W7  | 05/15 | `IDWxde2d4olXrYxChlBcgaOAn2d` |
| W8  | 05/22 | `CI5Pdcd4ooD5ltxxP7oc9RG5nnb` |
| W9  | 05/29 | `EZhIdQ5fho2fFtxxfF9cehZ5nyw` |
| W10 | 06/05 | `ItzbdpFJWoFdJZxFm9scu36Cnif` |
| W11 | 06/12 | `AOY2dFxr9oqYhUxGyb9cHEh6nPh` |
| W12 | 06/19 | `Ee7VdYDYJosS5Cx6T7pcseWlnwe` |
| W13 | 06/26 | `WZ0fdoUZloixI1x3hMFc6DH3nSc` |

### 表格列格式（从 W7 起统一格式）
```
链路 | 目标 | 月目标 | 核心进展-MMDD | 核心进展-MMDD | ...
```
- 每天一列，新列在右侧追加，格式为 `核心进展-MMDD`（如 `核心进展-0615`）
- **直接读全文会因截断丢失最新列** — 必须用 `--scope keyword` 定向搜索

### ⚠️ 已知陷阱（2026-06-15 测试验证）

| 陷阱 | 说明 |
|------|------|
| `--scope keyword` 只返回列标题行 | keyword 命中的是表头单元格，`<excerpt>` 只包含该行，不包含数据行（四轨名称和进展都在其他行）。**不能用 keyword 搜索来读取进展内容** |
| 报告窗口横跨两个 W 节 | 例如 Jun 11(Thu)-17(Wed) 中，0611 在 W10，0612-0617 在 W11。需同时读覆盖窗口的所有 W 节 |
| `--scope section` 返回整个 synced-source | 请求 W11 的 section 会返回 W6-W13 全部内容（~200KB）。需客户端按 H4 block_id 过滤到目标周次 |
| 部分日期无 wiki 条目 | 周末通常不更新，节假日亦然。窗口内缺日期属正常现象 |

### 正确读取方法（已测试可行，2026-06-15）

```python
from datetime import date, timedelta
import subprocess, json, re

def get_report_window(today):
    """计算汇报窗口：上周三 → 本周二（7天）。在任何星期几运行均正确。"""
    days_since_wed = (today.weekday() - 2) % 7   # Wed=0, Thu=1, ..., Tue=6
    most_recent_wed = today - timedelta(days=days_since_wed)
    last_wed = most_recent_wed - timedelta(days=7)
    this_tue = most_recent_wed - timedelta(days=1)
    d, dates = last_wed, []
    while d <= this_tue:
        dates.append(d.strftime('%m%d'))
        d += timedelta(days=1)
    return last_wed, this_tue, dates

def extract_week_section(full_content, h4_block_id):
    """从 section 全文中按 H4 block_id 提取对应周次内容。"""
    start_pat = re.compile(r'<h4 id="' + h4_block_id + r'">')
    m = start_pat.search(full_content)
    if not m:
        return ''
    start = m.start()
    rest = full_content[start + 10:]
    m2 = re.search(r'<h4 id="[^"]+">', rest)
    return full_content[start: start + 10 + m2.start()] if m2 else full_content[start:]

# Step 1: 获取整个"周目标&进展"章节（section_block_id 固定）
result = subprocess.run(
    ['lark-cli', 'docs', '+fetch', '--api-version', 'v2',
     '--doc', 'https://xiaopeng.feishu.cn/wiki/SBUYwm8Lri9aJ6kmexFcBAuGnlh',
     '--scope', 'section', '--start-block-id', 'STymdPgAJorwXvxjsrWcJKTMnDe',
     '--format', 'json'],
    capture_output=True, text=True
)
content = json.loads(result.stdout)['data']['document']['content']

# Step 2: 找所有 H4 blocks
h4s = re.findall(r'<h4 id="([^"]+)">([^<]+)</h4>', content)

# Step 3: 计算目标日期，找覆盖的 W 节
_, _, target_dates = get_report_window(date.today())
combined_content = ''
matched_weeks = []
for bid, label in h4s:
    week_content = extract_week_section(content, bid)
    cols = set(re.findall(r'核心进展-(\d{4})', week_content))
    if cols & set(target_dates):
        combined_content += week_content
        matched_weeks.append(label.strip())

# Step 4: 提取嵌套文档 IDs（去重）
nested_doc_ids = list(dict.fromkeys(re.findall(r'doc-id="([^"]+)"', combined_content)))

# Step 5: 逐一 fetch 嵌套文档
for doc_id in nested_doc_ids:
    subprocess.run(
        ['lark-cli', 'docs', '+fetch', '--api-version', 'v2',
         '--doc', doc_id, '--doc-format', 'markdown', '--format', 'json'],
        capture_output=True, text=True
    )
```
