from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.infrastructure.feishu_clients import FeishuMessageClient
from app.infrastructure.feishu_config import FeishuSettings

logger = logging.getLogger(__name__)

AIHOT_BASE_URL = "https://aihot.virxact.com"
AIHOT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
@dataclass(slots=True)
class DailyAiHotScheduler:
    settings: FeishuSettings
    message_client: FeishuMessageClient
    _task: asyncio.Task | None = None
    _stop_event: asyncio.Event | None = None

    def start(self) -> None:
        if not self.settings.daily_ai_hot_enabled:
            logger.info("daily AI hot scheduler disabled")
            return
        if not self.settings.daily_ai_hot_target_chat_id:
            logger.warning("daily AI hot scheduler enabled without target chat id")
            return
        if self._task and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop(), name="daily-ai-hot-scheduler")

    async def stop(self) -> None:
        if self._stop_event:
            self._stop_event.set()
        if self._task:
            await self._task
        self._task = None
        self._stop_event = None

    async def _run_loop(self) -> None:
        assert self._stop_event is not None
        await self._maybe_run_startup_catchup()
        while not self._stop_event.is_set():
            next_run = self._next_run_at(datetime.now(self._timezone()))
            wait_seconds = max(1.0, (next_run - datetime.now(self._timezone())).total_seconds())
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=wait_seconds)
            except TimeoutError:
                await self._run_once_for_date(self._report_date_for(next_run))
            except Exception:
                logger.exception("daily AI hot scheduler loop failed")

    async def _maybe_run_startup_catchup(self) -> None:
        if not self.settings.daily_ai_hot_run_on_startup_if_missed:
            return
        now = datetime.now(self._timezone())
        scheduled_today = datetime.combine(
            now.date(), self.settings.daily_ai_hot_time, tzinfo=self._timezone()
        )
        if now < scheduled_today:
            return
        if self._last_sent_date() == self._report_date_for(scheduled_today):
            return
        await self._run_once_for_date(self._report_date_for(scheduled_today))

    async def _run_once_for_date(self, report_date: date) -> None:
        if self._last_sent_date() == report_date:
            logger.info("daily AI hot already sent for %s", report_date.isoformat())
            return
        try:
            message = await asyncio.to_thread(fetch_and_render_daily_ai_hot, report_date, self._timezone())
            result = await asyncio.to_thread(
                self.message_client.send_text_to_chat,
                self.settings.daily_ai_hot_target_chat_id,
                message,
            )
            self._write_last_sent_date(report_date)
            logger.info(
                "daily AI hot sent for %s to %s, message_id=%s",
                report_date.isoformat(),
                self.settings.daily_ai_hot_target_chat_id,
                result.message_id,
            )
        except Exception:
            logger.exception("failed to send daily AI hot for %s", report_date.isoformat())

    def _next_run_at(self, now: datetime) -> datetime:
        candidate = datetime.combine(now.date(), self.settings.daily_ai_hot_time, tzinfo=self._timezone())
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    def _report_date_for(self, run_at: datetime) -> date:
        return (run_at - timedelta(days=1)).date()

    def _timezone(self) -> ZoneInfo:
        return ZoneInfo(self.settings.daily_ai_hot_timezone)

    def _last_sent_date(self) -> date | None:
        path = self.settings.daily_ai_hot_state_path
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            raw_date = payload.get("last_sent_date")
            return date.fromisoformat(raw_date) if raw_date else None
        except Exception:
            logger.warning("failed to read daily AI hot state file: %s", path, exc_info=True)
            return None

    def _write_last_sent_date(self, sent_date: date) -> None:
        path = self.settings.daily_ai_hot_state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_sent_date": sent_date.isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_and_render_daily_ai_hot(report_date: date, timezone: ZoneInfo) -> str:
    window_start = datetime.combine(report_date, time.min, tzinfo=timezone)
    window_end = window_start + timedelta(days=1)
    items = fetch_aihot_selected_items(window_start.astimezone(UTC), window_end.astimezone(UTC))
    return render_daily_ai_hot_message(report_date, timezone, items)


def fetch_aihot_selected_items(window_start_utc: datetime, window_end_utc: datetime) -> list[dict]:
    params = urllib.parse.urlencode(
        {
            "mode": "selected",
            "since": _format_utc(window_start_utc),
            "take": "100",
        }
    )
    request = urllib.request.Request(
        f"{AIHOT_BASE_URL}/api/public/items?{params}",
        headers={"User-Agent": AIHOT_USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    items = payload.get("items") or []
    return [item for item in items if _is_in_window(item, window_start_utc, window_end_utc)]


def render_daily_ai_hot_message(report_date: date, timezone: ZoneInfo, items: list[dict]) -> str:
    date_text = report_date.strftime("%Y-%m-%d")
    lines = [
        f"昨日 AI 圈精选动态（{date_text}）",
        "",
        f"数据源：AI HOT 精选；统计口径：{date_text} 00:00～24:00（{timezone.key}）",
        "",
    ]
    if not items:
        lines.append("昨日未抓取到 AI HOT 精选动态。")
        return "\n".join(lines)

    for index, item in enumerate(items[:20], start=1):
        title = _clean_text(item.get("title") or item.get("title_en") or "未命名动态")
        summary = _clean_text(item.get("summary") or "")
        url = item.get("url") or ""
        category = _category_label(item.get("category"))
        source = _clean_text(item.get("source") or "")
        lines.append(f"{index}. {title}")
        if summary:
            lines.append(_truncate(summary, 180))
        meta_parts = [part for part in (category, source) if part]
        if meta_parts:
            lines.append(f"分类/来源：{' / '.join(meta_parts)}")
        if url:
            lines.append(f"链接：{url}")
        lines.append("")

    lines.extend(
        [
            "简评：",
            _build_commentary(items),
        ]
    )
    return "\n".join(lines).strip()


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_in_window(item: dict, window_start_utc: datetime, window_end_utc: datetime) -> bool:
    published_at = item.get("publishedAt")
    if not published_at:
        return False
    parsed = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    return window_start_utc <= parsed < window_end_utc


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _category_label(category: str | None) -> str:
    labels = {
        "ai-models": "模型发布/更新",
        "ai-products": "产品发布/更新",
        "industry": "行业动态",
        "paper": "论文研究",
        "tip": "技巧与观点",
    }
    return labels.get(category or "", category or "")


def _build_commentary(items: list[dict]) -> str:
    categories = {item.get("category") for item in items}
    highlights = []
    if "ai-products" in categories:
        highlights.append("AI 产品与创作工具仍在快速降低使用门槛")
    if "ai-models" in categories:
        highlights.append("模型能力与多模型生态持续更新")
    if "tip" in categories:
        highlights.append("Agent 工作流、工具配置和实践技巧值得跟进")
    if "paper" in categories:
        highlights.append("研究与安全能力继续外溢到真实生产场景")
    if "industry" in categories:
        highlights.append("行业落地信号正在增多")
    if not highlights:
        return "昨日动态较分散，建议优先关注与自身工作流直接相关的工具和方法。"
    return "；".join(highlights) + "。"
