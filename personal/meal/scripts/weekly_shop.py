#!/usr/bin/env python3
"""
每周采购规划脚本
按周分析食谱中的食材，规划采购：
- 哪些食材可以共享（同一周多道菜共用）
- 哪些食材是一次性用完 vs. 有剩余
- 新鲜食材的保质期提醒
- 给出最优采购时间和建议

用法: python3 scripts/weekly_shop.py [--week 25]
      (默认本周，week=周数)
"""

import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PLANS_DIR = BASE_DIR / "plans"
DAILY_DIR = PLANS_DIR / "daily"


def get_week_dates(year, week_num):
    """获取指定周的所有日期（周一开始）"""
    first_day = date(year, 1, 1)
    # 找到第一个周一
    days_to_monday = (7 - first_day.weekday()) % 7
    if days_to_monday == 0:
        first_monday = first_day
    else:
        first_monday = first_day + timedelta(days=days_to_monday)

    week_start = first_monday + timedelta(weeks=week_num - 1)
    return [week_start + timedelta(days=i) for i in range(7)]


def extract_ingredients(daily_card_text):
    """从每日卡片中提取采购清单的食材"""
    ingredients = []
    in_shopping = False
    for line in daily_card_text.split("\n"):
        if "## 🛒 当日采购清单" in line:
            in_shopping = True
            continue
        if in_shopping:
            if line.startswith("#") and "##" not in line:
                break
            if line.strip().startswith("- "):
                # Parse: "- 食材名 分量（备注）"
                item = line.strip().lstrip("- ").strip()
                ingredients.append(item)
    return ingredients


def classify_perishability(item_text):
    """判断食材的新鲜程度分类"""
    item_lower = item_text.lower()

    # 特殊排除：调味酱类虽然含蔬菜名（番茄酱、番茄沙司）但不属于鲜菜
    sauce_exceptions = ["番茄酱", "番茄沙司", "甜辣酱"]
    for ex in sauce_exceptions:
        if ex in item_lower:
            return "🟢 存", "可长期存放"

    # 强保鲜期短（3天内需用完）——绿叶菜/嫩豆腐/鲜肉/鲜鱼/贝类
    fresh_short = [
        "娃娃菜", "西兰花", "空心菜",
        "青菜", "菠菜", "生菜", "油菜", "菜心", "白菜",
        "豆苗", "豆芽", "韭菜", "芹菜", "茼蒿", "苋菜",
        "番茄", "黄瓜", "西葫芦", "茄子", "青椒", "彩椒",
        "鲜香菇", "金针菇", "杏鲍菇",
        "嫩豆腐", "老豆腐", "豆腐",
        "香菜", "小葱", "葱花",
        "草莓", "蓝莓", "樱桃", "葡萄",
        "牛腩", "五花肉", "里脊", "排骨", "排骨",
        "鸡腿", "鸡胸", "鸡翅", "鸡翅根", "肉末", "肉片",
        "虾仁", "鲜虾", "巴沙鱼", "三文鱼", "鲫鱼", "鱼片",
        "肥牛卷", "牛肉",
    ]

    # 中保鲜期（1~2周内可用）——根茎/蛋奶/火腿/面包
    fresh_medium = [
        "鸡蛋", "鹌鹑蛋",
        "胡萝卜", "白萝卜",
        "洋葱", "大蒜", "生姜",
        "苹果", "梨", "橙子", "柠檬", "牛油果",
        "牛奶", "酸奶", "芝士", "马苏里拉", "芝士片", "奶酪", "黄油",
        "火腿肠", "儿童火腿肠", "火腿丁", "火腿片", "午餐肉", "香肠", "培根",
        "厚切吐司", "吐司", "面包", "馒头", "花卷", "饼",
        "甜玉米粒", "玉米粒", "玉米",
    ]

    # 长保质期（数周至数月）——根茎类/干货/调料/冷冻品
    long_shelf = [
        # 根茎类（阴凉处可存1-3周）
        "土豆", "红薯", "紫薯", "山药", "铁棍山药", "南瓜", "板栗南瓜",
        # 谷物
        "大米", "小米", "糯米", "黑米", "燕麦", "即食燕麦片",
        "面粉", "淀粉", "玉米淀粉", "面包糠",
        "挂面", "面条", "意大利面", "蝴蝶面",
        "粉丝", "粉条", "米粉",
        # 干货
        "黄豆", "红豆", "绿豆", "花生", "花生仁", "黑芝麻",
        "核桃", "核桃仁", "红枣", "枸杞", "百合", "干香菇",
        # 调料
        "宝宝酱油", "生抽", "老抽", "酱油",
        "白醋", "香醋", "醋",
        "蚝油", "料酒", "味醂", "味醂或料酒+糖",
        "香油", "食用油", "橄榄油",
        "盐", "白糖", "红糖", "冰糖", "糖",
        "蜂蜜", "番茄酱", "蛋黄酱", "沙拉酱", "花生酱", "炼乳",
        "白胡椒粉", "黑胡椒粉", "八角", "桂皮",
        # 干货
        "海苔", "海苔片", "紫菜", "虾皮",
        "金枪鱼罐头",
        "白芝麻", "黑芝麻",
        # 冷冻品
        "速冻", "冷冻",
        "寿司醋",
    ]

    for keyword in fresh_short:
        if keyword in item_lower:
            return "🔴 鲜", "3天内食用"
    for keyword in fresh_medium:
        if keyword in item_lower:
            return "🟡 耐", "1周内食用"
    for keyword in long_shelf:
        if keyword in item_lower:
            return "🟢 存", "可长期存放"

    return "⚪ 其他", "视情况"


def main():
    today = date.today()

    # 确定当前周数
    week_num = today.isocalendar()[1]
    year = today.year

    # 获取本周日期
    week_dates = get_week_dates(year, week_num)

    # 只处理包含未来日期的周（或者指定周）
    print(f"\n📅 第{week_num}周采购规划 ({week_dates[0]} ~ {week_dates[6]})\n")
    print("=" * 70)

    # 汇总所有食材
    all_ingredients = {}  # name -> {count, days, perishability, note}

    for d in week_dates:
        filename = DAILY_DIR / f"{d.year}-{d.month:02d}-{d.day:02d}.md"
        if not filename.exists():
            continue

        with open(filename, "r", encoding="utf-8") as f:
            content = f.read()

        ingredients = extract_ingredients(content)
        if not ingredients:
            continue

        # 获取早餐标题
        breakfast_title = ""
        for line in content.split("\n"):
            if line.startswith("### ") and "早餐" not in line:
                breakfast_title = line.replace("### ", "").strip()
                break

        for item in ingredients:
            # 提取食材名（去掉分量和备注）
            name = item.strip()
            # 去掉括号备注
            name = re.sub(r'[（(].*?[）)]', '', name).strip()
            # 去掉数量词（如"半根"、"少许"、"适量"）
            name = re.sub(r'\s+(少许|适量|几滴|小半碗|大半碗|半根|半个|个|根|条|只|袋|盒|罐|块|片|颗|粒|把|小把|大把|小勺|大勺|小碗|碗|杯|小段|段)$', '', name)
            # 去掉数字开头如 "2个" "1根"
            name = re.sub(r'\s+\d+[^a-zA-Z]*$', '', name)
            # 去掉末尾的纯数字
            name = re.sub(r'\s+\d+$', '', name)

            if not name:
                name = item.split(" ")[0] if " " in item else item

            if name not in all_ingredients:
                perish, note = classify_perishability(item)
                all_ingredients[name] = {
                    "count": 0,
                    "days": [],
                    "full_texts": [],
                    "perish": perish,
                    "note": note
                }

            all_ingredients[name]["count"] += 1
            all_ingredients[name]["days"].append(d.day)
            all_ingredients[name]["full_texts"].append(item)

    if not all_ingredients:
        print("⚠️ 本周无食谱数据，请先生成月度计划。")
        return

    # 按保鲜期分类输出
    categories = {
        "🔴 鲜 (3天内用完)": [],
        "🟡 耐 (1周内用完)": [],
        "🟢 存 (可长期存放)": [],
        "⚪ 其他": [],
    }

    for name, info in sorted(all_ingredients.items()):
        cat_key = f"{info['perish']} ({info['note']})"
        found = False
        for cat in categories:
            if info['perish'] in cat:
                categories[cat].append((name, info))
                found = True
                break
        if not found:
            categories["⚪ 其他"].append((name, info))

    for cat_name, items in categories.items():
        if not items:
            continue

        # 分类标题
        emoji = "🔴" if "3天" in cat_name else "🟡" if "1周" in cat_name else "🟢" if "长期" in cat_name else "⚪"
        print(f"\n{'='*70}")
        print(f" {cat_name}")
        print(f"{'='*70}")

        for name, info in sorted(items, key=lambda x: -x[1]["count"]):
            day_str = ",".join(str(d) for d in info["days"])
            count = info["count"]

            # 易耗品提示
            tips = []
            if count == 1 and "3天" in cat_name:
                tips.append("⚠️ 本周只用1次，买最小份或找替代")
            elif count >= 3 and "3天" in cat_name:
                tips.append("✅ 高频食材，合理")
            elif count == 1 and "1周" in cat_name:
                tips.append("💡 只用1次，留意保质期")

            # 多道菜共享提示
            if count >= 2:
                tips.append(f"用在{count}天")

            tip_str = f" — {' | '.join(tips)}" if tips else ""
            print(f"  {name:<16}  {info['count']}次 [{day_str}]{tip_str}")

    # 采购建议
    print(f"\n{'='*70}")
    print(" 💡 本周采购建议")
    print(f"{'='*70}")

    # 共享食材
    shared_items = [(name, info) for name, info in all_ingredients.items()
                    if info["count"] >= 2 and "鲜" in info['perish'] or info["count"] >= 2]
    if shared_items:
        print(" ✅ 一次买，多道菜共用（划算）：")
        for name, info in sorted(shared_items, key=lambda x: -x[1]["count"])[:10]:
            print(f"    · {name}  ×{info['count']}次")
        print("")

    # 单次易耗品提醒
    single_fresh = [(name, info) for name, info in all_ingredients.items()
                    if info["count"] == 1 and "鲜" in info['perish']]
    if single_fresh:
        print(" ⚠️ 这些鲜菜本周只用1次，少量购买或调整食谱：")
        for name, info in sorted(single_fresh, key=lambda x: x[0])[:10]:
            print(f"    · {name}")
        print("")

    # 周采购清单（按类别分组）
    print(" 📋 超市分区采购清单：")
    categories_map = {
        "🥩 肉禽": ["牛肉", "牛腩", "肉末", "里脊", "排骨", "五花肉", "猪瘦肉末", "猪里脊肉",
                    "鸡腿", "鸡胸", "鸡翅", "鸡翅根", "肥牛卷", "儿童早餐肠",
                    "火腿肠", "儿童火腿肠", "火腿丁", "火腿片", "午餐肉", "香肠", "培根"],
        "🦐 海鲜": ["虾仁", "鲜虾", "鱼片", "鲫鱼", "巴沙鱼", "三文鱼", "金枪鱼罐头"],
        "🥬 蔬菜": ["青菜", "菠菜", "生菜", "油菜", "菜心", "白菜", "娃娃菜", "西兰花", "豆苗", "豆芽",
                    "韭菜", "芹菜", "番茄", "黄瓜", "西葫芦", "茄子", "青椒", "彩椒",
                    "蘑菇", "鲜香菇", "金针菇", "杏鲍菇"],
        "🥕 根茎": ["土豆", "红薯", "紫薯", "山药", "铁棍山药", "南瓜", "板栗南瓜",
                    "胡萝卜", "白萝卜", "洋葱", "大蒜", "生姜",
                    "甜玉米粒", "玉米粒", "玉米"],
        "🥚 蛋奶": ["鸡蛋", "鹌鹑蛋", "牛奶", "酸奶", "芝士", "芝士片", "马苏里拉芝士碎", "黄油", "炼乳"],
        "🍞 主食": ["大米", "小米", "糯米", "黑米", "燕麦", "即食燕麦片",
                    "面粉", "淀粉", "玉米淀粉", "面包糠",
                    "挂面", "面条", "意大利面", "蝴蝶面", "粉丝", "粉条",
                    "厚切吐司", "吐司", "面包", "馒头", "花卷",
                    "速冻奶香小馒头", "速冻小花卷",
                    "速冻小馄饨", "速冻鲜肉小笼包", "速冻鲜肉小包子", "速冻水饺", "速冻锅贴"],
        "🥫 调味/干货": ["宝宝酱油", "生抽", "老抽", "酱油", "醋", "白醋", "香醋",
                        "蚝油", "料酒", "味醂", "味醂或料酒+糖",
                        "香油", "食用油", "橄榄油",
                        "盐", "白糖", "红糖", "冰糖", "糖",
                        "蜂蜜", "番茄酱", "蛋黄酱", "沙拉酱", "花生酱",
                        "白胡椒粉", "黑胡椒粉", "八角", "桂皮",
                        "海苔", "海苔片", "紫菜", "虾皮",
                        "红枣", "核桃", "核桃仁", "花生", "花生仁", "黑芝麻", "白芝麻",
                        "百合", "蔓越莓干", "黑米",
                        "寿司醋", "料酒"],
        "🍎 水果": ["苹果", "梨", "橙子", "柠檬", "牛油果", "香蕉", "草莓", "蓝莓", "樱桃", "葡萄",
                    "小番茄", "樱桃番茄", "时令水果"],
    }
    for section, keywords in categories_map.items():
        items_in_section = []
        for name, info in sorted(all_ingredients.items()):
            for kw in keywords:
                if kw in name:
                    items_in_section.append((name, info))
                    break
        if items_in_section:
            display = ", ".join(f"{n}" for n, _ in items_in_section)
            print(f"  {section}: {display}")

    print(f"\n 📝 采购策略：周日一次买干货+根茎+蛋奶，周中补买鲜菜")
    print(f"    肉类买回后分装冷冻，用前一晚放冷藏解冻")


if __name__ == "__main__":
    main()
