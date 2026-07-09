#!/usr/bin/env bash
set -euo pipefail

# 3DGS 飞书 / Skills 开发环境一键安装（Ubuntu）
# 用法（仓库根）: bash agents/scripts/setup-dev-environment.sh
#
# 安装：Python venv + requirements-feishu.txt、lark-cli、.cursor/.agents skill 链接

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
AGENT_DIR="${SCRIPT_DIR}/.."
VENV_DIR="${AGENT_DIR}/.venv"
SKIP_LARK_CLI=false
SKIP_AGENT=false
SKIP_LINKS=false

usage() {
  cat <<'EOF'
Usage: bash agents/scripts/setup-dev-environment.sh [options]

Options:
  --skip-lark-cli    不安装 lark-cli
  --skip-agent       不安装 Python 虚拟环境
  --skip-links       不创建 .cursor/.agents 符号链接
  -h, --help         帮助

安装后（首次）:
  lark-cli config init --new
  lark-cli auth login
  cd agents && cp .env.example .env
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-lark-cli) SKIP_LARK_CLI=true ;;
    --skip-agent) SKIP_AGENT=true ;;
    --skip-links) SKIP_LINKS=true ;;
    -h | --help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage; exit 1 ;;
  esac
  shift
done

echo "==> 3DGS dev environment (repo=${REPO_ROOT})"

if [[ "${SKIP_AGENT}" == "false" ]]; then
  bash "${SCRIPT_DIR}/install_deps.sh"
else
  echo "==> skip Python venv (--skip-agent)"
fi

if [[ "${SKIP_LARK_CLI}" == "false" ]]; then
  bash "${SCRIPT_DIR}/install-lark-cli.sh"
else
  echo "==> skip lark-cli (--skip-lark-cli)"
fi

if [[ "${SKIP_LINKS}" == "false" ]]; then
  bash "${SCRIPT_DIR}/setup-skills-links.sh"
else
  echo "==> skip skill links (--skip-links)"
fi

echo ""
echo "==> verification"
if [[ "${SKIP_AGENT}" == "false" ]]; then
  # shellcheck disable=SC1091
  source "${VENV_DIR}/bin/activate"
  python3 -c "import fastapi, uvicorn, requests; print('    python: fastapi, uvicorn, requests OK')"
  deactivate 2>/dev/null || true
fi
if [[ "${SKIP_LARK_CLI}" == "false" ]] && command -v lark-cli >/dev/null 2>&1; then
  if lark-cli auth status 2>/dev/null | grep -q '"tokenStatus": "valid"'; then
    echo "    lark-cli: auth valid"
  else
    echo "    lark-cli: run config init + auth login"
  fi
fi
[[ -L "${REPO_ROOT}/.cursor/skills" ]] && echo "    .cursor/skills -> $(readlink "${REPO_ROOT}/.cursor/skills")"

cat <<EOF

==> next steps
  bash agents/scripts/start_all.sh   # 启动 Bot（需先配置 .env）
  文档: docs/feishu/team-skills-and-agent-guide.md
EOF
