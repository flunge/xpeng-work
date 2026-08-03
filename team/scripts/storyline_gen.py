#!/usr/bin/env python3
"""Storyline 主线卡生成器（P2；MEMORY_REBUILD_V2 附：v1 人审半自动）

每周五 20:00（LaunchAgent com.xpeng.storyline-gen）拉取当周各项目证据，
组装候选卡写入追踪 Base「Storyline主线卡」（tbl7dyPy4sr01nBI），
全部标记 人工确认=待确认 → 周六李坤 IM 审阅修正（REBUILD_V2 流程步骤2-3）。

流水线：
  1. window：本周一 ~ 周日（--date 指定周内任意日，默认今天）
  2. memory_query.py 证据包（L3 状态 + L2 承诺/开口项，含来源）
  3. Episode 事件流（tblV7t82iJwnPb85）窗口内事件按项目归档 → 数字/叙事只引 record_id
  4. 候选卡写入 Storyline主线卡（写入前清空同周期同项目旧候选，重跑幂等）
  5. 推送李坤 DM（待确认数量 + 审阅入口）

依赖：lark-cli --profile xpeng（user 身份）
用法：
  python3 team/scripts/storyline_gen.py                # 生成并写库+推送
  python3 team/scripts/storyline_gen.py --date 2026-08-03   # 回填指定周
  python3 team/scripts/storyline_gen.py --dry-run       # 只组装打印
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PROFILE = "xpeng"
BASE_TOKEN = "NkIZb7eU7azZIEsegJ7cl2bfnUd"
EPISODE_TABLE = "tblV7t82iJwnPb85"
STORYLINE_TABLE = "tbl7dyPy4sr01nBI"
OPEN_TABLE = "tblZ7Mp5mLhY2Cnw"
LIKUN_OPEN_ID = "ou_ef9ffede830b69e0b991b3fdb28df8ed"  # 李坤 user 身份（personal profile）
# IM 推送通道：与 bot 的单聊会话（与 risk-push.py 同一通道；xpeng 应用无 im:message.send_as_user）
DM_CHAT = "oc_bc5bb378d432fca62a7786e26cf82578"
PUSH_PROFILE = "meal"
FEISHU_MAP = BASE_DIR / "memory" / "_feishu_map.json"

# 里程碑型 ledger 特征：无「三、持续进展」也不算缺陷；Seasonal 讨论式事件算 IM群聊
NO_MISMATCH_LEDGER = {"WM-内部探索"}

# 项目白名单 + 别名归并（非项目类散标签→None=跳过建卡，提醒）
_NON_PROJECT = {"多项目", "all", "ALL", "组会", "日会", "Oncall", "oncall", "实习生", "CCES", ""}
# 别名归并：canonical = _feishu_map 中的规范项目名；aliases 里第一个就是 canonical 自身。
# 注意：RC路线（生产侧）与 RC路线SIL验证（验证侧）是两个独立 ledger，
# 故意拆分（见 RC路线 ledger 文档属性），禁止互相归并，只在 storyline 分卡。
_ALIASES = {
    "车型泛化": ["车型泛化", "vehicle-generalization", "换车型"],
    "HIL链路部署": ["HIL", "HIL链路部署"],
    "RC路线": ["RC路线", "RC长里程", "RC生产"],
    "RC路线SIL验证": ["RC路线SIL验证", "SIL验证", "RC SIL"],
}


def load_project_whitelist():
    try:
        m = json.loads(FEISHU_MAP.read_text(encoding="utf-8"))
        return set((m.get("projects") or {}).keys())
    except Exception:
        return set()


def canonical_project(raw, whitelist):
    """原始标签 → 规范项目名；非项目标签返回 None。"""
    if not raw or raw in _NON_PROJECT:
        return None
    for canon, aliases in _ALIASES.items():
        if any(a in raw for a in aliases):
            return canon
    for p in whitelist:
        if p in raw or raw in p:
            return p
    return raw if raw in whitelist else None


def canonical_evidence_name(name, whitelist):
    """证据包里的项目名也往 canonical 归一，防“别名相互防不上”。"""
    for canon, aliases in _ALIASES.items():
        if any(a in name for a in aliases):
            return canon
    return name

# Storyline 表真实字段名（2026-08-03 +field-list 校准）
F_PROJ = "项目"
F_WEEK = "周期"
F_POS = "①定位一句话"
F_HAPPENED = "②本周发生了什么"
F_NUMS = "③数字与证据"
F_RISK = "④状态与风险"
F_NEXT = "⑤下周预判"
F_EPIDS = "生成依据EpisodeIDs"
F_CONFIRM = "人工确认"
F_GENTIME = "生成时间"


def cli(args, timeout=120):
    r = subprocess.run(["lark-cli", "--profile", PROFILE] + args + ["--as", "user"],
                       capture_output=True, text=True, timeout=timeout)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": {"message": (r.stdout + r.stderr)[:400]}}


def week_window(d: date):
    mon = d - timedelta(days=d.weekday())
    return mon, mon + timedelta(days=6)


def run_memory_query(mon, sun, out_path):
    r = subprocess.run(
        [sys.executable, str(BASE_DIR / "scripts" / "memory_query.py"),
         "--start", mon.isoformat(), "--end", sun.isoformat(), "--out", str(out_path)],
        capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print(f"[storyline] memory_query 失败: {r.stderr[:300]}", file=sys.stderr)
        return None
    return json.loads(Path(out_path).read_text(encoding="utf-8"))


def ensure_episodes(mon, sun):
    """保障 W<N> 窗口内 Episode 充足：不够时自动跑 backfill_all 补（幂等）。"""
    eps = fetch_episodes(mon, sun)
    if eps:
        return eps
    print(f"[storyline] {mon}~{sun} Episode 零事件 → 自动触发 backfill_all.py 补米", flush=True)
    r = subprocess.run(
        [sys.executable, str(BASE_DIR / "scripts" / "backfill_all.py")],
        capture_output=True, text=True, timeout=900)
    print(r.stdout.strip())
    return fetch_episodes(mon, sun)


def list_records(table_id, limit=500):
    """+record-list --json 全量返回 rows+record_ids+fields。"""
    out, offset = [], 0
    fields = None
    while True:
        d = cli(["base", "+record-list", "--base-token", BASE_TOKEN,
                 "--table-id", table_id, "--limit", "200", "--offset", str(offset), "--json"])
        if not d.get("ok"):
            print(f"[storyline] 记录拉取失败({table_id}): {(d.get('error') or {}).get('message')}",
                  file=sys.stderr)
            return [], fields
        data = d["data"]
        fields = data.get("fields", [])
        rows = data.get("data", [])
        rids = data.get("record_id_list", [])
        out.extend((rid, row) for rid, row in zip(rids, rows))
        if not data.get("has_more"):
            break
        offset += len(rows)
    return out, fields


def parse_date(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s)[:10]).date()
    except Exception:
        return None


def fetch_episodes(mon, sun):
    records, fields = list_records(EPISODE_TABLE)
    idx = {name: i for i, name in enumerate(fields)}
    out = []
    for rid, row in records:
        def cell(name):
            i = idx.get(name)
            return row[i] if i is not None and i < len(row) else None
        d0 = parse_date(cell("时间"))
        if d0 is None or not (mon <= d0 <= sun):
            continue
        out.append({
            "record_id": rid,
            "date": d0.isoformat(),
            "事件摘要": cell("事件摘要") or "",
            "涉及项目": cell("涉及项目") or "",
            "关键数字": cell("关键数字") or "",
            "动作": cell("动作") or "",
            "来源类型": cell("来源类型") or [],
            "原文链接": cell("原文链接") or "",
        })
    return out


def group_by_project(episodes, whitelist):
    by, skipped = {}, set()
    for e in episodes:
        projs = e["涉及项目"]
        if isinstance(projs, str):
            projs = [p.strip() for p in projs.replace("，", ",").replace("、", ",").split(",") if p.strip()]
        canon = set()
        for p in projs:
            cp = canonical_project(p, whitelist)
            if cp:
                canon.add(cp)
            else:
                skipped.add(p)
        for cp in (canon or []):
            by.setdefault(cp, []).append(e)
    return by, skipped


def fetch_open_items(project):
    """开口项追踪：按项目反查 open/suspected-close 条目，回引 record_id。
    修复：项目字段可能是“车型泛化、WM-内部探索”这类多值逗号分隔，先拆开再比对。"""
    records, fields = list_records(OPEN_TABLE)
    if not fields:
        return []
    idx = {name: i for i, name in enumerate(fields)}
    out = []
    for rid, row in records:
        def cell(name):
            i = idx.get(name)
            return row[i] if i is not None and i < len(row) else None
        proj_raw = str(cell("项目") or "")
        status_raw = cell("状态")
        if isinstance(status_raw, list):
            status = ",".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in status_raw)
        else:
            status = str(status_raw or "")
        proj_items = [p.strip() for p in proj_raw.replace("，", ",").replace("、", ",").split(",") if p.strip()]
        matched = any(project in p or p in project for p in proj_items)
        if matched and ("open" in status or "suspected" in status or "疑似" in status):
            out.append(f"- [{rid}] {str(cell('事项') or '')[:80]}（{status}）")
    return out[:5]


def build_card(project, week_label, items, evidence):
    ep_ids = [e["record_id"] for e in items]
    nums = [f"[{e['record_id']}] {e['关键数字']}" for e in items if e["关键数字"]]
    proj_ev = None
    for p in (evidence or {}).get("projects", []):
        pn = str(p.get("name", ""))
        # 包含匹配：项目名互含（规范名 canon 可能短于/长于 ledger 里的全名）
        match = project in pn or pn in project
        if not match:
            # 按 canonical 归一再比：RC路线 vs RC路线SIL验证 应能对上
            canon = canonical_evidence_name(pn, load_project_whitelist())
            match = canon == project
        if match:
            proj_ev = p
            break
    # 「①定位一句话」应该是最新里程碑/判断，不是 ledger 开头的文档属性说明。
    # 从 progress 数组拿最新一条，它比 current_status (ledger 头部文档属性) 更接近“本周定位”。
    raw_status = (proj_ev or {}).get("current_status") or ""
    # 过滤出真正的判断/里程碑行：进展非空且不是占位的“—”
    progress_lines = [
        str(x.get("text", ""))[:80]
        for x in (proj_ev or {}).get("progress", [])
        if str(x.get("text", "")).strip() not in ("—", "-", "", "--")
    ]
    latest = progress_lines[-1] if progress_lines else ""
    if latest:
        position = latest[:80]
    elif raw_status:
        # 去掉《》 p2p 等文档属性噪音，取纯判断
        cleaned = re.sub(r"（\d{4}-\d{2}-\d{2}（.*?））|📌|[（(].{0,5}精读补充.*[)）]", "", raw_status).strip()
        cleaned = re.sub(r"^\s*（截至 [^)]*）", "", cleaned).strip()
        position = cleaned[:80] or "（证据包无本项目状态，需补 ledger）"
    else:
        position = "（证据包无本项目状态，需补 ledger）"
    happened = "\n".join(
        f"- [{e['record_id']}] {e['事件摘要'][:100]}{('：' + e['动作'][:60]) if e['动作'] else ''}"
        for e in items[:8]) or "本周无 Episode 记录"
    nums_text = "\n".join(nums[:8]) or "（本周 Episode 未带关键数字）"
    progress = "; ".join(x.get("text", "")[:60] for x in (proj_ev or {}).get("progress", [])[:3])
    open_lines = fetch_open_items(project)
    risk_parts = []
    if progress:
        risk_parts.append(f"L3增量: {progress}")
    risk_parts.extend(open_lines or ["开口项追踪：本周无 open/suspected-close 顶层项"])
    risk = "\n".join(risk_parts)
    return {
        F_PROJ: project,
        F_WEEK: week_label,
        F_POS: position,
        F_HAPPENED: happened,
        F_NUMS: nums_text,
        F_RISK: risk,
        F_NEXT: "（待周六李坤审阅时填写）",
        F_EPIDS: ", ".join(ep_ids),
        F_CONFIRM: "待确认",
        F_GENTIME: int(datetime.now().timestamp() * 1000),   # datetime 字段=毫秒时间戳
    }


def clear_old_candidates(week_label):
    records, fields = list_records(STORYLINE_TABLE)
    if not fields:
        return
    idx = {name: i for i, name in enumerate(fields)}
    wi = idx.get(F_WEEK)
    olds = [rid for rid, row in records
            if wi is not None and wi < len(row) and row[wi] == week_label]
    for rid in olds:
        cli(["base", "+record-delete", "--base-token", BASE_TOKEN,
             "--table-id", STORYLINE_TABLE, "--record-id", rid, "--yes"])
    if olds:
        print(f"[storyline] 清理 {len(olds)} 张 {week_label} 旧候选卡")


def write_cards(cards):
    """+record-batch-create：fields=列名列表，rows 按列序。"""
    cols = [F_PROJ, F_WEEK, F_POS, F_HAPPENED, F_NUMS, F_RISK, F_NEXT, F_EPIDS, F_CONFIRM, F_GENTIME]
    rows = [[c.get(col) for col in cols] for c in cards]
    d = cli(["base", "+record-batch-create", "--base-token", BASE_TOKEN,
             "--table-id", STORYLINE_TABLE,
             "--json", json.dumps({"fields": cols, "rows": rows}, ensure_ascii=False)])
    if d.get("ok"):
        return len(rows), ""
    return 0, (d.get("error") or {}).get("message", "")


def push_review(week_label, count):
    url = f"https://xiaopeng.feishu.cn/base/{BASE_TOKEN}?table={STORYLINE_TABLE}"
    # 与 risk-push.py 一致：bot 身份 + 已建立的单聊会话
    r = subprocess.run(
        ["lark-cli", "--profile", PUSH_PROFILE, "im", "+messages-send", "--as", "bot",
         "--chat-id", DM_CHAT, "--text",
         f"📋 Storyline主线卡 {week_label}：已生成 {count} 张候选卡（人工确认=待确认）。\n"
         f"审阅入口：{url}\n"
         f"操作：逐张把「人工确认」改为「已确认」，错误处直接改字段。"],
        capture_output=True, text=True, timeout=60)
    try:
        return json.loads(r.stdout).get("ok", False)
    except json.JSONDecodeError:
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", default=None, help="周内任意日（默认今天），用于回填历史周")
    ap.add_argument("--dry-run", action="store_true", help="只组装打印，不写库不推送")
    args = ap.parse_args()
    today = date.fromisoformat(args.date) if args.date else date.today()
    _, w, _ = today.isocalendar()
    week_label = f"W{w:02d}"
    mon, sun = week_window(today)
    print(f"[storyline] {week_label} 窗口 {mon} ~ {sun}")

    ev_path = Path(f"/tmp/evidence_{week_label}.json")
    evidence = run_memory_query(mon, sun, ev_path)
    episodes = ensure_episodes(mon, sun)
    if not episodes:
        # 仍为空：ledger 逆推完后什么都补不出来（当前周末晚、添加的米还在 daily-sync 22:00）
        print(f"[storyline] {week_label} 当前周 Event 仍然为 0 → 不生成卡")
        if not args.dry_run:
            return
    print(f"[storyline] Episode 窗口内 {len(episodes)} 条；证据包 {'OK' if evidence else 'FAILED'}")
    # 证据包失败也别完全放弃 storyline —— 至少能用 Episode 生成轻微版
    if not evidence:
        evidence = {"projects": [], "promises": []}
    by_proj, skipped = group_by_project(episodes, load_project_whitelist())
    if skipped:
        print(f"[storyline] 非项目标签跳过建卡: {sorted(skipped)}")

    cards = [build_card(p, week_label, items, evidence)
             for p, items in sorted(by_proj.items()) if p != "__未标注__"]
    print(f"[storyline] 组装 {len(cards)} 张候选卡: {[c[F_PROJ] for c in cards]}")

    if args.dry_run:
        for c in cards:
            display = {k: (str(v)[:200] + "…" if len(str(v)) > 200 else v) for k, v in c.items()}
            print(json.dumps(display, ensure_ascii=False, indent=1))
            print("---")
        return

    if not cards:
        print("[storyline] 本周无项目事件，不写库。")
        return
    clear_old_candidates(week_label)
    n_ok, err = write_cards(cards)
    print(f"[storyline] 已写入 {n_ok}/{len(cards)} 张 → 「Storyline主线卡」（待确认） {err or ''}")
    if n_ok:
        print(f"[storyline] IM 推送李坤：{'OK' if push_review(week_label, n_ok) else 'FAILED'}")


if __name__ == "__main__":
    main()
