---
name: 3dgs-feishu-rd-agent
description: Summarizes the 3DGS Feishu R&D Agent workflow for this repository. Use when building, debugging, operating, or extending agents; integrating Feishu/Lark CLI, webhook events, bot replies, doc/report creation, Wiki bitable progress tracking, task queues, or 3DGS experiment orchestration from Feishu.
---

# 3DGS 飞书研发 Agent

## 目标

在本仓库中，`agents` 是面向飞书群协作的 3DGS 研发 Agent 后端；团队 Skill 统一维护在仓库根 [`skills/`](../README.md)（Cursor 用户执行 `bash agents/scripts/setup-skills-links.sh` 链接到 IDE）。目标是让同事在飞书私聊或群聊中给 bot 下达 3DGS 优化/实验任务，Agent 负责：

1. 接收飞书消息事件。
2. 解析任务命令或普通对话。
3. 创建并管理任务状态。
4. 串行执行仓库内预处理、训练、日志下载、报告生成等能力。
5. 将结果回传飞书消息。
6. 生成/更新飞书文档。
7. 将任务进展写入 Wiki 表格页底层 bitable 台账。

## 关键代码位置

- `agents/app/main.py`：FastAPI app，注册 startup/shutdown，启动后台 worker 和启动问候。
- `agents/app/interfaces/http/feishu_webhook.py`：飞书事件入口 `/webhook/feishu/events`。
- `agents/app/application/command_parser.py`：飞书文本命令解析。
- `agents/app/application/orchestrator.py`：任务创建、排队、串行执行、忙碌回复、状态更新。
- `agents/app/application/sync_service.py`：同步飞书消息、文档、Wiki 表格。
- `agents/app/infrastructure/feishu_config.py`：飞书环境变量配置与 `lark-cli` 适配器。
- `agents/app/infrastructure/feishu_clients.py`：真实飞书消息、文档、bitable 客户端。
- `agents/app/infrastructure/sqlite_repo.py`：SQLite 任务、事件、artifact 落盘。
- `agents/app/executors/`：各类 3DGS 执行器。

## 仓库能力映射

- 预处理：`pipeline/fuyao/deploy_preproc.bash <config_file> <job_name>`
- 默认预处理配置：`xpeng_data_process/configs/config_vision.yaml`
- 训练：`pipeline/fuyao/deploy_reconic.sh`
- 日志/状态分析：`tools/render_time_analysis/log_downloader.py`
- 评测汇总：`tools/eval_tools/eval_main.py`
- Difix 修复链路：`difix/`
- 训练主工程：`omnire_joint_trainning/`
- 数据预处理工程：`xpeng_data_process/`

## 飞书接入模式

当前支持两种模式：

- `FEISHU_MODE=mock`：本地假数据，适合离线开发。
- `FEISHU_MODE=cli`：使用已登录的 `lark-cli` 调真实飞书 API。

真实飞书前置检查：

```bash
lark-cli auth status
```

若 `tokenStatus: valid`，才能跑 `cli` 模式。

## 推荐环境变量

最小真实链路配置：

```bash
export FEISHU_MODE=cli
export FEISHU_MESSAGE_AS=bot
export FEISHU_DOC_AS=bot
export FEISHU_DOC_FALLBACK_AS=user
export FEISHU_PROGRESS_AS=user
export FEISHU_REPLY_IN_THREAD=true
```

Wiki 任务台账配置：

```bash
export FEISHU_PROGRESS_WIKI_URL="https://xiaopeng.feishu.cn/wiki/TBIEwZ7ZIi5Ct1kjQHoc8RmLnpO?table=tbld387ZPXuyuoPk&view=vew3h6TRri"
export FEISHU_PROGRESS_BASE_TOKEN="FetpbIFQCaDzccsiJulcW5tEn1b"
export FEISHU_PROGRESS_TABLE_ID=tbld387ZPXuyuoPk
export FEISHU_PROGRESS_VIEW_ID=vew3h6TRri
export FEISHU_PROGRESS_TEXT_FIELD="文本"
export FEISHU_PROGRESS_TASK_ID_FIELD="Task ID"
export FEISHU_PROGRESS_TASK_TYPE_FIELD="任务类型"
export FEISHU_PROGRESS_STATUS_FIELD="状态"
export FEISHU_PROGRESS_STAGE_FIELD="阶段"
export FEISHU_PROGRESS_REQUESTER_FIELD="请求人"
export FEISHU_PROGRESS_SUMMARY_FIELD="摘要"
export FEISHU_PROGRESS_DOC_URL_FIELD="文档链接"
```

文档公开权限配置：

```bash
export FEISHU_DOC_PUBLIC_ACCESS_ENABLED=true
export FEISHU_DOC_PUBLIC_PERMISSION_AS=user
export FEISHU_DOC_EXTERNAL_ACCESS=true
export FEISHU_DOC_LINK_SHARE_ENTITY=anyone_editable
export FEISHU_DOC_SHARE_ENTITY=anyone
export FEISHU_DOC_COMMENT_ENTITY=anyone_can_edit
export FEISHU_DOC_SECURITY_ENTITY=anyone_can_edit
```

启动问候与忙碌回复配置：

```bash
export FEISHU_BUSY_REPLY_TEXT="思考中"
export FEISHU_ENABLE_BOOTSTRAP_GREETING=true
export FEISHU_BOOTSTRAP_TARGET_NAME="杨星昊"
export FEISHU_BOOTSTRAP_TARGET_OPEN_ID=ou_xxx
export FEISHU_BOOTSTRAP_TARGET_CHAT_ID=oc_xxx
export FEISHU_BOOTSTRAP_GREETING="等待你的命令"
```

启动问候目标优先级：`FEISHU_BOOTSTRAP_TARGET_OPEN_ID` > `FEISHU_BOOTSTRAP_TARGET_CHAT_ID` > `FEISHU_BOOTSTRAP_TARGET_NAME`。生产环境优先配置 open_id 或 chat_id，避免姓名搜索不唯一。

## 飞书事件处理规则

入口：`POST /webhook/feishu/events`

处理规则：

1. 若 payload 包含 `challenge`，直接返回 challenge，供飞书 URL 校验。
2. 只处理 `header.event_type == "im.message.receive_v1"`。
3. 只处理 `message.message_type == "text"`。
4. 私聊 `chat_type == "p2p"` 直接处理。
5. 群聊需要被 mention，当前逻辑检查 `mentions` 中的 `Agent` / `agent` 或 open_id。
6. 文本内容从 `message.content` JSON 的 `text` 字段解析。
7. 构造 `FeishuMessage` 后调用 `orchestrator.create_task_from_message()`。

## 命令解析规则

`CommandParser` 将文本归一化：去掉 `@Agent` / `@agent`。

已支持：

- `查询 TASK-xxxxxx` -> `task.status`
- `启动 preprocess ...` 或 `启动预处理 ...` -> `pipeline.preprocess`
- `启动训练 ...` 或 `启动 train ...` -> `pipeline.train`
- `下载日志 ...` -> `logs.download`
- `生成报告 ...` 或 `评测报告 ...` -> `report.generate`
- 其他文本 -> `chat.reply`

参数格式使用 `key=value`，例如：

```text
启动预处理 clip_id=c-123 config=xpeng_data_process/configs/config_vision.yaml
启动训练 clip_id=c-123 cameras=023456 output_path=/workspace/output
下载日志 job_id=j-123 scenario_ids=s1,s2
生成报告 root_dir=/workspace/eval models=m1,m2
```

## 任务执行与队列

`TaskOrchestrator` 负责队列和执行：

- `create_task_from_message()` 创建任务并落 SQLite。
- 若当前忙碌，立即用 `SyncService.reply_busy()` 回复 `FEISHU_BUSY_REPLY_TEXT`，默认“思考中”。
- 新任务进入 `_pending_task_ids` 队列。
- startup 时 `application.orchestrator.start_worker()` 启动后台 worker。
- worker 使用 `asyncio.to_thread(self.run_task, task_id)` 串行执行任务。
- shutdown 时 `stop_worker()` 停止后台 worker。
- 执行失败会将任务标记为 `failed` 并尝试同步到飞书。

注意：webhook handler 不应长时间阻塞，应尽快创建任务并返回，让后台 worker 处理耗时任务。

## 飞书消息回传

`RealFeishuMessageClient` 使用 `lark-cli im`：

- 普通发送：`im +messages-send`
- 回复原消息/线程：`im +messages-reply`
- 默认 `FEISHU_MESSAGE_AS=bot`
- 若 `FEISHU_REPLY_IN_THREAD=true` 且有 `message_id`，优先回原消息线程。

常见权限/条件：

- bot 必须在群里，或对私聊对象可见。
- bot 身份依赖应用可见范围和 IM scopes。
- user 身份依赖当前登录用户对群/消息的访问权限。

## 飞书文档同步

`RealFeishuDocClient` 使用 `lark-cli docs`：

- 创建：`docs +create`
- 更新：`docs +update`
- 默认 `FEISHU_DOC_AS=bot`
- 如果文档操作权限不足，回退 `FEISHU_DOC_FALLBACK_AS=user`

文档创建/更新后会尝试设置公开权限：

```bash
lark-cli drive permission.public patch \
  --as user \
  --params '{"token":"docx_token","type":"docx"}' \
  --data '{"external_access":true,"link_share_entity":"anyone_editable","share_entity":"anyone","comment_entity":"anyone_can_edit","security_entity":"anyone_can_edit","invite_external":true}' \
  --yes
```

已知：公开权限 patch 需要飞书应用 scope `docs:permission.setting:write_only`。如果缺这个 scope，会报：

```text
App scope not enabled: required scope docs:permission.setting:write_only
```

## Wiki 表格任务台账

用户提供的任务进展页是 Wiki 页面，但底层对象是 bitable。通过 Wiki node 查询得到：

- `wiki node token = TBIEwZ7ZIi5Ct1kjQHoc8RmLnpO`
- `progress base token = FetpbIFQCaDzccsiJulcW5tEn1b`
- `table id = tbld387ZPXuyuoPk`
- `view id = vew3h6TRri`

查询 Wiki node 的方法：

```bash
lark-cli api GET /open-apis/wiki/v2/spaces/get_node --params '{"token":"TBIEwZ7ZIi5Ct1kjQHoc8RmLnpO"}'
```

写入记录使用：

```bash
lark-cli base +record-upsert \
  --as user \
  --base-token FetpbIFQCaDzccsiJulcW5tEn1b \
  --table-id tbld387ZPXuyuoPk \
  --json '{...}'
```

当前结构化字段：

- `Task ID`
- `任务类型`
- `状态`
- `阶段`
- `请求人`
- `摘要`
- `文档链接`
- `文本`

## 本地运行

```bash
cd agents
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8090
```

飞书开发者后台需要将事件订阅 URL 指到公网可访问的：

```text
https://<public-domain>/webhook/feishu/events
```

本地开发可用内网穿透或代理把 `127.0.0.1:8090` 暴露给飞书。

## 最小验证

本地伪造 webhook：

```bash
curl -X POST http://127.0.0.1:8090/webhook/feishu/events \
  -H 'Content-Type: application/json' \
  -d '{
    "header": {"event_id": "evt-local-1", "event_type": "im.message.receive_v1"},
    "event": {
      "sender": {"sender_id": {"open_id": "ou_xxx"}},
      "message": {
        "message_id": "om_xxx",
        "chat_id": "oc_xxx",
        "chat_type": "p2p",
        "thread_id": "omt_xxx",
        "message_type": "text",
        "content": "{\"text\":\"你好，帮我介绍一下你能做什么？\"}"
      },
      "mentions": []
    }
  }'
```

预期：

1. 返回 `{code: 0, msg: "ok"}`。
2. SQLite 中新增任务。
3. 任务类型为 `chat.reply`。
4. 飞书收到 bot 回复，证明 `飞书 -> Agent -> 飞书` 打通。

查询任务：

```bash
curl http://127.0.0.1:8090/tasks
curl http://127.0.0.1:8090/tasks/TASK-000001
```

## 常见问题

- `Permission denied [99991672]`：通常是 scope 未开、bot 不在群、应用可见范围不含目标用户、或当前身份不是文档/群资源的 owner/admin。
- `docs +create` 成功但 `permission_grant` 失败：文档创建成功，但给当前 user 授权失败；文档主流程可继续，必要时用 user fallback 或补权限。
- `drive permission.public patch` 失败且提示 `docs:permission.setting:write_only`：到飞书开放平台申请该 scope。
- `search:docs:read` 缺失：文档搜索能力不可用，不影响通过已知 token/url 操作文档。
- Wiki 链接不是 base token：先用 Wiki node token 查 `obj_token`，`obj_type=bitable` 时 `obj_token` 才是 base app token。
- `lark-cli` 命令参数不要手写拼接长字符串；Python 代码里优先使用 list args + `run_json_args()`，避免 shell quote 问题。

## 迭代建议

- 将 `lark-cli` 鉴权替换为正式 `app_id/app_secret` 服务端鉴权。
- 将普通文本回复升级为飞书卡片。
- 用 `Task ID` 实现真正幂等 upsert，避免 Wiki 表格重复记录。
- 将 executor 从“计划生成”升级为真实提交 Fuyao/训练/评测任务，并轮询状态。
- 增加事件去重表，基于 `event_id` 和 `message_id` 防止飞书重试导致重复任务。
