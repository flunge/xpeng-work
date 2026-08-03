#!/usr/bin/env bash
# cron/scripts/daily-sync.sh — 每日 22:00 数据同步
set -euo pipefail
cd /Users/xpeng/Documents/daily/team
bash scripts/daily-sync.sh >> memory/daily-sync/launchd-stdout.log 2>&1

# Episode 事件流增量入库（2026-08-03 合并）：机器人转群 docx + 作战表 revision 监测 → Base Episode事件流
python3 /Users/xpeng/Documents/daily/team/scripts/episode_ingest.py >> /Users/xpeng/Documents/daily/cron/logs/episode_ingest.log 2>&1 || echo "episode_ingest failed" >> /Users/xpeng/Documents/daily/cron/logs/episode_ingest.log
