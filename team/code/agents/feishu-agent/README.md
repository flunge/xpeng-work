# 3dgs Feishu Agent MVP

一个面向飞书群协作的 3dgs Agent MVP 后端，用于接收群内任务、创建任务台账、编排仓库执行能力，并将结果同步到飞书群、文档和 Wiki 任务页。

## 当前范围

首期实现覆盖：

- 飞书事件接收与标准化
- 任务创建、查询、取消、重试
- 规则路由与结构化参数解析
- 统一任务状态机与事件落盘
- 预处理 / 训练 / 日志下载 / 报告生成的 executor 抽象
- 飞书群消息、文档、Wiki 任务进展同步，支持 `mock` 与 `cli` 两种模式

默认仍使用 SQLite 持久化；当 `FEISHU_MODE=cli` 时，会复用当前机器上已登录的 `lark-cli` 身份，把任务同步到真实飞书。

## 目录结构

```text
agents/
  app/
    interfaces/http/      # HTTP webhook 与任务查询接口
    application/          # 用例、编排、命令解析、同步协调
    domain/               # 领域模型、状态机、DTO
    executors/            # 仓库执行器与注册表
    infrastructure/       # SQLite、飞书适配器、脚本适配器
```

## 安装依赖

在**仓库根**执行（推荐，会同时装 `lark-cli` 与 skill 链接）：

```bash
bash agents/scripts/setup-dev-environment.sh
```

仅安装本服务 Python 环境：

```bash
bash agents/scripts/install_deps.sh
```

其他脚本见 `scripts/`：`install-lark-cli.sh`、`setup-skills-links.sh`、`start_all.sh`。

依赖说明见仓库根 `requirements-feishu.txt`（含 `fastapi`、`uvicorn`、`requests` 等）。

## 真实飞书接入说明

### 1. 前置条件

先确保已完成 `setup-dev-environment.sh`，且飞书 CLI 已登录：

```bash
lark-cli auth status
```

如果返回 `tokenStatus: valid`，即可继续。

### 2. 环境变量

复制示例配置并按团队文档填写（勿提交 `.env`）：

```bash
cp .env.example .env
```

完整上手说明（含非 Cursor 同事）：[`docs/feishu/onboarding.md`](../docs/feishu/onboarding.md)。

最少需要：

```bash
export FEISHU_MODE=cli
export OPENAI_API_KEY=sk_xxx
```

可选：Wiki 任务台账、启动问候、每日 AI HOT 等见 `.env.example`。

结构化字段默认名如下，可按需覆盖：

```bash
export FEISHU_PROGRESS_TASK_ID_FIELD="Task ID"
export FEISHU_PROGRESS_TASK_TYPE_FIELD="任务类型"
export FEISHU_PROGRESS_STATUS_FIELD="状态"
export FEISHU_PROGRESS_STAGE_FIELD="阶段"
export FEISHU_PROGRESS_REQUESTER_FIELD="请求人"
export FEISHU_PROGRESS_SUMMARY_FIELD="摘要"
export FEISHU_PROGRESS_DOC_URL_FIELD="文档链接"
```

文档公开权限相关配置：

```bash
export FEISHU_DOC_PUBLIC_ACCESS_ENABLED=true
export FEISHU_DOC_PUBLIC_PERMISSION_AS=user
export FEISHU_DOC_EXTERNAL_ACCESS=true
export FEISHU_DOC_LINK_SHARE_ENTITY=anyone_editable
export FEISHU_DOC_SHARE_ENTITY=anyone
export FEISHU_DOC_COMMENT_ENTITY=anyone_can_edit
export FEISHU_DOC_SECURITY_ENTITY=anyone_can_edit
export FEISHU_DOC_INVITE_EXTERNAL=true
```

可选配置：

```bash
export FEISHU_DOC_FOLDER_TOKEN=folder_token_xxx
export FEISHU_DOC_WIKI_SPACE=my_library
export FEISHU_REPLY_IN_THREAD=true
export FEISHU_MESSAGE_AS=bot
export FEISHU_DOC_AS=bot
export FEISHU_DOC_FALLBACK_AS=user
export FEISHU_PROGRESS_AS=user
export FEISHU_BUSY_REPLY_TEXT="思考中"
export FEISHU_ENABLE_BOOTSTRAP_GREETING=true
export FEISHU_BOOTSTRAP_TARGET_CHAT_ID=oc_xxx
export FEISHU_BOOTSTRAP_GREETING="等待你的命令"
export FEISHU_DAILY_AI_HOT_ENABLED=false
export FEISHU_DAILY_AI_HOT_TARGET_CHAT_ID=oc_xxx
export FEISHU_DAILY_AI_HOT_TIME="09:30"
export FEISHU_DAILY_AI_HOT_TIMEZONE="Asia/Shanghai"
export FEISHU_DAILY_AI_HOT_RUN_ON_STARTUP_IF_MISSED=false
export OPENAI_API_KEY="sk_xxx"
export OPENAI_BASE_URL="https://socheap.ai/v1"
export OPENAI_MODEL="gpt-5.4"
export OPENAI_REVIEW_MODEL="gpt-5.4"
export OPENAI_REASONING_EFFORT="xhigh"
export OPENAI_DISABLE_RESPONSE_STORAGE=true
```

说明：
- 飞书普通文本默认忽略；只有消息以「大模型」开头时才会调用大模型 API，例如 `大模型 你好`。
- `FEISHU_BUSY_REPLY_TEXT` 用于执行中收到新命令时立即回复，默认 `思考中`。
- 团队共用的 Skill 文档在仓库根 [`skills/`](../skills/README.md)；Cursor 用户执行 `bash agents/scripts/setup-skills-links.sh` 后 IDE 会自动加载。
- 启动问候 / 每日 AI HOT 需在 `.env` 中显式配置目标 `chat_id` 或 `open_id`。
- 配置 `OPENAI_API_KEY` 后，只有以“大模型”开头的普通文本会走 OpenAI Responses API 智能回复；默认 base URL 为 `https://socheap.ai/v1`，默认模型为 `gpt-5.4`，且默认不存储响应。
- 文档默认先用 `bot` 身份创建/更新；如果权限不足会自动回退到 `user` 身份。
- 文档创建或更新后，会尝试自动设置为“组织内获得链接的人可阅读且可编辑”。
- 如果公开权限 patch 失败，不影响文档主流程完成。
- 任务进展页虽然入口是 Wiki 链接，但其底层对象是一个 `bitable`：
  - `wiki node token = TBIEwZ7ZIi5Ct1kjQHoc8RmLnpO`
  - `progress base token = FetpbIFQCaDzccsiJulcW5tEn1b`
  - `table id = tbld387ZPXuyuoPk`
  - `view id = vew3h6TRri`
- 当前实现会自动把任务进展写入该 bitable 的结构化字段与 `文本` 字段。

## 本地启动

**群聊要能回复，需要同时跑两个进程：**

1. HTTP Agent（处理任务、回消息）
2. 事件桥（`lark-cli` 长连接收消息 → 转发到本地 webhook）

```bash
cd agents
bash scripts/start_local_agent.sh          # 默认端口 8091
bash scripts/start_event_bridge.sh         # 另开终端
# 或一条命令：bash scripts/start_all.sh
```

飞书开发者后台还需开启：**事件订阅 → 长连接**，并订阅 `im.message.receive_v1`；群聊 @ 机器人通常还需要 scope `im:message.group_at_msg:readonly`。

### 群聊 @ 无响应排查

1. `lark-cli event status` 里 `Bus: running` 且 `RECEIVED` 会增长
2. 事件桥终端出现 `forwarded evt_...`
3. 群聊消息需 **@ 机器人**（私聊可直接发）
4. 机器人已在目标群内
5. `curl http://127.0.0.1:8091/tasks` 能看到新 `TASK-xxxxx`

旧文档里的 `8090` 端口若被占用，请改用 `8091`。

## 最小联调步骤

### 1. 伪造一条飞书 webhook 事件

```bash
curl -X POST http://127.0.0.1:8090/webhook/feishu/events \
  -H 'Content-Type: application/json' \
  -d '{
    "header": {"event_id": "evt-real-1", "event_type": "im.message.receive_v1"},
    "event": {
      "sender": {"sender_id": {"open_id": "ou_xxx"}},
      "message": {
        "message_id": "om_xxx",
        "chat_id": "oc_xxx",
        "thread_id": "omt_xxx",
        "message_type": "text",
        "content": "{\"text\":\"@Agent 启动 preprocess clip_id=c-123 config=config_vision.yaml\"}"
      }
    }
  }'
```

### 2. 验证真实链路

触发后应看到：
- 飞书群里收到任务状态消息
- 飞书文档中新建或更新了一篇任务报告
- 文档默认被设置为链接可编辑（`anyone_editable`，互联网获得链接者可编辑）
- Wiki 任务页对应表格新增一行结构化记录

### 2.1 验证飞书对话往返

除任务命令外，现在也支持普通文本对话：
- 私聊机器人时，文本消息会直接进入本地 Agent
- 群聊中 `@Agent` 后发送文本，也会进入本地 Agent
- Agent 会把回复通过飞书消息回传到原会话/原线程

示例：

```text
你好，帮我介绍一下你能做什么？
```

期望结果：
- 本地服务收到 `im.message.receive_v1` webhook
- Agent 创建一条 `chat.reply` 类型任务
- 飞书中收到机器人回复，说明链路 `飞书 -> Agent -> 飞书` 已打通

### 4. 验证串行命令与忙碌回复

1. 启动服务，确认应用启动后会主动向目标用户发送 `等待你的命令`。
2. 在第一条命令尚未完成时，再发送第二条命令，确认机器人立即回复 `思考中`。
3. 第一条任务完成后，确认最终结果通过飞书回传，然后第二条任务自动开始执行。
4. 使用 `GET /tasks` 检查任务列表，确认状态按 `queued -> preprocessing/training/evaluating/reporting -> done` 变化。

### 5. 查询本地任务台账

```bash
curl http://127.0.0.1:8090/tasks
curl http://127.0.0.1:8090/tasks/TASK-000001
```

## 与仓库能力的映射

- 预处理：`pipeline/fuyao/deploy_preproc.bash <config_file> <job_name>`
- 训练：`pipeline/fuyao/deploy_reconic.sh`
- 状态/日志：`tools/render_time_analysis/log_downloader.py`
- 评测汇总：`tools/eval_tools/eval_main.py`

## 当前实现说明

- `mock` 模式：保留原先本地 payload/假链接逻辑，便于离线开发。
- `cli` 模式：
  - 消息通过 `lark-cli im +messages-send` / `+messages-reply`
  - 文档通过 `lark-cli docs +create` / `+update`
  - 文档权限不足时自动从 `bot` 回退到 `user`
  - 文档创建/更新后通过 `drive permission.public patch` 设置所有人可编辑（默认 `anyone_editable` + `share_entity=anyone`）
  - Wiki 任务进展会写入其底层 bitable 表格的结构化字段
- `task_runs` 新增了 `sync_message_id`、`sync_record_id` 字段，用于保存真实飞书对象标识。

## 已验证结果

- 机器人身份消息发送已打通
- `bot` 身份创建飞书文档已打通
- Wiki 页底层 bitable 已可写入结构化记录
- 当前已创建结构化字段：
  - `Task ID`
  - `任务类型`
  - `状态`
  - `阶段`
  - `请求人`
  - `摘要`
  - `文档链接`
  - `文本`
- 结构化写入测试 record id: `recvjAVNFCzZhL`

## 后续建议

- 未来将 `cli` 鉴权切换到正式 `app_id/app_secret` 服务端鉴权。
- 把当前普通文本消息升级为飞书卡片消息。
- 基于 `Task ID` 增加真正的 upsert/查重逻辑，避免重复插入多条相同任务记录。
