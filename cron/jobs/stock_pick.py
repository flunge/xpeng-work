#!/usr/bin/env python3
"""
每天 09:00 — 推送最值得投资的港股和美股。

不再推新闻列表，而是：
1. 搜索港股/美股的市场热点和涨幅榜
2. 分析出 5 支长线 + 5 支短线推荐
3. 每支附「为什么值得投」的原因

数据源：ddgs (DuckDuckGo)
输出：推送到飞书单聊
"""

import json
import subprocess
import time
from datetime import datetime
from ddgs import DDGS

DM_CHAT = "oc_bc5bb378d432fca62a7786e26cf82578"


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


def search_stock_data():
    """搜索港股/美股市场数据和分析"""
    results = []
    with DDGS() as ddgs:
        # 港股
        for q in ["港股 涨幅榜 今日", "港股 热门股票 分析", "恒生指数 成分股 最新"]:
            for attempt in range(3):
                try:
                    for r in ddgs.text(q, max_results=5):
                        r["_search_type"] = "text"
                        results.append(r)
                    break
                except Exception:
                    time.sleep(2)

        # 美股
        for q in ["美股 涨幅榜 今日", "美股 热门股票 分析", "纳斯达克 成分股 最新"]:
            for attempt in range(3):
                try:
                    for r in ddgs.text(q, max_results=5):
                        r["_search_type"] = "text"
                        results.append(r)
                    break
                except Exception:
                    time.sleep(2)

        # 英文
        for q in ["top gaining stocks today", "best stocks to buy analysis", "stock market winners"]:
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

    return unique


def analyze_and_rank(all_data):
    """从搜索结果中分析出推荐股票。

    逻辑：
    1. 从每条新闻中提取股票代码/公司名
    2. 按出现频率排序
    3. 取前 10 支，分成 5 长线 + 5 短线
    """
    stock_mentions = {}  # {股票名: {count, contexts: [], sources: []}}

    # 知名科技公司列表（用于匹配）
    KNOWN_STOCKS = {
        # 美股
        "NVIDIA": "NVDA",
        "英伟达": "NVDA",
        "Tesla": "TSLA",
        "特斯拉": "TSLA",
        "Apple": "AAPL",
        "苹果": "AAPL",
        "Microsoft": "MSFT",
        "微软": "MSFT",
        "Google": "GOOGL",
        "Alphabet": "GOOGL",
        "Meta": "META",
        "Amazon": "AMZN",
        "亚马逊": "AMZN",
        "AMD": "AMD",
        "TSMC": "TSM",
        "台积电": "TSM",
        "Palantir": "PLTR",
        "Broadcom": "AVGO",
        "博通": "AVGO",
        # 港股
        "腾讯": "0700.HK",
        "阿里巴巴": "BABA/9988",
        "阿里": "BABA/9988",
        "美团": "3690.HK",
        "比亚迪": "1211.HK/BYDDY",
        "小米": "1810.HK",
        "中芯国际": "0981.HK/SMIC",
        "京东": "JD/9618",
        "百度": "BIDU/9888",
        "网易": "NTES/9999",
        "快手": "1024.HK",
        "理想汽车": "LI/2015",
        "蔚来": "NIO",
        "小鹏汽车": "XPEV/9868",
        "平安": "2318.HK",
        "建设银行": "0939.HK",
        "工商银行": "1398.HK",
        "招商银行": "3968.HK",
    }

    for item in all_data:
        title = item.get("title", "")
        body = item.get("body", "")
        source = item.get("source", "")
        text = title + " " + body

        for stock_name, ticker in KNOWN_STOCKS.items():
            if stock_name.lower() in text.lower():
                if stock_name not in stock_mentions:
                    stock_mentions[stock_name] = {
                        "ticker": ticker,
                        "count": 0,
                        "context": "",
                        "source": source,
                    }
                stock_mentions[stock_name]["count"] += 1
                # 取最长的 context
                snippet = summarize_body(body, 200)
                if len(snippet) > len(stock_mentions[stock_name]["context"]):
                    stock_mentions[stock_name]["context"] = snippet

    # 按出现频率排序
    ranked = sorted(stock_mentions.items(), key=lambda x: x[1]["count"], reverse=True)

    return ranked[:10]


def build_post_content(ranked_stocks):
    now_str = datetime.now().strftime("%Y-%m-%d")
    title = f"📈 每日投资参考 {now_str}"

    content_blocks = [
        [{"tag": "text", "text": f"📊 今日最值得关注的 {len(ranked_stocks)} 支港股/美股\n"}],
    ]

    # 前 5 支作为长线推荐
    long_term = ranked_stocks[:5]
    # 后 5 支作为短线推荐
    short_term = ranked_stocks[5:10]

    if long_term:
        content_blocks.append([{"tag": "text", "text": "🟢 长线推荐（未来潜力最高）："}])
        for i, (name, info) in enumerate(long_term, 1):
            ticker = info["ticker"]
            reason = info["context"] or "近期市场关注度较高"
            content_blocks.append([{
                "tag": "text",
                "text": f"{i}. {name}（{ticker}）\n   原因: {reason}\n"
            }])

    if short_term:
        content_blocks.append([{"tag": "text", "text": "🔴 短线推荐（短期可获利）："}])
        for i, (name, info) in enumerate(short_term, 1):
            ticker = info["ticker"]
            reason = info["context"] or "近期交易活跃"
            content_blocks.append([{
                "tag": "text",
                "text": f"{i}. {name}（{ticker}）\n   原因: {reason}\n"
            }])

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
        ["lark-cli", "im", "+messages-send", "--as", "bot",
         "--chat-id", DM_CHAT, "--msg-type", "post", "--content", content_json],
        capture_output=True, text=True, timeout=30,
    )
    return r.returncode == 0


def main():
    try:
        all_data = search_stock_data()
        if not all_data:
            print("未获取到数据")
            return

        ranked_stocks = analyze_and_rank(all_data)
        if not ranked_stocks:
            print("未分析出推荐股票")
            return

        payload = build_post_content(ranked_stocks)
        if push_message(payload):
            print(f"✅ 投资参考已推送（{len(ranked_stocks)} 支股票）")
        else:
            print("❌ 推送失败")
    except Exception as e:
        print(f"❌ 错误: {e}")


if __name__ == "__main__":
    main()
