# **训练仿真评测闭环pipeline初步****流程****：**

> ⚠️ **实现现状更新**：当前实现**不含 Planner/LLM**。流水线固定为
> 编包 → 提交仿真 → 等待 → 评测（跑 simworld `tools/` 出渲染耗时 CSV + FM 轨迹评测图片）
> → 报告（把 CSV + 图片直接发飞书）。下文「Planner Agent 使用 LLM」为早期构想，最新以 README/代码为准。

1. 首先用户准备好当前待测试的模型权重路径和全局开关配置（内嵌于代码）
    
2. 选取相应的待测试模型代码分支在本地5080台架上编包输出Binary（测试分支必须包含模型评测功能），编包完成获取Binary id
    
3. 根据binary id + ckpt path + 全局开关配置在网页端进行相应设置并提交闭环仿真云端任务
    
4. 待任务跑完拉取模型评测的输出进行整合并输出报告自动提交到飞书
    

```Bash
                    ┌──────────────────┐
                    │      User        │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │  Planner Agent   │
                    │  (任务规划层)     │
                    └────────┬─────────┘
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
          ▼                  ▼                  ▼

 ┌────────────────┐ ┌────────────────┐ ┌────────────────┐
 │ Build Agent    │ │ SimulationAgent│ │ Report Agent   │
 │ 编包Agent      │ │ 仿真Agent       │ │ 报告Agent      │
 └────────────────┘ └────────────────┘ └────────────────┘

          │                  │                  │
          └──────────────────┼──────────────────┘
                             ▼

                    ┌──────────────────┐
                    │ Workflow Engine  │
                    │ 状态机/调度器     │
                    └──────────────────┘
```

# 拆分成多个专用Agent

1. ## Planner Agent: 真正使用LLM和用户交互的Agent
    

例如用户输入：

```Bash
测试：
branch:
dev_difix_zf_0612

ckpt_path:
/mnt/xxx.ckpt

开关：
use_difix=true
use_nvfixer=false
```

Planner会生成执行计划：

```Markdown
1. checkout branch
2. build binary
3. get binary id
4. submit simulation
5. wait completion
6. collect metrics
7. generate report
8. send feishu
```

然后交给Workflow执行。

  

2. ## 仿真Agent
    

目前5080台架使用的是pipeline工具进行多仓管理，当前需求只需要在simulation和simworld仓库下进行分支切换

```SQL
cd /sandbox/simulation/simulation && ./scripts/upload_binary.py --cn --foundation_model --enable_simworld -v XP5 -f --build_region sh -n  zhouf4_nvfixer_xxxxx
```

  

3. ## Workflow Engine设计（核心）
    

不要让Agent自己记忆流程状态，必须有Workflow

推荐简单版如LangGraph / CrewAI Flow，工业版**Temporal** / Airflow / Argo Workflow，例如使用Temporal进行长流程管理

  

4. ## 状态机设计
    

每个实验必须有状态：

```Bash
CREATED

BUILDING

BUILD_SUCCESS

BUILD_FAILED

SUBMITTED

RUNNING

SIMULATION_FAILED

EVALUATING

REPORTING

COMPLETED
```

存数据库：

```SQL
experiment
```

```SQL
id
branch
ckpt
binary_id
task_id
status
report_url
```

  

5. ## 失败恢复
    

例如编包成功 -> 仿真提交成功 -> Agent挂了，第二天恢复时不能重新编包，而应该从DB读取状态 -> Running -> 继续等待结果，因此所有步骤都要保证可恢复 & 可重试 & 幂等

  

  

  

  

  

