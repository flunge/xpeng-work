#!/usr/bin/env python3
"""
每日飞书食谱通知脚本
用法: python3 scripts/notify_daily.py [--date 2026-06-16]

在每天18:00运行，读取明日食谱并发送到飞书群。
如不指定日期，默认为明天。
"""

import os
import sys
import json
import yaml
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
DAILY_DIR = BASE_DIR / "plans" / "daily"

# 数据源：迁飞书后 config 从飞书读；每日卡片本地缺失时从飞书「每日菜谱」下载。
try:
    import feishu_data
except Exception:
    feishu_data = None

# 推送目标：与机器人(cli_aaad7e4c46f95bb4)的单聊会话（已弃用群 webhook）
import subprocess
DM_CHAT = "oc_bc5bb378d432fca62a7786e26cf82578"


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_config(name):
    """加载 config：优先飞书，回退本地 config/ 目录。"""
    if feishu_data is not None:
        return feishu_data.load_config(name)
    return load_yaml(CONFIG_DIR / name)


def beijing_now():
    """Pod 时区为 UTC，换算成北京时间(UTC+8)。"""
    return datetime.utcnow() + timedelta(hours=8)


def find_target_daily_card(force_date=None):
    """选食谱：显式传 force_date 则用它；否则按北京时间 18:00 前发『今日』、之后发『明日』。"""
    if force_date is not None:
        target = force_date
        today = beijing_now().date()
        label = "明日食谱" if target > today else ("今日食谱" if target == today else "食谱")
    else:
        now = beijing_now()
        if now.hour < 18:
            target = now.date()
            label = "今日食谱"
        else:
            target = now.date() + timedelta(days=1)
            label = "明日食谱"
    date_str = f"{target.year}-{target.month:02d}-{target.day:02d}"
    filename = DAILY_DIR / f"{date_str}.md"
    if filename.exists():
        with open(filename, "r", encoding="utf-8") as f:
            return f.read(), target, label
    # 本地无 → 从飞书「每日菜谱」下载
    if feishu_data is not None:
        try:
            content = feishu_data.fetch_daily_card(date_str)
            if content:
                return content, target, label
        except Exception as e:
            print(f"⚠️ 从飞书获取食谱失败: {e}")
    print(f"⚠️ 未找到食谱文件: {date_str}.md（本地与飞书均无）")
    print("   请先运行 generate_month.py 生成月度计划")
    return None, target, label


def extract_sections(content):
    """从 Markdown 日志中提取各部分内容"""
    sections = {}

    if "## 🌅 早餐" in content:
        breakfast = content.split("## 🌅 早餐")[1]
        # 截到下一个 ## 或文件结尾
        if "## ☀️" in breakfast:
            breakfast = breakfast.split("## ☀️")[0]
        elif "## 🌙" in breakfast:
            breakfast = breakfast.split("## 🌙")[0]
        elif "## 🛒" in breakfast:
            breakfast = breakfast.split("## 🛒")[0]
        sections["breakfast"] = breakfast.strip()

    if "## ☀️ 午餐" in content:
        lunch = content.split("## ☀️ 午餐")[1]
        if "## 🌙" in lunch:
            lunch = lunch.split("## 🌙")[0]
        elif "## 🛒" in lunch:
            lunch = lunch.split("## 🛒")[0]
        sections["lunch"] = lunch.strip()

    if "## 🌙 晚餐" in content:
        dinner = content.split("## 🌙 晚餐")[1]
        if "## 🛒" in dinner:
            dinner = dinner.split("## 🛒")[0]
        sections["dinner"] = dinner.strip()

    if "## 🛒 当日采购清单" in content:
        shopping = content.split("## 🛒 当日采购清单")[1].strip()
        sections["shopping"] = shopping

    return sections


def format_lark_card(date_str, weekday_cn, sections, holiday_name="", label="明日食谱"):
    """构建飞书卡片消息 - 完整详细版"""
    title_tag = f"【{holiday_name}】" if holiday_name else ""
    header = f"🍽️ {date_str}（{weekday_cn}）{title_tag}{label}"

    elements = []

    def section_to_lark_md(text, title_prefix):
        """将 markdown 节内容转为飞书 lark_md 文本"""
        lines = text.split("\n")
        output = []
        for line in lines:
            # 保留 ### 标题（加粗展示）
            if line.startswith("### "):
                output.append(f"**{line.replace('### ', '').strip()}**")
            # 保留 **加粗** 文本
            elif line.startswith("**") and "**" in line[2:]:
                output.append(line)
            # 保留列表项
            elif line.strip().startswith("- "):
                output.append(line)
            elif line.strip().startswith("- [ ]"):
                output.append(f"☐ {line.strip().replace('- [ ] ', '')}")
            elif line.strip().startswith("1.") or line.strip().startswith("2.") or line.strip().startswith("3.") or line.strip().startswith("4.") or line.strip().startswith("5.") or line.strip().startswith("6.") or line.strip().startswith("7.") or line.strip().startswith("8."):
                output.append(line)
            elif line.strip():
                output.append(line)
        result = "\n".join(output).strip()
        return result

    # ---- 早餐 ----
    if "breakfast" in sections:
        full_text = section_to_lark_md(sections["breakfast"], "")
        breakfast_block = f"🌅 {full_text}"
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": breakfast_block}
        })

    # ---- 午餐 ----
    if "lunch" in sections:
        full_text = section_to_lark_md(sections["lunch"], "")
        lunch_block = f"☀️ {full_text}"
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": lunch_block}
        })

    # ---- 晚餐 ----
    if "dinner" in sections:
        full_text = section_to_lark_md(sections["dinner"], "")
        dinner_block = f"🌙 {full_text}"
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": dinner_block}
        })

    # ---- 采购清单 ----
    if "shopping" in sections:
        shopping_lines = [l.strip() for l in sections["shopping"].split("\n") if l.strip().startswith("- ")]
        shopping_text = "🛒 **采购清单：**\n"
        for item in shopping_lines:
            shopping_text += f"▸ {item.lstrip('- ')}\n"
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": shopping_text}
        })

    # ---- 脚注 ----
    elements.append({"tag": "hr"})
    elements.append({
        "tag": "note",
        "elements": [{
            "tag": "plain_text",
            "content": "💡 早上操作最多30分钟（前一晚备餐时间不限）。今晚照着'前一晚准备'做，明早从容开饭！"
        }]
    })

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": header},
            "template": "blue"
        },
        "elements": elements
    }

    return {"msg_type": "interactive", "card": card}


def send_to_feishu(webhook_url, message):
    """发送消息到飞书 Webhook"""
    data = json.dumps(message).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = resp.read().decode("utf-8")
            return json.loads(result)
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP 错误: {e.code} {e.reason}")
        print(f"   响应: {e.read().decode('utf-8')}")
        return None
    except urllib.error.URLError as e:
        print(f"❌ 网络错误: {e.reason}")
        return None
    except Exception as e:
        print(f"❌ 未知错误: {e}")
        return None


def send_simple_text(webhook_url, text):
    """发送纯文本消息（备用方案）"""
    message = {"msg_type": "text", "content": {"text": text}}
    return send_to_feishu(webhook_url, message)


def main():
    # 支持 --date YYYY-MM-DD 指定日期；不传则按北京时间自动选今日/明日
    force_date = None
    if "--date" in sys.argv:
        idx = sys.argv.index("--date")
        if idx + 1 < len(sys.argv):
            force_date = datetime.strptime(sys.argv[idx + 1], "%Y-%m-%d").date()
    content, target, label = find_target_daily_card(force_date)

    if not content:
        print(f"⚠️ 未找到 ({target}) 的食谱文件")
        sys.exit(1)

    # 提取各部分
    sections = extract_sections(content)

    if not sections:
        print("❌ 食谱文件格式异常，无法解析")
        sys.exit(1)

    # 获取日期信息
    weekday_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][target.weekday()]

    # 构建飞书卡片
    # 检查是否节假日
    holiday_name = ""
    holidays_config = load_config("holidays-2026.yaml")
    for h in holidays_config.get("holidays", []):
        start = datetime.strptime(h["start"], "%Y-%m-%d").date()
        end = datetime.strptime(h["end"], "%Y-%m-%d").date()
        if start <= target <= end:
            holiday_name = h["name"]
            break

    date_str = f"{target.month}月{target.day}日"
    card_msg = format_lark_card(date_str, weekday_cn, sections, holiday_name, label)

    # 通过 app 机器人发送到单聊（已弃用群 webhook）
    print(f"📤 正在发送{label}({date_str})到单聊...")
    content_json = json.dumps(card_msg["card"], ensure_ascii=False)
    r = subprocess.run(
        ["lark-cli", "im", "+messages-send", "--as", "bot",
         "--chat-id", DM_CHAT, "--msg-type", "interactive", "--content", content_json],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode == 0:
        print("✅ 通知发送成功！")
        log_dir = BASE_DIR / "notifications"
        os.makedirs(log_dir, exist_ok=True)
        log_entry = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 发送{label}({date_str})到单聊成功\n"
        with open(log_dir / "send.log", "a", encoding="utf-8") as f:
            f.write(log_entry)
    else:
        print(f"❌ 发送失败: {(r.stderr or r.stdout).strip()[:200]}")


if __name__ == "__main__":
    main()
