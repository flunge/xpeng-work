# 飞书 Agent 上手（无需 Cursor）

## 适用对象

需要在飞书群里使用 **「大模型 …」** 智能回复，或运维团队 Bot 的同事。

## 前置条件

1. 已 clone 本仓库。
2. 在仓库根执行一键安装（Ubuntu）：

```bash
bash agents/scripts/setup-dev-environment.sh
```

会安装：

| 组件 | 说明 |
|------|------|
| `agents/.venv` | Python：`fastapi`、`uvicorn`、`requests` 等（见 `requirements-feishu.txt`） |
| `lark-cli` | `npm install -g @larksuite/cli`，执行 **lark-\*** skill 必需 |
| `.cursor/skills` 链接 | 指向 `skills/`，供 Cursor 加载 |

3. 配置飞书 CLI（首次）：

```bash
lark-cli config init --new
lark-cli auth login
lark-cli auth status   # 期望 token 有效
```

4. Python 3.10+；若缺 venv：`sudo apt install python3-venv python3-pip`。若缺 Node：`sudo apt install nodejs npm` 或使用 nvm。

## 配置

```bash
cd agents
cp .env.example .env
# 编辑 .env：至少填写 OPENAI_API_KEY
```

团队共用的 Wiki 台账、推送群等由管理员在 `.env` 或部署机上统一配置。

## 启动（推荐：团队单机常驻）

```bash
cd agents
bash scripts/start_all.sh
```

- Agent：`http://127.0.0.1:8091`
- 健康检查：`curl -s http://127.0.0.1:8091/health | python -m json.tool`

## 群里怎么用

向已接入的 Bot 发送文本消息：

```text
大模型 用三句话介绍 3DGS
```

需要同时生成飞书文档时，在问题中加入关键词，例如「生成报告」「飞书文档」等（见 `agents` 内 `SyncService.wants_doc_output`）。

## 不用 Bot、自己操作飞书

阅读仓库 [`skills/`](../skills/README.md) 下的 `lark-*` 技能，按 `SKILL.md` 使用 `lark-cli` 即可。

## 与 Cursor 的关系

| 组件 | 是否需要 Cursor |
|------|-----------------|
| `agents` | 否 |
| `skills/lark-*` | 否（当操作手册） |
| `skills/3dgs-*` | 否（可手跑脚本；Cursor 更高效） |

Cursor 用户若未跑一键脚本，可单独执行：`bash agents/scripts/setup-skills-links.sh`。
