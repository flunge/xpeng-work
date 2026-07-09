#!/usr/bin/env python3
"""双周报逐条回源修复（受众=刘先明，周期6/18-6/30）：
删4个排除项(4728/182/620/召回10) + 旧数据(极速2.6×/尾部掉帧/一致性14%/近1500/1000工作台) +
脑补时态 + 黑话(塔包)。刘先明关注算法前沿→保留V3C/V3D/VAE蒸馏/Agent等技术细节。
"""
import subprocess, json

DOC = "A42GdtJGMopqqBxhF2McE7v7n8c"

def fetch():
    r=subprocess.run(["lark-cli","docs","+fetch","--doc",DOC,"--doc-format","markdown","--format","json"],
                    capture_output=True,text=True)
    return json.loads(r.stdout).get("data",{}).get("document",{}).get("content","")

def rep(old,new,label=""):
    r=subprocess.run(["lark-cli","docs","+update","--doc",DOC,"--command","str_replace",
                     "--doc-format","markdown","--pattern",old,"--content",new],
                    capture_output=True,text=True)
    out=json.loads(r.stdout) if r.stdout.strip() else {}
    ok=out.get("ok",False)
    print(f"  {label} ok={ok}"+("" if ok else f"  err={out.get('error',{}).get('message','')[:110]}"))
    return ok

# (old, new, label)。new为""即删除整句/整段。
fixes=[
 # T1: 极速2.6×是6/10旧数据 → 换双周窗口真实进展；删6/30整条(全是排除项4728/182/620)
 ("- 极速模式训练侧提速 2.6×（4h→1.5h），UCP 全链路约 100 分钟跑通；复现率 108 个 case 复现 80 个、按全量折损后约 50% 作为可用基线先行；6/26 对外交付文档完成。",
  "- 极速模式：UCP 全链路约 100 分钟跑通；复现率 108 个 case 复现 80 个、按全量折损后约 50% 作为可用基线先行；6/26 对外交付文档完成；仿真设置参数已精简至 1 个、后端改造本周四交付，自适应设置方案正在调研（涉及平台/扶摇/后端多方）。","T1-极速"),
 ("- **6/30 进展**：4728 项 case 完成首版截断、Stage2 仿真提效、截断前后指标稳定（撞车回退 5.8%→5.9%）；仿真先行 28 天评测 182 个模型，620 实测对比 610 走错路 1.0→1.7 次/百公里、异常减速 0.9→1.4。",
  "","T1-删排除项6/30"),
 # T2: 删斑马/pitch(非正式来源) + 塔包黑话 + 召回10/behavior(夏志勋评估组排除项)
 ("并联合算法定出三参数（车衣 / 摄像头外参 pitch+roll / 车型）敏感性扫描方案——已验证斑马车衣致车辆不加速、侧前 pitch 1° 即影响加减速与居中。6/30：车型泛化 8 个实验定位 camera 问题、需求已结但上传 calibration 塔包功能未通；红绿灯验证结论——3DGS 直出对变灯瞬间学不好、叠加 diffusion 后明显变好。6/30 metric 开发：新框架 behavior 层完成 7 项整理 + 合规类修复，导航类/合规类 KPI 召回提升 10+ 个百分点；安全类因移植未完成受阻、剩 3 个在做；争取 7/17 云端平台集成、7/14 与 7/24 DT 推 metric 上车。",
  "并联合算法制定三参数（车衣 / 摄像头外参 pitch+roll / 车型）敏感性扫描方案，量化各参数对车速与安全的影响。6/30：车型泛化 8 个实验定位到 side front left camera 致车速慢、已反馈车端、需求已结，上传车型标定文件的功能待平台打通；红绿灯验证——3DGS 直出对变灯瞬间学不好、叠加 diffusion 后明显变好。","T2-车型泛化去排除项/黑话/非正式"),
 # T3: 删"近1500"改1300+; 删一致性14%档(旧数据6/13); 删尾部掉帧(6/15旧); "1000工作台"说人话
 ("3 节点跑近 1500 条数据无中断；效率比 batch=20 为 1:2.82、batch≥30 达 1:2.5（达成月目标 1:3）；数据可用性 100%（5% 丢帧阈值，localpose UDP 阶段掉帧待网络层优化）。",
  "3 节点跑 1300+ scenario 无中断；效率比 batch=20 为 1:2.82、batch≥30 达 1:2.5（达成月目标 1:3）；数据可用性 100%（5% 丢帧阈值，localpose UDP 阶段掉帧待网络层优化）。","T3-1500→1300"),
 ("- 100 case × 5 次多轮一致性检测：优秀/良好档无显著随机性，14% 一般档需 PAT 评测确认影响，8 个最差档判为不可用、列入优化记录；PAT 评测链路已打通、跑通两版本模型对比。",
  "- PAT 评测链路已打通、跑通两版本模型对比。","T3-删旧一致性14%"),
 ("连续 case 尾部掉帧根因分析中。6/30：HIL 梳理 19 个事项、本周推进 12 项，5 节点上线运行、630 刷包 bug 已修；慢速模式合主线遇 FM 无输出/CI 耗时/万兆断连（版本差异工程问题），NVFixer 卡在平台 OSS→SAVE 拷贝排期。",
  "6/30：HIL 梳理 19 个事项、本周推进 12 项，5 节点上线运行、630 刷包 bug 已修；慢速模式代码与数据已就绪，卡在平台 OSS→SAVE 拷贝链路打通（待排期）。","T3-删尾部掉帧+去重"),
 ('🔴 6 月底"1000 工作台/天"目标未达（当前可用率 92%）；5080 台架预算月底到位，IT 采购 + 供应商交付预计延至 7 月底/8 月初，节点规模化是 Q3 关键瓶颈。',
  '🔴 6 月底"每天 1000 scenario 全跑"目标未达；5080 台架预算月底到位，IT 采购 + 供应商交付预计延至 7 月底/8 月初，节点规模化是 Q3 关键瓶颈。',"T3-1000工作台说人话"),
 ("**计划**：7 月底前用 5 台机器跑通问题、标准化操作系统镜像 ｜ NVFixer 接入 HIL 后慢速效率冲 1:8 ｜ 与评估组协同补齐 PAT metric。",
  "**计划**：7 月底前用 5 台机跑通并暴露问题、固化标准化部署流程 ｜ NVFixer 接入 HIL 后慢速效率冲 1:8 ｜ 与评估组协同补齐 PAT metric。","T3-计划去镜像黑话"),
]

c=fetch()
for old,new,label in fixes:
    if old in c:
        rep(old,new,label); c=fetch()
    else:
        print(f"  {label} NOT FOUND")

print("\ncheck (xianming):")
subprocess.run(["python3","/workspace/team/scripts/check_report.py",DOC,"--audience","xianming"])
