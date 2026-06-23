/**
 * GIC双周报 Workflow v4
 *
 * 为仿真算法组（李坤）生成GIC双周会汇报板块。
 *
 * 风格规范（来自 memory/gic-report-style.md）：
 *   1. 每节3-5 bullet + 1张GPT-Image-2图 — 核心信息在图里
 *   2. column/grid 排版，不用段落——刘先明没时间看长文
 *   3. 可参考其他组内容扩充，但限于算法组范围
 *   4. 不用内嵌文档，细节展开在正文
 *   5. 不谈WM竞争
 *
 * 配图流程（见 memory/image-agent.md）：
 *   生图(SoCheap) → 存本地 → 【贴图】占位 → 用户 /image 手动上传
 *
 * API: POST https://socheap.ai/media/generations
 *   model: gpt-image-2, 1024x576, 中文prompt, ~$0.03/张
 *   KEY: 从环境变量 MEDIA_API_KEY 或 pipelines/media_key.txt（git-ignored）读取，勿在代码/文档中写明文
 */

export const meta = {
  name: 'gic-report-v4',
  description: '仿真算法组GIC双周报。每节bullet+grid+GPT-Image-2图，column排版，核心信息在图内。',
  phases: [
    { title: 'Collect', detail: '采集两周数据' },
    { title: 'Analyze', detail: '提炼≤3个主题' },
    { title: 'Generate', detail: '生成grid/bullet + GPT-Image-2提示 + 写入' },
  ],
}

const TEAM_USER_IDS = {
  '郑丽娜':'ou_279a0e5c146848e3d2dfaefe85f2c505','杨星昊':'ou_b41c33085d2e629fbdff0c555cae0a3f',
  '周蔚旭':'ou_8780e6b813f605e4e3850a6b98b998c3','裴健宏':'ou_0c6500bc5981b6b0f14b9a716489091d',
  '周冯':'ou_7f6f5a26081a94ee1b0455a2e0a80fc0','吕文杰':'ou_65a5111eef3b9eb35a6f7d8d5b297a8c',
  '王禹丁':'ou_e58e3b3df19501f07c57e2773cc28f28','朱啸峰':'ou_09b6f76c8d98f186bb7163406fe3894a',
  '瞿鑫宇':'ou_3e961bf385c2624ddac97b54d2f1746d','冯美慧':'ou_583951f17f0e80484d0d81e08806999f',
  '靳希睿':'ou_0d77b376fea09975c0cc5c2e87f13d7d','严潇竹':'ou_9b65b8c67807ce544a5cef3efe5cbf8a',
  '高炳涛':'ou_8bcf2bb3c23a679a7c19bfcc80b4cdda','邓爽':'ou_0c29f42f96320d32e36b8616342955ef',
  '徐林鵾':'ou_a58ef3fb16b75da0adf725cf4e1157a5','赖西湖':'ou_795c727d71c02a25501a3fd4d2af540c',
  '黄佰民':'ou_312299a178f9e0fbcf53b2262000509b','刘开拓':'ou_5ff13a6d397bcb698bbfb66800fbb83a',
  '夏志勋':'ou_4e4a0102b41b6feb1a7043ec45dfad40','李元龙':'ou_68d278a961f613fa30d742c09cf4604e',
  '樊世洲':'ou_f1e8a45a54c418ef0aaef2d38dffb6f','李坤':'ou_f9cd23092a356c297d6a9f38fd7cfd5e',
}

const IMAGE_DIR = Deno.env.get('GIC_IMAGE_DIR') || new URL('../projects/GIC_report', import.meta.url).pathname
// API key：优先环境变量 MEDIA_API_KEY，否则从受保护的 pipelines/media_key.txt（git-ignored）读取；禁止硬编码明文
function loadMediaKey() {
  const envKey = Deno.env.get('MEDIA_API_KEY')
  if (envKey) return envKey
  try {
    const txt = Deno.readTextFileSync(new URL('./media_key.txt', import.meta.url).pathname)
    const m = txt.match(/Bearer\s+(sk-[A-Za-z0-9]+)/) || txt.match(/(sk-[A-Za-z0-9]+)/)
    if (m) return m[1]
  } catch (_) { /* fall through */ }
  throw new Error('MEDIA_API_KEY 未设置，且无法从 pipelines/media_key.txt 读取')
}
const API_KEY = loadMediaKey()

// ========== Phase 1: COLLECT ==========
phase('Collect')
log('Collecting data...')

const daily = await agent(`
Read daily-sync JSONs from last 14 days at ~/.claude/.../memory/daily-sync/*.json
Extract: meetings, progress, risks, decisions. Structured output.
`, {label:'daily', phase:'Collect'})

const im = await agent(`
Search IM past 2 weeks. Get date via bash, START=14 days ago.
@me + team + group chats (仿真算法组/Simworld MR Sync/通用智能中心)
Output key strategic messages only.
`, {label:'im', phase:'Collect'})

const wiki = await agent(`
**Q2 Wiki 正确读取方法（2026-06-15 测试验证）**

⚠️ 不可用：--doc-format markdown 全文（截断丢最新列）、--scope keyword 日期列名（只返回表头行不返回数据）

**Step A: 获取整个"周目标&进展"章节（固定 block_id：STymdPgAJorwXvxjsrWcJKTMnDe）**
\`\`\`bash
lark-cli docs +fetch --api-version v2 \\
  --doc "https://xiaopeng.feishu.cn/wiki/SBUYwm8Lri9aJ6kmexFcBAuGnlh" \\
  --scope section --start-block-id STymdPgAJorwXvxjsrWcJKTMnDe \\
  --format json
\`\`\`
返回约 200KB，包含 W4-W13 全部内容。

**Step B: 客户端过滤——找双周覆盖的 W 节**
计算过去 14 天的 MMDD 列表：
\`\`\`bash
python3 -c "
from datetime import date, timedelta
today = date.today()
dates = [(today - timedelta(days=i)).strftime('%m%d') for i in range(14, 0, -1)]
print(dates)
"
\`\`\`
对每个 H4 (<h4 id="...">W{n}</h4>)，提取该周内容，检查是否有 核心进展-MMDD 列命中目标日期。
合并所有命中的 W 节内容（通常 1-2 个，~40-80KB）。

**Step C: 提取嵌套文档（不可跳过）**
从合并内容中找到所有 doc-id="..." 的 wiki/docx 引用，去重后逐一 fetch：
\`\`\`bash
lark-cli docs +fetch --api-version v2 --doc <doc-id> --doc-format markdown --format json
\`\`\`

Also read the last GIC report for cross-reference style:
lark-cli docs +fetch --api-version v2 --doc "https://xiaopeng.feishu.cn/docx/SlNPdcCt5o4bYYxb7X7cGIe4nGc" --format json

Output: 双周内四轨（场景&生产/SIL/HIL/Agents）的每日进展、月目标内容、嵌套文档关键数据、其他组参考信息。
`, {label:'wiki', phase:'Collect'})

const mem = await agent(`
Read: ~/.../memory/gic-report-style.md, current-initiatives.md, team-members.md
Output: style rules, project status, team info.
`, {label:'mem', phase:'Collect'})

// ========== Phase 2: ANALYZE ==========
phase('Analyze')
log('Analyzing...')

const analysis = await agent(`
为仿真算法组（李坤）生成GIC双周会汇报板块。

## 风格规则
- **bullet风格**：每节3-5个bullet，不写段落
- **每个bullet的格式**：做了什么 + **所以呢（对业务/版本的影响）** + 关键数据 + **@负责人名字（必须写在bullet文本中才能转成cite标签）**
- **负责人名字必须显式写在bullet文本中**。例如"裴健宏完成场景编辑CLI上线"——不要写"MR#678合入"就不写人
- **不要写changelog**（"MR#xxx合入、yyy上线"），要写"场景编辑CLI上线后，极速模式全链路时延从6h压到3h"
- **核心信息在图里**：文字只给骨架，图承载数据细节
- **column排版**：并列内容用<grid><column>两列/三列
- **可参考其他组**：从邓爽(仿真先行)、杨雪智(自动化)、夏志勋(Metric)等部分了解全局
- **无内嵌文档**：细节展开在正文
- **无模板前缀**：不写"计划：""当前：""差距：""风险：" —— bullet就是内容本身
- **禁止**：World Model/张雨/王博洋、晋升建议、AI腔话
- **语言**：短句子，像李坤在说话

## 输入
daily: ${JSON.stringify(daily,null,2).slice(0,5000)}
IM: ${JSON.stringify(im,null,2).slice(0,3000)}
Wiki+跨组: ${JSON.stringify(wiki,null,2).slice(0,3000)}
Memory: ${JSON.stringify(mem,null,2).slice(0,3000)}

## 输出JSON
{
  "blocks": [{
    "title": "主题（≤8字）",
    "bullets": ["bullet1：判断·数据·行动（@负责人）","bullet2：..."],
    "use_grid": false,
    "grid_left": "左栏内容" | null,
    "grid_right": "右栏内容" | null,
    "image_prompt": "中文prompt，50-100字，描述图里画什么。因为核心信息在图里，所以必须详细：什么数据、什么对比、什么布局、颜色倾向"
  }]
}

约束：≤3个block，每block 3-5 bullet，image_prompt≥30字，结构不套模板。
Return JSON only.
`, {label:'extract', phase:'Analyze', schema:{
  type:'object', properties:{blocks:{
    type:'array', items:{
      type:'object', properties:{
        title:{type:'string'}, bullets:{type:'array',items:{type:'string'},minItems:3,maxItems:5},
        use_grid:{type:'boolean'}, grid_left:{type:'string'}, grid_right:{type:'string'},
        image_prompt:{type:'string',minLength:30},
      }, required:['title','bullets','image_prompt'],
    }, maxItems:3, minItems:1,
  }}, required:['blocks'],
}})

// ========== Phase 3: GENERATE ==========
phase('Generate')
var ds = (args&&args.today)?args.today.replace(/-/g,''):''
var title = '仿真算法组双周进展 '+ds

function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}

function rcites(t){
  var r=t; for(var n in TEAM_USER_IDS){var u=TEAM_USER_IDS[n]
    r=r.replace(new RegExp(n.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'),'g'),'\x00'+u+'\x00')}
  r=esc(r); for(var n in TEAM_USER_IDS)
    r=r.replace('\x00'+TEAM_USER_IDS[n]+'\x00','<cite type="user" user-id="'+TEAM_USER_IDS[n]+'" user-name="'+n+'"></cite>')
  return r
}

var xml='<title>'+title+'</title><callout emoji="🌍"><ul>'
for(var i=0;i<analysis.blocks.length;i++) xml+='<li>'+esc(analysis.blocks[i].title)+'</li>'
xml+='</ul></callout>'

for(var i=0;i<analysis.blocks.length;i++){
  var b=analysis.blocks[i], img='gic-'+ds+'-'+i+'.png'
  xml+='<h1>'+esc(b.title)+' '+rcites('李坤')+'</h1><ul>'
  for(var j=0;j<b.bullets.length;j++) xml+='<li>'+rcites(b.bullets[j])+'</li>'
  xml+='</ul>'

  if(b.use_grid&&b.grid_left&&b.grid_right)
    xml+='<grid><column width-ratio="0.50"><p>'+rcites(b.grid_left)+'</p></column><column width-ratio="0.50"><p>'+rcites(b.grid_right)+'</p></column></grid>'

  // Image placeholder — user uploads manually via /image command
  xml+='<p>【贴图：'+img+'】'+esc(b.image_prompt)+'</p>'
}

// Write doc — previously had shell escaping issues. Now done by main Claude after workflow returns.
// The XML content is returned as part of the result so main Claude writes it directly.
if(args&&args.targetDoc) log('Will write to '+args.targetDoc+' after workflow returns.')

// QA
var issues=[]
for(var i=0;i<analysis.blocks.length;i++){
  if(analysis.blocks[i].bullets.length<3||analysis.blocks[i].bullets.length>5) issues.push('bullet count block '+i)
  if(analysis.blocks[i].image_prompt.length<30) issues.push('short prompt block '+i)
}
if(xml.indexOf('&lt;cite')>=0) issues.push('escaped cite')
if(xml.indexOf('World Model')>=0||xml.indexOf('张雨')>=0||xml.indexOf('王博洋')>=0) issues.push('WM')

return {
  reportTitle:title, docUrl:args&&args.targetDoc||'(需指定文档)',
  summary:'已生成：'+title,
  blocks:analysis.blocks.map(function(b){return{title:b.title, bullets:b.bullets.length, img:b.image_prompt.slice(0,40)}}),
  qa:issues.length?issues:['pass'],
  xml: xml,
  images:'每节含【贴图】占位符，运行 /image 命令手动上传图片',
}
