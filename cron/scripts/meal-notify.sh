#!/usr/bin/env bash
# cron/scripts/meal-notify.sh — 每天 18:00 食谱推送
set -euo pipefail
/bin/bash /Users/xpeng/Documents/daily/personal/meal/scripts/run_daily.sh >> /Users/xpeng/Documents/daily/personal/meal/notifications/cron.log 2>&1
