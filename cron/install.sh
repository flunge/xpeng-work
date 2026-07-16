#!/usr/bin/env bash
# cron/install.sh — 一键安装 crontab（替换现有 crontab）
# 用法: bash cron/install.sh

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cat <<EOF | crontab -
PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin

# ===== 仿真部 team 同步 =====

# 每日数据同步 - 每天 22:00
0 22 * * * ${REPO_ROOT}/cron/scripts/daily-sync.sh

# 周标题更新 - 每周一 08:00
0 8 * * 1 ${REPO_ROOT}/cron/scripts/week-label.sh

# ===== 每日播报（09:00 并行） =====

# 项目风险播报 - 每天 09:00
0 9 * * * ${REPO_ROOT}/cron/scripts/risk-push.sh

# 10支最具投资价值股票 - 每天 09:00
0 9 * * * ${REPO_ROOT}/cron/scripts/stock-pick.sh

# AI圈头部10条新闻 - 每天 09:00
0 9 * * * ${REPO_ROOT}/cron/scripts/ai-news.sh

# ===== Chat 汇报 =====

# 上午 chat 汇报 - 每天 09:00
0 9 * * * ${REPO_ROOT}/cron/scripts/morning-chat.sh

# 中午 chat 汇报 - 每天 12:00
0 12 * * * ${REPO_ROOT}/cron/scripts/noon-chat.sh

# 下午 chat 汇报 - 每天 18:00
0 18 * * * ${REPO_ROOT}/cron/scripts/evening-chat.sh

# ===== 家庭食谱系统 =====

# 食谱通知 - 每天 18:00
0 18 * * * ${REPO_ROOT}/cron/scripts/meal-notify.sh

# 每月最后一天 20:00 生成下月食谱计划
0 20 28-31 * * ${REPO_ROOT}/cron/scripts/meal-generate-month.sh
EOF

echo "✅ crontab installed"
crontab -l
