#!/usr/bin/env bash
# cron/scripts/meal-notify.sh — 每天 18:00 食谱推送
set -euo pipefail
MEAL_DIR="/Users/xpeng/Documents/daily/personal/meal"
mkdir -p "$MEAL_DIR/notifications"
/bin/bash "$MEAL_DIR/scripts/run_daily.sh" >> "$MEAL_DIR/notifications/cron.log" 2>&1
