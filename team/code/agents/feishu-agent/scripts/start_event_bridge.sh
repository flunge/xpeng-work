#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source .venv/bin/activate

WEBHOOK_URL="${FEISHU_WEBHOOK_URL:-http://127.0.0.1:8091/webhook/feishu/events}"
echo "Forwarding lark-cli events -> ${WEBHOOK_URL}"
exec python -m app.interfaces.feishu_event_bridge --webhook-url "$WEBHOOK_URL" --as bot
