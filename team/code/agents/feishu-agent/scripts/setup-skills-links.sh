#!/usr/bin/env bash
set -euo pipefail

# 将仓库根 skills/ 链接到 .cursor/skills、.agents/skills（不提交 Git）
# 用法（仓库根）: bash agents/scripts/setup-skills-links.sh

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKILLS_SRC="${REPO_ROOT}/skills"

if [[ ! -d "${SKILLS_SRC}" ]]; then
  echo "error: ${SKILLS_SRC} not found" >&2
  exit 1
fi

mkdir -p "${REPO_ROOT}/.cursor" "${REPO_ROOT}/.agents"

link_dir() {
  local target_parent="$1"
  local link_path="${target_parent}/skills"
  if [[ -e "${link_path}" && ! -L "${link_path}" ]]; then
    echo "error: ${link_path} is not a symlink; remove it and re-run" >&2
    exit 1
  fi
  ln -sfn ../skills "${link_path}"
  echo "linked ${link_path} -> ../skills"
}

link_dir "${REPO_ROOT}/.cursor"
link_dir "${REPO_ROOT}/.agents"
echo "Done. Skills SSOT: ${SKILLS_SRC}"
