#!/usr/bin/env bash
# cron/scripts/stock-pick.sh — 每天 09:00 推送 10 支最具投资价值的股票
# 5 支长线（未来潜力最高）+ 5 支短线（短期可获利），优先港股/美股
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
exec /opt/homebrew/bin/python3 "${REPO_ROOT}/cron/jobs/stock_pick.py"
