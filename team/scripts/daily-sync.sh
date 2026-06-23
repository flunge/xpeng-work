#!/bin/bash
# 李坤数字分身 - 每日数据同步脚本
# 由 macOS LaunchAgent 在每天 22:07 触发
# 采集：日历 + 会议纪要 + Q2 Wiki + IM组员搜索 + IM群聊 + @我消息

set -euo pipefail

LARK_CLI="lark-cli"
# 项目路径（相对脚本定位：scripts/ 的上一级即项目根 team/）
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SYNC_DIR="$PROJECT_DIR/memory/daily-sync"
# 可传入日期参数回填历史（默认今天）：daily-sync.sh 2026-06-12
TODAY="${1:-$(date +%Y-%m-%d)}"
OUTFILE="$SYNC_DIR/$TODAY.json"
LOGFILE="$SYNC_DIR/sync.log"
TMPFILE="$OUTFILE.tmp"

VC_CHAT_ID="oc_56b10049700694038662e72aa78e35d3"
WIKI_DOC="https://xiaopeng.feishu.cn/wiki/SBUYwm8Lri9aJ6kmexFcBAuGnlh"

# 组员名单（用于IM搜索，排除产假的冯美慧）
TEAM_MEMBERS=("郑丽娜" "杨星昊" "周蔚旭" "裴健宏" "周冯" "吕文杰" "王禹丁" "朱啸峰" "瞿鑫宇" "严潇竹" "靳希睿")
# 组内关键群聊
TEAM_CHAT_IDS=(
  "oc_bb2cf097e2d3efc34a4bc37ebd9225d9|仿真算法组"
  "oc_af64a74c337b188fd3a95734e9aca29c|Simworld MR Sync"
)
# 其他关注群聊（中心级通知等）
WATCH_CHAT_IDS=(
  "oc_4b720d9eedc8192372fb5af253dfcf12|通用智能中心"
)

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOGFILE"
}

# ---------- 用 Python 构建完整 JSON ----------
python3 << PYEOF > "$TMPFILE" 2>>"$LOGFILE"
import json, subprocess, sys, os, re
from datetime import datetime

LARK_CLI = "$LARK_CLI"
SYNC_DIR = "$SYNC_DIR"
TODAY = "$TODAY"
VC_CHAT_ID = "$VC_CHAT_ID"
WIKI_DOC = "$WIKI_DOC"

# 组员名单 + 关键群聊
TEAM_MEMBERS = ["郑丽娜", "杨星昊", "周蔚旭", "裴健宏", "周冯", "吕文杰", "王禹丁", "朱啸峰", "瞿鑫宇", "严潇竹", "靳希睿"]
TEAM_CHATS = [
    ("oc_bb2cf097e2d3efc34a4bc37ebd9225d9", "仿真算法组"),
    ("oc_af64a74c337b188fd3a95734e9aca29c", "Simworld MR Sync"),
]
WATCH_CHATS = [
    ("oc_4b720d9eedc8192372fb5af253dfcf12", "通用智能中心"),
]

def run_lark(args):
    """Run lark-cli and return parsed JSON, or error dict."""
    try:
        result = subprocess.run([LARK_CLI] + args, capture_output=True, text=True, timeout=60)
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
        return {"error": f"exit={result.returncode}", "stderr": result.stderr[:500]}
    except Exception as e:
        return {"error": str(e)}

result = {
    "date": TODAY,
    "sync_time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
}

# Step 1: 日历
sys.stderr.write(f"[{datetime.now().strftime('%H:%M:%S')}] Step 1: Calendar...\n")
cal = run_lark(["calendar", "+agenda", "--as", "user", "--format", "json"])
events = cal.get("data", cal) if isinstance(cal, dict) else []
if isinstance(events, list):
    result["calendar"] = events
    sys.stderr.write(f"  Calendar: {len(events)} events\n")
else:
    result["calendar"] = cal
    sys.stderr.write(f"  Calendar: error\n")

# Step 2: VC Assistant 消息
sys.stderr.write(f"[{datetime.now().strftime('%H:%M:%S')}] Step 2: VC messages...\n")
vc = run_lark(["im", "+chat-messages-list", "--as", "user", "--chat-id", VC_CHAT_ID, "--format", "json", "--page-size", "30"])
result["vc_messages"] = vc

# 提取今天的文档链接
msgs = vc.get("data", {}).get("messages", []) if isinstance(vc, dict) else []
today_docs = []
for m in msgs:
    if TODAY in m.get("create_time", ""):
        content = m.get("content", "")
        doc_match = re.search(r'docx/([A-Za-z0-9]+)', content)
        if doc_match:
            today_docs.append({
                "token": doc_match.group(1),
                "url": f'https://xiaopeng.feishu.cn/docx/{doc_match.group(1)}',
                "time": m.get("create_time"),
                "msg_type": m.get("msg_type")
            })
        mins_match = re.search(r'minutes/([a-z0-9]+)', content)
        if mins_match:
            today_docs.append({
                "minutes_id": mins_match.group(1),
                "url": f'https://xiaopeng.feishu.cn/minutes/{mins_match.group(1)}',
                "time": m.get("create_time")
            })
result["today_docs"] = today_docs
sys.stderr.write(f"  Found {len(today_docs)} docs for today\n")

# Step 3: 读取每个会议文档（智能纪要 + 文字记录）
sys.stderr.write(f"[{datetime.now().strftime('%H:%M:%S')}] Step 3: Reading meeting docs...\n")
meeting_docs = []
for doc in today_docs:
    token = doc.get("token")
    if token:
        sys.stderr.write(f"  Reading summary: {token}\n")
        summary = run_lark(["docs", "+fetch", "--api-version", "v2", "--doc", token, "--format", "json"])
        doc_entry = {"token": token, "summary": summary}

        # 从智能纪要中提取文字记录链接
        summary_content = summary.get("data", {}).get("document", {}).get("content", "") if isinstance(summary, dict) else ""
        transcript_match = re.search(r'docx/([A-Za-z0-9]+)[^"]*"[^>]*>文字记录', summary_content)
        if not transcript_match:
            transcript_match = re.search(r'wiki/([A-Za-z0-9]+)[^"]*"[^>]*>文字记录', summary_content)
        if transcript_match:
            transcript_token = transcript_match.group(1)
            sys.stderr.write(f"  Reading transcript: {transcript_token}\n")
            transcript = run_lark(["docs", "+fetch", "--api-version", "v2", "--doc", transcript_token, "--format", "json"])
            doc_entry["transcript_token"] = transcript_token
            doc_entry["transcript"] = transcript

        meeting_docs.append(doc_entry)
result["meeting_docs"] = meeting_docs

# Step 4: Wiki 文档
sys.stderr.write(f"[{datetime.now().strftime('%H:%M:%S')}] Step 4: Reading Wiki...\n")
wiki = run_lark(["docs", "+fetch", "--api-version", "v2", "--doc", WIKI_DOC, "--doc-format", "markdown", "--format", "json"])
result["wiki_doc"] = wiki

# Step 5: IM - 组员关键词搜索
sys.stderr.write(f"[{datetime.now().strftime('%H:%M:%S')}] Step 5: IM member searches...\n")
im_member_hits = {}
for name in TEAM_MEMBERS:
    try:
        r = run_lark(["im", "+messages-search", "--as", "user",
            "--query", name,
            "--start", f"{TODAY}T00:00:00+08:00",
            "--end", f"{TODAY}T23:59:59+08:00",
            "--page-all", "--format", "json"])
        msgs = r.get("data", {}).get("messages", []) if isinstance(r, dict) else []
        if msgs:
            im_member_hits[name] = msgs
            sys.stderr.write(f"  {name}: {len(msgs)} hits\n")
        else:
            sys.stderr.write(f"  {name}: 0\n")
    except Exception as e:
        sys.stderr.write(f"  {name}: error - {e}\n")
result["im_member_searches"] = im_member_hits

# Step 6: IM - 组内群聊消息
sys.stderr.write(f"[{datetime.now().strftime('%H:%M:%S')}] Step 6: IM team chat messages...\n")
im_chat_messages = {}
all_chats = TEAM_CHATS + WATCH_CHATS
for chat_id, chat_name in all_chats:
    try:
        r = run_lark(["im", "+chat-messages-list", "--as", "user",
            "--chat-id", chat_id,
            "--start", f"{TODAY}T00:00:00+08:00",
            "--end", f"{TODAY}T23:59:59+08:00",
            "--page-all", "--format", "json"])
        msgs = r.get("data", {}).get("messages", []) if isinstance(r, dict) else []
        today_msgs = [m for m in msgs if TODAY in str(m.get("create_time", ""))]
        if today_msgs:
            im_chat_messages[chat_name] = today_msgs
            sys.stderr.write(f"  {chat_name}: {len(today_msgs)} messages today\n")
        else:
            sys.stderr.write(f"  {chat_name}: 0\n")
    except Exception as e:
        sys.stderr.write(f"  {chat_name}: error - {e}\n")
result["im_chat_messages"] = im_chat_messages

# Step 7: IM - @我的消息
sys.stderr.write(f"[{datetime.now().strftime('%H:%M:%S')}] Step 7: IM @me...\n")
try:
    at_me = run_lark(["im", "+messages-search", "--as", "user",
        "--is-at-me",
        "--start", f"{TODAY}T00:00:00+08:00",
        "--end", f"{TODAY}T23:59:59+08:00",
        "--page-all", "--format", "json"])
    at_msgs = at_me.get("data", {}).get("messages", []) if isinstance(at_me, dict) else []
    result["im_at_me"] = at_msgs
    sys.stderr.write(f"  @me: {len(at_msgs)} messages\n")
except Exception as e:
    result["im_at_me"] = []
    sys.stderr.write(f"  @me: error - {e}\n")

# Step 8: 生成每日摘要（即使不开 Claude Code 也能更新记忆文件）
# Step 9: 分发今日会议内容到各项目 ledger
sys.stderr.write(f"[{datetime.now().strftime('%H:%M:%S')}] Step 9: Dispatching meeting content to ledgers...\n")

PROJECT_DIR = "$PROJECT_DIR"

# 项目-关键词映射，用于匹配会议内容属于哪些 ledger
PROJECT_KEYWORDS = {
    "HIL/HIL链路部署":            ["HIL链路", "HIL效率", "朱啸峰", "VM搭建", "台架", "3DGS", "节点"],
    "HIL/慢速模式":               ["慢速模式", "慢速", "瞿鑫宇", "VIL", "Chief", "nvfix"],
    "SIL/车型泛化":               ["车型泛化", "泛化", "裴健宏"],
    "SIL/Fixer优化":              ["Fixer", "difix", "Diffusion", "nvfixer", "周冯"],
    "SIL/CLIP-IQA":               ["CLIP", "IQA", "图像质量", "王禹丁"],
    "Agents/复现率Agent":         ["复现率", "吕文杰", "郑丽娜", "严潇竹"],
    "Agents/TopDiff-Agent":       ["TopDiff", "top diff", "Top Diff", "变道"],
    "Agents/Prompt-Agent":        ["prompt", "误报"],
    "场景&生产/RC路线":           ["RC路线", "广州", "刘开拓", "UCP", "长里程"],
    "场景&生产/闭环场景集推进":   ["闭环场景", "场景集", "毕业", "黄佰民"],
    "场景&生产/极速模式":         ["极速模式", "周蔚旭", "seal链路"],
    "场景&生产/场景编辑":         ["场景编辑", "裴健宏", "Smart Agent"],
    "场景&生产/AVM鱼眼":          ["AVM", "鱼眼", "cam9", "Mei"],
    "场景&生产/WM-内部探索":      ["World Model", "WM", "靳希睿", "DiffSynth"],
}

def strip_xml_tags(text):
    import re
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def extract_relevant_snippet(plain_text, keywords, max_chars=600):
    """Find up to 2 keyword-adjacent snippets from plain text."""
    snippets = []
    seen_pos = set()
    for kw in keywords:
        idx = 0
        while True:
            pos = plain_text.lower().find(kw.lower(), idx)
            if pos == -1:
                break
            bucket = pos // 300
            if bucket not in seen_pos:
                seen_pos.add(bucket)
                start = max(0, pos - 100)
                end = min(len(plain_text), pos + max_chars)
                snippets.append(plain_text[start:end].strip())
            idx = pos + 1
            if len(snippets) >= 2:
                break
        if len(snippets) >= 2:
            break
    return snippets

def get_ledger_path(proj_key):
    """Return absolute path to ledger.md for a project key."""
    parts = proj_key.split("/")
    return os.path.join(PROJECT_DIR, "memory", "projects", *parts, "ledger.md")

def append_to_ledger(ledger_path, date_str, snippets, source_title, source_id):
    """Append a dated entry to the 时间线 section of a ledger.md."""
    if not os.path.exists(ledger_path):
        sys.stderr.write(f"    [WARN] ledger not found: {ledger_path}\n")
        return False

    with open(ledger_path, "r") as f:
        content = f.read()

    # Check if this date entry already exists
    if f"### {date_str}" in content:
        sys.stderr.write(f"    [SKIP] {date_str} already in {ledger_path}\n")
        return False

    # Build new entry
    snippet_text = "\n".join(f"- {s[:400]}" for s in snippets[:2])
    new_entry = f"\n### {date_str}（日会）\n{snippet_text}\n- 来源：{source_title} {source_id}\n"

    # Insert after "## 时间线" heading (before first existing ###)
    timeline_pos = content.find("## 时间线")
    if timeline_pos == -1:
        # Append at end
        content += new_entry
    else:
        insert_pos = content.find("\n### ", timeline_pos)
        if insert_pos == -1:
            content += new_entry
        else:
            content = content[:insert_pos] + new_entry + content[insert_pos:]

    with open(ledger_path, "w") as f:
        f.write(content)

    # Update last_updated in frontmatter
    content_updated = re.sub(r'(last_updated:\s*)\S+', f'\\g<1>{date_str}', content)
    if content_updated != content:
        with open(ledger_path, "w") as f:
            f.write(content_updated)

    sys.stderr.write(f"    [OK] appended {date_str} to {ledger_path}\n")
    return True

ledger_updates = []
# Step 9 粗糙关键词派发默认【跳过】——高质量的 ledger/people 更新统一走 daily-sync.js agent 工作流。
# 如确需启用这种 fallback 自动派发，显式设置 SKIP_LEDGER_DISPATCH=0。
SKIP_DISPATCH = os.environ.get("SKIP_LEDGER_DISPATCH", "1") == "1"

for doc_entry in (meeting_docs if not SKIP_DISPATCH else []):
    # Try smart summary first, fall back to transcript
    for content_key in ["summary", "transcript"]:
        doc_data = doc_entry.get(content_key, {})
        if not isinstance(doc_data, dict):
            continue
        raw_content = doc_data.get("data", {}).get("document", {}).get("content", "")
        if not raw_content:
            continue
        plain = strip_xml_tags(raw_content)
        title = doc_data.get("data", {}).get("document", {}).get("title", "") or doc_entry.get("token", "")
        token = doc_entry.get("token", "") if content_key == "summary" else doc_entry.get("transcript_token", "")

        for proj_key, keywords in PROJECT_KEYWORDS.items():
            snippets = extract_relevant_snippet(plain, keywords)
            if snippets:
                ledger_path = get_ledger_path(proj_key)
                updated = append_to_ledger(ledger_path, TODAY, snippets, title, token)
                if updated:
                    ledger_updates.append(f"{proj_key} ← {title}")

        # Only process summary once (don't double-append from transcript)
        break

sys.stderr.write(f"  Ledger updates: {len(ledger_updates)}\n")
for u in ledger_updates:
    sys.stderr.write(f"    · {u}\n")

result["ledger_updates"] = ledger_updates

# Step 8: Writing daily summary...
sys.stderr.write(f"[{datetime.now().strftime('%H:%M:%S')}] Step 8: Writing daily summary...\n")
summary_lines = [f"## {TODAY} 自动采集摘要\n"]
# 会议
for doc in today_docs:
    summary_lines.append(f"- 📋 会议纪要: {doc.get('url','?')} ({doc.get('time','?')})")
# 日历
if isinstance(result.get("calendar"), list):
    for ev in result["calendar"]:
        s = ev.get("start_time",{}).get("datetime","")[:16]
        summary_lines.append(f"- 📅 {ev.get('summary','?')} @{s}")
# Wiki 版本
rev = result.get("wiki_doc",{}).get("data",{}).get("document",{}).get("revision_id","?")
summary_lines.append(f"- 📝 Q2 Wiki rev: {rev}")
# IM 统计
total_im_hits = sum(len(v) for v in im_member_hits.values()) if isinstance(im_member_hits, dict) else 0
total_chat_msgs = sum(len(v) for v in im_chat_messages.values()) if isinstance(im_chat_messages, dict) else 0
total_at_me = len(result.get("im_at_me", []))
summary_lines.append(f"- 💬 IM: {total_im_hits}组员命中 + {total_chat_msgs}群聊消息 + {total_at_me}条@我")
# 组员命中详情
if im_member_hits:
    summary_lines.append("  - 组员提到:")
    for name, msgs in im_member_hits.items():
        summary_lines.append(f"    · {name} ({len(msgs)}条)")
# 群聊活跃详情
if im_chat_messages:
    summary_lines.append("  - 群聊活跃:")
    for chat_name, msgs in im_chat_messages.items():
        summary_lines.append(f"    · {chat_name} ({len(msgs)}条)")
# Ledger 更新详情
ledger_updates = result.get("ledger_updates", [])
if ledger_updates:
    summary_lines.append(f"- 📂 Ledger 更新: {len(ledger_updates)}个项目")
    for u in ledger_updates:
        summary_lines.append(f"    · {u}")
summary_lines.append("")

INBOX = os.path.join(SYNC_DIR, "inbox.md")
existing = ""
if os.path.exists(INBOX):
    with open(INBOX) as f:
        existing = f.read()
with open(INBOX, "w") as f:
    f.write("\n".join(summary_lines) + existing)

# 写入 JSON
with open("$TMPFILE", "w") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

sys.stderr.write(f"[{datetime.now().strftime('%H:%M:%S')}] Done → {TODAY}.json + inbox.md\n")
PYEOF

# ---------- 验证并完成 ----------
if python3 -c "import json; json.load(open('$TMPFILE'))" 2>/dev/null; then
    mv "$TMPFILE" "$OUTFILE"
    log "✅ Sync complete → $OUTFILE"
    find "$SYNC_DIR" -name "*.json" -mtime +30 -delete 2>/dev/null || true
else
    log "❌ JSON validation failed, output left at $TMPFILE"
    exit 1
fi
