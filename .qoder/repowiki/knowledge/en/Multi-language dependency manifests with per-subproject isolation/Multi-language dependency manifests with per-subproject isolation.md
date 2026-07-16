---
kind: dependency_management
name: Multi-language dependency manifests with per-subproject isolation
category: dependency_management
scope:
    - '**'
source_files:
    - team/package.json
    - team/package-lock.json
    - team/skills-lock.json
    - team/simworld/requirements-feishu.txt
    - team/simworld/agents/feishu-agent/requirements.txt
    - team/simworld/agents/train-sim-eval-agent/pyproject.toml
    - personal/meal/setup.sh
    - personal/meal/scripts/run_daily.sh
    - cron/install.sh
---

This monorepo manages dependencies across several independent subprojects, each using the language-native tooling rather than a top-level workspace manager. There is no shared lockfile or vendoring strategy at the repo root; instead every Python/Node project declares its own requirements and pins versions locally.

- Python (pip / requirements.txt)
  - `team/simworld/agents/feishu-agent/requirements.txt` declares the FastAPI/Uvicorn bot runtime.
  - `team/simworld/requirements-feishu.txt` is an aggregate that `-r`-includes the agent file plus `requests>=2.28,<3`, intended to be installed from the simworld root (`pip install -r requirements-feishu.txt`).
  - `personal/meal/scripts/run_daily.sh` and `setup.sh` perform on-demand `pip3 install --break-system-packages pyyaml` at runtime inside ephemeral containers, so PyYAML has no manifest entry — it is treated as an optional bootstrap dependency.
  - The SimWorld training agent uses a proper `pyproject.toml` (`team/simworld/agents/train-sim-eval-agent/pyproject.toml`) with `dependencies`, `optional-dependencies` (`client`, `server`, `eval`, `dev`, `ssh`), and `[project.scripts]` entry points. This is the only subproject using PEP 621.
  - Several third-party model trees under `team/simworld/models/*/requirements.txt` are vendored copies of upstream projects and are not managed by this repo's tooling.

- Node.js (npm)
  - `team/package.json` lists three pinned `^` ranges: `@resvg/resvg-js`, `satori`, `satori-html`.
  - `team/package-lock.json` (lockfileVersion 3) records exact resolved versions and integrity hashes for all transitive deps, including platform-specific optional binaries of `@resvg/resvg-js`. No `.npmrc` or private registry config is present.

- Lark skills (skills-lock.json)
  - `team/skills-lock.json` and `team/simworld/skills-lock.json` pin Feishu skill definitions fetched from `open.feishu.cn` via `sourceType: "well-known"`, each with a `computedHash`. These are consumed by the lark-cli skill system, not by pip/npm.

- Runtime bootstrapping scripts
  - `cron/install.sh` installs crontab entries but does not manage packages.
  - `personal/meal/setup.sh` checks for `lark-cli` in PATH, re-installs PyYAML if missing, and starts the cron daemon — treating these as environment concerns rather than declarative dependencies.

Conventions observed
- Each subproject owns its own manifest; there is no top-level `requirements.txt`, `package.json`, or `go.mod`.
- Version pinning style is loose (`>=X`, `^X.Y.Z`) rather than strict equality; lockfiles exist only for npm.
- Shared Python surface area is expressed via `requirements-feishu.txt` using `-r` includes rather than a virtual workspace.
- Optional heavy deps (e.g., `pyyaml` for meal, `pandas`/`matplotlib` for eval) are either installed lazily at runtime or isolated into `optional-dependencies` groups.