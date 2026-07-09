from __future__ import annotations

from enum import Enum


class TaskType(str, Enum):
    PIPELINE_PREPROCESS = "pipeline.preprocess"
    PIPELINE_TRAIN = "pipeline.train"
    LOGS_DOWNLOAD = "logs.download"
    TASK_STATUS = "task.status"
    REPORT_GENERATE = "report.generate"
    CHAT_REPLY = "chat.reply"


class TaskStatus(str, Enum):
    CREATED = "created"
    QUEUED = "queued"
    PREPROCESSING = "preprocessing"
    DATASET_READY = "dataset_ready"
    TRAINING = "training"
    EVALUATING = "evaluating"
    REPORTING = "reporting"
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = {
    TaskStatus.DONE,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
}
