import asyncio
import logging

from fastapi import FastAPI

from app.application.bootstrap import create_application
from app.infrastructure.llm_health import probe_llm
from app.interfaces.http.feishu_webhook import router as feishu_router
from app.interfaces.http.health import router as health_router
from app.interfaces.http.task_api import router as task_router

logger = logging.getLogger(__name__)


def build_app() -> FastAPI:
    app = FastAPI(title="3dgs Feishu Agent MVP", version="0.1.0")
    application = create_application()
    app.state.application = application

    @app.on_event("startup")
    async def _startup() -> None:
        application.orchestrator.start_worker()
        application.sync_service.send_bootstrap_greeting()
        application.daily_ai_hot_scheduler.start()
        if application.settings.openai_api_key:
            application.llm_probe_result = await asyncio.to_thread(probe_llm, application.settings)
            llm = application.llm_probe_result
            if llm.get("ok"):
                logger.info(
                    "LLM ready (inline): model=%s effort=%s timeout=%ss probe=%ss",
                    llm.get("model"),
                    llm.get("reasoning_effort"),
                    llm.get("timeout_seconds"),
                    llm.get("elapsed_seconds"),
                )
            else:
                logger.warning("LLM probe failed: %s", llm.get("message") or llm.get("status"))
        else:
            application.llm_probe_result = application.llm_config_summary()
            logger.warning("LLM not configured: set OPENAI_API_KEY in agents/.env")

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await application.daily_ai_hot_scheduler.stop()
        await application.orchestrator.stop_worker()

    app.include_router(health_router)
    app.include_router(feishu_router)
    app.include_router(task_router)
    return app


app = build_app()
