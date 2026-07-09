# 3DGS 团队 Skills（单一事实来源）

本目录是团队 **Skill 的唯一维护位置**。Cursor / Codex 等 IDE 通过符号链接加载，非 IDE 用户可直接阅读 `SKILL.md` 并按文档执行 `lark-cli` 或脚本。

## Clone 后一次性设置（Cursor / Agent 用户必做）

在仓库根执行**一键安装**（Python 依赖 + `lark-cli` + skill 链接）：

```bash
bash agents/scripts/setup-dev-environment.sh
```

仅重建 skill 链接时：

```bash
bash agents/scripts/setup-skills-links.sh
```

`.cursor/` 与 `.agents/` **不在 Git 中**（见根目录 `.gitignore`）。

**lark-cli**（飞书命令行，执行 `lark-*` skill 必需）由 `agents/scripts/install-lark-cli.sh` 安装，**不在** `requirements-feishu.txt` 里。详见 [docs/feishu/lark-cli-setup.md](../docs/feishu/lark-cli-setup.md)。

会在本地创建**仅含符号链接**的目录（不复制 skill 文件）：

```text
.cursor/skills  -> ../skills
.agents/skills  -> ../skills
```

Skill 正文始终只维护 `skills/` 这一份。

## 目录说明

| 前缀 | 来源 | 用途 |
|------|------|------|
| `lark-*` | 飞书 open.feishu.cn | 消息、文档、日历、多维表格等 `lark-cli` 操作 |
| `3dgs-*` | 本仓库 | 预处理、Fuyao、飞书 Agent 运维等 3DGS 流程 |
| `3dgs-write-skill` | 本仓库 | **把内容总结/写成 Skill 时只写入 `skills/`，禁止写 `.cursor`/`.agents`** |
| `cloudsim-*` | 本仓库 | CloudSim CCES 报告（需配置密钥，见 `.env.example`） |
| `aihot`、`khazix-writer` 等 | 第三方 git | 资讯、写作等辅助 skill |

版本锁定见仓库根目录 [`skills-lock.json`](../skills-lock.json)。

## 谁怎么用

| 角色 | 用法 |
|------|------|
| **Cursor 用户** | 执行 `setup-skills-links.sh` 后，在 Agent 对话中自动匹配 skill |
| **非 Cursor、有飞书** | 打开对应 `skills/lark-*/SKILL.md`，按文档运行 `lark-cli` |
| **飞书群 Bot** | 使用 [`agents`](../agents/README.md)，见 [`docs/feishu/onboarding.md`](../docs/feishu/onboarding.md) |

## 新增 / 修改 Skill

见 [`docs/skills/contributing.md`](../docs/skills/contributing.md)。
