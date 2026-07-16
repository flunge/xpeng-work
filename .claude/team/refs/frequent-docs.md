---
name: frequent-doc-context
description: 已读取的飞书文档全量索引，含会议体系
metadata: 
  node_type: memory
  type: reference
  originSessionId: 1b82ee7e-8c3b-4c47-81c6-9b8342353437
---

## 飞书文档全量索引

### 核心文档

| 文档 | Token | 内容 |
|------|-------|------|
| 人员名单 | `YjSUwQygaiavNskGxjgcVm7NnOc` (sheet) | 仿真算法组13人，筛选：四级部门="仿真算法组" |
| Q2 OKR & 人员分工 | `LpbTdfU95oDnnTx5LmAc7Q1WnVg` | 算法组4个OKR完整Owner分配 |
| 闭环仿真落地（**组内日报文档** ⭐ 用户 6/22 指定：组内日报就看这个，含本周·周目标列） | `SBUYwm8Lri9aJ6kmexFcBAuGnlh` (wiki) | Q2作战表 / 组内日报 |
| H2人力规划 | `EHXpwax93ig3PEkCDcic8d6xn2c` | 组织效能审视、职级表 |

### 技术方案文档

| 文档 | Token |
|------|-------|
| 场景编辑方案概要设计 | `LK8Qwjcx0ia1dakCPiqcMYsAnwg` |
| AVM链路-鱼眼 | `WDfGwUa0IiRWf5kVnflcokrHnth` |
| 极速模式交付文档 | `X6a2wQUVpimODBkVidxcnHOvnuc` |
| SIL&HIL fixer性能优化实验 | `STxrwJBKGi1QPOk1OXrcENZInG6` |
| 闭环复现分析Agent开发计划 | `K9eIw7MGBiXig6kJbsdcCIX5nVv` |
| 复现Agent阶段性验证报告 | `XF97w6WB2ihOtXkIvacchIe8nmc` |
| World Model方案调研 | `TjBXwI1QiiADy0kDSMHcmD6qn2g` |
| HIL链路计划及进展汇总 | `ACCFwgyckivIrjkUuiZcHv2ynBe` |
| 开闭环车型验证方案 | `G6I4w06nPiJ1g3kVlJ7cgnZinPg` |

### 会议纪要体系

| 系列 | 主文档Token | 历史篇数 | 频率 |
|------|------------|:--:|------|
| GIC双周会 | `Civld2s6coisyQx63kpcGWDOnOc` (6/5) | 2 | 双周五（每两周）|
| 仿真核心日会 | `NmbKdb20VoK0JoxuVeRcLkadnFc` (6/10) | 30 ✅全读 | 每日09:00 |
| 部门日会 | — | — | 每周二/四 |
| 算法组周会 | `DoPWdgr61oTCnAxkgHzci8Z0nBf` (6/5) | 7 ✅全读 | 每周五16:00 |
| 算法组每日例会 | `Wskqd8ufNouGkExrlcmceGVAnJe` (6/10) | 28 ✅全读 | 每日17:30 |
| 个人文件夹 | `EBvifvxhTlX77gdCcUNcHMman7d` ("入职启动") | — | — |

### 会议 → 日报文档映射（重要！）

| 会议 | 时间 | 对应日报文档 | Token | 李坤汇报节点 |
|------|------|------------|-------|-------------|
| **仿真核心日会** | 每天 09:00 | 仿真组日报（场景集/SIL/HIL进展汇总） | `Wu6ywIOM6iEucDkmx3hcEgLHnmg` | **每周三 09:00** 李坤汇报本组进展 |
| **算法部门日会** | 每天 17:30 | Q2作战表/闭环仿真落地 | `SBUYwm8Lri9aJ6kmexFcBAuGnlh` | — |
| **GIC双周会** | 双周五 11:00（本期提前至周三） | GIC双周会纪要 | `Civld2s6coisyQx63kpcGWDOnOc` | **每两周**李坤汇报本组板块 |

> **读日报的优先级**：每次采集信息前，先读 `Wu6ywIOM6iEucDkmx3hcEgLHnmg`（核心日会配套日报）作为当前状态基准，再读纪要逐字稿补细节。

### GIC关键人物

- **刘先明 (Xianming Liu)**：GIC负责人，主持GIC双周会
- **孙梦**：GIC HR/Staff
- **高炳涛**：P9，仿真核心日会常驻，算法组周会参与

### 外部关键协作角色

- **杜思聪**：生产链路技术Owner（O3技术Owner），base上海？
- **云荟**：**数据生产组**成员，极速模式试用反馈；汇报文档中应写"数据生产组"，不写个人名
- **戚芸**：扬州质检团队，Agent结果review
- **刘开拓**：生产组，RC路线采集协调

[[team-scope]] [[department-context]] [[likun-role]]
