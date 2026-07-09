#!/usr/bin/env python3
"""Fix HIL section: remove fabricated 一致性 data, fix 1000工作台 explanation, fix 计划 source."""
import subprocess, json

DOC = "KtzLdBh3ToRFLYx5R66cpLiHnEk"

def fetch():
    r = subprocess.run(
        ["lark-cli", "docs", "+fetch", "--doc", DOC, "--doc-format", "markdown", "--format", "json"],
        capture_output=True, text=True
    )
    d = json.loads(r.stdout)
    return d.get("data", {}).get("document", {}).get("content", "")

def str_replace(pattern, content):
    r = subprocess.run(
        ["lark-cli", "docs", "+update", "--doc", DOC,
         "--command", "str_replace",
         "--doc-format", "markdown",
         "--pattern", pattern,
         "--content", content],
        capture_output=True, text=True
    )
    out = json.loads(r.stdout) if r.stdout.strip() else {}
    ok = out.get("ok", False)
    print(f"  ok={ok}")
    if not ok:
        err = out.get("error", {}).get("message", r.stderr[:200])
        print(f"  error: {err}")
    return ok

content = fetch()

# 1. Fix the HIL 链路 进展 section — remove fabricated 一致性 bullet
old_hil = """- 进展
    - 阶段验收：5 节点机房部署可用、3 节点跑近 1500 条数据无中断；实时模式 batch≥30 效率比达 1:2.5（达月目标 1:3）、数据可用性 100%；PAT 评测链路已打通跑两版本对比。
    - 一致性：100 case×5 次——优良档无显著随机性，14% 一般需 PAT 确认、8 个最差判不可用已列优化。
    - 易用性：Cloudsim job 提交集成已上线、batchsize 默认 30。"""

new_hil = """- 进展
    - 阶段验收：5 节点机房部署可用、3 节点跑近 1500 条数据无中断；实时模式 batch≥30 效率比达 1:2.5（达月目标 1:3）、数据可用性 100%；PAT 评测链路已打通跑两版本对比。
    - 易用性：Cloudsim job 提交集成已上线、batchsize 默认 30。
    - 630 验证：刷包后功能异常修复（脚本 bug）、今晚出跑通结论。"""

if old_hil in content:
    print("[1] HIL 进展: removing fabricated 一致性, adding 630 actual progress...")
    str_replace(old_hil, new_hil)
else:
    print("[1] HIL old text not found, trying shorter match...")
    # try matching just the 一致性 line
    old_short = "一致性：100 case×5 次——优良档无显著随机性，14% 一般需 PAT 确认、8 个最差判不可用已列优化。"
    new_short = "630 验证：刷包后功能异常修复（脚本 bug）、今晚出跑通结论。"
    if old_short in content:
        print("[1b] Found short match, replacing...")
        str_replace(old_short, new_short)
    else:
        print("[1] BOTH patterns not found!")

# Re-fetch
content = fetch()

# 2. Fix "1000 工作台" → add context
old_risk = '6 月底"1000 工作台"目标未达'
new_risk = '6 月底"每天 1000 scenario 全跑起来"目标未达（来源：6/25 HIL 节点会）'

if old_risk in content:
    print("[2] 1000工作台: clarifying...")
    str_replace(old_risk, new_risk)
else:
    print("[2] old text not found!")

# Re-fetch
content = fetch()

# 3. Fix 计划 — source is 6/25 meeting goal
old_plan = "计划：7 月底前用 5 台机器跑通问题、拿回操作系统镜像制作标准化。"
new_plan = "计划：7 月底前 5 台机暴露问题并标准化流程（来源：6/25 节点会议 R3BzdeiFo...），保后续 30-40 台扩展。"

if old_plan in content:
    print("[3] 计划: adding source...")
    str_replace(old_plan, new_plan)
else:
    print("[3] old text not found!")

print("\nRunning check_report.py...")
subprocess.run(["python3", "/workspace/team/scripts/check_report.py", DOC, "--audience", "boss"])
