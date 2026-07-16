#!/bin/bash
# 检查飞书群反馈 - 每2小时运行一次
cd "$(dirname "$0")/.." || exit 1
python3 scripts/check_feedback.py >> notifications/feedback_cron.log 2>&1
