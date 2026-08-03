#!/usr/bin/env python3
"""IM 群聊消息 → Episode（L1）：按项目关键词全局搜索回填

洞②修复：车型泛化等 283 条消息散在 26 个群里，此前未采。
方法：`im +messages-search --query <关键词> --page-all --start <起点>`，
客户端按项目别名打标、按 im:{message_id} 幂等去重，批量写 Episode。

排除规则：
  - 噪声群（bot 任务播报等）进 _BLOCKLIST；
  - 单条 <12 字（表情/碎片）跳过；
  - 来源类型=IM群聊，事件摘要=<群名+发送人+节选>，原文链接=message_app_link。

用法：
  python3 team/scripts/backfill_im_mentions.py [--start 2026-03-01] [--dry-run]
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

PROFILE = "xpeng"
BASE_DIR = Path(__file__).resolve().parent.parent
BASE = "NkIZb7eU7azZIEsegJ7cl2bfnUd"
EPISODE = "tblV7t82iJwnPb85"
FEISHU_MAP = BASE_DIR / "memory" / "_feishu_map.json"

# 项目 → 搜索关键词（多词 OR：每个词单独搜一条，客户端合并去重）
PROJECT_QUERIES = {
    "车型泛化": ["车型泛化", "泛化仿真", "换车型"],
    "HIL链路部署": ["HIL链路", "HIL 台架"],
    "RC路线": ["RC路线", "长里程仿真"],
    "RC路线SIL验证": ["SIL仿真", "RC SIL"],
    "慢速模式": ["慢速模式"],
    "极速模式": ["极速模式"],
    "复现率Agent": ["复现率"],
    "TopDiff-Agent": ["TopDiff"],
    "场景编辑": ["场景编辑"],
    "闭环场景集推进": ["场景集毕业", "闭环场景集"],
    "CLIP-IQA": ["CLIP-IQA", "clipiqa"],
    "Fixer优化": ["Fixer", "difix"],
    "Prompt-Agent": ["Prompt-Agent"],
    "AVM鱼眼": ["AVM 鱼眼"],
    "WM-内部探索": ["世界模型", "World Model"],
}

# 噪声群屏蔽（实测命中但全是 bot 任务播报 / 无关业务）
_BLOCKLIST = {
    "oc_03368c4b04c5325ccba507e1b99b154c": "AI编程平台任务播报(噪声)",
}

# 白名单群（None=全网群都采；建议保持 None，让客户看得很全面的图）
_CHAT_WHITELIST = None


def cli(*args, timeout=300):
    r = subprocess.run(["lark-cli", "--profile", PROFILE] + list(args) + ["--as", "user"],
                       capture_output=True, text=True, timeout=timeout)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"ok": False, "error": {"message": (r.stdout + r.stderr)[:300]}}


def cli_retry(*args, timeout=300):
    for attempt in range(4):
        d = cli(*args, timeout=timeout)
        err = d.get("error") or {}
        if err.get("code") in (99991400, 99991663) or "rate_limit" in str(err.get("subtype")):
            wait = 5 * (attempt + 1)
            print(f"[429] sleep {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue
        return d
    return d


def load_project_whitelist():
    try:
        m = json.loads(FEISHU_MAP.read_text(encoding="utf-8"))
        return set((m.get("projects") or {}).keys())
    except Exception:
        return set(PROJECT_QUERIES.keys())


def search_project(project, kw, start, page_limit=20):
    """单个关键词全局搜索，返回 [(msg,chat,ct,content,sender,link)]。"""
    args = ["im", "+messages-search", "--as", "user",
            "--query", kw,
            "--start", start + "T00:00:00+08:00",
            "--page-all", "--no-reactions", "--format", "json"]
    if _CHAT_WHITELIST:
        args += ["--chat-id", ",".join(_CHAT_WHITELIST)]
    d = cli_retry(*args)
    if not d.get("ok"):
        print(f"[search] {project}/{kw} fail: {(d.get('error') or {}).get('message','')[:120]}")
        return []
    out = []
    for m in (d.get("data") or {}).get("messages", []):
        cid = m.get("chat_id", "")
        if cid in _BLOCKLIST:
            continue
        out.append({
            "message_id": m.get("message_id", ""),
            "chat_id": cid,
            "chat_name": m.get("chat_name", cid[:8]),
            "create_time": m.get("create_time", ""),
            "content": str(m.get("content", ""))[:600],
            "sender": (m.get("sender") or {}).get("name", "?"),
            "link": m.get("message_app_link", ""),
        })
    return out


def existing_im_keys():
    """拉 Episode 现有 im:{message_id} 键集合。"""
    out = set()
    offset = 0
    while True:
        d = cli("base", "+record-list", "--base-token", BASE, "--table-id", EPISODE,
                "--limit", "200", "--offset", str(offset), "--format", "json")
        if not d.get("ok"):
            break
        rows = d["data"].get("data", [])
        flds = d["data"].get("fields", [])
        idx = {n: i for i, n in enumerate(flds)}
        for row in rows:
            loc = str(row[idx["来源定位"]] or "")
            if loc.startswith("im:"):
                out.add(loc)
        if not d["data"].get("has_more"):
            break
        offset += len(rows)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-03-01")
    ap.add_argument("--projects", nargs="*", default=None, help="只跑指定项目，默认全部")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    existing = existing_im_keys()
    print(f"[check] 已有 {len(existing)} 条 im: 键")

    # 按项目+关键词搜，客户端去重（message_id 唯一）
    hits_by_msg = {}  # message_id -> {projects:set, row:data}
    targets = args.projects or list(PROJECT_QUERIES.keys())
    for proj in targets:
        for kw in PROJECT_QUERIES[proj]:
            for rec in search_project(proj, kw, args.start):
                mid = rec["message_id"]
                if not mid:
                    continue
                slot = hits_by_msg.setdefault(mid, {"projects": set(), "data": rec})
                slot["projects"].add(proj)
            time.sleep(0.3)

    print(f"[raw] 搜索命中 {len(hits_by_msg)} 条唯一消息")
    # 按时间先序排
    new = sorted(hits_by_msg.items(), key=lambda kv: kv[1]["data"]["create_time"])

    rows = []
    for mid, slot in new:
        rec = slot["data"]
        proj = "、".join(sorted(slot["projects"]))
        if len(rec["content"].strip()) < 12:
            continue
        key = f"im:{mid}"
        if key in existing:
            continue
        ct = rec["create_time"].replace(" ", "T") + ":00+08:00" if " " in rec["create_time"] else rec["create_time"]
        rows.append([
            f"[{rec['chat_name']}] {rec['sender']}: {rec['content'][:120]}",
            ct,
            proj,
            "IM群聊",
            key,
            "",
            "",
            rec["link"],
        ])
    print(f"[plan] 待入库 {len(rows)} 条")
    from collections import Counter
    print(Counter(r[2] for r in rows).most_common())

    if args.dry_run or not rows:
        for r in rows[:15]:
            print(" ", r[1][:16], r[2], "|", r[0][:100])
        return

    cols = ["事件摘要", "时间", "涉及项目", "来源类型", "来源定位", "关键数字", "动作", "原文链接"]
    ok_all = True
    for i in range(0, len(rows), 200):
        payload = {"fields": cols, "rows": rows[i:i + 200]}
        d = cli("base", "+record-batch-create", "--base-token", BASE, "--table-id", EPISODE,
                "--json", json.dumps(payload, ensure_ascii=False))
        print(f"[write] chunk {i//200} ok={d.get('ok')} {(d.get('error') or {}).get('message','')[:120]}")
        ok_all = ok_all and bool(d.get("ok"))
        time.sleep(1)
    print("[done]", ok_all)


if __name__ == "__main__":
    main()
