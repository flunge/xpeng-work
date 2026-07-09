#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

bash scripts/start_local_agent.sh &
AGENT_PID=$!
sleep 2
bash scripts/start_event_bridge.sh &
BRIDGE_PID=$!

echo "Feishu agent PID=${AGENT_PID}, event bridge PID=${BRIDGE_PID}"
echo "Agent: http://127.0.0.1:${FEISHU_AGENT_PORT:-8091}"
echo "Press Ctrl+C to stop both."
wait
