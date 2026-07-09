#!/usr/bin/env python3
"""修正周报 0630：
1. 列宽改为 100/300/600
2. 首行首列粗体居中
3. 人名全部用 <cite type="user" user-id="ou_xxx" user-name="名字">
4. 移动到指定文件夹 JIb3ftcJclQ1DvdHFkIc6gxNnOb
"""

import subprocess
import json

DOC_TOKEN = "KtzLdBh3ToRFLYx5R66cpLiHnEk"
TABLE_BLOCK_ID = "doxcnnegyxXnFiclKTFshitKiYe"
TARGET_FOLDER = "JIb3ftcJclQ1DvdHFkIc6gxNnOb"

# user-id mapping
U = {
    "朱啸峰":   '<cite type="user" user-id="ou_09b6f76c8d98f186bb7163406fe3894a" user-name="朱啸峰"></cite>',
    "邓爽":     '<cite type="user" user-id="ou_0c29f42f96320d32e36b8616342955ef" user-name="邓爽"></cite>',
    "王禹丁":   '<cite type="user" user-id="ou_16ed70882e5f4247b330612054b07d3f" user-name="王禹丁"></cite>',
    "郑丽娜":   '<cite type="user" user-id="ou_279a0e5c146848e3d2dfaefe85f2c505" user-name="郑丽娜"></cite>',
    "樊世洲":   '<cite type="user" user-id="ou_41c1fbbdee2aa8ced7cbe495a0e4b9c3" user-name="樊世洲"></cite>',
    "夏志勋":   '<cite type="user" user-id="ou_4e4a0102b41b6feb1a7043ec45dfad40" user-name="夏志勋"></cite>',
    "刘开拓":   '<cite type="user" user-id="ou_5ff13a6d397bcb698bbfb66800fbb83a" user-name="刘开拓"></cite>',
    "靳希睿":   '<cite type="user" user-id="ou_6dbb165c2c7f4dd57532ffda75e51169" user-name="靳希睿"></cite>',
    "赖西湖":   '<cite type="user" user-id="ou_795c727d71c02a25501a3fd4d2af540c" user-name="赖西湖"></cite>',
    "严潇竹":   '<cite type="user" user-id="ou_9b65b8c67807ce544a5cef3efe5cbf8a" user-name="严潇竹"></cite>',
    "裴健宏":   '<cite type="user" user-id="ou_a76e6fffce1c513ed5b33555aec19076" user-name="裴健宏"></cite>',
    "云荟":     '<cite type="user" user-id="ou_ad1ca535c4cc2642eb850dc22b024e49" user-name="云荟"></cite>',
    "杨星昊":   '<cite type="user" user-id="ou_b41c33085d2e629fbdff0c555cae0a3f" user-name="杨星昊"></cite>',
    "周冯":     '<cite type="user" user-id="ou_c37bf637460fbc4d1dd53470ecae8889" user-name="周冯"></cite>',
    "周蔚旭":   '<cite type="user" user-id="ou_c9f3e88a0d6f949b332a40a155814e69" user-name="周蔚旭"></cite>',
    "吕文杰":   '<cite type="user" user-id="ou_e6eb2da48b30725b46c548a1bcbf3fc6" user-name="吕文杰"></cite>',
    "瞿鑫宇":   '<cite type="user" user-id="ou_f360c7cfbd4fcbdc624c012dc151c6a4" user-name="瞿鑫宇"></cite>',
    # 老板/上级不 @（按 SKILL.md 规则）
    # 高炳涛、徐林鵾、黄佰民、李坤、高晋之 等不写
}

# 月目标列保持原文
SCENE_GOALS = '''<checkbox done="false">【业务交付】【闭环场景】完成8类Q2的头部问题闭环场景集生产交付和上线；</checkbox><checkbox done="false">【业务交付】【RC产线】产出北上广深全量的RC路线。</checkbox><checkbox done="false">【业务交付】【RC产线】当前产能评估以及后续新数据上线以及产量爬升计划。</checkbox><checkbox done="true">【产线规模化】形成便捷的客户端极速生产+验证模式，前端支持特定客诉case的快速生产+仿真验证，全链路时延2h以内。</checkbox><checkbox done="false">【算法优化】静态GGS+WM一阶段demo形成下一步可执行的落地方案。</checkbox>'''

SIL_GOALS = '''<checkbox done="false">【业务交付】【车型泛化】实现车型泛化业务侧常态化使用，完成仿真daily评测的闭环。</checkbox><checkbox done="false">【业务交付】【RC路线仿真】完成北上广深的RC路线（1000+km）仿真以及一阶段闭环指标的验证。</checkbox><checkbox done="false">【算法优化】复现率gating数据集上复现率达成80%以上，效率达到1：25，渲染效率1：5。</checkbox><checkbox done="false">【算法优化】SIL链路评测接入CLIP-IQA图像质量校验，图像质量召回率99%/准确率95%。</checkbox>'''

HIL_GOALS = '''<checkbox done="false">【HIL链路】1000km+RC路线稳定运行无中断验证，闭环运行的结论稳定可对外输出，运行稳定性达到95%以上。</checkbox><checkbox done="false">【HIL效率】实时模式效率比在1：3以内，慢速模式+difix效率比在1：5以内。</checkbox><checkbox done="false">【HIL指标】阶段性验收报告带PAT评测</checkbox>'''

AGENT_GOALS = '''<checkbox done="false">【业务Agent】完整集成复现率agent进入到各需求环节，可以进行常态化问题分析和归因，各项指标的准确率达到80%以上。</checkbox><checkbox done="false">【代码Agent】Simworld仓库整理方案：630达到某个阶段性的工程优化指标</checkbox>'''


def cite(name):
    return U.get(name, name)


SCENE_PROGRESS = f'''<p><b>【业务交付】</b></p><ul><li>【闭环场景集生产】{cite("刘开拓")}<ul><li>进展：城区毕业率 87%（剩 5 项，1 项异常减速本周毕业、4 项不再跟踪），园区毕业率 69%（4 项延期，本周摆动+导航走错路毕业），Robotaxi 5 项延期（停车纵向/横向偏差/阻塞交通/违章停车）；7/3 两项新增毕业 metrics 已开发初版但 case 未测。</li><li>月目标 Gap：12 项本周存在无法完成风险，根因 IP 实车 case 模型旧+折损率高，{cite("杨星昊")} 修复，文康本周补票。</li></ul></li><li>【RC 路线】{cite("刘开拓")}{cite("郑丽娜")}<ul><li>进展：TC 已交付 968km/1750km（折损 30% 后目标），大数据 35% 折损 backfill 在重试；端午 {cite("云荟")} 协调 3DGS 私有卡池重产广州 184km subrun 完整数据，日产能目标 100km，目标 7/2 达 1000km；本周累计产出 478km 新数据。</li><li>新风险：AJS 长路线 20-30% 数据损失，初判 TC 采集软件抢占资源致数据损坏，{cite("刘开拓")} 出"一页纸"上升处理。</li></ul></li><li>【极速模式】{cite("周蔚旭")}<ul><li>进展：邓爽内部团队无诉求，海外/质量/外部团队有诉求；6/26 完成对外交付文档，7/2 完成操作便利性优化后正式对外开放；7/2 平台支持历史重复数据去重。</li><li>反馈：刘星昊生产未用待回访；性能提升（NVFixer/feedforward）已立项 Q3 排期。</li></ul></li></ul><p><b>【算法优化】</b></p><ul><li>【场景编辑】{cite("裴健宏")}<ul><li>进展：基于规则的轨迹自动生成增至 4 类（切入/切出/跟车/对向来车），跑通 25-30 个 case 测试；编辑车未渲染问题修复（兼容 3DGS 新旧两种配置）；Sensor Fusion topic 同步方案改为在 simulation 实现（减轻 ucp 链路负担）。</li><li>月目标 Gap：批量产出 case 月底前出第一批，Q3 与业务对齐场景集和使用方式。</li></ul></li><li>【新增视角 AVM 鱼眼】{cite("王禹丁")}<ul><li>进展：鱼眼 gsplat 改造完成环境构建、数据流程打通中（一阶段完成），后续训练链路排 Q3。</li></ul></li><li>【场景泛化 / 静态 GGS+WM】{cite("杨星昊")}{cite("靳希睿")}<ul><li>进展：Inspatio-world LoRA 微调 750 steps（700 clips），效果一般、模型 copy ref 偏强；本周修复多卡训练报错、cache latent 提速（32 卡半天可训 10 epoch），对比急速输入 vs 训练 200/500/1000 步、定一版输入。</li><li>月目标 Gap：输入选择（feedforward vs 3DGS）未定，效果尚未可用。</li></ul></li></ul>'''

SIL_PROGRESS = f'''<p><b>【业务交付】</b></p><ul><li>【车型泛化】{cite("杨星昊")}{cite("裴健宏")}<ul><li>进展：与 {cite("赖西湖")} cloudsim 全链路联调完成，多车型 Pipeline 6/23 上线，Moe 模型代码已全部合入、自测正常待发版；车型泛化周一（6/29）上线，开闭环已上线，存在交互小问题修复中。</li><li>新需求：找 10-30 款车型聚合规律，已拉小范围会（邀于亦奇/范博/DRE）；车衣实验完成（斑马车衣致减速、白色可达限速）。</li><li>月目标 Gap：daily 评测闭环未跑通，平台外部自助换 calibration/车衣/车型 Q3 推进。</li></ul></li><li>【RC 路线 SIL 验证】{cite("王禹丁")}{cite("夏志勋")}<ul><li>进展：DSOP 闭环 metric 因代码 RTM topic 格式变更读不到，确认"先框定 10 个 metric 用老框架跑起来"策略，{cite("夏志勋")} 根因修复中；{cite("朱啸峰")} 本周会出报告。</li><li>月目标 Gap：10 个 metric 起跑被阻塞，依赖根因修复。</li></ul></li></ul><p><b>【算法优化】</b></p><ul><li>【Fixer 渲染优化】{cite("周冯")}<ul><li>进展：simulation 仓库代码改完，本地编包测试 FM 轨迹评测通过，准备合入代码仓；tinyVAE 尝试发现 latent 空间与 cosmos 不一致拟蒸馏；带 ref 图新方案框架完成，ref encoding 放预处理链路，验证新方案收益中。</li><li>当前最优：NVFixer ref 新版本 TRT 渲染耗时 1:7.2（vs 未优化 1:6.5、Difix 1:17），PTQ 量化和算子融合已达天花板。</li><li>月目标 Gap：1:5 未达成。</li></ul></li><li>【CLIP-IQA】{cite("王禹丁")}<ul><li>进展：与 {cite("夏志勋")} 团队联调完成、预计周四上线；HIL 接入实时性问题（单帧 40ms、超 80ms 阈值）考虑异步/云上方案。</li><li>月目标 Gap：周四上线后才出指标，HIL 实时性方案待定。</li></ul></li></ul>'''

HIL_PROGRESS = f'''<p><b>【HIL 链路】</b></p><ul><li>【常规模式】{cite("朱啸峰")}<ul><li>进展：本周 PAT 链路恢复正常，节点稳定运行 1300+ scenarios，可用率 92%，metric 抽样符合预期；本周跑两版模型 PAT+蛇形画龙对比；004 节点完成离线渲染跑通，SRE 重启检查后推进 IT 镜像编译；005 接入机房；HIL 链路新增节点问题专项会（6/25）已开。初版报告已出。</li><li>月目标 Gap：可用率 92%，距 95% 与 1000km 全量稳定有差距；万兆网卡对比实验下周执行；XOS630 兼容性待验。</li></ul></li><li>【慢速模式】{cite("瞿鑫宇")}{cite("周冯")}<ul><li>进展：xos/perception_xp5/simulation 实车 DT 合入主线编包部署中、rebase 后回归测试；NVFixer Ref 慢速链路（H265→VAE encoder latent）代码适配 50%，今日给重刷耗时预估；适配 ceph 自动化下载解压 latent + 按 cam/timestamp 每帧自动复用；连续 case 尾部掉帧根因分析中（{cite("郑丽娜")} AI 分析，本周收尾目标）。</li><li>月目标 Gap：latent 方案适配仍在 50%，效率比未实测达标；尾部掉帧待解。</li></ul></li><li>【交付】{cite("郑丽娜")}<ul><li>新风险：交付组明日（6/30）开始试用评测准确度，评测结果查看易用性问题较多但不阻塞验证。SF 运行异常 VRU 缺失定位为 mflocalpose 字段缺失，已与 SF 同学确认填充字段、待实现。</li></ul></li></ul>'''

AGENT_PROGRESS = f'''<p><b>【业务 Agent】</b></p><ul><li>【复现率 Agent】{cite("吕文杰")}{cite("周蔚旭")}<ul><li>进展：本周道内画龙 80%+（22/27）满足上线标准；{cite("朱啸峰")} 给画龙数据后 {cite("吕文杰")} 已适配、调整主辅路分合流不跟导航绘图、回归完整数据集查误判；本周生产验收复现正确率 89%，涉碰撞 metric 用一段时间后再调整；6/29 异常减速/不减速优化基于试用反馈更新。</li><li>新要求：双周会反馈"AI agent 明确落地计划节点+量化收益"，需对齐管理层。</li></ul></li><li>【TopDiff / Diff Agent】{cite("严潇竹")}<ul><li>进展：每周支持新 metric 自动 edit review，目前已支持 6 个 metric 自动 diff，准确率 50%；主辅路/分合流未跟导航 50+ case 一致率 70%，进逆向车道旧数据过期重新准备，变道找不到空挡方案设计完成。</li><li>反馈：项目开发与使用脱节，要求协调"维持开发节奏 vs 开发急需新 metric"，确定反馈人；数据迭代提高准确率需提供报告证明。</li></ul></li><li>【Prompt 对齐 Agent】{cite("严潇竹")}{cite("吕文杰")}<ul><li>进展：准确率 85%、加时间戳定位问题，代码交给 {cite("吕文杰")} 部署；与刘星昊对齐"卡严/高准确率/允许漏报"新标准，等周五初版性能结论。</li></ul></li><li>【OnCall + 融合机器人】{cite("郑丽娜")}<ul><li>进展：目标 6/30 上线，链路打通处于能用状态，oncall 由晋之验证准确率，融合机器人灰度阶段；强调"机器人不能自己验收、要业务同学多使用"。</li></ul></li></ul><p><b>【算法 / 代码 Agent】</b></p><ul><li>【Simworld 仓库治理】{cite("杨星昊")}{cite("郑丽娜")}<ul><li>进展：6/22 要求"7 月解决严重问题、Q3 大调整、各组下周一前提交整改计划"；6/29 调整为"每周扫实际存在问题直接修改"（追求最佳性价比、不大规模改造代码框架）。</li></ul></li><li>【环境构建 Agent / Docker 自动化】<ul><li>进展：本周完成框架与工具自动化构建（dockerfile 跟随 simworld git、fuyao sleep job 进 shell 安装、按安装过程编写 dockerfile、whl 包管理）；Docker 环境构建打通 OSS 上传下载。</li></ul></li><li>【WM 内部探索】{cite("杨星昊")}{cite("靳希睿")}：Inspatio-world LoRA 微调持续中（同场景&生产）。</li></ul>'''


def build_table():
    """Build the table with 100/300/600 col widths and bold-centered header row + first col."""
    xml = '<table>'
    xml += '<colgroup><col width="100"/><col width="300"/><col width="600"/></colgroup>'
    xml += '<tbody>'

    # Header row (粗体居中)
    xml += '<tr>'
    xml += '<td vertical-align="middle"><p align="center"><b>链路</b></p></td>'
    xml += '<td vertical-align="middle"><p align="center"><b>月目标</b></p></td>'
    xml += '<td vertical-align="middle"><p align="center"><b>核心进展0624-0630</b></p></td>'
    xml += '</tr>'

    # Row: 场景&生产 (first col 粗体居中)
    xml += '<tr>'
    xml += '<td vertical-align="middle"><p align="center"><b>场景&amp;生产</b></p></td>'
    xml += f'<td>{SCENE_GOALS}</td>'
    xml += f'<td>{SCENE_PROGRESS}</td>'
    xml += '</tr>'

    # Row: SIL
    xml += '<tr>'
    xml += '<td vertical-align="middle"><p align="center"><b>SIL</b></p></td>'
    xml += f'<td>{SIL_GOALS}</td>'
    xml += f'<td>{SIL_PROGRESS}</td>'
    xml += '</tr>'

    # Row: HIL
    xml += '<tr>'
    xml += '<td vertical-align="middle"><p align="center"><b>HIL</b></p></td>'
    xml += f'<td>{HIL_GOALS}</td>'
    xml += f'<td>{HIL_PROGRESS}</td>'
    xml += '</tr>'

    # Row: Agents
    xml += '<tr>'
    xml += '<td vertical-align="middle"><p align="center"><b>Agents</b></p></td>'
    xml += f'<td>{AGENT_GOALS}</td>'
    xml += f'<td>{AGENT_PROGRESS}</td>'
    xml += '</tr>'

    xml += '</tbody></table>'
    return xml


def main():
    # 1. Replace the table block
    body = build_table()
    print(f"Content length: {len(body)} chars")

    result = subprocess.run(
        ["lark-cli", "docs", "+update",
         "--api-version", "v2",
         "--doc", DOC_TOKEN,
         "--command", "block_replace",
         "--block-id", TABLE_BLOCK_ID,
         "--content", body],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"REPLACE FAILED: {result.stderr[:500]}")
        return
    print("Table replaced.")

    # 2. Move to target folder
    result = subprocess.run(
        ["lark-cli", "drive", "+move",
         "--file-token", DOC_TOKEN,
         "--type", "docx",
         "--folder-token", TARGET_FOLDER,
         "--format", "json"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"MOVE attempt 1 FAILED: {result.stderr[:300]}")
        # Try alternative subcommand
        result2 = subprocess.run(
            ["lark-cli", "drive", "+move",
             "--token", DOC_TOKEN,
             "--folder-token", TARGET_FOLDER,
             "--format", "json"],
            capture_output=True, text=True
        )
        if result2.returncode != 0:
            print(f"MOVE attempt 2 FAILED: {result2.stderr[:300]}")
            print(f"stdout: {result2.stdout[:300]}")
            return
    print(f"Move result: {result.stdout[:300]}")


if __name__ == "__main__":
    main()
