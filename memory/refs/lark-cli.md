---
name: lark-cli-patterns
description: lark-cli 常用命令模式和关键参数速记
metadata: 
  node_type: memory
  type: reference
  originSessionId: 8bb9d7ea-4c4a-494a-a59c-97184b907273
---

**读文档**：`lark-cli docs +fetch --api-version v2 --doc "<url>" --format json`
**读目录**：同上，加 `--scope outline --max-depth 3`
**读章节**：同上，加 `--scope section --start-block-id <标题id>`
**关键词搜索**：同上，加 `--scope keyword --keyword "词1|词2"`
**创建文档**：`lark-cli docs +create --api-version v2 --content '<title>标题</title>...'`
**编辑文档**：`lark-cli docs +update --api-version v2 --doc "<url>" --command append/str_replace/block_insert_after/block_replace/block_delete ...`
**读表格**：`lark-cli sheets +fetch --sheet "<token>" --sheet-id "<sheet-id>" --format json`
**Wiki节点**：`lark-cli wiki +node-list` / `+node-create` / `+move` / `+space-list`

**关键参数**：
- `--api-version v2`：docs 操作必须显式传入
- `--as user`：默认用户身份
- `--format json`：输出 JSON 格式
- `--detail`：simple（默认，只读）| with-ids（含block_id）| full（编辑用）

**Why:** 避免每会话重复查 skill 文档获取命令格式。
**How to apply:** 常见操作直接使用上述命令模板，不确定的参数才去读 .claude/skills/ 下的 reference 文件。
