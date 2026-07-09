from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from app.infrastructure.feishu_config import FeishuSettings


@dataclass(slots=True)
class AgentCommandResult:
    summary: str
    metrics: dict[str, Any]


class LocalAgentClient:
    """通用大模型客户端：仅转发用户问题，不注入本地仓库或业务上下文。"""

    def __init__(self, settings: FeishuSettings) -> None:
        self.settings = settings
        self._history: dict[str, deque[dict[str, str]]] = defaultdict(
            lambda: deque(maxlen=max(settings.repo_agent_context_messages, 2))
        )

    def execute(self, query: str, *, conversation_id: str = "default") -> AgentCommandResult:
        prompt = self._build_input(query, conversation_id)
        result = self.execute_prompt(prompt, original_query=query)
        if result.metrics.get("mode") == "generic_llm":
            self._append_history(conversation_id, "user", query)
            self._append_history(conversation_id, "assistant", result.summary)
        return result

    def execute_prompt(
        self,
        prompt: str,
        *,
        original_query: str | None = None,
        timeout_seconds: int | None = None,
    ) -> AgentCommandResult:
        query = original_query or prompt
        if not self.settings.openai_api_key:
            return AgentCommandResult(
                summary="大模型尚未配置 OPENAI_API_KEY，请配置后重启服务。",
                metrics={"mode": "missing_openai_api_key", "query": query},
            )

        payload = {
            "model": self.settings.openai_model,
            "input": prompt,
            "reasoning": {"effort": self.settings.openai_reasoning_effort},
            "store": not self.settings.openai_disable_response_storage,
        }
        try:
            response = self._post_responses(payload, timeout_seconds=timeout_seconds)
        except Exception as exc:
            return AgentCommandResult(
                summary=f"大模型调用失败：{exc}",
                metrics={"mode": "llm_error", "query": query, "error": str(exc)},
            )
        summary = self._extract_text(response).strip()
        if not summary:
            summary = "模型已返回，但未解析到可读文本。"
        return AgentCommandResult(
            summary=summary,
            metrics={
                "mode": "generic_llm",
                "query": query,
                "model": self.settings.openai_model,
                "base_url": self.settings.openai_base_url,
            },
        )

    def _build_input(self, query: str, conversation_id: str) -> str:
        history_text = self._render_history(conversation_id)
        if not history_text:
            return query
        return f"{history_text}\n\n用户：{query}"

    def _render_history(self, conversation_id: str) -> str:
        items = self._history.get(conversation_id)
        if not items:
            return ""
        lines = [f"{item['role']}：{item['content']}" for item in items]
        return "历史对话：\n" + "\n".join(lines)

    def _append_history(self, conversation_id: str, role: str, content: str) -> None:
        self._history[conversation_id].append({"role": role, "content": content[:4000]})

    def _post_responses(self, payload: dict[str, Any], *, timeout_seconds: int | None = None) -> dict[str, Any]:
        url = self._responses_url()
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self.settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            timeout = timeout_seconds or self.settings.openai_timeout_seconds
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI Responses API 请求失败: HTTP {exc.code}: {body}") from exc

    def _responses_url(self) -> str:
        base_url = self.settings.openai_base_url.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url += "/v1"
        return base_url + "/responses"

    def _extract_text(self, response: dict[str, Any]) -> str:
        if isinstance(response.get("output_text"), str):
            return response["output_text"]

        chunks: list[str] = []
        for item in response.get("output", []) or []:
            for content in item.get("content", []) or []:
                text = content.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return "\n".join(chunks)
