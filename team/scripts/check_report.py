#!/usr/bin/env python3
"""周报/双周报确定性校验：扫文档内容，抓出 manifest 排除项、受众违规、流水账特征、脑补职责词。
用法: python3 check_report.py <doc_token> [--audience boss|xianming]
不改文档，只报告问题清单。把"靠自觉判断"变成"机器拦截"。
"""
import sys, json, subprocess, re

# manifest 明确排除的内容（出现即报错）
EXCLUDE = {
    # 只抓"毕业率/毕业百分比"这类开环指标；"闭环 case/闭环生产"是本组、不命中
    "开环毕业率（非本组，只做闭环）": [r"毕业率", r"毕业\s*\d+\s*[%个]", r"城区.{0,4}毕业.{0,4}\d", r"园区.{0,4}毕业.{0,4}\d"],
    "case 截断（评估/生产侧）": [r"4728", r"case.*?截断", r"截断.*?case"],
    "仿真先行整体盘/模型评测数（邓爽部门）": [r"评测.*?\d+\s*个模型", r"182\s*个模型", r"仿真先行整体"],
    "620 实测/620 vs 610（部门盘，非本组成果）": [r"620.{0,8}610", r"走错路.{0,6}1\.7", r"620 实测"],
    "metric 开发当成本组成果（夏志勋评估组）": [r"召回提升 10", r"behavior 层完成 \d+ 项", r"新框架 behavior"],
}

# 受众违规：报告里不该写汇报对象自己做的事
AUDIENCE_BAD = {
    "boss": [r"高炳涛找", r"高炳涛 找", r"由高炳涛", r"高炳涛.{0,4}拉通", r"高炳涛.{0,4}对齐"],
    "xianming": [r"刘先明找", r"刘先明 安排", r"由刘先明"],
}

# 流水账特征：罗列每天干了啥（多个 6/xx 日期堆在一条里）
FLOW = r"6/2\d.{0,40}6/2\d"

# 脑补职责高风险词（需人工确认是否有源）
ROLE_GUESS = [r"补票", r"派活"]

# 废话括号：过程八卦
GOSSIP = [r"与高炳涛对齐后", r"（\d+/\d+ 与.{0,6}对齐）"]

# 🔴 内部溯源标注泄漏：报告正文不该出现给"我自己看"的溯源（token/会议日期+token）
# 溯源是写之前自己要做到的，不是糊进给老板看的正文
SOURCE_LEAK = [
    r"来源[：:].{0,30}[0-9A-Za-z]{8,}",        # "来源：... <token>"
    r"（来源[：:]",                              # "（来源："
    r"[A-Za-z0-9]{6,}\.\.\.",                  # 截断 token "R3BzdeiFo..."
    r"6/2\d.{0,6}节点会",                       # "6/25 节点会" 这类会议指代
    r"来源[：:].{0,4}\d+/\d+",                   # "来源：6/25"
]

# 🔴 内部黑话/词salad：只抓"我自创/过度精简的口语指代"。
# ⚠️ 行业/内部通用术语（CCES/gating/metric/feedforward/ref latent/VAE/difix/NVFixer/UCP/PAT/
#    方差筛选/双向聚类/ablation/定量回归 等）刘先明都懂——不报，过度翻译反丢专业度（2026-07-01 定）。
JARGON = [r"塔包", r"expand 框架", r"三参数敏感性", r"工作台(?!.{0,8}（)", r"老框架跑起来"]

# 🔴🔴 溯源闸（2026-07-01 沉淀，治"省10min/V3C/口头话冒充成果"——这些正则天生抓不到"没溯源"，
#    但能抓到"没溯源"最典型的两类字面痕迹）：
# A) 内部实验代号 / 内部消融指标：外部领导不知道、也不该知道，对外只讲结果
EXP_CODE = [
    r"V\d[A-Z]\b",          # V3C / V3D 架构实验编号
    r"\+\s*\d+\s*dB",       # +8dB 内部消融增益
    r"EXP[_\s]?\d",         # EXP_5 实验编号
    r"Holmes\s*格式",       # 未落地的 PPU 专用格式设想
]
# B) 口头话 / 未落地标记：带这些字样的"成果"多半来自茶水间聊天、不是日报量化结论
HEARSAY = [
    r"预估.{0,6}省", r"预估快", r"省\s*\d+\s*min",   # "预估省 10min" / "省 10min"
    r"预估.{0,4}测试中", r"后续(编译|再)",           # 未来设想当成果（"测试中"单独出现是合法进展描述、不抓，只抓"预估…测试中"这种口头成果）
]

# 🔴 易重复的特征短语：这些如果在同一份报告出现 >=2 次，几乎必是"现状/风险写重了"。
# 只放"具体到一件事"的短语（泛词如"排期"不放，会误伤）。发现新的重复模式往这里加。
DUP_PHRASES = ["OSS→SAVE 拷贝", "OSS→ceph 拷贝", "万兆断连", "undistort", "dpvo"]


def fetch(doc):
    r = subprocess.run(["lark-cli","docs","+fetch","--api-version","v2","--doc",doc,
                        "--doc-format","markdown","--format","json"],capture_output=True,text=True)
    return json.loads(r.stdout).get("data",{}).get("document",{}).get("content","")


def scan(c, audience):
    issues=[]
    for label,pats in EXCLUDE.items():
        for p in pats:
            m=re.search(p,c)
            if m: issues.append(("排除项", label, m.group(0)[:30])); break
    for p in AUDIENCE_BAD.get(audience,[]):
        m=re.search(p,c)
        if m: issues.append(("受众违规", f"写了汇报对象({audience})自己做的事", m.group(0)[:30]))
    for m in re.finditer(FLOW,c):
        issues.append(("流水账", "一条里堆多个日期(罗列每天)", m.group(0)[:40])); break
    for p in ROLE_GUESS:
        m=re.search(p,c)
        if m: issues.append(("职责存疑", "高风险脑补词,核对是否有源", m.group(0)[:20]))
    for p in GOSSIP:
        m=re.search(p,c)
        if m: issues.append(("废话括号", "过程八卦,删", m.group(0)[:24]))
    for p in SOURCE_LEAK:
        m=re.search(p,c)
        if m: issues.append(("溯源泄漏", "内部溯源标注写进了正文,删(溯源是自己做,不给老板看)", m.group(0)[:30])); break
    # 内部黑话/词salad：每个命中都报（这些是"连懂行的也得猜"的词，应说人话）
    for p in JARGON:
        m=re.search(p,c)
        if m: issues.append(("黑话词salad", "内部黑话/口语指代,说人话或加括号解释", m.group(0)[:24]))
    # 🔴🔴 溯源闸 A：内部实验代号/消融指标写进对外正文
    for p in EXP_CODE:
        m=re.search(p,c)
        if m: issues.append(("溯源闸·内部代号", "内部实验代号/消融指标,对外只讲结果不写代号", m.group(0)[:24]))
    # 🔴🔴 溯源闸 B：口头预估/未落地当成果
    for p in HEARSAY:
        m=re.search(p,c)
        if m: issues.append(("溯源闸·口头话", "口头预估/未落地(预估/测试中/后续),不是日报量化结论,删或换成果数据", m.group(0)[:24]))
    # 🔴 同项目内 现状/风险/进展 重复：抽每个 bullet 的"特征短语"，跨 bullet 撞了=冗余
    # (沉淀自 2026-06-30 慢速模式"OSS→SAVE 拷贝"同时出现在现状和风险)
    for phrase in DUP_PHRASES:
        if c.count(phrase)>=2:
            issues.append(("内容重复", "同一事实写进多个 bullet(现状/风险/进展),合并", phrase[:24]))
    return issues


def main():
    if len(sys.argv)<2:
        print("用法: check_report.py <doc_token> [--audience boss|xianming]"); sys.exit(1)
    doc=sys.argv[1]
    aud="boss"
    if "--audience" in sys.argv:
        aud=sys.argv[sys.argv.index("--audience")+1]
    c=fetch(doc)
    issues=scan(c,aud)
    if not issues:
        print(f"✅ 校验通过（受众={aud}），无排除项/受众违规/流水账/脑补/废话")
        sys.exit(0)
    print(f"🚫 校验发现 {len(issues)} 个问题（受众={aud}）：")
    for typ,label,evid in issues:
        print(f"  [{typ}] {label} —— 命中：{evid}")
    sys.exit(2)


if __name__=="__main__":
    main()
