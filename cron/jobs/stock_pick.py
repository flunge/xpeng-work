#!/usr/bin/env python3
"""
每天 09:00 — 推送 10 条投资参考新闻。

数据源：ddgs (DuckDuckGo)
输出：推送到飞书单聊
"""

import json
import subprocess
from datetime import datetime
from ddgs import DDGS

DM_CHAT = "oc_bc5bb378d432fca62a7786e26cf82578"


def search_stock_news():
    """搜索财经/股票新闻"""
    queries = [
        "stocks", "Hong Kong stocks", "US stocks", "growth stocks", "investing",
    ]

    import time
    results = []
    with DDGS() as ddgs:
        for q in queries:
            for attempt in range(3):
                try:
                    for r in ddgs.news(q, max_results=5):
                        results.append(r)
                    break
                except Exception:
                    time.sleep(2)
                    continue

    # 去重
    seen_titles = set()
    unique = []
    for r in results:
        title = r.get("title", "")
        if title and title not in seen_titles:
            seen_titles.add(title)
            unique.append(r)

    return unique[:20]


def build_post_content(news_items):
    now_str = datetime.now().strftime("%Y-%m-%d")

    title = f"📈 每日投资参考 {now_str}"

    content_blocks = [
        [{"tag": "text", "text": f"📊 今日 {len(news_items)} 条财经新闻\n"}],
    ]

    for i, item in enumerate(news_items[:10], 1):
        title_text = item.get("title", "")[:100]
        url = item.get("url", "")
        source = item.get("source", "")
        date = item.get("date", "")

        lines = [f"{i}. {title_text}"]
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
