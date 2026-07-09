#!/usr/bin/env python3
"""统一精简偏长 KR：一句话讲清结果+数字，去解释性长句，目标 ~50-80 字。
只改 >110 字的；短的保留。用各自当前真实 id 替换。"""
import subprocess

DOC = "M8iUwlfAhi190Sk2xIwcHLAWn8f"

# id -> 精简后内容
EDITS = {
    # O1
    "doxcnZZNc1bLV0txpBptPlvxtpc":
        '<li><b>KR1：扩大 RC 长里程产能与稳定交付。</b> 累积里程由 Q2 末约 2000km 提升至 <b>5000km+</b>、日产能 <b>100km/天</b>、渲染通过率 <b>≥94%</b>，支撑 630 发版 gating。</li>',
    "doxcnIQJNTeCgxKFKFm07wycBjc":
        '<li><b>KR2：建 RC 全链路看板，闭环数据留存率。</b> 自建采集→生产→入库全链路折损监控、推动上下游整改，留存率由 <b>48.9% 提升至 75%+</b>。</li>',
    "doxcnhi9hGEFCywkU9ttVYTkxjh":
        '<li><b>KR3：极速验证模式做成下游可自助。</b> 极速生产端到端压至 <b>100 分钟内</b>、复现率折损由 <b>30% 收敛至 15% 以内</b>，质量/海外/客诉团队自助闭环。</li>',
    "doxcng7YW7tagCRjuf7uwqcalJe":
        '<li><b>KR4：高价值 Corner Case 自动化构建。</b> 场景编辑扩至 <b>≥5 类</b>（切入/切出/跟车/对向/靠边停车/VRU）、自动化率 <b>80%+</b>、泛化可用率 <b>≥70%</b>，入库复现率 <b>50%</b>。</li>',
    # O2
    "doxcnPPVFR12hAtVXwLg4f1XzNc":
        '<li><b>KR1：突破 SIL 渲染性能瓶颈。</b> 带 ref 图单帧渲染压至 <b>0.5 秒内</b>（性能比 <b>1:7.2→1:5</b>）、H265 解码 <b>1:2</b>，支撑全量 gating 提效。</li>',
    "doxcnRweWKgdntOOfv83wj9refe":
        '<li><b>KR2：建 SIL 图像质量自动化卡口。</b> 渲染瑕疵召回率 <b>99%</b>、准确率 <b>75%→90%</b>，不合格图像不进评测，保障结论可信。</li>',
    "doxcnClbddAwvtBB618z1h8FVfh":
        '<li><b>KR3：攻坚 SIL 复现率，分场景设目标。</b> gating 数据集上常规模式 <b>51.8%→65%+</b>、极速模式 <b>50%+</b>，两类生产场景均达可用门槛。</li>',
    # O2-KR4 已是 96 字，保留不动
    # O3
    "doxcnRy8qOGgxfmT7PdJJ4Vfb9g":
        '<li><b>KR1：HIL 闭环结论绑定发版 gating 业务。</b> 纳入 <b>≥1 条</b>业务线（630 RC/园区）发版准出，每个发版周期产出可对外 HIL gating 报告。</li>',
    "doxcnOKB0W6TdLOTB22b5iFh3Ke":
        '<li><b>KR2：HIL 稳定规模化 + RC 路线常态化验证。</b> 由 3 节点扩至 <b>5 台</b>、向 <b>200+</b> 爬坡，1000km+ RC 稳定运行、可用率 <b>92%→95%+</b>、跑通 <b>10 个</b>闭环 metric、漏报率 <b>≤20%</b>（RC 验证 Q3 统一在 HIL 做）。</li>',
    "doxcnZJPZGOeADq4IQ4qZh4VQUc":
        '<li><b>KR3：攻坚 HIL 渲染效率与复现率。</b> 实时模式 <b>1:3 以内</b>（已达 1:2.5）、慢速 <b>1:8 以内</b>；综合复现率 <b>80%</b>（纯 3DGS 50%/difix 60%）、掉帧率 <b>12%→≤2%</b>。</li>',
    "doxcndVm6k4eSn7pGgUdQFTW3Jb":
        '<li><b>KR4：建 HIL 与实车等效性卡口。</b> 多轮一致性（<b>100 case×5</b> + PAT）将不可用档 <b>清零</b>、需人工复核档 <b>14%→5% 以内</b>，支撑数字化替代实车。</li>',
    # O4
    "doxcnhjzhHbiKg2sNROygzE2TTh":
        '<li><b>KR1：AI Agent 全面落地并量化收益。</b> 复现率 Agent 由 <b>4 项</b>扩至 <b>12 专项</b>（一致率 ≥85%）、Diff Agent 覆盖 <b>≥8 metric</b>（准确率 ≥80%），产出节省人工 review <b>≥50%</b> 的收益结论。</li>',
    "doxcnstdcmu5KlRITQb8HfN55Bf":
        '<li><b>KR4：「交互+泛化」沉淀动态场景与泛化能力。</b> Smart Agent 打通动态场景交互（编辑+生产/实时规划+渲染）形成可复用能力，明确 3DGS 场景泛化（多天气/多城市）边界、出 Q4 方向。</li>',
    # O4-KR2(81)/KR3(86) 已较短，保留
}


def main():
    for bid, content in EDITS.items():
        r = subprocess.run(
            ["lark-cli", "docs", "+update", "--api-version", "v2", "--doc", DOC,
             "--command", "block_replace", "--block-id", bid, "--content", content],
            capture_output=True, text=True)
        print(("OK  " if r.returncode == 0 else "FAIL ") + bid + ("" if r.returncode == 0 else " " + r.stderr[:120]))


if __name__ == "__main__":
    main()
