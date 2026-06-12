#!/bin/bash
# 李坤数字分身 - 每日数据同步脚本
# 由 macOS LaunchAgent 在每天 22:07 触发
# 采集：日历 + 会议纪要 + Q2 Wiki + IM组员搜索 + IM群聊 + @我消息

set -euo pipefail

LARK_CLI="/opt/homebrew/bin/lark-cli"
# 项目路径（所有文件统一管理在 /Users/xpeng/Documents/team/ 下）
PROJECT_DIR="/Users/xpeng/Documents/team"
SYNC_DIR="$PROJECT_DIR/memory/daily-sync"
TODAY=$(date +%Y-%m-%d)
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
