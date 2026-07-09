#!/usr/bin/env python3
"""整表重建周报：4 行全部按统一结构（进展/现状/风险/计划，无则省、多则子bullet）。
应用全部规则：删预研类(静态GGS+WM)、删非本组(开环/截断/仿真盘/metric开发)、去流水账、
时间默认本周不标日期、owner 准、一事一子bullet。月目标列不变。"""
import subprocess, json, re

DOC="KtzLdBh3ToRFLYx5R66cpLiHnEk"

U={
 "朱啸峰":'<cite type="user" user-id="ou_09b6f76c8d98f186bb7163406fe3894a" user-name="朱啸峰"></cite>',
 "邓爽":'<cite type="user" user-id="ou_0c29f42f96320d32e36b8616342955ef" user-name="邓爽"></cite>',
 "王禹丁":'<cite type="user" user-id="ou_16ed70882e5f4247b330612054b07d3f" user-name="王禹丁"></cite>',
 "郑丽娜":'<cite type="user" user-id="ou_279a0e5c146848e3d2dfaefe85f2c505" user-name="郑丽娜"></cite>',
 "樊世洲":'<cite type="user" user-id="ou_41c1fbbdee2aa8ced7cbe495a0e4b9c3" user-name="樊世洲"></cite>',
 "夏志勋":'<cite type="user" user-id="ou_4e4a0102b41b6feb1a7043ec45dfad40" user-name="夏志勋"></cite>',
 "刘开拓":'<cite type="user" user-id="ou_5ff13a6d397bcb698bbfb66800fbb83a" user-name="刘开拓"></cite>',
 "靳希睿":'<cite type="user" user-id="ou_6dbb165c2c7f4dd57532ffda75e51169" user-name="靳希睿"></cite>',
 "严潇竹":'<cite type="user" user-id="ou_9b65b8c67807ce544a5cef3efe5cbf8a" user-name="严潇竹"></cite>',
 "裴健宏":'<cite type="user" user-id="ou_a76e6fffce1c513ed5b33555aec19076" user-name="裴健宏"></cite>',
 "云荟":'<cite type="user" user-id="ou_ad1ca535c4cc2642eb850dc22b024e49" user-name="云荟"></cite>',
 "杨星昊":'<cite type="user" user-id="ou_b41c33085d2e629fbdff0c555cae0a3f" user-name="杨星昊"></cite>',
 "周冯":'<cite type="user" user-id="ou_c37bf637460fbc4d1dd53470ecae8889" user-name="周冯"></cite>',
 "周蔚旭":'<cite type="user" user-id="ou_c9f3e88a0d6f949b332a40a155814e69" user-name="周蔚旭"></cite>',
 "吕文杰":'<cite type="user" user-id="ou_e6eb2da48b30725b46c548a1bcbf3fc6" user-name="吕文杰"></cite>',
 "瞿鑫宇":'<cite type="user" user-id="ou_f360c7cfbd4fcbdc624c012dc151c6a4" user-name="瞿鑫宇"></cite>',
}
def u(n): return U.get(n,n)

# 月目标列（保持原值）
SCENE_GOALS='<checkbox done="false">【业务交付】【闭环场景】完成8类Q2的头部问题闭环场景集生产交付和上线；</checkbox><checkbox done="false">【业务交付】【RC产线】产出北上广深全量的RC路线。</checkbox><checkbox done="false">【业务交付】【RC产线】当前产能评估以及后续新数据上线以及产量爬升计划。</checkbox><checkbox done="true">【产线规模化】形成便捷的客户端极速生产+验证模式，前端支持特定客诉case的快速生产+仿真验证，全链路时延2h以内。</checkbox>'
SIL_GOALS='<checkbox done="false">【业务交付】【车型泛化】实现车型泛化业务侧常态化使用，完成仿真daily评测的闭环。</checkbox><checkbox done="false">【业务交付】【RC路线仿真】完成北上广深的RC路线（1000+km）仿真以及一阶段闭环指标的验证。</checkbox><checkbox done="false">【算法优化】复现率gating数据集上复现率达成80%以上，效率达到1：25，渲染效率1：5。</checkbox><checkbox done="false">【算法优化】SIL链路评测接入CLIP-IQA图像质量校验，图像质量召回率99%/准确率95%。</checkbox>'
HIL_GOALS='<checkbox done="false">【HIL链路】1000km+RC路线稳定运行无中断验证，闭环运行的结论稳定可对外输出，运行稳定性达到95%以上。</checkbox><checkbox done="false">【HIL效率】实时模式效率比在1：3以内，慢速模式+difix效率比在1：5以内。</checkbox><checkbox done="false">【HIL指标】阶段性验收报告带PAT评测</checkbox>'
AGENT_GOALS='<checkbox done="false">【业务Agent】完整集成复现率agent进入到各需求环节，可以进行常态化问题分析和归因，各项指标的准确率达到80%以上。</checkbox><checkbox done="false">【代码Agent】Simworld仓库整理方案：630达到某个阶段性的工程优化指标</checkbox>'

# ===== 进展列：统一结构，去流水账，删预研/非本组 =====
SCENE=f'''<p><b>【闭环场景集】</b>{u("刘开拓")}</p><ul><li>现状：本组负责闭环 P0 场景集生产与复现，12 类 P0 累计完成约 90%、持续补充闭环 case；园区走错路专项闭环 case 生产推进中。</li><li>风险：对外毕业受闭环 metric 可用性制约（评估组依赖），非本组生产环节问题。</li></ul><p><b>【RC 长里程】</b>{u("刘开拓")}{u("郑丽娜")}</p><ul><li>进展<ul><li>数据产能：新数据累计 561.5km；undistort 多进程 timeout 已修，公共卡池被高优场景集抢占、日产难稳定保 100km；7/1 用新老数据混合先凑 1000km 供各链路仿真。</li><li>RC 采集：TC 7/1 确认可用车辆与采集恢复时间。</li><li>数据折损：Event 数据回传丢失已拉通 TC+数据闭环部，7/2 出分析结论。</li><li>长里程看板：计划 7/13 上线，本周组内先预埋 pose 文件提取。</li></ul></li><li>风险：全链路留存率偏低（48.9%），折损根因（大数据 35%+卡池抢占+AJS 采集 20-30% 损坏）均在上下游，本组以看板监控+推动整改，已申请提升公共卡池优先级。</li></ul><p><b>【极速模式】</b>{u("周蔚旭")}</p><ul><li>进展：仿真参数已降至 1 个、准备提 MR；后端改造本周四交付；下一步改自适应设置、计划下周上线。</li><li>现状：已对质量+海外 Moe 用户开放，对外交付文档已交付；复现率上限受 feedforward 效果制约，优化排 Q3。</li></ul><p><b>【场景编辑】</b>{u("裴健宏")}</p><ul><li>进展：规则轨迹自动生成增至 4 类（切入/切出/跟车/对向车），编辑车未渲染问题修复（兼容新旧 3DGS 配置）；3dgs/simulation 编辑数据同步开发中（约 40%）。</li><li>现状：UCP 单次编辑约 4 分钟，瓶颈在模型/DDS 上传下载。</li></ul>'''

SIL=f'''<p><b>【车型泛化】</b>{u("杨星昊")}{u("裴健宏")}</p><ul><li>现状：多车型 Pipeline 已上线 Cloudsim、Moe 模型自测正常待发版；8 个实验定位 camera 问题、需求已结，上传 calibration 塔包功能未通待平台打通。</li><li>进展：红绿灯验证——3DGS 直出对变灯瞬间学不好，叠加 diffusion 后明显变好。</li><li>计划：新同学接入推进，聚类与三参数（车衣/外参/车型）敏感性结论交付研发。</li></ul><p><b>【车衣验证】</b>{u("杨星昊")}{u("王禹丁")}</p><ul><li>进展：已验证斑马车衣致车辆不加速、白色车衣可达限速；侧前 pitch 1° 即影响加减速与居中。</li><li>计划：泛化多种车衣样式纳入验证集，避免测试车/量产车差异。</li></ul><p><b>【RC 路线 SIL 验证】</b>{u("王禹丁")}</p><ul><li>现状：基于 1300+ scenarios 出初版报告；采用"先 10 metric 用老框架跑起来"策略。</li><li>风险：DSOP 闭环 metric 因 RTM topic 格式变更读不到，10 metric 起跑被阻塞、依赖评估组根因修复。</li></ul><p><b>【Fixer 渲染优化】</b>{u("周冯")}</p><ul><li>现状：NVFixer 带 ref 新版 TRT 渲染效率比 1:7.2（vs 未优化 1:6.5、Difix 1:17），TRT 与 PyTorch 输出对齐、FM 评测一致。</li><li>风险：PTQ 量化敏感层溢出、算子融合 FMHA 已到天花板，1:5 目标难达。</li><li>计划：转向 TinyVAE/LightVAE 蒸馏；HIL Nvfixer ref 新方案（VAE encoder 放预处理、复用 ref latent）PPU 环境适配中。</li></ul><p><b>【CLIP-IQA】</b>{u("王禹丁")}</p><ul><li>进展：与 {u("夏志勋")} 团队联调完成、已上线，过滤极差 case 验证有效。</li><li>风险：HIL 接入实时性（单帧 40ms/2.7G 超 80ms 阈值），方案改异步/云上待定。</li></ul>'''

HIL=f'''<p><b>【HIL 链路】</b>{u("朱啸峰")}</p><ul><li>进展<ul><li>阶段验收：5 节点机房部署可用、3 节点跑近 1500 条数据无中断；实时模式 batch≥30 效率比达 1:2.5（达月目标 1:3）、数据可用性 100%；PAT 评测链路已打通跑两版本对比。</li><li>一致性：100 case×5 次——优良档无显著随机性，14% 一般需 PAT 确认、8 个最差判不可用已列优化。</li><li>易用性：Cloudsim job 提交集成已上线、batchsize 默认 30。</li></ul></li><li>风险：6 月底"1000 工作台"目标未达；5080 预算月底到位、IT 采购+交付预计 7 月底/8 月初，节点规模化是 Q3 瓶颈；004 节点网络配置待与 SRE 标准化。</li><li>计划：7 月底前用 5 台机器跑通问题、拿回操作系统镜像制作标准化。</li></ul><p><b>【慢速模式】</b>{u("瞿鑫宇")}{u("周冯")}</p><ul><li>现状：NVFixer Ref 慢速链路（H265→VAE encoder latent）代码适配 50%、已给重刷耗时预估；连续 case 尾部掉帧根因分析中（{u("郑丽娜")} 收尾）。</li><li>风险：合主线遇 FM 无输出/CI 耗时/万兆断连（版本差异工程问题）；NVFixer 卡平台 OSS→SAVE 拷贝排期。</li></ul><p><b>【交付与下游】</b>{u("郑丽娜")}</p><ul><li>进展：交付组本周开始试用评测准确度；review agent demo（针对化隆）可对两版本特定指标出静态质检报告。</li><li>计划：待 {u("邓爽")} 定优先级后与 {u("夏志勋")} metric 计划协同推进。</li></ul>'''

AGENT=f'''<p><b>【复现率 Agent】</b>{u("吕文杰")}{u("周蔚旭")}</p><ul><li>进展：新增 7 类问题场景、累计支持 11 类；道内画龙测试集准确率 80%+ 达上线标准；生产验收复现正确率 89%；摆动复现 19/24（79%）。</li><li>现状：未完成类——危险变道/绕行 24 case（调试不收敛）、不居中/贴边 14、撞路沿/障碍物 12、未及时变道 10。</li><li>风险：双周会要求"AI agent 明确落地节点+量化收益"，本周未显式输出、需主动对齐。</li></ul><p><b>【Diff / TopDiff Agent】</b>{u("严潇竹")}</p><ul><li>进展：支持 6 个 metric 自动 diff（准确率 50%）；道内画龙 Topdiff 7/11 正确上报、与人工一致率 64%；主辅路/分合流未跟导航 50+ case 一致率 70%。</li><li>风险：开发与使用脱节，需协调"维持开发节奏 vs 开发急需新 metric"、确定反馈人。</li></ul><p><b>【Prompt 对齐 Agent】</b>{u("严潇竹")}</p><ul><li>进展：提示词开关+飞书机器人 HTML 输出已解决，73 case 中 54 可比、人工一致率 85%；与刘星昊对齐"卡严/高准确率/允许漏报"标准。</li><li>计划：二次分级确认可行，{u("郑丽娜")} 组织生产同学试用推广。</li></ul><p><b>【OnCall+融合机器人 / AB Review】</b>{u("郑丽娜")}</p><ul><li>进展：oncall+融合机器人本周上线（晋之验证准确率、灰度中）；AB Review review agent demo 可对两版本指标出静态质检报告。</li><li>计划：3DGS 生产 OnCall Agent 规范日志落盘 OSS→自动诊断→报告→对比。</li></ul><p><b>【代码治理 / 环境构建 Agent】</b>{u("杨星昊")}{u("王禹丁")}</p><ul><li>进展：代码治理策略转向"每周扫实际问题直接修"（不大规模改造框架）；车型适配 Agent 已上线；环境构建 Agent 打通"base image→自动产 Dockerfile"。</li></ul>'''


def build_table():
    rows=[("场景&amp;生产",SCENE_GOALS,SCENE),("SIL",SIL_GOALS,SIL),("HIL",HIL_GOALS,HIL),("Agents",AGENT_GOALS,AGENT)]
    xml='<table><colgroup><col width="100"/><col width="300"/><col width="600"/></colgroup><tbody>'
    xml+='<tr><td vertical-align="middle"><p align="center"><b>链路</b></p></td><td vertical-align="middle"><p align="center"><b>月目标</b></p></td><td vertical-align="middle"><p align="center"><b>核心进展0624-0630</b></p></td></tr>'
    for label,goals,prog in rows:
        xml+=f'<tr><td vertical-align="middle"><p align="center"><b>{label}</b></p></td><td>{goals}</td><td>{prog}</td></tr>'
    xml+='</tbody></table>'
    return xml


def main():
    r=subprocess.run(["lark-cli","docs","+fetch","--api-version","v2","--doc",DOC,"--detail","with-ids","--format","json"],capture_output=True,text=True)
    c=json.loads(r.stdout)["data"]["document"]["content"]
    tid=re.search(r'<table id="([^"]+)"',c).group(1)
    print("table:",tid)
    body=build_table()
    print("len:",len(body))
    r=subprocess.run(["lark-cli","docs","+update","--api-version","v2","--doc",DOC,"--command","block_replace","--block-id",tid,"--content",body],capture_output=True,text=True)
    print("OK" if r.returncode==0 else "FAIL "+r.stderr[:300])


if __name__=="__main__":
    main()
