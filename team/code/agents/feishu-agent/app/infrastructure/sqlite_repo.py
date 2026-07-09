from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from app.domain.enums import TaskStatus, TaskType
from app.domain.models import TaskArtifact, TaskEvent, TaskRun, utc_now


class SQLiteTaskRepository:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS task_runs (
                    task_id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    requester TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    thread_id TEXT,
                    raw_text TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_stage TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    doc_url TEXT,
                    sync_message_id TEXT,
                    sync_record_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                );

                CREATE TABLE IF NOT EXISTS task_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS task_artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    uri TEXT NOT NULL,
                    meta_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(task_runs)").fetchall()}
            if "sync_message_id" not in columns:
                conn.execute("ALTER TABLE task_runs ADD COLUMN sync_message_id TEXT")
            if "sync_record_id" not in columns:
                conn.execute("ALTER TABLE task_runs ADD COLUMN sync_record_id TEXT")

    def create_task(self, task: TaskRun) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO task_runs (
                    task_id, task_type, requester, chat_id, message_id, thread_id, raw_text,
                    params_json, status, current_stage, summary, doc_url, sync_message_id,
                    sync_record_id, created_at, updated_at, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    task.task_type.value,
                    task.requester,
                    task.chat_id,
                    task.message_id,
                    task.thread_id,
                    task.raw_text,
                    json.dumps(task.params, ensure_ascii=False),
                    task.status.value,
                    task.current_stage,
                    task.summary,
                    task.doc_url,
                    task.sync_message_id,
                    task.sync_record_id,
                    task.created_at.isoformat(),
                    task.updated_at.isoformat(),
                    task.started_at.isoformat() if task.started_at else None,
                    task.finished_at.isoformat() if task.finished_at else None,
                ),
            )

    def update_task(self, task: TaskRun) -> None:
        task.updated_at = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE task_runs
                SET status = ?, current_stage = ?, summary = ?, doc_url = ?,
                    sync_message_id = ?, sync_record_id = ?,
                    updated_at = ?, started_at = ?, finished_at = ?, params_json = ?
                WHERE task_id = ?
                """,
                (
                    task.status.value,
                    task.current_stage,
                    task.summary,
                    task.doc_url,
                    task.sync_message_id,
                    task.sync_record_id,
                    task.updated_at.isoformat(),
                    task.started_at.isoformat() if task.started_at else None,
                    task.finished_at.isoformat() if task.finished_at else None,
                    json.dumps(task.params, ensure_ascii=False),
                    task.task_id,
                ),
            )

    def get_task(self, task_id: str) -> TaskRun | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM task_runs WHERE task_id = ?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def list_tasks(self) -> list[TaskRun]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM task_runs ORDER BY created_at DESC").fetchall()
        return [self._row_to_task(row) for row in rows]

    def add_event(self, event: TaskEvent) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO task_events (task_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (event.task_id, event.event_type, json.dumps(event.payload, ensure_ascii=False), event.created_at.isoformat()),
            )

    def list_events(self, task_id: str) -> list[TaskEvent]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT task_id, event_type, payload_json, created_at FROM task_events WHERE task_id = ? ORDER BY id ASC",
                (task_id,),
            ).fetchall()
        return [
            TaskEvent(
                task_id=row["task_id"],
                event_type=row["event_type"],
                payload=json.loads(row["payload_json"]),
            )
            for row in rows
        ]

    def add_artifacts(self, task_id: str, artifacts: Iterable[TaskArtifact]) -> None:
        with self._connect() as conn:
            for artifact in artifacts:
                conn.execute(
                    "INSERT INTO task_artifacts (task_id, artifact_type, uri, meta_json, created_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        task_id,
                        artifact.artifact_type,
                        artifact.uri,
                        json.dumps(artifact.meta, ensure_ascii=False),
                        utc_now().isoformat(),
                    ),
                )

    def list_artifacts(self, task_id: str) -> list[TaskArtifact]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT artifact_type, uri, meta_json FROM task_artifacts WHERE task_id = ? ORDER BY id ASC",
                (task_id,),
            ).fetchall()
        return [
            TaskArtifact(
                task_id=task_id,
                artifact_type=row["artifact_type"],
                uri=row["uri"],
                meta=json.loads(row["meta_json"]),
            )
            for row in rows
        ]

    def _row_to_task(self, row: sqlite3.Row) -> TaskRun:
        return TaskRun(
            task_id=row["task_id"],
            task_type=TaskType(row["task_type"]),
            requester=row["requester"],
            chat_id=row["chat_id"],
            message_id=row["message_id"],
            thread_id=row["thread_id"],
            raw_text=row["raw_text"],
            params=json.loads(row["params_json"]),
            status=TaskStatus(row["status"]),
            current_stage=row["current_stage"],
            summary=row["summary"],
            doc_url=row["doc_url"],
            sync_message_id=row["sync_message_id"],
            sync_record_id=row["sync_record_id"],
        )
