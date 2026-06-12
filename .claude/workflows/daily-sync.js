export const meta = {
  name: 'daily-sync',
  description: '处理 daily-sync JSON，从源文档（逐字稿/IM/文档）中提取事实并更新所有 memory 文件。JSON 只是索引，源文档才是事实。',
  phases: [
    { title: '盘点', detail: '列出所有待读取的源文档 URL' },
    { title: '读源文档', detail: '逐篇读取会议逐字稿+智能纪要+Wiki+聊天链接文档' },
    { title: '聊天上下文', detail: '补读父消息和消息中链接的文档' },
    { title: '人物画像分析', detail: '从逐字稿和IM提取每人行为/性格观察' },
    { title: '记忆写入', detail: '更新 members/*.md, current-initiatives.md, chat-insights.md' },
    { title: '自检', detail: '逐条核查三不写，确认每条事实有出处' },
  ],
}

// ============================================================
// 读取 daily-sync JSON，这只是索引
// ============================================================
phase('盘点')

const SYNC_DIR = args.syncDir || `${Deno.env.get('HOME')}/.claude/projects/-Users-xpeng-Documents-team/memory/daily-sync`
const MEMORY_DIR = args.memoryDir || `${Deno.env.get('HOME')}/.claude/projects/-Users-xpeng-Documents-team/memory`
const DATE = args.date || '2026-06-11'

// Step 1: 读取 JSON 索引
const jsonPath = `${SYNC_DIR}/${DATE}.json`
const rawJson = await agent(`Read the daily-sync JSON file at ${jsonPath} and extract ALL of the following into a structured inventory:

1. **Meeting docs** (from meeting_docs / vc_messages): For EACH meeting doc URL, also check the document for a "文字记录" (transcript) link. List BOTH the summary URL AND the transcript URL.

2. **Wiki doc**: The wiki document content and revision info.

3. **IM @me messages**: Every message that @mentioned the user. For each:
   - Does it contain a feishu/docx/wiki URL? Extract it.
   - Does it have a reply_to parent message ID? Extract it.

4. **IM member searches**: For each team member, list what they said, and note if any message contains URLs.

5. **Calendar events**: List all events with organizer, time, topic.

Return a detailed inventory with every URL that needs to be read, categorized as:
- TRANSCRIPT_URLS (meeting transcripts - HIGHEST PRIORITY)
- SUMMARY_URLS (meeting summaries)
- WIKI_URLS
- CHAT_DOC_URLS (docs linked in chat messages)
- PARENT_MSG_IDS (parent messages to fetch for context)
`, { label: '盘点源文档', schema: {
  type: 'object',
  properties: {
    date: { type: 'string' },
    transcriptUrls: { type: 'array', items: { type: 'string' } },
    summaryUrls: { type: 'array', items: { type: 'string' } },
    wikiUrls: { type: 'array', items: { type: 'string' } },
    chatDocUrls: { type: 'array', items: { type: 'string' } },
    parentMsgIds: { type: 'array', items: { type: 'string' } },
    calendarEvents: { type: 'array', items: { type: 'object' } },
    atMeSummary: { type: 'string' },
    memberActivitySummary: { type: 'string' },
  },
  required: ['transcriptUrls', 'summaryUrls']
}})

if (!rawJson) { log('❌ 无法读取 daily-sync JSON'); throw new Error('SYNC_JSON_READ_FAILED') }

const inventory = rawJson
log(`📋 盘点完成: ${inventory.transcriptUrls?.length || 0} 篇逐字稿, ${inventory.summaryUrls?.length || 0} 篇纪要, ${inventory.wikiUrls?.length || 0} 篇Wiki, ${inventory.chatDocUrls?.length || 0} 个聊天文档链接, ${inventory.parentMsgIds?.length || 0} 条父消息待补读`)

// ============================================================
// Phase 2: 读所有源文档（逐字稿优先级最高）
// ============================================================
phase('读源文档')

// 2a: 先并行读所有会议逐字稿（最高优先级）
const transcripts = await pipeline(
  (inventory.transcriptUrls || []).map((url, i) => ({ url, index: i, label: `逐字稿#${i+1}` })),
  async (item) => {
    const content = await agent(
      `Read this meeting transcript in markdown format using: lark-cli docs +fetch --api-version v2 --doc "${item.url}" --doc-format markdown --format json

Extract:
1. Who said what (exact quotes where possible) — especially 高炳涛, 李坤, and our team members
2. Tone, urgency, and real concerns (not AI-summarized)
3. Decision points and who made them
4. Any personality/behavior observations

CRITICAL: This is a TRANSCRIPT (逐字稿), not an AI summary. Read individual voices.`,
      { label: item.label, phase: '读源文档', schema: {
        type: 'object',
        properties: {
          url: { type: 'string' },
          keyQuotes: { type: 'array', items: { type: 'object', properties: {
            speaker: { type: 'string' },
            quote: { type: 'string' },
            context: { type: 'string' },
          }}},
          decisions: { type: 'array', items: { type: 'string' } },
          personalityObservations: { type: 'array', items: { type: 'object', properties: {
            person: { type: 'string' },
            observation: { type: 'string' },
            evidence: { type: 'string' },
          }}},
          teamMemberMentions: { type: 'array', items: { type: 'string' } },
        },
        required: ['keyQuotes', 'decisions']
      }}
    )
    return content
  }
)

// 2b: 并行读所有智能纪要 + Wiki
const [summaries, wikiDocs] = await Promise.all([
  parallel(
    (inventory.summaryUrls || []).map((url, i) => () =>
      agent(
        `Read this meeting summary in markdown: lark-cli docs +fetch --api-version v2 --doc "${url}" --doc-format markdown --format json
Extract: agenda, conclusions, action items with assignees, key topics. Also find the "相关链接 → 文字记录" link if present.`,
        { label: `纪要#${i+1}`, phase: '读源文档', schema: {
          type: 'object',
          properties: {
            url: { type: 'string' },
            topic: { type: 'string' },
            conclusions: { type: 'array', items: { type: 'string' } },
            actionItems: { type: 'array', items: { type: 'object', properties: {
              task: { type: 'string' }, assignee: { type: 'string' },
            }}},
            transcriptLink: { type: 'string' },
          },
          required: ['topic', 'actionItems']
        }}
      )
    )
  ),
  parallel(
    (inventory.wikiUrls || []).map((url, i) => () =>
      agent(
        `Read this Wiki document in markdown: lark-cli docs +fetch --api-version v2 --doc "${url}" --doc-format markdown --format json
Summarize: title, key content, what changed, relevance to our team.`,
        { label: `Wiki#${i+1}`, phase: '读源文档' }
      )
    )
  ),
])

log(`✅ 源文档读取完成: ${transcripts.filter(Boolean).length} 逐字稿, ${summaries.filter(Boolean).length} 纪要, ${wikiDocs.filter(Boolean).length} Wiki`)

// ============================================================
// Phase 3: 聊天上下文补读
// ============================================================
phase('聊天上下文')

// 3a: 补读父消息
const parentMsgs = await parallel(
  (inventory.parentMsgIds || []).map((id) => () =>
    agent(
      `Read the parent message with ID "${id}" using: lark-cli im +messages-mget --message-ids "${id}" --format json
Return the full message content, sender, and context.`,
      { label: `父消息:${id.slice(-8)}`, phase: '聊天上下文' }
    )
  )
)

// 3b: 读聊天中链接的文档
const chatDocs = await parallel(
  (inventory.chatDocUrls || []).map((url, i) => () =>
    agent(
      `Read this document linked in chat: lark-cli docs +fetch --api-version v2 --doc "${url}" --doc-format markdown --format json
Summarize the content and explain what it reveals about the chat context.`,
      { label: `聊天文档#${i+1}`, phase: '聊天上下文' }
    )
  )
)

log(`✅ 聊天上下文: ${parentMsgs.filter(Boolean).length} 父消息, ${chatDocs.filter(Boolean).length} 聊天文档`)

// ============================================================
// Phase 4: 人物画像分析（核心能力）
// ============================================================
phase('人物画像分析')

// 收集所有源文档内容，对每个在岗组员+高炳涛做画像分析
const TEAM_MEMBERS = [
  '郑丽娜', '杨星昊', '周蔚旭', '裴健宏', '周冯',
  '吕文杰', '王禹丁', '朱啸峰', '瞿鑫宇', '靳希睿', '严潇竹',
]
const KEY_PEOPLE = [...TEAM_MEMBERS, '高炳涛', '李坤']

const personalityUpdates = await pipeline(
  KEY_PEOPLE.map(name => ({ name })),
  async ({ name }) => {
    // 从所有已读源文档中提取关于此人的观察
    const allTranscriptObservations = transcripts
      .filter(Boolean)
      .flatMap(t => (t.personalityObservations || []).filter(o => o.person === name))

    const allQuotes = transcripts
      .filter(Boolean)
      .flatMap(t => (t.keyQuotes || []).filter(q => q.speaker === name))

    if (allTranscriptObservations.length === 0 && allQuotes.length === 0) {
      return { name, hasNewObservations: false }
    }

    // 读取现有人物画像
    const existingProfile = await agent(
      `Read the existing memory file for ${name} at ${MEMORY_DIR}/members/${name.toLowerCase()}-*.md or similar.
If the file doesn't exist, note that. Extract the existing personality tags, communication style notes, and behavior observations.`,
      { label: `读现画像:${name}`, phase: '人物画像分析' }
    )

    // 综合分析新观察
    const analysis = await agent(
      `You are analyzing ${name}'s behavior and personality based on today's meeting transcripts and chat messages.

**Existing profile knowledge:**
${existingProfile || 'No existing profile'}

**New observations from today's transcripts:**
${JSON.stringify(allTranscriptObservations, null, 2)}

**Direct quotes from ${name} today:**
${JSON.stringify(allQuotes, null, 2)}

**From chat messages (check inventory):**
${inventory.memberActivitySummary || 'No chat data'}

Analyze:
1. What new behavior/personality patterns are visible today?
2. Does anything contradict or refine the existing profile?
3. What should be ADDED or UPDATED in their memory file?
4. Specific evidence (quote, action, decision) for each update.

Focus on: communication style, decision-making patterns, technical depth, leadership behaviors, reactions to pressure, collaboration patterns.`,
      { label: `分析画像:${name}`, phase: '人物画像分析', schema: {
        type: 'object',
        properties: {
          name: { type: 'string' },
          hasNewObservations: { type: 'boolean' },
          newTags: { type: 'array', items: { type: 'string' } },
          updatesToProfile: { type: 'array', items: { type: 'object', properties: {
            section: { type: 'string' },
            oldContent: { type: 'string' },
            newContent: { type: 'string' },
            evidence: { type: 'string' },
          }}},
          notableQuote: { type: 'string' },
          overallAssessment: { type: 'string' },
        },
        required: ['hasNewObservations']
      }}
    )
    return analysis
  }
)

const significantUpdates = personalityUpdates.filter(Boolean).filter(p => p.hasNewObservations)
log(`🧠 人物画像: ${significantUpdates.length} 人有新观察 (${significantUpdates.map(p => p.name).join(', ')})`)

// ============================================================
// Phase 5: 记忆写入（每条事实有出处）
// ============================================================
phase('记忆写入')

// 5a: 更新每个人的 memory 文件
const memberUpdates = await parallel(
  significantUpdates.map(update => () => {
    const memberFileName = {
      '郑丽娜': 'zheng-lina', '杨星昊': 'yang-xinghao', '周蔚旭': 'zhou-weixu',
      '裴健宏': 'pei-jianhong', '周冯': 'zhou-feng', '吕文杰': 'lv-wenjie',
      '王禹丁': 'wang-yuding', '朱啸峰': 'zhu-xiaofeng', '瞿鑫宇': 'qu-xinyu',
      '靳希睿': 'jin-xirui', '严潇竹': 'yan-xiaozhu',
      '高炳涛': '../boss-gaobingtao', '李坤': '../likun-role',
    }[update.name] || update.name.toLowerCase()

    return agent(
      `Update the memory file at ${MEMORY_DIR}/members/${memberFileName}.md with these changes:

**Person to update:** ${update.name}
**Changes to apply:**
${JSON.stringify(update.updatesToProfile, null, 2)}

**Rules for writing:**
- Each update must reference the specific source (meeting date, chat time)
- Don't delete existing content, add/refine
- For personality tags: add new ones if genuinely new patterns emerge
- For progress updates: add date-stamped entries under the appropriate section
- Preserve the existing file structure

Read the current file first, then edit it.`,
      { label: `写入:${update.name}`, phase: '记忆写入' }
    )
  })
)

// 5b: 更新 current-initiatives.md
await agent(
  `Read ${MEMORY_DIR}/current-initiatives.md, then update it with today's verified facts.

**Source materials (verified from transcripts/summaries):**
Meeting summaries: ${JSON.stringify(summaries.filter(Boolean).map(s => ({topic: s.topic, conclusions: s.conclusions, actionItems: s.actionItems})))}

**Rules:**
1. Every claim must be traceable to a specific source document
2. Update project status, milestones, risks with date stamps
3. Add new risks if discovered today
4. Mark the update date as ${DATE}

Write the updates.`,
  { label: '更新项目进展', phase: '记忆写入' }
)

// 5c: 更新 chat-insights.md
await agent(
  `Read ${MEMORY_DIR}/chat-insights.md, then update with today's chat observations.

**Chat context:**
- @me messages: ${inventory.atMeSummary || 'None'}
- Parent messages: ${JSON.stringify(parentMsgs.filter(Boolean))}
- Chat documents read: ${JSON.stringify(chatDocs.filter(Boolean))}
- Member activity: ${inventory.memberActivitySummary || 'None'}

**Rules:**
1. Only record decisions, milestones, personnel changes — not routine chat
2. Each entry must have date, event description, and initiator
3. Link to source message or document

Write the updates.`,
  { label: '更新群聊洞察', phase: '记忆写入' }
)

log(`📝 记忆文件已更新`)

// ============================================================
// Phase 6: 自检（三不写核查）
// ============================================================
phase('自检')

const selfCheck = await agent(
  `Perform a self-check on ALL memory updates made today. For each claim written to memory:

1. Can I point to the exact source document/message?
2. Did I read the source, or did I infer from a summary?
3. Are there any linked documents I should have read but didn't?
4. Specific check: "What exactly did 高炳涛 say in today's meetings?" — if I can't quote him, I didn't read the transcript.

Also check:
- Did I update all team members who had activity today? (Members with chat activity: ${inventory.memberActivitySummary || 'check inventory'})
- Did I miss any meeting transcript?
- Are there chat messages with URLs I didn't read?

Return a verification report with:
- PASS items (source-backed facts)
- WARN items (uncertain provenance)
- FAIL items (must fix — inferred without reading source)
- Any sources I still need to read`,
  { label: '三不寫自檢', phase: '自检', schema: {
    type: 'object',
    properties: {
      passCount: { type: 'number' },
      warnItems: { type: 'array', items: { type: 'string' } },
      failItems: { type: 'array', items: { type: 'string' } },
      unreadSources: { type: 'array', items: { type: 'string' } },
      canAnswerBossQuestion: { type: 'boolean' },
      bossQuote: { type: 'string' },
      overallVerdict: { type: 'string', enum: ['PASS', 'FIX_REQUIRED'] },
    },
    required: ['passCount', 'failItems', 'overallVerdict']
  }}
)

if (selfCheck.overallVerdict === 'FIX_REQUIRED') {
  log(`⚠️ 自检未通过: ${selfCheck.failItems.length} 条需修复`)
  log(`失败项: ${selfCheck.failItems.join('; ')}`)
}

if (!selfCheck.canAnswerBossQuestion) {
  log(`🔴 无法回答"高炳涛说了什么" — 逐字稿未读或未充分提取`)
}

log(`✅ 自检完成: ${selfCheck.passCount} 条通过, ${selfCheck.failItems?.length || 0} 条需修复, 老板关键语录: "${selfCheck.bossQuote || '未提取'}"`)

// ============================================================
// 最终：更新 .last-processed
// ============================================================
log(`🏁 Daily sync ${DATE} 处理完成`)
log(`  - 逐字稿: ${transcripts.filter(Boolean).length} 篇`)
log(`  - 纪要: ${summaries.filter(Boolean).length} 篇`)
log(`  - 人物画像更新: ${significantUpdates.length} 人`)
log(`  - 自检: ${selfCheck.overallVerdict}`)

return {
  date: DATE,
  transcriptsRead: transcripts.filter(Boolean).length,
  summariesRead: summaries.filter(Boolean).length,
  wikiDocsRead: wikiDocs.filter(Boolean).length,
  chatDocsRead: chatDocs.filter(Boolean).length,
  personalityUpdates: significantUpdates.length,
  selfCheckVerdict: selfCheck.overallVerdict,
  bossQuote: selfCheck.bossQuote,
}
