#!/usr/bin/env bash
# 【更新 repo】命令脚本
# 一键：拉取远程 → 解压根目录包 → 处理冲突 → 提交推送

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$REPO_ROOT"

echo "🔄 [更新 repo] 开始"
echo "   目录: $REPO_ROOT"
echo "   分支: $(git branch --show-current)"

# ============= 1. 拉取远程（总是） =============
echo ""
echo "⬇️ 步骤 1/4：拉取远程"

PULL_STASHED=0
if ! git diff --quiet --ignore-submodules || ! git diff --cached --quiet --ignore-submodules || [ -n "$(git ls-files --others --exclude-standard)" ]; then
  echo "   本地有改动，先 stash..."
  git stash push -u -m "update-repo:auto-stash"
  PULL_STASHED=1
else
  echo "   工作区干净，无需 stash"
fi

CURRENT_BRANCH="$(git branch --show-current)"

if ! git pull origin "$CURRENT_BRANCH" --ff-only; then
  echo "❌ git pull origin $CURRENT_BRANCH --ff-only 失败" >&2
  if [ "$PULL_STASHED" -eq 1 ]; then
    echo "   恢复自动 stash..."
    git stash pop || true
  fi
  exit 1
fi

if [ "$PULL_STASHED" -eq 1 ]; then
  echo "   恢复 stash..."
  if ! git stash pop; then
    echo "⚠️ stash pop 产生冲突，stash 冲突以本地为准"
    # stash 冲突：以本地(ours)为准
    git checkout --ours .
    git add -A
  fi
fi

# ============= 2. 解压根目录包（有时） =============
echo ""
echo "📦 步骤 2/4：检测并解压根目录压缩包"

ARCHIVES=()
while IFS= read -r line; do
  [ -n "$line" ] && ARCHIVES+=("$line")
done < <(find . -maxdepth 1 -type f \( -name "*.tar" -o -name "*.tar.gz" -o -name "*.tgz" -o -name "*.zip" \) | sort)

if [ ${#ARCHIVES[@]} -eq 0 ]; then
  echo "   根目录无压缩包，跳过"
else
  for f in "${ARCHIVES[@]}"; do
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

# ============= 3. 解冲突（有冲突时） =============
echo ""
echo "🔀 步骤 3/4：检查冲突"

if grep -rl "^<<<<<<<" --include="*" . 2>/dev/null | head -1 | grep -q .; then
  echo "   检测到冲突，pull 冲突以远程为准"
  git checkout --theirs .
  git add -A
else
  echo "   无冲突"
fi

# ============= 4. 提交推送（有改动时） =============
echo ""
echo "📤 步骤 4/4：检查并提交推送"

if git diff --quiet --ignore-submodules && git diff --cached --quiet --ignore-submodules && [ -z "$(git ls-files --others --exclude-standard)" ]; then
  echo "   工作区无改动，无需提交"
else
  echo "   检测到改动，准备提交..."
  git add -A
  git commit -m "sync: 更新 repo"
  git push origin "$CURRENT_BRANCH"
  echo "   ✅ 已推送到 origin/$CURRENT_BRANCH"
fi

echo ""
echo "✅ [更新 repo] 完成"
