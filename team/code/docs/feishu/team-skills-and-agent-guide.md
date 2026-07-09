# 3DGS 仓库：Skills 与飞书 Agent 团队使用指南（Ubuntu）

> 适用环境：Ubuntu Linux。本文说明仓库结构调整、**环境安装**、以及 clone 后各角色如何上手。

---

## 一、这次改了什么？

我们把 **Skill（操作手册）** 和 **飞书 Bot 服务** 分开管理，并统一到 Git，方便全团队共用。

### 1.1 新目录结构

| 路径 | 作用 | 谁需要 |
|------|------|--------|
| **`skills/`** | 团队 Skill 的**唯一维护位置**（飞书 `lark-*`、3DGS `3dgs-*` 等） | 所有人 |
| **`skills-lock.json`** | 官方 lark skill 版本锁定 | 维护者升级时用 |
| **`agents/`** | 飞书群 Bot 服务 + **安装脚本** | 所有人（装环境）/ 运维（跑 Bot） |
| **`agents/scripts/`** | 环境安装、启动 Bot、skill 链接 | 见下文第二节 |
| **`.cursor/skills` → `../skills`** | 本地符号链接（**不提交 Git**） | Cursor 用户 |
| **`requirements-feishu.txt`** | Python 依赖清单（仓库根） | `pip` 安装用 |

**重要原则：**

- Skill 正文**只改** `skills/` 目录。
- **大模型不是独立进程**，随 Bot 在收到「大模型 …」时内联调用 API。
- **`lark-cli` 不是 pip 包**，需单独安装（见下）。

### 1.2 安装脚本一览（均在 `agents/scripts/`）

| 脚本 | 作用 |
|------|------|
| **`setup-dev-environment.sh`** | **一键安装**（推荐）：Python venv + `lark-cli` + skill 符号链接 |
| `install_deps.sh` | 仅安装 Python 虚拟环境与 `requirements-feishu.txt` |
| `install-lark-cli.sh` | 仅安装 `lark-cli` 命令行 |
| `setup-skills-links.sh` | 仅创建 `.cursor`/`.agents` → `skills/` 链接 |
| `start_all.sh` | 启动 Bot + 事件桥接（需已配置 `.env`） |
| `start_local_agent.sh` | 仅启动 Bot HTTP 服务 |

---

## 二、环境安装（Clone 后必做）

在**仓库根目录**执行：

```bash
cd /path/to/3dgs

# 一键安装（Ubuntu）
bash agents/scripts/setup-dev-environment.sh
```

### 2.1 一键脚本会装什么？

| 组件 | 安装方式 | 说明 |
|------|----------|------|
| **Python 依赖** | `agents/.venv` + `pip install -r requirements-feishu.txt` | `fastapi`、`uvicorn`、`requests` 等 |
| **lark-cli** | `npm install -g @larksuite/cli`（若无则报错并提示） | 执行 **lark-\*** skill、Cursor 里发飞书消息/文档 |
| **Skill 链接** | `.cursor/skills`、`.agents/skills` → `../skills` | 仅本地，不提交 Git |

**`requirements-feishu.txt` 不包含 lark-cli**——命令行与 pip 分开装。

### 2.2 分步安装（可选）

```bash
# 仅 Python
bash agents/scripts/install_deps.sh

# 仅 lark-cli
bash agents/scripts/install-lark-cli.sh

# 仅 skill 链接
bash agents/scripts/setup-skills-links.sh
```

跳过某项时，一键脚本支持参数：

```bash
bash agents/scripts/setup-dev-environment.sh --skip-lark-cli
bash agents/scripts/setup-dev-environment.sh --skip-agent
bash agents/scripts/setup-dev-environment.sh --skip-links
```

### 2.3 系统前置（Ubuntu）

```bash
# Python 3.10+
python3 --version
sudo apt install -y python3-venv python3-pip   # 若缺 venv

# Node.js（装 lark-cli 用，一键脚本会调 npm）
sudo apt install -y nodejs npm
# 或使用 nvm 安装 Node 18+
```

### 2.4 飞书 CLI 首次配置（每人一次）

```bash
lark-cli config init --new    # 按提示配置飞书应用
lark-cli auth login           # 用户登录（Cursor 发文档/消息需要）
lark-cli auth status          # 检查 token
```

若 `npm install` 后找不到命令：

```bash
export PATH="$(npm config get prefix)/bin:$PATH"
```

更多排障见 `docs/feishu/lark-cli-setup.md`。

### 2.5 飞书 Bot 配置（跑 Bot 的机器）

```bash
cd agents
cp .env.example .env
# 编辑 .env：至少 OPENAI_API_KEY；Wiki/推送群等按团队文档填写

bash scripts/start_all.sh
curl -s http://127.0.0.1:8091/health | python3 -m json.tool
```

---

## 三、按角色怎么用

### 3.1 只用飞书、不用 Cursor

**A. 群 Bot（推荐单机常驻）**

```text
大模型 用三句话介绍 3DGS
```

带文档关键词：**生成报告**、**飞书文档**、**写报告** 等。

**B. 自己操作飞书（Cursor 里让 Agent 执行 skill）**

需完成第二节环境安装 + `lark-cli auth login`。Agent 会在终端执行 `lark-cli`，**不是** Bot 自动代发。

阅读 `skills/lark-im/`、`skills/lark-doc/` 等 `SKILL.md`。

### 3.2 使用 Cursor 开发 3DGS

1. 执行 `bash agents/scripts/setup-dev-environment.sh`（若尚未执行）。
2. 新开 Agent 会话以加载 `skills/`。
3. 参考 `skills/3dgs-preprocess-task/`、`skills/3dgs-feishu-rd-agent/` 等。

### 3.3 维护 Skill

- 只改 `skills/<name>/`；见 `docs/skills/contributing.md`、`skills/3dgs-write-skill/`。
- 勿提交密钥、个人 open_id。

---

## 四、飞书 Agent 环境变量

见 `agents/.env.example`。Bot 创建文档默认 **所有人可编辑**（`anyone_editable`）。**不要**提交 `.env`。

---

## 五、Git 提交注意

**应提交：** `skills/`、`skills-lock.json`、`agents/`（含 `scripts/`）、`requirements-feishu.txt`、`docs/`

**不要提交：** `.env`、`.venv/`、`data/`、`.cursor/`、`.agents/`

---

## 六、常见问题

**Q：同事更新了 `skills/`，我还要跑安装脚本吗？**  
A：一般不用。`git pull` 后 skill 内容自动更新；仅当 `.cursor/skills` 链接不存在时再跑 `setup-skills-links.sh`。

**Q：Cursor 里说「整理成文档发给某人」会自动用 Bot 发吗？**  
A：**不会。** 需本机已装 `lark-cli` 且已 `auth login`；Agent 用 **你的 user 身份**调 CLI。Bot 只在飞书群里响应「大模型 …」。

**Q：大模型 timeout？**  
A：`.env` 中 `OPENAI_TIMEOUT_SECONDS` ≥ 180；或降低 `OPENAI_REASONING_EFFORT`。

**Q：lark-cli 与 pip 的关系？**  
A：`requirements-feishu.txt` 只管 Python；`lark-cli` 用 `install-lark-cli.sh` 或一键脚本安装。

---

## 七、文档索引

| 文档 | 路径 |
|------|------|
| 本指南（本地） | `docs/feishu/team-skills-and-agent-guide.md` |
| lark-cli 详解 | `docs/feishu/lark-cli-setup.md` |
| Skills 总览 | `skills/README.md` |
| Bot 说明 | `agents/README.md` |

---

*文档版本：含环境安装脚本迁移至 agents/scripts。*
