---
name: closed-loop-sim
description: 闭环仿真规模化落地 — Q2核心战役
metadata: 
  node_type: memory
  type: project
  originSessionId: 1b82ee7e-8c3b-4c47-81c6-9b8342353437
---

## 闭环仿真规模化落地（Q2主战役）

### 目标
完成闭环基线摸底，打通 HIL + 3DGS + 模型主链路，在至少一个重点业务方向进入固定节奏试运行。

### 三条线
1. 10个闭环问题集 + SIL
2. 开环车型泛化实验 + SIL
3. RC 1000公里 + HIL

### OKR结构
- **O1 SIL链路**：业务Owner郑丽娜 | 技术Owner杨星昊
  - KR1: 最小闭环+性能基准，漏报率<20%（吕文杰）
  - KR2: 标准化评测卡口（吕文杰）
  - KR3: 渲染提效→单帧0.5s、性能比1:5（裴健宏+王禹丁）
- **O2 HIL链路**：业务Owner郑丽娜 | 技术Owner杨星昊
  - KR1: 集成链路+递进式验证（朱啸峰）
  - KR2: 纯3DGS复现率50%+、+dfix 60%（瞿鑫宇+周冯）
  - KR3: 等效性验证卡口+200+台架（朱啸峰）
- **O3 生产链路**：业务Owner郑丽娜 | 技术Owner杜思聪
  - KR1: 日产1000 case、Q2末1wkm（杜思聪+周冯）
  - KR2: CornerCase场景定制（郑丽娜）
  - KR3: golden testcase+自动化质检（周蔚旭）
- **O4 算法预研**：业务Owner李坤 | 技术Owner杨星昊
  - KR1: Diffusion新模型（周冯）
  - KR2: Feedforward新方法（杜思聪+周冯）
  - KR3: Smart Agent（裴健宏）
  - KR4: 3DGS场景泛化（王禹丁）

### 6月关键Milestone
| 项目 | 当前状态 | 6月目标 |
|------|----------|---------|
| 场景集构建 | 90%完成 | 6/20完成7类metric验收 |
| RC路线 | 4车采集中 | Q2末1000km |
| SIL复现率 | — | 80%+，效率1:25 |
| HIL效率比 | 最优1:2.5 | 目标1:3，稳定率95%+ |
| 极速模式 | UCP迁移中 | **6/10下周一上线** |
| 场景编辑 | 代码合入simworld | **6/12自动化CLI完成** |

### 核心风险
- **缺卡**：A100不足，Diff重训、大规模生产受限
- **IT延迟**：镜像编译未完成
- **闭环Metric**：6/20才验收，可能延迟场景毕业

[[team-scope]] [[current-initiatives]]
