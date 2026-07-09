from __future__ import annotations

from typing import Any

from app.domain.enums import TaskStatus
from app.domain.models import ExecutionResult, TaskRun
from app.executors.base import BaseExecutor


class ChatReplyExecutor(BaseExecutor):
    task_type_name = "chat.reply"

    def __init__(self, agent_client: Any | None = None) -> None:
        self.agent_client = agent_client

    def execute(self, task: TaskRun) -> ExecutionResult:
        query = (task.params.get("query") or "").strip()
        if not query:
            summary = "请在「大模型」后写上你的问题，例如：大模型 今天天气怎么样？"
            metrics = {"mode": "empty_llm_query"}
        elif self.agent_client is None:
            summary = "大模型客户端未配置，请设置 OPENAI_API_KEY 后重启服务。"
            metrics = {"mode": "missing_agent_client"}
        else:
            result = self.agent_client.execute(query, conversation_id=task.chat_id)
            summary = result.summary
            metrics = result.metrics
        return ExecutionResult(
            status=TaskStatus.DONE,
            current_stage="reporting",
            summary=summary,
            metrics={"query": query, **metrics},
        )
