#!/usr/bin/env python3
"""Build weekly report 2026-06-30 (covers 0624-0630), preserving template structure
(4 rows × 3 cols: 链路 / 月目标 / 核心进展0624-0630), replacing the 'core progress' column only.

Sources:
- 6/24 茶水间 W0uXdVZqAo2GPsxAJxDcyAUrn8g (already read earlier)
- 6/25 核心日会 TUwpdyT3xohJ4bx3r6kcR2uVndd (read)
- 6/25 每日例会 BnvRd7LMqowxmOxjQQRcDzernhh (read)
- 6/26 核心日会 YMyudyWVRo1xgPxWBIPc4CjZnwe (read)
- 6/29 核心日会 SdULd0jepoNfVrxMbJJcHCkynjf (read earlier)
- W27 6/29 当日组员自填进展 (read)
- All project ledgers
"""

import subprocess
import json

TEMPLATE_DOC = "Ml9xdq2XDo4NsOxzOFycYdNAnnh"

# 月目标列保持与模板一致（来自 0617-0623 周报：4 大类）
# 用 checkbox 表示，与原文档格式保持一致

# ============ 场景&生产 月目标 ============
SCENE_GOALS = '''<checkbox done="false">【业务交付】【闭环场景】完成8类Q2的头部问题闭环场景集生产交付和上线；</checkbox><checkbox done="false">【业务交付】【RC产线】产出北上广深全量的RC路线。</checkbox><checkbox done="false">【业务交付】【RC产线】当前产能评估以及后续新数据上线以及产量爬升计划。</checkbox><checkbox done="true">【产线规模化】形成便捷的客户端极速生产+验证模式，前端支持特定客诉case的快速生产+仿真验证，全链路时延2h以内。</checkbox><checkbox done="false">【算法优化】静态GGS+WM一阶段demo形成下一步可执行的落地方案。</checkbox>'''

# ============ 场景&生产 核心进展 0624-0630 ============
SCENE_PROGRESS = '''<p><b>【业务交付】</b></p><ul><li>【闭环场景集生产】<ul><li>进展（6/29 核心日会）：城区毕业率 87%（剩 5 项，1 项异常减速本周毕业、4 项不再跟踪），园区毕业率 69%（4 项延期，本周摆动+导航走错路毕业），Robotaxi 5 项延期（停车纵向/横向偏差/阻塞交通/违章停车），7/3 两项新增毕业 metrics 已开发初版但 case 未测。</li><li>月目标 Gap：12 项本周存在无法完成风险，根因 IP 实车 case 模型旧+折损率高，星昊/雪智修复，文康本周补票。</li></ul></li><li>【RC 路线】<ul><li>进展：6/25 同步 TC 已交付 968km/1750km（折损 30% 后目标），大数据 35% 折损 backfill 在重试；端午广州重产 184km subrun 完整数据，云荟协调 3DGS 私有卡池日产能 100km，目标 7/2 达 1000km。本周（6/24-6/27）累计产出 478km 新数据，截至 6/29 W27 周一日产无风险。</li><li>新风险（6/29）：AJS 长路线数据采集 20-30% 损失，初判 TC 采集软件抢占资源致数据损坏，开拓出"一页纸"高炳涛找学渊处理。</li><li>月目标 Gap：广州为主，北上深+产量爬升与卡池稳定性待收尾。</li></ul></li><li>【极速模式】<ul><li>进展：邓爽内部团队无诉求，外部团队（海外/质量/邵晴）有诉求；6/26 完成对外交付文档，7/2 完成操作便利性优化后正式对外开放；7/2 平台支持历史重复数据去重。</li><li>新增反馈（6/24 茶水间）：刘星昊生产未用，海外可能在用、明日回访；性能提升是否同步推 NVFixer/feedforward 已立项 Q3 排期。</li></ul></li></ul><p><b>【算法优化】</b></p><ul><li>【场景编辑】<ul><li>进展：基于规则的轨迹自动生成增至 4 类（切入/切出/跟车/对向来车），跑通 25-30 个 case 测试；编辑车未渲染问题修复（兼容 3DGS 新旧两种配置）；Sensor Fusion topic 同步方案改为在 simulation 实现（减轻 ucp 链路负担）。</li><li>月目标 Gap：批量产出 case 月底前出第一批，Q3 与业务对齐场景集和使用方式。</li></ul></li><li>【新增视角 AVM 鱼眼】<ul><li>进展：鱼眼 gsplat 改造完成环境构建、数据流程打通中（一阶段完成），后续训练链路排 Q3。</li></ul></li><li>【场景泛化 / 静态 GGS+WM】<ul><li>进展：Inspatio-world LoRA 微调端午约 750 steps（700 clips），效果一般、模型 copy ref 偏强；本周修复多卡训练报错、用 cache latent 提速（32 卡半天可训 10 epoch），对比急速输入 vs 训练 200/500/1000 步、定一版输入。</li><li>月目标 Gap：输入选择（feedforward vs 3DGS）未定，效果尚未可用。</li></ul></li></ul>'''

# ============ SIL 月目标 ============
SIL_GOALS = '''<checkbox done="false">【业务交付】【车型泛化】实现车型泛化业务侧常态化使用，完成仿真daily评测的闭环。</checkbox><checkbox done="false">【业务交付】【RC路线仿真】完成北上广深的RC路线（1000+km）仿真以及一阶段闭环指标的验证。</checkbox><checkbox done="false">【算法优化】复现率gating数据集上复现率达成80%以上，效率达到1：25，渲染效率1：5。</checkbox><checkbox done="false">【算法优化】SIL链路评测接入CLIP-IQA图像质量校验，图像质量召回率99%/准确率95%。</checkbox>'''

# ============ SIL 核心进展 ============
SIL_PROGRESS = '''<p><b>【业务交付】</b></p><ul><li>【车型泛化】<ul><li>进展：cloudsim 全链路联调完成，多车型 Pipeline 6/23 上线，Moe 模型代码已全部合入、自测正常，待发版；车型泛化周一（6/29）上线，开闭环已上线，存在交互小问题正在修复（裴健宏、杨星昊已测）。</li><li>新需求（6/22 高炳涛+6/24 茶水间）：找 10-30 款车型聚合规律，已拉小范围会（邀于亦奇/范博/DRE）讨论；车衣实验（纯色 vs 斑马）已完成，验证斑马车衣会让车减速、白色车衣可达限速。</li><li>月目标 Gap：daily 评测闭环未跑通，平台开放外部自助换 calibration/车衣/车型功能 Q3 推进。</li></ul></li><li>【RC 路线 SIL 验证】<ul><li>进展：DSOP 闭环 metric 因代码 RTM topic 格式变更读不到，6/24 茶水间确认"先框定 10 个 metric 用老框架跑起来"策略，志勋根因修复中；啸峰本周会出报告。</li><li>月目标 Gap：10 个 metric 起跑被阻塞，依赖夏志勋修复。</li></ul></li></ul><p><b>【算法优化】</b></p><ul><li>【Fixer 渲染优化】<ul><li>进展（6/25 例会）：周冯改完 simulation 仓库代码，本地编包测试 FM 轨迹评测通过，准备合入代码仓；tinyVAE 尝试发现 latent 空间与 cosmos 不一致拟蒸馏（自 VAE 当 teacher、one 翻译 VAE 当 student）；Here 带 ref 图新方案框架完成，ref encoding 放预处理链路，明日验证新方案收益。</li><li>当前最优：NVFixer ref 新版本 TRT 渲染耗时 1:7.2（vs 未优化 1:6.5、Difix 1:17），PTQ 量化和算子融合已达天花板，FMHA 已是上限。</li><li>月目标 Gap：1:5 未达成。</li></ul></li><li>【CLIP-IQA】<ul><li>进展：CLIP-IQA 与志勋团队联调完成、预计周四上线；HIL 接入实时性问题（单帧 40ms、超 80ms 阈值）考虑异步/云上方案；HIL 链路接入前期评估与王禹丁对接（无 ref 图情况）。</li><li>月目标 Gap：周四上线后才出指标，HIL 实时性方案待定。</li></ul></li></ul>'''

# ============ HIL 月目标 ============
HIL_GOALS = '''<checkbox done="false">【HIL链路】1000km+RC路线稳定运行无中断验证，闭环运行的结论稳定可对外输出，运行稳定性达到95%以上。</checkbox><checkbox done="false">【HIL效率】实时模式效率比在1：3以内，慢速模式+difix效率比在1：5以内。</checkbox><checkbox done="false">【HIL指标】阶段性验收报告带PAT评测</checkbox>'''

# ============ HIL 核心进展 ============
HIL_PROGRESS = '''<p><b>【HIL 链路】</b></p><ul><li>【常规模式】<ul><li>进展：本周 PAT 链路恢复正常，节点稳定运行 1300+ scenarios，可用率 92%，metric 抽样符合预期；本周（6/25）跑两版模型 PAT+蛇形画龙对比；004 节点完成离线渲染跑通（6/25）、SRE 重启检查后推进给 IT 镜像编译；005 接入机房（6/25）；HIL 链路新增节点问题专项会（6/25 15:09）已开。</li><li>初版报告（6/25 当日）已出，啸峰更新 1300 scenarios 性能指标呈现给爽。</li><li>月目标 Gap：可用率 92%，距 95% 与 1000km 全量稳定有差距；万兆网卡对比实验下周执行；XOS630 兼容性待验。</li></ul></li><li>【慢速模式】<ul><li>进展：xos/perception_xp5/simulation 实车 DT 合入主线编包部署中、rebase 后回归测试；NVFixer Ref 慢速链路（H265→VAE encoder latent）代码适配 50%，今日给重刷耗时预估；适配 ceph 自动化下载解压 latent + 按 cam/timestamp 每帧自动复用；连续 case 尾部掉帧根因分析中（郑丽娜 AI 分析，本周收尾目标）。</li><li>月目标 Gap：latent 方案适配仍在 50%，效率比未实测达标；尾部掉帧待解。</li></ul></li><li>【上下游与交付】<ul><li>新风险（6/29 W27 周一）：交付组明日（6/30）开始试用评测准确度，评测结果查看易用性问题较多但不阻塞验证。</li><li>SF 运行异常 VRU 缺失定位为 mflocalpose 字段缺失，已与 SF 同学确认填充字段、待实现。</li></ul></li></ul>'''

# ============ Agents 月目标 ============
AGENT_GOALS = '''<checkbox done="false">【业务Agent】完整集成复现率agent进入到各需求环节，可以进行常态化问题分析和归因，各项指标的准确率达到80%以上。</checkbox><checkbox done="false">【代码Agent】Simworld仓库整理方案：630达到某个阶段性的工程优化指标</checkbox>'''

# ============ Agents 核心进展 ============
AGENT_PROGRESS = '''<p><b>【业务 Agent】</b></p><ul><li>【复现率 Agent】<ul><li>进展：本周道内画龙 80%+（22/27）满足上线标准；6/27 啸峰给画龙数据后吕文杰已适配、调整主辅路分合流不跟导航绘图、回归完整数据集查误判；周蔚旭本周生产验收复现正确率 89%，涉碰撞 metric 用一段时间后再调整；6/29 W27 异常减速/不减速优化基于试用反馈更新。</li><li>新风险（6/22 高炳涛）：双周会要求"AI agent 明确落地计划节点+量化收益"，需对齐管理层。</li></ul></li><li>【TopDiff / Diff Agent】<ul><li>进展（6/26 核心日会）：每周支持新 metric 自动 edit review，目前已支持 6 个 metric 自动 diff，准确率 50%；6/29 W27 主辅路/分合流未跟导航 50+ case 一致率 70%，进逆向车道旧数据过期重新准备，变道找不到空挡方案设计完成。</li><li>新要求（6/26 高炳涛）：项目开发与使用脱节，要求张振宇协调"维持开发节奏 vs 开发急需新 metric"，确定反馈人；数据迭代提高准确率需提供报告证明。</li></ul></li><li>【Prompt 对齐 Agent】<ul><li>进展（6/25 例会）：准确率 85%、加时间戳定位问题，代码交给文杰部署；6/26 与刘星昊对齐"卡严/高准确率/允许漏报"新标准，等周五初版性能结论。</li></ul></li><li>【OnCall + 融合机器人】<ul><li>进展（6/26）：目标 6/30 上线，链路打通处于能用状态，oncall 由晋之验证准确率，融合机器人灰度阶段、由薛栋+冠秋查看；高炳涛强调"机器人不能自己验收、要业务同学多使用"。</li></ul></li></ul><p><b>【算法 / 代码 Agent】</b></p><ul><li>【Simworld 仓库治理】<ul><li>进展（6/22+6/29 调整）：高炳涛 6/22 要求"7 月解决严重问题、Q3 大调整、各组下周一前提交整改计划"；6/29 调整为"每周扫实际存在问题直接修改"（高炳涛+黄佰民确认"追求最佳性价比、不大规模改造代码框架"）。</li></ul></li><li>【环境构建 Agent / Docker 自动化】<ul><li>进展：本周完成框架与工具自动化构建（dockerfile 跟随 simworld git、fuyao sleep job 进 shell 安装、按安装过程编写 dockerfile、whl 包管理）；Docker 环境构建打通 OSS 上传下载。</li></ul></li><li>【WM 内部探索】Inspatio-world LoRA 微调持续中（同场景&生产）。</li></ul>'''


def build_table():
    """Build the complete weekly report XML body."""
    xml = '<table><colgroup><col/><col/><col/></colgroup><tbody>'

    # Header row
    xml += '<tr><td vertical-align="middle"><b>链路</b></td>'
    xml += '<td vertical-align="middle"><b>月目标</b></td>'
    xml += '<td><b>核心进展0624-0630</b></td></tr>'

    # Row 1: 场景&生产
    xml += f'<tr><td vertical-align="middle"><b>场景&amp;生产</b></td>'
    xml += f'<td>{SCENE_GOALS}</td>'
    xml += f'<td>{SCENE_PROGRESS}</td></tr>'

    # Row 2: SIL
    xml += f'<tr><td vertical-align="middle"><b>SIL</b></td>'
    xml += f'<td>{SIL_GOALS}</td>'
    xml += f'<td>{SIL_PROGRESS}</td></tr>'

    # Row 3: HIL
    xml += f'<tr><td vertical-align="middle"><b>HIL</b></td>'
    xml += f'<td>{HIL_GOALS}</td>'
    xml += f'<td>{HIL_PROGRESS}</td></tr>'

    # Row 4: Agents
    xml += f'<tr><td vertical-align="middle"><b>Agents</b></td>'
    xml += f'<td>{AGENT_GOALS}</td>'
    xml += f'<td>{AGENT_PROGRESS}</td></tr>'

    xml += '</tbody></table>'
    return xml


def main():
    title = "周报 2026-06-30"
    body = build_table()

    full_content = f'<title>{title}</title>{body}'

    print(f"Content length: {len(full_content)} chars")

    # Create new doc
    result = subprocess.run(
        ["lark-cli", "docs", "+create",
         "--api-version", "v2",
         "--content", full_content,
         "--format", "json"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"FAILED: {result.stderr[:500]}")
        return

    data = json.loads(result.stdout)
    doc_data = data.get("data", {}).get("document", {})
    new_token = doc_data.get("document_id") or doc_data.get("token") or doc_data.get("obj_token")
    print(f"OK - new doc token: {new_token}")
    print(f"Full response: {json.dumps(data, ensure_ascii=False)[:500]}")


if __name__ == "__main__":
    main()
