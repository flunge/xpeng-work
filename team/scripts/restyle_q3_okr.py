#!/usr/bin/env python3
"""把 Q3 OKR 的 O/KR 表述改成 Q2 风格（范本 I9wCwVRFqiteBEkh3h1cXtibnDg）：
O = 【标题词】+强动词战略长句；KR = 加粗动词小标题 + 完整句 + 加粗数字。
实质内容/数字不变，只改措辞。逐个 block_replace（h3 标题 + 各 KR li）。
"""
import subprocess

DOC = "M8iUwlfAhi190Sk2xIwcHLAWn8f"

# (block_id, 新内容XML)
EDITS = [
    # ===== O1 场景产线 =====
    ("doxcnzFnlbXwuwyONZ7hKeD9Y7c",
     '<h3><b>O1：【规模化生产】打造按天可交付、能为发版把关的 3DGS 场景工业化产线，规模化支撑长里程与高价值 Corner Case 仿真验证</b></h3>'),
    ("doxcnGbfyoXrU7UW3lbxFsCfvMg",
     '<li><b>KR1：保障北上广深 RC 长里程的规模化高质量交付。</b> 打通标准化场景量产通道，累积里程由 Q2 末约 1wkm 扩至 <b>2wkm+</b>、日产稳定 <b>1000 case</b>，并攻坚大数据 35% 折损与卡池抢占，将全链路留存率由 <b>48.9% 提升至 75%</b>，稳定支撑 630 发版 gating。</li>'),
    ("doxcnYitJDGiJzHNDOOZfdi068e",
     '<li><b>KR2：将「1 小时极速验证」模式做成下游默认入口。</b> 依托 Feedforward 3DGS + Difix 底座把极速生产端到端压至 <b>100 分钟内</b>、复现率折损由 <b>30% 降至 15% 以内</b>，作为质量/海外/客诉团队默认通道（日均提交 <b>≥50 job</b>），与正常模式形成「先极速筛、再正常补」漏斗。</li>'),
    ("doxcnkocRuxbZz9p5S7l6ugslIf",
     '<li><b>KR3：攻坚高价值长尾场景（Corner Case）的自动化构建能力。</b> 场景编辑由 cut-in 扩展至切出/跟车/对向/靠边停车/VRU <b>≥5 类</b>，以规则+大模型自动生成轨迹、<b>月产 ≥100 case</b>，大幅提升主动安全/泊车等长尾场景的仿真评测覆盖度。</li>'),
    ("doxcnqEjIOsEv5VKb1hNxkTrYIc",
     '<li><b>KR4：建立自动化质检体系与生产看板，严控场景交付基线。</b> 将 golden testcase + CLIP-IQA + 自动化质检卡口接入产线，确保入库场景复现率达 <b>50%</b>、渲染通过率 <b>≥94%</b>，并建生产看板做数据丢失实时监控。</li>'),

    # ===== O2 SIL =====
    ("doxcnaMyQ8tkmpDRw8mFKODBRpb",
     '<h3><b>O2：【SIL 标准化】将 SIL 链路打造为 FM 发版的正式算法评测标准，攻坚渲染算法的效率与保真度双突破</b></h3>'),
    ("doxcnASVxFZWTH8h4aFeAy6in1b",
     '<li><b>KR1：突破 SIL 渲染底层性能瓶颈，强力支撑全量 gating 提效。</b> 落地 NVFixer 带 ref 新架构（V3C 全局 self-attention 拼接 ref+render latent <b>+8dB</b> / V3D VAE decoder 后注入 <b>+6dB</b>）的 64 卡全量训练，将渲染效率比由 <b>1:7.2 提至 1:5</b>、单帧压降至 <b>0.5 秒内</b>、H265 解码提效至 <b>1:2</b>，扫除全量 gating 集规模化运行的耗时障碍。</li>'),
    ("doxcnhD9Qt6gp5UB1BkIs93xuxg",
     '<li><b>KR2：建立 SIL 图像质量自动化卡口，严控评测输入。</b> 将 CLIP-IQA 接入 SIL 评测链路作为正式卡口，渲染瑕疵图像召回率达 <b>99%</b>、准确率由 <b>75% 提升至 90%</b>，不合格图像不进入评测，保障评测结论可信。</li>'),
    ("doxcn0eDGMI51b4jy3xf4TLzIKb",
     '<li><b>KR3：实现车型泛化常态化，支撑 630 多车型发版验证。</b> 打通多车型 Pipeline 并形成 daily 评测闭环，覆盖 <b>≥30 款</b>车型聚类、产出「哪些车型可共用一套 3DGS 参数」的规律，并将三参数（车衣/外参 pitch+roll/车型）敏感性结论交付研发。</li>'),
    ("doxcn0mcwzmE1plI3xP5jAiTwth",
     '<li><b>KR4：完成 RC 路线 SIL 验证的常态化运行与可信解读。</b> 在北上广深 1000km+ RC 路线 SIL 仿真上跑通 <b>10 个</b>核心闭环 metric、每日自动出报告、漏报率 <b>≤20%</b>，攻克 metric 阻塞，产出可解读的发版参考结论。</li>'),

    # ===== O3 HIL =====
    ("doxcntDQIl77sAbv5tDpWQSDW4c",
     '<h3><b>O3：【HIL 准出】将 HIL 链路绑定发版 gating 业务，做成模型上车前的最终把关手段</b></h3>'),
    ("doxcnR38f0tG3NIH3C7iXt968pd",
     '<li><b>KR1：把 HIL 闭环结论正式绑定到发版 gating 业务。</b> 将 HIL 评测纳入 <b>≥1 条</b>业务线（630 RC/园区）的发版准出流程，每个发版周期产出可对外的 HIL gating 报告，使仿真成为模型上车前不可绕过的最终关卡。</li>'),
    ("doxcn3SSRQFpkgRg0YX3SjrniUd",
     '<li><b>KR2：完成 HIL 链路的稳定运行与渐进式规模化。</b> 由 3 节点扩至 <b>5 台</b>（5080 台架到位）并向 <b>200+</b> 台架爬坡，保障 1000km+ RC 路线稳定运行无中断、系统可用率由 <b>92% 提升至 95%+</b>。</li>'),
    ("doxcnEJkpnhoGoGVwFyJRZ1tuCe",
     '<li><b>KR3：攻坚 HIL 高保真渲染与复现率，深挖实时性上限。</b> 实时模式效率比稳定 <b>1:3 以内</b>（已达 1:2.5）、慢速+NVFixer 模式 <b>1:8 以内</b>；综合复现率达 <b>80%</b>（纯 3DGS 50% / difix 60%），掉帧率由 <b>12% 降至 ≤2%</b>。</li>'),
    ("doxcnihDp3DvcGOIgGofAEPq89d",
     '<li><b>KR4：建立 HIL 与实车等效性验证卡口。</b> 跑通多轮一致性验证（<b>100 case×5 次</b> + PAT 评测），将不可用档（8 个最差）<b>清零</b>、一般档比例由 <b>14% 压至 5% 以内</b>，为数字化替代实车评测提供量化置信度。</li>'),

    # ===== O4 预研 & Agents =====
    ("doxcnsZOWl1508HzRS4ODnNnwbf",
     '<h3><b>O4：【预研与 Agents】预研下一代生成式仿真技术，并以 AI Agent 重塑研发·生产·评测全流程</b></h3>'),
    ("doxcnqGnJ9fNEv468Pj07C5fnFd",
     '<li><b>KR1：推动 AI Agent 全面落地并量化收益。</b> 复现率 Agent 由 <b>4 项</b>上线扩至 <b>12 专项</b>全覆盖、单专项人机一致率 <b>≥85%</b>，Diff Agent 覆盖 <b>≥8 个</b> metric、准确率 <b>≥80%</b>，并产出「节省人工 review 时间 <b>≥50%</b>」的量化收益报告。</li>'),
    ("doxcnS8Jki3IQ2NrWeSEItBkMxc",
     '<li><b>KR2：「更好」攻坚下一代 Diffusion 生成模型。</b> 在轻量化、多摄一致性、新视角生成上完成阶段性验证、给出 Q4 落地方案；并以 CCES 指标验证 World Model 作为泛化测试集的能力。</li>'),
    ("doxcnbwvLA5GoYiQXIAQt6aIdSh",
     '<li><b>KR3：「更快」探索 Feedforward 点云生成新路径。</b> 验证前馈式生成在 3DGS 生产链路的可行性、对比 3DGS 输入定方案，大幅缩减单场景 3D 重建耗时，提升生产自动化率。</li>'),
    ("doxcnaIftEhm3j2QA0yj1LWbOie",
     '<li><b>KR4：「交互+泛化」沉淀动态场景能力与泛化边界。</b> Smart Agent 打通动态场景交互（编辑+生产 / 实时规划+渲染）形成可复用能力；并明确基于 3DGS 的场景泛化（多天气/多城市）边界、产出 Q4 方向。</li>'),
]


def main():
    for bid, content in EDITS:
        r = subprocess.run(
            ["lark-cli", "docs", "+update", "--api-version", "v2",
             "--doc", DOC, "--command", "block_replace",
             "--block-id", bid, "--content", content],
            capture_output=True, text=True
        )
        ok = r.returncode == 0
        print(("OK  " if ok else "FAIL ") + bid + ("" if ok else " :: " + r.stderr[:200]))
        if not ok:
            return


if __name__ == "__main__":
    main()
