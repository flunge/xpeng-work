#!/usr/bin/env python3
"""
每天 09:00 — 推送 AI 圈前沿新闻。

筛选标准：模型发布/融资/重大突破/政策，不推 trivial 信息。
数据源：IT之家 RSS（可靠发布日期 + 中文标题）+ DuckDuckGo news（英文补充）
输出：推送到飞书单聊
"""

import json
import re
import subprocess
import time
import urllib.request
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from ddgs import DDGS

DM_CHAT = "oc_bc5bb378d432fca62a7786e26cf82578"

# ── 前沿主题查询 ──
# DuckDuckGo news 搜索英文（有可靠 date 字段），作为补充
SEARCH_QUERIES = [
    "AI model release breakthrough 2026",
    "NVIDIA AI chip GPU humanoid robot 2026",
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


def _extract_date_from_text(title, body, href):
    """从 body 提取发布日期。
    只信任中文媒体日期模式（如 "7月20日消息"），不信任 "N days ago"（那是爬虫时间）。
    """
    import re as _re
    now = datetime.now()
    body_str = body or ""

    # 中文媒体日期：X月X日（只看前80字符，避免正文里引用旧日期）
    head = body_str[:80]
    m = _re.search(r'(\d{1,2})月(\d{1,2})日', head)
    if m:
        try:
            return datetime(now.year, int(m[1]), int(m[2]))
        except ValueError:
            pass

    # MM-DD 或 MM/DD（前80字符）
    m = _re.search(r'(\d{1,2})[-/](\d{1,2})\b', head)
    if m:
        try:
            d = datetime(now.year, int(m[1]), int(m[2]))
            if abs((now - d).days) <= 31:  # 合理范围
                return d
        except ValueError:
            pass

    # 英文月份缩写 + 日（如 "Jul 20"）在前80字符
    months = {'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
              'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12}
    m = _re.search(r'(\w{3})\s*(\d{1,2})\b', head, _re.IGNORECASE)
    if m and m.group(1).lower() in months:
        try:
            d = datetime(now.year, months[m.group(1).lower()], int(m[2]))
            if abs((now - d).days) <= 31:
                return d
        except ValueError:
            pass

    return None


def is_chinese(title):
    """标题包含中文字符视为中文新闻。"""
    return bool(re.search(r'[\u4e00-\u9fff]', title or ""))


def _fetch_ithome_rss():
    """从 IT之家 RSS 获取最新文章，返回标准化列表。
    RSS 有可靠 <pubDate>，全中文标题，是国内最好的 AI 新闻 RSS 源。"""
    items = []
    try:
        req = urllib.request.Request(
            "https://www.ithome.com/rss/",
            headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        html = resp.read().decode("utf-8", errors="ignore")
        for m in re.finditer(
            r"<item>.*?<title>(.*?)</title>.*?<link>(.*?)</link>.*?<pubDate>(.*?)</pubDate>",
            html, re.DOTALL):
            title = m.group(1).strip()
            link = m.group(2).strip()
            pub = parsedate_to_datetime(m.group(3).strip())
            items.append({
                "title": title,
                "href": link,
                "body": "",
                "date": pub.strftime("%Y-%m-%dT%H:%M:%S"),
                "_source": "ithome_rss",
            })
    except Exception:
        pass
    return items


def search_ai_news():
    results = []
    week_ago = datetime.now() - timedelta(days=7)

    # 1) IT之家 RSS：可靠日期 + 中文标题
    results.extend(_fetch_ithome_rss())

    # 2) DuckDuckGo news 搜索英文（有可靠 date 字段），作补充
    for query in SEARCH_QUERIES:
        for attempt in range(2):
            try:
                with DDGS() as ddgs:
                    items = ddgs.news(query, max_results=8, timelimit="w")
                    for r in items:
                        r["_source"] = "ddg_news"
                        results.append(r)
                break
            except Exception:
                time.sleep(3)

    # 去重 + 过滤
    seen_titles = set()
    unique = []
    for r in results:
        title = r.get("title", "")
        key = title.lower()
        if not key or key in seen_titles:
            continue
        # 只保留中文新闻
        if not is_chinese(title):
            continue

        # 日期过滤：超过 7 天的丢弃
        r_date = _parse_ddg_date(r.get("date", ""))
        if r_date is None:
            r_date = _extract_date_from_text(
                r.get("title", ""), r.get("body", ""), r.get("href", ""))
        if r_date is None or r_date < week_ago:
            continue

        seen_titles.add(key)
        unique.append(r)

    return unique


def _parse_ddg_date(date_str):
    """解析 DuckDuckGo 的日期字段，返回 naive datetime 或 None。"""
    if not date_str:
        return None
    # 去掉时区后缀，统一用 naive datetime 比较
    s = date_str.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:len(datetime.now().strftime(fmt))], fmt)
        except ValueError:
            continue
    # 截取 ISO 格式的日期部分
    if "T" in s:
        s = s.split("T")[0]
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d")
    except ValueError:
        return None


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
        ["lark-cli", "--profile", "meal", "im", "+messages-send", "--as", "bot",
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
