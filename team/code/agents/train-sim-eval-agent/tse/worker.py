import asyncio
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.contrib.pydantic import pydantic_data_converter

from tse.config import get_settings
from tse.constants import TASK_QUEUE
from tse.workflows.experiment import ExperimentWorkflow
from tse.activities.infra import mirror_status
from tse.activities.build import build_binary
from tse.activities.submit import submit_simulation
from tse.activities.monitor import monitor_wait
from tse.activities.evaluate import evaluate
from tse.activities.report import generate_and_send_report


async def connect() -> Client:
    s = get_settings()
    return await Client.connect(s.temporal_target, namespace=s.temporal_namespace,
                                data_converter=pydantic_data_converter)


async def run_worker() -> None:
    client = await connect()
    worker = Worker(
        client, task_queue=TASK_QUEUE,
        workflows=[ExperimentWorkflow],
        activities=[mirror_status, build_binary, submit_simulation,
                    monitor_wait, evaluate, generate_and_send_report],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(run_worker())
