from __future__ import annotations

from dataclasses import dataclass
from datetime import time
import os
from pathlib import Path
import shlex

_AGENT_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = _AGENT_ROOT.parent


def _default_repo_root() -> str:
    return os.getenv("REPO_ROOT", str(_REPO_ROOT)).strip() or str(_REPO_ROOT)


def _default_daily_ai_hot_state_path() -> Path:
    return Path(os.getenv("FEISHU_DAILY_AI_HOT_STATE_PATH", str(_AGENT_ROOT / "data" / "daily_ai_hot_state.json")))


@dataclass(slots=True)
class FeishuSettings:
    mode: str = "mock"
    base_url: str = "https://open.feishu.cn"
    doc_folder_token: str | None = None
    doc_wiki_space: str | None = None
    doc_public_access_enabled: bool = True
    doc_public_permission_as: str = "bot"
    doc_external_access: bool = True
    doc_link_share_entity: str = "anyone_editable"
    doc_share_entity: str = "anyone"
    doc_comment_entity: str = "anyone_can_edit"
    doc_security_entity: str = "anyone_can_edit"
    doc_invite_external: bool = True
    progress_wiki_url: str | None = None
    progress_base_token: str | None = None
    progress_table_id: str | None = None
    progress_view_id: str | None = None
    progress_text_field: str = "文本"
    progress_task_id_field: str = "Task ID"
    progress_task_type_field: str = "任务类型"
    progress_status_field: str = "状态"
    progress_stage_field: str = "阶段"
    progress_requester_field: str = "请求人"
    progress_summary_field: str = "摘要"
    progress_doc_url_field: str = "文档链接"
    reply_in_thread: bool = True
    message_as: str = "bot"
    doc_as: str = "bot"
    doc_fallback_as: str = "user"
    progress_as: str = "user"
    enable_bootstrap_greeting: bool = False
    bootstrap_target_open_id: str | None = None
    bootstrap_target_chat_id: str | None = None
    bootstrap_target_name: str | None = None
    bootstrap_greeting: str = "等待你的命令"
    busy_reply_text: str = "思考中"
    openai_api_key: str | None = None
    openai_base_url: str = "https://socheap.ai/v1"
    openai_model: str = "gpt-5.4"
    openai_review_model: str = "gpt-5.4"
    openai_reasoning_effort: str = "xhigh"
    openai_disable_response_storage: bool = True
    openai_timeout_seconds: int = 180
    repo_agent_enabled: bool = True
    repo_agent_root: str = ""
    repo_agent_context_messages: int = 8
    repo_agent_max_files: int = 8
    repo_agent_max_file_chars: int = 6000
    cursor_agent_command: str | None = None
    daily_ai_hot_enabled: bool = False
    daily_ai_hot_target_chat_id: str | None = None
    daily_ai_hot_time: time = time(9, 30)
    daily_ai_hot_timezone: str = "Asia/Shanghai"
    daily_ai_hot_state_path: Path = Path()
    daily_ai_hot_run_on_startup_if_missed: bool = False

    @classmethod
    def from_env(cls) -> "FeishuSettings":
        return cls(
            mode=os.getenv("FEISHU_MODE", "mock").strip().lower() or "mock",
            base_url=os.getenv("FEISHU_BASE_URL", "https://open.feishu.cn").strip() or "https://open.feishu.cn",
            doc_folder_token=_clean(os.getenv("FEISHU_DOC_FOLDER_TOKEN")),
            doc_wiki_space=_clean(os.getenv("FEISHU_DOC_WIKI_SPACE")),
            doc_public_access_enabled=_as_bool(os.getenv("FEISHU_DOC_PUBLIC_ACCESS_ENABLED"), default=True),
            doc_public_permission_as=os.getenv("FEISHU_DOC_PUBLIC_PERMISSION_AS", "bot").strip().lower() or "bot",
            doc_external_access=_as_bool(os.getenv("FEISHU_DOC_EXTERNAL_ACCESS"), default=True),
            doc_link_share_entity=os.getenv("FEISHU_DOC_LINK_SHARE_ENTITY", "anyone_editable").strip()
            or "anyone_editable",
            doc_share_entity=os.getenv("FEISHU_DOC_SHARE_ENTITY", "anyone").strip() or "anyone",
            doc_comment_entity=os.getenv("FEISHU_DOC_COMMENT_ENTITY", "anyone_can_edit").strip() or "anyone_can_edit",
            doc_security_entity=os.getenv("FEISHU_DOC_SECURITY_ENTITY", "anyone_can_edit").strip() or "anyone_can_edit",
            doc_invite_external=_as_bool(os.getenv("FEISHU_DOC_INVITE_EXTERNAL"), default=True),
            progress_wiki_url=_clean(os.getenv("FEISHU_PROGRESS_WIKI_URL")),
            progress_base_token=_clean(os.getenv("FEISHU_PROGRESS_BASE_TOKEN")),
            progress_table_id=_clean(os.getenv("FEISHU_PROGRESS_TABLE_ID")),
            progress_view_id=_clean(os.getenv("FEISHU_PROGRESS_VIEW_ID")),
            progress_text_field=os.getenv("FEISHU_PROGRESS_TEXT_FIELD", "文本").strip() or "文本",
            progress_task_id_field=os.getenv("FEISHU_PROGRESS_TASK_ID_FIELD", "Task ID").strip() or "Task ID",
            progress_task_type_field=os.getenv("FEISHU_PROGRESS_TASK_TYPE_FIELD", "任务类型").strip() or "任务类型",
            progress_status_field=os.getenv("FEISHU_PROGRESS_STATUS_FIELD", "状态").strip() or "状态",
            progress_stage_field=os.getenv("FEISHU_PROGRESS_STAGE_FIELD", "阶段").strip() or "阶段",
            progress_requester_field=os.getenv("FEISHU_PROGRESS_REQUESTER_FIELD", "请求人").strip() or "请求人",
            progress_summary_field=os.getenv("FEISHU_PROGRESS_SUMMARY_FIELD", "摘要").strip() or "摘要",
            progress_doc_url_field=os.getenv("FEISHU_PROGRESS_DOC_URL_FIELD", "文档链接").strip() or "文档链接",
            reply_in_thread=_as_bool(os.getenv("FEISHU_REPLY_IN_THREAD"), default=True),
            message_as=os.getenv("FEISHU_MESSAGE_AS", "bot").strip().lower() or "bot",
            doc_as=os.getenv("FEISHU_DOC_AS", "bot").strip().lower() or "bot",
            doc_fallback_as=os.getenv("FEISHU_DOC_FALLBACK_AS", "user").strip().lower() or "user",
            progress_as=os.getenv("FEISHU_PROGRESS_AS", "user").strip().lower() or "user",
            enable_bootstrap_greeting=_as_bool(os.getenv("FEISHU_ENABLE_BOOTSTRAP_GREETING"), default=False),
            bootstrap_target_open_id=_clean(os.getenv("FEISHU_BOOTSTRAP_TARGET_OPEN_ID")),
            bootstrap_target_chat_id=_clean(os.getenv("FEISHU_BOOTSTRAP_TARGET_CHAT_ID")),
            bootstrap_target_name=_clean(os.getenv("FEISHU_BOOTSTRAP_TARGET_NAME")),
            bootstrap_greeting=os.getenv("FEISHU_BOOTSTRAP_GREETING", "等待你的命令").strip() or "等待你的命令",
            busy_reply_text=os.getenv("FEISHU_BUSY_REPLY_TEXT", "思考中").strip() or "思考中",
            openai_api_key=_clean(os.getenv("OPENAI_API_KEY")),
            openai_base_url=os.getenv("OPENAI_BASE_URL", "https://socheap.ai/v1").strip() or "https://socheap.ai/v1",
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5.4").strip() or "gpt-5.4",
            openai_review_model=os.getenv("OPENAI_REVIEW_MODEL", os.getenv("OPENAI_MODEL", "gpt-5.4")).strip() or "gpt-5.4",
            openai_reasoning_effort=os.getenv("OPENAI_REASONING_EFFORT", "medium").strip() or "medium",
            openai_disable_response_storage=_as_bool(os.getenv("OPENAI_DISABLE_RESPONSE_STORAGE"), default=True),
            openai_timeout_seconds=int(os.getenv("OPENAI_TIMEOUT_SECONDS", "180")),
            repo_agent_enabled=_as_bool(os.getenv("REPO_AGENT_ENABLED"), default=True),
            repo_agent_root=os.getenv("REPO_AGENT_ROOT", _default_repo_root()).strip() or _default_repo_root(),
            repo_agent_context_messages=int(os.getenv("REPO_AGENT_CONTEXT_MESSAGES", "8")),
            repo_agent_max_files=int(os.getenv("REPO_AGENT_MAX_FILES", "8")),
            repo_agent_max_file_chars=int(os.getenv("REPO_AGENT_MAX_FILE_CHARS", "6000")),
            cursor_agent_command=_clean(os.getenv("CURSOR_AGENT_COMMAND")),
            daily_ai_hot_enabled=_as_bool(os.getenv("FEISHU_DAILY_AI_HOT_ENABLED"), default=False),
            daily_ai_hot_target_chat_id=_clean(os.getenv("FEISHU_DAILY_AI_HOT_TARGET_CHAT_ID")),
            daily_ai_hot_time=_parse_time(os.getenv("FEISHU_DAILY_AI_HOT_TIME"), default=time(9, 30)),
            daily_ai_hot_timezone=os.getenv("FEISHU_DAILY_AI_HOT_TIMEZONE", "Asia/Shanghai").strip()
            or "Asia/Shanghai",
            daily_ai_hot_state_path=_default_daily_ai_hot_state_path(),
            daily_ai_hot_run_on_startup_if_missed=_as_bool(
                os.getenv("FEISHU_DAILY_AI_HOT_RUN_ON_STARTUP_IF_MISSED"), default=False
            ),
        )


class FeishuConfigurationError(RuntimeError):
    pass


class FeishuIntegrationError(RuntimeError):
    pass


class FeishuPermissionError(FeishuIntegrationError):
    pass


class FeishuCliAuthAdapter:
    def __init__(self, settings: FeishuSettings) -> None:
        self.settings = settings

    def validate_ready(self) -> None:
        if self.settings.mode not in {"mock", "cli"}:
            raise FeishuConfigurationError(f"Unsupported FEISHU_MODE: {self.settings.mode}")
        if self.settings.mode == "mock":
            return

        self._run_cli_plain(["auth", "status"])

    def run_json(self, args: str) -> dict:
        return self._run_cli(args)

    def run_json_args(self, args: list[str]) -> dict:
        return self._run_cli_args(args)

    def resolve_open_id_by_name(self, name: str) -> str | None:
        response = self.run_json_args(["contact", "+search-user", "--query", name, "--has-chatted", "--as", "user"])
        data = response.get("data", response)
        candidates = data.get("items") or data.get("users") or data.get("user_list") or []
        if isinstance(candidates, dict):
            candidates = candidates.get("items") or candidates.get("users") or []
        if len(candidates) != 1:
            return None
        candidate = candidates[0]
        return candidate.get("open_id") or candidate.get("user_id") or candidate.get("user", {}).get("open_id")

    def _run_cli(self, args: str) -> dict:
        return self._run_cli_args(shlex.split(args))

    def _run_cli_args(self, args: list[str]) -> dict:
        import json

        completed = self._run_cli_command(["lark-cli", *args])
        payload = (completed.stdout or "").strip()
        if not payload:
            return {}
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise FeishuIntegrationError(f"无法解析 lark-cli 输出: {payload}") from exc

    def _run_cli_plain(self, args: list[str]) -> str:
        completed = self._run_cli_command(["lark-cli", *args])
        return (completed.stdout or "").strip()

    def _run_cli_command(self, command: list[str]):
        import subprocess

        try:
            completed = subprocess.run(command, check=False, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise FeishuConfigurationError("未找到 lark-cli，请先安装并完成登录授权") from exc

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            if "permission" in detail.lower() or "scope" in detail.lower():
                raise FeishuPermissionError(detail)
            raise FeishuIntegrationError(detail or f"lark-cli exited with code {completed.returncode}")
        return completed


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _as_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_time(value: str | None, *, default: time) -> time:
    if not value:
        return default
    try:
        hour, minute = value.strip().split(":", 1)
        return time(int(hour), int(minute))
    except ValueError:
        return default
