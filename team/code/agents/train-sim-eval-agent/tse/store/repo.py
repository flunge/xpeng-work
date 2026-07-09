import json
import sqlite3
from datetime import datetime, timezone
from contextlib import contextmanager
from tse.constants import Status
from tse.models.db import CREATE_TABLE_SQL


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ExperimentRepo:
    def __init__(self, db_path: str):
        self.db_path = db_path
        with self._conn() as c:
            c.executescript(CREATE_TABLE_SQL)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # —— 写：状态镜像（被 mirror_status Activity 调用）——
    def upsert_status(self, experiment_id: str, status: Status, **fields) -> None:
        cols = {"status": status.value, "updated_at": _now()}
        for k in ("branch", "binary_id", "sim_task_id", "report_url",
                  "error", "temporal_workflow_id", "build_key", "submit_key", "feishu_msg_id"):
            if k in fields and fields[k] is not None:
                cols[k] = fields[k]
        if "switches" in fields:
            cols["switches"] = json.dumps(fields["switches"])

        with self._conn() as c:
            exists = c.execute("SELECT 1 FROM experiment WHERE id=?", (experiment_id,)).fetchone()
            if exists:
                sets = ", ".join(f"{k}=?" for k in cols)
                c.execute(f"UPDATE experiment SET {sets} WHERE id=?",
                          (*cols.values(), experiment_id))
            else:
                cols.setdefault("switches", json.dumps(fields.get("switches", {})))
                cols["id"] = experiment_id
                cols["created_at"] = _now()
                keys = ", ".join(cols)
                ph = ", ".join("?" for _ in cols)
                c.execute(f"INSERT INTO experiment ({keys}) VALUES ({ph})", tuple(cols.values()))

    # —— 读：CLI/agentd 查询 ——
    def get(self, experiment_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM experiment WHERE id=?", (experiment_id,)).fetchone()
            return dict(row) if row else None

    def list(self, limit: int = 50) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM experiment ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    # —— 幂等查询 ——
    def find_binary_by_build_key(self, build_key: str) -> str | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT binary_id FROM experiment WHERE build_key=? AND binary_id IS NOT NULL "
                "ORDER BY updated_at DESC LIMIT 1", (build_key,)).fetchone()
            return row["binary_id"] if row else None

    def find_task_by_submit_key(self, submit_key: str) -> str | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT sim_task_id FROM experiment WHERE submit_key=? AND sim_task_id IS NOT NULL "
                "ORDER BY updated_at DESC LIMIT 1", (submit_key,)).fetchone()
            return row["sim_task_id"] if row else None
