from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.enums import TaskStatus, TaskType


class FeishuWebhookResponse(BaseModel):
    code: int = 0
    msg: str = "ok"
    challenge: str | None = None


class TaskRunResponse(BaseModel):
    task_id: str
    task_type: TaskType
    requester: str
    chat_id: str
    message_id: str
    status: TaskStatus
    current_stage: str
    summary: str
    doc_url: str | None = None


class TaskListResponse(BaseModel):
    items: list[TaskRunResponse]


class RetryTaskResponse(BaseModel):
    task_id: str
    status: TaskStatus
    current_stage: str
    summary: str


class SendMessageRequest(BaseModel):
    chat_id: str
    thread_id: str | None = None
    title: str
    body_lines: list[str] = Field(default_factory=list)
    doc_url: str | None = None
