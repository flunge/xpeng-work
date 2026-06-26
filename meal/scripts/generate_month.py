#!/usr/bin/env python3
"""
月度食谱计划生成器
用法: python3 scripts/generate_month.py --year 2026 --month 6 [--output plans/2026-06.md]

读取食谱库和节假日配置，生成不重样的月度食谱计划。
"""

import os
import sys
import yaml
import argparse
import calendar
from datetime import date, datetime, timedelta
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent

# 路径常量
RECIPES_DIR = BASE_DIR / "recipes"
CONFIG_DIR = BASE_DIR / "config"
PLANS_DIR = BASE_DIR / "plans"
DAILY_DIR = PLANS_DIR / "daily"


def load_yaml(path):
    """安全加载 YAML 文件"""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_all_recipes(recipe_type):
    """加载某一类型（breakfast/lunch/dinner）的所有食谱"""
    recipes = []
    recipe_dir = RECIPES_DIR / recipe_type
    if not recipe_dir.exists():
        return recipes
    for f in sorted(recipe_dir.glob("*.yaml")):
        recipe = load_yaml(f)
        recipe["_file"] = f.name
        recipe["_type"] = recipe_type
        recipes.append(recipe)
    return recipes


def is_holiday(d, holidays):
    """判断某天是否是法定节假日"""
    for h in holidays:
        start = datetime.strptime(h["start"], "%Y-%m-%d").date()
        end = datetime.strptime(h["end"], "%Y-%m-%d").date()
        if start <= d <= end:
            return True, h["name"]
    return False, None


def is_workday_compensation(d, holidays):
    """判断某天是否是调休上班日（原本周末但需要上班）"""
    for h in holidays:
        for wd in h.get("workdays", []):
            if d == datetime.strptime(wd, "%Y-%m-%d").date():
                return True
    return False


def get_day_type(d, holidays):
    """返回日期类型: 'workday' | 'weekend' | 'holiday'"""
    # 先判断是否节假日
    is_h, h_name = is_holiday(d, holidays)
    if is_h:
        return "holiday", h_name

    # 判断是否调休上班日
    if is_workday_compensation(d, holidays):
        return "workday", None

    # 判断周末
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return "weekend", None

    return "workday", None


def _ingredient_score(recipe, preferred_tags):
    """计算食谱与偏好食材的匹配分数"""
    if not preferred_tags:
        return 0
    recipe_tags = set(recipe.get("ingredient_tags", []))
    if not recipe_tags:
        return 0
    return len(recipe_tags & preferred_tags)


def pick_recipes(recipes_pool, count, used_titles, day_index=0, preferred_tags=None):
    """
    从池中挑选不重复的食谱。
    优先选择与 preferred_tags 共享食材的食谱（食材聚类），
    其次按 day_index 轮换。
    """
    available = [r for r in recipes_pool if r["title"] not in used_titles]
    if not available:
        available = recipes_pool

    selected = []
    for i in range(count):
        if preferred_tags and len(available) > count:
            # 按食材匹配度排序（高分优先），同分按原顺序
            scored = [(r, _ingredient_score(r, preferred_tags)) for r in available]
            # 按分数降序排列，分数相同保持原顺序
            scored.sort(key=lambda x: (-x[1], available.index(x[0])))
            best_score = scored[0][1]
            if best_score > 0:
                # 有食材匹配的食谱，选分数最高的
                chosen = scored[0][0]
            else:
                # 没有匹配，回退到 index 轮换
                idx = (day_index + i) % len(available)
                chosen = available[idx]
        else:
            idx = (day_index + i) % len(available)
            chosen = available[idx]

        selected.append(chosen)
        used_titles.add(chosen["title"])
    return selected


def pick_side(sides, used_side, day_index, preferred_tags=None, exclude_titles=None, prefer_category=None):
    """
    为全餐日挑选 1 道加菜。
    - 优先选与所属正餐共享食材的加菜（减少食材浪费）
    - 已用过的不重复；一轮用尽后重置循环
    - exclude_titles 保证同一天午/晚餐加菜不重复
    """
    exclude_titles = exclude_titles or set()
    base = sides
    if prefer_category:
        cat = [s for s in sides if s.get("category") == prefer_category]
        if cat:
            base = cat
    avail = [s for s in base
             if s["title"] not in used_side and s["title"] not in exclude_titles]
    if not avail:
        # 该类加菜已用尽，重置其循环（仍排除当天已选）
        for s in base:
            used_side.discard(s["title"])
        avail = [s for s in base if s["title"] not in exclude_titles]
    if not avail:
        avail = list(base)

    if preferred_tags:
        ordered = sorted(avail, key=lambda r: (-_ingredient_score(r, preferred_tags),
                                               base.index(r)))
        if _ingredient_score(ordered[0], preferred_tags) > 0:
            return ordered[0]
    return avail[day_index % len(avail)]


def generate_month_plan(year, month, recipes, holidays):
    """生成月度食谱计划"""
    # 按类型分组
    breakfasts = recipes.get("breakfast", [])
    lunches = recipes.get("lunch", [])
    dinners = recipes.get("dinner", [])
    sides = recipes.get("side", [])

    # 获取当月天数
    _, days_in_month = calendar.monthrange(year, month)

    used_breakfast = set()
    used_lunch = set()
    used_dinner = set()
    used_side = set()

    # 记录上一餐的食材标签，用于聚类
    last_breakfast_tags = set()
    last_lunch_tags = set()
    last_dinner_tags = set()

    plan = []
    day_index = 0

    for day in range(1, days_in_month + 1):
        d = date(year, month, day)
        day_type, holiday_name = get_day_type(d, holidays)

        # 确定当天需要哪些餐
        needs_breakfast = True
        if day_type == "workday":
            needs_lunch = False
            needs_dinner = False
        else:  # weekend or holiday
            needs_lunch = True
            needs_dinner = True

        entry = {
            "date": d,
            "weekday_cn": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][d.weekday()],
            "day_type": day_type,
            "holiday_name": holiday_name,
            "breakfast": None,
            "lunch": None,
            "dinner": None,
            "lunch_extra": None,
            "dinner_extra": None,
        }

        if needs_breakfast and breakfasts:
            picked = pick_recipes(breakfasts, 1, used_breakfast, day_index,
                                  preferred_tags=last_breakfast_tags)
            entry["breakfast"] = picked[0]
            used_breakfast.add(picked[0]["title"])
            # 更新上一餐食材标签
            last_breakfast_tags = set(picked[0].get("ingredient_tags", []))

        if needs_lunch and lunches:
            picked = pick_recipes(lunches, 1, used_lunch, day_index,
                                  preferred_tags=last_lunch_tags)
            entry["lunch"] = picked[0]
            used_lunch.add(picked[0]["title"])
            last_lunch_tags = set(picked[0].get("ingredient_tags", []))
            # 全餐日加菜：午餐补 1 道，凑齐 3 道
            if sides:
                s = pick_side(sides, used_side, day_index, preferred_tags=last_lunch_tags)
                entry["lunch_extra"] = s
                used_side.add(s["title"])

        if needs_dinner and dinners:
            picked = pick_recipes(dinners, 1, used_dinner, day_index,
                                  preferred_tags=last_dinner_tags)
            entry["dinner"] = picked[0]
            used_dinner.add(picked[0]["title"])
            last_dinner_tags = set(picked[0].get("ingredient_tags", []))
            # 全餐日加菜：晚餐补 1 道，凑齐 3 道（排除当天午餐加菜，避免重复）
            if sides:
                exclude = set()
                if entry.get("lunch_extra"):
                    exclude.add(entry["lunch_extra"]["title"])
                s = pick_side(sides, used_side, day_index,
                              preferred_tags=last_dinner_tags, exclude_titles=exclude,
                              prefer_category="粗粮")
                entry["dinner_extra"] = s
                used_side.add(s["title"])

        plan.append(entry)
        day_index += 1

    return plan


def format_monthly_markdown(year, month, plan, holidays):
    """生成本月食谱概览 Markdown 文件"""
    lines = []
    lines.append(f"# {year}年{month}月 家庭食谱计划\n")
    lines.append(f"> 一家四口 | 儿童友好 | 不辣少油盐\n")

    # 统计
    breakfast_count = sum(1 for p in plan if p["breakfast"])
    lunch_count = sum(1 for p in plan if p["lunch"])
    dinner_count = sum(1 for p in plan if p["dinner"])
    lines.append(f"**本月概览：** {len(plan)}天 · 早餐{breakfast_count}餐 · 午餐{lunch_count}餐 · 晚餐{dinner_count}餐\n")
    lines.append("---\n")

    for entry in plan:
        d = entry["date"]
        date_str = f"{d.month}/{d.day}"
        weekday = entry["weekday_cn"]
        day_type = entry["day_type"]

        # 类型标签
        type_labels = {"workday": "📆", "weekend": "🎉", "holiday": "🏖️"}
        type_label = type_labels.get(day_type, "📆")

        title_parts = [f"### {type_label} {date_str}（{weekday}）"]

        if entry["holiday_name"]:
            title_parts.append(f"🎊 {entry['holiday_name']}")

        lines.append(" ".join(title_parts) + "\n")

        if entry["breakfast"]:
            b = entry["breakfast"]
            lines.append(f"  🌅 **早餐：** {b['title']}")
            lines.append(f"    - 工具：{'/'.join(b.get('tools', []))}")
            lines.append(f"    - 用时：{b.get('total_time', '')}")
            lines.append(f"    - 前一晚：{b.get('night_prep', [''])[0] if b.get('night_prep') else '无'}")
            lines.append("")

        if entry["lunch"]:
            l = entry["lunch"]
            lines.append(f"  ☀️ **午餐：** {l['title']}")
            lines.append(f"    - 食材：{'/'.join(i['name'] for i in l.get('ingredients', {}).get(list(l.get('ingredients', {}).keys())[0], []))}")
            if entry.get("lunch_extra"):
                lines.append(f"    - ➕ 加菜：{entry['lunch_extra']['title']}")
            lines.append("")

        if entry["dinner"]:
            di = entry["dinner"]
            lines.append(f"  🌙 **晚餐：** {di['title']}")
            lines.append(f"    - 食材：{'/'.join(i['name'] for i in di.get('ingredients', {}).get(list(di.get('ingredients', {}).keys())[0], []))}")
            if entry.get("dinner_extra"):
                lines.append(f"    - ➕ 加菜：{entry['dinner_extra']['title']}")
            lines.append("")

        lines.append("---\n")

    return "\n".join(lines)


def _append_dish_detail(lines, dish):
    """把一道菜的用料和做法追加到卡片（用于加菜，置于所属餐区块内）"""
    lines.append(f"### ➕ 加菜：{dish['title']}\n")
    for section, items in dish.get("ingredients", {}).items():
        if isinstance(items, list) and len(items) > 0:
            lines.append(f"**{section}：**\n")
            for item in items:
                note = f"（{item.get('note', '')}）" if item.get("note") else ""
                opt = "（可选）" if item.get("optional") else ""
                lines.append(f"- {item['name']} {item.get('amount', '')}{note}{opt}")
            lines.append("")
    if dish.get("steps"):
        lines.append("**做法：**\n")
        for step_item in dish["steps"]:
            step_text = step_item["step"] if isinstance(step_item, dict) else step_item
            tool = step_item.get("tool", "") if isinstance(step_item, dict) else ""
            tool_tag = f" 🔧{tool}" if tool else ""
            lines.append(f"- {step_text}{tool_tag}")
        lines.append("")


def write_daily_card(entry):
    """为每一天生成详细的食谱卡片文件"""
    d = entry["date"]
    filename = DAILY_DIR / f"{d.year}-{d.month:02d}-{d.day:02d}.md"
    os.makedirs(DAILY_DIR, exist_ok=True)

    lines = []
    lines.append(f"# {d.year}年{d.month}月{d.day}日（{entry['weekday_cn']}）\n")

    if entry["holiday_name"]:
        lines.append(f"🎊 {entry['holiday_name']}假期\n")

    if entry["breakfast"]:
        b = entry["breakfast"]
        lines.append("---\n")
        lines.append("## 🌅 早餐\n")
        lines.append(f"### {b['title']}\n")
        lines.append(f"**用时：** {b.get('total_time', '')}\n")
        lines.append(f"**工具：** {'、'.join(b.get('tools', []))}\n")

        # 食材
        lines.append("### 用料\n")
        for section, items in b.get("ingredients", {}).items():
            if isinstance(items, list) and len(items) > 0:
                lines.append(f"**{section}：**\n")
                for item in items:
                    note = f"（{item.get('note', '')}）" if item.get("note") else ""
                    opt = "（可选）" if item.get("optional") else ""
                    lines.append(f"- {item['name']} {item.get('amount', '')}{note}{opt}")
                lines.append("")

        # 前一晚准备
        if b.get("night_prep"):
            lines.append("### 🕐 前一晚准备\n")
            for step in b["night_prep"]:
                lines.append(f"- [ ] {step}")
            lines.append("")

        # 早上步骤
        if b.get("morning_steps"):
            lines.append("### 🌤️ 早上操作（≤30分钟）\n")
            for i, step in enumerate(b["morning_steps"], 1):
                lines.append(f"{i}. {step}")
            lines.append("")

        # 备注
        if b.get("notes"):
            lines.append(f"💡 {b['notes']}\n")

    if entry["lunch"]:
        l = entry["lunch"]
        lines.append("---\n")
        lines.append("## ☀️ 午餐\n")
        lines.append(f"### {l['title']}\n")

        for section, items in l.get("ingredients", {}).items():
            if isinstance(items, list) and len(items) > 0:
                lines.append(f"**{section}：**\n")
                for item in items:
                    note = f"（{item.get('note', '')}）" if item.get("note") else ""
                    lines.append(f"- {item['name']} {item.get('amount', '')}{note}")
                lines.append("")

        lines.append("### 做法\n")
        for step_item in l.get("steps", []):
            step_text = step_item["step"] if isinstance(step_item, dict) else step_item
            tool = step_item.get("tool", "") if isinstance(step_item, dict) else ""
            tool_tag = f" 🔧{tool}" if tool else ""
            lines.append(f"- {step_text}{tool_tag}")
        lines.append("")

        if entry.get("lunch_extra"):
            _append_dish_detail(lines, entry["lunch_extra"])

    if entry["dinner"]:
        di = entry["dinner"]
        lines.append("---\n")
        lines.append("## 🌙 晚餐\n")
        lines.append(f"### {di['title']}\n")

        for section, items in di.get("ingredients", {}).items():
            if isinstance(items, list) and len(items) > 0:
                lines.append(f"**{section}：**\n")
                for item in items:
                    note = f"（{item.get('note', '')}）" if item.get("note") else ""
                    lines.append(f"- {item['name']} {item.get('amount', '')}{note}")
                lines.append("")

        lines.append("### 做法\n")
        for step_item in di.get("steps", []):
            step_text = step_item["step"] if isinstance(step_item, dict) else step_item
            tool = step_item.get("tool", "") if isinstance(step_item, dict) else ""
            tool_tag = f" 🔧{tool}" if tool else ""
            lines.append(f"- {step_text}{tool_tag}")
        lines.append("")

        if entry.get("dinner_extra"):
            _append_dish_detail(lines, entry["dinner_extra"])

    # 采购清单汇总
    lines.append("---\n")
    lines.append("## 🛒 当日采购清单\n")
    all_ingredients = []
    for meal_type in ["breakfast", "lunch", "dinner", "lunch_extra", "dinner_extra"]:
        meal = entry.get(meal_type)
        if meal:
            for section, items in meal.get("ingredients", {}).items():
                if isinstance(items, list):
                    for item in items:
                        amount = item.get("amount", "")
                        note = item.get("note", "")
                        full_note = f"（{note}）" if note else ""
                        all_ingredients.append(f"- {item['name']} {amount} {full_note}")
    lines.extend(all_ingredients)

    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return filename


def generate_shopping_list(entry):
    """生成次日采购清单文本"""
    items = []
    for meal_type in ["breakfast", "lunch", "dinner"]:
        meal = entry[meal_type]
        if meal:
            for section, item_list in meal.get("ingredients", {}).items():
                if isinstance(item_list, list):
                    for item in item_list:
                        if not item.get("optional"):
                            items.append(f"  {item['name']} {item.get('amount', '')}")
    return "\n".join(items)


def collect_night_prep(entry):
    """收集所有可以前一晚完成的操作"""
    steps = []
    for meal_type in ["breakfast", "lunch", "dinner"]:
        meal = entry[meal_type]
        if meal and meal.get("night_prep"):
            steps.append(f"\n--- {meal['title']} ---")
            steps.extend(meal["night_prep"])
    return steps


def main():
    parser = argparse.ArgumentParser(description="月度食谱计划生成器")
    parser.add_argument("--year", type=int, default=datetime.now().year, help="年份")
    parser.add_argument("--month", type=int, default=datetime.now().month, help="月份")
    parser.add_argument("--output", type=str, help="输出文件路径")
    args = parser.parse_args()

    # 加载配置
    family = load_yaml(CONFIG_DIR / "family.yaml")
    holidays_config = load_yaml(CONFIG_DIR / "holidays-2026.yaml")
    holidays = holidays_config.get("holidays", [])

    print(f"📋 正在生成 {args.year}年{args.month}月 食谱计划...")

    # 加载所有食谱
    recipes = {}
    for recipe_type in ["breakfast", "lunch", "dinner", "side"]:
        recipes[recipe_type] = load_all_recipes(recipe_type)
        print(f"  ✅ 已加载 {len(recipes[recipe_type])} 道{recipe_type}食谱")

    if not any(recipes.values()):
        print("❌ 未找到任何食谱！请先创建食谱文件。")
        sys.exit(1)

    # 生成月度计划
    plan = generate_month_plan(args.year, args.month, recipes, holidays)

    # 保存月度概览
    os.makedirs(PLANS_DIR, exist_ok=True)
    output_file = args.output or str(PLANS_DIR / f"{args.year}-{args.month:02d}.md")
    markdown = format_monthly_markdown(args.year, args.month, plan, holidays)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(markdown)
    print(f"  ✅ 月度计划已保存: {output_file}")

    # 生成每日卡片（只生成从今天及之后的）
    today = datetime.now().date()
    daily_count = 0
    for entry in plan:
        if entry["date"] >= today:
            filename = write_daily_card(entry)
            daily_count += 1
    print(f"  ✅ 已生成 {daily_count} 张每日卡片")

    print(f"\n🎉 {args.year}年{args.month}月食谱计划生成完成！")
    print(f"   早餐 {sum(1 for p in plan if p['breakfast'])} 餐")
    print(f"   午餐 {sum(1 for p in plan if p['lunch'])} 餐")
    print(f"   晚餐 {sum(1 for p in plan if p['dinner'])} 餐")
    print(f"   共 {len(plan)} 天")


if __name__ == "__main__":
    main()
