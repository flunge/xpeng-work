#!/usr/bin/env python3
"""
检查飞书群里的食谱反馈
读取 "个人话题" 群中的最近消息，
提取关于食谱的反馈意见（如 "不好吃"、"换一个" 等关键词），
保存到文件供后续处理。

用法: python3 scripts/check_feedback.py
"""

import json
import subprocess
import os
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
FEEDBACK_DIR = BASE_DIR / "notifications"
FEEDBACK_FILE = FEEDBACK_DIR / "feedback.md"

# 食谱推送群ID
CHAT_ID = "oc_c7c387e2f4a4a849aee503b04c62a442"

# 反馈关键词
FEEDBACK_KEYWORDS = [
    "不好吃", "不喜欢", "换一个", "换菜", "不想吃",
    "太多", "太少", "太油", "太咸", "太淡",
    "换个", "改一下", "调整", "不要", "别做",
    "重复", "一样", "same", "boring",
]


def run_lark(args):
    """运行 lark-cli 命令并返回解析后的 JSON"""
    cmd = ["lark-cli"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        print(f"⚠️ lark-cli 错误: {result.stderr[:200]}")
        return None
    return json.loads(result.stdout)


def check_feedback():
    """检查群中最近的反馈消息"""
    print(f"📬 正在检查食谱群反馈...")

    # 获取最近 50 条消息（24小时内）
    since = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S+08:00")

    result = run_lark([
        "im", "+chat-messages-list",
        "--chat-id", CHAT_ID,
        "--page-size", "50",
        "--sort", "desc",
    ])

    if not result or not result.get("ok"):
        print("❌ 无法获取群消息")
        return

    messages = result.get("data", {}).get("messages", [])
    if not messages:
        # 可能在不同层级
        messages = result.get("data", [])

    if not messages:
        print("ℹ️ 群中没有消息")
        return

    feedback_found = []

    for msg in messages:
        # 只看用户发的消息（不是 bot 自己发的）
        sender = msg.get("sender", {})
        sender_type = sender.get("sender_type", "")
        if sender_type != "user":
            continue

        msg_type = msg.get("msg_type", "")
        content_raw = msg.get("content", "")
        create_time = msg.get("create_time", "")

        # 提取文本内容
        text_content = ""
        if msg_type == "text":
            try:
                content_data = json.loads(content_raw)
                text_content = content_data.get("text", content_raw)
            except (json.JSONDecodeError, TypeError):
                text_content = content_raw

        # 检查是否包含反馈关键词
        found_keywords = [kw for kw in FEEDBACK_KEYWORDS if kw in text_content]

        if found_keywords:
            feedback_found.append({
                "time": create_time,
                "text": text_content.strip(),
                "keywords": found_keywords,
            })
            print(f"  📝 发现反馈 [{create_time}]: {text_content[:80]}...")

    if feedback_found:
        # 保存到文件
        os.makedirs(FEEDBACK_DIR, exist_ok=True)

        if FEEDBACK_FILE.exists():
            with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
                existing = f.read()
        else:
            existing = "# 📬 食谱反馈记录\n\n"

        with open(FEEDBACK_FILE, "w", encoding="utf-8") as f:
            f.write(f"# 📬 食谱反馈记录\n\n")
            f.write(f"---\n")
            f.write(f"最后检查: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")

            for fb in reversed(feedback_found):
                f.write(f"### {fb['time']}\n")
                f.write(f"**内容:** {fb['text']}\n")
                f.write(f"**关键词:** {', '.join(fb['keywords'])}\n\n")

            if existing and "最后检查" in existing:
                f.write("\n---\n### 历史记录\n\n")
                # Append old entries
                for line in existing.split("\n"):
                    if line.startswith("### 2") and not line.startswith(f"### {feedback_found[-1]['time']}"):
                        f.write(line + "\n")

        print(f"✅ 已保存 {len(feedback_found)} 条反馈到 {FEEDBACK_FILE}")
    else:
        print("✅ 暂无新的反馈")


if __name__ == "__main__":
    check_feedback()
