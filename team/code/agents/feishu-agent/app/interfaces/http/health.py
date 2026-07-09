from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict:
    application = request.app.state.application
    return {
        "service": "3dgs-feishu-agent",
        "llm": application.llm_probe_result or application.llm_config_summary(),
    }
