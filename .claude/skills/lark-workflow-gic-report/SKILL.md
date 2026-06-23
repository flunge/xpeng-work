---
name: lark-workflow-gic-report
version: 2.0.0
description: "GIC双周会汇报板块生成。注意：参考风格必须读 memory/gic-report-style.md，不要用邓爽的部门报告风格。"
triggers:
  - 双周会
  - GIC双周会
  - 双周报
  - 生成汇报
  - gic report
---

# GIC双周报工作流

**首先：读 memory/gic-report-style.md，理解李坤的GIC汇报风格**

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
- 短句子，像在说话
- "当前有两台台架，预期达到目标需要至少5台" —— 不是"差距：3台"
- 不写"计划：""当前：""差距：" 这种模板前缀
- bullet开头的词就是内容本身

### GPT-Image-2 配图
- 每节1张图，核心信息在图里承载，文字只给骨架
- SoCheap API: POST https://socheap.ai/media/generations
  - model: gpt-image-2, size: 1024x576
  - prompt: 中文, 50-100字, 详细描述图的内容。加 "Fill the entire frame, no white space"
  - KEY: Bearer sk-d8516293f5414d16c58bb646bf996e862c3adc1550382a861e20b0be33304fa8（见 pipelines/media_key.txt）
- 生成耗时 ~45秒，~$0.03/张
- **⚠️ 不要反复测试生图**，prompt想好再发，每次$0.03
- 流程：生图 → 存本地 → 文档写 `【贴图：<name>.png】` → 用户 `/image` 手动上传
- 存到 `/Users/xpeng/Documents/team/.claude/.../memory/daily-sync/images/`
- 上传后裁剪白边（用 image-agent.md 的 trim_white 函数）

## QA自检

- [ ] 每节≤5个bullet
- [ ] 每节有图（whiteboard或GPT-Image-2）
- [ ] 不写段落
- [ ] 标题后`<cite>李坤</cite>`
- [ ] 结构不套模板
- [ ] 语言自然，像在说话
- [ ] 没有"计划→当前→差距→原因"这种模板前缀
- [ ] 没有World Model/张雨/王博洋内容
