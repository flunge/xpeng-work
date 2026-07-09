#!/usr/bin/env python3
"""V7 修复：1) 车型泛化计划说人话 2) 10 metric 说人话 3) 删正文里的内部溯源标注。"""
import subprocess, json

DOC = "KtzLdBh3ToRFLYx5R66cpLiHnEk"

def fetch():
    r = subprocess.run(
        ["lark-cli", "docs", "+fetch", "--doc", DOC, "--doc-format", "markdown", "--format", "json"],
        capture_output=True, text=True
    )
    return json.loads(r.stdout).get("data", {}).get("document", {}).get("content", "")

def rep(pattern, content):
    r = subprocess.run(
        ["lark-cli", "docs", "+update", "--doc", DOC,
         "--command", "str_replace", "--doc-format", "markdown",
         "--pattern", pattern, "--content", content],
        capture_output=True, text=True
    )
    out = json.loads(r.stdout) if r.stdout.strip() else {}
    ok = out.get("ok", False)
    print(f"  ok={ok}" + ("" if ok else f"  err={out.get('error',{}).get('message','')[:120]}"))
    return ok

fixes = [
    # 1. 车型泛化 计划：说人话
    ("计划：新同学接入推进，聚类与三参数（车衣/外参/车型）敏感性结论交付研发。",
     "计划：新同学接入；按车衣、摄像头外参、车型三个维度做参数扫描，量化各参数对车速与安全的影响，并对多款车型聚类找共性规律，交付研发。"),
    # 2. RC SIL 10 metric：说人话
    ('现状：基于 1300+ scenarios 出初版报告；采用"先 10 metric 用老框架跑起来"策略。',
     "现状：基于 1300+ scenarios 出初版报告；因逐个开发 metric 太慢（一周一个、70+ 个需一年半），改为复用旧 expand 框架、按优先级一次批量跑通 10 个 metric。"),
    # 3a. 删 HIL 风险里的内部溯源标注
    ('6 月底"每天 1000 scenario 全跑起来"目标未达（来源：6/25 HIL 节点会）',
     '6 月底"每天 1000 scenario 全跑"目标未达'),
    # 3b. 删 HIL 计划里的内部溯源标注 + token
    ("计划：7 月底前 5 台机暴露问题并标准化流程（来源：6/25 节点会议 R3BzdeiFo...），保后续 30-40 台扩展。",
     "计划：7 月底前用 5 台机跑通并暴露问题、固化标准化部署流程，为后续 30-40 节点扩展铺路。"),
]

content = fetch()
for i, (old, new) in enumerate(fixes, 1):
    if old in content:
        print(f"[{i}] replacing...")
        rep(old, new)
        content = fetch()
    else:
        print(f"[{i}] NOT FOUND: {old[:40]}...")

print("\ncheck_report.py:")
subprocess.run(["python3", "/workspace/team/scripts/check_report.py", DOC, "--audience", "boss"])
