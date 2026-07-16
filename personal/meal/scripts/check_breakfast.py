#!/usr/bin/env python3
"""统计某月早餐『主食』重复（剥离蛋/饮品组件，只看主食主体）。
用法: python3 check_breakfast.py 2026-07"""
import sys, re
from pathlib import Path
from collections import defaultdict

month = sys.argv[1] if len(sys.argv) > 1 else "2026-07"
DAILY = Path(__file__).resolve().parent.parent / "plans" / "daily"

# 饮品/蛋类组件关键词——这些属于三件套固定组件，不算主食重样
DRINK_KW = ["牛奶", "豆浆", "米糊", "汁", "浆", "露", "糊", "酸奶", "奶"]
EGG_KW = ["蛋"]

def is_component(part):
    """判断某个 + 分段是否为『蛋』或『饮品』组件（而非主食）"""
    p = part.strip()
    # 纯蛋组件：煎蛋/水煮蛋/溏心蛋/鹌鹑蛋/荷包蛋…（短词且含蛋）
    if any(k in p for k in EGG_KW) and len(p) <= 5:
        return True
    # 纯饮品组件
    if any(p.endswith(k) or p == k for k in DRINK_KW) and len(p) <= 7:
        return True
    return False

stat = defaultdict(list)
files = sorted(DAILY.glob(f"{month}-*.md"))
print(f"检查 {month} 早餐主食，共 {len(files)} 天\n")

for f in files:
    day = f.stem[-2:]
    content = f.read_text(encoding="utf-8")
    if "## 🌅 早餐" not in content:
        continue
    seg = content.split("## 🌅 早餐", 1)[1]
    for nxt in ["## ☀️", "## 🌙", "## 🛒"]:
        if nxt in seg:
            seg = seg.split(nxt)[0]
            break
    m = re.search(r"^###\s+(.+)$", seg, re.M)
    if not m:
        continue
    title = m.group(1).strip()
    parts = [p.strip() for p in re.split(r"[+＋]", title)]
    mains = [p for p in parts if not is_component(p)]
    main_key = " + ".join(mains) if mains else title
    stat[main_key].append(day)

dups = {k: v for k, v in stat.items() if len(v) > 1}
print(f"不同早餐主食组合数: {len(stat)} 种 / {len(files)} 天")
if not dups:
    print("✅ 早餐主食 30 天内无重样！")
else:
    print("\n⚠️ 重样的早餐主食：")
    for k, v in sorted(dups.items(), key=lambda x: -len(x[1])):
        print(f"  {k}  ×{len(v)}: {', '.join(v)}日")
