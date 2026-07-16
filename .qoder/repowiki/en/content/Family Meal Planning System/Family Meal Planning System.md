# Family Meal Planning System

<cite>
**Referenced Files in This Document**
- [meal/README.md](file://meal/README.md)
- [meal/config/family.yaml](file://meal/config/family.yaml)
- [meal/config/holidays-2026.yaml](file://meal/config/holidays-2026.yaml)
- [meal/config/vacations-2026.yaml](file://meal/config/vacations-2026.yaml)
- [meal/config/webhook.yaml](file://meal/config/webhook.yaml)
- [meal/scripts/generate_month.py](file://meal/scripts/generate_month.py)
- [meal/scripts/notify_daily.py](file://meal/scripts/notify_daily.py)
- [meal/scripts/run_daily.sh](file://meal/scripts/run_daily.sh)
- [meal/scripts/generate_next_month.sh](file://meal/scripts/generate_next_month.sh)
- [meal/scripts/check_feedback.py](file://meal/scripts/check_feedback.py)
- [meal/scripts/weekly_shop.py](file://meal/scripts/weekly_shop.py)
- [meal/setup.sh](file://meal/setup.sh)
- [meal/recipes/breakfast/01-奶香玉米汁-西葫芦鸡蛋饼.yaml](file://meal/recipes/breakfast/01-奶香玉米汁-西葫芦鸡蛋饼.yaml)
- [meal/recipes/dinner/01-香菇滑鸡-上汤娃娃菜.yaml](file://meal/recipes/dinner/01-香菇滑鸡-上汤娃娃菜.yaml)
- [meal/plans/daily/2026-07-01.md](file://meal/plans/daily/2026-07-01.md)
- [meal/plans/2026-06.md](file://meal/plans/2026-06.md)
</cite>

## Table of Contents
1. Introduction
2. Project Structure
3. Core Components
4. Architecture Overview
5. Detailed Component Analysis
6. Dependency Analysis
7. Performance Considerations
8. Troubleshooting Guide
9. Conclusion
10. Appendices

## Introduction
This document describes the Family Meal Planning System designed for a family of four (two adults and two young children). The system automatically generates daily meal notifications and monthly plans using constraint-based algorithms. It balances nutrition, respects dietary preferences and cooking constraints, reduces ingredient waste through cross-day reuse, and adapts to holidays and school vacations. Notifications are delivered via Feishu (Lark), and all planning logic is driven by YAML configuration files processed by Python scripts.

Key outcomes:
- Daily Feishu notifications with next-day or same-day menus, prep steps, and shopping lists
- Monthly plan generation with no-repeat rules across meals and days
- Holiday-aware scheduling and vacation-mode quick lunches
- Ingredient optimization and variety maintenance
- Practical guidance for adding recipes, customizing settings, and troubleshooting

## Project Structure
The project is organized into configuration, recipe data, generated plans, automation scripts, and deployment helpers.

```mermaid
graph TB
subgraph "Config"
F["family.yaml"]
H["holidays-2026.yaml"]
V["vacations-2026.yaml"]
W["webhook.yaml"]
end
subgraph "Recipes"
RB["breakfast/*.yaml"]
RL["lunch/*.yaml"]
RD["dinner/*.yaml"]
RS["side/*.yaml"]
RQ["lunch_quick/*.yaml"]
end
subgraph "Scripts"
GM["generate_month.py"]
ND["notify_daily.py"]
RN["run_daily.sh"]
GN["generate_next_month.sh"]
CF["check_feedback.py"]
WS["weekly_shop.py"]
end
subgraph "Output"
PM["plans/YYYY-MM.md"]
PD["plans/daily/YYYY-MM-DD.md"]
NF["notifications/*"]
end
F --> GM
H --> GM
V --> GM
RB --> GM
RL --> GM
RD --> GM
RS --> GM
RQ --> GM
GM --> PM
GM --> PD
RN --> ND
GN --> GM
ND --> NF
CF --> NF
WS --> PD
```

**Diagram sources**
- [meal/scripts/generate_month.py:1-654](file://meal/scripts/generate_month.py#L1-L654)
- [meal/scripts/notify_daily.py:1-279](file://meal/scripts/notify_daily.py#L1-L279)
- [meal/scripts/run_daily.sh:1-9](file://meal/scripts/run_daily.sh#L1-L9)
- [meal/scripts/generate_next_month.sh:1-19](file://meal/scripts/generate_next_month.sh#L1-L19)
- [meal/scripts/check_feedback.py:1-137](file://meal/scripts/check_feedback.py#L1-L137)
- [meal/scripts/weekly_shop.py:1-328](file://meal/scripts/weekly_shop.py#L1-L328)
- [meal/config/family.yaml:1-74](file://meal/config/family.yaml#L1-L74)
- [meal/config/holidays-2026.yaml:1-39](file://meal/config/holidays-2026.yaml#L1-L39)
- [meal/config/vacations-2026.yaml:1-13](file://meal/config/vacations-2026.yaml#L1-L13)
- [meal/config/webhook.yaml:1-6](file://meal/config/webhook.yaml#L1-L6)

**Section sources**
- [meal/README.md:1-108](file://meal/README.md#L1-L108)

## Core Components
- Configuration layer
  - Family profile, preferences, appliances, and constraints
  - Holidays and workday compensations
  - School vacations for weekday quick lunch mode
  - Webhook URL and send time (for documentation; current notification uses app bot)
- Recipe database
  - Structured YAML per category: breakfast, lunch, dinner, side, lunch_quick
  - Fields include title, type, difficulty, total_time, servings, tools, tags, ingredient_tags, ingredients, night_prep, morning_steps, noon_steps, steps, notes
- Planning engine
  - Constraint-based selection with anti-repetition, cross-meal signature deduplication, ingredient clustering, and month rotation
  - Day-type classification (workday, weekend, holiday) and vacation-aware quick lunch insertion
- Output layer
  - Monthly overview Markdown
  - Daily cards with full details and shopping list
  - Feishu card messages and logs
- Automation and operations
  - Cron-driven daily notification and month-end plan generation
  - Feedback polling and weekly shopping planner

**Section sources**
- [meal/config/family.yaml:1-74](file://meal/config/family.yaml#L1-L74)
- [meal/config/holidays-2026.yaml:1-39](file://meal/config/holidays-2026.yaml#L1-L39)
- [meal/config/vacations-2026.yaml:1-13](file://meal/config/vacations-2026.yaml#L1-L13)
- [meal/config/webhook.yaml:1-6](file://meal/config/webhook.yaml#L1-L6)
- [meal/recipes/breakfast/01-奶香玉米汁-西葫芦鸡蛋饼.yaml:1-48](file://meal/recipes/breakfast/01-奶香玉米汁-西葫芦鸡蛋饼.yaml#L1-L48)
- [meal/recipes/dinner/01-香菇滑鸡-上汤娃娃菜.yaml:1-71](file://meal/recipes/dinner/01-香菇滑鸡-上汤娃娃菜.yaml#L1-L71)
- [meal/scripts/generate_month.py:1-654](file://meal/scripts/generate_month.py#L1-L654)
- [meal/scripts/notify_daily.py:1-279](file://meal/scripts/notify_daily.py#L1-L279)
- [meal/scripts/run_daily.sh:1-9](file://meal/scripts/run_daily.sh#L1-L9)
- [meal/scripts/generate_next_month.sh:1-19](file://meal/scripts/generate_next_month.sh#L1-L19)
- [meal/scripts/check_feedback.py:1-137](file://meal/scripts/check_feedback.py#L1-L137)
- [meal/scripts/weekly_shop.py:1-328](file://meal/scripts/weekly_shop.py#L1-L328)

## Architecture Overview
End-to-end flow from configuration and recipes to outputs and notifications.

```mermaid
sequenceDiagram
participant User as "User"
participant Cron as "Cron"
participant Gen as "generate_month.py"
participant Notif as "notify_daily.py"
participant Lark as "Feishu Bot"
participant FS as "Filesystem"
User->>Gen : Run monthly generator (manual or cron)
Gen->>FS : Read config (family, holidays, vacations)
Gen->>FS : Load recipes (breakfast/lunch/dinner/side/lunch_quick)
Gen->>Gen : Classify day types<br/>Apply constraints & scoring
Gen-->>FS : Write plans/YYYY-MM.md
Gen-->>FS : Write plans/daily/YYYY-MM-DD.md
Cron->>Notif : Trigger at scheduled time
Notif->>FS : Find target daily card (today/tomorrow)
Notif->>Notif : Extract sections and format Feishu card
Notif->>Lark : Send interactive card via lark-cli
Lark-->>Notif : Acknowledge
Notif-->>FS : Log to notifications/send.log
```

**Diagram sources**
- [meal/scripts/generate_month.py:1-654](file://meal/scripts/generate_month.py#L1-L654)
- [meal/scripts/notify_daily.py:1-279](file://meal/scripts/notify_daily.py#L1-L279)
- [meal/scripts/run_daily.sh:1-9](file://meal/scripts/run_daily.sh#L1-L9)
- [meal/scripts/generate_next_month.sh:1-19](file://meal/scripts/generate_next_month.sh#L1-L19)

## Detailed Component Analysis

### Planning Engine (generate_month.py)
Responsibilities:
- Load YAML configs and recipe pools
- Classify each date as workday, weekend, or holiday; detect vacation periods
- Select meals under constraints:
  - No repeat within a month per meal type
  - Cross-meal signature deduplication to avoid same staple across breakfast/lunch/dinner
  - Ingredient clustering to reduce waste (prefer shared ingredient_tags)
  - Anti-clustering for breakfast to ensure variety
  - Month rotation to avoid identical sequences across months
- Generate monthly overview and daily cards with shopping lists

Algorithm highlights:
- pick_recipes: filters by used titles and signatures, applies preferred/avoided tags, falls back to index cycling
- pick_side: selects side dishes with category preference and tag matching
- generate_month_plan: orchestrates day-by-day selection and writes outputs

```mermaid
flowchart TD
Start(["Start"]) --> LoadCfg["Load family.yaml, holidays, vacations"]
LoadCfg --> LoadRec["Load recipe pools by type"]
LoadRec --> ForEachDay{"For each day"}
ForEachDay --> DayType["Classify day_type + holiday/vacation"]
DayType --> NeedsBreakfast{"Needs breakfast?"}
NeedsBreakfast --> |Yes| PickB["pick_recipes(breakfast, avoid_tags=last_breakfast_tags)"]
NeedsBreakfast --> |No| NextMeal["Next meal decision"]
PickB --> UpdateBTags["Update last_breakfast_tags"]
UpdateBTags --> NextMeal
NextMeal --> NeedsLunch{"Needs lunch?"}
NeedsLunch --> |Yes| PickL["pick_recipes(lunch, preferred_tags=last_lunch_tags)"]
NeedsLunch --> |No| NextDinner["Next dinner decision"]
PickL --> SideL["pick_side(sides, prefer_category='coarse grain')"]
SideL --> UpdateLTags["Update last_lunch_tags"]
UpdateLTags --> NextDinner
NextDinner --> NeedsDinner{"Needs dinner?"}
NeedsDinner --> |Yes| PickD["pick_recipes(dinner, preferred_tags=last_dinner_tags,<br/>exclude_sigs=same_day_staples)"]
NeedsDinner --> |No| QuickLunchCheck["Vacation weekday?"]
PickD --> UpdateDTags["Update last_dinner_tags"]
UpdateDTags --> QuickLunchCheck
QuickLunchCheck --> |Yes| PickQL["pick_recipes(lunch_quick, exclude_sigs=breakfast_signature)"]
QuickLunchCheck --> |No| EndDay["Append day entry"]
PickQL --> UpdateQLTags["Update last_quick_lunch_tags"]
UpdateQLTags --> EndDay
EndDay --> ForEachDay
ForEachDay --> |Done| WriteOut["Write monthly overview + daily cards"]
WriteOut --> End(["End"])
```

**Diagram sources**
- [meal/scripts/generate_month.py:1-654](file://meal/scripts/generate_month.py#L1-L654)

**Section sources**
- [meal/scripts/generate_month.py:1-654](file://meal/scripts/generate_month.py#L1-L654)

### Notification Flow (notify_daily.py)
Responsibilities:
- Determine target date based on Beijing time and optional --date flag
- Locate the corresponding daily card
- Parse sections and build a Feishu interactive card
- Send via lark-cli to a DM chat ID
- Log success/failure

```mermaid
sequenceDiagram
participant Cron as "Cron"
participant Script as "notify_daily.py"
participant FS as "Filesystem"
participant CLI as "lark-cli"
participant Bot as "Feishu Bot"
Cron->>Script : Execute run_daily.sh -> notify_daily.py
Script->>FS : find_target_daily_card(force_date?)
alt File exists
Script->>Script : extract_sections(content)
Script->>Script : format_lark_card(...)
Script->>CLI : im +messages-send --chat-id ...
CLI-->>Bot : Send interactive card
Bot-->>CLI : OK
CLI-->>Script : returncode==0
Script->>FS : Append notifications/send.log
else File missing
Script-->>Cron : Exit with warning
end
```

**Diagram sources**
- [meal/scripts/notify_daily.py:1-279](file://meal/scripts/notify_daily.py#L1-L279)
- [meal/scripts/run_daily.sh:1-9](file://meal/scripts/run_daily.sh#L1-L9)

**Section sources**
- [meal/scripts/notify_daily.py:1-279](file://meal/scripts/notify_daily.py#L1-L279)
- [meal/scripts/run_daily.sh:1-9](file://meal/scripts/run_daily.sh#L1-L9)

### Weekly Shopping Planner (weekly_shop.py)
Responsibilities:
- Aggregate ingredients from daily cards for a given week
- Classify perishability (short/medium/long shelf life)
- Provide tips for single-use fresh items and shared ingredients
- Produce categorized supermarket-style lists

```mermaid
flowchart TD
A["Input: plans/daily/YYYY-MM-DD.md"] --> B["Extract shopping list lines"]
B --> C["Normalize item names (strip amounts/notes)"]
C --> D["Classify perishability"]
D --> E["Aggregate counts and days"]
E --> F["Group by category (fresh/medium/long)"]
F --> G["Generate tips and recommendations"]
G --> H["Print categorized shopping list"]
```

**Diagram sources**
- [meal/scripts/weekly_shop.py:1-328](file://meal/scripts/weekly_shop.py#L1-L328)

**Section sources**
- [meal/scripts/weekly_shop.py:1-328](file://meal/scripts/weekly_shop.py#L1-L328)

### Feedback Poller (check_feedback.py)
Responsibilities:
- Query recent messages from a Feishu group using lark-cli
- Detect feedback keywords related to taste, portion size, repetition, etc.
- Persist findings to notifications/feedback.md

**Section sources**
- [meal/scripts/check_feedback.py:1-137](file://meal/scripts/check_feedback.py#L1-L137)

### Deployment and Scheduling
- setup.sh installs PyYAML if missing, verifies lark-cli presence, installs crontab entries, and starts cron daemon when available
- run_daily.sh ensures dependencies and invokes notify_daily.py
- generate_next_month.sh runs on the last day of the month to generate next month’s plan

**Section sources**
- [meal/setup.sh:1-84](file://meal/setup.sh#L1-L84)
- [meal/scripts/run_daily.sh:1-9](file://meal/scripts/run_daily.sh#L1-L9)
- [meal/scripts/generate_next_month.sh:1-19](file://meal/scripts/generate_next_month.sh#L1-L19)

## Dependency Analysis
High-level dependency relationships among components.

```mermaid
graph LR
CFG["Config YAMLs"] --> GEN["generate_month.py"]
REC["Recipe YAMLs"] --> GEN
GEN --> OUTM["Monthly Plan MD"]
GEN --> OUTD["Daily Cards MD"]
RUN["run_daily.sh"] --> NOTI["notify_daily.py"]
NOTI --> FEISHU["Feishu Bot (lark-cli)"]
NEXT["generate_next_month.sh"] --> GEN
FEED["check_feedback.py"] --> LOGS["notifications/*"]
SHOP["weekly_shop.py"] --> OUTD
```

**Diagram sources**
- [meal/scripts/generate_month.py:1-654](file://meal/scripts/generate_month.py#L1-L654)
- [meal/scripts/notify_daily.py:1-279](file://meal/scripts/notify_daily.py#L1-L279)
- [meal/scripts/run_daily.sh:1-9](file://meal/scripts/run_daily.sh#L1-L9)
- [meal/scripts/generate_next_month.sh:1-19](file://meal/scripts/generate_next_month.sh#L1-L19)
- [meal/scripts/check_feedback.py:1-137](file://meal/scripts/check_feedback.py#L1-L137)
- [meal/scripts/weekly_shop.py:1-328](file://meal/scripts/weekly_shop.py#L1-L328)

**Section sources**
- [meal/scripts/generate_month.py:1-654](file://meal/scripts/generate_month.py#L1-L654)
- [meal/scripts/notify_daily.py:1-279](file://meal/scripts/notify_daily.py#L1-L279)

## Performance Considerations
- Deterministic selection with index cycling prevents starvation and avoids expensive recomputation
- Ingredient tag matching is O(n) per pool; typical pools are small (<100), so performance is negligible
- Month rotation ensures varied sequences without additional computation
- File I/O dominates runtime; batch write of daily cards is efficient
- Avoid excessive logging in hot paths; keep cron logs concise

[No sources needed since this section provides general guidance]

## Troubleshooting Guide
Common issues and resolutions:
- Missing PyYAML after Pod restart
  - Re-run setup.sh to install dependencies and restore cron jobs
- Feishu notification fails
  - Ensure lark-cli is installed and authorized; verify chat ID and message JSON; check notifications/send.log
- No daily card found
  - Run generate_month.py for the relevant month first; confirm plans/daily/YYYY-MM-DD.md exists
- Repetitive meals or lack of variety
  - Expand recipe pools; add ingredient_tags to improve clustering; adjust family preferences (e.g., kid_friendly, taste_priority)
- Ingredient waste
  - Use ingredient_economy.cross_day_reuse; leverage weekly_shop.py to identify single-use fresh items and consolidate purchases
- Vacation mode not triggering
  - Verify vacations-2026.yaml ranges and that generate_month.py loads them; ensure lunch_quick recipes exist

**Section sources**
- [meal/setup.sh:1-84](file://meal/setup.sh#L1-L84)
- [meal/scripts/notify_daily.py:1-279](file://meal/scripts/notify_daily.py#L1-L279)
- [meal/scripts/generate_month.py:1-654](file://meal/scripts/generate_month.py#L1-L654)
- [meal/scripts/weekly_shop.py:1-328](file://meal/scripts/weekly_shop.py#L1-L328)
- [meal/config/vacations-2026.yaml:1-13](file://meal/config/vacations-2026.yaml#L1-L13)

## Conclusion
The Family Meal Planning System combines structured YAML configurations, a robust constraint-based planner, and automated Feishu notifications to deliver practical, nutritious, and varied meal plans for a family of four. Its design emphasizes ingredient efficiency, holiday awareness, and ease of customization, while providing operational resilience through setup and cron automation.

[No sources needed since this section summarizes without analyzing specific files]

## Appendices

### Data Model: Recipe YAML Schema
Core fields used across categories:
- title: string
- type: enum {breakfast, lunch, dinner, side, lunch_quick}
- difficulty: string
- total_time: string
- servings: integer
- tools: array of strings
- series: string (optional)
- tags: array of strings
- ingredient_tags: array of strings
- ingredients: map of section to list of items
  - name: string
  - amount: string
  - note: string (optional)
  - optional: boolean (optional)
- night_prep: array of strings (optional)
- morning_steps: array of strings (optional, breakfast)
- noon_steps: array of strings (optional, lunch_quick)
- steps: array of step objects or strings (optional, main courses)
  - step: string
  - tool: string (optional)
- notes: string (optional)

Example references:
- Breakfast example: [meal/recipes/breakfast/01-奶香玉米汁-西葫芦鸡蛋饼.yaml:1-48](file://meal/recipes/breakfast/01-奶香玉米汁-西葫芦鸡蛋饼.yaml#L1-L48)
- Dinner example: [meal/recipes/dinner/01-香菇滑鸡-上汤娃娃菜.yaml:1-71](file://meal/recipes/dinner/01-香菇滑鸡-上汤娃娃菜.yaml#L1-L71)

**Section sources**
- [meal/recipes/breakfast/01-奶香玉米汁-西葫芦鸡蛋饼.yaml:1-48](file://meal/recipes/breakfast/01-奶香玉米汁-西葫芦鸡蛋饼.yaml#L1-L48)
- [meal/recipes/dinner/01-香菇滑鸡-上汤娃娃菜.yaml:1-71](file://meal/recipes/dinner/01-香菇滑鸡-上汤娃娃菜.yaml#L1-L71)

### Configuration Options Reference
- family.yaml
  - members, count, preferences (no_spicy, light_oil_salt, kid_friendly, kid_favorite_flavors, taste_priority, no_deep_fry, air_fryer_ok, no_microwave, appliances)
  - servings_basis (adults, kids)
  - breakfast constraints (max_morning_time, night_prep_ok, components_required, month_no_repeat, nutrition_for_kids)
  - holiday_meal constraints (min/max dishes, has_staple, soup_optional, meat_veg_balance, coarse_fine_grain)
  - vacation_quick_lunch (enabled, trigger, servings, max_noon_time, night_prep_ok, recipes_dir, note)
  - ingredient_economy (min_pack_note, cross_day_reuse)
- holidays-2026.yaml
  - year, holidays[] (name, start, end, workdays[])
- vacations-2026.yaml
  - year, vacations[] (name, start, end)
- webhook.yaml
  - url, send_time (documented; current implementation uses lark-cli DM)

Practical examples:
- Add a new breakfast recipe: create a YAML under recipes/breakfast following the schema; ensure ingredient_tags and tools are set
- Modify family preferences: edit family.yaml to reflect new tastes, appliance availability, or child-friendly priorities
- Customize meal generation rules: adjust breakfast components_required, holiday_meal dish counts, or enable/disable vacation_quick_lunch

**Section sources**
- [meal/config/family.yaml:1-74](file://meal/config/family.yaml#L1-L74)
- [meal/config/holidays-2026.yaml:1-39](file://meal/config/holidays-2026.yaml#L1-L39)
- [meal/config/vacations-2026.yaml:1-13](file://meal/config/vacations-2026.yaml#L1-L13)
- [meal/config/webhook.yaml:1-6](file://meal/config/webhook.yaml#L1-L6)

### Output Artifacts
- Monthly overview: plans/YYYY-MM.md
- Daily cards: plans/daily/YYYY-MM-DD.md (includes prep steps, ingredients, and shopping list)
- Logs: notifications/send.log, notifications/cron.log, notifications/feedback.md

Examples:
- Sample daily card: [meal/plans/daily/2026-07-01.md:1-106](file://meal/plans/daily/2026-07-01.md#L1-L106)
- Sample monthly overview: [meal/plans/2026-06.md:1-200](file://meal/plans/2026-06.md#L1-L200)

**Section sources**
- [meal/plans/daily/2026-07-01.md:1-106](file://meal/plans/daily/2026-07-01.md#L1-L106)
- [meal/plans/2026-06.md:1-200](file://meal/plans/2026-06.md#L1-L200)