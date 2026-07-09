# OKR 进展拆解 · Li Kun（截至 2026-06-26）

> 配套个人试用期 OKR（4 个 O / 14 个 KR）的工作进展拆解。OKR 正文在飞书 OKR 组件内（GXgDdti1...），本文承接其结构，把当前工作按 KR 填入 Progress / Issue / Risk / Plan 四项。

---

# O1 SIL 链路：常态化运行与标准化评测，成为 FM 发版正式算法评测标准

## KR1 SIL 最小闭环可信基准 + 版本管理基座，漏报率控制 20% 以内

**Progress this week**
- 车型泛化从实验阶段进入规模化生产，完成 F30bes / h93aes / e29 等七车型同场景闭环对比，结论与实车趋势一致；
- 完成斑马车衣与正常车衣互换闭环验证，确认外观差异不影响仿真决策一致性；
- 广州 RC 路线完成 200km SIL 仿真，输出版本对齐结论，当前对齐率 46%；
- VLA 市场问题闭环复现率 81.25%（26/32 起碰撞事故可复现），漏报侧已有初步基准。

**Issue identified**
- 对齐率 46% 距"可信替代实车"差距大，失真集中在安全碰撞、不居中、行驶顿挫三类；
- 失真根因尚未区分是渲染问题还是 FM 模型问题，若在模型侧算法组难独立解决；
- 闭环 metric 连续数周不可用，场景"能跑"但"不能毕业"，漏报率无法量化对齐。

**Risk & resource support**
- 依赖评估组 6/20 闭环 metric 验收，若再延期需部门层面协调；
- 需 FM 团队配合排查横向/纵向控制参数 diff。

**Plan for next week**
- 46% 对齐率按失真类型专项拆解（碰撞/不居中/顿挫/其他），逐类定位根因；
- metric 不可用则用复现率 Agent + 人工抽检双轨先行，毕业场景须 ≥3 次复现且人机一致率 ≥85%。

## KR2 SIL 渲染瑕疵 + difix 算法效果/效率标准化评测卡口

**Progress this week**
- CLIP-IQA 无参考质检卡口跑通，当前筛除约 13% 渲染差 case，召回约 90%、精确约 75%；
- 质检 gating 已合入 IPS，进入生产链路；
- NQA 评测代码完成测试、已编包仿真，与平台对齐 JSON 输出格式与集成验证点。

**Issue identified**
- 精确度 75% 距目标 80% 差 5 个点，存在约 25% 误杀；
- 长里程阈值未精调，不同城市/路段质量分布不同，单一阈值会造成部分路段误杀偏高。

**Risk & resource support**
- 需平台支持 CLIP-IQA JSON 结果流转到 Cloudsim 联调。

**Plan for next week**
- 长里程数据按城市/路段分别统计质量分布，制定分层阈值；
- 误杀 case 专项标注（50 case 人工复核），找出误杀模式后调参。

## KR3 SIL 渲染+解码双链路提速：单帧 0.5s 内 / 性能比 1:5 / H265 解码 1:2

**Progress this week**
- 渲染性能比（difix，MIG 口径 apple-to-apple）：baseline 1:17（510s/clip），优化后 EXP_5 ref 降分辨率达 1:14.8、EXP_6 达 1:15.5；NVFixer ref 新版 TRT 轨迹评测 1:7.2（前序未优化 1:6.5）；
- YAML→npz 加载优化，3DGS 模型加载耗时降低 72%（平均每 clip 约 5 秒）；
- 去掉 DDS 原始图像 topic，单场景耗时减少 11 秒；
- 实时模式不带 difix 已完成 10km 小数据跑通。

**Issue identified**
- difix（MIG）当前最好 1:14.8、NVFixer ref 1:7.2，距目标 1:5 仍有较大差距；PTQ + 算子融合已到 FMHA 天花板，剩余空间在系统侧非算法侧；
- H265 解码侧 1:2 目标进展未明确。

**Risk & resource support**
- 进一步压降受 GPU 算力约束，需与平台协商 GPU stream 并行度。

**Plan for next week**
- 解码侧专项定位 H265→latent 转换瓶颈，给出 1:2 可行路径或明确不可达；
- 若 1:5 短期不可达，建立分级耗时标准（快速 1:6 / 慢速 1:10 可接受）。

---

# O2 HIL 链路：稳定运行 + 等效性验证，成为模型发版上车的最终 gating 手段

## KR1 HIL 集成链路打通 + 渐进式规模验证，网时比 1:3 以内

**Progress this week**
- XTest 标准运行框架正式接入 HIL，广州 RC 路线闭环任务试运行；
- 完成 100 场景 × 5 次 = 500 case 一致性压测，500 job 中 95% 通过 CCES 检查；
- 77% case 的 P95 横向误差 < 1m，里程一致性中位数 0.21%；
- 节点从 3 扩展到 5（新增 004/005）；
- 排查修复台架异常重启、PC 模块丢包、mflocalpose 跳帧、下游错帧；当前耗时比不刷包约 1:3、刷包约 1:4。

**Issue identified**
- 一致性 77% 距准出标准 ≥90% 差 13 个点，根因是 14 个大偏差 case（初判 FM 起始速度/加速度 diff）；
- HIL 底层调度存在多次运行随机性，同 case 多次运行结果不完全一致，影响可重复性。

**Risk & resource support**
- 003 节点需平台加 pod 支持；万兆网卡对比实验待排期。

**Plan for next week**
- 14 个大偏差 case 根因归类（FM diff / trigger time / 渲染帧错位 / 未知）；
- 建立 HIL 随机性管理规则：同 case 跑 3 次取中位数，方差超阈值标记"不稳定"不进准出；
- 5 节点全量压测，输出带 PAT 的阶段性验收报告。

## KR2 HIL 高保真渲染 + 复现率：纯 3DGS 50% / difix 60% / 综合 80%

**Progress this week**
- 极速模式相对复现率 74%（正常模式基线），绝对复现率约 50%；
- 慢速模式（带 ref 图 NVFixer）在上海台架跑通，里程差异 0.3m、横向 < 0.1m，一致性显著优于快速模式；
- difix 默认开启随发版上线，VLA 闭环复现率 81.25%。

**Issue identified**
- 极速模式有约 30% 复现率折损，根因在 feedforward 重建质量（跳过逐场景训练），非 difix 参数；
- 慢速模式 latent 直读代码适配仅 50%，未能规模跑、缺统计意义一致性数据；
- 近点模糊待改善，受 GPU 算力约束。

**Risk & resource support**
- 短期提复现率需匀 GPU 给 difix 训练；
- 慢速模式重刷耗时预估待出，可能只能用于高价值 case。

**Plan for next week**
- 完成慢速模式 latent 代码适配剩余 50%，跑 50 case 端到端验证；
- 极速→正常模式"晋级率"作为极速可信度持续 KPI；
- GPU 到位后优先训 difix 近点专项数据集。

## KR3 HIL 等效性验证卡口 + 200+ 台架规模化 + 闭环准出

**Progress this week**
- HIL 渲染与 difix 等效性验证卡口框架搭建中，依托 XTest 标准链路；
- 慢速模式时间依赖问题已解决，为 gating 高可信复现提供基础；
- 台架 TensorRT 转换完成 80%，Seal/HIL 链路已合入 dev 最新分支（计划全局开关控制）。

**Issue identified**
- 闭环 metric 仍在评估组开发中，未验收前 3DGS 场景发布和 RC 链路毕业存在不确定性；
- 200+ 台架规模化的稳定性压测结论尚未沉淀。

**Risk & resource support**
- 强依赖评估组 6/20 七类闭环 metric 验收（核心里程碑）。

**Plan for next week**
- 推动 6/20 七类闭环 metric 按期验收，作为 6 月 HIL 链路核心里程碑；
- 三节点跑最后一轮稳定性压测，输出可消费的闭环结论模板。

---

# O3 规模化生产：3DGS 场景级标准化量产通道 + 长里程交付 + 数据质检体系

## KR1 长里程 MVP + 极速量产通道：日产 1000 case，1wkm 长里程交付

**Progress this week**
- RC 路线外业采集累计 2000km+（截至 6/17 新增约 1000km），月底目标 2500km；
- UCP batch 模式上线，日产目标 70~100km；扶摇 SDK warmup 从 1.5h 压缩至 0.5h；
- 广州 RC + 新增路线持续生产，42 组完成 36 组，产出 786 个 scenario。

**Issue identified**
- 距 1wkm 全量交付差距大，按月底 2500km 计 Q2 覆盖约 31%，Q3 需大幅加速；
- 长里程部分 case timeout（anti-distort 子进程未退出致父进程卡死），成功率 50~90% 波动；
- 76 条历史 subrun 因前期数据 pipeline 格式不兼容未入库。

**Risk & resource support**
- 数据 pipeline 历史积压需走数据闭环 oncall；
- 需 TC 持续补充城区/高速/园区高价值源头 case。

**Plan for next week**
- anti-distort 卡死专项：多进程池改线程池 + 子进程 timeout/kill + 失败自动重试；
- 月产能爬坡：6月底 2500km → 7月底 5000km → 8月底 8000km+（4 城全覆盖）；
- 76 条积压区分可挽救/不可挽救，可挽救的提单恢复。

## KR2 高价值 CornerCase 场景定制开发 + 业务交付机制（主动安全/泊车/VRU）

**Progress this week**
- 场景编辑动态资产库累计 1700+；
- 规则轨迹自动生成跑通 cut-in 场景（基于 RI Local Map 定车道、TTC 定触发点）；
- 大逻辑已完成、细逻辑调测中，6/15 起可批量一键执行（本地 + UCP），已产初批 case 做仿真测试。

**Issue identified**
- 目前仅跑通 cut-in 一类，距覆盖靠边停车、VRU 横穿、复杂让行等高价值场景还有距离；
- 规则可维护性和泛化性是瓶颈，大模型编排轨迹仍在构想阶段。

**Risk & resource support**
- 业务单点需求常直接找执行人致团队压力，需平台开放自助操作分流。

**Plan for next week**
- 完成 cut-in 全链路验证（batch 生产 + 仿真 + 评估）确认端到端可用；
- 启动靠边停车、VRU 横穿两类场景的规则开发。

## KR3 1 小时极速验证模式 + golden testcase + 自动化质检/gating，入库复现率 50%

**Progress this week**
- 极速模式 UCP 全链路约 100 分钟（前处理 + feedforward 训练 + difix 渲染 + 评估），默认打开随发版上线；
- 采用"漏斗策略"——极速先过一遍，复现率不足的 case 再进正常生产；
- 场景集管理流程工具 6/22 上线（入库/生产筛选/标签/车型泛化）。

**Issue identified**
- 极速复现率约 50%、30% 折损为结构性问题，对 gating 数据集结论不可信；
- golden testcase 标准与自动化质检 gating 仍需固化。

**Risk & resource support**
- 近点模糊改善受 GPU 约束。

**Plan for next week**
- 文档明确标注极速模式结论为"参考级"，不作为准出依据；
- 统计极速→正常模式晋级率作为可信度 KPI；
- 后续接入 NVFixer 最新版评估极速链路轻量 ref 图补偿。

---

# O4 算法预研：下一代生成式仿真技术，为 3DGS 渲染闭环优化升级奠定基础

## KR1 「更好」Diffusion 新模型：轻量化、多摄一致性、新视角生成阶段性验证

**Progress this week**
- NVFixer 架构升级 V3C（DIT block 全局 self-attention）/ V3D（VAE decode 前注入 latent），实验 PSNR +6~8dB、LPIPS 明显改善；
- 周末提交 64 卡全量数据大批量训练，下周做变化仿真 FM 轨迹评测；
- AVM 鱼眼 cam9 渲染适配完成、初版效果验证，支持 9 个微相机 3D 逆向投射（多摄一致性方向）。

**Issue identified**
- 64 卡全量训练结论待产出，若大规模增益不如小实验需快速回退；
- 鱼眼图片颜色差异未解决，待接入 difix 修复；
- 带 ref 图方案前提是参考图可获取，新路线/新城市可能不存在或时效差。

**Risk & resource support**
- 大批量训练占用 64 卡 GPU。

**Plan for next week**
- 大训练结束后立即做 FM 轨迹评测，对比 V3C / V3D / V2 baseline 后冻结架构；
- 鱼眼颜色差异接入 difix 验证效果，输出 AVM 下一步计划文档。

## KR2 「更快」Feedforward 新方法：大幅缩减 3D 重建耗时，提升生产自动化

**Progress this week**
- FF/WM 方向输出 15 篇综述；
- 完成 3DGS 输入 vs feedforward 输入对比实验：3DGS 渲染作为输入优于 feedforward 输入训 diffusion（后者会"抄 ref 图"，疑信息量不足）；
- 与极佳科技交流 feedforward + dreamzero world model。

**Issue identified**
- 预研处于探索阶段，Q2 内不进入生产（预期内）；
- feedforward 重建质量是极速模式 30% 折损的根因，需聚焦提升。

**Risk & resource support**
- 杜思聪 6/5 离职，feedforward 探索 Owner 部分空缺，已由组内消化。

**Plan for next week**
- 确认"3DGS 输入优于 feedforward 输入"后聚焦 3DGS + Diffusion 联合架构；
- 明确 FF 方向对接点：服务极速模式提复现率。

## KR3 「交互」Smart Agent：核心动态场景交互 case，编辑+生产 / 实时规划+渲染两路

**Progress this week**
- 规则轨迹自动生成（编辑+生产路线）跑通 cut-in，作为交互场景的基建；
- 探索用大模型作为智能体编排轨迹生成逻辑（实时动态规划方向构想）。

**Issue identified**
- 大模型编排仍在构想阶段，短期依赖规则；
- 两条路线（编辑+生产 / 实时规划+渲染）尚未明确优先级。

**Risk & resource support**
- 需算法 + 工程协同，跨 cut-in 基建复用。

**Plan for next week**
- 在 cut-in 基建上扩展更多动态交互场景；
- 评估大模型编排可行性，明确两路线优先级。

## KR4 「泛化」基于 3DGS 本身的场景泛化能力探索

**Progress this week**
- 车型泛化代码已全部合入 Cloudsim，发起与 scenario 创建均由 Cloudsim 控制，UCP 任务由 file 模式改 custom 模式；
- 场景集管理流程工具上线（含车型泛化），可出仿真比较报告；
- 斑马车衣/正常车衣互换验证泛化鲁棒性。

**Issue identified**
- 当前泛化以车型/车衣为主，路况/天气/城市维度泛化尚未系统验证；
- 泛化结论可信度受 SIL/HIL 对齐率制约。

**Risk & resource support**
- 泛化能力验证依赖多城市、多车型数据。

**Plan for next week**
- 在多路段/多天气条件下验证泛化稳定性；
- 与 SIL 对齐率专项联动，明确泛化适用边界。

---

> **跨 O 共性风险**：① 评估组闭环 metric 是多个 KR 的共同卡点，需部门层面管理；② 杜思聪离职后生产链路单点风险，7 月前完成关键流程文档化 + skill 化；③ GPU 算力是渲染提速、近点优化、大批量训练的共同约束，需统一排期。
