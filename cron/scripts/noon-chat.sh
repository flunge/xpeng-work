#!/usr/bin/env bash
# cron/scripts/noon-chat.sh — 每天 12:00 汇报上午关联 chat
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
exec /opt/homebrew/bin/python3 "${REPO_ROOT}/cron/jobs/chat_summary.py" noon
