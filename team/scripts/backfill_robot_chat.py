#!/usr/bin/env python3
"""日会/会议纪要机器人群 全量历史回填 Episode（L1）+ 项目标注修复

洞①：seed_episode/episode_ingest 只覆盖 7/16 以后，3/1~7/15 上百条纪要 docx 未入。
洞②：已入行的「涉及项目」= 多项目，靠内容判断的 project tagging 缺失。

本脚本：
  1. 按 50/页翻完聊天全历史（--start 2026-03-01 起），提取 docx token；
  2. 对未入库 token：docs +fetch --scope outline 拉标题/目录，
     项目命中 = 目录含项目别名关键词（车型泛化/HIL/RC/SIL/慢速/极速...）→ 涉及项目；
  3. 落行：来源类型=会议纪要逐字稿, 来源定位=docx:{token}, 事件摘要=纪要标题；
  4. 对已入但未标项目的行（涉及项目=多项目/空）：用 outline 命中结果 +record-update 补项目列。

幂等：以 docx:{token} 去重；重跑只补新文档。
速率：--sleep 默认 0.3s；遇到 99991400 自动退避 max(2, rate/2) 秒。

用法：
  python3 team/scripts/backfill_robot_chat.py [--start 2026-03-01] [--dry-run] \
      [--chat oc_56b10049700694038662e72aa78e35d3] [--sleep 0.3]
"""
import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROFILE = "xpeng"
BASE = "NkIZb7eU7azZIEsegJ7cl2bfnUd"
EPISODE = "tblV7t82iJwnPb85"
DEFAULT_CHAT = "oc_56b10049700694038662e72aa78e35d3"

# 项目别名 → 规范项目名（与 storyline_gen._ALIASES 保持一致方向）
PROJECT_ALIAS = {
    "车型泛化": ["车型泛化", "换车型", "泛化验证"],
    "HIL链路部署": ["HIL", "HIL链路"],
    "RC路线": ["RC路线", "长里程", "RC生产"],
    "RC路线SIL验证": ["SIL仿真", "RC SIL", "轻量化SIL"],
    "慢速模式": ["慢速模式", "低速模式"],
    "极速模式": ["极速模式", "高速模式"],
    "复现率Agent": ["复现率", "顿挫专项", "RB 侧"],
    "TopDiff-Agent": ["TopDiff"],
    "场景编辑": ["场景编辑", "场景编辑算法"],
    "闭环场景集推进": ["闭环场景集", "场景集毕业"],
    "Prompt-Agent": ["Prompt-Agent"],
    "AVM鱼眼": ["AVM", "鱼眼"],
    "CLIP-IQA": ["CLIP-IQA", "clipiqa"],
    "Fixer优化": ["Fixer", "difix"],
    "WM-内部探索": ["世界模型", "World Model", "WM-"],
}


def cli(*args, timeout=180):
    r = subprocess.run(["lark-cli", "--profile", PROFILE] + list(args) + ["--as", "user"],
                       capture_output=True, text=True, timeout=timeout)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"ok": False, "error": {"message": (r.stdout + r.stderr)[:300]}}


def cli_retry(*args, sleep=0.3, timeout=180):
    for attempt in range(4):
        d = cli(*args, timeout=timeout)
        err = d.get("error") or {}
        if err.get("code") == 99991400 or "rate_limit" in str(err.get("subtype")):
            wait = max(2, sleep * (attempt + 1) * 4)
            print(f"[429] rate limit, sleep {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue
        return d
    return d


def pull_chat_history(chat, start, sleep=0.3):
    """翻完全部历史消息（倒序），返回 (create_time, docx_token)。"""
    page_token = None
    out = []  # (create_time, token, message_id)
    total = 0
    while True:
        args = ["im", "+chat-messages-list", "--chat-id", chat,
                "--start", start + "T00:00:00+08:00",
                "--no-reactions", "--format", "json"]
        if page_token:
            args += ["--page-token", page_token]
        d = cli_retry(*args, sleep=sleep)
        if not d.get("ok"):
            print("[pull] fail:", d.get("error")); break
        data = d["data"]
        ms = data.get("messages", [])
        total += len(ms)
        for m in ms:
            c = str(m.get("content", ""))
            for tok in re.findall(r"docx/([A-Za-z0-9]+)", c):
                out.append((m.get("create_time", ""), tok, m.get("message_id", "")))
        pt = data.get("page_token")
        if not data.get("has_more") or not pt or pt == page_token:
            break
        page_token = pt
        time.sleep(sleep)
    print(f"[pull] 共 {total} 条消息 → {len(out)} 个 docx token")
    # 时间升序 + token 去重（保留首次出现时间）
    seen = {}
    for ct, tok, mid in out:
        seen.setdefault(tok, (ct, mid))
    return sorted(((ct, tok, mid) for tok, (ct, mid) in seen.items()), key=lambda x: x[0])


OUTLINE_CACHE = {}


def fetch_outline(tok, sleep=0.3):
    if tok in OUTLINE_CACHE:
        return OUTLINE_CACHE[tok]
    d = cli_retry("docs", "+fetch", "--doc", tok,
                  "--doc-format", "markdown", "--scope", "full", sleep=sleep, timeout=120)
    text = ""
    title = ""
    if d.get("ok"):
        doc = (d.get("data") or {}).get("document") or {}
        text = doc.get("content") or ""
        m = re.match(r"\s*<title>(.*?)</title>", text)
        title = m.group(1).strip() if m else ""
    OUTLINE_CACHE[tok] = (title, text)
    time.sleep(sleep)
    return title, text


def match_projects(text):
    hits = set()
    for proj, kws in PROJECT_ALIAS.items():
        if any(k in text for k in kws):
            hits.add(proj)
    return "、".join(sorted(hits)) if hits else "多项目"


def existing_sources():
    """全量翻页拉 Episode 现有 来源定位。"""
    out, offset = set(), 0
    while True:
        d = cli("base", "+record-list", "--base-token", BASE, "--table-id", EPISODE,
                "--limit", "200", "--offset", str(offset), "--format", "json")
        if not d.get("ok"):
            print("[list] fail:", d.get("error")); break
        rows = d["data"].get("data", [])
        flds = d["data"].get("fields", [])
        idx = {n: i for i, n in enumerate(flds)}
        for row in rows:
            loc = str(row[idx["来源定位"]] or "")
            if loc:
                out.add(loc)
        if not d["data"].get("has_more"):
            break
        offset += len(rows)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-03-01")
    ap.add_argument("--chat", default=DEFAULT_CHAT)
    ap.add_argument("--sleep", type=float, default=0.3)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    hist = pull_chat_history(args.chat, args.start, sleep=args.sleep)
    existing = existing_sources()
    print(f"[dedupe] Episode 已有 {len(existing)} 条来源")

    new_docs = [(ct, tok, mid) for ct, tok, mid in hist if f"docx:{tok}" not in existing]
    print(f"[plan] 新 docx {len(new_docs)} / 历史 {len(hist)} 篇")

    rows = []
    titles = {}
    for ct, tok, mid in new_docs:
        title, outline = fetch_outline(tok, sleep=args.sleep)
        titles[tok] = title
        proj = match_projects(outline or title)
        # 时间：message create_time "2026-07-31 09:59" → ISO
        t_iso = ct.replace(" ", "T") + ":00+08:00" if " " in ct else ct
        summary = title or f"智能纪要（{tok[:8]}）"
        rows.append([
            summary, t_iso, proj,
            "会议纪要逐字稿",
            f"docx:{tok}",
            "",  # 关键数字（留给内容过滤器）
            "",
            f"https://xiaopeng.feishu.cn/docx/{tok}",
        ])

    print(f"[plan] 待入库 {len(rows)} 条，项目分布:")
    from collections import Counter
    print(Counter(r[2] for r in rows))

    if not args.dry_run and rows:
        cols = ["事件摘要", "时间", "涉及项目", "来源类型", "来源定位", "关键数字", "动作", "原文链接"]
        # 拆批 50
        ok_all = True
        for i in range(0, len(rows), 50):
            payload = {"fields": cols, "rows": rows[i:i + 50]}
            d = cli("base", "+record-batch-create", "--base-token", BASE, "--table-id", EPISODE,
                    "--json", json.dumps(payload, ensure_ascii=False))
            print(f"[write] chunk {i//50} ok={d.get('ok')} {(d.get('error') or {}).get('message','')[:120]}")
            ok_all = ok_all and bool(d.get("ok"))
            time.sleep(args.sleep)
        print("[done] 全部写入:", ok_all)
    else:
        for r in rows[:10]:
            print(" ", r[1][:16], r[2], "|", r[0][:50])


if __name__ == "__main__":
    main()
