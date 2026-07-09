# lark-cli 安装与使用（Ubuntu）

`lark-cli` 是飞书官方命令行工具，**不是 Python 包**。执行仓库里 `skills/lark-*`、在 Cursor 里「发飞书文档/消息」、以及 `agents` 的 event bridge，都依赖它在系统 `PATH` 里可用。

## 和 requirements-feishu.txt 的关系

| 类型 | 安装方式 | 文件 |
|------|----------|------|
| Python（Bot、部分 skill 脚本） | `pip install -r requirements-feishu.txt` | `requirements-feishu.txt` |
| **lark-cli 命令行** | `npm` 或复制二进制 | 本页 / `agents/scripts/install-lark-cli.sh` |

一键装两者：

```bash
bash agents/scripts/setup-dev-environment.sh
```

只装 lark-cli：

```bash
bash agents/scripts/install-lark-cli.sh
```

## 安装

### 方式 A：仓库脚本（推荐）

```bash
# 无 node/npm 时会尝试 apt 安装；有 Node 18 时用 npm 全局安装
bash agents/scripts/install-lark-cli.sh

# 需要 Node 20+ 官方向导时（可选，较慢）
USE_NODE20=1 bash agents/scripts/install-lark-cli.sh
```

### 方式 B：手动 npm

```bash
# Ubuntu 若无 node/npm
sudo apt update
sudo apt install -y nodejs npm
# 官方 npx 向导需 Node >= 20；Node 18 请用下一行全局安装

npm install -g @larksuite/cli

# 确认在 PATH 中（npm 全局 bin 常见路径）
export PATH="$(npm config get prefix)/bin:$PATH"
lark-cli --version
```

### 方式 C：复制已有二进制

若团队内某台机器已有 `lark-cli`（例如 `~/.local/bin/lark-cli`）：

```bash
mkdir -p ~/.local/bin
scp colleague@host:~/.local/bin/lark-cli ~/.local/bin/
chmod +x ~/.local/bin/lark-cli
export PATH="$HOME/.local/bin:$PATH"
```

## 首次配置（每人一次）

```bash
# 1. 配置飞书应用（按终端提示打开链接完成）
lark-cli config init --new

# 2. 用户登录（Cursor 里发消息/建文档一般用 user 身份）
lark-cli auth login

# 3. 检查
lark-cli auth status
```

Bot 相关能力（应用身份）在 `config init` 里配置 app_id/app_secret 后，`--as bot` 即可用，通常**不需要**对 bot 执行 `auth login`。

## 常用命令速查

| 场景 | 命令 |
|------|------|
| 查看登录 | `lark-cli auth status` |
| 发私聊/群消息 | `lark-cli im +messages-send --as user --user-id ou_xxx --text "..."` |
| 从 Markdown 建文档 | `lark-cli docs +create --api-version v2 --doc-format markdown --content @file.md` |
| 文档权限（所有人可编辑） | `lark-cli drive permission.public patch --as bot --yes --params '...' --data '...'` |

详细参数见 `skills/lark-im/SKILL.md`、`skills/lark-doc/SKILL.md` 等。

## 与 Cursor skill 的关系

1. `setup-dev-environment.sh` 安装 **lark-cli** + **Python 依赖** + **skill 链接**。
2. Cursor 读取 `skills/lark-*` 里的说明，在对话中**调用终端**执行 `lark-cli ...`。
3. 若未安装或未 `auth login`，skill 会失败（与是否 clone `skills/` 无关）。

## 故障排查

| 现象 | 处理 |
|------|------|
| `lark-cli: command not found` | 跑 `install-lark-cli.sh`（会自动 apt 装 nodejs/npm）或 `export PATH="$(npm config get prefix)/bin:$PATH"` |
| `无法自动安装 lark-cli` | 机器无 node/npm 且无 sudo：先 `apt install nodejs npm` 或让管理员安装 |
| `ERR_REQUIRE_ESM` / npx install 失败 | Node 18 请用 `npm install -g @larksuite/cli`，或 `USE_NODE20=1` 装 Node 20 |
| Permission denied | 按报错里的 `console_url` 在开放平台开 scope，或 `lark-cli auth login --scope "..."` |
| Cursor 说不发飞书 | 确认本机有 `lark-cli` 且 Agent 允许执行 shell；不是 Bot 服务自动代发 |
