# .claude/agents — 内化的开发流程职责

> 原平台脚手架（kiro）的多 agent 流程已内化为本工作区的职责文档。
> 平台用 6 个独立 agent 串成 requirements→design→tasks→development→testing→review 流水线；
> 在本 monorepo 里它们**折叠为单助手（灵犀）顺序执行**——按需取用对应阶段的职责，不再依赖
> 平台脚手架的 `steering/context.md`、`{spec_dir}` 等外部路径。

## 职责一览

| 阶段 | 文件 | 职责 |
|------|------|------|
| 需求 | [requirements.md](requirements.md) | 澄清需求、生成结构化需求与验收标准（EARS） |
| 设计 | [design.md](design.md) | 需求驱动的技术设计、API 策略、数据结构 |
| 任务 | [tasks.md](tasks.md) | 拆 3–6 个可独立验证的任务，需求全覆盖、双向可追溯 |
| 开发 | [development.md](development.md) | 按任务实现、每步编译验证、需求覆盖自检 |
| 测试 | [testing.md](testing.md) | 真实测试（UI/API/平台），如实报告 |
| 审查 | [review.md](review.md) | 只审不改、安全扫描、可操作的改进建议 |
| 审稿 | [reviewer.md](reviewer.md) | 述职/汇报内容审稿人：以「不了解你工作的领域专家」视角，审内容能否听懂 + 格式 + 口吻 |

## 使用约定

- **简单改动**：直接进入开发职责（等价平台的 quick-agent），不必走全流程。
- **复杂任务（5+ 文件 / 多模块）**：用待办列表分解，按"先定位→实现→每步验证"推进，必要时显式经过设计/任务阶段。
- 全流程的通用安全红线、工作方式、输出格式见上级 [../CLAUDE.md](../CLAUDE.md)，此处不重复。
- 平台原有的 `spec_dir`（requirements.md/design.md/tasks.md）产出物机制在本仓库**默认不落盘**（快速模式）；
  确需 spec 文档时，放到对应项目的 `docs/spec/` 下。
