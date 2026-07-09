#!/usr/bin/env python3
"""按李坤 7 条红线重写 Q3 OKR（v2）。
真实基线（6/30）：RC 累积约 2000km；常规综合复现率 51.8%；极速相对 74%/折损 50%；留存率 48.9%。
红线：真实基线不抄目标值 / 不纳入上下游(只监控推动) / 不写不可控指标 / 数量非目标(能力为目标) /
      不写实验细节 / 写目的不写手段 / 复现率分常规+极速设目标。
"""
import subprocess

DOC = "M8iUwlfAhi190Sk2xIwcHLAWn8f"

EDITS = [
    # ===== O1 场景产线 =====
    ("doxcnzFnlbXwuwyONZ7hKeD9Y7c",
     '<h3><b>O1：【规模化生产】打造按天可交付、能为发版把关的 3DGS 场景工业化产线，规模化支撑长里程与高价值 Corner Case 仿真验证</b></h3>'),
    ("doxcnGbfyoXrU7UW3lbxFsCfvMg",
     '<li><b>KR1：扩大 RC 长里程的规模化产能与稳定交付。</b> 在 Q2 末累积约 2000km 的基础上，将北上广深 RC 路线累积里程提升至 <b>5000km+</b>、稳定日产能达 <b>100km/天</b>，渲染通过率保持 <b>≥94%</b>，稳定支撑 630 发版 gating。</li>'),
    ("doxcnYitJDGiJzHNDOOZfdi068e",
     '<li><b>KR2：建立 RC 路线全链路看板能力，闭环数据留存率。</b> 自建覆盖采集→预处理→生产→入库全链路的折损监控看板，定位每一环损失并推动上下游（大数据/平台/采集）整改，将全链路留存率由 <b>48.9% 提升至 75%+</b>。</li>'),
    ("doxcnkocRuxbZz9p5S7l6ugslIf",
     '<li><b>KR3：将「1 小时极速验证」做成可自助的下游敏捷迭代能力。</b> 把极速生产端到端压至 <b>100 分钟内</b>，简化交互让质量/海外/客诉团队可自助完成「生产→验证」闭环，极速模式复现率折损由 <b>30% 收敛至 15% 以内</b>。</li>'),
    ("doxcnqEjIOsEv5VKb1hNxkTrYIc",
     '<li><b>KR4：攻坚高价值 Corner Case 的自动化构建能力。</b> 场景编辑由 cut-in 扩展至切出/跟车/对向/靠边停车/VRU <b>≥5 类</b>，以规则+大模型实现轨迹自动生成、自动化率达 <b>80%+</b>（无需人工逐 case 调参），输出场景泛化可用率 <b>≥70%</b>，并以 golden testcase + 自动化质检卡口保障入库复现率达 <b>50%</b>。</li>'),

    # ===== O2 SIL =====
    ("doxcnaMyQ8tkmpDRw8mFKODBRpb",
     '<h3><b>O2：【SIL 标准化】将 SIL 链路打造为 FM 发版的正式算法评测标准，攻坚渲染效率、图像保真与复现率的全面突破</b></h3>'),
    ("doxcnASVxFZWTH8h4aFeAy6in1b",
     '<li><b>KR1：突破 SIL 渲染底层性能瓶颈，支撑全量 gating 提效。</b> 将带 ref 图渲染的单帧总耗时压降至 <b>0.5 秒内</b>（性能比由 <b>1:7.2 跃升至 1:5</b>）、H265 解码提效至 <b>1:2</b>，扫除全量 gating 集规模化运行的耗时障碍。</li>'),
    ("doxcnhD9Qt6gp5UB1BkIs93xuxg",
     '<li><b>KR2：建立 SIL 图像质量自动化卡口，严控评测输入可信度。</b> 对渲染瑕疵图像建立客观质量评价与自动筛选机制，瑕疵召回率达 <b>99%</b>、准确率由 <b>75% 提升至 90%</b>，不合格图像不进入评测，保障发版评测结论可信。</li>'),
    ("doxcn0eDGMI51b4jy3xf4TLzIKb",
     '<li><b>KR3：攻坚 SIL 渲染复现率，分场景设定可用基线。</b> 在 gating 数据集上，常规模式生产场景综合复现率由 <b>51.8% 提升至 65%+</b>、极速模式生产场景复现率达 <b>50%+</b>，使两类生产场景均达到可支撑发版评测的可用门槛。</li>'),
    ("doxcn0mcwzmE1plI3xP5jAiTwth",
     '<li><b>KR4：实现车型泛化常态化并完成 RC 路线 SIL 验证。</b> 打通多车型 Pipeline 形成 daily 评测闭环、支撑 630 多车型发版验证（覆盖 <b>≥30 款</b>车型、输出车型可共用参数的聚类规律）；在北上广深 1000km+ RC 路线上跑通 <b>10 个</b>核心闭环 metric、漏报率 <b>≤20%</b>，产出可解读的发版参考结论。</li>'),

    # ===== O3 HIL =====
    ("doxcntDQIl77sAbv5tDpWQSDW4c",
     '<h3><b>O3：【HIL 准出】将 HIL 链路绑定发版 gating 业务，做成模型上车前的最终把关手段</b></h3>'),
    ("doxcnR38f0tG3NIH3C7iXt968pd",
     '<li><b>KR1：把 HIL 闭环结论正式绑定到发版 gating 业务。</b> 将 HIL 评测纳入 <b>≥1 条</b>业务线（630 RC/园区）的发版准出流程，每个发版周期产出可对外的 HIL gating 报告，使仿真成为模型上车前不可绕过的最终关卡。</li>'),
    ("doxcn3SSRQFpkgRg0YX3SjrniUd",
     '<li><b>KR2：完成 HIL 链路的稳定运行与渐进式规模化。</b> 由当前 3 节点扩至 <b>5 台</b>台架、并向 <b>200+</b> 台架爬坡，保障 1000km+ RC 路线稳定运行无中断、系统可用率由 <b>92% 提升至 95%+</b>。</li>'),
    ("doxcnEJkpnhoGoGVwFyJRZ1tuCe",
     '<li><b>KR3：攻坚 HIL 高保真渲染与复现率，深挖实时性上限。</b> 实时模式效率比稳定 <b>1:3 以内</b>（当前已达 1:2.5）、慢速模式 <b>1:8 以内</b>；HIL 端综合复现率达 <b>80%</b>（纯 3DGS 场景 50%、difix 渲染场景 60%），掉帧率由 <b>12% 降至 ≤2%</b>。</li>'),
    ("doxcnihDp3DvcGOIgGofAEPq89d",
     '<li><b>KR4：建立 HIL 与实车等效性验证卡口。</b> 跑通多轮一致性验证（<b>100 case×5 次</b> + PAT 评测），将不可用档（当前 8 个最差）<b>清零</b>、需人工复核的一般档比例由 <b>14% 压至 5% 以内</b>，为数字化替代实车评测提供量化置信度。</li>'),

    # ===== O4 预研 & Agents =====
    ("doxcnsZOWl1508HzRS4ODnNnwbf",
     '<h3><b>O4：【预研与 Agents】预研下一代生成式仿真技术，并以 AI Agent 重塑研发·生产·评测全流程</b></h3>'),
    ("doxcnqGnJ9fNEv468Pj07C5fnFd",
     '<li><b>KR1：推动 AI Agent 全面落地并量化收益。</b> 复现率分析 Agent 由当前 <b>4 项</b>扩至 <b>12 专项</b>全覆盖、单专项人机一致率 <b>≥85%</b>，A/B 评测 Agent 覆盖 <b>≥8 个</b> metric、准确率 <b>≥80%</b>，并产出「节省人工 review 时间 <b>≥50%</b>」的量化收益结论。</li>'),
    ("doxcnS8Jki3IQ2NrWeSEItBkMxc",
     '<li><b>KR2：「更好」攻坚下一代生成式渲染模型。</b> 在轻量化、多摄一致性、新视角生成上完成阶段性验证、给出 Q4 落地方案，目标新视角泛化能力与直出画质相对当前显著提升。</li>'),
    ("doxcnbwvLA5GoYiQXIAQt6aIdSh",
     '<li><b>KR3：「更快」探索前馈式 3D 重建新路径。</b> 验证前馈式生成在 3DGS 生产链路的可行性、定输入方案，目标将单场景 3D 重建耗时较当前大幅缩减，显著提升生产自动化率。</li>'),
    ("doxcnaIftEhm3j2QA0yj1LWbOie",
     '<li><b>KR4：「交互+泛化」沉淀动态场景能力与泛化边界。</b> Smart Agent 打通动态场景交互（编辑+生产 / 实时规划+渲染）形成可复用能力；明确基于 3DGS 的场景泛化（多天气/多城市）能力边界、产出 Q4 方向。</li>'),
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
