---
kind: external_dependency
name: lark-cli — 飞书 OpenAPI 命令行客户端
slug: lark-cli
category: external_dependency
category_hints:
    - framework_behavior
    - auth_protocol
scope:
    - '**'
---

### lark-cli
- **角色**：统一调用飞书 OpenAPI 的 CLI 二进制，被 cron 任务、meal 脚本、team 报告生成器广泛使用。
- **行为模式**：以独立进程运行，凭据通过 `/platform/.lark-cli` 持久化；首次初始化用 `config init --new` 指定工作区域，再用 `auth login` 完成 OAuth 设备码授权。
- **认证协议**：OAuth device flow（`accounts.feishu.cn/oauth/v1/device/verify?flow_id=...&user_code=...`），扫码或点击链接完成授权。
- **注意**：多工作区场景下必须为每个工作区单独 `config init --new`，否则跨域文档会返回 permission denied。