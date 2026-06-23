---
name: agent-prompt
track: Agents
status: active
owner: 严潇竹
contributors:
  - 吕文杰（代码指导）
  - 郑丽娜（方向）
since: 2026-06-10
last_updated: 2026-06-15
sources:
  - memory/projects/Agents/Prompt-Agent.md
  - /tmp/q2wiki_by_project.json (key: Agents/Prompt-Agent, W11)
---

# Prompt Agent — 活文档

> 最后更新：2026-06-15 | 来源：Prompt-Agent.md + Q2 Wiki JSON W11

## 背景与目标

调试复现率 Agent 的 prompt，降低误报率。  
背景：复现率 Agent 一期上线后，gating 数据集中存在 prompt 误报 case，需要系统分析并针对性调优。严潇竹的第一个独立任务。

## 当前状态（截至 2026-06-12）

正在分析 gating 误报 case（已分三类），针对 AI 误判 case 进行调优。识别出 prompt 不对齐的两类系统原因：指令跟随生效配置不一致、多高亮功能导致提示词变化。仿真车/实车分离引发的因果颠倒误报待排期处理。

## 时间线（按时间倒序）

### 2026-06-11 — 误报case分类，针对AI误判调优
- 生产部门分析完 gating 级 prompt 误报 case，严潇竹根据人工+AI 结果调整提示词 [来源：Prompt-Agent.md]
- 郑丽娜建议先调 scale，不行再看简化处理 [来源：Prompt-Agent.md]
- gating 集 prompt 误报 case 分为三类 [来源：JSON W11]：
  1. **参考AI**：涉及阈值，人工觉得有影响而给了分歧，差距实际可能不大
  2. **不参考AI**：人工自判，思路与 AI 不同但结论可能一致
  3. **误判**：如把 S/R 分离后范围的不对齐也采纳了，或对阈值判别过度敏感
- 目前提取了重点 case，针对 AI 误判 case 进行调优 [来源：JSON W11]
- 与生产沟通，疑似误报 case 进行人工二次核验 [来源：JSON W11]
- Prompt 是否对齐结论分析中，初步评估不对齐存在两类原因：指令跟随生效配置不一致(e.g. 6/15)、多高亮功能导致提示词变化 [来源：JSON W11]
- Prompt Agent 自身误报根因：仿真车和实车分离导致的因果颠倒，待排期改进 [来源：JSON W11]

### 2026-06-10 — 任务分配
- 郑丽娜安排严潇竹调试 Agent prompt，作为第一个独立任务 [来源：Prompt-Agent.md]

### 2026-06-09 — 入群
- 严潇竹入群，李坤邀请 [来源：Prompt-Agent.md]

## 变道晚检测指标设计（来源：变道晚检测流水线 PXZWwJBd）

**指标代号**：`closed_loop_late_lane_change`  
**适用场景**：导航变道（Routing LC）、避障绕行变道（Active LC）  
**核心逻辑**：物理锚点定位 → 拓扑分化速决 → 语义因果归因 → 激进副作用复核

### 四节点串行专家工作流

| 节点 | 名称 | 核心功能 |
|------|------|---------|
| Node 1 | 拓扑分化与导航依从裁判 | 检测 A/B 是否被车道线物理隔开；走错道直接判 Loss；拓扑重合判 Tie；拓扑分化触发 Node 2 |
| Node 2 | 意图与博弈提取器 | 判断早期变道意图 + 目标车道是否有博弈压制 |
| Node 3 | 微观语义排雷兵 | 防误报兜底：排查隐性物理障碍（锥桶 / 旁车红灯） |
| Node 4 | 激进安全稽查员 | 并行执行，复核较早变道方是否有激进加塞（间隙极小 / 锐角横切 / 压实线） |

### 工程约束

- 所有 `uncertain` / `insufficient_evidence` 路由至 `ReviewRequired`，不强行判定
- 职责严密隔离：前置脚本（计算死线/完成点，渲染 BEV）/ VLM 工作流（语义感知）/ 后台状态机（查表定性）
- Node 4 仅降级为 `ReviewRequired` 或 `Mixed`，不直接判负

## 仿真仓库优化方案（来源：simworld仓库优化与回归测试 O1CXdGF2）

### 优化背景

simworld 仓库已从"单一模型研发"演进为"预处理 + 多模型 + 生产 + 闭环仿真 + HIL"复合工程：关键入口分散、命名不统一、旧链路与新链路并存（如 UCP 旧/新入口并存），维护成本持续放大。

### 目标目录结构

- `pipeline/fuyao/` — Fuyao 部署链路（原 `fuyao_deploy`）
- `pipeline/ucp/` — UCP 生产链路（原 `ips_deploy`）
- `models/` — 一模型一目录（nvfixer / difix / g3r / nail_evolsplat / street_gaussians 等）
- `hil/` — HIL 相关（原 `hil_3dgs_server`）
- `libs/xpeng_raster/` — 基础库（原 `xpeng_raster`）
- `agents/` — feishu_3dgs_agent 等
- `sim_interface/`、`xpeng_data_process/`、`omnire_joint_trainning/`、`tools/` 保留

### 核心目录映射

| 旧路径 | 新路径 |
|--------|--------|
| `fuyao_deploy` | `pipeline/fuyao` |
| `ips_deploy` | `pipeline/ucp` |
| `hil_3dgs_server` | `hil` |
| `xpeng_raster` | `libs/xpeng_raster` |
| `feishu_3dgs_agent` | `agents` |

### 四大回归验收域

以 **Fuyao / UCP / 闭环仿真 / HIL** 四条链路全部通过为验收基线；每条链路新人可在 30 分钟内定位入口并跑通 smoke test。

### 实施计划

1. **文件架构重构（0.5 天）**：新建目录骨架，迁移并修复显式路径引用，输出旧→新路径迁移清单
2. **3DGS 训练/渲染/预处理整理（1 天）**：归一 Reconic 训练/预处理入口脚本，删除废弃重复脚本，输出《训练与预处理脚本映射表》
3. **闭环仿真与 UCP 生产代码整理（1 天）**：梳理 UCP 入口（clip/subrun/多车型/difix 分支），历史脚本加 `deprecated` 标识，输出《生产与仿真入口 Runbook》

UCP 任务提交参数规范（`job_resource_request`、`application_config`、`processors_config` 等）详见任务参数说明（来源：UCP_3dgs任务参数说明 B99cwamI）

## 风险与阻塞（当前）

- 🔴 仿真车/实车分离导致的因果颠倒误报，根因已知但待排期改进 [来源：JSON W11]
- 🟡 Prompt 不对齐二类系统原因（指令跟随配置、多高亮功能）尚未解决 [来源：JSON W11]

## 关键决策记录

- **2026-06-11**：将误报 case 分三类处理（参考AI分歧、不参考AI、AI误判），优先针对第三类调优 [来源：JSON W11]
- **2026-06-11**：郑丽娜决策先调 scale，不行再看简化处理 [来源：Prompt-Agent.md]

## 相关文档

| 文档 | doc_id | 状态 | 用途 |
|------|--------|------|------|
| 变道晚检测流水线 | PXZWwJBdQiU35gkIuY7cqg5wnmf | ✅ 已读 | 指标定义与检测逻辑 |
| simworld 仓库优化与回归测试 | O1CXdGF2HoUJ3axrBHQcTMBHn2d | ✅ 已读 | 仓库优化方案与回归测试 |
| UCP 3dgs 任务参数说明 | B99cwamIjiVpoMkSYncctsWNnye | ✅ 已读 | UCP 平台参数规范 |
