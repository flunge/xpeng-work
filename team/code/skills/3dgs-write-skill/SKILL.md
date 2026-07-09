---
name: 3dgs-write-skill
description: >-
  Writes or updates Agent Skills for this repository. Use when the user asks to
  summarize something into a skill, create/add a project skill, write SKILL.md,
  or says 总结成 skill / 写成 skill / 添加到 skills / 新建 skill / 整理成 skill 文件.
---

# 3DGS 仓库内编写 Skill

## 硬性规则（必须遵守）

当用户要求把某段流程、文档、对话或经验**总结成 Skill**、**写成 Skill**、**添加到 skills** 时：

1. **只写入仓库根目录 `skills/<skill-name>/`**，主文件为 `SKILL.md`。
2. **禁止**在以下路径创建或修改 Skill 正文（这些目录仅允许本地符号链接，且已在 `.gitignore` 中）：
   - `.cursor/skills/`
   - `.agents/skills/`
   - `~/.cursor/skills/`（除非用户明确要求个人全局 skill，且与团队仓库无关）
3. **禁止**把 Skill 复制一份到 `.cursor` / `.agents`；clone 后由同事自行执行 `bash agents/scripts/setup-skills-links.sh`，链接会自动指向 `skills/`。
4. `git pull` 更新 `skills/` 后**不需要**重新跑链接脚本；只有链接不存在或损坏时才需要。

## 目录与命名

```text
skills/
  <skill-name>/
    SKILL.md          # 必需
    references/       # 可选
    scripts/          # 可选
```

| 类型 | 命名前缀 | 示例 |
|------|----------|------|
| 本仓库 3DGS 流程 | `3dgs-` | `3dgs-preprocess-task` |
| 飞书官方（从 open.feishu.cn 同步） | `lark-` | `lark-im` |
| 其他工具/报告 | 语义化短名 | `cloudsim-cces-job-report` |

- `skill-name` 使用小写、连字符，与 frontmatter 中 `name` 一致。
- 不要与 `skills/` 下已有目录重名；新增前先扫一眼 `skills/` 列表。

## SKILL.md 结构

```markdown
---
name: skill-name
description: >-
  一句话说明做什么；写明触发场景（中英文关键词），便于 Agent 自动选用。
---

# 标题

## 何时使用
...

## 步骤 / 命令
...
```

- `description` 必须包含用户会说的触发词。
- 正文简洁、可执行；命令用仓库内真实路径。
- **不要**在 Skill 里提交密钥、个人 open_id、绝对路径默认值；用 `.env.example` 或占位符。

## 工作流程

1. **理解素材**：用户提供的对话、文档、脚本或「把 XXX 总结成 skill」中的 XXX。
2. **定名与范围**：选一个 `skills/<name>/`，判断用 `3dgs-` 还是其他前缀。
3. **写入文件**：创建或更新 `skills/<name>/SKILL.md`（及必要的 `references/`、`scripts/`）。
4. **不碰** `.cursor/`、`.agents/`（除提醒用户链接已自动生效外）。
5. **收尾**：
   - 若新增团队级 skill，在 `skills/README.md` 的说明表中补一行（仅当值得长期保留时）。
   - 提醒：提交 Git 的是 `skills/` 目录；同事首次 clone 需 `bash agents/scripts/setup-dev-environment.sh`（含 `lark-cli` 与 Python 依赖）。
   - 更细的协作规范见 `docs/skills/contributing.md`。

## 常见用户表述 → 动作

| 用户说法 | Agent 动作 |
|----------|------------|
| 把…总结成 skill | 在 `skills/<新名>/SKILL.md` 写总结后的可复用流程 |
| 更新 xxx skill | 只改 `skills/xxx/SKILL.md`（及该目录下附属文件） |
| 加到 .cursor skills | **纠正**：应写到 `skills/`，并说明链接机制 |
| 同步到 agents | 同上，只维护 `skills/` |

## 反例（禁止）

```text
❌ 写入 .cursor/skills/my-skill/SKILL.md
❌ 复制 skills/foo 到 .agents/skills/foo
❌ 仅改 symlink 目标下的文件而不改 skills/ 源目录
✅ 写入 skills/my-skill/SKILL.md
```

## 相关文档

- 团队 Skills 总览：`skills/README.md`
- 贡献规范：`docs/skills/contributing.md`
- 链接脚本：`agents/scripts/setup-skills-links.sh`
