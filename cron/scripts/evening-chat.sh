#!/usr/bin/env bash
# cron/scripts/evening-chat.sh — 每天 18:00 汇报下午关联 chat
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
exec /opt/homebrew/bin/python3 "${REPO_ROOT}/cron/jobs/chat_summary.py" evening
