#!/usr/bin/env python3
"""每日 09:00 承诺风险哨兵（P0 版）

数据源：飞书 Base「承诺追踪与风险哨兵」（承诺追踪表），token 由 --base-token 指定。
行为：
  1. 拉全部记录，按规则计算风险等级（规则引擎，非 LLM）：
     - Deadline < 今天 且 状态 ∈ {进行中,低风险}   → 已逾期（高风险等级）
     - 今天 ≤ Deadline ≤ 今天+2 且 最近核查日期 < 昨天 → 高风险
     - 今天 ≤ Deadline ≤ 今天+5 且 最近核查日期 < 昨天 → 低风险
  2. 将自动判级的状态写回 Base（幂等：只在状态变化时更新）。
  3. 只向李坤 DM 推送「状态变化」的记录（即本次运行中等级变化的项，
     防止每天重复轰炸）；若全部为头版运行则推送全量非完成项。
运行：python3 team/scripts/risk_sentinel.py [--dry-run] [--push]
依赖：lark-cli（--profile xpeng，user+bot 双身份已配置）
"""

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta

PROFILE = "xpeng"
BASE_TOKEN = "NkIZb7eU7azZIEsegJ7cl2bfnUd"
TABLE_NAME = "承诺追踪"
DM_CHAT = "oc_bc5bb378d432fca62a7786e26cf82578"  # 与 xpeng 机器人的单聊
STATE_FILE = "/tmp/risk_sentinel_state.json"

HUE = {"进行中": "blue", "已完成": "green", "低风险": "yellow",
       "高风险": "red", "已逾期": "purple"}


def cli(*args, as_identity="user"):
    r = subprocess.run(
        ["lark-cli", "--profile", PROFILE] + list(args) + ["--as", as_identity],
        capture_output=True, text=True, timeout=60)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": {"message": r.stdout + r.stderr}}


def to_date(v):
    if v in (None, "", []):
        return None
    if isinstance(v, (int, float)):
        # Base datetime 可能返回毫秒时间戳
        return datetime.fromtimestamp(v / 1000 if v > 1e12 else v).date()
    if isinstance(v, str):
        try:
            return datetime.strptime(v[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    if isinstance(v, dict) and "text" in v:
        return to_date(v["text"])
    return None


def norm_text(v):
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return "".join(x.get("text", "") if isinstance(x, dict) else str(x) for x in v)
    if isinstance(v, dict):
        return v.get("text", "")
    return str(v) if v is not None else ""


def fetch_records():
    out = cli("base", "+record-list", "--base-token", BASE_TOKEN,
              "--table-id", TABLE_NAME, "--limit", "500", "--page-all")
    if not out.get("ok"):
        print(json.dumps(out, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)
    return out["data"].get("records", [])


def grade(rec, today):
    f = rec["fields"]
    status = norm_text(f.get("状态")) or "进行中"
    if status in ("已完成",):
        return status, []
    dl = to_date(f.get("Deadline"))
    checked = to_date(f.get("最近核查日期"))
    stale = checked is None or checked <= today - timedelta(days=2)
    reasons = []
    if dl and dl < today:
        reasons.append(f"逾期 {(today - dl).days} 天（Deadline {dl}）")
        return "已逾期", reasons
    if dl is None:
        if stale:
            reasons.append("无Deadline且超2天未核查")
        return ("低风险" if stale else status), reasons
    days = (dl - today).days
    if days <= 2 and stale:
        reasons.append(f"Deadline {dl} 剩 {days} 天且超2天未核查")
        return "高风险", reasons
    if days <= 5 and stale:
        reasons.append(f"Deadline {dl} 剩 {days} 天，超2天未核查")
        return "低风险", reasons
    return status, reasons


def update_status(record_id, status):
    return cli("base", "+record-batch-update", "--base-token", BASE_TOKEN,
               "--table-id", TABLE_NAME,
               "--json", json.dumps(
                   {"records": [{"record_id": record_id,
                                 "fields": {"状态": status, "最近核查日期": str(date.today())}}]},
                   ensure_ascii=False))


def load_prev():
    try:
        return json.load(open(STATE_FILE))
    except Exception:
        return {}


def save_prev(d):
    json.dump(d, open(STATE_FILE, "w"), ensure_ascii=False)


def push_post(items):
    lines = []
    for r, g, reasons in items:
        f = r["fields"]
        title = f"【{g}】{norm_text(f.get('承诺内容'))[:40]}"
        line = f"🔴 {title}\n    承诺人：{norm_text(f.get('承诺人'))}｜Deadline：{norm_text(f.get('Deadline'))}\n    原因：" + "；".join(reasons)
        lines.append(line)
    if not lines:
        return True
    content = "\n".join(lines)
    text = f"🚨 承诺风险日报 {date.today()}\n\n{content}"
    payload = {"text": text}
    out = cli("im", "+messages-send", "--chat-id", DM_CHAT,
              "--msg-type", "text",
              "--content", json.dumps(payload, ensure_ascii=False),
              as_identity="bot")
    return out.get("ok", False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--push", action="store_true", help="实际发 IM / 回写 Base")
    args = ap.parse_args()

    today = date.today()
    recs = fetch_records()
    prev = load_prev()
    changed, report = [], []
    state = {}
    for r in recs:
        rid = r["record_id"]
        g, reasons = grade(r, today)
        state[rid] = g
        if g in ("高风险", "已逾期"):
            report.append((r, g, reasons))
        # 状态变化（较上次运行）才推送
        if g in ("高风险", "已逾期") and prev.get(rid) != g:
            changed.append((r, g, reasons))
        # 回写 Base（仅变化时）
        if not args.dry_run and args.push:
            cur = norm_text(r["fields"].get("状态"))
            if cur != g and g in ("低风险", "高风险", "已逾期"):
                update_status(rid, g)

    first_run = not prev
    to_push = report if first_run else changed
    print(f"records={len(recs)} risky={len(report)} changed={len(changed)} first_run={first_run}")
    for r, g, reasons in report:
        print(f"  - [{g}] {norm_text(r['fields'].get('承诺人'))}: "
              f"{norm_text(r['fields'].get('承诺内容'))[:50]} | {';'.join(reasons)}")
    if args.push and not args.dry_run:
        ok = push_post(to_push)
        print("push:", "ok" if ok else "failed")
        if ok:
            save_prev(state)


if __name__ == "__main__":
    main()
