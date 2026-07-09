#!/usr/bin/env python3
"""双周报/周报 发布前全量体检（一条命令查完，取代"逐点自审"）。

沉淀自 2026-07-01：一份双周报改了 10 轮才到 80%，根因是我每轮只检查用户刚指出的那处、
改完就宣布"完成"，从不在交付前做全量自审。这个脚本把"要记住检查 N 件事"变成"跑一条命令"：
它模拟用户的挑剔眼光，把所有机械可查的维度一次跑完，任一红就 exit 非 0——不许在它绿之前说"完成"。

用法: python3 scripts/preflight.py <doc_token> [--audience xianming|boss] [--topics topic1,topic2,...]

查这些（机械、确定性）：
  1. 溯源闸    —— check_report.py（排除项/受众/内部代号/口头话/黑话/重复/溯源泄漏）
  2. 渲染闸    —— 重新生成每个 topic 图，几何自检文字溢出（gen_svg_infographic exit 3）
  3. 配图齐全  —— 文档里 whiteboard 块数 == topic 数（漏插/漏替换会被抓）
  4. 名字泄漏  —— 双周报正文不该出现组员名（owner 名单硬编码在此）
查不了的（判断类，脚本只提醒人工过）：数字是否与源一致、缩写是否真重构、术语取舍。
"""
import sys, os, json, subprocess, re

HERE = os.path.dirname(os.path.abspath(__file__))
# 双周报正文不该出现的组员名（团队架构图例外，正文/其余配图都要去）
OWNER_NAMES = ["杨星昊", "周蔚旭", "周冯", "朱啸峰", "瞿鑫宇", "裴健宏", "王禹丁",
               "吕文杰", "严潇竹", "樊世洲", "靳希睿", "李祉浚", "谷佳萱", "张振宇",
               "高晋之", "刘开拓", "郑丽娜", "韩阿东"]


def sh(args):
    return subprocess.run(args, capture_output=True, text=True)


def fetch_md(doc):
    r = sh(["lark-cli", "docs", "+fetch", "--api-version", "v2", "--doc", doc,
            "--doc-format", "markdown", "--format", "json"])
    try:
        return json.loads(r.stdout).get("data", {}).get("document", {}).get("content", "")
    except Exception:
        return ""


def main():
    if len(sys.argv) < 2:
        print("用法: preflight.py <doc_token> [--audience xianming|boss] [--topics t1,t2]")
        sys.exit(1)
    doc = sys.argv[1]
    aud = "xianming"
    if "--audience" in sys.argv:
        aud = sys.argv[sys.argv.index("--audience") + 1]
    topics = ["topic1", "topic2", "topic3", "topic4"]
    if "--topics" in sys.argv:
        topics = sys.argv[sys.argv.index("--topics") + 1].split(",")

    fails = []   # 硬失败（红）
    warns = []   # 人工复核（黄）

    # ── 1. 溯源闸 ──
    print("① 溯源闸 check_report.py …")
    r = sh(["python3", os.path.join(HERE, "check_report.py"), doc, "--audience", aud])
    print("  " + r.stdout.strip().replace("\n", "\n  "))
    if r.returncode != 0:
        fails.append("溯源闸未过（见上，逐条改到 check_report 绿）")

    # ── 2. 渲染闸（重新生成每个 topic，几何自检）──
    print(f"② 渲染闸 gen_svg_infographic.py（{len(topics)} 张）…")
    for t in topics:
        r = sh(["python3", os.path.join(HERE, "gen_svg_infographic.py"), t])
        line = (r.stdout + r.stderr).strip().split("\n")[-1] if (r.stdout or r.stderr) else ""
        print(f"  {t}: {line}")
        if r.returncode != 0:
            fails.append(f"渲染闸 {t} 溢出（修坐标/收窄 max_px/精简文案）")

    # ── 3. 配图齐全 ──
    md = fetch_md(doc)
    if md:
        wb = md.count("<whiteboard")
        n_topic = sum(1 for t in topics)
        # 双周报还有一张团队架构图，容忍 whiteboard 数 >= topic 数
        print(f"③ 配图齐全：文档 whiteboard 块 {wb} 个，topic {n_topic} 个")
        if wb < n_topic:
            fails.append(f"配图缺失：whiteboard {wb} < topic {n_topic}（有 topic 漏插图/漏替换）")
    else:
        warns.append("配图齐全：文档抓取为空，未能核对（检查 lark-cli 登录）")

    # ── 4. 名字泄漏（仅双周报 xianming）──
    if aud == "xianming" and md:
        # 去掉团队架构/组织架构那一段再查（那里本就该有名）
        body = re.sub(r"(团队|组织架构).{0,2000}", "", md, flags=re.S)
        hit = sorted({n for n in OWNER_NAMES if n in body})
        print(f"④ 名字泄漏：正文命中组员名 {hit if hit else '无'}")
        if hit:
            fails.append(f"双周报正文出现组员名 {hit}（正文+配图都要去，架构图除外）")

    # ── 人工复核提醒（脚本查不了的判断类）──
    warns.append("数字/结论是否与本周日报或嵌套文档一致？逐个回源指到原文（脚本查不了）")
    warns.append("每条是「重构」非「缩写」？读者不看源能懂「在解决什么问题」吗？")

    print("\n" + "=" * 48)
    if fails:
        print(f"🚫 PREFLIGHT 未过：{len(fails)} 项硬失败，禁止交付/宣布完成：")
        for f in fails:
            print("  ✗", f)
    else:
        print("✅ PREFLIGHT 机械闸全绿。")
    print(f"⚠️ 仍需人工复核 {len(warns)} 项（判断类，脚本兜不住）：")
    for w in warns:
        print("  ?", w)
    sys.exit(2 if fails else 0)


if __name__ == "__main__":
    main()
