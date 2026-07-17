#!/usr/bin/env python3
"""
每天 09:00 — 推送 AI 圈前沿新闻。

筛选标准：模型发布/融资/重大突破/政策，不推 trivial 信息。
数据源：ddgs (DuckDuckGo) + DuckDuckGo web search
输出：推送到飞书单聊
"""

import json
import re
import subprocess
import time
from datetime import datetime
from ddgs import DDGS

DM_CHAT = "oc_bc5bb378d432fca62a7786e26cf82578"

# ── 前沿主题查询 ──
# 每条查询对应一个前沿方向，搜索结果需包含实质性内容
SEARCH_QUERIES = [
    # 大模型前沿
    ("大模型 发布 最新", "text"),
    ("GPT Claude Gemini latest", "news"),
    ("OpenAI funding release", "news"),
    # 自动驾驶 / 世界模型
    ("自动驾驶 端到端 最新进展", "text"),
    ("world model autonomous driving breakthrough", "news"),
    # 具身智能 / 机器人
    ("具身智能 人形机器人 最新", "text"),
    ("humanoid robotics AI breakthrough", "news"),
    # AI 芯片 / 算力
    ("AI芯片 英伟达 算力 最新", "text"),
    ("NVIDIA AI chip GPU latest", "news"),
]

# ── 过滤规则 ──
# 这些关键词出现时认为是 trivial/低价值新闻，跳过
TRIVIAL_KEYWORDS = [
    "quiz", "test your", "joke", "meme", "funny",
    "basketball", "sport", "celebrity",
    "sponsored", "advertisement", "推广", "广告",
    "订阅", "关注公众号", "扫码",
]

# 这些关键词出现时认为是高价值前沿新闻
FRONTIER_KEYWORDS = [
    "发布", "release", "launch", "推出", "上线", "open source", "开源",
    "融资", "funding", "round", "估值", "valuation", "IPO",
    "突破", "breakthrough", "SOTA", "state-of-the-art", "benchmark",
    "GPT", "Claude", "Gemini", "Llama", "通义", "文心", "DeepSeek",
    "NVIDIA", "英伟达", "H100", "H200", "B200", "Blackwell",
    "自动驾驶", "autonomous", "端到端", "end-to-end", "FSD",
    "具身智能", "embodied", "人形机器人", "humanoid",
    "世界模型", "world model",
    "政策", "监管", "regulation", "ban", "executive order",
]


def is_frontier(title, body):
    """判断是否为前沿重要新闻"""
    text = (title + " " + body).lower()

    # 排除 trivial
    for kw in TRIVIAL_KEYWORDS:
        if kw.lower() in text:
            return False

    # 至少命中一个前沿关键词
    for kw in FRONTIER_KEYWORDS:
        if kw.lower() in text:
            return True

    return False


def summarize_body(body, max_chars=300):
    """按句号/分号边界截取正文，不硬截断。"""
    if not body:
        return ""
    if len(body) <= max_chars:
        return body.strip()
    truncated = body[:max_chars]
    for sep in ["。", "！", "？", "；", ". ", "? ", "! "]:
        idx = truncated.rfind(sep)
        if idx > max_chars // 2:
            return truncated[:idx + len(sep)].strip()
    return truncated.strip() + "…"


def search_ai_news():
    results = []
    with DDGS() as ddgs:
        for query, search_type in SEARCH_QUERIES:
            for attempt in range(3):
                try:
                    if search_type == "text":
                        items = ddgs.text(query, max_results=8)
                    else:
                        items = ddgs.news(query, max_results=8)
                    for r in items:
                        r["_search_type"] = search_type
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

    return unique


def build_post_content(news_items):
    now_str = datetime.now().strftime("%Y-%m-%d")
    title = f"🤖 AI 前沿速递 {now_str}"

    content_blocks = [
        [{"tag": "text", "text": f"📰 今日 AI 圈 {len(news_items)} 条前沿新闻\n"}],
    ]

    for i, item in enumerate(news_items, 1):
        title_text = item.get("title", "")
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
        all_news = search_ai_news()

        # 筛选前沿新闻
        frontier_news = []
        for item in all_news:
            title = item.get("title", "")
            body = item.get("body", "")
            if is_frontier(title, body):
                frontier_news.append(item)

        # 取前 10 条
        frontier_news = frontier_news[:10]

        if not frontier_news:
            print("未获取到前沿新闻")
            return

        payload = build_post_content(frontier_news)
        if push_message(payload):
            print(f"✅ AI 前沿速递已推送（{len(frontier_news)} 条）")
        else:
            print("❌ 推送失败")
    except Exception as e:
        print(f"❌ 错误: {e}")


if __name__ == "__main__":
    main()
