from __future__ import annotations

import os
import shlex
import subprocess
from collections import defaultdict, deque
from pathlib import Path
from string import Template
from typing import Any

from app.infrastructure.feishu_config import FeishuSettings
from app.infrastructure.local_agent_client import AgentCommandResult, LocalAgentClient
from app.infrastructure.repository_context import RepositoryContextProvider


class RepositoryAgentClient:
    def __init__(self, settings: FeishuSettings, fallback_client: LocalAgentClient) -> None:
        self.settings = settings
        self.fallback_client = fallback_client
        self.context_provider = RepositoryContextProvider(
            settings.repo_agent_root,
            max_files=settings.repo_agent_max_files,
            max_file_chars=settings.repo_agent_max_file_chars,
        )
        self._history: dict[str, deque[dict[str, str]]] = defaultdict(
            lambda: deque(maxlen=max(settings.repo_agent_context_messages, 2))
        )

    def execute(self, query: str, *, conversation_id: str = "default") -> AgentCommandResult:
        if not self.settings.repo_agent_enabled:
            return self.fallback_client.execute(query)

        if self.settings.cursor_agent_command:
            result = self._try_external_cursor_agent(query, conversation_id=conversation_id)
            if result is not None:
                return result

        context, files = self.context_provider.collect(query)
        history_text = self._render_history(conversation_id)
        prompt = self._build_repo_prompt(query, history_text, context)
        result = self.fallback_client.execute_prompt(prompt, timeout_seconds=self._timeout_for_query(query))
        metrics = {
            **result.metrics,
            "mode": "repo_agent_socheap",
            "repo_root": self.settings.repo_agent_root,
            "context_files": files,
            "conversation_id": conversation_id,
        }
        self._append_history(conversation_id, "user", query)
        self._append_history(conversation_id, "assistant", result.summary)
        return AgentCommandResult(summary=result.summary, metrics=metrics)

    def _try_external_cursor_agent(self, query: str, *, conversation_id: str) -> AgentCommandResult | None:
        command_template = self.settings.cursor_agent_command
        if not command_template:
            return None

        repo_root = str(Path(self.settings.repo_agent_root).resolve())
        prompt = self._build_external_agent_prompt(query, conversation_id)
        command = Template(command_template).safe_substitute(repo_root=repo_root, prompt=shlex.quote(prompt))
        env = {
            **os.environ,
            "OPENAI_API_KEY": self.settings.openai_api_key or "",
            "OPENAI_BASE_URL": self.settings.openai_base_url,
            "OPENAI_MODEL": self.settings.openai_model,
        }
        try:
            completed = subprocess.run(
                command,
                shell=True,
                check=False,
                capture_output=True,
                text=True,
                cwd=repo_root,
                env=env,
                timeout=self.settings.openai_timeout_seconds,
            )
        except Exception:
            return None
        if completed.returncode != 0:
            return None
        summary = (completed.stdout or completed.stderr).strip()
        if not summary:
            return None
        self._append_history(conversation_id, "user", query)
        self._append_history(conversation_id, "assistant", summary)
        return AgentCommandResult(
            summary=summary,
            metrics={
                "mode": "cursor_cli_agent",
                "repo_root": repo_root,
                "conversation_id": conversation_id,
            },
        )

    def _timeout_for_query(self, query: str) -> int:
        if any(keyword in query.lower() for keyword in ("总结", "介绍", "概览", "overview", "summary")):
            return max(self.settings.openai_timeout_seconds, 180)
        return self.settings.openai_timeout_seconds

    def _build_repo_prompt(self, query: str, history_text: str, context: str) -> str:
        return (
            "你是运行在本地 3DGS 仓库中的 Cursor/CLI 风格仓库 Agent。"
            "你必须基于提供的仓库上下文和会话历史回答飞书用户问题。"
            "上下文中如果包含 .cursor/skills/*/SKILL.md，这些 Skill 是本仓库对你的强约束，"
            "涉及对应场景时必须优先遵守；尤其是 3dgs-feishu-rd-agent、3dgs-preprocess-task、"
            "3dgs-preprocess-rd-loop。"
            "大模型接口使用 SoCheap OpenAI Responses API，但仓库上下文由本地 agent 注入。"
            "如果上下文不足，请明确说明还需要查看哪些文件或执行哪些命令，不要编造仓库事实。"
            "如果用户是在要求提交/执行预处理、训练、下载日志等真实任务，不要回答‘不能执行’，"
            "而是提示用户使用明确命令格式；飞书外层编排器会负责真实执行这些任务。"
            "请用简体中文，直接给出结论；涉及文件时列出相对路径。\n\n"
            f"仓库根目录：{self.settings.repo_agent_root}\n\n"
            f"会话历史：\n{history_text or '无'}\n\n"
            f"本轮检索到的仓库上下文：\n{context}\n\n"
            f"用户问题：{query}"
        )

    def _build_external_agent_prompt(self, query: str, conversation_id: str) -> str:
        history_text = self._render_history(conversation_id)
        return (
            "你在 3DGS 仓库根目录下运行，请保留并利用仓库上下文回答飞书用户。"
            "运行前必须读取并遵守仓库内相关 .cursor/skills/*/SKILL.md，"
            "特别是 3dgs-feishu-rd-agent、3dgs-preprocess-task、3dgs-preprocess-rd-loop。"
            "模型接口配置为 OPENAI_BASE_URL/OPENAI_API_KEY/OPENAI_MODEL 指向 SoCheap。\n\n"
            f"会话历史：\n{history_text or '无'}\n\n"
            f"用户问题：{query}"
        )

    def _render_history(self, conversation_id: str) -> str:
        items = self._history.get(conversation_id)
        if not items:
            return ""
        return "\n".join(f"{item['role']}: {item['content']}" for item in items)

    def _append_history(self, conversation_id: str, role: str, content: str) -> None:
        self._history[conversation_id].append({"role": role, "content": content[:4000]})
