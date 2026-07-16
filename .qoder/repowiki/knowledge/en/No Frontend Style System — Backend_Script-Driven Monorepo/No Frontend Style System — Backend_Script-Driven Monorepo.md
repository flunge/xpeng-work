---
kind: frontend_style
name: No Frontend Style System — Backend/Script-Driven Monorepo
category: frontend_style
scope:
    - '**'
---

This repository is a backend and automation-focused monorepo (Python cron jobs, Feishu/Lark agent skills, SimWorld 3DGS platform, LaTeX resume) and does not contain a frontend style system. There are no CSS/SCSS/Tailwind/theme files, no React/Vue/Svelte components, and no browser-facing UI code. The only visual artifacts are:

- Inline-styled HTML email templates under `team/.agents/skills/lark-mail/assets/templates/*.html` (and the mirrored `.claude` copy), which use hand-written inline styles for Lark mail rendering.
- A Node script `team/scripts/html2svg.mjs` that converts small HTML snippets to SVG via Satori for report images.
- LaTeX resume styling in `personal/resume/` using the moderncv class.

These are one-off presentation assets, not a shared frontend styling architecture. Consequently, the `frontend_style` category does not apply to this repo.