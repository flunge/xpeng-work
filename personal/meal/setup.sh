#!/bin/bash
# =============================================================
# meal 系统环境引导脚本（Pod 重启后运行一次即可恢复）
#
# 背景：/workspace 与 /platform 在持久盘上，工程文件和 lark-cli
#       授权会保留；但容器 overlay 临时层里的运行依赖
#       （PyYAML、crontab、cron 守护进程）会在 Pod 重启后丢失。
#       本脚本负责把这些临时层依赖补齐。
#
# 用法：bash /workspace/personal/meal/setup.sh
#       SKIP_CRON_DAEMON=1 bash /workspace/personal/meal/setup.sh   # 不启动 cron 守护进程
# =============================================================
set -u

MEAL_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$MEAL_DIR" || exit 1

echo "🍳 meal 环境恢复 @ $MEAL_DIR"

# --- 1. PyYAML ---
echo "[1/4] 检查 PyYAML..."
if python3 -c "import yaml" 2>/dev/null; then
    echo "  ✅ 已安装"
else
    echo "  ⏳ 安装中..."
    pip3 install --break-system-packages pyyaml >/dev/null 2>&1 \
        && echo "  ✅ PyYAML 安装完成" \
        || echo "  ❌ PyYAML 安装失败，请手动 pip3 install --break-system-packages pyyaml"
fi

# --- 2. lark-cli（仅检查，二进制由平台置备） ---
echo "[2/4] 检查 lark-cli..."
if command -v lark-cli >/dev/null 2>&1; then
    echo "  ✅ 已就绪: $(lark-cli --version 2>&1)"
    # 授权配置在 /platform 持久盘，正常情况下无需重新授权
    if [ -f /platform/.lark-cli/config.json ]; then
        echo "  ✅ 飞书配置存在（授权已持久化）"
    else
        echo "  ⚠️ 未找到飞书配置，需重新运行 lark-cli config init / auth login"
    fi
else
    echo "  ⚠️ lark-cli 不在 PATH，需平台重新置备或重新安装后再跑本脚本"
fi

# --- 3. crontab 定时任务 ---
echo "[3/4] 安装 crontab 定时任务..."
CRON_TMP="$(mktemp)"
# 保留非 meal 的既有条目（清掉旧的 meal 行/注释，幂等可重复运行）
crontab -l 2>/dev/null | grep -vE "$MEAL_DIR/scripts|^#meal:" > "$CRON_TMP" || true
cat >> "$CRON_TMP" <<EOF
#meal: --- 家庭食谱系统（由 setup.sh 维护，勿手动改）---
#meal: ⚠️ Pod 时区是 UTC，以下均为 UTC 时间，北京时间需 +8h
#meal: 北京 18:00 = UTC 10:00 —— 每天推送明日食谱
0 10 * * * $MEAL_DIR/scripts/run_daily.sh
#meal: 北京 20:00 = UTC 12:00 —— 月末生成下月计划
0 12 28-31 * * $MEAL_DIR/scripts/generate_next_month.sh
#meal: 每 2 小时检查反馈（与时区无关）
0 */2 * * * $MEAL_DIR/scripts/check_feedback.sh
EOF
if crontab "$CRON_TMP" 2>/dev/null; then
    echo "  ✅ crontab 已安装（北京时间：每日18:00通知 / 月末20:00生成 / 每2h反馈）"
else
    echo "  ❌ crontab 安装失败"
fi
rm -f "$CRON_TMP"

# --- 4. cron 守护进程 ---
echo "[4/4] 检查 cron 守护进程..."
if [ "${SKIP_CRON_DAEMON:-0}" = "1" ]; then
    echo "  ⏭️ 已跳过（SKIP_CRON_DAEMON=1）"
elif pgrep -x cron >/dev/null 2>&1; then
    echo "  ✅ cron 守护进程已在运行"
else
    if command -v cron >/dev/null 2>&1 && cron 2>/dev/null; then
        echo "  ✅ cron 守护进程已启动"
    elif command -v crond >/dev/null 2>&1 && crond 2>/dev/null; then
        echo "  ✅ crond 守护进程已启动"
    else
        echo "  ⚠️ 无法启动 cron 守护进程，定时任务不会自动触发（脚本仍可手动运行）"
    fi
fi

echo "✅ 恢复完成。可用 'crontab -l' 查看定时任务。"
