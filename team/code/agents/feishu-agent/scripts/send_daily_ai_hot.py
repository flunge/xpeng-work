#!/usr/bin/env python3
"""手动发送指定日期的 AI HOT 精选到飞书群。用法: python scripts/send_daily_ai_hot.py [YYYY-MM-DD]"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.application.daily_ai_hot import fetch_and_render_daily_ai_hot
from app.infrastructure.feishu_clients import RealFeishuMessageClient
from app.infrastructure.feishu_config import FeishuCliAuthAdapter, FeishuSettings


def main() -> int:
    parser = argparse.ArgumentParser(description="Send AI HOT digest to Feishu group")
    parser.add_argument(
        "report_date",
        nargs="?",
        help="报告日期 YYYY-MM-DD，默认昨天（Asia/Shanghai）",
    )
    parser.add_argument("--no-update-state", action="store_true", help="不更新 daily_ai_hot_state.json")
    args = parser.parse_args()

    tz = ZoneInfo("Asia/Shanghai")
    if args.report_date:
        report = date.fromisoformat(args.report_date)
    else:
        report = (date.today() - timedelta(days=1))

    settings = FeishuSettings.from_env()
    if not settings.daily_ai_hot_target_chat_id:
        print("错误: 未配置 FEISHU_DAILY_AI_HOT_TARGET_CHAT_ID", file=sys.stderr)
        return 1

    message = fetch_and_render_daily_ai_hot(report, tz)
    auth = FeishuCliAuthAdapter(settings)
    auth.validate_ready()
    client = RealFeishuMessageClient(settings, auth)
    result = client.send_text_to_chat(settings.daily_ai_hot_target_chat_id, message)
    print(f"已发送到 {settings.daily_ai_hot_target_chat_id}, message_id={result.message_id}")

    if not args.no_update_state:
        state_path = settings.daily_ai_hot_state_path
        state_path.parent.mkdir(parents=True, exist_ok=True)
        from datetime import UTC, datetime

        payload = {
            "last_sent_date": report.isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "manual": True,
        }
        state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"状态已更新: {state_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
