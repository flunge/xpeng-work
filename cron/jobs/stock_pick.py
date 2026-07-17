#!/usr/bin/env python3
"""
每天 09:00 — 推送最值得投资的港股和美股。

流程：
1. 搜索市场热点，识别出现频率最高的股票
2. 对每支入选股票，单独搜索其投资分析/最新动态
3. 从专属搜索结果中提取该股票的投资理由
4. 分 5 长线 + 5 短线推送

数据源：ddgs (DuckDuckGo)
输出：推送到飞书单聊
"""

import json
import re
import subprocess
import time
from datetime import datetime
from ddgs import DDGS

DM_CHAT = "oc_bc5bb378d432fca62a7786e26cf82578"

# ── 股票字典：名称 → (代码, 交易所) ──
STOCK_DICT = {
    # 美股
    "英伟达": ("NVDA", "美股"),
    "NVIDIA": ("NVDA", "美股"),
    "特斯拉": ("TSLA", "美股"),
    "Tesla": ("TSLA", "美股"),
    "苹果": ("AAPL", "美股"),
    "Apple": ("AAPL", "美股"),
    "微软": ("MSFT", "美股"),
    "Microsoft": ("MSFT", "美股"),
    "谷歌": ("GOOGL", "美股"),
    "Alphabet": ("GOOGL", "美股"),
    "Meta": ("META", "美股"),
    "亚马逊": ("AMZN", "美股"),
    "Amazon": ("AMZN", "美股"),
    "AMD": ("AMD", "美股"),
    "台积电": ("TSM", "美股"),
    "TSMC": ("TSM", "美股"),
    "Palantir": ("PLTR", "美股"),
    "博通": ("AVGO", "美股"),
    "Broadcom": ("AVGO", "美股"),
    "Netflix": ("NFLX", "美股"),
    "奈飞": ("NFLX", "美股"),
    "JPMorgan": ("JPM", "美股"),
    "摩根大通": ("JPM", "美股"),
    # 港股
    "腾讯": ("0700.HK", "港股"),
    "阿里巴巴": ("9988.HK", "港股"),
    "阿里": ("9988.HK", "港股"),
    "美团": ("3690.HK", "港股"),
    "比亚迪": ("1211.HK", "港股"),
    "小米": ("1810.HK", "港股"),
    "中芯国际": ("0981.HK", "港股"),
    "京东": ("9618.HK", "港股"),
    "百度": ("9888.HK", "港股"),
    "网易": ("9999.HK", "港股"),
    "快手": ("1024.HK", "港股"),
    "理想汽车": ("2015.HK", "港股"),
    "蔚来": ("9866.HK", "港股"),
    "小鹏汽车": ("9868.HK", "港股"),
    "平安": ("2318.HK", "港股"),
    "建设银行": ("0939.HK", "港股"),
    "工商银行": ("1398.HK", "港股"),
    "招商银行": ("3968.HK", "港股"),
    "汇丰": ("0005.HK", "港股"),
    "港交所": ("0388.HK", "港股"),
    "药明生物": ("2269.HK", "港股"),
    "农夫山泉": ("9633.HK", "港股"),
    "海底捞": ("6862.HK", "港股"),
    "哔哩哔哩": ("9626.HK", "港股"),
    "商汤": ("0020.HK", "港股"),
    "联想集团": ("0992.HK", "港股"),
    "中远海控": ("1919.HK", "港股"),
    "中国移动": ("0941.HK", "港股"),
    "中国海洋石油": ("0883.HK", "港股"),
    "中海油": ("0883.HK", "港股"),
}

# ── 搜索关键词 ──
CN_SEARCH_QUERIES = [
    "港股 涨幅榜 今日 热门",
    "美股 涨幅榜 今日 热门",
    "港股 投资价值分析 最新",
    "美股 投资价值分析 最新",
    "恒生指数 成分股 涨幅 今日",
    "纳斯达克 涨幅榜 今日",
    "港股 热门股票 机构评级",
    "美股 热门股票 机构评级",
]

EN_SEARCH_QUERIES = [
    "top gaining stocks today",
    "best stocks to buy analysis",
    "stock market winners today",
    "Hong Kong stocks rally",
    "US tech stocks surge",
]


def search_raw(queries, search_fn, max_per_query=5):
    """通用搜索封装"""
    results = []
    with DDGS() as ddgs:
        for q in queries:
            for attempt in range(3):
                try:
                    for r in search_fn(ddgs, q, max_per_query):
                        results.append(r)
                    break
                except Exception:
                    time.sleep(2)
    return results


def _text_search(ddgs, q, max_r):
    return [{"title": r.get("title", ""), "body": r.get("body", ""),
             "href": r.get("href", ""), "source": "web", "date": ""}
            for r in ddgs.text(q, max_results=max_r)]


def _news_search(ddgs, q, max_r):
    return [{"title": r.get("title", ""), "body": r.get("body", ""),
             "href": r.get("url", ""), "source": r.get("source", ""),
             "date": r.get("date", "")}
            for r in ddgs.news(q, max_results=max_r)]


def identify_trending_stocks(all_data):
    """从搜索结果中统计股票出现频率，返回前 10"""
    mentions = {}  # {显示名: {ticker, market, count, contexts: []}}

    for item in all_data:
        text = (item.get("title", "") + " " + item.get("body", "")).lower()
        for stock_name, (ticker, market) in STOCK_DICT.items():
            if stock_name.lower() in text:
                if stock_name not in mentions:
                    mentions[stock_name] = {
                        "ticker": ticker,
                        "market": market,
                        "count": 0,
                        "contexts": [],
                    }
                mentions[stock_name]["count"] += 1
                # 保存上下文片段（最多 200 字）
                snippet = item.get("body", "")[:200]
                if snippet:
                    mentions[stock_name]["contexts"].append(snippet)

    # 按频率排序
    ranked = sorted(mentions.items(), key=lambda x: x[1]["count"], reverse=True)
    return ranked[:10]


def search_stock_analysis(stock_name, ticker):
    """对单支股票搜索其投资分析/最新动态"""
    queries = [
        f"{stock_name} {ticker} 投资分析 最新",
        f"{stock_name} {ticker} 机构评级 目标价",
        f"{stock_name} {ticker} 财报 业绩 增长",
    ]

    results = []
    with DDGS() as ddgs:
        for q in queries:
            for attempt in range(2):
                try:
                    for r in ddgs.text(q, max_results=3):
                        results.append({
                            "title": r.get("title", ""),
                            "body": r.get("body", ""),
                            "href": r.get("href", ""),
                        })
                    break
                except Exception:
                    time.sleep(1)

    return results[:5]  # 最多取 5 条


def extract_reason(stock_name, ticker, analysis_data):
    """从该股票的专属搜索结果中提取投资理由"""
    if not analysis_data:
        return f"近期市场关注度较高，可关注其后续走势"

    # 投资关键词
    INVEST_KEYWORDS = [
        "增长", "上涨", "突破", "创新高", "利好", "买入", "增持",
        "超预期", "强劲", "领先", "潜力", "机会", "回购", "分红",
        "市盈率", "估值", "目标价", "评级", "营收", "利润", "现金流",
        "市场份额", "竞争优势", "技术壁垒", "行业龙头", "成长性",
        "AI", "芯片", "新能源", "智能化", "自动驾驶", "机器人",
        "demand", "growth", "surge", "rally", "upgrade", "beat",
        "partnership", "contract", "launch", "expansion",
    ]

    best_snippets = []
    for item in analysis_data:
        body = item.get("body", "")
        title = item.get("title", "")
        text = title + " " + body

        # 找包含投资关键词的句子
        sentences = re.split(r'[。！？；\n]', text)
        relevant = []
        for s in sentences:
            s = s.strip()
            if len(s) < 10:
                continue
            for kw in INVEST_KEYWORDS:
                if kw.lower() in s.lower():
                    relevant.append(s)
                    break

        if relevant:
            # 取最长的相关句
            best = max(relevant, key=len)
            if len(best) > 200:
                # 按逗号截断
                truncated = best[:200]
                comma_idx = truncated.rfind("，")
                if comma_idx > 100:
                    best = truncated[:comma_idx]
                else:
                    best = truncated + "…"
            best_snippets.append(best)

    if not best_snippets:
        # 回退：取第一条分析结果的 body 前 150 字
        fallback = analysis_data[0].get("body", "")[:150]
        return fallback if fallback else "近期市场关注度较高"

    # 合并前 2 条理由
    reason_parts = best_snippets[:2]
    return "；".join(reason_parts)


def build_stock_entry(name, info, reason_text):
    """构建单支股票的展示信息"""
    return {
        "name": name,
        "ticker": info["ticker"],
        "market": info["market"],
        "reason": reason_text,
        "url": "",  # 可扩展
    }


def build_post_content(stocks_long, stocks_short):
    now_str = datetime.now().strftime("%Y-%m-%d")
    title = f"📈 每日投资参考 {now_str}"

    content_blocks = []

    if stocks_long:
        content_blocks.append([{"tag": "text", "text": "🟢 长线推荐（未来潜力最高）：\n"}])
        for i, s in enumerate(stocks_long, 1):
            lines = [
                f"{i}. {s['name']}（{s['ticker']}）",
                f"   原因：{s['reason']}",
            ]
            content_blocks.append([{"tag": "text", "text": "\n".join(lines) + "\n"}])

    if stocks_short:
        content_blocks.append([{"tag": "text", "text": "🔴 短线推荐（短期可获利）：\n"}])
        for i, s in enumerate(stocks_short, 1):
            lines = [
                f"{i}. {s['name']}（{s['ticker']}）",
                f"   原因：{s['reason']}",
            ]
            content_blocks.append([{"tag": "text", "text": "\n".join(lines) + "\n"}])

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
        # Step 1: 搜索市场热点
        print("[1/4] 搜索市场热点...")
        cn_results = search_raw(CN_SEARCH_QUERIES, _text_search)
        en_results = search_raw(EN_SEARCH_QUERIES, _news_search)
        all_data = cn_results + en_results
        print(f"  获取 {len(all_data)} 条搜索结果")

        # Step 2: 识别热门股票
        print("[2/4] 识别热门股票...")
        ranked = identify_trending_stocks(all_data)
        if not ranked:
            print("未识别出热门股票")
            return
        print(f"  识别出 {len(ranked)} 支热门股票: {', '.join([r[0] for r in ranked])}")

        # Step 3: 对每支股票搜索专属投资分析
        print("[3/4] 搜索每支股票的投资分析...")
        stocks_long = []
        stocks_short = []

        for name, info in ranked:
            print(f"  搜索 {name}({info['ticker']})...")
            analysis = search_stock_analysis(name, info["ticker"])
            reason = extract_reason(name, info["ticker"], analysis)
            entry = build_stock_entry(name, info, reason)

            # 前 5 支为长线，后 5 支为短线
            if len(stocks_long) < 5:
                stocks_long.append(entry)
            else:
                stocks_short.append(entry)

        # Step 4: 推送
        print("[4/4] 推送到飞书...")
        payload = build_post_content(stocks_long, stocks_short)
        if push_message(payload):
            print(f"✅ 投资参考已推送（{len(stocks_long)} 长线 + {len(stocks_short)} 短线）")
        else:
            print("❌ 推送失败")
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
