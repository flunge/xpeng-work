#!/usr/bin/env python3
"""
每天 09:00 — 推送 AI 圈头部 10 条新闻（去重）。

数据源：ddgs (DuckDuckGo)
输出：推送到飞书单聊
"""

import json
import subprocess
import time
from datetime import datetime
from ddgs import DDGS

DM_CHAT = "oc_bc5bb378d432fca62a7786e26cf82578"

# 中文关键词 → 用 text 搜索（news 对中文返回空）
CN_QUERIES = [
    "人工智能 最新新闻",
    "大模型 最新进展",
    "自动驾驶 AI 最新",
    "具身智能 机器人 最新",
    "AI芯片 算力 最新",
]

# 英文关键词 → 用 news 搜索
EN_QUERIES = [
    "AI", "OpenAI", "Tesla AI", "robotics", "autonomous driving",
]


def summarize_body(body, max_chars=300):
    """按句号/分号边界截取正文，不硬截断。"""
    if not body:
        return ""
    if len(body) <= max_chars:
        return body.strip()
    truncated = body[:max_chars]
    # 在最后一个句号/问号/感叹号处截断
    for sep in ["。", "！", "？", "；", ". ", "? ", "! "]:
        idx = truncated.rfind(sep)
        if idx > max_chars // 2:
            return truncated[:idx + len(sep)].strip()
    return truncated.strip() + "…"


def search_ai_news():
    results = []
    with DDGS() as ddgs:
        # 中文：text 搜索
        for q in CN_QUERIES:
            for attempt in range(3):
                try:
                    for r in ddgs.text(q, max_results=5):
                        r["_search_type"] = "text"
                        results.append(r)
                    break
                except Exception:
                    time.sleep(2)

        # 英文：news 搜索
        for q in EN_QUERIES:
            for attempt in range(3):
                try:
                    for r in ddgs.news(q, max_results=5):
                        r["_search_type"] = "news"
                        results.append(r)
                    break
                except Exception:
                    time.sleep(2)

    # 去重（按标题）
    seen_titles = set()
    unique = []
    for r in results:
        title = r.get("title", "").lower()
        if title and title not in seen_titles:
            seen_titles.add(title)
            unique.append(r)

    return unique[:10]


def build_post_content(news_items):
    now_str = datetime.now().strftime("%Y-%m-%d")

    title = f"🤖 AI 圈新闻 {now_str}"

    content_blocks = [
        [{"tag": "text", "text": f"📰 今日 AI 圈 {len(news_items)} 条头部新闻\n"}],
    ]

    for i, item in enumerate(news_items, 1):
        title_text = item.get("title", "")
        # text 搜索用 href，news 搜索用 url
        url = item.get("href") or item.get("url") or ""
        source = item.get("source", "")
        date = item.get("date", "")
        body = summarize_body(item.get("body", ""))

        lines = [f"{i}. {title_text}"]
        if body:
            lines.append(f"   {body}")
        meta_parts = []
        if source:
            meta_parts.append(f"来源: {source}")
        if date:
            meta_parts.append(date)
        if meta_parts:
            lines.append("   " + " | ".join(meta_parts))
        if url:
            lines.append(f"   🔗 {url}")

        content_blocks.append([{
            "tag": "text",
            "text": "\n".join(lines) + "\n"
        }])

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
    post_content = payload["content"]["post"]
    content_json = json.dumps(post_content, ensure_ascii=False)
    r = subprocess.run(
        ["lark-cli", "im", "+messages-send", "--as", "bot",
         "--chat-id", DM_CHAT, "--msg-type", "post", "--content", content_json],
        capture_output=True, text=True, timeout=30,
    )
    return r.returncode == 0


def main():
    try:
        news_items = search_ai_news()
        if not news_items:
            print("未获取到新闻")
            return

        payload = build_post_content(news_items)
        if push_message(payload):
            print("✅ AI 新闻已推送")
        else:
            print("❌ 推送失败")
    except Exception as e:
        print(f"❌ 错误: {e}")


if __name__ == "__main__":
    main()
