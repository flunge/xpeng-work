# lik44-star-team

「灵犀」运行的多项目工作空间（monorepo）。仓库根下并列两个**相互独立**的项目区：

```
/workspace
├── .claude/               # 工作区规则中枢（CLAUDE.md 总则 + team/ 规则 + skills + agents）
├── personal/              # ① 个人自动化区（.claude 规则 + meal/ 家庭食谱）
└── team/                  # ② 仿真部飞书工作空间交互（lark-cli + 飞书记忆库）
```

> ⚠️ **cron / 触发层 / 每日采集在用户本地维护，不在本云端仓库。**
> 云端仓库只保留三类：**规则**（`.claude/`、`personal/.claude/`）、**可复用工具脚本**（`team/scripts/`、`personal/meal/scripts/`）、**飞书关联**（`team/memory/_feishu_map.json`、`personal/meal/config/feishu.yaml`）。
> 所有**内容产出物只在飞书**（配方库 / 记忆库 / 周报 / 双周报 / 述职等）；本地不存任何内容副本，需要改内容一律直接改飞书。

---

## 项目一览

| 目录 | 用途 | 技术栈 | 详细规则 |
|------|------|--------|----------|
| [`personal/meal/`](personal/meal/) | 一家四口自动化食谱：每日推送明日食谱 + 采购清单，月末生成下月计划（配方/计划全量在飞书） | Python3 + PyYAML + lark-cli | [personal/.claude/CLAUDE.md](personal/.claude/CLAUDE.md) · [personal/meal/README.md](personal/meal/README.md) · [personal/.claude/WORKFLOW.md](personal/.claude/WORKFLOW.md) · [personal/.claude/RECIPE_RULES.md](personal/.claude/RECIPE_RULES.md) |
| [`team/`](team/) | 用 `lark-cli` 读写飞书、采集会议纪要、维护团队记忆库、生成周报/双周报 | Python3 + Node.js + lark-cli | [team/CLAUDE.md](team/CLAUDE.md) · [.claude/team/INDEX.md](.claude/team/INDEX.md) |

---

## ① personal/meal/ —— 家庭食谱自动化

**做什么**：每晚 18:00 推送次日食谱 + 采购清单到飞书；每月末 20:00 生成下月计划。

**架构（2026-07-16 全量迁飞书后）**：内容与脚本分离——本地只留脚本 + 飞书映射，配方 / 月计划 / 每日卡片 / 配置全在飞书（多 agent 协作共享）。

| 类别 | 位置 | 说明 |
|------|------|------|
| **规则** | [`personal/.claude/`](personal/.claude/) | `CLAUDE.md`（数据架构 + 脚本用法）、`RECIPE_RULES.md`（食谱宪法）、`WORKFLOW.md`（生成/推送/质检流程） |
| **脚本** | `personal/meal/scripts/` | `feishu_data.py`（飞书数据层）、`generate_month.py`、`notify_daily.py`、质检工具 |
| **飞书映射** | `personal/meal/config/feishu.yaml` | 配方库 Base + 各文件夹 token；根文件夹 `IVBgfymaolzx9Bdbpbsc1VPGnAc` |
| **内容** | 🌐 **只在飞书** | 94 配方（Base 多维表格）、月计划、每日卡片、config，全在[飞书根文件夹](https://xiaopeng.feishu.cn/drive/folder/IVBgfymaolzx9Bdbpbsc1VPGnAc) |

**触发**：由用户本地 cron 调 `personal/meal/scripts/` 脚本（云端仓库不含触发层）。

---

## ② team/ —— 仿真部飞书工作空间

**做什么**：以李坤（P8，仿真算法组）视角，用 `lark-cli` 维护团队记忆系统，生成周报 / 双周报 / 述职等对外报告。

**架构（2026-07-16 重构后）**：内容与规则彻底分离——本地只留规则 + 工具 + 飞书关联。

| 类别 | 位置 | 说明 |
|------|------|------|
| **规则 / 命令 / 参考** | [`.claude/team/`](.claude/team/) | 铁律（`rules/`）、命令手册（`commands/`）、速查（`refs/`）、洞察（`insights/`）；入口 [`INDEX.md`](.claude/team/INDEX.md) |
| **可复用工具** | `team/scripts/` | 报告发布闸 `preflight.py`/`check_report.py`、配图链 `gen_svg_infographic.py`/`push_whiteboard_native.py`/`html2svg.mjs`；`hooks/` 校验钩子；`fonts/` |
| **报告生成器** | `team/pipelines/` | `weekly-report.js`（周报）、`gic-report.js`（双周报）Workflow 脚本，**数据源全部从飞书读**；`gpt_image_gen`/`grok_image_gen` 图片工具 + `media_key.txt`（git-ignored） |
| **飞书关联** | `team/memory/_feishu_map.json` | 项目名 / 人名 → 飞书 token；`root_folder=W7rqfwqnnlzSfUdEcIGcjcTNnqe` |
| **内容（记忆库）** | 🌐 **只在飞书** | 项目 ledger / 人物画像 / chat-log / 周报 / 两索引，全在[飞书根文件夹](https://xiaopeng.feishu.cn/drive/folder/W7rqfwqnnlzSfUdEcIGcjcTNnqe) |
| **临时文件** | `team/tmp/` | 所有任务的临时 / 中间产物，用完即弃、不入库 |

**怎么用**：
- 处理 team 任务前先读 [`team/CLAUDE.md`](team/CLAUDE.md)（导航页）→ 按触发词到 [`.claude/team/INDEX.md`](.claude/team/INDEX.md) 定位具体规则
- 常用：聊天发 **【更新记忆】** 触发记忆同步；**周报 / 双周报** 走对应 skill + `pipelines/` 脚本
- **修改记忆内容 = 直接改飞书文档**（本地无内容副本）
- 报告发布前必过闸：`python3 team/scripts/preflight.py <doc_token> --audience boss|xianming`

---

## 工作区约定（详见 [.claude/CLAUDE.md](.claude/CLAUDE.md)）

- **本地只留规则 + 工具 + 飞书关联**，一切内容产出物只在飞书。
- **临时文件统一放 `team/tmp/`**（meal 类推），用完即弃、不入库。
- **cron / 触发 / 每日采集在用户本地维护**，云端不含。
- `team/` 有自己的 `CLAUDE.md` 与 skills，处理 team 文件时优先遵循该目录规则。

---

## 部署说明

工作空间部署在 Agent Pod。工程文件（`/workspace`）与飞书授权（`/platform/.lark-cli`）在持久盘，Pod 重启不丢。触发调度（cron / 触发脚本）由用户在本地维护，不随本仓库分发。meal 需 `pip install pyyaml` 且依赖 `lark-cli` 已登录。
