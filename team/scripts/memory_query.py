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


def _list_records(table):
    """record-list markdown 表解析（当前 lark-cli 完整载荷）。返回 [{字段名: 值}]"""
    r = subprocess.run(["lark-cli", "--profile", PROFILE, "base", "+record-list",
                        "--base-token", PROMISE_BASE, "--table-id", table,
                        "--limit", "200", "--as", "user", "--format", "markdown"],
                       capture_output=True, text=True, timeout=90)
    return _parse_md_table(r.stdout)


def _parse_md_table(text):
    lines = [ln for ln in text.splitlines() if ln.startswith("| ")]
    if len(lines) < 2:
        return []
    header = [c.strip() for c in lines[0].strip("|").split("|")]
    rows = []
    for ln in lines[2:]:
        cells = [c.strip() for c in ln.split("|")][1:-1]
        if len(cells) < len(header):
            continue
        rows.append(dict(zip(header, cells)))
    return rows


def fetch_episodes(start_d, end_d):
    """从 Episode事件流 拉窗口内记录：日期过滤 + 项目缝合。"""
    rows = _list_records("Episode事件流")
    items = []
    for r in rows:
        t = r.get("时间", "")
        m = DATE_RE.search(t)
        if not m:
            continue
        try:
            d = datetime.strptime(m.group(1).replace("/", "-"), "%Y-%m-%d").date()
        except ValueError:
            continue
        if not (start_d <= d <= end_d):
            continue
        items.append({
            "date": str(d), "summary": r.get("事件摘要", ""),
            "src_type": r.get("来源类型", ""), "src": r.get("来源定位", ""),
            "projects": [p.strip() for p in r.get("涉及项目", "").split(",") if p.strip()],
            "key_numbers": r.get("关键数字", ""), "action": r.get("动作", ""),
            "url": r.get("原文链接", "")})
    return items


def fetch_promises(start_d, end_d):
    rows = _list_records("承诺追踪")
    items = []
    for r in rows:
        items.append({"record_id": r.get("_record_id", ""),
                      "content": r.get("承诺内容", ""), "owner": r.get("承诺人", ""),
                      "deadline": r.get("Deadline", ""), "status": r.get("状态", ""),
                      "projects": r.get("相关项目", ""), "evidence": r.get("证据来源", "")})
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
            "projects": [], "promises": fetch_promises(start_d, end_d),
            "open_items": _add_open_items(), "episodes": fetch_episodes(start_d, end_d)}

    # 把 Episode 按项目贴合
    for proj in pack["projects"]:
        proj["episodes"] = [e for e in pack["episodes"]
                            if proj["name"] in e["projects"]]

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
        print(f"written: {args.out} ({len(out_json)} chars) "
              f"episodes={len(pack['episodes'])} promises={len(pack['promises'])} "
              f"open_items={len(pack['open_items'])}")
    else:
        print(out_json)


def _add_open_items():
    rows = _list_records("开口项追踪")
    out = []
    for r in rows:
        st = r.get("状态", "").strip('"[] ')
        out.append({
            "record_id": r.get("_record_id", ""),
            "project": r.get("项目", ""), "item": r.get("事项", ""),
            "status": st, "open_date": r.get("开口日期", ""),
            "open_src": r.get("开口来源", ""), "close_src": r.get("关闭来源", ""),
            "evidence": r.get("证据原文", "")})
    return out


if __name__ == "__main__":
    main()
