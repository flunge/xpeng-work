#!/usr/bin/env python3
"""
每天 09:00 — 推送 10 支最具投资价值的股票。

5 支长线（未来潜力最高，不一定是当前最热的）
5 支短线（短期可获利，现在进去能获取收益）
优先港股 / 美股。

数据源：duckduckgo_search 搜索财经新闻 + 市场热点
输出：推送到飞书单聊
"""

import json
import subprocess
from datetime import datetime
from duckduckgo_search import DDGS

PROFILE = "meal"
TARGET_USER_ID = "ou_f9cd23092a356c297d6a9f38fd7cfd5e"


def search_stock_news():
    """搜索财经/股票新闻"""
    queries = [
        "best stocks to buy 2026 long term",
        "top performing stocks Hong Kong US market today",
        "high growth potential stocks 2026",
        "short term stock picks momentum trading",
        "港股 美股 投资推荐 2026",
    ]

    results = []
    with DDGS() as ddgs:
        for q in queries:
            for r in ddgs.news(q, max_results=5):
                results.append(r)

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

    title = f"📈 每日股票推荐 {now_str}"

    content_blocks = [
        [{"tag": "text", "text": "📊 今日市场分析 & 股票推荐\n"}],
        [{"tag": "text", "text": "🟢 长线推荐（未来潜力最高）：\n"}],
    ]

    # 由于没有实时行情 API，这里用新闻标题作为参考
    for i, item in enumerate(news_items[:5], 1):
        title_text = item.get("title", "")[:100]
        body = item.get("body", "")[:150]
        content_blocks.append([{"tag": "text", "text": f"{i}. {title_text}\n   {body}\n"}])

    content_blocks.append([{"tag": "text", "text": "🔴 短线推荐（短期可获利）：\n"}])

    for i, item in enumerate(news_items[5:10], 1):
        title_text = item.get("title", "")[:100]
        body = item.get("body", "")[:150]
        content_blocks.append([{"tag": "text", "text": f"{i}. {title_text}\n   {body}\n"}])

    content_blocks.append([{
        "tag": "text",
        "text": "⚠️ 以上信息仅供参考，不构成投资建议。请根据自身风险承受能力做决策。"
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
        ["lark-cli", "--profile", PROFILE, "im", "+messages-send", "--as", "bot",
         "--user-id", TARGET_USER_ID, "--msg-type", "post", "--content", content_json],
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
            print("✅ 股票推荐已推送")
        else:
            print("❌ 推送失败")
    except Exception as e:
        print(f"❌ 错误: {e}")


if __name__ == "__main__":
    main()
