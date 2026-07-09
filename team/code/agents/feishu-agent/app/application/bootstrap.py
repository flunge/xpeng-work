from __future__ import annotations

from pathlib import Path

from app.application.command_parser import CommandParser
from app.application.daily_ai_hot import DailyAiHotScheduler
from app.application.orchestrator import TaskOrchestrator
from app.application.sync_service import SyncService
from app.executors.registry import ExecutorRegistry
from app.infrastructure.llm_health import llm_config_summary
from app.infrastructure.local_agent_client import LocalAgentClient
from app.infrastructure.feishu_clients import (
    FeishuDocClient,
    FeishuMessageClient,
    FeishuSheetClient,
    RealFeishuDocClient,
    RealFeishuMessageClient,
    RealFeishuSheetClient,
)
from app.infrastructure.feishu_config import FeishuCliAuthAdapter, FeishuSettings
from app.infrastructure.sqlite_repo import SQLiteTaskRepository


class ApplicationContainer:
    def __init__(
        self,
        orchestrator: TaskOrchestrator,
        sync_service: SyncService,
        daily_ai_hot_scheduler: DailyAiHotScheduler,
        settings: FeishuSettings,
        llm_probe_result: dict | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.sync_service = sync_service
        self.daily_ai_hot_scheduler = daily_ai_hot_scheduler
        self.settings = settings
        self.llm_probe_result = llm_probe_result

    def llm_config_summary(self) -> dict:
        return llm_config_summary(self.settings)


def create_application() -> ApplicationContainer:
    root = Path(__file__).resolve().parents[2]
    db_path = root / "data" / "agent.db"
    repository = SQLiteTaskRepository(str(db_path))
    parser = CommandParser()
    settings = FeishuSettings.from_env()
    agent_client = LocalAgentClient(settings)
    executors = ExecutorRegistry(agent_client=agent_client)
    if settings.mode == "cli":
        auth = FeishuCliAuthAdapter(settings)
        auth.validate_ready()
        message_client = RealFeishuMessageClient(settings, auth)
        doc_client = RealFeishuDocClient(settings, auth)
        sheet_client = RealFeishuSheetClient(settings, auth)
    else:
        message_client = FeishuMessageClient()
        doc_client = FeishuDocClient()
        sheet_client = FeishuSheetClient()

    sync_service = SyncService(
        message_client=message_client,
        doc_client=doc_client,
        sheet_client=sheet_client,
        settings=settings,
    )
    orchestrator = TaskOrchestrator(repository, parser, executors, sync_service)
    daily_ai_hot_scheduler = DailyAiHotScheduler(settings, message_client)
    return ApplicationContainer(orchestrator, sync_service, daily_ai_hot_scheduler, settings)
