# 训练仿真评测闭环 Agent（train-sim-eval-agent）

用一个 **Agent + 工作流引擎（Temporal）** 把"编包 → 提交仿真 → 等待 → 拉取评测 → 生成报告 → 发送飞书"的人工闭环自动化。

- 设计文档：[docs/architecture-design.md](docs/architecture-design.md)
- 开发文档：[docs/development-guide.md](docs/development-guide.md)
- 台架部署（5080 / Server，含无外网离线装 Temporal）：[docs/deployment-bench.md](docs/deployment-bench.md)
- 客户端 CLI 安装与使用（使用方）：[docs/client-cli-setup.md](docs/client-cli-setup.md)

## 架构要点

- **三层心智模型**：`Workflow`（确定性、无副作用）/ `Activity`（一切 IO）/ `Server·CLI`（普通应用代码）。
- **固定流水线**：pipeline 是确定的（编包→提交→等待→评测→报告→飞书），由 `ExperimentWorkflow` 编排；**无 Planner Agent / 任务规划，全程无 LLM**。
- **报告即产物**：`EvaluateActivity` 跑 simworld 工具产出「渲染耗时统计 CSV + FM 轨迹评测图片」，`ReportActivity` 直接把这些文件发飞书，**不经 LLM 摘要**。
- **低成本等待**：仿真等待封装在后台 `monitor_wait` Activity 内做纯 API 轮询 + heartbeat，等待期 token 成本 ≈ 0。
- **状态外置**：流程状态由 Temporal 持久化，并镜像到 SQLite 供查询；Agent 自身无状态、可随时重启。
- **幂等**：`build_key` / `submit_key` / `experiment_id` 去重，崩溃恢复不重复编包/提交/发报。

## 目录结构

```
tse/
├── config.py            # Settings（pydantic-settings）
├── constants.py         # 状态枚举、重试策略、任务队列、开关白名单
├── errors.py            # 统一错误类型
├── models/              # domain（Pydantic 模型）、db（DDL）
├── store/               # SQLite 读写（ExperimentRepo）
├── integrations/        # bench / sim_cloud / simworld_tools / feishu（外部系统适配）
├── activities/          # mirror_status / build / submit / monitor / evaluate / report
├── workflows/           # ExperimentWorkflow（状态机）
├── request/             # build_request 校验 + start_experiment 启动（无 LLM）
├── server/              # auth / control_api / agentd
├── cli/                 # 远程瘦客户端（run/status/list）
└── worker.py            # Worker 注册（pydantic data converter）
```

## 安装

依赖按角色拆分，各取所需：

```bash
# 台架（服务端，tse-agentd）：服务端全套 + 评测画图（+ ssh 编包可加 ,ssh）
pip install -e ".[server,eval]"

# 使用方（瘦客户端，tse）：仅 typer + httpx，体积小
pip install ".[client]"

# 开发/测试（跑全量测试，含服务端依赖）
pip install -e ".[dev]"
```

## 本地启动与冒烟验证

```bash
# —— 台架（Agent host）——
# 1) Temporal dev server（持久化 + 仅本地监听）
temporal server start-dev --db-filename ./temporal.db --ip 127.0.0.1

# 2) agentd（控制 API + Worker 同进程，无 LLM）
export TSE_CONTROL_TOKEN=dev-token
export TSE_SIM_X_TOKEN=...  TSE_SIM_X_ACCOUNT=...  TSE_FEISHU_APP_ID=...  TSE_FEISHU_RECEIVE_ID=...
tse-agentd                       # 默认监听 0.0.0.0:8443

# —— 远程设备（用户侧）——
export TSE_ENDPOINT=https://<bench-host>:8443
export TSE_CONTROL_TOKEN=dev-token
tse run --rerun-job-id 134316 --sim-x-token <仿真平台x-token> --sim-x-account you@xiaopeng.com --set use_difix=true
tse status <experiment_id>
```

## 测试

```bash
pytest
```

工作流测试用 `WorkflowEnvironment.start_time_skipping` 跳过长等待，秒级验证 10 态流转。

## 待对接（TODO）

| 位置 | 说明 |
| --- | --- |
| `integrations/simworld_tools.py` | simworld `tools/` 下载/评测脚本路径与 `eval_*` 基线 job 校准 |
| `integrations/sim_cloud.py` | 仿真平台 submit/query 接口与终态字符串 |
| `integrations/feishu.py` | 飞书 app 凭据与 `receive_id`/`receive_id_type`（报告发文件/图片） |
| `integrations/bench.py` | `upload_binary.py` 输出格式校准 `_BINARY_ID_RE`，必要时前置切分支 |
