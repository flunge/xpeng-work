#!/bin/bash
# =============================================================
# 灵犀任务触发入口（事件 / 消息驱动统一执行层）
#
# 设计：把"触发"和"执行"解耦。任何触发源都只调用本脚本：
#   - 飞书消息唤起 agent 后，由灵犀调用 `bash /workspace/lingxi-trigger.sh <task>`
#   - 也可被任意外部调度器 / 平台定时任务调用
#
# 用法：bash /workspace/lingxi-trigger.sh <task>
#   task = food | risk | sync | help
# =============================================================
set -u
TASK="${1:-help}"
log() { echo "[$(date -u +'%F %T UTC')] [trigger:$TASK] $*"; }

# 依赖自愈（临时层可能在重启后丢失 PyYAML）
python3 -c "import yaml" 2>/dev/null || pip3 install --break-system-packages -q pyyaml 2>/dev/null || true

case "$TASK" in
  food|食谱|推送食谱|今天食谱|今日食谱|明日食谱)
    log "推送食谱到单聊（今日/明日按北京18点自动判断）…"
    cd /workspace/meal && exec python3 scripts/notify_daily.py
    ;;
  risk|风险|风险播报|项目风险)
    log "推送项目风险播报到单聊…"
    exec /usr/bin/python3 /workspace/team/scripts/risk-push.py
    ;;
  sync|同步|memory|会议纪要|更新memory)
    log "采集会议纪要/主文档更新并更新 memory…"
    exec env PATH=/usr/local/bin:/usr/bin:/bin /workspace/team/scripts/daily-sync.sh
    ;;
  help|*)
    cat <<'EOF'
灵犀可触发任务：
  food  —— 推送「明日食谱」到飞书（meal/notify_daily.py）
  risk  —— 推送「项目风险播报」到飞书（team/risk-push.py）
  sync  —— 采集「会议纪要 / 主文档更新」并更新 memory（team/daily-sync.sh）

用法：bash /workspace/lingxi-trigger.sh <food|risk|sync>
EOF
    ;;
esac
