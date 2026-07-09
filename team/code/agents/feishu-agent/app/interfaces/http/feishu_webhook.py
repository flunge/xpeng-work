from __future__ import annotations

import json

from fastapi import APIRouter, Request

from app.domain.models import FeishuMessage
from app.domain.schemas import FeishuWebhookResponse

router = APIRouter(prefix="/webhook/feishu", tags=["feishu"])


@router.post("/events", response_model=FeishuWebhookResponse)
async def receive_feishu_events(request: Request) -> FeishuWebhookResponse:
    payload = await request.json()
    if "challenge" in payload:
        return FeishuWebhookResponse(challenge=payload["challenge"])

    feishu_message = _parse_compact_event(payload) or _parse_openapi_event(payload)
    if feishu_message is None:
        return FeishuWebhookResponse(msg="ignored unsupported event")

    app_container = request.app.state.application
    task = app_container.orchestrator.create_task_from_message(feishu_message)
    if task is None:
        return FeishuWebhookResponse(msg="ignored non-llm message")
    return FeishuWebhookResponse()


def _parse_openapi_event(payload: dict) -> FeishuMessage | None:
    header = payload.get("header", {})
    if header.get("event_type") != "im.message.receive_v1":
        return None

    event = payload.get("event", {})
    message = event.get("message", {})
    if message.get("message_type") != "text":
        return None

    content = message.get("content", "{}")
    try:
        content_json = json.loads(content)
    except json.JSONDecodeError:
        content_json = {"text": content}

    text = (content_json.get("text") or "").strip()
    if not text:
        return None

    mentions = event.get("mentions") or []
    should_process = _should_process_group_or_p2p(
        chat_type=message.get("chat_type"),
        text=text,
        mentions=mentions,
    )
    if not should_process:
        return None

    sender = event.get("sender", {})
    sender_id = sender.get("sender_id", {})
    return FeishuMessage(
        event_id=header.get("event_id", "unknown-event"),
        message_id=message.get("message_id", "unknown-message"),
        chat_id=message.get("chat_id", "unknown-chat"),
        sender_id=sender_id.get("open_id") or sender_id.get("user_id") or "unknown-sender",
        text=text,
        raw_payload=payload,
        thread_id=message.get("thread_id"),
    )


def _parse_compact_event(payload: dict) -> FeishuMessage | None:
    if payload.get("type") != "im.message.receive_v1":
        return None
    if payload.get("message_type") != "text":
        return None

    text = (payload.get("content") or "").strip()
    if not text:
        return None

    chat_type = payload.get("chat_type")
    should_process = _should_process_group_or_p2p(chat_type=chat_type, text=text, mentions=[])
    if not should_process:
        return None

    return FeishuMessage(
        event_id=payload.get("event_id", "unknown-event"),
        message_id=payload.get("message_id") or payload.get("id") or "unknown-message",
        chat_id=payload.get("chat_id", "unknown-chat"),
        sender_id=payload.get("sender_id", "unknown-sender"),
        text=text,
        raw_payload=payload,
        thread_id=payload.get("thread_id"),
    )


def _should_process_group_or_p2p(
    *,
    chat_type: str | None,
    text: str,
    mentions: list[dict],
) -> bool:
    if chat_type == "p2p":
        return True
    if chat_type != "group":
        return False
    if mentions:
        return True
    # lark-cli compact 事件会把 @ 渲染进正文；群聊需 @ 机器人才处理
    if "@" in text:
        return True
    return any(token in text for token in ("@Agent", "@agent"))
