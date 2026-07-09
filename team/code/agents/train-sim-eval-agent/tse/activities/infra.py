from temporalio import activity
from tse.config import get_settings
from tse.constants import Status
from tse.store.repo import ExperimentRepo


@activity.defn
async def mirror_status(experiment_id: str, status: str, fields: dict) -> None:
    repo = ExperimentRepo(get_settings().db_path)
    repo.upsert_status(experiment_id, Status(status), **fields)
