#!/usr/bin/env python3
"""
Local Agent Bot — 常驻飞书消息监听代理

职责：
1. 以用户身份轮询 DM_CHAT 的最近消息。
2. 收到用户消息后：
   - 简单关键词（食谱 / 风险 / 更新今日工作 / 帮助）直接调用 lingxi-trigger.sh 并回复。
   - 复杂消息写入 inbox JSONL，由本地 agent 轮询处理。
3. 通过本地文件 IPC 与 local-agent-inbox-agent 协作。

常驻方式：由 launchd UserAgent com.xpeng.local-agent-bot.plist 管理，KeepAlive=true。
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent.parent
TRIGGER = WORKSPACE / "lingxi-trigger.sh"
INBOX_PATH = WORKSPACE / "team" / "memory" / "daily-sync" / "incoming_via_bot.jsonl"
LOG_PATH = WORKSPACE / "team" / "memory" / "daily-sync" / "local-agent-bot.log"
PROCESSED_IDS_PATH = WORKSPACE / "team" / "memory" / "daily-sync" / "local-agent-bot-processed-ids.json"

DM_CHAT = "oc_bc5bb378d432fca62a7786e26cf82578"
BOT_APP_ID = "cli_aaad7e4c46f95bb4"

POLL_INTERVAL_SEC = 3
LOOKBACK_MINUTES = 2


def log(msg: str):
    t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{t}] {msg}"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        print(line, flush=True)


def send_text(text: str):
    content = json.dumps({"text": text}, ensure_ascii=False)
    r = subprocess.run(
        ["lark-cli", "im", "+messages-send", "--as", "bot",
         "--chat-id", DM_CHAT, "--msg-type", "text", "--content", content],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        log(f"[send] failed: {(r.stderr or r.stdout).strip()[:200]}")


def execute_task(task_name: str) -> bool:
    log(f"[task] trigger {task_name}")
    r = subprocess.run(
        ["bash", str(TRIGGER), task_name],
        capture_output=True, text=True, timeout=300,
    )
    ok = r.returncode == 0
    if not ok:
        log(f"[task] {task_name} failed: {(r.stderr or r.stdout).strip()[:300]}")
    else:
        log(f"[task] {task_name} done")
    return ok


def append_inbox(message_id: str, sender_id: str, text: str):
    entry = {
        "received_at": datetime.now().isoformat(),
        "message_id": message_id,
        "sender_id": sender_id,
        "text": text,
        "status": "pending",
    }
    INBOX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(INBOX_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    log(f"[inbox] appended message {message_id}")


CRITICISM_MARKERS = [
    "干嘛", "干什么", "写这么", "发这么", "这么多", "一堆", "流水账",
    "不要", "别发", "别给我", "够了", "烦", "垃圾", "没用", "不对",
    "应该", "而不是", "不要给我"
]


def looks_like_criticism(text: str) -> bool:
    """如果文本是抱怨/反馈/批评，就不触发任务。"""
    return any(m in text for m in CRITICISM_MARKERS)


def is_simple_keyword(text: str) -> tuple[bool, str, str]:
    """判断是否为简单关键词指令。返回 (is_simple, task_name, reply_text)。"""
    if looks_like_criticism(text):
        return False, "", ""

    t = text.lower()
    if any(k in t for k in ["食谱", "food", "今天吃什么", "明日食谱", "今日食谱", "吃什么"]):
        return True, "food", "正在推送今日/明日食谱…"
    if any(k in t for k in ["风险播报", "项目风险"]):
        return True, "risk", "正在推送项目风险播报…"
    if text.strip().startswith("风险"):
        return True, "risk", "正在推送项目风险播报…"
    if any(k in t for k in ["更新今日工作", "会议纪要", "memory"]):
        return True, "sync", "正在更新今日工作记忆…"
    if any(k in t for k in ["同步"]):
        return True, "sync", "正在同步…"
    if any(k in t for k in ["帮助", "help", "能做什么", "怎么用"]):
        return True, "", "Local Agent 可以帮你：\n• 发“食谱” → 推送今日/明日食谱\n• 发“风险” → 推送项目风险播报\n• 发“更新今日工作” → 采集会议纪要并更新记忆\n复杂问题我会转给本地 agent 处理。"
    return False, "", ""


def load_processed_ids() -> set:
    if not PROCESSED_IDS_PATH.exists():
        return set()
    try:
        data = json.loads(PROCESSED_IDS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return set(data)
    except Exception:
        pass
    return set()


def save_processed_ids(ids: set):
    PROCESSED_IDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(PROCESSED_IDS_PATH, "w", encoding="utf-8") as f:
            json.dump(sorted(ids), f, ensure_ascii=False)
    except Exception as e:
        log(f"[state] save processed ids failed: {e}")


def handle_message(message_id: str, sender_id: str, text: str):
    log(f"[recv] from {sender_id}: {text[:120]}")

    is_simple, task, reply = is_simple_keyword(text)
    if is_simple:
        send_text(reply)
        if task:
            execute_task(task)
    else:
        send_text("已收到，本地 agent 处理中…")
        append_inbox(message_id, sender_id, text)


def iso_now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def iso_minutes_ago(minutes: int) -> str:
    t = datetime.now(timezone(timedelta(hours=8))) - timedelta(minutes=minutes)
    return t.strftime("%Y-%m-%dT%H:%M:%S+08:00")


def poll_messages(processed_ids: set) -> int:
    """轮询最近消息，返回本次处理的新消息数。"""
    start = iso_minutes_ago(LOOKBACK_MINUTES)
    r = subprocess.run(
        ["lark-cli", "im", "+chat-messages-list", "--as", "user",
         "--chat-id", DM_CHAT, "--start", start, "--order", "asc",
         "--page-size", "50"],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        err = (r.stderr or r.stdout).strip()[:200]
        if "unauthorized" in err.lower() or "token" in err.lower():
            log(f"[poll] auth error: {err}")
        else:
            log(f"[poll] failed: {err}")
        return 0

    try:
        payload = json.loads(r.stdout)
    except json.JSONDecodeError:
        log("[poll] invalid json")
        return 0

    if not payload.get("ok"):
        err = payload.get("error", {}).get("message", "unknown")
        log(f"[poll] error: {err}")
        return 0

    messages = payload.get("data", {}).get("messages", [])
    count = 0
    new_ids = set()
    for msg in messages:
        message_id = msg.get("message_id")
        sender = msg.get("sender", {})
        sender_id = sender.get("id")
        sender_type = sender.get("sender_type")
        msg_type = msg.get("msg_type")
        content = msg.get("content", "")

        if not message_id:
            continue
        if message_id in processed_ids:
            continue
        if sender_type == "app" or sender_id == BOT_APP_ID:
            new_ids.add(message_id)
            continue
        if msg_type != "text" or not isinstance(content, str) or not content:
            new_ids.add(message_id)
            continue

        text = content.strip()
        if not text:
            new_ids.add(message_id)
            continue

        handle_message(message_id, sender_id or "unknown", text)
        new_ids.add(message_id)
        count += 1

    processed_ids.update(new_ids)
    save_processed_ids(processed_ids)
    return count


def main():
    log("=== Local Agent Bot started ===")
    processed_ids = load_processed_ids()
    log(f"[state] loaded {len(processed_ids)} processed message ids")

    # 启动时发送一条上线通知
    try:
        send_text("Local Agent Bot 已上线。可以发“食谱”“风险”“更新今日工作”。复杂问题我会转给本地 agent 处理。")
    except Exception as e:
        log(f"[startup] send failed: {e}")

    while True:
        try:
            count = poll_messages(processed_ids)
            if count:
                log(f"[cycle] processed {count} message(s)")
        except Exception as e:
            log(f"[cycle] error: {e}")
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("=== stopped by user ===")
        sys.exit(0)
