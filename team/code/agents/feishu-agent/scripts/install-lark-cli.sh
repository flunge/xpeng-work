#!/usr/bin/env bash
set -euo pipefail

# 安装飞书 lark-cli（执行 skills/lark-* 与 event bridge 必需，非 pip 包）
# 用法：bash agents/scripts/install-lark-cli.sh
#
# 可选环境变量：
#   INSTALL_NODE=1   无 node/npm 时尝试 apt 安装（默认开启）
#   USE_NODE20=1     尝试通过 NodeSource 安装 Node 20+（需 curl，较慢）

MIN_NODE_MAJOR=18
RECOMMENDED_NODE_MAJOR=20

log() { echo "==> $*"; }
warn() { echo "警告: $*" >&2; }
err() { echo "error: $*" >&2; }

node_major() {
  node -v 2>/dev/null | sed 's/^v//' | cut -d. -f1
}

find_lark_cli() {
  if command -v lark-cli >/dev/null 2>&1; then
    command -v lark-cli
    return 0
  fi
  local npm_bin=""
  if command -v npm >/dev/null 2>&1; then
    npm_bin="$(npm config get prefix 2>/dev/null)/bin/lark-cli"
    if [[ -x "${npm_bin}" ]]; then
      echo "${npm_bin}"
      return 0
    fi
  fi
  if [[ -x "${HOME}/.local/bin/lark-cli" ]]; then
    echo "${HOME}/.local/bin/lark-cli"
    return 0
  fi
  return 1
}

export_npm_bin_path() {
  if ! command -v npm >/dev/null 2>&1; then
    return 0
  fi
  local npm_bin
  npm_bin="$(npm config get prefix 2>/dev/null)/bin"
  if [[ -n "${npm_bin}" && -d "${npm_bin}" ]]; then
    export PATH="${npm_bin}:${PATH}"
  fi
  if [[ -d "${HOME}/.local/bin" ]]; then
    export PATH="${HOME}/.local/bin:${PATH}"
  fi
}

ensure_nodejs() {
  if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    local major
    major="$(node_major)"
    if [[ "${major}" -lt "${MIN_NODE_MAJOR}" ]]; then
      err "Node.js $(node -v) 版本过低，需要 >= v${MIN_NODE_MAJOR}"
      return 1
    fi
    if [[ "${major}" -lt "${RECOMMENDED_NODE_MAJOR}" ]]; then
      warn "当前 Node $(node -v)；官方 npx 安装向导需要 >= v${RECOMMENDED_NODE_MAJOR}，将使用 npm 全局安装。"
    fi
    return 0
  fi

  if [[ "${INSTALL_NODE:-1}" != "1" ]]; then
    err "未找到 node/npm，且 INSTALL_NODE=0。请先安装 Node.js ${MIN_NODE_MAJOR}+。"
    return 1
  fi

  log "未检测到 node/npm，尝试通过 apt 安装 nodejs npm ..."
  if ! command -v apt-get >/dev/null 2>&1; then
    err "无 apt-get，请手动安装 Node.js ${MIN_NODE_MAJOR}+ 与 npm 后重试。"
    return 1
  fi

  local apt_install=(apt-get install -y nodejs npm curl ca-certificates)
  if [[ "$(id -u)" -eq 0 ]]; then
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive "${apt_install[@]}"
  elif command -v sudo >/dev/null 2>&1; then
    sudo apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive "${apt_install[@]}"
  else
    err "需要 root 或 sudo 安装依赖: sudo apt install -y nodejs npm"
    return 1
  fi

  hash -r 2>/dev/null || true
  if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
    err "apt 安装后仍找不到 node/npm"
    return 1
  fi
  log "Node $(node -v), npm $(npm -v)"
}

maybe_install_node20() {
  [[ "${USE_NODE20:-0}" == "1" ]] || return 1
  [[ "$(node_major)" -ge "${RECOMMENDED_NODE_MAJOR}" ]] && return 0

  if ! command -v curl >/dev/null 2>&1; then
    warn "USE_NODE20=1 但未安装 curl，跳过 NodeSource 安装"
    return 1
  fi

  log "尝试安装 Node.js 20（NodeSource）..."
  local setup_cmd=(bash -c "curl -fsSL https://deb.nodesource.com/setup_20.x | bash -")
  if [[ "$(id -u)" -eq 0 ]]; then
    "${setup_cmd[@]}"
    DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs
  elif command -v sudo >/dev/null 2>&1; then
    sudo "${setup_cmd[@]}"
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs
  else
    return 1
  fi
  hash -r 2>/dev/null || true
  log "Node $(node -v)"
}

install_via_npm_global() {
  log "npm install -g @larksuite/cli"
  npm install -g @larksuite/cli
}

install_via_npx_wizard() {
  local major
  major="$(node_major)"
  if [[ "${major}" -lt "${RECOMMENDED_NODE_MAJOR}" ]]; then
    return 1
  fi
  log "npx @larksuite/cli@latest install（官方向导，Node >= ${RECOMMENDED_NODE_MAJOR}）"
  npx --yes @larksuite/cli@latest install
}

ensure_path_hint() {
  export_npm_bin_path
  local cli_path
  if ! cli_path="$(find_lark_cli)"; then
    return 0
  fi
  local npm_bin
  npm_bin="$(dirname "${cli_path}")"
  if [[ ":${PATH}:" != *":${npm_bin}:"* ]]; then
    echo ""
    echo "提示: 若新终端找不到 lark-cli，将下面一行加入 ~/.bashrc："
    echo "  export PATH=\"${npm_bin}:\$PATH\""
  fi
}

# --- main ---
export_npm_bin_path
if cli="$(find_lark_cli)"; then
  echo "lark-cli 已安装: ${cli} ($(lark-cli --version 2>/dev/null || true))"
  exit 0
fi

if ! ensure_nodejs; then
  exit 1
fi

maybe_install_node20 || true
export_npm_bin_path

if ! install_via_npm_global; then
  warn "npm 全局安装失败，尝试官方向导 ..."
fi
export_npm_bin_path
if ! find_lark_cli >/dev/null 2>&1; then
  install_via_npx_wizard || warn "npx 安装向导跳过或失败（Node < 20 时正常）"
fi
export_npm_bin_path
if cli="$(find_lark_cli)"; then
  echo "安装成功: ${cli}"
  lark-cli --version 2>/dev/null || true
  ensure_path_hint
  echo ""
  echo "下一步: lark-cli config init --new && lark-cli auth login"
  exit 0
fi

cat <<'EOF' >&2
lark-cli 已安装但当前 shell 找不到命令。请执行:

  export PATH="$(npm config get prefix)/bin:$HOME/.local/bin:$PATH"
  lark-cli --version

若仍失败，Ubuntu 手动安装:
  sudo apt install -y nodejs npm    # 或 Node 20+: USE_NODE20=1 bash agents/scripts/install-lark-cli.sh
  npm install -g @larksuite/cli

详见: docs/feishu/lark-cli-setup.md
EOF
exit 1
