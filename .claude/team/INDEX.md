# 仿真部 team 规则索引

> 单一导航源。本目录（`/workspace/.claude/team/`）存**规则/命令/参考**；**记忆内容一律在飞书**，本地不保存。
> 处理 `team/` 下工作时，先读本索引定位到具体规则文件。触发词见下表。

## 🧭 遇到什么 → 读哪个

| 场景 / 触发词 | 文件 |
|---|---|
| **【更新记忆】** | `commands/update-memory.md`（唯一记忆同步命令） |
| 写 **周报 / 双周报** | `commands/weekly-report.md` |
| 报告/修改前**信息获取**（溯源/回源/读图/数字口径/不懂就问） | `rules/sourcing.md` |
| 写**飞书文档/表格/@人/超链接/画图**、lark-cli、身份认证 | `rules/writing.md` |
| 记忆**写哪里/golden 模板/三线关联/什么不写/两索引** | `rules/memory-model.md` |
| 对外报告**发布前必过闸** | `rules/publish-gate.md` |
| 写**对外文档/汇报/述职**内容与风格 | `rules/report-writing.md` |
| **GIC 双周报**风格 | `rules/gic-report-style.md`（+ `gic-report-judgment.md` / `gic-report-repo.md`） |
| **周报**内容规范 | `rules/weekly-report-doc.md` |
| 群 ID / 组员 p2p / **文档 token** 速查 | `refs/tokens.md` |
| 常用文档 / 图片 agent / 项目上下文 | `refs/frequent-docs.md`、`refs/image-agent.md`、`refs/project-context.md` |
| 文档/会议/质量**洞察规则** | `insights/doc-rules.md`、`insights/meeting-rules.md`、`insights/quality-rules.md` |
| lark-cli 命令与参数 | `lark-cli skills read lark-doc`（各 service skill 自带，本仓不重复维护） |

## 📚 记忆内容在飞书（本地不存）

| 资源 | token / 链接 |
|---|---|
| **根文件夹**（projects/people/teams/insights/weekly-reports） | [`W7rqfwqnnlzSfUdEcIGcjcTNnqe`](https://xiaopeng.feishu.cn/drive/folder/W7rqfwqnnlzSfUdEcIGcjcTNnqe) |
| 内部索引（记了什么） | `UwiEdTJJ2oRGokxtkE2cJXjwnyb` |
| 溯源索引（从哪读的） | `SsWCdQbVZohGHFxhE3RcCmJ2nSb` |
| 名称 → 飞书文档 token 映射 | `/workspace/team/memory/_feishu_map.json` |

- 项目 ledger / 人物画像 / chat-log / 周报 **全部在飞书**，读写靠 `_feishu_map.json` 定位。
- **需要修改内容 = 直接改飞书文档**；本地不留任何中间产物，修改轮次结束即删。

## 🔑 最高铁律

1. **溯源先行**：先吃透全貌再动笔（`rules/sourcing.md` §1-2）。
2. **理解→协调→修订**：更新记忆是新增/修订/解除/关联（`commands/update-memory.md`）。
3. **只重述不脑补**，缺数据如实标注（`rules/sourcing.md` §6）。
4. **他组的事不进本组记忆**（`rules/memory-model.md` §5）。
5. **对外报告发布前必过 preflight 闸**（`rules/publish-gate.md`）。
