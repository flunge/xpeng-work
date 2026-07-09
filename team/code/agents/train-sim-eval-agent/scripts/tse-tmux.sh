#!/usr/bin/env bash
# tse-tmux.sh —— 用 tmux 在 5080 台架常驻两个进程：
#   窗口 temporal : Temporal dev server（127.0.0.1:7233，SQLite 持久化）
#   窗口 agentd   : tse-agentd（控制 API :8443 + Temporal Worker 同进程）
#
# 用法:
#   ./scripts/tse-tmux.sh start     # 创建会话并拉起两个进程（先起 dev server，等 7233 就绪再起 agentd）
#   ./scripts/tse-tmux.sh stop      # 杀掉 tmux 会话（停止两个进程）
#   ./scripts/tse-tmux.sh restart   # 重启
#   ./scripts/tse-tmux.sh status    # 查看会话/端口/健康
#   ./scripts/tse-tmux.sh attach    # 进入会话查看实时输出（Ctrl-b d 脱离）
#   ./scripts/tse-tmux.sh logs      # 抓取两个窗口最近输出（不进入会话）
#
# 可用环境变量覆盖默认值:
#   TSE_TMUX_SESSION   tmux 会话名         (默认 tse)
#   TSE_VENV           venv 目录           (默认 <项目目录>/.venv)
#   TSE_TEMPORAL_DB    dev server 持久化db (默认 <项目目录>/temporal.db)
#   TEMPORAL_BIN       temporal CLI 路径   (默认 PATH 中的 temporal)
set -euo pipefail

# —— 路径推导：脚本位于 <项目目录>/scripts/ ——
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

SESSION="${TSE_TMUX_SESSION:-tse}"
VENV="${TSE_VENV:-$PROJECT_DIR/.venv}"
TEMPORAL_DB="${TSE_TEMPORAL_DB:-$PROJECT_DIR/temporal.db}"
TEMPORAL_BIN="${TEMPORAL_BIN:-temporal}"
AGENTD_BIN="$VENV/bin/tse-agentd"
TEMPORAL_HOST="127.0.0.1"
TEMPORAL_PORT="7233"

log()  { printf '\033[32m[tse-tmux]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[tse-tmux]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31m[tse-tmux] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

require_tmux() {
  command -v tmux >/dev/null 2>&1 || die "未找到 tmux，请先安装：sudo apt-get install -y tmux"
}

session_exists() { tmux has-session -t "$SESSION" 2>/dev/null; }

# 用 bash 内置 /dev/tcp 探测端口是否可连（不依赖 nc/ss）
port_open() {
  (exec 3<>"/dev/tcp/$TEMPORAL_HOST/$TEMPORAL_PORT") 2>/dev/null && exec 3>&- 3<&- && return 0
  return 1
}

wait_temporal_ready() {
  local tries="${1:-60}"   # 最多等 tries*0.5s（默认 30s）
  log "等待 Temporal $TEMPORAL_HOST:$TEMPORAL_PORT 就绪 ..."
  for ((i = 0; i < tries; i++)); do
    if port_open; then log "Temporal 已就绪"; return 0; fi
    sleep 0.5
  done
  warn "等待 $TEMPORAL_PORT 超时；agentd 仍会尝试连接（连不上会退出，请用 logs 检查 dev server）"
  return 1
}

# 等待 Temporal 完全停止：7233 端口关闭 + dev server 进程退出。
# restart 时用它替代固定 sleep，确保 temporal.db 的文件锁已随旧进程释放，
# 避免新 dev server 启动时 SQLITE_BUSY（database is locked）。
wait_temporal_stopped() {
  local tries="${1:-40}"   # 最多等 tries*0.5s（默认 20s）
  log "等待旧 Temporal 退出并释放 $TEMPORAL_HOST:$TEMPORAL_PORT ..."
  for ((i = 0; i < tries; i++)); do
    if ! port_open && ! pgrep -f 'temporal server start-dev' >/dev/null 2>&1; then
      log "旧 Temporal 已退出，端口/db 锁已释放"
      return 0
    fi
    sleep 0.5
  done
  warn "等待旧 Temporal 退出超时；继续启动可能撞 SQLite 锁，必要时手动 kill 残留 temporal 进程"
  return 1
}

preflight() {
  [[ -x "$AGENTD_BIN" ]] || die "未找到 $AGENTD_BIN —— 请先在项目目录建 venv 并安装：
    python3 -m venv .venv && source .venv/bin/activate && pip install -e \".[server,eval]\""
  command -v "$TEMPORAL_BIN" >/dev/null 2>&1 || die "未找到 temporal CLI（$TEMPORAL_BIN）；见 docs/deployment-bench.md §2.4 安装"
  [[ -f "$PROJECT_DIR/.env" ]] || warn "未发现 $PROJECT_DIR/.env —— agentd 将用默认配置，凭据可能缺失（cp .env.example .env 后填写）"
}

cmd_start() {
  require_tmux
  if session_exists; then
    warn "tmux 会话 '$SESSION' 已存在；如需重启请先： $0 stop（或用 $0 restart）"
    cmd_status
    return 0
  fi
  preflight

  log "创建 tmux 会话 '$SESSION'，窗口1启动 Temporal dev server ..."
  # 进程崩溃时保留窗格输出，便于排查
  tmux new-session -d -s "$SESSION" -n temporal \
    "exec '$TEMPORAL_BIN' server start-dev --db-filename '$TEMPORAL_DB' --ip '$TEMPORAL_HOST'"
  tmux set-option -t "$SESSION" remain-on-exit on >/dev/null

  wait_temporal_ready 60 || true

  log "窗口2启动 tse-agentd（cwd=$PROJECT_DIR，读取 ./.env）..."
  tmux new-window -t "$SESSION" -n agentd \
    "cd '$PROJECT_DIR' && exec '$AGENTD_BIN'"

  sleep 1
  log "已拉起。查看实时输出： $0 attach   ｜   健康检查： $0 status"
}

cmd_stop() {
  require_tmux
  if session_exists; then
    log "停止 tmux 会话 '$SESSION' ..."
    tmux kill-session -t "$SESSION"
    log "已停止"
  else
    warn "tmux 会话 '$SESSION' 不存在，无需停止"
  fi
}

cmd_restart() {
  require_tmux
  cmd_stop || true
  # 关键：等旧 Temporal 进程退出 + 7233 端口释放，再启动，
  # 否则新旧 dev server 争抢 temporal.db 的 SQLite 写锁 → SQLITE_BUSY 启动失败。
  wait_temporal_stopped 40 || true
  sleep 1                       # 额外缓冲，给 SQLite WAL 收尾/文件锁释放留时间
  cmd_start
}

cmd_status() {
  require_tmux
  echo "== tmux 会话 =="
  if session_exists; then
    tmux list-windows -t "$SESSION"
  else
    echo "(会话 '$SESSION' 未运行)"
  fi
  echo "== 端口监听 =="
  if command -v ss >/dev/null 2>&1; then
    ss -tlnp 2>/dev/null | grep -E ':7233|:8443' || echo "(未监听 7233/8443)"
  else
    port_open && echo "7233 可连" || echo "7233 不可连"
  fi
  echo "== 控制 API 健康 (/list) =="
  if command -v curl >/dev/null 2>&1; then
    curl -fsS http://127.0.0.1:8443/list \
      && echo || echo "(请求失败：确认 agentd 已起、8443 在监听)"
  else
    echo "(未安装 curl，跳过)"
  fi
}

cmd_attach() {
  require_tmux
  session_exists || die "会话 '$SESSION' 未运行，先执行： $0 start"
  exec tmux attach -t "$SESSION"
}

cmd_logs() {
  require_tmux
  session_exists || die "会话 '$SESSION' 未运行"
  for w in temporal agentd; do
    echo "===== [$w] 最近 50 行 ====="
    tmux capture-pane -p -t "$SESSION:$w" 2>/dev/null | tail -n 50 || echo "(无该窗口)"
    echo
  done
}

case "${1:-}" in
  start)   cmd_start ;;
  stop)    cmd_stop ;;
  restart) cmd_restart ;;
  status)  cmd_status ;;
  attach)  cmd_attach ;;
  logs)    cmd_logs ;;
  *) cat <<EOF
用法: $0 {start|stop|restart|status|attach|logs}
  start    创建 tmux 会话并拉起 Temporal dev server + tse-agentd
  stop     停止（kill）tmux 会话
  restart  重启
  status   会话 / 端口(7233,8443) / 控制API 健康检查
  attach   进入会话看实时输出（Ctrl-b d 脱离，不杀进程）
  logs     抓取两个窗口最近输出（不进入会话）
EOF
     exit 1 ;;
esac
