#!/usr/bin/env bash
# cron/scripts/meal-generate-month.sh — 每月最后一天 20:00 生成下月计划
set -euo pipefail
cd /Users/xpeng/Documents/daily/personal/meal && /bin/bash scripts/generate_next_month.sh
