#!/usr/bin/env python3
"""Episode 事件流 · 每日增量入库（合并于 daily-sync 22:00 链）

规则（防止重复轰炸/重复入库）：
  1. 来源 A：会议纪要机器人群当日新增消息（docx token 提取），按条落行；
     dedupe key = 源定位（docx:{token}）。
  2. 来源 B：作战表/日报当日 revision 变化（若存在档位切换说明有新行，
     落「日报/作战表刷新」类行，源定位 = doc token + revision）。
     dedupe key = docu:{token}:rev{revision}。
  3. 已入库记录先拉「源定位」列集合，遇已存在跳过。
应用场景：daily-sync.sh 末尾调用；须与日期窗口对齐（默认今天本地时区）。
依赖：lark-cli --profile xpeng user 身份。
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys

PROFILE = "xpeng"
BASE = "NkIZb7eU7azZIEsegJ7cl2bfnUd"
TABLE = "Episode事件流"
ROBOT_CHAT = "oc_56b10049700694038662e72aa78e35d3"
BATTLE_TABLE = "SBUYwm8Lri9aJ6kmexFcBAuGnlh"   # Q3 作战表
STATE = "/tmp/episode_ingest_state.json"


def cli(*a):
    r = subprocess.run(["lark-cli", "--profile", PROFILE] + list(a) + ["--as", "user"],
                       capture_output=True, text=True, timeout=180)
    try:
        return json.loads(r.stdout or r.stderr)
    except Exception:
        return {"ok": False, "raw": (r.stdout or r.stderr)[:300]}


def existing_keys():
    d = cli("base", "+record-list", "--base-token", BASE,
            "--table-id", TABLE, "--limit", "500", "--format", "json")
    data = d.get("data") or {}
    rows = data.get("data") or []
    fields = data.get("fields") or []
    keys = set()
    if "来源定位" in fields:
        idx = fields.index("来源定位")
        for row in rows:
            v = row[idx] if idx < len(row) else ""
            if isinstance(v, list):
                v = "".join(x.get("text", "") for x in v if isinstance(x, dict))
            if v:
                keys.add(v)
    return keys


def today_window():
    today = dt.date.today()
    return dt.datetime.combine(today, dt.time(0, 0, 0)).isoformat() + "+08:00", \
           dt.datetime.combine(today, dt.time(23, 59, 59)).isoformat() + "+08:00"


def fetch_robot_new():
    """会议纪要机器人群当日新消息 → [{title, token, create_time}]"""
    start, end = today_window()
    d = cli("im", "+chat-messages-list", "--chat-id", ROBOT_CHAT,
            "--start", start, "--end", end, "--order", "asc",
            "--page-size", "50")
    msgs = (d.get("data") or {}).get("messages") or []
    out = []
    for m in msgs:
        c = json.dumps(m, ensure_ascii=False)
        toks = re.findall(r"docx/([A-Za-z0-9]+)", c)
        for tok in toks:
            title = "智能纪要"
            out.append({"title": title, "token": tok,
                        "create_time": m.get("create_time", "")})
    return out


def battle_revision_row():
    d = cli("docs", "+fetch", "--doc", f"https://xiaopeng.feishu.cn/docx/{BATTLE_TABLE}")
    if not d.get("ok"):
        return []
    rev = d["data"]["document"].get("edit_info", {}).get("revision") \
          or d["data"]["document"].get("revision")
    st = json.load(open(STATE)) if os.path.exists(STATE) else {}
    last = st.get("battle_revision", 0)
    if not last:
        st["battle_revision"] = rev or 0
        json.dump(st, open(STATE, "w"), ensure_ascii=False)
        return []  # 首次只建基线
    if rev and rev > last:
        st["battle_revision"] = rev
        json.dump(st, open(STATE, "w"), ensure_ascii=False)
        return [{
            "时间": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "来源类型": "日报作战表",
            "来源定位": f"docu:{BATTLE_TABLE}:rev{rev}",
            "事件摘要": f"作战表 revision {last}→{rev}（有新行）",
            "涉及项目": "多项目",
            "原文链接": f"https://xiaopeng.feishu.cn/docx/{BATTLE_TABLE}",
        }]
    return []


def robot_rows():
    rows = []
    for it in fetch_robot_new():
        rows.append({
            "时间": it["create_time"],
            "来源类型": "会议纪要逐字稿",
            "来源定位": f"docx:{it['token']}",
            "事件摘要": f"{it['title']}（{it['token'][:8]}）",
            "涉及项目": "",
            "原文链接": f"https://xiaopeng.feishu.cn/docx/{it['token']}",
        })
    return rows


def insert(rows):
    payload = {
        "fields": ["事件摘要", "时间", "来源类型", "来源定位",
                   "涉及项目", "涉及人物", "关键数字", "动作", "原文链接"],
        "rows": [[r.get("事件摘要", ""), r["时间"], r["来源类型"], r["来源定位"],
                  r.get("涉及项目", ""), r.get("涉及人物", ""), r.get("关键数字", ""),
                  r.get("动作", ""), r.get("原文链接", "")] for r in rows],
    }
    return cli("base", "+record-batch-create", "--base-token", BASE,
               "--table-id", TABLE, "--json", json.dumps(payload, ensure_ascii=False))


def main():
    dry = "--dry-run" in sys.argv
    rows = robot_rows() + battle_revision_row()
    keys = existing_keys()
    new_rows = [r for r in rows if r["来源定位"] not in keys]
    print(f"based_rows={len(rows)} new={len(new_rows)}")
    if dry:
        for r in new_rows:
            print("  +", r["时间"], r["来源类型"], r["事件摘要"][:60])
        return
    if not new_rows:
        return
    resp = insert(new_rows)
    ok = resp.get("ok")
    print("insert:", "ok" if ok else resp)


if __name__ == "__main__":
    main()
