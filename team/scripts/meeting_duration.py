#!/usr/bin/env python3
"""统计组内日会/例会真实时长（从会议纪要标题的 HH:MM - HH:MM 提取）。
用法: python3 scripts/meeting_duration.py
不用内联 heredoc——脚本落盘再跑，避免工具调用解析中断。"""
import json, glob, re, subprocess
from datetime import datetime

SYNC = "memory/daily-sync"

# 1) 收集本月所有会议纪要 token
tokens = []
for f in sorted(glob.glob(f"{SYNC}/2026-06-*.json")):
    try:
        data = json.load(open(f, encoding="utf-8"))
    except Exception:
        continue
    for m in data.get("meeting_docs", []) or []:
        if isinstance(m, dict):
            t = m.get("doc") or m.get("token") or ""
            if t:
                tokens.append(t)
tokens = list(dict.fromkeys(tokens))

# 2) 逐个 fetch 标题行，提取会议名 + 时间段
pat = re.compile(r"(\d{1,2}:\d{2})\s*[-–~]\s*(\d{1,2}:\d{2})")
rows = []
for tk in tokens:
    try:
        out = subprocess.run(
            ["lark-cli", "docs", "+fetch", "--doc", tk,
             "--doc-format", "markdown", "--format", "pretty"],
            capture_output=True, text=True, timeout=40).stdout
    except Exception:
        continue
    head = out[:400]
    title = head.split("\n")[0].replace("<title>", "").replace("</title>", "").strip()
    if not any(k in title for k in ["日会", "例会"]):
        continue
    m = pat.search(head)
    if not m:
        continue
    s = datetime.strptime(m.group(1), "%H:%M")
    e = datetime.strptime(m.group(2), "%H:%M")
    mins = int((e - s).total_seconds() / 60)
    if mins < 0:
        mins += 24 * 60
    kind = "核心日会" if "核心" in title else ("每日例会" if "例会" in title else "日会")
    rows.append((title[:40], kind, mins))

# 3) 输出
print(f"统计到 {len(rows)} 场日会/例会\n")
by_kind = {}
for title, kind, mins in rows:
    print(f"  [{mins:>3}分钟] {kind} | {title}")
    by_kind.setdefault(kind, []).append(mins)

print("\n=== 平均时长 ===")
all_mins = []
for kind, arr in by_kind.items():
    avg = sum(arr) / len(arr)
    print(f"  {kind}: {len(arr)} 场, 平均 {avg:.0f} 分钟 (最短{min(arr)}/最长{max(arr)})")
    all_mins += arr
if all_mins:
    print(f"  合计: {len(all_mins)} 场, 平均 {sum(all_mins)/len(all_mins):.0f} 分钟/场")
    print(f"  每天两会合计平均: {2*sum(all_mins)/len(all_mins):.0f} 分钟/天")
