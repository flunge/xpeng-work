from __future__ import annotations

import time
from typing import Any

from app.infrastructure.feishu_config import FeishuSettings
from app.infrastructure.local_agent_client import LocalAgentClient


def llm_config_summary(settings: FeishuSettings) -> dict[str, Any]:
    return {
        "mode": "inline",
        "description": "大模型随 Agent 进程内按需调用 SoCheap，无独立 LLM 服务进程",
        "configured": bool(settings.openai_api_key),
        "base_url": settings.openai_base_url,
        "model": settings.openai_model,
        "reasoning_effort": settings.openai_reasoning_effort,
        "timeout_seconds": settings.openai_timeout_seconds,
    }


def probe_llm(settings: FeishuSettings, *, probe_timeout: int = 60) -> dict[str, Any]:
    summary = llm_config_summary(settings)
    if not settings.openai_api_key:
        return {**summary, "ok": False, "status": "not_configured", "message": "未设置 OPENAI_API_KEY"}

    client = LocalAgentClient(settings)
    started = time.perf_counter()
    result = client.execute_prompt("请只回复：ok", timeout_seconds=probe_timeout)
    elapsed = round(time.perf_counter() - started, 2)
    mode = result.metrics.get("mode")
    if mode == "generic_llm":
        return {
            **summary,
            "ok": True,
            "status": "ok",
            "elapsed_seconds": elapsed,
            "probe_reply": (result.summary or "")[:80],
        }
    return {
        **summary,
        "ok": False,
        "status": "error",
        "elapsed_seconds": elapsed,
        "message": result.summary,
        "error": result.metrics.get("error"),
    }
