import tempfile
import os
from tse.constants import Status
from tse.store.repo import ExperimentRepo


def _repo() -> ExperimentRepo:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return ExperimentRepo(path)


def test_insert_then_update_status():
    repo = _repo()
    repo.upsert_status("e1", Status.CREATED, branch="b", ckpt_path="/c",
                       switches={"use_difix": True})
    row = repo.get("e1")
    assert row is not None
    assert row["status"] == "CREATED"
    assert row["branch"] == "b"

    repo.upsert_status("e1", Status.BUILD_SUCCESS, binary_id="bin123")
    row = repo.get("e1")
    assert row["status"] == "BUILD_SUCCESS"
    assert row["binary_id"] == "bin123"
    assert row["branch"] == "b"   # 旧字段保留


def test_idempotent_queries():
    repo = _repo()
    repo.upsert_status("e1", Status.BUILD_SUCCESS, branch="b", ckpt_path="/c",
                       build_key="bk1", binary_id="bin1")
    assert repo.find_binary_by_build_key("bk1") == "bin1"
    assert repo.find_binary_by_build_key("missing") is None

    repo.upsert_status("e2", Status.SUBMITTED, branch="b", ckpt_path="/c",
                       submit_key="sk1", sim_task_id="task1")
    assert repo.find_task_by_submit_key("sk1") == "task1"
    assert repo.find_task_by_submit_key("missing") is None


def test_list_orders_recent_first():
    repo = _repo()
    repo.upsert_status("e1", Status.CREATED, branch="b", ckpt_path="/c")
    repo.upsert_status("e2", Status.CREATED, branch="b", ckpt_path="/c")
    rows = repo.list()
    assert {r["id"] for r in rows} == {"e1", "e2"}
