#!/usr/bin/env bash
# cron/install.sh — 一键安装用户级 LaunchAgent（替代 crontab）
#
# 背景：macOS 的 cron 由系统 launchd 启动，缺少 ~/Documents 的"完全磁盘访问
# 权限"（TCC），导致所有定时任务执行时报 "Operation not permitted"。
# 改用用户级 LaunchAgent：launchd 在用户登录会话中运行，继承对 ~/Documents
# 的完整访问权，绕过 cron 的 TCC 限制。
#
# 进一步优化：9/10 任务直接用 Python 运行（Python 已有"完全磁盘访问权限"），
# 完全绕过 /bin/bash 的 TCC 限制。仅 daily-sync 因含 bash heredoc 仍需 bash。
#
# 用法: bash cron/install.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$REPO_ROOT/cron/logs"
PYTHON="/opt/homebrew/bin/python3"
PATH_ENV="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

LABELS=(
    com.xpeng.daily-sync
    com.xpeng.week-label
    com.xpeng.risk-push
    com.xpeng.stock-pick
    com.xpeng.ai-news
    com.xpeng.morning-chat
    com.xpeng.noon-chat
    com.xpeng.evening-chat
    com.xpeng.meal-notify
    com.xpeng.meal-generate-month
    com.xpeng.larkdocs-sync
    com.xpeng.storyline-gen
)

mkdir -p "$LAUNCH_DIR" "$LOG_DIR"

# ---- 卸载旧任务（忽略未加载的错误）----
echo "🔄 卸载已有 LaunchAgent…"
for label in "${LABELS[@]}"; do
    launchctl unload "$LAUNCH_DIR/${label}.plist" 2>/dev/null || true
done

# ---- 生成 plist 的辅助函数 ----
# 参数: label  schedule_xml  stdout_path  program_args...
emit_plist() {
    local label="$1" schedule="$2" stdout="$3"
    shift 3
    local args_xml=""
    for arg in "$@"; do
        args_xml+="        <string>${arg}</string>"$'\n'
    done
    cat > "$LAUNCH_DIR/${label}.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${label}</string>
    <key>ProgramArguments</key>
    <array>
${args_xml}    </array>
    <key>StartCalendarInterval</key>
${schedule}
    <key>StandardOutPath</key>
    <string>${stdout}</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/${label}-stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>${PATH_ENV}</string>
        <key>HOME</key>
        <string>${HOME}</string>
    </dict>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
PLIST
}

# 调度计划辅助
daily()  { echo "<dict><key>Hour</key><integer>$1</integer><key>Minute</key><integer>${2:-0}</integer></dict>"; }
weekly() { echo "<dict><key>Weekday</key><integer>$1</integer><key>Hour</key><integer>$2</integer><key>Minute</key><integer>${3:-0}</integer></dict>"; }

# 月末 28-31 日 20:00（脚本内部判断是否月末）
MONTHLY_END='<array>
        <dict><key>Day</key><integer>28</integer><key>Hour</key><integer>20</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Day</key><integer>29</integer><key>Hour</key><integer>20</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Day</key><integer>30</integer><key>Hour</key><integer>20</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Day</key><integer>31</integer><key>Hour</key><integer>20</integer><key>Minute</key><integer>0</integer></dict>
    </array>'

echo "📝 生成 plist 文件…"

# ===== 10 个 Python-direct 任务（绕过 bash，直接用 Python）=====

# 1. 周标题更新 — 每周一 08:00
emit_plist com.xpeng.week-label "$(weekly 1 8)" \
    "$REPO_ROOT/.zod/week-label/week-label.log" \
    "$PYTHON" "$REPO_ROOT/.zod/week-label/week-label.py"

# 2. 项目风险播报 — 每天 09:00
emit_plist com.xpeng.risk-push "$(daily 9)" \
    "$REPO_ROOT/team/memory/daily-sync/risk-push-stdout.log" \
    "$PYTHON" "$REPO_ROOT/team/scripts/risk-push.py"

# 3. 10支股票推荐 — 每天 09:00
emit_plist com.xpeng.stock-pick "$(daily 9)" \
    "$LOG_DIR/com.xpeng.stock-pick.log" \
    "$PYTHON" "$REPO_ROOT/cron/jobs/stock_pick.py"

# 4. AI圈新闻 — 每天 09:00
emit_plist com.xpeng.ai-news "$(daily 9)" \
    "$LOG_DIR/com.xpeng.ai-news.log" \
    "$PYTHON" "$REPO_ROOT/cron/jobs/ai_news.py"

# 5. 上午 chat 汇报 — 每天 09:00
emit_plist com.xpeng.morning-chat "$(daily 9)" \
    "$LOG_DIR/com.xpeng.morning-chat.log" \
    "$PYTHON" "$REPO_ROOT/cron/jobs/chat_summary.py" morning

# 6. 中午 chat 汇报 — 每天 12:00
emit_plist com.xpeng.noon-chat "$(daily 12)" \
    "$LOG_DIR/com.xpeng.noon-chat.log" \
    "$PYTHON" "$REPO_ROOT/cron/jobs/chat_summary.py" noon

# 7. 下午 chat 汇报 — 每天 18:00
emit_plist com.xpeng.evening-chat "$(daily 18)" \
    "$LOG_DIR/com.xpeng.evening-chat.log" \
    "$PYTHON" "$REPO_ROOT/cron/jobs/chat_summary.py" evening

# 8. 食谱通知 — 每天 18:00（直接跑 Python，跳过 run_daily.sh 的 bash 包装）
emit_plist com.xpeng.meal-notify "$(daily 18)" \
    "$REPO_ROOT/personal/meal/notifications/cron.log" \
    "$PYTHON" "$REPO_ROOT/personal/meal/scripts/notify_daily.py"

# 9. 生成下月食谱计划 — 每月 28-31 日 20:00（Python 启动器替代 bash）
emit_plist com.xpeng.meal-generate-month "$MONTHLY_END" \
    "$REPO_ROOT/personal/meal/notifications/cron.log" \
    "$PYTHON" "$REPO_ROOT/cron/jobs/meal_generate_month.py"

# ===== 1 个 bash 任务（daily-sync 含 bash heredoc，需 /bin/bash 有完全磁盘访问权限）=====

# 10. 每日数据同步 — 每天 22:00
emit_plist com.xpeng.daily-sync "$(daily 22)" \
    "$REPO_ROOT/team/memory/daily-sync/launchd-stdout.log" \
    /bin/bash "$REPO_ROOT/cron/scripts/daily-sync.sh"

# 11. larkdocs 文档镜像+索引 — 每天 23:00（P0 持久镜像 -> P1 FTS5 索引重建）
emit_plist com.xpeng.larkdocs-sync "$(daily 23)" \
    "$LOG_DIR/com.xpeng.larkdocs-sync.log" \
    "$PYTHON" "$REPO_ROOT/team/scripts/larkdocs_sync.py"

# 12. Storyline 主线卡候选生成 — 每周五 20:00（P2 半自动；写库为候选待确认，李坤周六审）
emit_plist com.xpeng.storyline-gen "$(weekly 5 20)" \
    "$LOG_DIR/com.xpeng.storyline-gen.log" \
    "$PYTHON" "$REPO_ROOT/team/scripts/storyline_gen.py"

# ---- 加载所有 plist ----
echo "🚀 加载 LaunchAgent…"
for label in "${LABELS[@]}"; do
    launchctl load "$LAUNCH_DIR/${label}.plist"
done

# ---- 备份并清空 crontab ----
echo "🧹 备份并清空 crontab…"
if crontab -l 2>/dev/null | grep -q .; then
    BACKUP="$REPO_ROOT/cron/crontab.backup.$(date +%Y%m%d_%H%M%S)"
    crontab -l > "$BACKUP"
    crontab -r
    echo "   crontab 已清空（备份: cron/$(basename "$BACKUP")）"
else
    echo "   crontab 本就为空，无需清理"
fi

# ---- 打印状态 ----
echo ""
echo "✅ 已安装 ${#LABELS[@]} 个 LaunchAgent（11 个 Python-direct + 1 个 bash）："
echo ""
for label in "${LABELS[@]}"; do
    info=$(launchctl list "$label" 2>/dev/null || true)
    if [ -n "$info" ]; then
        printf "  ✅ %-30s loaded\n" "$label"
    else
        printf "  ❌ %-30s 未加载\n" "$label"
    fi
done
echo ""
echo "⚠️  daily-sync 仍通过 /bin/bash 运行，需在系统设置 → 隐私与安全性 →"
echo "   完全磁盘访问权限 中添加 /bin/bash（⌘⇧G 输入 /bin/bash）。"
echo "   其余 11 个任务直接用 Python 运行，无需此步骤。"
echo ""
echo "日志目录: $LOG_DIR/"
echo "卸载:     bash cron/uninstall.sh"
