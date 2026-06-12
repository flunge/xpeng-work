---
name: project-context
description: 项目的核心定位、工作方式和技术约束
metadata: 
  node_type: memory
  type: project
  originSessionId: 8bb9d7ea-4c4a-494a-a59c-97184b907273
---

本项目（/Users/xpeng/Documents/team）是仿真部飞书工作空间交互项目，核心目标是通过 lark-cli 与飞书进行文档读写和内容管理。

**技术栈**：lark-cli（命令行工具），飞书 API v2。

**关键约束**：
- 所有 lark-cli 操作默认使用 `--as user`（用户身份）
- `docs +fetch` 和 `docs +create`、`docs +update` 必须显式传 `--api-version v2`
- 写操作前必须确认用户意图
- 优先用 shortcut（`lark-cli <service> +<verb>`）而非直接调 API

**Why:** 用户不希望每次新会话都要重新解释如何读文档、写文档。
**How to apply:** 见到飞书 URL 直接用 docs +fetch 读取，不要先读 skill 文件再行动。详细的命令参考见 CLAUDE.md。
