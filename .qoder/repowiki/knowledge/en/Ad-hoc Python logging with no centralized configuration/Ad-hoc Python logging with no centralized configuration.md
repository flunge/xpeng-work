---
kind: logging_system
name: Ad-hoc Python logging with no centralized configuration
category: logging_system
scope:
    - '**'
source_files:
    - team/simworld/agents/feishu-agent/app/main.py
    - team/simworld/agents/feishu-agent/app/application/bootstrap.py
    - team/simworld/agents/feishu-agent/app/application/daily_ai_hot.py
    - cron/jobs/ai_news.py
    - personal/meal/scripts/notify_daily.py
---

This monorepo has no unified logging system. Each sub-project uses its own ad-hoc approach:

- **Feishu Agent (FastAPI service)** — Uses the standard library `logging` module, creating a logger per module via `logger = logging.getLogger(__name__)` and calling `logger.info(...)` / `logger.warning(...)`. There is no `logging.basicConfig()` or custom handler setup in `app/main.py` or `bootstrap.py`, so log output relies on Python's default stderr handler. No structured fields, no log-level configuration, no file sink.
- **Cron job scripts** (`cron/jobs/*.py`) — Do not use any logging framework; they print status to stdout/stderr via `print()` and rely on the shell wrapper to capture output.
- **Meal planner scripts** (`personal/meal/scripts/*.py`) — Use `print()` for user-facing messages and append timestamped lines to a local file `notifications/send.log` via plain file I/O for success tracking.
- **SimWorld model/tooling code** — Scattered `logging.basicConfig(level=logging.INFO)` calls in various one-off scripts under `models/dynamic_assets/`, plus third-party library level suppression (e.g., `logging.getLogger('libav').setLevel(50)`, `logging.getLogger("torch").setLevel(logging.ERROR)`). A few legacy utilities define their own logger helpers.

There is no shared logging utility, no environment-driven log level, no JSON/structured format, and no central sink configuration. Log behavior varies by script and depends entirely on each entry point's local imports.