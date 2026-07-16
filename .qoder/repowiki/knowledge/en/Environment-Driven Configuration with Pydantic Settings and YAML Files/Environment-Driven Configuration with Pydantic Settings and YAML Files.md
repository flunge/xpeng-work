---
kind: configuration_system
name: Environment-Driven Configuration with Pydantic Settings and YAML Files
category: configuration_system
scope:
    - '**'
source_files:
    - team/simworld/agents/train-sim-eval-agent/tse/config.py
    - team/simworld/agents/feishu-agent/.env.example
    - team/simworld/agents/feishu-agent/.env
    - personal/meal/config/feishu.yaml
    - personal/meal/config/webhook.yaml
    - cron/install.sh
---

This monorepo uses a hybrid configuration approach combining three complementary mechanisms, each suited to its subsystem:

1. **Pydantic BaseSettings (typed env-driven config)** — The team/simworld/agents/train-sim-eval-agent/tse/config.py module defines a single Settings(BaseSettings) class backed by pydantic_settings. It reads from .env files and environment variables prefixed with TSE_, providing typed defaults, validation, and runtime overrides via effective_settings(). This is the most structured configuration in the repo.

2. **Per-service .env files** — Each Python service ships an .env.example template and a local .env (gitignored) for secrets and per-machine overrides. Notable examples:
   - team/simworld/agents/feishu-agent/.env — OpenAI keys, Feishu daily AI hot push toggles, chat targets.
   - personal/meal/ scripts read config via os.environ / direct file paths; no dedicated loader found but the pattern is consistent.
   - Secrets are never committed; .env.example documents required keys.

3. **YAML data/configuration files** — Human-editable, non-secret configuration lives under config/*.yaml:
   - personal/meal/config/feishu.yaml — Feishu Drive folder tokens, Base/table IDs, field mappings for the meal planner's Lark integration.
   - personal/meal/config/webhook.yaml — Webhook URL and notification send time.
   - Various model configs under team/simworld/models/*/configs/ (e.g., CLIP-IQA, difix) follow the same YAML convention.

4. **Shell-driven orchestration** — cron/install.sh installs crontab entries that invoke thin shell wrappers (cron/scripts/*.sh) which cd into their project root and run Python entry points. These scripts rely on environment variables and YAML files rather than a central config loader.

Conventions observed:
- Secrets go into .env (never committed); documented in .env.example.
- Non-secret service settings go into config/*.yaml or typed BaseSettings fields with sensible defaults.
- Environment variable prefixing (TSE_) scopes settings to one subsystem.
- Runtime override pattern: effective_settings() copies a Settings instance and updates selected fields from request parameters, allowing per-request credential injection without mutating global state.
- Cron jobs assume they are executed from the repository root and use relative paths to locate config.