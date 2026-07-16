---
kind: external_dependency
name: Temporal.io — 训练-仿真-评测闭环编排引擎
slug: temporal-io
category: external_dependency
category_hints:
    - sdk_real_api
    - framework_behavior
scope:
    - '**'
---

### Temporal.io
- **角色**：驱动 `train-sim-eval-agent` 的分布式工作流引擎，编排「编包 → 提交仿真 → 监视等待 → 评测拉取 → 报告发送」五阶段实验流水线。
- **SDK 用法**：服务端 `agentd.py` 在同一进程中同时启动 FastAPI 控制 API 与 Temporal Worker；Worker 通过 `pydantic_data_converter` 直接序列化 Pydantic 模型作为 Workflow/Activity 参数。
- **架构要点**：状态镜像写 DB 封装为 Activity（不能在 workflow 内做副作用）；各阶段 Activity 均带 retry_policy 与 start_to_close_timeout；监控阶段使用 heartbeat_timeout 防止长时间轮询超时。