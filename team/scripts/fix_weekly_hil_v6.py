#!/usr/bin/env python3
"""Fix HIL: 1500 → 1300+ (actual source number)."""
import subprocess, json

DOC = "KtzLdBh3ToRFLYx5R66cpLiHnEk"

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

# Fix 1500 → 1300+
print("[1] Fixing 1500 → 1300+...")
str_replace(
    "3 节点跑近 1500 条数据无中断",
    "3 节点跑 1300+ scenario 无中断"
)

print("\nRunning check_report.py...")
subprocess.run(["python3", "/workspace/team/scripts/check_report.py", DOC, "--audience", "boss"])
