#!/usr/bin/env python3
"""开口项闸：扫 ledger 里 🔴/🟡 行 → 对比开口项表 → 报告 or 自动补库

强制规则（MEMORY_REBUILD_V2 规则 1）：ledger 中所有 🔴🟡 标记的必须
同步进入「开口项追踪」（tblZ7Mp5mLhY2Cnw），ledger 里保留叙述口径。

用法：
  python3 team/scripts/sync_open_items_from_ledger.py             # 检查所有项目，只报告
  python3 team/scripts/sync_open_items_from_ledger.py --apply     # 发现缺失自动入 Base（status=open）
  python3 team/scripts/sync_open_items_from_ledger.py --project 车型泛化 --apply

匹配规则（防重复）：同一 project + 事项前 20 字子串相同即视为已存在；
若已存在但状态是 closed/suspected-close 又 ➜ 需结合原文，只报告不自动改。
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

BASE = "NkIZb7eU7azZIEsegJ7cl2bfnUd"
TABLE = "tblZ7Mp5mLhY2Cnw"
PROFILE = "xpeng"
BASE_DIR = Path(__file__).resolve().parent.parent
RED_RE = re.compile(r"🔴")
YELLOW_RE = re.compile(r"🟡")
BLUE_RE = re.compile(r"🔵")
DONE_RE = re.compile(r"(?:已关闭|已解决|✅|closed)")
MARKER_RE = re.compile(r"^\s*(?:[-*+]\s*)?(?:\*\*)?(?:🔴|🟡|🔵)\s*(?:\*\*)?")


def cli(args, timeout=120):
    r = subprocess.run(["lark-cli", "--profile", PROFILE] + args + ["--as", "user"],
                       capture_output=True, text=True, timeout=timeout)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"ok": False, "raw": (r.stdout or r.stderr)[:300]}


def load_open_items():
    offset = 0
    items = []
    while True:
        d = cli(["base", "+record-list", "--base-token", BASE, "--table-id", TABLE,
                 "--limit", "200", "--offset", str(offset), "--json"])
        if not d.get("ok"):
            return items
        data = d["data"]
        fields = data.get("fields", [])
        idx = {n: i for i, n in enumerate(fields)}
        rows = data.get("data", [])
        rids = data.get("record_id_list", [])
        for rid, row in zip(rids, rows):
            def cell(name):
                i = idx.get(name)
                return row[i] if i is not None and i < len(row) else ""
            proj = str(cell("项目") or "")
            status_v = cell("状态")
            if isinstance(status_v, list):
                status = ",".join(x.get("text", x) if isinstance(x, dict) else str(x) for x in status_v)
            else:
                status = str(status_v or "")
            items.append({
                "record_id": rid,
                "项目": proj,
                "事项": str(cell("事项") or ""),
                "状态": status,
                "来源": str(cell("开口来源") or ""),
            })
        if not data.get("has_more"):
            break
        offset += len(rows)
    return items


def norm(s):
    return re.sub(r"\s+", "", s)


STOP_WORDS = {"已", "的", "了", "与", "是", "在", "需", "待", "要", "由", "通过", "目前", "未", "能", "正", "即将", "拟", "与实车", "对实车", "问题", "项", "事项", "来源"}
# 项目内同义词（不用全局查表，靠短词组挂接）
SYN = {
    "训练集群": ["卡", "A100", "算力"],
    "卡": ["训练集群", "算力"],
    "因果颠倒": ["因果"],
    "HIL": ["HIL链路", "链路"],
    "聚合": ["聚合函数", "误判"],
}


def tokenize(s):
    """粗粒度分词：中文按 2 字，拉丁整词"""
    toks = set()
    words = re.findall(r"[一-鿿]+|[A-Za-z0-9]+", s)
    for w in words:
        if re.match(r"[一-鿿]", w):
            if len(w) <= 2:
                toks.add(w)
            else:
                for i in range(len(w) - 1):
                    toks.add(w[i:i+2])
        else:
            toks.add(w.lower())
    return {t for t in toks if t not in STOP_WORDS and len(t) > 1}


def sim(a, b):
    """Jaccard 相似度 + 同义词扩展"""
    ta, tb = tokenize(a), tokenize(b)
    if not ta or not tb:
        return 0.0
    inter = ta & tb
    for t in list(ta):
        if t in SYN:
            inter |= set(SYN[t]) & tb
    for t in list(tb):
        if t in SYN:
            inter |= set(SYN[t]) & ta
    union = ta | tb
    return len(inter) / len(union) if union else 0.0


def same_item(a, b, prefix=20):
    if sim(a, b) >= 0.35:
        return True
    a_n, b_n = re.sub(r"\s+", "", a), re.sub(r"\s+", "", b)
    return a_n[: prefix] == b_n[: prefix] or a_n[: prefix] in b_n or b_n[: prefix] in a_n


def extract_marked_items(md_text):
    """从 ledger 全文中抽 🔴🟡 开头的行级条目（含编号）"""
    out = []
    for line in md_text.splitlines():
        line = line.strip()
        if not MARKER_RE.search(line):
            continue
        if DONE_RE.search(line):
            continue
        # 去掉 emoji / markdown 强调符
        txt = MARKER_RE.sub("", line)
        txt = re.sub(r"^[-*+]\s*", "", txt).strip()
        txt = re.sub(r"^(\*\*)+", "", txt).strip()
        if len(txt) < 8:
            continue
        out.append(txt[:280])
    return out


def find_ledger(project_name):
    f = BASE_DIR / "memory" / "larkdocs" / "team" / "projects" / f"{project_name}.md"
    return f if f.exists() else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", help="仅检查某一个项目")
    ap.add_argument("--apply", action="store_true", help="缺失项自动入 Base（open）")
    args = ap.parse_args()

    projects_dir = BASE_DIR / "memory" / "larkdocs" / "team" / "projects"
    if args.project:
        ledgers = [(args.project, find_ledger(args.project))]
    else:
        ledgers = [(p.stem, p) for p in sorted(projects_dir.glob("*.md"))]
    ledgers = [(n, f) for n, f in ledgers if f]

    existing = load_open_items()
    print(f"[sync] 开口项表已有 {len(existing)} 条记录")

    new_items = []
    dup = 0
    closed_but_present = []
    for proj, fpath in ledgers:
        md_text = fpath.read_text(encoding="utf-8")
        marked = extract_marked_items(md_text)
        # 该项目已有的（任何状态）
        proj_existing = [it for it in existing if proj in it["项目"] or it["项目"] in proj]
        for item_text in marked:
            hit = None
            for it in proj_existing:
                if same_item(item_text, it["事项"]):
                    hit = it
                    break
            if hit is not None:
                if "closed" in hit["状态"] or "疑似" in hit["状态"]:
                    closed_but_present.append((proj, item_text, hit["record_id"], hit["状态"]))
                else:
                    dup += 1
                continue
            new_items.append({"项目": proj, "事项": item_text, "来源": f"ledger:{fpath.name}"})

    print(f"[sync] 开口项已匹配 {dup} 条；新发现缺失 {len(new_items)} 条；closed 但 ledger 又出现 {len(closed_but_present)} 条")
    for it in new_items[:30]:
        print(f"  + 新开口 [{it['项目']}] {it['事项'][:80]}")
    for proj, item_text, rid, st in closed_but_present:
        print(f"  ⚠️ closed又出现 [{proj}] {item_text[:60]} record={rid} status={st}")

    if not args.apply or not new_items:
        if not args.apply:
            print("使用 --apply 入库新开口项（status=open，来源口径 ledger 文件名）")
        return

    rows = []
    for it in new_items:
        rows.append([
            it["项目"],
            it["事项"],
            "open",
            "2026-08-03",  # 开口日期
            it["来源"],
            "",            # 证据原文（可后续补）
            "",            # 关闭来源
            "",            # 最近核查日期
        ])
    payload = {"fields": ["项目", "事项", "状态", "开口日期", "开口来源", "证据原文", "关闭来源", "最近核查日期"],
               "rows": rows}
    resp = cli(["base", "+record-batch-create", "--base-token", BASE, "--table-id", TABLE,
                "--json", json.dumps(payload, ensure_ascii=False)])
    print(f"[sync] 入库 ok={resp.get('ok')} err={str(resp.get('error',{}).get('message',''))[:300]}")


if __name__ == "__main__":
    main()
