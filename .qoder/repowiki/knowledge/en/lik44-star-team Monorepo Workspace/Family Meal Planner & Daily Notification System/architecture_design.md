Data-driven, script-only system organized into four layers:
- `config/` — static YAML inputs: `family.yaml` (4-member preferences, appliance constraints, breakfast components), `holidays-2026.yaml` / `vacations-2026.yaml` (holiday/vacation date ranges), `webhook.yaml` (Feishu target).
- `recipes/` — recipe library split by meal type (`breakfast/`, `lunch/`, `dinner/`, `side/`, plus `lunch_quick/` for vacation weekdays); each dish is one `.yaml` file with `ingredient_tags` used as the cross-day clustering key.
- `plans/` — generated output only: `YYYY-MM.md` monthly overviews and `plans/daily/YYYY-MM-DD.md` daily cards containing ingredients, steps, night-prep, and a shopping list.
- `scripts/` — Python3 + PyYAML entry points orchestrated by cron via shell wrappers:
  * `generate_month.py` loads all YAML recipes, classifies each day as workday/weekend/holiday/vacation, picks dishes using an ingredient-tag similarity score with cycle-reset to avoid starvation, writes monthly overview + per-day Markdown cards.
  * `notify_daily.py` parses the next-day card's Markdown sections, builds a Feishu interactive card JSON, POSTs it via `urllib.request` to the webhook URL from `config/webhook.yaml`.
  * `weekly_shop.py` aggregates ingredients across a week and groups by shelf life.
  * `check_feedback.py` + `check_feedback.sh` use the external `lark-cli` binary to pull recent group messages and match keywords.
  * Shell wrappers `run_daily.sh`, `generate_next_month.sh` are thin crontab targets; `setup.sh` installs PyYAML, rewrites crontab entries (UTC-aware, Beijing time offsets), and starts the cron daemon.
Dependency direction is strictly one-way: scripts → config + recipes → plans + notifications logs. There is no shared Python package or import graph between scripts — each is self-contained.