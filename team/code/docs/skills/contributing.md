# Skills 贡献指南

## 环境（同事 clone 后）

```bash
bash agents/scripts/setup-dev-environment.sh
```

安装 Python 依赖（`requirements-feishu.txt`）、`lark-cli`、`.cursor`/`.agents` 符号链接。未安装 `lark-cli` 时 Cursor 无法执行 **lark-\*** skill。

## 原则

- 所有 skill 只放在仓库根 **`skills/<name>/`**，不要在 `.cursor` 或 `.agents` 下复制第二份。
- `.cursor/skills`、`.agents/skills` 仅为指向 `skills/` 的符号链接（由 `agents/scripts/setup-skills-links.sh` 创建）。
- 用 Agent「总结成 skill」时，遵循 **`skills/3dgs-write-skill/SKILL.md`**。

## 命名

- `lark-*`：与飞书官方同步，谨慎手改；升级对照 `skills-lock.json`。
- `3dgs-*`：本仓库业务 skill，PR 需说明触发场景与依赖脚本。
- 勿在 skill 内提交 API Key、个人 open_id、CloudSim 密钥。

## 新增 3dgs skill 步骤

1. 创建 `skills/3dgs-my-feature/SKILL.md`（含 YAML frontmatter：`name`、`description`）。
2. 在 `skills/README.md` 表格中补充一行说明。
3. 如需脚本，放在 `skills/3dgs-my-feature/scripts/`。
4. PR 由至少一人 review。

## 升级 lark-* skills

按 `skills-lock.json` 中的 `source` 与 `computedHash` 从 `open.feishu.cn` 拉取新版本，覆盖 `skills/lark-*` 后更新 lock 中的 hash。
