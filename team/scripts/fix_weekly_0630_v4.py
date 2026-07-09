#!/usr/bin/env python3
"""Fix weekly report: add 车型泛化 side front left finding + 复现率 Agent 6/30 progress."""
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

# 1. 车型泛化: add "定位 side front left 致车速慢、已反馈车端"
old1 = "8 个实验定位 camera 问题、需求已结，上传 calibration 塔包功能未通待平台打通。"
new1 = "8 个实验定位到 side front left camera 致车速慢、已反馈车端，需求已结；上传 calibration 塔包功能未通待平台打通。"

if old1 in content:
    print("[1] 车型泛化: replacing...")
    str_replace(old1, new1)
else:
    print("[1] 车型泛化: old text NOT found in doc!")

# Re-fetch
content = fetch()

# 2. 复现率 Agent: add 分合流/路口不跟导航/未及时变道
old2 = "生产验收复现正确率 89%；摆动复现 19/24（79%）。"
new2 = "生产验收复现正确率 89%；摆动复现 19/24（79%）；本周为分合流/路口不跟导航/未及时变道三类专项提供数据；Stage1 保存时效问题沿用 Stage2 方案解决。"

if old2 in content:
    print("[2] 复现率 Agent: replacing...")
    str_replace(old2, new2)
else:
    print("[2] 复现率 Agent: old text NOT found in doc!")

print("\nRunning check_report.py...")
subprocess.run(["python3", "/workspace/team/scripts/check_report.py", DOC, "--audience", "boss"])
