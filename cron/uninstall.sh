#!/usr/bin/env bash
# cron/uninstall.sh — 卸载所有 cron/ LaunchAgent
# 用法: bash cron/uninstall.sh

set -euo pipefail

LAUNCH_DIR="$HOME/Library/LaunchAgents"

LABELS=(
    com.xpeng.daily-sync
    com.xpeng.week-label
    com.xpeng.risk-push
    com.xpeng.stock-pick
    com.xpeng.ai-news
    com.xpeng.morning-chat
    com.xpeng.noon-chat
    com.xpeng.evening-chat
    com.xpeng.meal-notify
    com.xpeng.meal-generate-month
)

echo "🔄 卸载 LaunchAgent…"
for label in "${LABELS[@]}"; do
    launchctl unload "$LAUNCH_DIR/${label}.plist" 2>/dev/null || true
    rm -f "$LAUNCH_DIR/${label}.plist"
    echo "   ✅ $label"
done

echo ""
echo "✅ 已卸载 ${#LABELS[@]} 个 LaunchAgent"
echo ""
echo "如需恢复 crontab，可从备份恢复:"
echo "   crontab cron/crontab.backup.*"
echo "或重新安装 LaunchAgent:"
echo "   bash cron/install.sh"
