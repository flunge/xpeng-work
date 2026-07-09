from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from textwrap import dedent

from app.domain.enums import TaskType
from app.domain.models import ExecutionResult, TaskRun
from app.infrastructure.feishu_config import (
    FeishuCliAuthAdapter,
    FeishuIntegrationError,
    FeishuPermissionError,
    FeishuSettings,
)


@dataclass(slots=True)
class MessageDispatchResult:
    chat_id: str
    thread_id: str | None
    message_id: str | None
    title: str
    body_lines: list[str]
    doc_url: str | None = None


class FeishuMessageClient:
    def send_task_update(self, task: TaskRun, result: ExecutionResult | None = None) -> MessageDispatchResult:
        payload = build_message_payload(task, result)
        return MessageDispatchResult(
            chat_id=payload["chat_id"],
            thread_id=payload["thread_id"],
            message_id=None,
            title=payload["title"],
            body_lines=payload["body_lines"],
            doc_url=payload["doc_url"],
        )

    def reply_text(self, message_id: str, chat_id: str, text: str, *, reply_in_thread: bool = True) -> MessageDispatchResult:
        return MessageDispatchResult(
            chat_id=chat_id,
            thread_id=None,
            message_id=None,
            title=text,
            body_lines=[],
            doc_url=None,
        )

    def send_text_to_chat(self, chat_id: str, text: str) -> MessageDispatchResult:
        return MessageDispatchResult(
            chat_id=chat_id,
            thread_id=None,
            message_id=None,
            title=text,
            body_lines=[],
            doc_url=None,
        )

    def send_text_to_user(self, user_id: str, text: str) -> MessageDispatchResult:
        return MessageDispatchResult(
            chat_id=user_id,
            thread_id=None,
            message_id=None,
            title=text,
            body_lines=[],
            doc_url=None,
        )

    def send_text_to_user_name(self, name: str, text: str) -> MessageDispatchResult:
        return MessageDispatchResult(
            chat_id=name,
            thread_id=None,
            message_id=None,
            title=text,
            body_lines=[],
            doc_url=None,
        )


class RealFeishuMessageClient(FeishuMessageClient):
    def __init__(self, settings: FeishuSettings, auth: FeishuCliAuthAdapter) -> None:
        self.settings = settings
        self.auth = auth

    def send_task_update(self, task: TaskRun, result: ExecutionResult | None = None) -> MessageDispatchResult:
        payload = build_message_payload(task, result)
        text = render_message_text(payload)
        response = self._dispatch_message(task.chat_id, task.message_id, text)
        data = response.get("data", response)
        return MessageDispatchResult(
            chat_id=task.chat_id,
            thread_id=payload["thread_id"],
            message_id=data.get("message_id") or data.get("message", {}).get("message_id"),
            title=payload["title"],
            body_lines=payload["body_lines"],
            doc_url=payload["doc_url"],
        )

    def reply_text(self, message_id: str, chat_id: str, text: str, *, reply_in_thread: bool = True) -> MessageDispatchResult:
        response = self._dispatch_message(chat_id, message_id, text, reply_in_thread=reply_in_thread)
        data = response.get("data", response)
        return MessageDispatchResult(
            chat_id=chat_id,
            thread_id=None,
            message_id=data.get("message_id") or data.get("message", {}).get("message_id"),
            title=text,
            body_lines=[],
            doc_url=None,
        )

    def send_text_to_chat(self, chat_id: str, text: str) -> MessageDispatchResult:
        response = self._send_chat_message(chat_id, text)
        data = response.get("data", response)
        return MessageDispatchResult(
            chat_id=chat_id,
            thread_id=None,
            message_id=data.get("message_id") or data.get("message", {}).get("message_id"),
            title=text,
            body_lines=[],
            doc_url=None,
        )

    def send_text_to_user(self, user_id: str, text: str) -> MessageDispatchResult:
        args = [
            "im",
            "+messages-send",
            "--as",
            self.settings.message_as,
            "--user-id",
            user_id,
            "--text",
            text,
        ]
        response = self.auth.run_json_args(args)
        data = response.get("data", response)
        return MessageDispatchResult(
            chat_id=user_id,
            thread_id=None,
            message_id=data.get("message_id") or data.get("message", {}).get("message_id"),
            title=text,
            body_lines=[],
            doc_url=None,
        )

    def send_text_to_user_name(self, name: str, text: str) -> MessageDispatchResult:
        user_id = self.auth.resolve_open_id_by_name(name)
        if not user_id:
            raise ValueError(f"无法唯一解析飞书用户：{name}，请配置 FEISHU_BOOTSTRAP_TARGET_OPEN_ID")
        return self.send_text_to_user(user_id, text)

    def _dispatch_message(
        self,
        chat_id: str,
        message_id: str | None,
        text: str,
        *,
        reply_in_thread: bool = True,
    ) -> dict:
        if self.settings.reply_in_thread and message_id:
            try:
                return self._reply_message(message_id, text, reply_in_thread=reply_in_thread)
            except FeishuIntegrationError:
                return self._send_chat_message(chat_id, text)
        return self._send_chat_message(chat_id, text)

    def _reply_message(self, message_id: str, text: str, *, reply_in_thread: bool) -> dict:
        args = [
            "im",
            "+messages-reply",
            "--as",
            self.settings.message_as,
            "--message-id",
            message_id,
            "--text",
            text,
        ]
        if reply_in_thread:
            args.append("--reply-in-thread")
        return self.auth.run_json_args(args)

    def _send_chat_message(self, chat_id: str, text: str) -> dict:
        args = [
            "im",
            "+messages-send",
            "--as",
            self.settings.message_as,
            "--chat-id",
            chat_id,
            "--text",
            text,
        ]
        return self.auth.run_json_args(args)


class FeishuDocClient:
    def upsert_task_doc(self, task: TaskRun, result: ExecutionResult | None = None) -> str:
        suffix = task.task_id.lower()
        return f"https://feishu.example.local/docs/{suffix}"


class RealFeishuDocClient(FeishuDocClient):
    def __init__(self, settings: FeishuSettings, auth: FeishuCliAuthAdapter) -> None:
        self.settings = settings
        self.auth = auth

    def upsert_task_doc(self, task: TaskRun, result: ExecutionResult | None = None) -> str:
        markdown = render_doc_markdown(task, result)
        doc_title = _doc_title_for_task(task)
        if task.doc_url:
            self._run_doc_command(
                "docs +update",
                [
                    "--doc",
                    task.doc_url,
                    "--mode",
                    "overwrite",
                    "--markdown",
                    markdown,
                ],
            )
            self._maybe_set_doc_public_permissions(task.doc_url)
            return task.doc_url

        args = [
            "--title",
            doc_title,
            "--markdown",
            markdown,
        ]
        if self.settings.doc_folder_token:
            args.extend(["--folder-token", self.settings.doc_folder_token])
        elif self.settings.doc_wiki_space:
            args.extend(["--wiki-space", self.settings.doc_wiki_space])
        response = self._run_doc_command("docs +create", args)
        data = response.get("data", response)
        url = data.get("doc_url") or data.get("url") or data.get("document", {}).get("url")
        token = data.get("doc_id") or data.get("document_id") or data.get("obj_token") or data.get("token")
        doc_url = url or _doc_url_from_token(token)
        self._maybe_set_doc_public_permissions(doc_url)
        return doc_url

    def _run_doc_command(self, command: str, args: list[str]) -> dict:
        primary_args = ["--as", self.settings.doc_as, *args]
        try:
            return self.auth.run_json(_build_cli_args(command, primary_args))
        except FeishuPermissionError:
            fallback_args = ["--as", self.settings.doc_fallback_as, *args]
            return self.auth.run_json(_build_cli_args(command, fallback_args))

    def _maybe_set_doc_public_permissions(self, doc_url: str) -> None:
        if not self.settings.doc_public_access_enabled or not doc_url:
            return
        payload: dict[str, object] = {
            "link_share_entity": self.settings.doc_link_share_entity,
            "comment_entity": self.settings.doc_comment_entity,
            "security_entity": self.settings.doc_security_entity,
            "share_entity": self.settings.doc_share_entity,
            "external_access": self.settings.doc_external_access,
            "invite_external": self.settings.doc_invite_external,
        }
        args = [
            "--as",
            self.settings.doc_public_permission_as,
            "--params",
            json.dumps({"token": _extract_doc_token(doc_url), "type": "docx"}, ensure_ascii=False),
            "--data",
            json.dumps(payload, ensure_ascii=False),
            "--yes",
        ]
        try:
            self.auth.run_json(_build_cli_args("drive permission.public patch", args))
        except FeishuPermissionError:
            fallback_candidates = [self.settings.doc_as, self.settings.doc_fallback_as]
            fallback_as = next(
                (identity for identity in fallback_candidates if identity != self.settings.doc_public_permission_as),
                None,
            )
            if not fallback_as:
                return
            fallback_args = [
                "--as",
                fallback_as,
                "--params",
                json.dumps({"token": _extract_doc_token(doc_url), "type": "docx"}, ensure_ascii=False),
                "--data",
                json.dumps(payload, ensure_ascii=False),
                "--yes",
            ]
            try:
                self.auth.run_json(_build_cli_args("drive permission.public patch", fallback_args))
            except FeishuPermissionError:
                return


class FeishuSheetClient:
    def upsert_task_row(self, task: TaskRun) -> dict:
        return {
            "task_id": task.task_id,
            "status": task.status.value,
            "summary": task.summary,
            "doc_url": task.doc_url,
        }


class RealFeishuSheetClient(FeishuSheetClient):
    def __init__(self, settings: FeishuSettings, auth: FeishuCliAuthAdapter) -> None:
        self.settings = settings
        self.auth = auth

    def upsert_task_row(self, task: TaskRun) -> dict:
        if not self.settings.progress_base_token or not self.settings.progress_table_id:
            return {
                "mode": "wiki_table_manual",
                "wiki_url": self.settings.progress_wiki_url,
                "table_id": self.settings.progress_table_id,
                "view_id": self.settings.progress_view_id,
                "task_id": task.task_id,
                "status": task.status.value,
                "summary": task.summary,
                "doc_url": task.doc_url,
                "note": "未配置 progress_base_token，暂无法自动写入 Wiki 对应 bitable。",
            }

        record = build_structured_progress_record(task, self.settings)
        response = self.auth.run_json(
            _build_cli_args(
                "base +record-upsert",
                [
                    "--as",
                    self.settings.progress_as,
                    "--base-token",
                    self.settings.progress_base_token,
                    "--table-id",
                    self.settings.progress_table_id,
                    "--json",
                    json.dumps(record, ensure_ascii=False),
                ],
            )
        )
        data = response.get("data", response)
        return {
            **data,
            "wiki_url": self.settings.progress_wiki_url,
            "table_id": self.settings.progress_table_id,
            "view_id": self.settings.progress_view_id,
            "record_payload": record,
        }


def build_message_payload(task: TaskRun, result: ExecutionResult | None = None) -> dict:
    wants_doc = bool(task.params.get("wants_doc"))
    doc_url = task.doc_url or (result.doc_url if result else None)

    if wants_doc and doc_url:
        title = "已生成飞书文档"
        body_lines = [f"文档: {doc_url}"]
    else:
        title = task.summary
        body_lines = [task.summary]

    return {
        "chat_id": task.chat_id,
        "thread_id": task.thread_id,
        "title": title,
        "body_lines": body_lines,
        "doc_url": doc_url,
    }


def render_message_text(payload: dict) -> str:
    if payload["body_lines"] == [payload["title"]]:
        return payload["title"]
    return "\n".join([payload["title"], *payload["body_lines"]])


def render_doc_markdown(task: TaskRun, result: ExecutionResult | None = None) -> str:
    if task.task_type == TaskType.CHAT_REPLY:
        return render_llm_doc_markdown(task, result)
    return render_legacy_task_doc_markdown(task, result)


def render_llm_doc_markdown(task: TaskRun, result: ExecutionResult | None = None) -> str:
    user_question = _extract_llm_user_question(task)
    answer = (result.summary if result else task.summary) or ""
    title = _doc_title_for_task(task)
    return dedent(
        f"""
        # {title}

        ## 问题

        {user_question}

        ## 回答

        {answer}
        """
    ).strip()


def render_legacy_task_doc_markdown(task: TaskRun, result: ExecutionResult | None = None) -> str:
    metrics = json.dumps(result.metrics, ensure_ascii=False, indent=2) if result and result.metrics else "{}"
    artifacts = "\n".join(
        f"- {artifact.artifact_type}: {artifact.uri}" for artifact in (result.artifacts if result else [])
    ) or "- 无"
    return dedent(
        f"""
        # 任务报告

        - 任务 ID: {task.task_id}
        - 任务类型: {task.task_type.value}
        - 请求人: {task.requester}
        - 状态: {task.status.value}
        - 阶段: {task.current_stage}

        ## 用户消息

        {task.raw_text}

        ## 摘要

        {task.summary}

        ## Agent 回复

        {result.summary if result else task.summary}

        ## 指标

        ```json
        {metrics}
        ```

        ## Artifacts

        {artifacts}
        """
    ).strip()


def _extract_llm_user_question(task: TaskRun) -> str:
    query = (task.params.get("query") or "").strip()
    if query:
        return query
    text = (task.raw_text or "").strip()
    if text.startswith("大模型"):
        text = text[len("大模型") :].lstrip(" ：:，,\t\n")
    return text or task.raw_text or ""


def _doc_title_for_task(task: TaskRun) -> str:
    question = _extract_llm_user_question(task)
    noise_prefixes = (
        "请输出报告，",
        "请生成报告，",
        "请写报告，",
        "请整理成文档，",
        "请整理为文档，",
        "输出报告，",
        "生成报告，",
        "写报告，",
        "整理成文档，",
        "整理为文档，",
        "请输出报告",
        "请生成报告",
        "请写报告",
        "输出报告",
        "生成报告",
        "写报告",
        "飞书文档",
        "请",
        "帮我",
        "帮忙",
    )
    for prefix in noise_prefixes:
        if question.startswith(prefix):
            question = question[len(prefix) :].lstrip("，,：: \t")
    title = question[:48].strip().rstrip("。，,;；:：.!?！？")
    if title:
        return title
    return f"大模型回复-{task.task_id}"


def render_progress_text(task: TaskRun) -> str:
    if task.task_type == TaskType.CHAT_REPLY:
        question = _extract_llm_user_question(task)
        short = question[:80] + ("..." if len(question) > 80 else "")
        return f"大模型对话 | {short} | 文档={task.doc_url or '-'}"
    return (
        f"[{task.task_id}] {task.task_type.value} | 状态={task.status.value} | 阶段={task.current_stage} | "
        f"请求人={task.requester} | 摘要={task.summary} | 文档={task.doc_url or '-'}"
    )


def build_structured_progress_record(task: TaskRun, settings: FeishuSettings) -> dict:
    return {
        settings.progress_text_field: render_progress_text(task),
        settings.progress_task_id_field: task.task_id,
        settings.progress_task_type_field: task.task_type.value,
        settings.progress_status_field: task.status.value,
        settings.progress_stage_field: task.current_stage,
        settings.progress_requester_field: task.requester,
        settings.progress_summary_field: task.summary,
        settings.progress_doc_url_field: task.doc_url or "",
    }


def _doc_url_from_token(token: str | None) -> str:
    if not token:
        return ""
    return f"https://xiaopeng.feishu.cn/docx/{token}"


def _extract_doc_token(doc_url: str) -> str:
    return doc_url.rstrip("/").split("/")[-1].split("?")[0]


def _build_cli_args(command: str, args: list[str]) -> str:
    return " ".join([command, *(shlex.quote(arg) for arg in args)])
