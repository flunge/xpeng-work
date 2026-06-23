# 仿真部项目全流程文档

## 1. 文档目的

本文件用于沉淀当前仓库的全链路工作流程，覆盖知识沉淀、日常同步、风险播报、周报产出、GIC 汇报、Agent/Skill 体系与脚本自动化，便于交接、审计和复用。

## 2. 仓库核心结构

- `memory/`：知识与项目状态主库
- `memory/projects/`：按赛道维护项目 ledger（场景&生产、SIL、HIL、Agents）
- `memory/people/`：人员画像与协作信息
- `memory/teams/`：团队结构和协同规则
- `memory/insights/`：文档规则、会议规则、质量规则
- `memory/daily-sync/`：每日同步产物与运行日志
- `memory/weekly-reports/`：周报归档
- `projects/GIC_report/`：GIC 双周会提示词与图片产物
- `pipelines/`：自动化脚本与专项技能
- `.agents/skills/`：技能库定义（含各领域 SKILL.md 与 references）
- `.claude/`：工作流与扩展技能配置
- `scripts/`：日常自动化脚本（daily-sync、risk-push）
- `team_building/`：团队活动资料

## 3. 日常运行主流程

### 3.1 每日同步（daily-sync）

目标：同步飞书侧会议、文档、聊天上下文到本地知识体系。

流程：
1. 定时任务触发 `scripts/daily-sync.sh`。
2. 生成 `memory/daily-sync/YYYY-MM-DD.json` 作为索引输入。
3. 根据规则读取源文档（会议纪要、文字记录、Wiki、消息链接文档）。
4. 更新人物、团队、项目三条主线记忆。
5. 在 `memory/insights/chat-log.md` 沉淀关键决策与事件。

关键输出：
- 每日 JSON 索引：`memory/daily-sync/*.json`
- 同步日志：`memory/daily-sync/sync.log`

### 3.2 项目风险日报（risk-push）

目标：每天 9:00 自动汇总项目风险并推送到飞书群。

流程：
1. 定时任务调用 `scripts/risk-push.py`。
2. 脚本遍历 `memory/projects/**/ledger.md`。
3. 提取风险标记（🔴/🟡/⚠️）与项目摘要。
4. 组装飞书机器人 post 消息。
5. 调用 webhook 发送并落盘日志。

关键输出：
- 执行日志：`memory/daily-sync/risk-push.log`
- LaunchAgent 输出：`memory/daily-sync/risk-push-stdout.log`、`memory/daily-sync/risk-push-stderr.log`

### 3.3 周报流程（weekly-report）

目标：按规则汇总过去一周会议、聊天、文档，生成结构化周报。

流程：
1. 读取周会/日会纪要与文字记录。
2. 读取 `@我`、组内群聊和 p2p 上下文。
3. 按 `memory/insights/quality-rules.md` 逐条核验事实。
4. 产出周报并落地到 `memory/weekly-reports/`。

关键脚本/技能：
- `pipelines/weekly-report.js`
- `pipelines/weekly-report/SKILL.md`
- `.agents/skills/weekly-report/SKILL.md`

### 3.4 GIC 双周会汇报流程

目标：按约定风格生成 GIC 汇报各板块。

流程：
1. 读取 GIC 上下文和风格基准。
2. 根据分板块提示词生成内容与配图。
3. 写入汇报稿与相关素材。

关键输入与产物：
- 提示词：`projects/GIC_report/*-prompt.md`
- 图片：`projects/GIC_report/*.png`
- 风格基准：`memory/gic-report-style.md`
- 判断标准：`memory/gic-report-judgment.md`
- 汇报仓上下文：`memory/gic-report-repo.md`

## 4. 记忆维护流程（People / Teams / Projects）

### 4.1 People 线

- 维护路径：`memory/people/`
- 内容：人物画像、行为模式、项目参与变化
- 索引：`memory/people/_index.md`

### 4.2 Teams 线

- 维护路径：`memory/teams/`
- 内容：组织结构、协作关系、职责边界

### 4.3 Projects 线

- 维护路径：`memory/projects/<track>/<project>/ledger.md`
- 内容：状态、里程碑、风险、owner 变化
- 归档：`_archive/`

## 5. Agent / Skill 体系流程

### 5.1 技能来源

- 主技能仓：`.agents/skills/`
- 扩展技能仓：`.claude/skills/`
- Pipeline 技能：`pipelines/*/SKILL.*`

### 5.2 运行方式

1. 由指令路由到对应 skill。
2. 按 skill 定义执行查询、编辑、汇总或生成。
3. 结果回写到 `memory/` 或 `projects/` 对应目录。

### 5.3 典型技能类别

- 飞书业务技能：`lark-*`
- 周报/GIC 工作流技能：`weekly-report`、`lark-workflow-*`
- 图像生成技能：`gpt_image_gen`、`grok_image_gen`

## 6. 自动化与调度

- daily-sync：由 LaunchAgent 定时触发，脚本在 `scripts/daily-sync.sh`
- risk-push：由 LaunchAgent 每天 9:00 触发，脚本在 `scripts/risk-push.py`
- 运行日志统一落在 `memory/daily-sync/`

## 7. 输入输出全链路（简版）

输入源：飞书文档/会议/聊天、历史记忆、项目 ledger、规则文档

处理层：
- 规则校验（doc-rules / meeting-rules / quality-rules）
- 自动脚本（daily-sync / risk-push / report pipelines）
- skill 编排（.agents/.claude/pipelines）

输出层：
- 人员画像更新（people）
- 项目状态更新（projects）
- 团队结构更新（teams）
- 周报/GIC 材料产出（weekly-reports、GIC_report）
- 风险播报消息（飞书 webhook）

## 8. 本次打包说明

- 打包目标：保留项目原目录结构，包含 agent/skill 等相关文件
- 排除规则：排除 lark-cli 相关配置文件（路径名包含 `lark-cli` 的文件）
- 压缩包输出路径：`docs/team-project-full-package-2026-06-18.zip`

## 9. 维护建议

1. 每次流程变更后同步更新本文件。
2. 新增自动化脚本时补充“触发方式 + 输入输出 + 失败处理”。
3. 对风险推送和周报流程建议补充失败重试与返回码校验。
