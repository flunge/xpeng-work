#!/usr/bin/env bash
# cron/scripts/daily-sync.sh — 每日 22:00 数据同步
set -euo pipefail
cd /Users/xpeng/Documents/daily/team
bash scripts/daily-sync.sh >> memory/daily-sync/launchd-stdout.log 2>&1
