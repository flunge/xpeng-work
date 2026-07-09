from __future__ import annotations

from typing import Any

from app.domain.enums import TaskType
from app.executors.chat_reply import ChatReplyExecutor


class ExecutorRegistry:
    def __init__(self, agent_client: Any | None = None) -> None:
        self._executors = {
            TaskType.CHAT_REPLY: ChatReplyExecutor(agent_client=agent_client),
        }

    def get(self, task_type: TaskType):
        return self._executors.get(task_type)
