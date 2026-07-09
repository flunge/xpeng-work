from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.models import ExecutionResult, TaskRun


class BaseExecutor(ABC):
    task_type_name: str

    @abstractmethod
    def execute(self, task: TaskRun) -> ExecutionResult:
        raise NotImplementedError
