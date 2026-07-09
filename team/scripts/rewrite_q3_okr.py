#!/usr/bin/env python3
"""重写 Q3 OKR（M8iUwlfAhi190Sk2xIwcHLAWn8f）。
按李坤框架：O1 场景产线 / O2 SIL / O3 HIL（绑发版gating）/ O4 预研&Agents。
基于 Q2 末实际 ledger 进展，O 振奋人心、每条 KR 三要素+数字量化。
用 block_replace 替换原 4 个 h3。
"""
import subprocess

DOC = "M8iUwlfAhi190Sk2xIwcHLAWn8f"

# 原 4 个 h3 block id（按文档顺序）
BLOCKS = {
    "O1": "doxcnFpsH9wpmaakAdqHsgVPY3f",
    "O2": "doxcnMwvABjcH3Qrf2Gh8PHQFDc",
    "O3": "doxcnRYJexdz6QP8Qimk0iepx7d",
    "O4": "doxcnMsCuNPtpNMj6w6aLnZ0b7d",
}

# 每个 O = h3 标题 + 若干 KR bullet
NEW = {
    # ===== O1 场景产线 =====
    "O1": '''<h3>O1 场景产线：把仿真场景做成"按天可交付、能给发版把关"的工业化产线</h3>
<ul>
<li>KR1【长里程量产】北上广深 RC 路线累积里程从 Q2 末约 1wkm 扩到 2wkm+、日产稳定 1000 case，全链路留存率从 48.9% 提到 75%（修复大数据 35% 折损 + 卡池抢占），稳定支撑 630 发版 gating。</li>
<li>KR2【1 小时极速模式】极速生产端到端压到 100 分钟内、复现率折损从 30% 降到 15% 以内，作为质量/海外/客诉团队默认入口，日均提交 ≥50 job，与正常模式形成"先极速筛、再正常补"的漏斗。</li>
<li>KR3【高价值 CornerCase 量产】场景编辑从 cut-in 扩到切出/跟车/对向/靠边停车/VRU ≥5 类，规则+大模型自动生成轨迹、月产 ≥100 case，覆盖主动安全/泊车高价值场景。</li>
<li>KR4【质检 gating 体系】golden testcase + CLIP-IQA + 自动化质检卡口接入产线，入库场景复现率达 50%、渲染通过率 ≥94%，并建生产看板做数据丢失监控。</li>
</ul>''',

    # ===== O2 SIL =====
    "O2": '''<h3>O2 SIL：让 SIL 成为 FM 发版的正式算法评测标准，渲染又快又真</h3>
<ul>
<li>KR1【渲染算法提速】NVFixer 带 ref 新架构（V3C 全局 self-attention 拼接 ref+render latent +8dB / V3D VAE decoder 后注入 +6dB）64 卡全量训练落地，渲染效率比从 1:7.2 提到 1:5、单帧 0.5s 内、H265 解码 1:2，支撑全量 gating 集在可接受时延内跑通。</li>
<li>KR2【图像质检卡口】CLIP-IQA 接入 SIL 评测链路并作为正式卡口，渲染瑕疵图像召回率 99%、准确率从 75% 提到 90%，不合格图像不进入评测。</li>
<li>KR3【车型泛化常态化】多车型 Pipeline 支撑 630 多车型发版验证，覆盖 ≥30 款车型聚类、输出"哪些车型可共用一套 3DGS 参数"的规律，三参数（车衣/外参 pitch+roll/车型）敏感性结论交付研发，闭环 daily 评测跑通。</li>
<li>KR4【RC 路线 SIL 验证】北上广深 1000km+ RC 路线 SIL 仿真 + 10 个核心闭环 metric 每日自动出报告、漏报率 ≤20%，解决 metric 阻塞、产出可解读的发版参考结论。</li>
</ul>''',

    # ===== O3 HIL（绑定发版 gating 业务） =====
    "O3": '''<h3>O3 HIL：绑定发版 gating 业务，做成模型上车前的最后一道关</h3>
<ul>
<li>KR1【绑定发版 gating 业务】HIL 闭环结论正式纳入 ≥1 条业务线（630 RC/园区）的发版准出流程，每个发版周期产出可对外的 HIL gating 报告，成为模型上车前的最终把关手段。</li>
<li>KR2【链路稳定性 + 规模】3 节点扩到 5 台（5080 台架到位）、再向 200+ 台架爬坡，1000km+ RC 路线稳定运行无中断、可用率从 92% 提到 95%+。</li>
<li>KR3【渲染效率 + 复现率】实时模式效率比稳定 1:3 以内（已达 1:2.5）、慢速+NVFixer 模式 1:8 以内；综合复现率达 80%（纯 3DGS 50% / difix 60%），掉帧率从 12% 降到 ≤2%。</li>
<li>KR4【等效性卡口】HIL 与实车一致性验证卡口跑通（100 case×5 多轮一致性 + PAT 评测），8 个最差档不可用项清零、一般档比例从 14% 压到 5% 以内。</li>
</ul>''',

    # ===== O4 预研 & Agents =====
    "O4": '''<h3>O4 预研 &amp; Agents：用生成式新技术 + AI Agent 重塑研发·生产·评测流</h3>
<ul>
<li>KR1【AI Agent 落地 + 量化收益】复现率 Agent 从 4 项上线扩到 12 专项全覆盖、单专项人机一致率 ≥85%，Diff Agent 覆盖 ≥8 个 metric 准确率 ≥80%，并产出"节省人工 review 时间 ≥50%"的量化收益报告。</li>
<li>KR2【"更好"Diffusion】下一代生成式渲染新模型在轻量化、多摄一致性、新视角生成上完成阶段性验证，给 Q4 落地方案；World Model 用 CCES 指标证明可作泛化测试集能力。</li>
<li>KR3【"更快"Feedforward】Feedforward 重建提速进生产验证、对比 3DGS 输入定方案，大幅缩减单场景重建耗时，提升生产自动化率。</li>
<li>KR4【"交互+泛化"】Smart Agent 动态场景交互（编辑+生产 / 实时规划+渲染）形成可复用能力；基于 3DGS 的场景泛化（多天气/多城市）边界明确，出 Q4 方向。</li>
</ul>''',
}


def main():
    for key in ["O1", "O2", "O3", "O4"]:
        bid = BLOCKS[key]
        content = NEW[key]
        r = subprocess.run(
            ["lark-cli", "docs", "+update", "--api-version", "v2",
             "--doc", DOC, "--command", "block_replace",
             "--block-id", bid, "--content", content],
            capture_output=True, text=True
        )
        if r.returncode != 0:
            print(f"{key} FAILED: {r.stderr[:300]}")
            return
        print(f"{key} OK")


if __name__ == "__main__":
    main()
