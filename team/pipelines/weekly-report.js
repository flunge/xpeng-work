export const meta = {
  name: 'weekly-report',
  description: 'Generate weekly progress report for 李坤 (P8, 仿真算法组), optimized for 高炳涛 (P9) review. 数据源全部在飞书（作战表/日报/会议纪要机器人群/项目 ledger），本地不存任何内容。',
  phases: [
    { title: 'Collect', detail: '从飞书读：作战表 + 日报 + 会议纪要机器人群 + 各项目 ledger + IM 群聊' },
    { title: 'Analyze', detail: '按四轨（场景&生产/SIL/HIL/Agents）提取结构化进展' },
    { title: 'Synthesize', detail: '按高炳涛偏好合成结构化周报' },
    { title: 'Output', detail: '写入飞书周报文档（不在本地存档）' },
  ]
}

// 规则/关联位置（本地只留规则+关联，内容全在飞书）：
//   规则：/workspace/.claude/team/（rules / commands / refs / insights / INDEX.md）
//   飞书关联：/workspace/team/memory/_feishu_map.json（项目名→飞书 token；root_folder=W7rqfwqnnlzSfUdEcIGcjcTNnqe）
// 关键 token（另见 .claude/team/refs/tokens.md）：
//   日报 Wu6ywIOM6iEucDkmx3hcEgLHnmg ｜ Q3作战表 SBUYwm8Lri9aJ6kmexFcBAuGnlh
//   会议纪要机器人群 oc_56b10049700694038662e72aa78e35d3
const FEISHU_MAP = '/workspace/team/memory/_feishu_map.json'
const RULES_DIR = '/workspace/.claude/team'

// ─── Phase 1: COLLECT（全部从飞书 / lark-cli 读，无本地记忆依赖）──────
phase('Collect')

const [wartableData, imData] = await parallel([
  () => agent(
    `你是数据采集助手，数据源全部在飞书，用 lark-cli（--as user）读。返回结构化结果。

## 汇报窗口
当前日期 ${new Date().toISOString().split('T')[0]}。窗口=上周五 00:00 → 本周五 12:00（与算法组周会对齐）。先算出起止日期。

## 任务 1：Q3 作战表（主数据源）
\`lark-cli docs +fetch --doc SBUYwm8Lri9aJ6kmexFcBAuGnlh --scope section --start-block-id STymdPgAJorwXvxjsrWcJKTMnDe --format json\`
找覆盖窗口日期的 W## 节，逐日「核心进展」列 + 周目标 + 风险行，按四轨（场景&生产/SIL/HIL/Agents）分组。**逐日 cell 贴的图必须下载读全**（规则见 ${RULES_DIR}/rules/sourcing.md §4）。

## 任务 2：仿真核心日会日报
\`lark-cli docs +fetch --doc Wu6ywIOM6iEucDkmx3hcEgLHnmg --scope outline\` 定位窗口内日期段，逐段读全。

## 任务 3：各项目 ledger（飞书）
读 ${FEISHU_MAP} 的 projects 段拿各项目飞书 token，对每个 token \`lark-cli docs +fetch --doc <token> --doc-format markdown\`，提取「当前状态」+「持续进展」窗口内条目 +「风险」。

## 任务 4：嵌套文档
上述内容里出现的 doc-id/wiki token 全量提取去重，逐个 fetch 读全（doc-id 出现≠读过）。

## 返回
1. 汇报窗口起止；2. 四轨各项目本周进展（进展+数字+Owner+来源）；3. 风险汇总（等级+Owner+来源）；4. 关键节点及状态；5. 数据完整性（哪些 ledger 有本周条目、哪些空）。`,
    { label: 'collect:wartable', phase: 'Collect' }
  ),

  () => agent(
    `你是数据采集助手，用 lark-cli（--as user）从飞书拉 IM。返回结构化结果。

## 汇报窗口
当前 ${new Date().toISOString().split('T')[0]}，窗口=上周五 00:00 → 本周五 12:00。时间必须带 +08:00 时区偏移。

## 任务 1：会议纪要机器人群（当窗口全部会议纪要来源）
\`lark-cli im +chat-messages-list --chat-id oc_56b10049700694038662e72aa78e35d3 --start "<起>T00:00:00+08:00" --end "<止>T12:00:00+08:00" --page-size 50\`
逐条提 docx token → fetch 读全（含逐字稿"文字记录"链接）。

## 任务 2：核心群 + 老板 p2p（群/p2p id 见 ${RULES_DIR}/refs/tokens.md）
仿真算法组 oc_bb2cf097e2d3efc34a4bc37ebd9225d9、核心日会 oc_763ac0acd21f75e04d9945fcc139c5c1、算法组+高炳涛 oc_e18d1d68d26c17f45f3ce3492e5143fe、李坤-高炳涛 p2p oc_a5278d3009a2142eaaa57c3bd9821aec。
\`im +chat-messages-list\` 不支持 --page-all，用 --page-size 50 + --page-token 循环。提取：关键决策/技术突破/风险预警/人员变动（关键词 进展|完成|延期|阻塞|上线|AI|问题|修复|决定|风险|缺）。

## 任务 3：项目关键词跨群搜（核心群之外的跨组讨论）
对活跃项目用 \`im +messages-search --query <关键词如 车型/HIL/极速/复现率> --start "<起>+08:00" --end "<止>+08:00" --page-all\`。

## 返回
1. 群聊关键消息（按群分组：时间/发送者/摘要）；2. 老板本窗口发言与指令；3. 跨组依赖/风险。`,
    { label: 'collect:im', phase: 'Collect' }
  )
])

log(`采集完成。wartable: ${wartableData ? 'OK' : 'FAIL'}, im: ${imData ? 'OK' : 'FAIL'}`)

// ─── Phase 2: ANALYZE ───────────────────────────────────────────
phase('Analyze')

const TRACKS = [
  { key: 'scene', name: '场景&生产', keywords: '场景|生产|3DGS|采集|RC路线|极速模式|场景编辑|AVM|鱼眼|泛化|WM|World Model|feedforward|海外|CLI|trigger|camera model', owners: '杨星昊,周蔚旭,裴健宏,王禹丁' },
  { key: 'sil', name: 'SIL', keywords: 'SIL|车型泛化|fixer|nvfixer|difix|渲染优化|ClipIQA|IQA|PSNR|复现率|评测链路|LPIPS|ref图|encoder|decoder', owners: '周冯,裴健宏,王禹丁,杨星昊' },
  { key: 'hil', name: 'HIL', keywords: 'HIL|台架|节点|VM|慢速模式|效率比|OLM|镜像|5080|XPU|XTest|VIL|Chief|Pose|CameraImage|RTM', owners: '朱啸峰,瞿鑫宇,周蔚旭' },
  { key: 'agent', name: 'Agents', keywords: 'Agent|复现率Agent|Diff.Agent|Evaluator|prompt|提示词|误报|准确率|Doubao|DeepSeek|千问|simworld|回归测试|OnCall', owners: '吕文杰,郑丽娜,杨星昊,严潇竹' }
]

const trackAnalyses = await pipeline(
  TRACKS,
  (track) => agent(
    `你是仿真算法组周报分析助手。从采集数据中提取"${track.name}"轨道的本周进展。

## 轨道
名称：${track.name}｜关键 Owner：${track.owners}｜关键词：${track.keywords}

## 数据来源
### 作战表 + 日报 + ledger（主数据源）
${wartableData ? wartableData.substring(0, 20000) : '无'}
### IM 补充（群聊 + 搜索）
${imData ? imData.substring(0, 8000) : '无'}

## 规则
优先级：作战表/ledger 窗口条目 > 日报 > 群聊；不捏造数字、不把他轨内容混入、不从背景推断进展。
写作/质检规则见 ${RULES_DIR}/rules/sourcing.md、${RULES_DIR}/insights/quality-rules.md。

## 提取结构
1. 本周核心进展（做了什么+Owner+量化结果+来源）；2. 当前状态（项目→一句话）；3. 风险与阻塞（描述+等级🔴🟡🟢+Owner+来源）；4. 关键时间节点（承诺日期+ON_TRACK/AT_RISK/DELAYED）。只保留本轨内容。`,
    { label: `analyze:${track.key}`, phase: 'Analyze' }
  )
)

log(`${trackAnalyses.filter(Boolean).length}/${TRACKS.length} 轨道分析完成`)

// ─── Phase 3: SYNTHESIZE ────────────────────────────────────────
phase('Synthesize')

const trackText = trackAnalyses.filter(Boolean).map((a, i) => `## ${TRACKS[i].name}\n\n${a}`).join('\n\n---\n\n')

const report = await agent(
  `你是李坤（P8，仿真算法组负责人）的周报撰写助手。据以下数据生成周报。汇报对象=高炳涛（P9）。

## 高炳涛偏好（必守）
核心关注（按频率）：AI > 代码质量 > 时间/节点 > 闭环 > 效率。
喜欢：脉络清晰有结构、每进展有闭环（做了什么→结果→下一步）、具体数字与日期、风险有等级+应对+Owner。
讨厌：散装罗列、无小结、假毕业、过细技术。缺时间节点/看不到闭环/资源不清/提到AI 会触发追问，要主动答全。

## 写作规则（必守，详见 ${RULES_DIR}/rules/report-writing.md）
不写人名评价；精准 scope（只写本组闭环仿真）；零 AI 腔（禁"赋能/抓手/已具备独立交付能力/闭环思维/颗粒度"等）；写短；自测"这像当面汇报的话吗"。

## 各轨分析
${trackText}

## 采集摘要
${(wartableData || '').substring(0, 5000)}
${(imData || '').substring(0, 3000)}

## 报告格式（Markdown）
一、总体脉络（3-5句连贯叙述：主线/最重要1-2进展/最大风险/整体判断）
二、四轨进展（每轨表格：月目标｜本周核心进展｜风险）
三、跨轨关注（🤖AI使用 / 📝代码质量 / 📊效率指标表 / ⏰关键节点表）
四、总体风险（风险｜等级｜影响｜应对｜Owner）
五、跨组依赖（依赖项｜依赖方｜状态｜是否阻塞）
六、下周重点（3-5项）

输出前自检：每轨有月目标、每进展有数字+Owner、AI与代码质量显式列出、风险有等级+应对+Owner、节点有日期+状态、脉络是连贯叙述、零AI腔、"近期/下周"改具体日期、有闭环。直接输出周报 Markdown。`,
  { label: 'synthesize', phase: 'Synthesize' }
)

log(`合成完成，长度: ${report ? report.length : 0} 字符`)

// ─── Phase 4: OUTPUT（只写飞书，不在本地存档）────────────────────
phase('Output')

const outputResult = await agent(
  `你是周报输出助手。把以下周报写入飞书文档（**不在本地存任何副本**）。

## 周报内容
${report}

## 步骤
1. 周报文档 token 从 ${FEISHU_MAP} 的 weekly-reports 段取（若无则 \`lark-cli docs +create\` 建新文档、把 token 回写进 _feishu_map.json 的 weekly-reports 段）。
2. \`lark-cli docs +update --doc <token> --command append --content '<周报>'\` 追加（>5000 字符分段 append，段间空行）。
3. 遵循 ${RULES_DIR}/rules/writing.md 的安全编辑：写后 fetch 复查内容在且正确。
4. 发布前过闸：\`python3 /workspace/team/scripts/preflight.py <token> --audience boss\`。
5. 完成返回：文档 URL + 写入状态 + 闸结果。**不写本地存档**。`,
  { label: 'output', phase: 'Output' }
)

log(`输出完成: ${outputResult ? 'OK' : 'FAIL'}`)

return {
  period: 'weekly',
  report: report,
  output: outputResult,
  trackCount: trackAnalyses.filter(Boolean).length,
}
