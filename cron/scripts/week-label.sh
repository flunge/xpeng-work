#!/usr/bin/env bash
# cron/scripts/week-label.sh — 每周一 08:00 更新周标题
set -euo pipefail
/opt/homebrew/bin/python3 /Users/xpeng/Documents/daily/.zod/week-label/week-label.py >> /Users/xpeng/Documents/daily/.zod/week-label/week-label.log 2>&1
