#!/bin/bash
# 下月食谱计划生成 - 每月最后一天20:00运行
# 检查今天是否是本月最后一天，是则生成下月计划

cd "$(dirname "$0")/.." || exit 1

# 检查明天是否下个月1号（即今天是否本月最后一天）
tomorrow_month=$(python3 -c "from datetime import date, timedelta; print((date.today() + timedelta(days=1)).month)")
current_month=$(date +%m)

if [ "$tomorrow_month" != "$current_month" ]; then
    next_year=$(python3 -c "from datetime import date; print((date.today().replace(day=1) + __import__('datetime').timedelta(days=32)).year)")
    next_month=$(python3 -c "from datetime import date; print((date.today().replace(day=1) + __import__('datetime').timedelta(days=32)).month)")
    python3 scripts/generate_month.py --year "$next_year" --month "$next_month"
    echo "✅ 已生成 ${next_year}年${next_month}月食谱计划" >> notifications/cron.log
else
    echo "⏭️ $(date): 今天不是本月最后一天，跳过" >> notifications/cron.log
fi
