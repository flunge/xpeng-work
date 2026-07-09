from __future__ import annotations

import asyncio
from collections import deque
from itertools import count
import logging

from app.domain.enums import TERMINAL_STATUSES, TaskStatus, TaskType
from app.domain.models import ExecutionResult, FeishuMessage, TaskEvent, TaskRun, utc_now
from app.domain.state_machine import TaskStateMachine
from app.executors.registry import ExecutorRegistry
from app.infrastructure.sqlite_repo import SQLiteTaskRepository
from .command_parser import CommandParser
from .sync_service import SyncService

logger = logging.getLogger(__name__)


class TaskOrchestrator:
    def __init__(
        self,
        repository: SQLiteTaskRepository,
        parser: CommandParser,
        executors: ExecutorRegistry,
        sync_service: SyncService,
    ) -> None:
        self.repository = repository
        self.parser = parser
        self.executors = executors
        self.sync_service = sync_service
        self._counter = count(start=self._load_initial_counter())
        self._message_task_map = self._load_message_task_map()
        self._pending_task_ids: deque[str] = deque()
        self._queued_task_ids: set[str] = set()
        self._busy_replied_message_ids: set[str] = set()
        self._running_task_id: str | None = None
        self._queue_event: asyncio.Event | None = None
        self._worker_task: asyncio.Task[None] | None = None
        self._stop_worker = False

    def _load_message_task_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for task in self.repository.list_tasks():
            if task.message_id:
                mapping[task.message_id] = task.task_id
        return mapping

    def _load_initial_counter(self) -> int:
        tasks = self.repository.list_tasks()
        if not tasks:
            return 1
        numeric_ids = []
        for task in tasks:
            if task.task_id.startswith("TASK-"):
                try:
                    numeric_ids.append(int(task.task_id.split("-", 1)[1]))
                except ValueError:
                    continue
        return (max(numeric_ids) + 1) if numeric_ids else 1

    def start_worker(self) -> None:
        if self._worker_task and not self._worker_task.done():
            return
        self._stop_worker = False
        self._queue_event = asyncio.Event()
        self._worker_task = asyncio.create_task(self._worker_loop(), name="feishu-agent-task-worker")

    async def stop_worker(self) -> None:
        self._stop_worker = True
        if self._queue_event:
            self._queue_event.set()
        if self._worker_task:
            await self._worker_task
            self._worker_task = None

    def create_task_from_message(self, message: FeishuMessage) -> TaskRun | None:
        existing_task_id = self._message_task_map.get(message.message_id)
        if existing_task_id:
            task = self.require_task(existing_task_id)
            self._enqueue_task(task.task_id)
            return task

        spec = self.parser.parse(message)
        if spec is None:
            return None

        task = TaskRun(
            task_id=f"TASK-{next(self._counter):06d}",
            task_type=spec.task_type,
            requester=spec.requester,
            chat_id=spec.chat_id,
            message_id=spec.message_id,
            thread_id=spec.thread_id,
            raw_text=spec.raw_text,
            params=spec.params,
            status=TaskStatus.CREATED,
            current_stage="created",
            summary=spec.summary,
        )
        self.repository.create_task(task)
        self._message_task_map[message.message_id] = task.task_id
        self.repository.add_event(TaskEvent(task.task_id, "task.created", {"summary": spec.summary, "params": spec.params}))
        self._reply_busy_once(task)
        self._enqueue_task(task.task_id)
        return task

    @property
    def is_busy(self) -> bool:
        return self._running_task_id is not None or bool(self._pending_task_ids)

    @property
    def running_task_id(self) -> str | None:
        return self._running_task_id

    def queue_size(self) -> int:
        return len(self._pending_task_ids)

    def _enqueue_task(self, task_id: str) -> None:
        task = self.repository.get_task(task_id)
        if task is None or task.status in TERMINAL_STATUSES:
            return
        if self._running_task_id == task_id or task_id in self._queued_task_ids:
            return
        self._pending_task_ids.append(task_id)
        self._queued_task_ids.add(task_id)
        if self._queue_event:
            self._queue_event.set()

    def _reply_busy_once(self, task: TaskRun) -> None:
        if task.message_id in self._busy_replied_message_ids:
            return
        self._busy_replied_message_ids.add(task.message_id)
        try:
            self.sync_service.reply_busy(task)
            self.repository.add_event(TaskEvent(task.task_id, "task.busy_replied", {"message_id": task.message_id}))
        except Exception as exc:
            self.repository.add_event(TaskEvent(task.task_id, "task.busy_reply_failed", {"error": str(exc)}))
            logger.exception("Failed to send busy reply for %s", task.task_id)

    async def _worker_loop(self) -> None:
        assert self._queue_event is not None
        while not self._stop_worker:
            if not self._pending_task_ids:
                self._queue_event.clear()
                await self._queue_event.wait()
                continue
            task_id = self._pending_task_ids.popleft()
            self._queued_task_ids.discard(task_id)
            self._running_task_id = task_id
            try:
                await asyncio.to_thread(self.run_task, task_id)
            except Exception as exc:
                logger.exception("Task worker failed while running %s", task_id)
                self._mark_task_failed(task_id, exc)
            finally:
                self._running_task_id = None

    def _mark_task_failed(self, task_id: str, exc: Exception) -> None:
        task = self.repository.get_task(task_id)
        if task is None:
            return
        task.status = TaskStatus.FAILED
        task.current_stage = "failed"
        task.summary = f"任务执行失败：{exc}"
        task.finished_at = utc_now()
        self.repository.update_task(task)
        self.repository.add_event(TaskEvent(task.task_id, "task.failed", {"error": str(exc)}))
        try:
            self.sync_service.sync(task)
        except Exception:
            logger.exception("Failed to sync failed task %s", task_id)

    def run_task(self, task_id: str) -> TaskRun:
        task = self.require_task(task_id)
        task.status = TaskStatus.QUEUED
        task.current_stage = "queued"
        task.started_at = utc_now()
        self.repository.update_task(task)
        self.repository.add_event(TaskEvent(task.task_id, "task.queued", {"task_type": task.task_type.value}))

        executor = self.executors.get(task.task_type)
        if executor is None:
            task.status = TaskStatus.BLOCKED
            task.current_stage = "blocked"
            task.summary = f"任务类型 `{task.task_type.value}` 当前没有注册 executor"
            self.repository.update_task(task)
            self.repository.add_event(TaskEvent(task.task_id, "task.blocked", {"reason": "missing_executor"}))
            self.sync_service.sync(task)
            self.repository.update_task(task)
            return task

        runtime_status = TaskStateMachine.infer_initial_runtime_status(task.task_type)
        if TaskStateMachine.can_transition(task.status, runtime_status):
            task.status = runtime_status
            task.current_stage = runtime_status.value
            self.repository.update_task(task)
            self.repository.add_event(TaskEvent(task.task_id, "task.started", {"stage": runtime_status.value}))

        result = executor.execute(task)
        task.status = result.status
        task.current_stage = result.current_stage
        task.summary = result.summary
        task.doc_url = result.doc_url or task.doc_url
        task.finished_at = utc_now()
        self.repository.update_task(task)
        self.repository.add_event(TaskEvent(task.task_id, "task.finished", {"summary": result.summary, "metrics": result.metrics}))
        if result.extra_events:
            for event in result.extra_events:
                self.repository.add_event(event)
        if result.artifacts:
            self.repository.add_artifacts(task.task_id, result.artifacts)
        self.sync_service.sync(task, result)
        self.repository.update_task(task)
        return task

    def retry_task(self, task_id: str) -> TaskRun:
        task = self.require_task(task_id)
        task.status = TaskStatus.QUEUED
        task.current_stage = "queued"
        task.finished_at = None
        self.repository.update_task(task)
        self.repository.add_event(TaskEvent(task.task_id, "task.retry", {}))
        self._enqueue_task(task_id)
        return task

    def cancel_task(self, task_id: str) -> TaskRun:
        task = self.require_task(task_id)
        task.status = TaskStatus.CANCELLED
        task.current_stage = "cancelled"
        task.finished_at = utc_now()
        task.summary = task.summary or "任务已取消"
        self.repository.update_task(task)
        self.repository.add_event(TaskEvent(task.task_id, "task.cancelled", {}))
        self.sync_service.sync(task)
        self.repository.update_task(task)
        return task

    def require_task(self, task_id: str) -> TaskRun:
        task = self.repository.get_task(task_id)
        if task is None:
            raise KeyError(f"Task {task_id} not found")
        return task

    def list_tasks(self) -> list[TaskRun]:
        return self.repository.list_tasks()
