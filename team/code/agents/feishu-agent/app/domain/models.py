from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .enums import TaskStatus, TaskType


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class FeishuMessage:
    event_id: str
    message_id: str
    chat_id: str
    sender_id: str
    text: str
    raw_payload: dict[str, Any]
    thread_id: str | None = None


@dataclass(slots=True)
class TaskSpec:
    task_type: TaskType
    params: dict[str, Any]
    summary: str
    requester: str
    chat_id: str
    message_id: str
    thread_id: str | None
    raw_text: str
    idempotency_key: str


@dataclass(slots=True)
class TaskRun:
    task_id: str
    task_type: TaskType
    requester: str
    chat_id: str
    message_id: str
    thread_id: str | None
    raw_text: str
    params: dict[str, Any]
    status: TaskStatus = TaskStatus.CREATED
    current_stage: str = "created"
    summary: str = ""
    doc_url: str | None = None
    sync_message_id: str | None = None
    sync_record_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass(slots=True)
class TaskEvent:
    task_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class TaskArtifact:
    task_id: str
    artifact_type: str
    uri: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExecutionResult:
    status: TaskStatus
    current_stage: str
    summary: str
    doc_url: str | None = None
    artifacts: list[TaskArtifact] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    extra_events: list[TaskEvent] = field(default_factory=list)
