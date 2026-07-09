#!/usr/bin/env bash
set -euo pipefail

# 仅安装/更新 agents 虚拟环境与 Python 依赖
# 用法：bash agents/scripts/install_deps.sh

AGENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "${AGENT_DIR}/.." && pwd)"
VENV_DIR="${AGENT_DIR}/.venv"

if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 not found" >&2
  exit 1
fi
if ! python3 -c "import venv" 2>/dev/null; then
  echo "error: python3-venv not found. Ubuntu: sudo apt install python3-venv python3-pip" >&2
  exit 1
fi

cd "${AGENT_DIR}"
if [[ ! -d "${VENV_DIR}" ]]; then
  python3 -m venv "${VENV_DIR}"
fi
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
pip install -q --upgrade pip
pip install -q -r "${REPO_ROOT}/requirements-feishu.txt"
echo "Dependencies installed in ${VENV_DIR}"
