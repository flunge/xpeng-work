#!/usr/bin/env python3
"""
每天 09:00 — 获取当天上午所有关联 chat 并汇报。

拉取范围：
- 所有 @我 的消息
- 所有 p2p 找我的消息
- 群组里和组员相关的事情/任务

输出：推送到飞书单聊
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta

# 推送目标：与机器人的单聊会话
DM_CHAT = "oc_bc5bb378d432fca62a7786e26cf82578"
TARGET_USER_ID = "ou_f9cd23092a356c297d6a9f38fd7cfd5e"  # 李坤

# 核心群列表（chat_id → 群名）
CORE_CHATS = {
    "oc_bb2cf097e2d3efc34a4bc37ebd9225d9": "算法组组员群",
    "oc_e18d1d68d26c17f45f3ce3492e5143fe": "仿真算法组(+老板)",
    "oc_763ac0acd21f75e04d9945fcc139c5c1": "仿真核心日会群",
    "oc_66d514ceafe86807c9e6597087d76f7f": "班委群/SMG",
    "oc_a5278d3009a2142eaaa57c3bd9821aec": "李坤-高炳涛 私聊",
    "oc_b414f6a25f8725f81a3d9471bbc24c4b": "管理层+HRBP群",
    "oc_9162465555fd30580c78fe528147e1ef": "仿真部全员群",
    "oc_a19cd7f6afaf38d949a036b88779136d": "HR/招聘群",
    "oc_56b10049700694038662e72aa78e35d3": "会议纪要机器人群",
}

# 组员 p2p chat-id
MEMBER_P2P = {
    "oc_393a6cc854f8fe6c8cf1f3395c7412e9": "朱啸峰",
    "oc_803194d7d11cf983786f4972a4be781c": "周冯",
    "oc_76762db4579e74f2dada75d114928c97": "杨星昊",
    "oc_de9e1fe7cf844343b4856da067aeb175": "郑丽娜",
    "oc_b08e07e4c76e2e11bd7084905d03bd53": "瞿鑫宇",
    "oc_4ee65e6b57e2094f2971a86606e43cd7": "王禹丁",
    "oc_1543f82fdb4f9edb4fdcfea464142364": "裴健宏",
    "oc_619ea11ae3782e64613df49cc6622a15": "周蔚旭",
    "oc_a21652046a06ded833abfb561ac55521": "吕文杰",
    "oc_b7c8c4f1d078bc9710f5bb34fb559b27": "刘开拓",
}


def run_lark(args, timeout=30):
    cmd = ["lark-cli", "--as", "user"] + args
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def get_time_range(period):
    """根据时段返回 (start_time, end_time) Unix 时间戳"""
    now = datetime.now()
    today_9 = now.replace(hour=9, minute=0, second=0, microsecond=0)

    if period == "morning":
        start = today_9
        end = now
    elif period == "noon":
        start = today_9
        end = now.replace(hour=12, minute=0, second=0, microsecond=0)
        if now < start:
            return None, None
    elif period == "evening":
        noon = now.replace(hour=12, minute=0, second=0, microsecond=0)
        start = noon
        end = now
    else:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now

    return int(start.timestamp()), int(end.timestamp())


def parse_create_time(create_time):
    """解析 lark-cli 返回的 create_time，支持 '2026-07-17 09:24' 和 '2026-07-17 09:24:30'"""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return int(datetime.strptime(create_time, fmt).timestamp())
        except ValueError:
            continue
    return None


def fetch_chat_messages(chat_id, start_time, end_time, page_size=50, max_pages=2):
    """拉取指定群/会话在时间范围内的消息"""
    all_messages = []
    page_token = None

    for _ in range(max_pages):
        args = [
            "im", "+chat-messages-list",
            "--chat-id", chat_id,
            "--page-size", str(page_size),
            "--sort", "desc",
        ]
        if page_token:
            args += ["--page-token", page_token]

        result = run_lark(args)
        if not result or not result.get("ok"):
            break

        messages = result.get("data", {}).get("messages", [])
        if not messages:
            break

        # 过滤时间范围
        for msg in messages:
            create_time = msg.get("create_time", "")
            if not create_time:
                continue
            # create_time 格式可能为 "2026-07-17 09:24" 或 "2026-07-17 09:24:30"
            msg_ts = parse_create_time(create_time)
            if msg_ts is None:
                continue
            if start_time <= msg_ts <= end_time:
                all_messages.append(msg)
            elif msg_ts < start_time:
                return all_messages  # 已超出时间范围，停止

        page_token = result.get("data", {}).get("page_token")
        if not page_token or not result.get("data", {}).get("has_more"):
            break

    return all_messages


def extract_message_text(msg):
    """提取消息的文本内容"""
    msg_type = msg.get("msg_type", "")
    content_raw = msg.get("content", "")

    if msg_type == "text":
        try:
            content_data = json.loads(content_raw)
            return content_data.get("text", content_raw)
        except (json.JSONDecodeError, TypeError):
            return content_raw
    elif msg_type == "interactive":
        try:
            content_data = json.loads(content_raw)
            # 尝试从卡片中提取标题
            header = content_data.get("header", {})
            title = header.get("title", {})
            if isinstance(title, dict):
                return title.get("content", "[卡片消息]")
            return "[卡片消息]"
        except (json.JSONDecodeError, TypeError):
            return "[卡片消息]"
    else:
        return f"[{msg_type}]"


def collect_chat_summary(period):
    """收集指定时段的 chat 汇总"""
    start_time, end_time = get_time_range(period)
    if start_time is None:
        return None

    summary_items = []

    # 1. 拉取核心群消息
    for chat_id, chat_name in CORE_CHATS.items():
        messages = fetch_chat_messages(chat_id, start_time, end_time)
        if messages:
            chat_msgs = []
            for msg in messages:
                sender = msg.get("sender", {})
                sender_id = sender.get("sender_id", "")
                sender_type = sender.get("sender_type", "")
                text = extract_message_text(msg)
                create_time = msg.get("create_time", "")

                # 标记是否 @了我
                at_me = "@me" if msg.get("mentions") else ""

                chat_msgs.append({
                    "time": create_time,
                    "sender": sender_id[:8] if sender_id else "?",
                    "text": text[:200],
                    "at_me": at_me,
                })

            summary_items.append({
                "source": chat_name,
                "message_count": len(messages),
                "messages": chat_msgs[:10],  # 最多展示10条
            })

    # 2. 拉取组员 p2p 消息
    for chat_id, member_name in MEMBER_P2P.items():
        messages = fetch_chat_messages(chat_id, start_time, end_time)
        if messages:
            chat_msgs = []
            for msg in messages:
                text = extract_message_text(msg)
                create_time = msg.get("create_time", "")
                chat_msgs.append({
                    "time": create_time,
                    "sender": member_name,
                    "text": text[:200],
                })

            summary_items.append({
                "source": f"p2p: {member_name}",
                "message_count": len(messages),
                "messages": chat_msgs[:10],
            })

    return summary_items


def build_post_content(summary_items, period):
    """构建飞书 post 消息"""
    period_names = {
        "morning": "上午",
        "noon": "中午",
        "evening": "下午",
    }
    period_name = period_names.get(period, period)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    title = f"💬 Chat 汇报 {now_str}（{period_name}）"

    content_blocks = []

    if not summary_items:
        content_blocks.append([{"tag": "text", "text": "✅ 该时段无关联 chat 消息"}])
    else:
        total_messages = sum(item["message_count"] for item in summary_items)
        content_blocks.append([{"tag": "text", "text": f"📊 共 {len(summary_items)} 个会话，{total_messages} 条消息\n"}])

        for item in summary_items:
            content_blocks.append([{
                "tag": "text",
                "text": f"📌 {item['source']}（{item['message_count']} 条）"
            }])

            for msg in item["messages"]:
                at_me = msg.get("at_me", "")
                text = msg["text"].replace("\n", " ")[:100]
                content_blocks.append([{
                    "tag": "text",
                    "text": f"  {msg['time']} {at_me} [{msg['sender']}]: {text}"
                }])

            content_blocks.append([{"tag": "text", "text": ""}])

    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": content_blocks,
                }
            }
        },
    }


def push_message(payload):
    """推送到飞书单聊"""
    post_content = payload["content"]["post"]
    content_json = json.dumps(post_content, ensure_ascii=False)
    r = subprocess.run(
        ["lark-cli", "im", "+messages-send", "--as", "bot",
         "--chat-id", DM_CHAT, "--msg-type", "post", "--content", content_json],
        capture_output=True, text=True, timeout=30,
    )
    return r.returncode == 0


def main():
    period = sys.argv[1] if len(sys.argv) > 1 else "morning"

    summary_items = collect_chat_summary(period)
    if summary_items is None:
        print(f"无法获取 {period} 时段的时间范围")
        return

    payload = build_post_content(summary_items, period)
    success = push_message(payload)

    if success:
        print(f"✅ {period} chat 汇报已推送")
    else:
        print(f"❌ {period} chat 汇报推送失败")


if __name__ == "__main__":
    main()
