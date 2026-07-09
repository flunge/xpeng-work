#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [[ ! -d .venv ]] || [[ ! -f .venv/bin/activate ]]; then
  bash "$(dirname "${BASH_SOURCE[0]}")/install_deps.sh"
fi
# shellcheck disable=SC1091
source .venv/bin/activate

export FEISHU_MODE="${FEISHU_MODE:-cli}"
export FEISHU_MESSAGE_AS="${FEISHU_MESSAGE_AS:-bot}"
export FEISHU_DOC_AS="${FEISHU_DOC_AS:-bot}"
export FEISHU_DOC_FALLBACK_AS="${FEISHU_DOC_FALLBACK_AS:-user}"
export FEISHU_ENABLE_BOOTSTRAP_GREETING="${FEISHU_ENABLE_BOOTSTRAP_GREETING:-false}"
export FEISHU_DAILY_AI_HOT_ENABLED="${FEISHU_DAILY_AI_HOT_ENABLED:-true}"
export FEISHU_DAILY_AI_HOT_TARGET_CHAT_ID="${FEISHU_DAILY_AI_HOT_TARGET_CHAT_ID:-oc_ccdc18b238a010907ac32ddb81ed7f4c}"
export FEISHU_DAILY_AI_HOT_TIME="${FEISHU_DAILY_AI_HOT_TIME:-09:30}"
export FEISHU_DAILY_AI_HOT_TIMEZONE="${FEISHU_DAILY_AI_HOT_TIMEZONE:-Asia/Shanghai}"
export FEISHU_DAILY_AI_HOT_RUN_ON_STARTUP_IF_MISSED="${FEISHU_DAILY_AI_HOT_RUN_ON_STARTUP_IF_MISSED:-false}"
export OPENAI_TIMEOUT_SECONDS="${OPENAI_TIMEOUT_SECONDS:-180}"

PORT="${FEISHU_AGENT_PORT:-8091}"
echo "Starting 3dgs Feishu Agent on http://127.0.0.1:${PORT}"
if [[ -n "${OPENAI_API_KEY:-}" ]]; then
  echo "LLM: inline (no separate process) ${OPENAI_BASE_URL:-https://socheap.ai/v1} model=${OPENAI_MODEL:-gpt-5.4} effort=${OPENAI_REASONING_EFFORT:-medium} timeout=${OPENAI_TIMEOUT_SECONDS}s"
  echo "LLM health after startup: curl -s http://127.0.0.1:${PORT}/health | python -m json.tool"
else
  echo "LLM: not configured (set OPENAI_API_KEY in agents/.env)"
fi
echo "Daily AI HOT: enabled=${FEISHU_DAILY_AI_HOT_ENABLED} chat=${FEISHU_DAILY_AI_HOT_TARGET_CHAT_ID} at=${FEISHU_DAILY_AI_HOT_TIME} (${FEISHU_DAILY_AI_HOT_TIMEZONE})"
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
