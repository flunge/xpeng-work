#!/usr/bin/env bash
# 【更新 repo】命令脚本
# 一键：拉取远程 → 更新 submodule → 解压根目录包 → 处理冲突 → 提交推送

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$REPO_ROOT"

CURRENT_BRANCH="$(git branch --show-current)"

# 收集 submodule 列表（只收集顶层）
SUBMODULES=""
if [ -f "$REPO_ROOT/.gitmodules" ]; then
  SUBMODULES="$(git config --file "$REPO_ROOT/.gitmodules" --get-regexp '\.path$' | awk '{print $2}')"
fi

echo "🔄 [更新 repo] 开始"
echo "   目录: $REPO_ROOT"
echo "   分支: $CURRENT_BRANCH"
echo "   submodule: ${SUBMODULES:-无}"

# ============= 1. 拉取远程（总是） =============
echo ""
echo "⬇️ 步骤 1/5：拉取远程"

# 1a. 主仓库 stash
MAIN_STASHED=0
if ! git diff --quiet --ignore-submodules || ! git diff --cached --quiet --ignore-submodules || [ -n "$(git ls-files --others --exclude-standard)" ]; then
  echo "   主仓库有改动，先 stash..."
  git stash push -u -m "update-repo:auto-stash"
  MAIN_STASHED=1
else
  echo "   主仓库工作区干净，无需 stash"
fi

# 1b. Submodule stash（逐个）；用 SM_STASHED_LIST 记录被 stash 的 path
SM_STASHED_LIST=""
for sm_path in $SUBMODULES; do
  if [ -d "$REPO_ROOT/$sm_path/.git" ] || [ -f "$REPO_ROOT/$sm_path/.git" ]; then
    cd "$REPO_ROOT/$sm_path"
    if ! git diff --quiet || ! git diff --cached --quiet || [ -n "$(git ls-files --others --exclude-standard)" ]; then
      echo "   submodule [$sm_path] 有改动，先 stash..."
      git stash push -u -m "update-repo:auto-stash"
      SM_STASHED_LIST="$SM_STASHED_LIST $sm_path"
    fi
    cd "$REPO_ROOT"
  fi
done

# 1c. 主仓库 pull
if ! git pull origin "$CURRENT_BRANCH" --ff-only; then
  echo "❌ git pull origin $CURRENT_BRANCH --ff-only 失败" >&2
  if [ "$MAIN_STASHED" -eq 1 ]; then
    echo "   恢复主仓库 stash..."
    git stash pop || true
  fi
  # 恢复 submodule stash
  for sm_path in $SM_STASHED_LIST; do
    cd "$REPO_ROOT/$sm_path" && git stash pop || true && cd "$REPO_ROOT"
  done
  exit 1
fi

# 1d. 恢复主仓库 stash
if [ "$MAIN_STASHED" -eq 1 ]; then
  echo "   恢复主仓库 stash..."
  if ! git stash pop; then
    echo "⚠️ 主仓库 stash pop 冲突，以本地为准"
    git checkout --ours .
    git add -A
  fi
fi

# ============= 2. 更新 submodule（有 submodule 时） =============
echo ""
echo "📦 步骤 2/5：更新 submodule"

if [ -n "$SUBMODULES" ]; then
  echo "   同步 submodule..."
  if ! git submodule update --init --recursive; then
    echo "⚠️ submodule update 失败，继续处理后续步骤" >&2
  fi

  # 恢复 submodule stash（逐个）
  for sm_path in $SM_STASHED_LIST; do
    echo "   恢复 submodule [$sm_path] stash..."
    cd "$REPO_ROOT/$sm_path"
    if ! git stash pop; then
      echo "⚠️ submodule [$sm_path] stash pop 冲突，以本地为准"
      git checkout --ours .
      git add -A
    fi
    cd "$REPO_ROOT"
  done
else
  echo "   无 submodule，跳过"
fi

# ============= 3. 解压根目录包（有时） =============
echo ""
echo "📦 步骤 3/5：检测并解压根目录压缩包"

ARCHIVES=""
ARCHIVES="$(find . -maxdepth 1 -type f \( -name "*.tar" -o -name "*.tar.gz" -o -name "*.tgz" -o -name "*.zip" \) | sort)" || true

if [ -z "$ARCHIVES" ]; then
  echo "   根目录无压缩包，跳过"
else
  for f in $ARCHIVES; do
    echo "   解压: $f"
    case "$f" in
      *.tar)
        tar -xf "$f" ;;
      *.tar.gz|*.tgz)
        tar -xzf "$f" ;;
      *.zip)
        unzip -o "$f" ;;
      *)
        echo "   ⚠️ 不支持的格式: $f，跳过"
        continue
        ;;
    esac
    rm "$f"
    echo "      已解压并删除"
  done
fi

# ============= 4. 解冲突（有冲突时） =============
echo ""
echo "🔀 步骤 4/5：检查冲突"

if grep -rl "^<<<<<<<" --include="*" . 2>/dev/null | head -1 | grep -q .; then
  echo "   检测到冲突，pull 冲突以远程为准"
  git checkout --theirs .
  git add -A
else
  echo "   无冲突"
fi

# ============= 5. 提交推送（有改动时） =============
echo ""
echo "📤 步骤 5/5：检查并提交推送"

# 5a. Submodule 层
if [ -n "$SUBMODULES" ]; then
  echo "   检查 submodule 改动..."
  for sm_path in $SUBMODULES; do
    cd "$REPO_ROOT/$sm_path"
    SM_BRANCH="$(git branch --show-current)"
    if ! git diff --quiet || ! git diff --cached --quiet || [ -n "$(git ls-files --others --exclude-standard)" ]; then
      echo "   [$sm_path] 有改动，提交并推送 (branch=$SM_BRANCH)..."
      git add -A
      git commit -m "sync: 更新 repo" || echo "      无需提交（可能无改动）"
      git push origin "$SM_BRANCH" || echo "   ⚠️ [$sm_path] push 失败，继续"
    else
      echo "   [$sm_path] 无改动"
    fi
    cd "$REPO_ROOT"
  done
fi

# 5b. 主仓库层
echo "   检查主仓库改动..."
if git diff --quiet --ignore-submodules && git diff --cached --quiet --ignore-submodules && [ -z "$(git ls-files --others --exclude-standard)" ]; then
  echo "   主仓库无改动，无需提交"
else
  echo "   主仓库有改动，准备提交..."
  git add -A
  git commit -m "sync: 更新 repo"
  git push origin "$CURRENT_BRANCH"
  echo "   ✅ 已推送到 origin/$CURRENT_BRANCH"
fi

echo ""
echo "✅ [更新 repo] 完成"
