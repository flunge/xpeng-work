from __future__ import annotations

from dataclasses import dataclass

from .enums import TaskStatus, TaskType


@dataclass(frozen=True)
class StatusTransition:
    from_status: TaskStatus
    to_status: TaskStatus
    reason: str


class TaskStateMachine:
    _valid_transitions: dict[TaskStatus, set[TaskStatus]] = {
        TaskStatus.CREATED: {TaskStatus.QUEUED, TaskStatus.BLOCKED, TaskStatus.CANCELLED},
        TaskStatus.QUEUED: {
            TaskStatus.PREPROCESSING,
            TaskStatus.TRAINING,
            TaskStatus.EVALUATING,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        },
        TaskStatus.PREPROCESSING: {
            TaskStatus.DATASET_READY,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        },
        TaskStatus.DATASET_READY: {TaskStatus.TRAINING, TaskStatus.CANCELLED},
        TaskStatus.TRAINING: {
            TaskStatus.EVALUATING,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        },
        TaskStatus.EVALUATING: {
            TaskStatus.REPORTING,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        },
        TaskStatus.REPORTING: {
            TaskStatus.DONE,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        },
        TaskStatus.BLOCKED: {TaskStatus.QUEUED, TaskStatus.CANCELLED},
        TaskStatus.DONE: set(),
        TaskStatus.FAILED: {TaskStatus.QUEUED},
        TaskStatus.CANCELLED: set(),
    }

    @classmethod
    def can_transition(cls, from_status: TaskStatus, to_status: TaskStatus) -> bool:
        return to_status in cls._valid_transitions.get(from_status, set())

    @classmethod
    def infer_initial_runtime_status(cls, task_type: TaskType) -> TaskStatus:
        if task_type == TaskType.PIPELINE_PREPROCESS:
            return TaskStatus.PREPROCESSING
        if task_type == TaskType.PIPELINE_TRAIN:
            return TaskStatus.TRAINING
        if task_type in {TaskType.LOGS_DOWNLOAD, TaskType.REPORT_GENERATE}:
            return TaskStatus.EVALUATING
        return TaskStatus.QUEUED
