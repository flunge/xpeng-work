#!/usr/bin/env python3
"""统计某月日计划中菜品重复情况。用法: python3 check_dup.py 2026-07"""
import sys, re
from pathlib import Path
from collections import defaultdict

month = sys.argv[1] if len(sys.argv) > 1 else "2026-07"
DAILY = Path(__file__).resolve().parent.parent / "plans" / "daily"

MEALS = ["🌅 早餐", "☀️ 午餐", "🌙 晚餐"]

def split_dishes(title):
    # 去掉「加菜」「➕」等前缀标记
    title = re.sub(r"➕\s*加菜[:：]?", "", title)
    # 按 + ＋ 、 拆分
    parts = re.split(r"[+＋、]", title)
    dishes = []
    for p in parts:
        p = p.strip()
        # 去掉括号注释如（儿童版）
        p = re.sub(r"[（(].*?[)）]", "", p).strip()
        if p:
            dishes.append(p)
    return dishes

# meal_type -> dish -> [dates]
stat = defaultdict(lambda: defaultdict(list))
all_stat = defaultdict(list)
files = sorted(DAILY.glob(f"{month}-*.md"))
print(f"检查 {month}，共 {len(files)} 天\n")

for f in files:
    day = f.stem[-2:]
    content = f.read_text(encoding="utf-8")
    for i, meal in enumerate(MEALS):
        marker = f"## {meal}"
        if marker not in content:
            continue
        seg = content.split(marker, 1)[1]
        # 截到下一餐或采购
        for nxt in MEALS[i+1:] + ["🛒 当日采购"]:
            if f"## {nxt}" in seg:
                seg = seg.split(f"## {nxt}")[0]
                break
        # 该餐内所有 ### 标题（含加菜）
        titles = re.findall(r"^###\s+(.+)$", seg, re.M)
        # 排除纯步骤性标题
        for t in titles:
            if any(k in t for k in ["用料", "做法", "前一晚", "早上操作", "🕐", "🌤️"]):
                continue
            for d in split_dishes(t):
                mt = meal[2:]
                stat[mt][d].append(day)
                all_stat[d].append((mt, day))

for mt in ["早餐", "午餐", "晚餐"]:
    dups = {d: days for d, days in stat[mt].items() if len(days) > 1}
    print(f"===== {mt} =====")
    if not dups:
        print("  ✅ 无重复\n")
        continue
    for d, days in sorted(dups.items(), key=lambda x: -len(x[1])):
        print(f"  ⚠️ {d}  出现 {len(days)} 次: {', '.join(days)}日")
    print()

print("===== 跨餐次全月出现≥3次的菜 =====")
cross = {d: v for d, v in all_stat.items() if len(v) >= 3}
if not cross:
    print("  无")
for d, v in sorted(cross.items(), key=lambda x: -len(x[1])):
    print(f"  {d}: {len(v)}次 -> " + ", ".join(f"{mt}{day}" for mt, day in v))
