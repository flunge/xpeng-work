#!/usr/bin/env bash
# cron/scripts/risk-push.sh — 每天 09:00 项目风险播报
set -euo pipefail
/opt/homebrew/bin/python3 /Users/xpeng/Documents/daily/team/scripts/risk-push.py >> /Users/xpeng/Documents/daily/team/memory/daily-sync/risk-push-stdout.log 2>&1
