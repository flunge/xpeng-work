#!/usr/bin/env python3
"""记忆证据包装配器（evidence pack）— 周报/双周报防幻觉工程的 P0 组件

原则：写报告的 LLM **只**消费本脚本产出的 JSON 证据包，不允许回到原始
纪要/日报自由检索。证据包内每条事实自带 日期 + 来源 token + 原文行，
preflight.py 的数字回查闸以本包为唯一基准 [LOWCONF]。

用法：
  python3 team/scripts/memory_query.py --start 2026-07-20 --end 2026-08-02 \
      --out /tmp/evidence_W31.json
输出 JSON 结构：
  { "window": {...}, "projects": [ {name, token, url, current_status, progress:[{date, source_col, text}]} ],
    "promises": [承诺追踪表中窗口内的进行中/风险项], "generated_at": ... }
依赖：lark-cli（--profile xpeng，user 身份）
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

PROFILE = "xpeng"
BASE_DIR = Path(__file__).resolve().parent.parent
FEISHU_MAP = BASE_DIR / "memory" / "_feishu_map.json"
PROMISE_BASE = "NkIZb7eU7azZIEsegJ7cl2bfnUd"

DATE_RE = re.compile(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})")


def cli(*args):
    r = subprocess.run(["lark-cli", "--profile", PROFILE] + list(args) + ["--as", "user"],
                       capture_output=True, text=True, timeout=90)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": {"message": r.stdout + r.stderr}}


def strip_tags(s):
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).strip()


def fetch_doc(token):
    out = cli("docs", "+fetch", "--doc", token)
    if not out.get("ok"):
        return ""
    return out["data"]["document"]["content"]


def extract_section(content, heading_pat):
    m = re.search(heading_pat, content)
    if not m:
        return ""
    start = m.end()
    nxt = re.search(r"<h[23][ >]", content[start:])
    return content[start:start + (nxt.start() if nxt else len(content))]


def parse_progress(content, start_d, end_d):
    """解析「持续进展」表：<tr><td>时间</td><td>作战表(日报)</td><td>会议纪要/日会</td><td>其他来源</td>"""
    sec = extract_section(content, r"<h[23][^>]*>[^<]*持续进展")
    if not sec:
        return []
    rows = []
    for tr in re.findall(r"<tr>.*?</tr>", sec, re.DOTALL):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)
        if len(tds) < 2:
            continue
        cells = [strip_tags(t) for t in tds]
        m = DATE_RE.search(cells[0])
        if not m:
            continue
        try:
            d = datetime.strptime(m.group(1).replace("/", "-"), "%Y-%m-%d").date()
        except ValueError:
            continue
        if not (start_d <= d <= end_d):
            continue
        cols = [("作战表(日报)", cells[1] if len(cells) > 1 else ""),
                ("会议纪要/日会", cells[2] if len(cells) > 2 else ""),
                ("其他来源", cells[3] if len(cells) > 3 else "")]
        for col, text in cols:
            if text:
                rows.append({"date": str(d), "source_col": col, "text": text})
    return rows


def parse_status(content):
    sec = extract_section(content, r"<h[23][^>]*>[^<]*当前状态")
    return strip_tags(sec)[:800] if sec else ""


def fetch_promises(start_d, end_d):
    out = cli("base", "+record-list", "--base-token", PROMISE_BASE,
              "--table-id", "承诺追踪", "--limit", "500", "--page-all")
    if not out.get("ok"):
        return []
    items = []
    for r in out["data"].get("records", []):
        f = r["fields"]
        items.append({"record_id": r["record_id"],
                      "content": f.get("承诺内容"), "owner": f.get("承诺人"),
                      "deadline": f.get("Deadline"), "status": f.get("状态"),
                      "projects": f.get("相关项目"), "evidence": f.get("证据来源")})
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--projects", default="", help="逗号分隔，仅打包指定项目")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    start_d = datetime.strptime(args.start, "%Y-%m-%d").date()
    end_d = datetime.strptime(args.end, "%Y-%m-%d").date()

    fmap = json.load(open(FEISHU_MAP))
    wanted = set(filter(None, (p.strip() for p in args.projects.split(","))))

    pack = {"window": {"start": args.start, "end": args.end},
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "projects": [], "promises": fetch_promises(start_d, end_d)}

    for name, meta in fmap.get("projects", {}).items():
        if wanted and name not in wanted:
            continue
        content = fetch_doc(meta["token"])
        if not content:
            print(f"warn: fetch failed {name} {meta['token']}", file=sys.stderr)
            continue
        rows = parse_progress(content, start_d, end_d)
        pack["projects"].append({
            "name": name, "token": meta["token"], "url": meta.get("url", ""),
            "current_status": parse_status(content),
            "progress": rows})
        print(f"{name}: status={'Y' if pack['projects'][-1]['current_status'] else 'N'} rows={len(rows)}")

    out_json = json.dumps(pack, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(out_json, encoding="utf-8")
        print(f"written: {args.out} ({len(out_json)} chars)")
    else:
        print(out_json)


if __name__ == "__main__":
    main()
