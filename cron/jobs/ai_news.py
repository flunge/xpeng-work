#!/usr/bin/env python3
"""
每天 09:00 — 推送 AI 圈头部 10 条新闻（去重）。

重点关注：大模型 / 世界模型 / 智驾 / 具身

数据源：duckduckgo_search
输出：推送到飞书单聊
"""

import json
import subprocess
from datetime import datetime
from ddgs import DDGS

DM_CHAT = "oc_bc5bb378d432fca62a7786e26cf82578"


def search_ai_news():
    """搜索 AI 领域新闻"""
    queries = [
        "AI", "OpenAI", "Tesla AI", "robotics", "autonomous driving",
    ]

    results = []
    with DDGS() as ddgs:
        for q in queries:
            for r in ddgs.news(q, max_results=5):
                results.append(r)

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
        [{"tag": "text", "text": "📊 今日 AI 圈 10 条头部新闻\n"}],
    ]

    for i, item in enumerate(news_items, 1):
        title_text = item.get("title", "")[:100]
        body = item.get("body", "")[:150]
        source = item.get("source", "")
        date = item.get("date", "")
        content_blocks.append([{
            "tag": "text",
            "text": f"{i}. {title_text}\n   {body}\n   来源: {source} | {date}\n"
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
