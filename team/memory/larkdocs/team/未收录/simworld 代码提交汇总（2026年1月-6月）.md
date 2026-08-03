# simworld 代码提交汇总（2026年1月-6月）

## 一、项目概览

| 项目 | 说明 |
|-|-|
| 仓库 | simworld |
| 主分支 | dev |
| 项目简介 | 三维重建任务相关开发，包括模型训练、渲染、数据处理和生产部署 |
| dev分支总提交数 | 44 |
| 近6个月提交数 | 39 |
| 远程分支总数 | 3294 |

### 目录结构

| 目录 | 说明 |
|-|-|
| `pipeline/fuyao/` | Fuyao 训练/预处理提交 |
| `pipeline/ucp/` | IPS/UCP 场景生产 |
| `xpeng_data_process/` | 数据预处理 |
| `omnire_joint_trainning/` | Reconic 训练与渲染（render_sim 等） |
| `models/` | 各模型目录（difix、g3r、street_gaussians、inspatio-world、nvfixer、CLIP-IQA 等） |
| `agents/` | 飞书 Agent 服务 |
| `skills/` | 团队 Skills（飞书 lark-\* 系列、3dgs-\* 系列等） |
| `tools/` | 调试与评测工具 |
| `libs/xpeng_raster/` | 光栅化库 |
| `sim_interface/` | 闭环仿真接口 |

## 二、提交统计

### 贡献者排名

| 排名 | 贡献者 | 提交数 | 主要方向 |
|-|-|-|-|
| 1 | yangxh7 | 13 | 渲染Pipeline、Inspatio-World、NVFixer、海外功能 |
| 2 | peijh | 8 | 3DGS多车闭环、场景编辑自动化、UCP Subrun |
| 3 | wangyd13 | 7 | CLIP-IQA评测发布、XP5系列车辆遮罩、Dockerfile |
| 4 | Zhou Weixu (zhouwx2) | 5 | CloudSim参数简化、异常处理框架、Loc Pose上传 |
| 5 | zhouf4 | 4 | 3DGS自动数据预处理与训练、NVFixer Reference Pipeline |
| 6 | quxy | 1 | 3DGS模型加载加速与Light DDS上传 |
| 7 | jinxr | 1 | Inspatio-World模型初始引入 |

### 时间分布与重要说明

<callout emoji="🎁">
dev 分支于 2026年6月4日 执行了 `chore: init clean architecture and completely drop legacy history`，重新初始化了代码库并丢弃了所有历史记录。因此全部 39 条提交集中在 2026年6月4日 ～ 7月1日 之间，1月～5月期间 dev 分支无提交记录。
</callout>

### 提交方式说明

所有 39 条提交均为**直接推送到 dev 分支**，无 merge commit。这意味着团队成员主要通过直接推送或 rebase 后推送的方式协作，而非通过 merge request/PR 合入。

## 三、详细提交记录（按贡献者分组）

### 1. yangxh7（13 commits）

#### 项目初始化与架构搭建

| 日期 | Commit Message | 改动概要 |
|-|-|-|
| 2026-06-04 | `chore: init clean architecture and completely drop legacy history` | 项目架构初始化，建立 BUILD/WORKSPACE/agents/skills 等基础结构（+538） |

#### 渲染 Pipeline 与 Smoke Test

| 日期 | Commit Message | 改动概要 |
|-|-|-|
| 2026-06-05 | `[render] pass 3dgs render and preprocess smoke test` | 3DGS渲染与预处理smoke test通过，新增deploy_render.bash/render.sh等脚本（+538/-72） |
| 2026-06-05 | `fix missing dep in camopt` | 修复camopt依赖缺失，新增Python_VO子模块（lidar2cam标定优化） |
| 2026-06-24 | `update deploy scripts` | 更新部署脚本，新增render_fastmode.py（+72/-24） |

#### NVFixer 部署与推理

| 日期 | Commit Message | 改动概要 |
|-|-|-|
| 2026-06-08 | `[nvfixer] deploy and infer scripts` | NVFixer部署与推理脚本，新增deploy/run_infer.sh等（+374/-17） |

#### Inspatio-World 模型开发

| 日期 | Commit Message | 改动概要 |
|-|-|-|
| 2026-06-09 | `Jxr dev v2 inspatio` | inspatio-world开发v2，更新配置和推理代码（+30/-30） |
| 2026-06-23 | `[models] inspatio wm train and infer in multiple modes` | inspatio世界模型多模式训练与推理，大幅重构（+3930/-1299） |
| 2026-06-23 | `update inspatio-world infer` | 更新inspatio-world推理，新增.fuyaoignore（+130/-23） |

#### 海外功能与 UCP

| 日期 | Commit Message | 改动概要 |
|-|-|-|
| 2026-06-09 | `ucp overseas feature` | UCP海外功能，更新README和calib_utils（+21/-5） |
| 2026-06-09 | `fix overseas debug code` | 修复海外调试代码（-3） |
| 2026-06-09 | `[preprocess] fetch avm camera` | 预处理新增AVM相机获取（+81/-11） |

#### 其他

| 日期 | Commit Message | 改动概要 |
|-|-|-|
| 2026-06-23 | `[agents] R&D agent` | 飞书Agent研发，重组agents目录结构 |
| 2026-06-24 | `fix car mask mr bug` | 修复car mask MR bug（-20） |

---

### 2. peijh（8 commits）

#### 3DGS 多车闭环与 CloudSim 触发

| 日期 | Commit Message | 改动概要 |
|-|-|-|
| 2026-06-10 | `[3dgs][feat]multi vehicle closeloop render` | 多车闭环渲染，新增simulator_base功能（+69） |
| 2026-06-22 | `[3dgs][feat]multi vehicle cloudsim trigger` | 多车CloudSim触发，重构create_multi_vehicle_scenario（+268/-255） |
| 2026-06-23 | `[3dgs][feat]adapt cloudsim close loop multi vechile` | 适配CloudSim闭环多车场景（+39/-3） |
| 2026-06-30 | `[3dgs][feat]scenario edit automatic pipeline dev` | 场景编辑自动化pipeline，新增agent_service/trajectory_strategy/cloudsim_api等（+3084/-42，27文件） |

#### UCP Subrun 与触发时间适配

| 日期 | Commit Message | 改动概要 |
|-|-|-|
| 2026-06-10 | `[3dgs][feat]update scenario edit code` | 更新场景编辑代码，新增batch_scenario_generate/oss_file_uploader等（+1048/-39，18文件） |
| 2026-06-12 | `User/pjh/trigger time adapt v2` | 触发时间适配v2，更新ips_utils/ucp_xpeng_vision（+140/-48） |
| 2026-06-15 | `[3dgs][feat]subrun ucp dev` | UCP subrun开发，重命名ips_subrun_2models→ucp_subrun_2models（+169/-126） |

#### 其他

| 日期 | Commit Message | 改动概要 |
|-|-|-|
| 2026-06-08 | `smoke test, fix ucp/ips` | smoke test修复UCP/IPS（+3） |

---

### 3. wangyd13（7 commits）

#### CLIP-IQA 评测体系与发布

| 日期 | Commit Message | 改动概要 |
|-|-|-|
| 2026-06-08 | `release clip iqa` | 发布CLIP-IQA，新增完整CLIP-IQA模型代码含mmedit框架（大量文件） |
| 2026-06-09 | `clip-iqa-result-evaluation` | CLIP-IQA结果评测，新增result_evaluation模块（+2713，6文件） |

#### XP5 系列车辆遮罩（连续多次提交，合并展示）

| 日期 | Commit Message | 改动概要 |
|-|-|-|
| 2026-06-09 | `add XP5_281 mask` | 新增XP5_281车辆遮罩（15文件） |
| 2026-06-22 | `add XP5_304 mask` | 新增XP5_304车辆遮罩（18文件） |
| 2026-06-24 | `add XP5_245 mask` | 新增XP5_245车辆遮罩（18文件） |

#### Dockerfile 与部署

| 日期 | Commit Message | 改动概要 |
|-|-|-|
| 2026-07-01 | `dockerfile-change` | Dockerfile变更，更新README和latest_a100/latest_ppu Dockerfile（+177/-89） |

---

### 4. Zhou Weixu / zhouwx2（5 commits）

#### CloudSim 参数简化与异常处理框架

| 日期 | Commit Message | 改动概要 |
|-|-|-|
| 2026-06-02 | `fast mode support adapted_trigger_timestamp` | 快速模式支持adapted_trigger_timestamp（+7） |
| 2026-06-24 | `wraper_all_the_exception` | 统一异常处理wrapper，新增error_definitions.yaml和pipeline_error_codes.py（+236/-12） |
| 2026-06-26 | `simple_the_para_for_run_cloudsim` | 简化CloudSim运行参数，新增simulator_helpers.py（+27） |
| 2026-06-30 | `rename carmask strategy to keep pkg path less than 100` | 重命名carmask策略以缩短包路径并fail-fast（+17/-10） |
| 2026-06-30 | `upload loc pose and anchor to oss` | 上传loc pose和anchor到OSS（+25/-2） |

---

### 5. zhouf4（4 commits）

#### 3DGS 自动数据预处理与训练

| 日期 | Commit Message | 改动概要 |
|-|-|-|
| 2026-06-08 | `[3dgs] add automatic data preprocessing & 3dgs training` | 3DGS自动数据预处理与训练，新增download_data_and_train.py（+430/-25） |
| 2026-06-12 | `[preprocess] add raise_on_smooth_pose_error control` | 预处理新增raise_on_smooth_pose_error控制（+57/-12） |

#### NVFixer Reference Pipeline

| 日期 | Commit Message | 改动概要 |
|-|-|-|
| 2026-07-01 | `[model] add new nvfixer with reference pipeline & ucp subrun ref enc pipeline` | 新增NVFixer reference pipeline和UCP subrun ref enc pipeline（30文件，+6843/-122） |

#### 其他

| 日期 | Commit Message | 改动概要 |
|-|-|-|
| 2026-06-22 | `fix_undistort_module_still_stuck` | 修复undistort模块卡死问题（+151/-112） |

---

### 6. quxy（1 commit）

| 日期 | Commit Message | 改动概要 |
|-|-|-|
| 2026-06-16 | `Speed up loading 3dgs model and upload light dds` | 加速3DGS模型加载并上传light DDS，新增extract_results_cache.py和merge_slice_hil_dds_lib.py（+719/-51） |

---

### 7. jinxr（1 commit）

| 日期 | Commit Message | 改动概要 |
|-|-|-|
| 2026-06-09 | `[inspatio] add models/inspatio-world` | 新增inspatio-world模型，包含完整wan模型框架、分布式训练、因果推理pipeline（大量文件） |

## 四、发版情况（标签）

近6个月共产生 **60+ 个发版标签**，均通过 CI/CD 流水线自动创建（`Official Release for version: ...`）。以下按版本系列分类列出：

### sim3dgs 版本系列

| 标签 | 创建时间 | 对应提交 |
|-|-|-|
| sim3dgs_v500 | 2026-06-16 | Speed up loading 3dgs model and upload light dds |
| sim3dgs_v502 | 2026-06-22 | add XP5_304 mask |
| sim3dgs_v503 | 2026-06-24 | fix car mask mr bug |
| sim3dgs_v510 | 2026-07-03 | add xp5-256 mask |

### v3.3.x 系列（d02/d03/g02 esvr）

| 标签 | 创建时间 |
|-|-|
| v3.3.6-d01a-xos620-bringupxp5-ultra | 2026-06-23 |
| v3.3.6-d02esvr-xos620-xp5v-ultra | 2026-06-23 |
| v3.3.6-d03esvr-xos620-xp5v-ultra | 2026-06-23 |
| v3.3.6-g02esvr-xos620-xp5v-ultra | 2026-06-23 |
| v3.3.7-d02esvr-xos620-xp5v-ultra | 2026-06-25 |
| v3.3.7-d03esvr-xos620-xp5v-ultra | 2026-06-25 |
| v3.3.7-g02esvr-xos620-xp5v-ultra | 2026-06-25 |
| v3.3.8-d02esvr-xos620-xp5v-ultra | 2026-07-03 |
| v3.3.8-d03esvr-xos620-xp5v-ultra | 2026-07-03 |
| v3.3.8-g02esvr-xos620-xp5v-ultra | 2026-07-03 |

### vA.1.x 系列

| 标签 | 创建时间 |
|-|-|
| vA.1.6-v01-xos620-vwxp5-ultra | 2026-06-29 |
| vA.1.6-v01a-xos620-vwxp5-ultra | 2026-06-29 |
| vA.1.8-d03es-xos620-bringupxp5-ultra | 2026-06-23 |
| vA.1.9-d03es-xos620-bringupxp5-ultra | 2026-06-30 |
| vA.1.A-d03es-xos620-bringupxp5-ultra | 2026-07-04 |
| vA.1.B-\* (7个子版本) | 2026-06-24 |
| vA.1.C-\* (7个子版本) | 2026-06-25 |

### vA.2.x 系列

| 标签 | 创建时间 |
|-|-|
| vA.2.1-e29-xos630-xp5-ultra | 2026-06-22 |
| vA.2.1-e38be-xos630-xp5-ultra | 2026-06-22 |
| vA.2.1-f01es-xos630-xp5-ultra | 2026-06-22 |
| vA.2.1-f01xccp-xos630-xp5-ultra | 2026-06-22 |
| vA.2.1-f30bes-xos630-xp5-ultra | 2026-06-22 |
| vA.2.1-f57aes-xos630-xp5-ultra | 2026-06-22 |
| vA.2.1-h93aes-xos630-xp5-ultra | 2026-06-22 |
| vA.2.2-e29-xos630-xp5-ultra | 2026-07-01 |
| vA.2.2-e38be-xos630-xp5-ultra | 2026-07-01 |
| vA.2.2-f01es-xos630-xp5-ultra | 2026-07-01 |
| vA.2.2-f01xccp-xos630-xp5-ultra | 2026-07-01 |
| vA.2.2-f30bes-xos630-xp5-ultra | 2026-07-01 |
| vA.2.2-f57aes-xos630-xp5-ultra | 2026-07-01 |
| vA.2.2-g01-xos630-xp5-ultrasuper | 2026-06-29 |

### 其他版本

| 标签 | 创建时间 |
|-|-|
| v0.0.1-d02rte-xos620-xp5l4-ultrasuper | 2026-06-22 |
| v0.0.2-d02rte-xos620-xp5l4-ultrasuper | 2026-07-01 |
| v1.3.0-g01-xos620-xp5l4-ultrasuper | 2026-06-20 |
| v1.3.1-g01-xos620-xp5l4-ultrasuper | 2026-06-26 |
| v1.4.0-g01-xos620-xp5l4-ultrasuper | 2026-07-03 |
| v2.8.1-d02es-xos620-bringupxp5-ultra | 2026-06-22 |
| v2.8.2-d02es-xos620-bringupxp5-ultra | 2026-06-30 |
| v2.8.3-d02es-xos620-bringupxp5-ultra | 2026-07-02 |
| v5.1.0-d05es-xos620-xp5-ultra | 2026-06-16 |
| v5.1.9-g02-xos620-bringupxp5-ultra | 2026-06-16 |
| v5.1.B-g02-xos620-bringupxp5-ultra | 2026-07-04 |

<callout emoji="💡">
发版标签命名规则：`v{版本号}-{平台代号}-xos{系统版本}-{芯片平台}-ultra/super`。同一版本号会针对不同平台（d02/d03/g02/e29/e38be/f01es/f30bes/f57aes/h93aes 等）分别发版。CI/CD 自动创建标签时提交信息为 `Official Release for version: ...`。
</callout>

## 五、分支合入主分支（dev）情况

| 统计项 | 数量 |
|-|-|
| 远程分支总数 | 3294 |
| 已合入 dev 的分支 | 249 |
| 未合入 dev 的分支 | 3210 |

### 合入方式分析

- dev 分支所有 39 条近6个月提交均为**直接推送**，无 merge commit
- 团队协作模式为：在个人/功能分支上开发 → rebase 到 dev 最新 → 直接推送到 dev
- 未合入 dev 的 3210 个分支中，大部分为历史发版分支（如 `origin/v3.3.6-*`）、个人开发分支（如 `origin/USER/pjh/*`）和测试分支（如 `origin/407_test*`）

### 主要活跃功能分支

以下分支在近6个月有独立提交但可能尚未合入 dev：

| 分支 | 负责人 | 主要内容 |
|-|-|-|
| `origin/USER/pjh/multi_vehicle_closeloop` | peijh | 多车闭环开发 |
| `origin/USER/pjh/scenario_edit_automatic_pipeline` | peijh | 场景编辑自动化 |
| `origin/USER/pjh/subrun_ucp_error_test` | peijh | UCP subrun错误测试 |
| `origin/USER/WANGYD/clip-iqa-evaluate` | wangyd13 | CLIP-IQA评测 |
| `origin/USER/WANGYD/dockerfile-remake` | wangyd13 | Dockerfile重构 |
| `origin/zhouwx2/simple_the_para_for_run_cloudsim` | Zhou Weixu | CloudSim参数简化 |
| `origin/zhouwx2/3dgs_prod_agent_dev` | Zhou Weixu | 3DGS生产Agent开发 |

## 六、关键技术进展总结

<callout emoji="✅">
**1. 项目架构重建（6月4日）**完成了项目架构的全面重建，建立了清晰的目录结构（pipeline/models/agents/skills/tools等）和构建系统（BUILD/WORKSPACE），完全丢弃了历史遗留代码。
**2. 3DGS 渲染 Pipeline 完善**完成了3DGS渲染与预处理的smoke test（yangxh7），新增了多车闭环渲染（peijh）、CloudSim多车触发（peijh）、场景编辑自动化pipeline（peijh），以及3DGS模型加载加速（quxy）。
**3. Inspatio-World 世界模型**jinxr 初始引入 inspatio-world 模型（含完整wan模型框架、分布式训练、因果推理pipeline），yangxh7 后续完成了多模式训练与推理、部署脚本等。
**4. NVFixer 模型部署**zhouf4 新增了 NVFixer reference pipeline 和 UCP subrun ref enc pipeline（+6843行），yangxh7 完成了部署与推理脚本。
**5. CLIP-IQA 评测体系**wangyd13 发布了完整的 CLIP-IQA 评测工具（含mmedit框架），建立了结果评测流程（result_evaluation模块，+2713行）。
**6. 多车场景编辑与生成**peijh 实现了场景编辑自动化pipeline，新增 agent_service/trajectory_strategy/cloudsim_api/dds_parser 等模块（+3084行），支持多车场景自动生成。
**7. XP5 车辆遮罩持续迭代**wangyd13 持续新增 XP5 系列车辆遮罩（281/304/245等），覆盖更多车型和相机视角。
**8. 异常处理框架**Zhou Weixu 建立了统一的异常处理框架，包含 error_definitions.yaml 错误定义和 pipeline_error_codes.py 错误码体系（+236行）。
</callout>

## 七、提交时间线（按日期正序）

| 日期 | 贡献者 | 提交内容 |
|-|-|-|
| 06-02 | Zhou Weixu | fast mode support adapted_trigger_timestamp |
| 06-04 | yangxh7 | init clean architecture and completely drop legacy history |
| 06-05 | yangxh7 | [render] pass 3dgs render and preprocess smoke test |
| 06-05 | yangxh7 | fix missing dep in camopt |
| 06-08 | yangxh7 | [nvfixer] deploy and infer scripts |
| 06-08 | peijh | smoke test, fix ucp/ips |
| 06-08 | wangyd13 | release clip iqa |
| 06-09 | jinxr | [inspatio] add models/inspatio-world |
| 06-09 | yangxh7 | [preprocess] fetch avm camera |
| 06-09 | yangxh7 | Jxr dev v2 inspatio |
| 06-09 | yangxh7 | ucp overseas feature |
| 06-09 | yangxh7 | fix overseas debug code |
| 06-09 | wangyd13 | add XP5_281 mask |
| 06-09 | wangyd13 | clip-iqa-result-evaluation |
| 06-10 | peijh | [3dgs][feat]update scenario edit code |
| 06-10 | peijh | [3dgs][feat]multi vehicle closeloop render |
| 06-12 | peijh | User/pjh/trigger time adapt v2 |
| 06-12 | zhouf4 | [preprocess] add raise_on_smooth_pose_error control |
| 06-15 | peijh | [3dgs][feat]subrun ucp dev |
| 06-16 | quxy | Speed up loading 3dgs model and upload light dds |
| 06-22 | peijh | [3dgs][feat]multi vehicle cloudsim trigger |
| 06-22 | wangyd13 | add XP5_304 mask |
| 06-22 | zhouf4 | fix_undistort_module_still_stuck |
| 06-23 | yangxh7 | [models] inspatio wm train and infer in multiple modes |
| 06-23 | yangxh7 | [agents] R&D agent |
| 06-23 | yangxh7 | update inspatio-world infer |
| 06-23 | peijh | [3dgs][feat]adapt cloudsim close loop multi vechile |
| 06-24 | yangxh7 | update deploy scripts |
| 06-24 | yangxh7 | fix car mask mr bug |
| 06-24 | Zhou Weixu | wraper_all_the_exception |
| 06-24 | wangyd13 | add XP5_245 mask |
| 06-26 | Zhou Weixu | simple_the_para_for_run_cloudsim |
| 06-30 | peijh | [3dgs][feat]scenario edit automatic pipeline dev |
| 06-30 | Zhou Weixu | rename carmask strategy to keep pkg path less than 100 |
| 06-30 | Zhou Weixu | upload loc pose and anchor to oss |
| 07-01 | wangyd13 | dockerfile-change |
| 07-01 | zhouf4 | [model] add new nvfixer with reference pipeline |
|  |  |  |

## 八、全分支活动汇总（所有分支 × 所有人）

以上章节仅统计了 **dev 主分支** 的提交。本节扩展到 **全部分支**，覆盖所有贡献者在近6个月（2026年1月-6月）的活动。

### 全分支贡献者总览

| 排名 | 贡献者 | 全分支提交数 | dev提交数 | 活跃时间范围 | 主要方向 |
|-|-|-|-|-|-|
| 1 | yangxh7 | 1348 | 13 | 01-07 \~ 07-01 | 仿真渲染、Difix、IPS Pipeline、Inspatio-World |
| 2 | peijh | 828 | 8 | 01-05 \~ 07-01 | 3DGS多车闭环、CloudSim触发、场景编辑自动化 |
| 3 | wangyd13 | 733 | 7 | 01-05 \~ 07-01 | CLIP-IQA评测发布、XP5遮罩、Kafka消息、H265转PNG |
| 4 | dusc | 703 | 0 | 01-09 \~ 05-15 | 渲染管线、scube预处理、subrun数据生产 |
| 5 | zhouf4 | 425 | 4 | 01-04 \~ 07-01 | NVFixer、Difix训练、HIL ref生产、3DGS自动预处理 |
| 6 | xuzh2 | 418 | 0 | 01-29 \~ 04-02 | 批量渲染、xpeng_raster、HIL pipeline、3DGS仿真 |
| 7 | root（多人共用） | 237 | 0 | 01-04 \~ 06-02 | 仿真调试、物体轨迹优化、快速模式开发 |
| 8 | zhuxf1 | 125 | 0 | 02-26 \~ 06-26 | 道闸栏杆SAM3D、预处理bug修复、HIL渲染 |
| 9 | zhangzy30 | 122 | 0 | 01-04 \~ 02-10 | 道闸栏杆SAM3D、批量处理、训练参数调优 |
| 10 | zhangzy27 | 122 | 0 | 01-17 \~ 03-24 | 道闸栏杆SAM3D、栏杆位姿插值、刚体约束 |
| 11 | lvwj1 | 96 | 0 | 02-06 \~ 06-11 | 道闸栏杆SAM3D、oml数据适配、xpeng_raster集成 |
| 12 | quxy | 100 | 0 | 01-30 \~ 06-23 | 渲染加速、道闸栏杆SAM3D、坐标系统变换 |
| 13 | Zhou Weixu (zhouwx2) | 47 | 5 | 02-04 \~ 07-01 | 渲染优化、静态剪枝、sky下采样、资源监控 |
| 14 | ai-coding | 46 | 0 | 03-28 \~ 07-01 | AI自动编码、参考设计文档、场景泛化Agent |
| 15 | lvy10 | 43 | 0 | 01-04 \~ 02-05 | Difix推理基准、TRT profiling、延迟优化 |
| 16 | Codex Remote | 23 | 0 | 05-14 \~ 05-17 | DiFiX smoke workflow、TRT延迟实验、推理benchmarking |
| 17 | wangyl11 | 22 | 0 | 01-05 \~ 02-10 | ego pose、worldmodel case、scenario update |
| 18 | fansz | 15 | 0 | 06-16 \~ 07-01 | train-sim-eval agent、场景泛化、视频分析 |
| 19 | jinxr | 6 | 0 | 06-05 \~ 06-30 | inspatio-world模型、wan_14b |
| 20 | gujx3 | 6 | 0 | 06-24 \~ 06-26 | 天气风格编辑、fuyao改动 |
| 21 | fengmh | 5 | 0 | 02-24 \~ 03-04 | SAM3 prompt设计、预处理训练 |
| 22 | wangh | 4 | 0 | 01-07 \~ 01-22 | localpose训练、渲染调试 |
| 23 | zhengln | 3 | 0 | 03-10 \~ 03-13 | profiler_report、多相机版本 |
| 24 | xiaobp | 2 | 0 | 02-06 | 右转修复、rebase |
| 25 | Your Name | 2 | 0 | 01-22 \~ 01-26 | xpeng raster 5 cams同分辨率 |
| 26 | zhangdk1 | 1 | 0 | 01-07 | local pose train z |
| 27 | Xihu Lai | 1 | 0 | 03-20 | prune_all_gaussians_for_render |
| 28 | adc_pdd_ciops_gocicd | 9 | 0 | 02-11 \~ 06-15 | CI/CD自动创建branch.yaml |

<callout emoji="💡">
**关键发现**：dev 主分支仅有 39 条提交（7人贡献），但全分支共有 **5240+ 条提交**（28+ 位贡献者）。大量开发工作发生在个人功能分支上，通过发版分支（如 `dev_g01_xos630_*`）直接发版，未必经过 dev 分支合并。这说明团队的发版流程与 dev 主分支是相对独立的。
</callout>

### 各贡献者全分支活动详情

#### 1. yangxh7（1348 commits｜dev: 13）

**活跃时间**：2026-01-07 \~ 2026-07-01

**主要工作方向**：

| 方向 | 时间段 | 代表性提交 |
|-|-|-|
| 仿真渲染 | 1月-2月 | `[sim] mock sim render`、`[sim] fix z value in simulation`、`[sim] use difix with lora in sim` |
| Difix训练与优化 | 2月-3月 | `[difix] update difix train & optimize difix speed in sim`、`[difix] add mask in difix train` |
| IPS Pipeline | 2月-4月 | `[ips] ips pipeline for preparing difix train data`、`[sim] set default fixer cfg` |
| xpeng_raster | 3月 | `[raster] init xpeng_raster`、`[sim] download images origin` |
| 项目架构重建 | 6月4日 | `chore: init clean architecture and completely drop legacy history` |
| Inspatio-World | 6月 | `[models] inspatio wm train and infer in multiple modes` |
| NVFixer部署 | 6月 | `[nvfixer] deploy and infer scripts` |

#### 2. peijh（828 commits｜dev: 8）

**活跃时间**：2026-01-05 \~ 2026-07-01

**主要工作方向**：

| 方向 | 时间段 | 代表性提交 |
|-|-|-|
| CloudSim触发 | 1月 | `[3dgs][feat]send trigger time to cloudsim` |
| Kafka消息 | 1月-4月 | `[3dgs][feat]evaluate send kafka`、`send kafka`、`update kafka callback msg` |
| 渲染策略 | 2月-3月 | `[3dgs][feat]refactor render strategy`、`[3dgs][feat]render strategy & origin png render` |
| H265转PNG | 4月 | `[3dgs][feat]camera video h265 convert to image`、`[3dgs][feat]h265 convert to png on ips` |
| 多车闭环 | 6月 | `[3dgs][feat]multi vehicle closeloop render`、`[3dgs][feat]multi vehicle cloudsim trigger` |
| 场景编辑自动化 | 6月 | `[3dgs][feat]scenario edit automatic pipeline dev` |

#### 3. wangyd13（733 commits｜dev: 7）

**活跃时间**：2026-01-05 \~ 2026-07-01

**主要工作方向**：

| 方向 | 时间段 | 代表性提交 |
|-|-|-|
| 地面渲染调优 | 1月 | `change opacity lr`、`ground_change`、`ground*0.5`、`pvg_ground` |
| 2DGS渲染 | 1月 | `2dgs&render_bug`、`render_gsplat` |
| Fuyao部署 | 1月 | `fuyao_deploy setup`、`fuyao-job`、`wandb_dockerfile` |
| CLIP-IQA评测 | 6月 | `release clip iqa`、`clip-iqa-result-evaluation` |
| XP5遮罩 | 6月 | `add XP5_281 mask`、`add XP5_304 mask`、`add XP5_245 mask` |
| Kafka与H265 | 4月 | `camera video h265 convert to image`、`send kafka` |

#### 4. dusc（703 commits｜dev: 0）

<callout emoji="🎁">
**注意**：dusc（邓宇胜）有 703 条提交，但 **0 条在 dev 分支**。所有工作在其他分支完成。
</callout>

**活跃时间**：2026-01-09 \~ 2026-05-15

| 方向 | 时间段 | 代表性提交 |
|-|-|-|
| subrun数据生产 | 3月-4月 | `[preprocess] add subrun data process`、`[preprocess] use extra info for streaming` |
| scube预处理 | 4月 | `[preprocess] add scube preprocess` |
| 渲染管线 | 4月-5月 | `[preprocess] optimize subrun data production`、`[3dgs] add rigid nodes render`、`[render] add trajectory slerp` |
| IPS Pipeline | 4月 | `[ips pipeline] modify check metrics & add case info` |

#### 5. zhouf4（425 commits｜dev: 4）

**活跃时间**：2026-01-04 \~ 2026-07-01

| 方向 | 时间段 | 代表性提交 |
|-|-|-|
| NVFixer开发 | 6月-7月 | `[model] add new nvfixer with reference pipeline`、`[nvfixer] new nvfixer ref version`、`nvfixer ppu init use cache` |
| HIL ref生产 | 6月 | `HIL ref production pipeline`、`hil ppu ref`、`add hil nvfixer ref` |
| 3DGS自动训练 | 6月 | `[3dgs] add automatic data preprocessing & 3dgs training`、`fix 3dgs train difix diffuser` |
| 预处理控制 | 6月 | `[preprocess] add raise_on_smooth_pose_error control` |

#### 6. xuzh2（418 commits｜dev: 0）

<callout emoji="🎁">
**注意**：xuzh2 有 418 条提交，但 **0 条在 dev 分支**。
</callout>

**活跃时间**：2026-01-29 \~ 2026-04-02

| 方向 | 时间段 | 代表性提交 |
|-|-|-|
| 批量渲染 | 3月-4月 | `[sim] sil batch render`、`batch render xpeng raster` |
| HIL pipeline | 3月-4月 | `add hil simulation in simworld`、`[hil] init hil pipeline and 3dgs`、`hil render orchestrator` |
| 渲染优化 | 3月 | `modify far plane and add radius clip`、`add xpeng_raster`、`remove seg sort` |
| SmartAgent | 3月 | `[Sim] fix smart agent bug`、`fix sm bug` |

#### 7. root（237 commits｜多人共用｜dev: 0）

**活跃时间**：2026-01-04 \~ 2026-06-02

| 方向 | 时间段 | 代表性提交 |
|-|-|-|
| 物体轨迹优化 | 5月 | `optimize y center`、`use extimate y`、`modify func` |
| 快速模式 | 5月 | `modify for fast mode run dev branch`、`temp modify sim` |
| 渲染调试 | 5月 | `add debug code`、`add logs for ips_xpeng_vision.py`、`add simdiag resource monitoring logs` |
| 渲染优化 | 3月 | `add static_prune and sh0_collect_cache`、`add sky_downsample`、`sky affine use float16` |

#### 8. zhuxf1（125 commits｜dev: 0）

**活跃时间**：2026-02-26 \~ 2026-06-26

| 方向 | 时间段 | 代表性提交 |
|-|-|-|
| 道闸栏杆SAM3D | 2月-3月 | `init for add sam3 for gate arms`、`bugfix for extrach batch`、`fix gate arm select and tool`、`train for barrier gate` |
| 栏杆训练与优化 | 2月-3月 | `smooth barrier gate in annotation`、`refine barrier gate and tools`、`opt preprocess barrier gate process` |

#### 9. zhangzy30（122 commits｜dev: 0）

**活跃时间**：2026-01-04 \~ 2026-02-10

| 方向 | 时间段 | 代表性提交 |
|-|-|-|
| 道闸栏杆SAM3D | 1月-2月 | `init for add sam3 for gate arms`、`bugfix for extrach batch`、`fix gate arm select and tool` |
| 栏杆渲染与训练 | 1月-2月 | `train for barrier gate`、`smooth barrier gate in annotation`、`refine barrier gate and tools` |

#### 10. zhangzy27（122 commits｜dev: 0）

**活跃时间**：2026-01-17 \~ 2026-03-24

| 方向 | 时间段 | 代表性提交 |
|-|-|-|
| 道闸栏杆SAM3D | 1月-3月 | `init for add sam3 for gate arms`、`modify th for barrier gate in sam3d`、`test: refine barrier gate in sam3d` |
| 栏杆位姿与插值 | 2月 | `add interpolation for barrier gate position`、`bugfix for pose of barrier gate`、`seperate barrier gate for train` |

#### 11. lvwj1（96 commits｜dev: 0）

**活跃时间**：2026-02-06 \~ 2026-06-11

| 方向 | 时间段 | 代表性提交 |
|-|-|-|
| 道闸栏杆SAM3D | 2月-3月 | `init for add sam3 for gate arms`、`fix gate arm select and tool`、`modify th for barrier gate in sam3d` |
| oml数据适配 | 2月 | `adapt optprocessor for omldata`、`load oml barrier gate partI` |
| xpeng_raster | 3月 | `attach xpeng raster to repo`、`build xpeng raster and replace`、`adjust tile size to 8` |

#### 12. quxy（100 commits｜dev: 0）

**活跃时间**：2026-01-30 \~ 2026-06-23

| 方向 | 时间段 | 代表性提交 |
|-|-|-|
| 道闸栏杆SAM3D | 2月-3月 | `init for add sam3 for gate arms`、`add interpolation for barrier gate position`、`loss calculation：enhance barrier gate pixel` |
| 栏杆刚体约束 | 3月 | `add rigid constraint for barrier gate`、`add protection for reading barrier gate mask` |
| 渲染加速 | 3月 | `improve rendering speed：tool size, radius clip, segmentsort and downsample sky` |

#### 13. Zhou Weixu / zhouwx2（47 commits｜dev: 5）

**活跃时间**：2026-02-04 \~ 2026-07-01

| 方向 | 时间段 | 代表性提交 |
|-|-|-|
| 渲染优化 | 3月 | `add static_prune and sh0_collect_cache`、`add sky_downsample`、`sky affine use float16 in postprocess` |
| 资源监控 | 5月 | `add simdiag resource monitoring logs`、`output log when received SIGTERM`、`set 1 hour max for sub_process` |
| CloudSim | 6月 | `simple_the_para_for_run_cloudsim`、`upload loc pose and anchor to oss` |

#### 14. ai-coding（46 commits｜dev: 0）

**活跃时间**：2026-03-28 \~ 2026-07-01

| 方向 | 时间段 | 代表性提交 |
|-|-|-|
| 参考设计文档 | 3月 | `feat(docs): add reference design documentation [ai-coding]` |
| 场景泛化Agent | 6月-7月 | `feat(scenarios-generalization-agent): add LLM call`、`fix(cutin_gen): cut-in car abnormal speed` |
| cut-in生成 | 7月 | `feat(cutin_gen): edit default pad_seconds`、`fix(cutin_gen): gap between ego and cut-in` |

#### 15. lvy10（43 commits｜dev: 0）

**活跃时间**：2026-01-04 \~ 2026-02-05

| 方向 | 时间段 | 代表性提交 |
|-|-|-|
| Difix推理基准 | 5月 | `Add-DiFiX-TRT-ref-cache-experiments`、`Optimize-DiFiX-TRT-profiling`、`Add DiFiX latency optimization report` |
| TRT延迟优化 | 5月 | `Optimize-DiFiX-fast-scheduler`、`Optimize-DiFiX-tensor-ref-lifetime`、`Document-DiFiX-latency-stability` |

#### 16. Codex Remote（23 commits｜dev: 0）

**活跃时间**：2026-05-14 \~ 2026-05-17

| 方向 | 时间段 | 代表性提交 |
|-|-|-|
| DiFiX smoke工作流 | 5月 | `Add remote DiFiX smoke workflow`、`Add-DiFiX-latency-experiment-notes` |
| TRT优化实验 | 5月 | `Optimize-DiFiX-inference-benchmarking`、`Optimize-DiFiX-binding-dtype-cache` |

#### 17. wangyl11（22 commits｜dev: 0）

**活跃时间**：2026-01-05 \~ 2026-02-10

| 方向 | 时间段 | 代表性提交 |
|-|-|-|
| ego pose | 1月 | `WYL: ego pose world`、`WYL: mock ips pose get`、`WYL: ego pose timestamp` |
| scenario | 2月 | `WYL: optimize scenario update`、`WYL: worldmodel case` |

#### 18. fansz（15 commits｜dev: 0）

**活跃时间**：2026-06-16 \~ 2026-07-01

| 方向 | 时间段 | 代表性提交 |
|-|-|-|
| train-sim-eval agent | 6月 | `add CLAUDE.md`、`firstly add train-sim-eval agent`、`add edited eval_tasks_download.py` |
| 场景泛化 | 7月 | `Add a paper`、`add a video to analyze`、`add map .json` |

#### 19. jinxr（6 commits｜dev: 0）

**活跃时间**：2026-06-05 \~ 2026-06-30

| 方向 | 时间段 | 代表性提交 |
|-|-|-|
| inspatio-world | 6月 | `inspatio`、`[inspatio] add models/inspatio-world`、`wan_14b` |

#### 20. gujx3（6 commits｜dev: 0）

**活跃时间**：2026-06-24 \~ 2026-06-26

| 方向 | 时间段 | 代表性提交 |
|-|-|-|
| 天气风格编辑 | 6月 | `path_change`、`fuyao改动`、`unique_frames_inference`、`初步天气风格编辑` |

#### 21. fengmh（5 commits｜dev: 0）

**活跃时间**：2026-02-24 \~ 2026-03-04

| 方向 | 时间段 | 代表性提交 |
|-|-|-|
| SAM3 prompt | 2月-3月 | `init`、`add dustbin and catron for sam3 prompt`、`add fence&carton&dustbin prompt for sam3 in preprocess` |

#### 22. wangh（4 commits｜dev: 0）

**活跃时间**：2026-01-07 \~ 2026-01-22

| 方向 | 时间段 | 代表性提交 |
|-|-|-|
| localpose | 1月 | `use train localpose z value`、`fix error` |

#### 23. zhengln（3 commits｜dev: 0）

**活跃时间**：2026-03-10 \~ 2026-03-13

| 方向 | 时间段 | 代表性提交 |
|-|-|-|
| profiler | 3月 | `add profiler_report`、`move frame_idx from cpu to gpu`、`multi camera version` |

#### 24-27. 其他少量贡献者

| 贡献者 | 提交数 | 活跃时间 | 代表性提交 |
|-|-|-|-|
| xiaobp | 2 | 02-06 | `fix turn right`、`rebase` |
| Your Name | 2 | 01-22 \~ 01-26 | `xpeng raster same resolution 5 cams`、`add log` |
| zhangdk1 | 1 | 01-07 | `use local pose train z` |
| Xihu Lai | 1 | 03-20 | `add prune_all_gaussians_for_render` |

#### 28. adc_pdd_ciops_gocicd（9 commits｜CI/CD 自动化）

**活跃时间**：2026-02-11 \~ 2026-06-15

CI/CD 流水线自动创建和更新 branch.yaml，用于管理发版分支配置。

### 全分支 vs dev 分支对比分析

<callout emoji="📊">
**dev 分支覆盖率低**：28 位贡献者中仅 7 位有提交进入 dev 分支。大量工作（如 dusc 的 703 条、xuzh2 的 418 条）完全在个人/功能分支上完成，未合入 dev。
**主要原因**：
1. dev 分支于 6月4日才重建，之前的历史被丢弃
2. 团队采用 **功能分支 → 发版分支直接发版** 的模式，不强制经过 dev
3. 部分分支为实验性开发（如 root 共用分支），不计划合入主干
**建议关注**：
- dusc 和 xuzh2 的分支是否需要合入 dev
- ai-coding 的场景泛化 Agent 是否已进入正式开发流程
- gujx3 的天气风格编辑功能进展如何
</callout>