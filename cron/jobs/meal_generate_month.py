#!/usr/bin/env python3
"""
月末生成下月食谱计划 — Python 启动器
替代 cron/scripts/meal-generate-month.sh 的 bash wrapper，绕过 /bin/bash 的 TCC 限制。

逻辑：检查今天是否本月最后一天（明天是否跨月），是则调用 generate_month.py 生成下月计划。
由 LaunchAgent 在每月 28-31 日 20:00 触发（脚本内部判断，非月末自动跳过）。
"""
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

# meal 项目根目录（cron/jobs/ 的上三级 → repo root → personal/meal）
MEAL_DIR = Path(__file__).resolve().parent.parent.parent / "personal" / "meal"
LOG_FILE = MEAL_DIR / "notifications" / "cron.log"

today = date.today()
tomorrow = today + timedelta(days=1)

if tomorrow.month != today.month:
    # 今天是月末，生成下月计划
    first_of_month = today.replace(day=1)
    next_first = (first_of_month + timedelta(days=32)).replace(day=1)
    result = subprocess.run([
        sys.executable,
        str(MEAL_DIR / "scripts" / "generate_month.py"),
        "--year", str(next_first.year),
        "--month", str(next_first.month),
    ])
    msg = f"✅ 已生成 {next_first.year}年{next_first.month}月食谱计划\n"
    sys.stderr.write(msg)
    sys.exit(result.returncode)
else:
    msg = f"⏭️ {today}: 今天不是本月最后一天，跳过\n"
    sys.stderr.write(msg)
