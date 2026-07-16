#!/usr/bin/env bash
# cron/scripts/morning-chat.sh — 每天 09:00 汇报上午关联 chat
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
exec /opt/homebrew/bin/python3 "${REPO_ROOT}/cron/jobs/chat_summary.py" morning
