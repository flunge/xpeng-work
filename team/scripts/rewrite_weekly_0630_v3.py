#!/usr/bin/env python3
"""周报 0630 v3 — 完全按新规则重写：
- 全会议清单已核（11 场全读，2 场 HR 类跳过）
- 承诺追踪表已建立（14 项跟踪、3 项静默已显式呈现）
- 决策对比（代码治理 180° 转向、场景集目标降配）
- 缺口/静默已检测并融入报告
- 每个数字可溯源到源文档
"""

import subprocess

DOC_TOKEN = "KtzLdBh3ToRFLYx5R66cpLiHnEk"

U = {
    "朱啸峰":'<cite type="user" user-id="ou_09b6f76c8d98f186bb7163406fe3894a" user-name="朱啸峰"></cite>',
    "邓爽":  '<cite type="user" user-id="ou_0c29f42f96320d32e36b8616342955ef" user-name="邓爽"></cite>',
    "王禹丁":'<cite type="user" user-id="ou_16ed70882e5f4247b330612054b07d3f" user-name="王禹丁"></cite>',
    "郑丽娜":'<cite type="user" user-id="ou_279a0e5c146848e3d2dfaefe85f2c505" user-name="郑丽娜"></cite>',
    "樊世洲":'<cite type="user" user-id="ou_41c1fbbdee2aa8ced7cbe495a0e4b9c3" user-name="樊世洲"></cite>',
    "夏志勋":'<cite type="user" user-id="ou_4e4a0102b41b6feb1a7043ec45dfad40" user-name="夏志勋"></cite>',
    "刘开拓":'<cite type="user" user-id="ou_5ff13a6d397bcb698bbfb66800fbb83a" user-name="刘开拓"></cite>',
    "靳希睿":'<cite type="user" user-id="ou_6dbb165c2c7f4dd57532ffda75e51169" user-name="靳希睿"></cite>',
    "赖西湖":'<cite type="user" user-id="ou_795c727d71c02a25501a3fd4d2af540c" user-name="赖西湖"></cite>',
    "严潇竹":'<cite type="user" user-id="ou_9b65b8c67807ce544a5cef3efe5cbf8a" user-name="严潇竹"></cite>',
    "裴健宏":'<cite type="user" user-id="ou_a76e6fffce1c513ed5b33555aec19076" user-name="裴健宏"></cite>',
    "云荟":  '<cite type="user" user-id="ou_ad1ca535c4cc2642eb850dc22b024e49" user-name="云荟"></cite>',
    "杨星昊":'<cite type="user" user-id="ou_b41c33085d2e629fbdff0c555cae0a3f" user-name="杨星昊"></cite>',
    "周冯":  '<cite type="user" user-id="ou_c37bf637460fbc4d1dd53470ecae8889" user-name="周冯"></cite>',
    "周蔚旭":'<cite type="user" user-id="ou_c9f3e88a0d6f949b332a40a155814e69" user-name="周蔚旭"></cite>',
    "吕文杰":'<cite type="user" user-id="ou_e6eb2da48b30725b46c548a1bcbf3fc6" user-name="吕文杰"></cite>',
    "瞿鑫宇":'<cite type="user" user-id="ou_f360c7cfbd4fcbdc624c012dc151c6a4" user-name="瞿鑫宇"></cite>',
}


def u(n):
    return U.get(n, n)


SCENE_GOALS = '''<checkbox done="false">【业务交付】【闭环场景】完成8类Q2的头部问题闭环场景集生产交付和上线；</checkbox><checkbox done="false">【业务交付】【RC产线】产出北上广深全量的RC路线。</checkbox><checkbox done="false">【业务交付】【RC产线】当前产能评估以及后续新数据上线以及产量爬升计划。</checkbox><checkbox done="true">【产线规模化】形成便捷的客户端极速生产+验证模式，前端支持特定客诉case的快速生产+仿真验证，全链路时延2h以内。</checkbox><checkbox done="false">【算法优化】静态GGS+WM一阶段demo形成下一步可执行的落地方案。</checkbox>'''
SIL_GOALS = '''<checkbox done="false">【业务交付】【车型泛化】实现车型泛化业务侧常态化使用，完成仿真daily评测的闭环。</checkbox><checkbox done="false">【业务交付】【RC路线仿真】完成北上广深的RC路线（1000+km）仿真以及一阶段闭环指标的验证。</checkbox><checkbox done="false">【算法优化】复现率gating数据集上复现率达成80%以上，效率达到1：25，渲染效率1：5。</checkbox><checkbox done="false">【算法优化】SIL链路评测接入CLIP-IQA图像质量校验，图像质量召回率99%/准确率95%。</checkbox>'''
HIL_GOALS = '''<checkbox done="false">【HIL链路】1000km+RC路线稳定运行无中断验证，闭环运行的结论稳定可对外输出，运行稳定性达到95%以上。</checkbox><checkbox done="false">【HIL效率】实时模式效率比在1：3以内，慢速模式+difix效率比在1：5以内。</checkbox><checkbox done="false">【HIL指标】阶段性验收报告带PAT评测</checkbox>'''
AGENT_GOALS = '''<checkbox done="false">【业务Agent】完整集成复现率agent进入到各需求环节，可以进行常态化问题分析和归因，各项指标的准确率达到80%以上。</checkbox><checkbox done="false">【代码Agent】Simworld仓库整理方案：630达到某个阶段性的工程优化指标</checkbox>'''


# === 场景&生产 — 含承诺兑现/静默标注 ===
SCENE_PROGRESS = f'''<p><b>【业务交付】</b></p><ul><li>【闭环场景集】{u("刘开拓")}<ul><li>城区毕业率 87%（剩 5 项；6/29 异常减速本周毕业，其余 4 项不再跟踪），园区 69%（4 项延期，本周摆动+导航走错路毕业），Robotaxi 5 项延期（停车纵向/横向偏差/阻塞交通/违章停车）。</li><li>目标变更：Q2 闭环目标从 8 个降为 6 个（6/24 与高炳涛对齐后）；6/29 评估 12 项本周仍有未完成风险，根因 IP 实车 case 模型旧+折损率高，{u("杨星昊")} 修复、{u("夏志勋")} 团队补票。</li></ul></li><li>【RC 长里程】{u("刘开拓")}{u("郑丽娜")}<ul><li>TC 端 968/1750km（30% 折损后目标）；大数据 35% 折损 backfill 重试中；端午 {u("云荟")} 协调 3DGS 私有卡池重产广州 184km subrun 完整数据，6/24 重跑 285/288 成功；6/25 拆解 undistort 多进程非 spawn 致 timeout 已修，公共卡池被高优挤掉风险待解；本周累计 478km 新数据，目标 7/2 累计 1000km。</li><li>新风险：6/29 AJS 长路线 20-30% 数据损失，初判 TC 采集软件抢占资源致数据损坏，{u("刘开拓")} 出"一页纸"上升处理。</li></ul></li><li>【极速模式】{u("周蔚旭")}<ul><li>内部团队（爽）无诉求确认，已开放给质量+海外 Moe 用户；<b>对外交付文档 6/26 已交付</b>，操作便利性优化 7/2 完成后正式对外开放；feedforward 效果较 3DGS 差排查中，{u("刘开拓")} 安排实习生查 feedforward 论文+开源代码以借鉴。</li></ul></li><li>【场景执行效率·case 截断】{u("夏志勋")}（莫春媚）<ul><li>6/30：4728 项 case 第一版截断完成，Stage2 仿真效率明显提升（Stage1 扶摇 job 化受调度影响差异不明显）；截断前后两版模型验证指标稳定（撞车/撞 VRU 回退 5.8%→5.9% 基本一致），舒适类幅度因只评有效段而收窄（变道顿挫 49%→40%，符合预期）；遗留：约 1000+ case 需加接管时间重洗、变道类需联合 TTC/TTE 多 metric 判定。</li></ul></li><li>【仿真先行整体盘】{u("邓爽")}<ul><li>6/30：6/1 起分两条线，28 天共评测 <b>182 个模型</b>（范博 620 老框架新车型 133 个 + 航哥新模型结构 5 款车）；620 实测对比 610——走错路 1.0→1.7 次/百公里、异常减速 0.9→1.4，多为带条件通过；待补自动化回填+结论总结（7 月上旬）、与 TC 反馈闭环未完善。</li></ul></li></ul><p><b>【算法优化】</b></p><ul><li>【场景编辑】{u("裴健宏")}<ul><li>规则轨迹自动生成增至 4 类（切入/切出/跟车/对向车），UCP 单次编辑 4 分钟（瓶颈在模型/DDS 上传下载）；通过引入地面点云尝试修复编辑车 roll/pitch；编辑车未渲染问题修复（兼容新旧 3DGS 配置）；Sensor Fusion topic 同步改在 simulation 实现（减轻 ucp 链路负担）；现阶段编辑车出现时不加载真实动态车以避免视觉跳变。</li></ul></li><li>【AVM 鱼眼】{u("王禹丁")}：gsplat 环境构建完成、数据流程打通中（一阶段完成），训练链路排 Q3。<b>静默项：颜色差异接 difix 修复方案未推进</b>。</li><li>【静态 GGS+WM】{u("杨星昊")}{u("靳希睿")}<ul><li>训练侧：Inspatio-world LoRA 微调 700 clips；32 卡半天可训 10 epoch（cache latent 提速）；训练步数对比 200=4min/1000=8min/2000=13min、1000 步效果提升；6/26 不带 ref vs 带 ref 训练对比中 infer 时模型无进步、疑代码问题待确认。</li><li>推理侧（6/25 WM 同步）：multi-batch 推理 PSNR 50→20（4 月底加车道 fingerprint 致累积误差），FP8 推理 0.8s→1.8s（缺 RTX Pro 5000 内核+DIT attention FP8 原生算子，已手写算子待测）；7 月中旬新模型发布，先用老 126 case 跑 CCES 闭环（6 个指标）。</li><li>研判：模型 1.3B（与 Difix 相当），copy ref 偏强，疑 feedforward 输入信息不足。</li></ul></li></ul>'''


# === SIL — 含 RC 验证依赖 / 1:5 物理瓶颈承认 ===
SIL_PROGRESS = f'''<p><b>【业务交付】</b></p><ul><li>【车型泛化】{u("杨星昊")}{u("裴健宏")}<ul><li>与 {u("赖西湖")} Cloudsim 全链路联调完成，多车型 Pipeline 6/23 上线，Moe 模型自测正常待发版；车型泛化 6/29 开闭环上线、存在交互小问题修复中；车端 calibration 包到 3dgs calib.json 转换完成，待平台联合测试。</li><li>聚类研究（响应 6/22 双周会要求）：6/24 茶水间拉小范围会（邀于亦奇/范博/DRE），6/26 算法 idea 会确认三参数扫描方案（车衣/外参 pitch+roll/车型），{u("杨星昊")} 整理文档后收集思静/佳祺/惠康/陈进意见。</li></ul></li><li>【车衣验证】{u("杨星昊")}{u("王禹丁")}<ul><li>已验证斑马车衣致不加速、白色车衣可达限速；6/24 高炳涛要求泛化车衣样式进验证集（避免测试车/量产车差异）；6/26 算法 idea 会王逸舟提出三参数扫描方案（车衣/camera pitch/roll/车型），单车型间侧前 pitch 1° 即影响效率/居中。</li></ul></li><li>【RC 路线 SIL 验证】{u("王禹丁")}{u("夏志勋")}<ul><li>DSOP 闭环 metric 因代码 RTM topic 格式变更读不到，确认"先 10 metric 用老框架跑起来"策略；{u("朱啸峰")} 本周出基于 1300+ scenarios 的初版报告，下游每周新增 1 个闭环 metric（{u("夏志勋")} 排优先级）。</li><li><b>风险</b>：10 metric 起跑被阻塞，依赖根因修复。</li></ul></li><li>【红绿灯通行验证】{u("杨星昊")}：630 FM 模型完全红绿灯通行需验证，10 测试 case 已提交生产，等 {u("周冯")} NVFixer 上线后再看新效果。</li><li>【metric 开发】{u("夏志勋")}<ul><li>6/30：5 月→6 月中高强度迭代后缺陷明显减少；新框架 behavior 层完成 7 项整理 + 合规类修复，导航类/合规类 KPI 显著提升、<b>召回提升 10+ 个百分点</b>；安全类因移植未完成（俊强/仲君高优交付占用）受阻、剩 3 个在做；园区 12 任务交付 4 个、3 个本周完成；争取 <b>7/17</b> 云端平台集成、7/14 与 7/24 DT 推 metric 上车。</li></ul></li></ul><p><b>【算法优化】</b></p><ul><li>【Fixer 渲染优化】{u("周冯")}<ul><li>NVFixer ref TRT 渲染 1:7.2（vs 未优化 1:6.5、Difix 1:17）；6/25 SIL 链路打通、TRT-torch 输出对齐、FM 评测一致；6/24 决策尝试 TinyVAE 蒸馏路径（latent 空间与 cosmos 不一致）；6/26 HIL Nvfixer ref 新方案（VAE encoder 放预处理 pipeline、复用 ref latent），PPU 环境适配中（holmes 替代 trt，ref encoder 11.7ms/帧 → ref latent 0.281MiB）。</li><li><b>承认物理瓶颈</b>：PTQ 量化敏感层溢出、算子融合 FMHA 已是天花板；月目标 1:5 大概率难达成，下一步靠 TinyVAE/LightVAE 蒸馏或硬件迁移。</li><li>新发现：新 dev 分支较旧分支 difix 渲染耗时增加（1:17.6 vs 1:17），{u("周冯")}+{u("杨星昊")} 排查仓库版本差异。</li></ul></li><li>【CLIP-IQA】{u("王禹丁")}<ul><li>与 {u("夏志勋")} 团队联调完成、<b>6/26 周四已上线</b>（按承诺兑现），过滤极差 case 验证有效；HIL 接入实时性问题（单帧 40ms/2.7G 超 80ms 阈值），方案改异步/云上待定。</li></ul></li></ul>'''


# === HIL — 含 1000 工作台 delay 显式呈现 ===
HIL_PROGRESS = f'''<p><b>【HIL 链路】</b></p><ul><li>【常规模式 + 节点扩容】{u("朱啸峰")}<ul><li><b>6/29 HIL 链路演示/AB Review Agent Demo 阶段验收</b>（{u("郑丽娜")} 主讲）：HIL 链路 5 节点机房部署可用，3 节点跑近 1500 条数据无中断；<b>实时模式 batch=20 效率 1:2.82、batch≥30 达 1:2.5（已达月目标 1:3）</b>；数据可用性 100%（5% 丢帧阈值，localpose UDP 阶段掉帧待网络层优化）；100 case × 5 次一致性 — 优秀/良好档无显著随机性，14% 一般需 PAT 评测确认，8 个最差判为不可用、已列入优化记录；PAT 评测链路已打通跑了两版本对比，准确度待 {u("夏志勋")} 确认。</li><li>Cloudsim job 提交集成（submit new job）已上线，batchsize 默认 30 提效；二期交互优化让 {u("刘开拓")} 试用一次性解决易用性问题。</li><li>6/25 HIL 节点会专项排查：004 节点网络配置与 002/003 不同（SRE 接入特殊配置异常），显卡驱动与 Docker 安装顺序待标准化，分阶段镜像方案（基础+服务）；005 待 004 镜像验证后接入。</li><li><b>进度风险</b>：原 6 月底"1000 工作台跑起来"未达，新阶段目标 7 月底前 5 台机器跑通问题；5080 预算月底拿到→IT 定点采购 2 周→供应商交付 10 台约 2 周+，预计 7 月底或 8 月初交付，{u("朱啸峰")} 与张驰沟通拿回操作系统镜像制作链路。</li></ul></li><li>【慢速模式】{u("瞿鑫宇")}{u("周冯")}<ul><li>xos/perception_xp5/simulation 实车 DT 合入主线编包部署中；NVFixer Ref 慢速链路（H265→VAE encoder latent）代码适配 50%，已给重刷耗时和 latent 大小预估；适配 ceph 自动化下载解压 latent + 按 cam/timestamp 每帧自动复用；连续 case 尾部掉帧根因分析中，{u("郑丽娜")} AI 分析本周收尾。</li></ul></li><li>【交付与下游】<ul><li>交付组 6/30 周二开始试用评测准确度，{u("郑丽娜")} 牵头；6/29 Demo 中 {u("郑丽娜")} 演示 review agent 快速 demo（针对化隆）可对两个版本特定指标出静态质检报告，待 {u("邓爽")} 定优先级后与 {u("夏志勋")} metric 计划协同推进；SF 运行异常 VRU 缺失定位为 mflocalpose 字段缺失、已与 SF 同学确认填充字段。</li></ul></li></ul>'''


# === Agents — 含 AI agent ROI 静默项显式呈现 ===
AGENT_PROGRESS = f'''<p><b>【业务 Agent】</b></p><ul><li>【复现率 Agent】{u("吕文杰")}{u("周蔚旭")}<ul><li>本周新增 7 类问题场景开发，agent 累计支持 11 类；道内画龙 80%+（22/27 = 81%）满足上线标准；6/26 生产验收复现正确率 89%（{u("周蔚旭")}）；FMprompt 复现率单训练集 80%（deepseek-v4 微调 20+40）；摆动复现准确率 19/24 = 79%（FMprompt 12/24 = 50%，疑真值标记错误）。</li><li>未完成：危险变道/绕行 24 case（7 case 多次调试不收敛）、不居中/贴边 14、撞路沿/障碍物 12、未及时变道 10。</li><li><b>静默项：6/22 双周会要求"AI agent 明确落地计划节点+量化收益"，本周 0 显式输出（下次双周会需主动对齐）</b>。</li></ul></li><li>【TopDiff / Diff Agent】{u("严潇竹")}<ul><li>每周支持新 metric 自动 edit review，6 个 metric 自动 diff 准确率 50%；本周道内画龙 Topdiff 7/11 正确上报、与人工一致率 64%；主辅路/分合流未跟导航 50+ case 一致率 70%、进逆向车道旧数据过期重新准备、变道找不到空挡方案设计完成。</li><li>反馈：6/26 高炳涛点名"开发与使用脱节"，要求 {u("严潇竹")} 协调"维持开发节奏 vs 开发急需新 metric"、确定反馈人；数据迭代提升准确率需提供报告证明。</li></ul></li><li>【Prompt 对齐 Agent】{u("严潇竹")}<ul><li>提示词开关+飞书机器人 HTML 输出已解决，73 case 中 54 可比、人工一致率 83.3% → 85%；与刘星昊对齐"卡严/高准确率/允许漏报"新标准；二次分级与 {u("吕文杰")} 确认可行，{u("郑丽娜")} 组织生产同学试用推广。</li></ul></li><li>【OnCall + 融合机器人】{u("郑丽娜")}<ul><li>目标 6/30 上线，链路打通处于能用状态，oncall 由晋之验证准确率，融合机器人灰度阶段（薛栋+冠秋查看）；6/26 强调"机器人不能自己验收、要业务同学多使用"。</li><li>【3DGS 生产 OnCall Agent】{u("周蔚旭")} 启动前期工作，规范日志落盘 OSS → 自动错误诊断 → 单次报告 → 多版本对比 → 智能问答。</li></ul></li><li>【AB Review Agent / 质检报告】{u("郑丽娜")}<ul><li>6/29 HIL Demo 演示针对化隆的 review agent 快速 demo：可直接对两个版本特定指标出结果，生成静态页面质检报告；期望与 {u("夏志勋")} metric 计划结合协同人力，待 {u("邓爽")} 定优先级后拉会推进。</li></ul></li></ul><p><b>【算法/代码 Agent】</b></p><ul><li>【Simworld 仓库治理】{u("杨星昊")}{u("郑丽娜")}<ul><li><b>决策转向</b>：6/22 双周会要求"7 月解决严重问题、Q3 大调整、各组下周一前提整改计划"→ 6/29 调整为"每周扫实际存在问题直接修改"（追求最佳性价比、不大规模改造代码框架）。</li><li>【车型适配 Agent】6/24 已上线，飞书完成车型 mask 适配+提交 git，计划推广给 {u("云荟")}。</li></ul></li><li>【环境构建 Agent / Docker 自动化】{u("王禹丁")}<ul><li>Docker 自动化构建本地跑通（输入 base image+安装包→自动提交测试），dockerfile 跟随 simworld git、fuyao sleep job 进 shell 安装、whl 包管理。</li></ul></li><li>【Smart-Agent Planner】{u("樊世洲")}：本周组内未实质性同步。</li></ul>'''


def build_table():
    xml = '<table>'
    xml += '<colgroup><col width="100"/><col width="300"/><col width="600"/></colgroup>'
    xml += '<tbody>'
    xml += '<tr>'
    xml += '<td vertical-align="middle"><p align="center"><b>链路</b></p></td>'
    xml += '<td vertical-align="middle"><p align="center"><b>月目标</b></p></td>'
    xml += '<td vertical-align="middle"><p align="center"><b>核心进展0624-0630</b></p></td>'
    xml += '</tr>'
    for label, goals, prog in [
        ("场景&amp;生产", SCENE_GOALS, SCENE_PROGRESS),
        ("SIL",          SIL_GOALS,   SIL_PROGRESS),
        ("HIL",          HIL_GOALS,   HIL_PROGRESS),
        ("Agents",       AGENT_GOALS, AGENT_PROGRESS),
    ]:
        xml += '<tr>'
        xml += f'<td vertical-align="middle"><p align="center"><b>{label}</b></p></td>'
        xml += f'<td>{goals}</td>'
        xml += f'<td>{prog}</td>'
        xml += '</tr>'
    xml += '</tbody></table>'
    return xml


def get_table_block_id():
    import json, re
    r = subprocess.run(
        ["lark-cli", "docs", "+fetch",
         "--api-version", "v2",
         "--doc", DOC_TOKEN,
         "--detail", "with-ids",
         "--format", "json"],
        capture_output=True, text=True
    )
    d = json.loads(r.stdout)
    c = d.get("data", {}).get("document", {}).get("content", "")
    m = re.search(r'<table id="([^"]+)"', c)
    return m.group(1) if m else None


def main():
    tid = get_table_block_id()
    if not tid:
        print("FAILED to find table")
        return
    print(f"Table block: {tid}")

    body = build_table()
    print(f"Content length: {len(body)} chars")

    r = subprocess.run(
        ["lark-cli", "docs", "+update",
         "--api-version", "v2",
         "--doc", DOC_TOKEN,
         "--command", "block_replace",
         "--block-id", tid,
         "--content", body],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        print(f"REPLACE FAILED: {r.stderr[:500]}")
        return
    print("Done.")


if __name__ == "__main__":
    main()
