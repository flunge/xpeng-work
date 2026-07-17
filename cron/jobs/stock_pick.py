#!/usr/bin/env python3
"""
每天 09:00 — 推送投资参考新闻。

数据源：ddgs (DuckDuckGo)
输出：推送到飞书单聊
"""

import json
import subprocess
import time
from datetime import datetime
from ddgs import DDGS

DM_CHAT = "oc_bc5bb378d432fca62a7786e26cf82578"

# 中文关键词 → text 搜索
CN_QUERIES = [
    "港股 最新新闻",
    "美股 最新行情",
    "A股 市场动态",
    "新能源 车企 股票",
    "半导体 芯片 股票",
]

# 英文关键词 → news 搜索
EN_QUERIES = [
    "stocks", "Hong Kong stocks", "US stocks", "growth stocks", "investing",
]


def search_stock_news():
    results = []
    with DDGS() as ddgs:
        for q in CN_QUERIES:
            for attempt in range(3):
                try:
                    for r in ddgs.text(q, max_results=5):
                        r["_search_type"] = "text"
                        results.append(r)
                    break
                except Exception:
                    time.sleep(2)

        for q in EN_QUERIES:
            for attempt in range(3):
                try:
                    for r in ddgs.news(q, max_results=5):
                        r["_search_type"] = "news"
                        results.append(r)
                    break
                except Exception:
                    time.sleep(2)

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
    title = f"📈 每日投资参考 {now_str}"

    content_blocks = [
        [{"tag": "text", "text": f"📊 今日 {len(news_items)} 条财经新闻\n"}],
    ]

    for i, item in enumerate(news_items, 1):
        title_text = item.get("title", "")[:100]
        url = item.get("href") or item.get("url") or ""
        source = item.get("source", "")
        date = item.get("date", "")
        body = item.get("body", "")[:120]

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

    content_blocks.append([{
        "tag": "text",
        "text": "⚠️ 以上信息仅供参考，不构成投资建议。"
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
        news_items = search_stock_news()
        if not news_items:
            print("未获取到新闻")
            return

        payload = build_post_content(news_items)
        if push_message(payload):
            print("✅ 投资参考已推送")
        else:
            print("❌ 推送失败")
    except Exception as e:
        print(f"❌ 错误: {e}")


if __name__ == "__main__":
    main()
