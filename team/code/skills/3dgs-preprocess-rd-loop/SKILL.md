---
name: 3dgs-preprocess-rd-loop
description: Drives the 3DGS preprocess optimization R&D loop from a Cursor user request. MUST use when the user mentions “3dgs预处理”, “3DGS 预处理”, preprocess optimization, processor speedup/stability/quality/cost work, Fuyao preprocess experiments, or closed-loop AI R&D for preprocessing. Structures requirements, creates a Feishu design doc, waits for confirmation in Cursor, submits a Fuyao baseline before code edits, develops on a new branch without auto-commit, runs candidate experiments, polls status, validates results, and iterates.
---

# 3DGS 预处理闭环研发流程

## 触发场景

当用户在 Cursor 对话窗口提出 3DGS 预处理相关优化需求时必须使用本流程。触发词包括但不限于：
- `使用全智能模式`
- `3dgs预处理`
- `3DGS 预处理`
- `预处理优化`
- `preprocess 优化`
- `processor 太慢 / 提速 / OOM / 失败 / 质量不稳定 / 成本太高`
- `img_processor`、`sam3d_processor`、`mvsnet_processor`、`pcd_fusion_processor` 等 processor 相关优化

典型需求示例：

- `img_processor 太慢，需要提速`
- `sam3d_processor 容易 OOM，帮我优化`
- `mvsnet_processor 结果质量不稳定`
- `预处理链路成本太高，需要降资源消耗`

相关基础 Skill：

- `skills/3dgs-preprocess-task/SKILL.md`：预处理任务、配置、Fuyao 提交与状态查询。
- `skills/3dgs-feishu-rd-agent/SKILL.md`：飞书 Agent、文档、消息、任务台账。

## 固定约束

1. 需求入口是 Cursor 对话窗口；用户和 AI 的方案确认、是否继续、是否停止迭代等交互都在 Cursor 窗口完成，不依赖飞书消息确认。
2. 每个需求自动创建新分支；不允许自动 commit。
3. 方案文档生成后必须等待用户在 Cursor 中确认，确认前不能改代码。
4. 飞书仅用于向默认用户同步方案文档、实验状态和结论；消息发送必须使用 bot 身份，默认用户为杨星昊：`ou_b1580eda1ea60b5f2fc9a91e3609f101`，默认 bot 会话为 `oc_06e2113693f57188a147099c6a9adc60`。
5. 飞书 Agent 中只有用户输入以“大模型”开头时才允许调用 API 大模型；普通飞书文本不能消耗模型 API。
6. Baseline 必须先在当前未修改的 baseline 分支提交到 Fuyao；确认 Fuyao baseline 已开始正常运行后，才能创建/切换新分支并改代码。
7. 不允许修改 baseline 分支；测试新分支时仓库内容均可修改，但必须保护用户已有改动。
8. 预处理任务入口固定为 `pipeline/fuyao/deploy_preproc.bash`。
9. Fuyao 的 queue / site / project / experiment 固定，提交前可以先查询可用资源；允许自动连续提交多个实验，但要避免过量排队。
10. 提交后必须记录 Fuyao job id；如果 deploy 输出无法直接提取 job id，用 job_name 结合 Fuyao view/history 反查。
11. 任务运行中每隔 10 分钟查询 Fuyao 状态，并查看结果文件或 log，反馈任务跑到哪个 processor / 阶段。
12. 默认实验 clip 由 Skill 文件或 `xpeng_data_process/configs/config_vision.yaml` 记录；用户未给 clip/config 时使用默认配置。
13. 每次实验配置放到 `outputs/agent_experiments/<task_id>/config.yaml`。
14. 产物放到 `<config_vision.yaml 中 datasets[0].root>/<exp_id>`，当前默认 root 是 `/workspace/yangxh7@xiaopeng.com/datasets/xpeng/agent`。
15. 单元测试允许先跑，但必须 dry run，不能修改预处理结果文件。
16. 失败后自动迭代；每次实验维护同一个飞书文档，追加简洁、可读的迭代记录。
17. `agents` 运行在本机长期进程；飞书文档、消息和 Fuyao 权限默认已具备。
18. 飞书 Agent 相关流程见 `skills/3dgs-feishu-rd-agent/SKILL.md`、`skills/3dgs-preprocess-task/SKILL.md`、本文件。

## 飞书与大模型链路

- 方案文档、实验状态和结论必须通过飞书 bot 发给默认用户杨星昊，而不是用 user 身份自发自收。
- 默认配置：`FEISHU_MESSAGE_AS=bot`、`FEISHU_DOC_AS=bot`、`FEISHU_DOC_FALLBACK_AS=user`、`FEISHU_BOOTSTRAP_TARGET_OPEN_ID=ou_b1580eda1ea60b5f2fc9a91e3609f101`、`FEISHU_BOOTSTRAP_TARGET_CHAT_ID=oc_06e2113693f57188a147099c6a9adc60`。
- 飞书 Agent 中，只有用户消息以“大模型”开头时才允许调用 API 大模型；普通飞书消息只做规则回复或任务命令解析。
- Cursor 中的用户确认是权威确认来源：方案是否执行、是否继续迭代、是否停止，都以 Cursor 对话为准。
- `agents` 的仓库智能回复只是 Skill 文件上下文注入，不等同于完整 Cursor 工具能力；真正研发闭环仍由 Cursor Agent 在本仓库中按本 Skill 执行。

## 需求结构化字段

收到自然语言需求后，整理为以下字段；缺省项由 Agent 预估并写入方案文档：

| 字段 | 说明 |
| --- | --- |
| `task_id` | 需求 ID，例如 `PREOPT-YYYYMMDD-<MODULE>` |
| `requester` | 默认 `杨星昊`，身份信息使用 Feishu Agent 现有配置位 |
| `target_processor` | 目标 processor，如 `img_processor` |
| `optimization_type` | `speed` / `stability` / `quality` / `cost` / `mixed` |
| `problem_statement` | 用户原始问题与 Agent 归纳 |
| `baseline_branch` | 当前 baseline 分支，提交 baseline 后保持不修改 |
| `candidate_branch` | 新建开发分支，如 `agent/preprocess-opt/<task_id>` |
| `base_config` | 默认 `xpeng_data_process/configs/config_vision.yaml` |
| `generated_config` | `outputs/agent_experiments/<task_id>/config.yaml` |
| `clip_ids` | 用户给定或从默认配置读取 |
| `exp_id` | 实验 ID，用于产物目录与 job_name |
| `output_root` | `<dataset_root>/<exp_id>` |
| `baseline_job_id` | Baseline Fuyao job id |
| `candidate_job_ids` | 候选方案 Fuyao job id 列表 |
| `acceptance_rules` | 通过/不通过规则，用户未给时由 Agent 预估 |
| `iteration_limit` | 自动迭代上限，未指定时建议 2~3 轮 |
| `doc_url` | 飞书方案与实验记录文档 |

## 内置飞书 Markdown 文档模板

创建飞书文档时先使用精简 Markdown 模板，标题格式：

```markdown
# [PREOPT-YYYYMMDD-XXX] 预处理优化方案：<target_processor>

> 当前状态：方案待确认。确认后将先提交 baseline Fuyao 任务，待 baseline 正常运行后再创建开发分支并改代码。

## 1. 需求摘要

| 项 | 内容 |
| --- | --- |
| 请求人 | 杨星昊 |
| 目标模块 | <target_processor> |
| 优化类型 | <optimization_type> |
| 默认配置 | xpeng_data_process/configs/config_vision.yaml |
| 实验配置 | outputs/agent_experiments/<task_id>/config.yaml |
| 产物目录 | <output_root> |

## 2. 当前假设

- <假设 1>
- <假设 2>
- <风险>

## 3. 方案设计

| 方向 | 做法 | 风险 | 验证方式 |
| --- | --- | --- | --- |
| <方向> | <做法> | <风险> | <验证方式> |

## 4. 实验计划

1. 在 baseline 分支用原始配置提交 Fuyao baseline。
2. 确认 baseline job 已正常运行后，创建新分支开发。
3. 本地 dry-run 单元测试，不改结果文件。
4. 用候选分支提交 Fuyao 实验。
5. 每 10 分钟同步 Fuyao 状态与阶段。
6. 结束后解析 Fuyao CLI、log、产物与代码变化，自动判断是否通过。

## 5. 默认验收指标

| 类型 | 目标 |
| --- | --- |
| 提速 | 总耗时或目标 processor 耗时较 baseline 降低 >= 15% |
| 稳定性 | 无新增失败/OOM/异常退出 |
| 质量 | 必要产物完整，关键文件数量/结构无明显退化；必须对比 `input_ply/points3D_bkgd.ply` 与 baseline 的点数、包围盒、中心、尺度和抽样分布，确认背景点云质量差异不大后才允许判定通过 |
| 成本 | GPU/排队/运行资源无明显增加，若增加需有收益解释 |

## 6. 待用户确认

回复“确认执行”后开始：baseline Fuyao 提交 → 等待 baseline 正常运行 → 新分支开发 → 候选实验 → 结论校验 → 自动迭代。

## 7. 实验记录

- v0 baseline：待提交
- v1 candidate：待开发
```

## Baseline 与开发顺序

1. 读取当前 git 状态，记录 baseline 分支和未提交变更。
2. 如果工作区有用户修改，必须避免把 baseline 任务建立在不明确状态上；必要时询问用户是否允许继续，或建议先保存/隔离。
3. 生成 baseline 配置到 `outputs/agent_experiments/<task_id>/config.yaml`，配置应指向 baseline 产物目录 `<root>/<exp_id>_baseline`。
4. 调用 `bash pipeline/fuyao/deploy_preproc.bash <generated_config> <job_name>` 提交 baseline。
5. 解析并记录 Fuyao job id。
6. 用 `fuyao view --site fuyao_b1_prod2 --only-me` 或 `fuyao history --site fuyao_b1_prod2 --limit 20` 确认 baseline 已进入 running / 正常运行。
7. 只有完成第 6 步，才可创建新分支并开始代码开发。

## 开发与测试规则

- 分支命名建议：`agent/preprocess-opt/<task_id-lower>`。
- 不允许自动 commit。
- 修改某个 processor 后，优先查找并运行对应 dry-run 单元测试。
- 若没有单测，至少做静态检查、局部 import 检查或增加不写产物的 dry-run 验证。
- 不得覆盖 `xpeng_data_process/configs/config_vision.yaml`；单次实验只能写入 `outputs/agent_experiments/<task_id>/config.yaml` 或同目录派生配置。

## Fuyao 状态轮询

- baseline/candidate 提交后，每 10 分钟查询一次。
- 运行中需要同步给用户：job id、job_name、状态、当前 processor/阶段、已运行时间、最近 log 摘要。
- 结束后同步：成功/失败、耗时、产物目录、主要指标、是否通过、下一轮动作。
- 查询失败连续 3 次时提醒用户并保留任务继续轮询。

## 默认通过/不通过规则

如果用户没有给规则，按优化类型预估：

- `speed`：目标 processor 或总耗时降低 >= 15%；稳定性、质量、成本无明显退化；`input_ply/points3D_bkgd.ply` 必须与 baseline 点云质量相差不大。
- `stability`：目标失败模式消失；耗时/质量无明显退化；`input_ply/points3D_bkgd.ply` 必须与 baseline 点云质量相差不大。
- `quality`：目标质量指标提升；耗时和成本退化不超过 10%，除非方案文档提前说明；`input_ply/points3D_bkgd.ply` 必须与 baseline 点云质量相差不大。
- `cost`：GPU/CPU/IO/存储等成本下降；成功率和质量无明显退化；`input_ply/points3D_bkgd.ply` 必须与 baseline 点云质量相差不大。

## 自动迭代

- 不通过时自动分析 Fuyao CLI 输出、log、产物、代码改动，提出下一轮假设并继续迭代。
- 每轮迭代追加到同一飞书文档，保持简洁：变更点、job id、结果、结论、下一步。
- 默认最多 3 轮；若连续失败或风险升高，停止并请求用户介入。
