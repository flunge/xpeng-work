#!/usr/bin/env python3
"""拉老板高炳涛近一月(05-31~06-30)全部发言 + p2p，存原始到文件，stdout 只给精简清单。
避免把几百条原文灌进对话上下文。"""
import json, subprocess, sys

BOSS = "ou_8bcf2bb3c23a679a7c19bfcc80b4cdda"
START = "2026-05-31T00:00:00+08:00"
END = "2026-06-30T23:59:59+08:00"
OUT = "/workspace/team/memory/daily-sync/boss_month_raw.json"


def run(args):
    r = subprocess.run(["lark-cli"] + args, capture_output=True, text=True, timeout=120)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"_err": r.stderr[:300]}


def main():
    allmsgs = run(["im", "+messages-search", "--as", "user", "--sender", BOSS,
                   "--start", START, "--end", END, "--page-all", "--format", "json"])
    msgs = allmsgs.get("data", {}).get("messages", []) if isinstance(allmsgs, dict) else []
    with open(OUT, "w") as f:
        json.dump(msgs, f, ensure_ascii=False, indent=1)
    print(f"老板发言共 {len(msgs)} 条，原始存 {OUT}")
    # 按群归类统计 + 精简清单
    by_chat = {}
    for m in msgs:
        cn = m.get("chat_name") or m.get("chat_id", "?")[:12]
        by_chat.setdefault(cn, []).append(m)
    print("=== 按群分布 ===")
    for cn, ms in sorted(by_chat.items(), key=lambda x: -len(x[1])):
        print(f"  {cn}: {len(ms)} 条")
    print("=== 精简清单（时间|群|内容前80字）===")
    for m in sorted(msgs, key=lambda x: str(x.get("create_time", ""))):
        ct = m.get("create_time", "")
        cn = (m.get("chat_name") or m.get("chat_id", "")[:10])
        c = str(m.get("content", "")).replace("\n", " ")[:80]
        print(f"[{ct}] {cn}: {c}")


if __name__ == "__main__":
    main()
