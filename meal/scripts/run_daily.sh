#!/bin/bash
# 飞书食谱通知 - 每天18:00运行
# 读取明日食谱并发送到飞书群

cd "$(dirname "$0")/.." || exit 1
# 自愈：PyYAML 可能缺失，缺了就补装
python3 -c "import yaml" 2>/dev/null || pip3 install --break-system-packages -q pyyaml
python3 scripts/notify_daily.py >> notifications/cron.log 2>&1
