#!/usr/bin/env bash
# cron/scripts/ai-news.sh — 每天 09:00 推送 AI 圈头部 10 条新闻（去重）
# 重点关注：大模型 / 世界模型 / 智驾 / 具身
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
exec /opt/homebrew/bin/python3 "${REPO_ROOT}/cron/jobs/ai_news.py"
