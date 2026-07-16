---
kind: error_handling
name: 'Python Error Handling: Custom Exception Hierarchy, FastAPI HTTPException, and Structured Logging'
category: error_handling
scope:
    - '**'
source_files:
    - team/simworld/agents/feishu-agent/app/infrastructure/feishu_config.py
    - team/simworld/agents/feishu-agent/app/application/orchestrator.py
    - team/simworld/agents/feishu-agent/app/interfaces/http/task_api.py
    - team/simworld/agents/feishu-agent/app/executors/base.py
    - cron/jobs/ai_news.py
    - cron/jobs/chat_summary.py
    - cron/jobs/stock_pick.py
---

This monorepo uses a mixed but mostly Python-centric error-handling strategy across its Feishu agent service (FastAPI), cron job scripts, and supporting tools. There is no single centralized error module; instead, conventions are layered per subsystem.

### 1. What system/approach is used
- **Custom exception hierarchy** for domain/integration failures in the Feishu agent (`FeishuConfigurationError`, `FeishuIntegrationError`, `FeishuPermissionError` all subclassing `RuntimeError`).
- **Built-in exceptions** raised directly (`KeyError`, `ValueError`, `json.JSONDecodeError`, `FileNotFoundError`) for configuration/IO/validation errors.
- **FastAPI `HTTPException`** at API boundaries to translate internal errors into HTTP responses (404 for missing tasks).
- **Structured logging via `logging`** with `logger.exception(...)` around worker loops and failure paths; no dedicated structured logger (e.g., structlog) or log-level management framework.
- **Cron jobs** rely on bare `try/except` blocks catching `Exception` / specific built-ins and printing or ignoring failures — no retry/backoff library.

### 2. Key files and packages
- `team/simworld/agents/feishu-agent/app/infrastructure/feishu_config.py` — defines `FeishuConfigurationError`, `FeishuIntegrationError`, `FeishuPermissionError`; raises them when lark-cli is missing, unauthenticated, permission-denied, or output is malformed.
- `team/simworld/agents/feishu-agent/app/application/orchestrator.py` — central task worker loop catches any `Exception` from executor execution, marks tasks `FAILED`, persists an event, and attempts sync anyway; also raises `KeyError` for unknown task IDs.
- `team/simworld/agents/feishu-agent/app/interfaces/http/task_api.py` — converts `KeyError` from orchestrator into `HTTPException(status_code=404, detail=...)`.
- `team/simworld/agents/feishu-agent/app/executors/base.py` — abstract base raises `NotImplementedError` for missing executor implementations.
- `cron/jobs/*.py` — lightweight scripts using ad-hoc `try/except` around network/JSON parsing calls; no custom error types.

### 3. Architecture and conventions
- **Layered error propagation**: low-level infrastructure code raises typed `Feishu*` exceptions; the orchestrator treats any exception as a terminal failure and records it; HTTP routes only expose `HTTPException`s.
- **Failure recording over rethrowing**: the worker loop never re-raises after catching; it updates DB state, emits a `task.failed` event, and tries to push status back to Feishu even on failure.
- **Graceful degradation**: webhook parser returns `None` for unsupported events rather than raising; busy-reply failures are logged and persisted without aborting the task.
- **No global middleware**: there is no FastAPI exception handler registered to normalize error responses; each route handles its own `KeyError → HTTPException` mapping.

### 4. Rules developers should follow
- Prefer raising the appropriate `FeishuConfigurationError` / `FeishuIntegrationError` / `FeishuPermissionError` in infrastructure code instead of generic `RuntimeError` so callers can distinguish config vs. runtime vs. auth issues.
- Let the orchestrator's worker loop be the single place that wraps executor execution in `try/except Exception`; do not swallow exceptions inside executors — return `ExecutionResult` with `status=FAILED` if you need controlled failure semantics.
- At HTTP boundaries, convert domain exceptions to `HTTPException` with explicit status codes (404 for missing resources); avoid returning raw exception strings in responses.
- Use `logger.exception(...)` for unexpected failures so stack traces are captured; supplement with `TaskEvent` persistence for auditability.
- Cron job scripts should at minimum catch `Exception` around external calls and log the traceback; consider adding simple retry wrappers if jobs are idempotent.