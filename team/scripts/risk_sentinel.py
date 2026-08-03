#!/usr/bin/env python3
"""每日 09:00 风险哨兵（P0 版）

数据源：飞书 Base「追踪Base」（承诺追踪表 + 开口项追踪表）。
承诺模块（原有）：
  1. 拉全部记录，按规则计算风险等级（规则引擎，非 LLM）：
     - Deadline < 今天 且 状态 ∈ {进行中,低风险}   → 已逾期（高风险等级）
     - 今天 ≤ Deadline ≤ 今天+2 且 最近核查日期 < 昨天 → 高风险
     - 今天 ≤ Deadline ≤ 今天+5 且 最近核查日期 < 昨天 → 低风险
  2. 将自动判级的状态写回 Base（幂等：只在状态变化时更新）。
  3. 只向李坤 DM 推送「状态变化」的记录（即本次运行中等级变化的项，
     防止每天重复轰炸）；若全部为头版运行则推送全量非完成项。
开口项模块（2026-08-03 新增）：
  - 扫「开口项追踪」表：
    * suspected-close 条目 → 每日提醒「疑似已关闭，待有人确认」；
    * open 条目 且 最近核查日期 > 7 天（或为空） → 提醒「开口项失联，需重新悬挂」。
  - 只做提醒推送、不回写；防止每天重复轰炸 → 同样基于首次/状态变化状态文件记忆。
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
OPEN_TABLE = "开口项追踪"
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


def _list_records(table):
    """json 模式拼装：data.data 权行 + fields 字段名 + record_id_list 合并。"""
    out = cli("base", "+record-list", "--base-token", BASE_TOKEN,
              "--table-id", table, "--limit", "200", "--format", "json")
    if not out.get("ok"):
        return out, []
    data = out.get("data") or {}
    fields = data.get("fields") or []
    rows = data.get("data") or []
    ids = data.get("record_id_list") or []
    recs = []
    for rid, values in zip(ids, rows):
        recs.append({"record_id": rid, "fields": dict(zip(fields, values))})
    return {"ok": True}, recs


def fetch_records():
    out, recs = _list_records(TABLE_NAME)
    if not out.get("ok"):
        print(json.dumps(out, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)
    return recs or []


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


PROJECT_STALE_DAYS = 7
EPISODE_TABLE = "Episode事件流"


def check_project_stall(today):
    """项目级停摆哨兵：某项目 Episode 最近一条 > 7 天（且开口项还有未闭环项）→ 风险提示。
    返回 report=[(project, last_date, days_stale, open_count)]"""
    # Episode 事件流：按项目取最近日期
    out, recs = _list_records(EPISODE_TABLE)
    proj_last = {}
    for r in recs:
        f = r["fields"]
        proj_raw = norm_text(f.get("涉及项目"))
        tstr = norm_text(f.get("时间"))
        if not proj_raw or not tstr:
            continue
        d = to_date(tstr)
        if not d:
            continue
        for p in proj_raw.replace("，", ",").replace("、", ",").split(","):
            p = p.strip()
            if d > proj_last.get(p, date(2000, 1, 1)):
                proj_last[p] = d
    # 开口项：有 open 的项目才给提示（已全部闭环就不报）
    open_by_proj = {}
    for r in fetch_open_records():
        f = r["fields"]
        st = norm_text(f.get("状态")) or "open"
        if st not in ("open", "suspected-close"):
            continue
        for p in norm_text(f.get("项目")).replace("，", ",").replace("、", ",").split(","):
            p = p.strip()
            if p:
                open_by_proj[p] = open_by_proj.get(p, 0) + 1
    # 重点监控项目集合（有跟踪价值的）
    keys = set(open_by_proj) | {k for k, v in proj_last.items() if v >= date(2026, 7, 1)}
    report = []
    for p in sorted(keys):
        last = proj_last.get(p)
        if last is None:
            days = 999
        else:
            days = (today - last).days
        if days >= PROJECT_STALE_DAYS and open_by_proj.get(p, 0) > 0:
            report.append((p, last, days, open_by_proj[p]))
    return report


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

    # ── 开口项模块：suspected-close 提醒 + stale 失联提醒 ──
    open_changed, open_report = check_open_items(today)
    prev_open = prev.get("_open_items", {}) if isinstance(prev, dict) else {}
    if open_report:
        print("\n开口项提醒:")
        for r, lvl, reasons in open_report:
            f = r["fields"]
            print(f"  - [{lvl}] {norm_text(f.get('项目'))}｜{norm_text(f.get('事项'))[:40]} | {';'.join(reasons)}")
    if args.push and not args.dry_run:
        # 每级只推新出现的一组（防止每日重发同一批）
        alerts = [(r, lvl, reasons) for (r, lvl, reasons) in open_report
                  if prev_open.get(r["record_id"]) != lvl]
        if alerts:
            lines = []
            for r, lvl, reasons in alerts:
                f = r["fields"]
                lines.append(
                    f"[{lvl}] {norm_text(f.get('项目'))}｜{norm_text(f.get('事项'))[:40]}"
                    f"\n    原因：{'；'.join(reasons)}")
            text = "📌 开口项状态提醒 " + str(date.today()) + "\n\n" + "\n".join(lines)
            out = cli("im", "+messages-send", "--chat-id", DM_CHAT,
                      "--msg-type", "text",
                      "--content", json.dumps({"text": text}, ensure_ascii=False),
                      as_identity="bot")
            print("open-push:", "ok" if out.get("ok") else "failed", f"({len(alerts)}条)")
        new_open = {"_open_items": {r["record_id"]: lvl for (r, lvl, _) in open_report}}
        prev.update(new_open)
        save_prev(prev)

    # ── 项目级停摆哨兵 ──
    stall = check_project_stall(today)
    if stall:
        print("\n项目停摆提醒（Episode>7 天未更新 + 尚有未闭环开口项）:")
        for p, last, days, open_n in stall:
            print(f"  - {p}: 最后 Episode {last}（{days}天前），未闭环开口 {open_n} 条")
    if args.push and not args.dry_run and stall:
        lines = []
        for p, last, days, open_n in stall:
            last_s = str(last) if last else "无记录"
            lines.append(f"{p}：最后 Episode {last_s}（{days} 天前），仍有 {open_n} 条 open/suspected-close 开口项")
        text = "📊 项目停摆哨兵 " + str(date.today()) + "\n\n" + "\n".join(lines)
        out = cli("im", "+messages-send", "--chat-id", DM_CHAT,
                  "--msg-type", "text",
                  "--content", json.dumps({"text": text}, ensure_ascii=False),
                  as_identity="bot")
        print("stall-push:", "ok" if out.get("ok") else "failed", f"({len(stall)}条)")


def fetch_open_records():
    out, recs = _list_records(OPEN_TABLE)
    return recs or []


def check_open_items(today):
    """返回 (changed, report): report=[(rec, level, [reasons])]，level∈{疑似关闭,开口项失联}"""
    report = []
    state = {}
    changed = []
    for r in fetch_open_records():
        f = r["fields"]
        status = norm_text(f.get("状态")) or "open"
        checked = to_date(f.get("最近核查日期"))
        stale = checked is None or checked <= today - timedelta(days=7)
        lv = None
        reasons = []
        if status == "suspected-close":
            lv, reasons = "疑似关闭", [
                "已具备关闭候选证据，需人工确认", norm_text(f.get("证据原文"))[:60]]
        elif status == "open" and stale:
            lv = "开口项失联"
            reasons = ["开口超7天未核查" if checked is None else f"最近核查 {checked} 超 7 天"]
        if lv:
            report.append((r, lv, reasons))
            state[r["record_id"]] = lv
    return changed, report


if __name__ == "__main__":
    main()
