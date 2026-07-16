---
kind: build_system
name: Per-Subproject Build & Packaging (No Monorepo Orchestrator)
category: build_system
scope:
    - '**'
source_files:
    - team/simworld/libs/xpeng_raster/setup.py
    - team/simworld/libs/xpeng_raster/scripts/build_in_container.sh
    - team/simworld/libs/xpeng_raster/scripts/build_xpeng_raster_a100.sh
    - team/simworld/tools/dockerfile/latest_a100/Dockerfile
    - team/simworld/agents/train-sim-eval-agent/pyproject.toml
    - team/package.json
    - cron/install.sh
---

This repository is a personal/team monorepo with no top-level build orchestrator. Each subproject owns its own build, packaging, and deployment artifacts independently.

**Python packages**
- `team/simworld/libs/xpeng_raster/` — C++/CUDA extension built via `setup.py` + `torch.utils.cpp_extension.CUDAExtension`. Two helper scripts wrap the build: `scripts/build_in_container.sh` (containerized, env-driven) and `scripts/build_xpeng_raster_a100.sh` (host A100). The Dockerfile at `team/simworld/tools/dockerfile/latest_a100/Dockerfile` reproduces the same steps inside an image, including editable installs and `--no-build-isolation` pip installs.
- `team/simworld/agents/train-sim-eval-agent/` — pure-Python package declared in `pyproject.toml` using `setuptools.build_meta`, split into optional dependency groups (`client`, `server`, `eval`, `dev`) and exposes CLI entry points `tse` / `tse-agentd`.
- Other models under `team/simworld/models/*/` ship their own `setup.py` or `setup.cfg` (e.g. `CLIP-IQA/setup.py`).

**Node.js tooling**
- `team/package.json` declares only runtime deps for SVG-to-image rendering (`@resvg/resvg-js`, `satori`, `satori-html`). There is no top-level `package-lock.json` orchestration; each script that needs Node runs `npm ci` locally.

**Cron & scheduled jobs**
- `cron/install.sh` writes a single crontab that invokes thin shell wrappers under `cron/scripts/*.sh`, which in turn call Python job scripts under `cron/jobs/`. This is the repo's only system-level scheduler.

**LaTeX resume**
- `personal/resume/main.tex` uses the `moderncv` class with classic/orange style; PDF generation is done by running `xelatex`/`pdflatex` against the `.tex` tree (no Makefile).

**Containerization**
- `team/simworld/tools/dockerfile/latest_a100/Dockerfile` is the primary production image, based on an internal Fuyao base image, installing CUDA, PyTorch wheels from Tsinghua/NVIDIA mirrors, then building all in-tree CUDA extensions and third-party C++ libs (`diff-gaussian-rasterization*`, `torchsparse`, `openvdb/fvdb`). A parallel PPU variant exists at `latest_ppu/Dockerfile`.

**CI**
- No `.github/workflows` files exist at the repo root. CI configuration is absent from this repository; any CI lives outside (referenced only in docs of vendored third-party code such as `pybind11/.github/workflows/ci.yml`).