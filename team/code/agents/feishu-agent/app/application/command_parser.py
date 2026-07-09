from __future__ import annotations

import re
from app.domain.enums import TaskType
from app.domain.models import FeishuMessage, TaskSpec
from app.application.sync_service import SyncService


class CommandParser:
    """仅处理以「大模型」开头的飞书文本；其余消息忽略。"""

    def parse(self, message: FeishuMessage) -> TaskSpec | None:
        text = self._normalize(message.text)
        query = self._extract_llm_query(text)
        if query is None:
            return None
        if not query:
            return TaskSpec(
                task_type=TaskType.CHAT_REPLY,
                params={"query": "", "wants_doc": False},
                summary="大模型消息为空",
                requester=message.sender_id,
                chat_id=message.chat_id,
                message_id=message.message_id,
                thread_id=message.thread_id,
                raw_text=message.text,
                idempotency_key=f"feishu:{message.message_id}:chat.reply",
            )

        return TaskSpec(
            task_type=TaskType.CHAT_REPLY,
            params={"query": query, "wants_doc": SyncService.wants_doc_output(text)},
            summary=f"大模型对话：{query[:80]}",
            requester=message.sender_id,
            chat_id=message.chat_id,
            message_id=message.message_id,
            thread_id=message.thread_id,
            raw_text=message.text,
            idempotency_key=f"feishu:{message.message_id}:chat.reply",
        )

    def _normalize(self, text: str) -> str:
        normalized = re.sub(r"^@[^\s]+\s*", "", text.strip())
        return normalized.replace("@Agent", "").replace("@agent", "").strip()

    def _extract_llm_query(self, text: str) -> str | None:
        if not text.startswith("大模型"):
            return None
        return text[len("大模型") :].lstrip(" ：:，,\t\n")
