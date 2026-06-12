export const meta = {
  name: 'weekly-report',
  description: 'Generate weekly progress report for 李坤 (P8, 仿真算法组), optimized for 高炳涛 (P9) review. Collects meeting minutes, transcripts, chat messages, and context from the past 7 days, then synthesizes a structured report.',
  phases: [
    { title: 'Collect', detail: 'Reading daily-sync data, meeting transcripts, chat messages, memory files, and wiki context' },
    { title: 'Analyze', detail: 'Extracting structured progress per track (场景&生产, SIL, HIL, Agents)' },
    { title: 'Synthesize', detail: 'Generating report formatted for 高炳涛 preferences' },
    { title: 'Output', detail: 'Writing report to Feishu doc and archiving locally' },
  ]
}

// ─── Phase 1: COLLECT ───────────────────────────────────────────
phase('Collect')

// Agent A: Read local data — daily-sync JSONs + memory files
// Agent B: Fetch live data — chat messages + wiki docs
const [localData, liveData] = await parallel([
  () => agent(
    `你是一个数据采集助手。请完成以下任务并返回结构化结果。

## 任务 1：读取 daily-sync JSON 文件

目录：~/.claude/projects/-Users-xpeng-Documents-team/memory/daily-sync/

1. 列出该目录下所有 YYYY-MM-DD.json 文件
2. 当前日期是 ${new Date().toISOString().split('T')[0]}，计算7天前的日期（上周三）
3. 读取7天窗口内所有 daily-sync JSON 文件
4. 对每个文件，提取：
   - calendar 中的会议（summary, start_time, end_time, organizer, 参会人识别）
   - meeting_docs 中的会议纪要内容（标题、参会人、AI总结要点）
   - meeting_docs 中是否有 transcript（逐字稿）字段
   - vc_messages 中的消息链接

## 任务 2：读取 Memory 文件

读取以下文件并提取关键信息：
- ~/.claude/projects/-Users-xpeng-Documents-team/memory/current-initiatives.md（项目状态）
- ~/.claude/projects/-Users-xpeng-Documents-team/memory/team-scope.md（Q2 OKR）
- ~/.claude/projects/-Users-xpeng-Documents-team/memory/team-members.md（人员分工）
- ~/.claude/projects/-Users-xpeng-Documents-team/memory/boss-gaobingtao.md（老板偏好）
- ~/.claude/projects/-Users-xpeng-Documents-team/memory/chat-insights.md（群聊洞察）
- ~/.claude/projects/-Users-xpeng-Documents-team/memory/department-context.md（部门架构）
- ~/.claude/projects/-Users-xpeng-Documents-team/memory/personality-profiles.md（性格画像）
- ~/.claude/projects/-Users-xpeng-Documents-team/memory/meeting-reading-rules.md（纪要规则）

## 任务 3：确定汇报周期

当前日期是 ${new Date().toISOString().split('T')[0]}。
计算：
- 本周三日期（如果今天是周三就用今天，否则找最近的周三）
- 上周三日期 = 本周三 - 7天
- 汇报周期：上周三 00:00 至 本周三 12:00

## 返回格式

请返回以下结构化信息：
1. 汇报周期（起止日期）
2. 会议清单：每个会议的时间、主题、参会人、有无逐字稿、有无AI摘要、3-5条关键事实
3. Memory 摘要：Q2月目标、人员分工、项目状态、高炳涛偏好要点
4. 数据完整性：哪些天有 daily-sync 数据，哪些缺失`,
    { label: 'collect:local', phase: 'Collect' }
  ),

  () => agent(
    `你是一个数据采集助手。请完成以下任务并返回结构化结果。

## 任务 1：获取群聊消息

从以下4个关键群聊获取过去7天的消息（从上周三到本周三）：

群聊ID列表：
- oc_bb2cf097（团队群 — 仿真算法组）
- oc_763ac0a（仿真核心日会群）
- oc_e18d1d68d（算法组+高炳涛群）
- oc_a5278d3（李坤-高炳涛私聊）

对每个群聊，运行：
\`\`\`bash
lark-cli im +messages-search --query "" --chat-id <chat_id> \\
  --start "上周三日期T00:00:00+08:00" \\
  --end "本周三日期T12:00:00+08:00" \\
  --page-all --format json
\`\`\`

注意：
- 如果某个群聊ID不正确或无法访问，标注并跳过
- 从消息中提取：关键决策、技术突破、风险预警、人员变动
- 重点关注包含以下关键词的消息：进展|完成|延期|阻塞|上线|AI|问题|修复|决定|风险|缺

## 任务 2：获取上下游 Context

### 2a. 部门日会 Wiki
读取最近一周部门日会中其他组的进展：
\`\`\`bash
lark-cli docs +fetch --api-version v2 \\
  --doc "https://xiaopeng.feishu.cn/wiki/Wu6ywIOM6iEucDkmx3hcEgLHnmg" \\
  --doc-format markdown --format json
\`\`\`
关注：平台组、业务组、评估组、引擎组、硬件组、生产组的进展和风险

### 2b. Q2 Wiki（月目标对照）
\`\`\`bash
lark-cli docs +fetch --api-version v2 \\
  --doc "https://xiaopeng.feishu.cn/wiki/SBUYwm8Lri9aJ6kmexFcBAuGnlh" \\
  --doc-format markdown --format json
\`\`\`
提取：SIL/HIL/生产链路的6月目标、效率指标目标值

## 任务 3：补抓缺失的逐字稿

检查 daily-sync 中 meeting_docs 是否有 transcript 字段。
对缺失逐字稿的组内日会和核心日会，尝试获取：
\`\`\`bash
# 从会议纪要文档中找到"文字记录"链接
lark-cli docs +fetch --api-version v2 --doc "<meeting_doc_token>" --format json | \\
  grep -o 'docx/[A-Za-z0-9]\+[^"]*"[^>]*>文字记录'
\`\`\`

## 返回格式

1. 群聊关键消息（按群分组，每条消息的时间、发送者、内容摘要）
2. 上下游其他组进展摘要
3. Q2月目标基线
4. 补抓到的逐字稿（如有）`,
    { label: 'collect:live', phase: 'Collect' }
  )
])

log(`数据采集完成。localData: ${localData ? 'OK' : 'FAIL'}, liveData: ${liveData ? 'OK' : 'FAIL'}`)

// ─── Phase 2: ANALYZE ───────────────────────────────────────────
phase('Analyze')

const TRACKS = [
  {
    key: 'scene',
    name: '场景&生产',
    keywords: '场景|生产|3DGS|采集|RC路线|极速模式|场景编辑|AVM|鱼眼|泛化|GGS|WM|World Model|feedforward|海外|冻结|CLI|trigger|camera model|地面空洞',
    owners: '杨星昊,周蔚旭,裴健宏,王禹丁,靳希睿'
  },
  {
    key: 'sil',
    name: 'SIL',
    keywords: 'SIL|sil|车型泛化|fixer|Fixer|nvfixer|difix|渲染优化|ClipIQA|IQA|PSNR|复现率|评测链路|LPIPS|ref图|cross.attention|encoder|decoder',
    owners: '周冯,裴健宏,王禹丁,杨星昊'
  },
  {
    key: 'hil',
    name: 'HIL',
    keywords: 'HIL|hil|台架|节点|VM|虚拟机|慢速模式|效率比|OLM|IT部署|镜像|5080|XPU|XTest|TSMaster|多节点|瘦身|IOMMU|FLR|VIL|Chief|perception|Pose|CameraImage',
    owners: '朱啸峰,瞿鑫宇,周蔚旭'
  },
  {
    key: 'agent',
    name: 'Agents',
    keywords: 'Agent|agent|复现率Agent|Diff.Agent|代码Agent|Evaluator|prompt|提示词|误报|准确率|Doubao|DeepSeek|千问|Claude|simworld|回归测试|metric.*diff|AB对比|导航变道',
    owners: '吕文杰,郑丽娜,杨星昊,严潇竹'
  }
]

// Pipeline: each track goes through extraction → completion check
const trackAnalyses = await pipeline(
  TRACKS,
  // Stage 1: Extract facts for this track
  (track) => agent(
    `你是仿真算法组的周报分析助手。请从以下数据中提取"${track.name}"轨道的本周进展。

## 轨道信息
- 轨道名称：${track.name}
- 关键Owner：${track.owners}
- 关键词：${track.keywords}

## 数据来源
### 本地数据（daily-sync + memory）
${localData ? localData.substring(0, 15000) : '无本地数据'}

### 实时数据（群聊 + wiki）
${liveData ? liveData.substring(0, 10000) : '无实时数据'}

## 提取要求

请按以下结构提取信息：

### 1. 本周核心进展
每条进展必须包含：
- 具体做了什么（不是"讨论了"或"沟通了"）
- 谁做的（Owner名字）
- 量化结果（数字、百分比、时间）
- 与月目标的差距

### 2. 风险与阻塞
- 风险描述 + 等级（🔴严重/🟡关注/🟢正常）
- 影响范围
- 应对措施

### 3. AI 使用情况
- 本轨是否使用了AI工具？什么工具？效果如何？
- 是否有AI相关的讨论或决策？

### 4. 代码质量
- 是否有代码重构、清理、审计的进展？
- 是否有"实删代码"相关内容？

### 5. 关键时间节点
- 承诺了什么日期？当前状态（ON_TRACK/AT_RISK/DELAYED）

请只提取与"${track.name}"轨道相关的内容，忽略其他轨道的信息。
注意：高炳涛特别关注具体数字、时间节点和闭环——每条进展都要说清楚"做了什么→结果是什么→下一步是什么"。`,
    { label: `analyze:${track.key}`, phase: 'Analyze' }
  )
)

log(`${trackAnalyses.filter(Boolean).length}/${TRACKS.length} 轨道分析完成`)

// ─── Phase 3: SYNTHESIZE ────────────────────────────────────────
phase('Synthesize')

const reportContext = {
  localData: localData || '',
  liveData: liveData || '',
  trackAnalyses: trackAnalyses.filter(Boolean).map((a, i) => `## ${TRACKS[i].name}\n\n${a}`).join('\n\n---\n\n'),
}

const report = await agent(
  `你是李坤（P8，仿真算法组负责人）的周报撰写助手。请根据以下数据，生成本周汇报内容。

## 汇报对象
高炳涛（P9，仿真部负责人）
汇报时间：每周三上午

## 高炳涛的性格与偏好（必须遵守）

### 5个核心标签
务实敢言 | 结构导向 | 高频追问 | 当场拍板 | AI狂热推手

### 核心关注点（按频率排序）
1. **AI** (113次提及) — "AI能不能帮我们找一些线索？"
2. **代码质量** (92次) — "实删代码含实量还多不多？"
3. **时间/节点** (80次) — "大概要等多长时间？"
4. **闭环** (70次) — "我缺少一个闭环"
5. **效率** (38次) — "效率还能不能提升？"

### 喜欢什么
- 脉络清晰、有结构的汇报
- 每个进展有闭环：做了什么→结果是什么→下一步是什么
- 具体数字和时间节点（不是"近期""下周"这种模糊表述）
- 风险有等级、有应对、有Owner

### 讨厌什么
- "散装"汇报 — 罗列任务但看不出主线
- "凌乱" — 没有小结、抓不住脉络
- "假毕业" — 说完成了但实际上没完成
- 过于微观的技术细节（"这个太细了，你不用说了"）

### 什么会触发追问（要主动回答）
- 缺时间节点 → 每个关键事项必须有预计完成日期
- 看不到闭环 → 每个进展必须说明"下一步"
- 资源不清晰 → 需要多少人/卡/时间要说清楚
- 提到AI → 他会追问细节，AI相关内容要详实

### 什么会让他沉默（说明满意）
- 汇报有结构、进度正常

## 写作规则（必须遵守）

1. **不写人名评价** — 可以写谁做了什么，不写对个人的评价
2. **精准scope** — 聚焦仿真算法组的闭环仿真，不写其他组的业务
3. **不要AI腔** — 禁止使用：已具备独立交付能力、AI Native角色、形成可复用的范式、赋能、抓手、闭环思维、颗粒度
4. **写短** — 砍到要点，只写判断和结论
5. **自测**：这句话像你跟高炳涛当面汇报时说的吗？不像就改。

---

## 各轨道分析数据

${reportContext.trackAnalyses}

## 其他数据

### 本地数据摘要
${reportContext.localData.substring(0, 5000)}

### 实时数据摘要
${reportContext.liveData.substring(0, 3000)}

---

## 报告格式要求

请生成以下结构的周报（Markdown格式）：

\`\`\`markdown
## 仿真算法组 周报 ({start_date} — {end_date})

### 一、总体脉络
[3-5句连贯叙述]
- 本周主线是什么？
- 最重要的1-2个进展？
- 最大的风险是什么？
- 整体判断：正常/有风险/有阻塞

### 二、四轨进展

#### 场景&生产
| 月目标 | 本周核心进展 | 风险 |
|--------|------------|------|
| [从Q2 wiki提取] | [具体进展+数字+Owner] | [🔴/🟡/🟢] |

#### SIL
[同上格式]

#### HIL
[同上格式]

#### Agents
[同上格式]

### 三、跨轨关注

#### 🤖 AI使用情况
[本周AI在哪些环节被使用？什么工具/模型？效果如何？成本？]
[高炳涛本周提到AI的次数和内容]

#### 📝 代码质量
[代码重构/清理/审计的进展]
[实删代码情况]
[高炳涛本周提到的代码质量相关要求]

#### 📊 效率指标
| 指标 | 上周 | 本周 | 变化 | 6月目标 |
|------|------|------|------|---------|
| SIL复现率 | - | - | - | 80%+ |
| HIL效率比 | - | - | - | 1:3 |
| 台架节点数 | - | - | - | 5台 |
| 场景集完成率 | - | - | - | 90%+ |

#### ⏰ 关键节点
| 节点 | 承诺日期 | 状态 | 风险 |
|------|---------|------|------|
| ... | YYYY-MM-DD | ON_TRACK/AT_RISK/DELAYED | ... |

### 四、总体风险
| 风险 | 等级 | 影响 | 应对 | Owner |
|------|:--:|------|------|-------|
| ... | 🔴/🟡/🟢 | ... | ... | ... |

### 五、跨组依赖
| 依赖项 | 依赖方 | 本周状态 | 阻塞？ |
|--------|--------|---------|:--:|
| ... | [平台组/业务组/硬件组/...] | ... | 是/否 |

### 六、下周重点
- [3-5个最重要的事项]
\`\`\`

## 质量自检（输出前必须确认）

- [ ] 每轨有月目标
- [ ] 每条进展有具体数字和Owner
- [ ] AI使用在跨轨关注中显式列出
- [ ] 代码质量在跨轨关注中显式列出
- [ ] 每个风险有等级+应对+Owner
- [ ] 关键节点有具体日期和状态
- [ ] 总体脉络是连贯叙述（非bullet list）
- [ ] 零AI腔（无"赋能""抓手""已具备独立交付能力"等）
- [ ] 所有"近期""下周"改为具体日期
- [ ] 有闭环：做了什么→结果→下一步

请直接输出最终的周报Markdown内容，不要输出其他说明。`,
  { label: 'synthesize', phase: 'Synthesize' }
)

log(`报告合成完成，长度: ${report ? report.length : 0} 字符`)

// ─── Phase 4: OUTPUT ────────────────────────────────────────────
phase('Output')

const outputResult = await agent(
  `你是周报输出助手。请将以下周报内容写入飞书文档。

## 要写入的周报内容

${report}

## 操作步骤

### Step 1: 检查是否存在周报文档
读取文件：~/.claude/projects/-Users-xpeng-Documents-team/memory/weekly-report-doc.md
查看其中是否记录了飞书文档URL。

### Step 2a: 如果已有文档URL
使用 lark-cli 追加内容：
\`\`\`bash
lark-cli docs +update --api-version v2 \\
  --doc "<已有的文档URL>" \\
  --command append \\
  --content '<周报Markdown内容>' \\
  --format json
\`\`\`

### Step 2b: 如果没有文档URL
创建新文档：
\`\`\`bash
lark-cli docs +create --api-version v2 \\
  --content '<title>仿真算法组 周报</title><p>周报文档，每周三更新</p>' \\
  --format json
\`\`\`
从输出中提取文档URL，写入 weekly-report-doc.md。

然后用 Step 2a 的命令追加本周周报。

### Step 3: 存档
将周报Markdown内容保存到：
~/.claude/projects/-Users-xpeng-Documents-team/memory/weekly-reports/{today-date}.md

### Step 4: 更新 Memory
更新 ~/.claude/projects/-Users-xpeng-Documents-team/memory/weekly-report-doc.md，在"历史报告"部分追加：
- [{today-date}] 周报已生成，文档URL: <url>

---

## 重要提示
- 写入文档时，如果内容太长（>5000字符），请分段 append
- 每段之间加空行分隔
- 注意 Markdown 在飞书文档中的渲染效果
- 完成后返回：文档URL + 写入状态 + 存档路径`,
  { label: 'output', phase: 'Output' }
)

log(`输出完成: ${outputResult ? 'OK' : 'FAIL'}`)

// ─── Return summary ─────────────────────────────────────────────
return {
  period: 'weekly',
  report: report,
  output: outputResult,
  trackCount: trackAnalyses.filter(Boolean).length,
}
