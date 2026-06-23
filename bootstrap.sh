#!/bin/bash
# =============================================================
# Pod 启动自愈引导（持久盘 /workspace，重启不丢）
#
# ⚠️ 调度已改为「消息 / 事件驱动」：
#     飞书消息唤起灵犀 → 灵犀调用 /workspace/lingxi-trigger.sh <task> 执行。
#     不再使用 in-pod cron —— 按需 pod 重启即失效、且睡着时不触发，不可靠。
#
# 本脚本现在只负责补运行依赖（lingxi-trigger.sh 也会自愈，这里是双保险）。
# 用法：bash /workspace/bootstrap.sh
# =============================================================
set -u
echo "[bootstrap] $(date -u +'%F %T UTC') 检查运行依赖…"
python3 -c "import yaml" 2>/dev/null || pip3 install --break-system-packages -q pyyaml
echo "[bootstrap] 完成。"
echo "[bootstrap] 任务触发：给机器人发消息 → 灵犀执行 /workspace/lingxi-trigger.sh <food|risk|sync>"
echo "[bootstrap] (如需临时启用 in-pod 定时作为 best-effort 兜底，手动运行：bash /workspace/meal/setup.sh)"
