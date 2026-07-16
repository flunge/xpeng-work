#!/usr/bin/env python3
"""
食谱计划质检 - 同一天跨餐主食不得重复
用法: python3 scripts/qc_plan.py [--months 6,7,8]

检查每日卡片里 早餐/午餐/晚餐/快手午餐 的「主食 signature」（标题第一个 + 前、
去括注的主食名）在同一天是否撞车。退出码非 0 表示有撞车，可接入生成后自检。

沉淀自 2026-06-26：早餐和晚餐都排到「番茄鸡蛋面」却没被发现——
各餐池独立去重，跨餐撞车无人查。质检必须按「同一天的全部餐」逐日核对。
"""

import re
import sys
import glob
import os
import argparse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DAILY_DIR = BASE_DIR / "plans" / "daily"


def signature(title):
    """主食标识：标题第一个 +/＋ 前、去掉括注的主食名。
    「番茄鸡蛋面 + 纯牛奶」与「番茄鸡蛋面 + 煎午餐肉」→ 同为「番茄鸡蛋面」。"""
    if not title:
        return ""
    head = re.split(r"[+＋]", title)[0]
    head = re.split(r"[（(]", head)[0]
    return head.strip()


def first_h3(segment):
    m = re.search(r"^### (.+)$", segment, re.M)
    return m.group(1).strip() if m else None


def parse_day(content):
    """返回 {餐位: 标题}。午餐位可能是完整午餐或快手午餐，取该区块首个 ### 即可。"""
    meals = {}
    if "## 🌅 早餐" in content:
        seg = content.split("## 🌅 早餐", 1)[1]
        for nm in ("## ☀️", "## 🌙", "## 🛒"):
            seg = seg.split(nm)[0]
        meals["早餐"] = first_h3(seg)
    if "## ☀️ 午餐" in content:
        seg = content.split("## ☀️ 午餐", 1)[1]
        for nm in ("## 🌙", "## 🛒"):
            seg = seg.split(nm)[0]
        meals["午餐"] = first_h3(seg)
    if "## 🌙 晚餐" in content:
        seg = content.split("## 🌙 晚餐", 1)[1].split("## 🛒")[0]
        meals["晚餐"] = first_h3(seg)
    return {k: v for k, v in meals.items() if v}


def main():
    parser = argparse.ArgumentParser(description="食谱计划同日跨餐质检")
    parser.add_argument("--months", type=str, default="6,7,8",
                        help="检查的月份（逗号分隔），默认 6,7,8")
    args = parser.parse_args()
    months = [m.strip().zfill(2) for m in args.months.split(",")]

    files = []
    for m in months:
        files += sorted(glob.glob(str(DAILY_DIR / f"2026-{m}-*.md")))

    bad = 0
    for f in files:
        content = open(f, encoding="utf-8").read()
        meals = parse_day(content)
        seen = {}
        for pos, title in meals.items():
            s = signature(title)
            if s in seen:
                print(f"❌ {os.path.basename(f)}: {seen[s]} 与 {pos} 主食都是【{s}】")
                bad += 1
            else:
                seen[s] = pos

    print(f"--- 质检 {len(files)} 天，同日跨餐撞车 {bad} 处 ---")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
