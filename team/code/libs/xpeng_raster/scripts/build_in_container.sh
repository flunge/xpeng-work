#!/usr/bin/env bash
set -euo pipefail

# Usage examples:
#   bash scripts/build_in_container.sh
#   TORCH_CUDA_ARCH_LIST=8.0 bash scripts/build_in_container.sh
#   TORCH_SPEC="torch==2.3.1+cu121 torchvision==0.18.1+cu121" \
#   TORCH_INDEX_URL="https://download.pytorch.org/whl/cu121" \
#     bash scripts/build_in_container.sh
#   CLEAN=1 EDITABLE=1 bash scripts/build_in_container.sh
#
# Env vars:
#   PYTHON (default: python3)
#   TORCH_SPEC (optional, e.g. "torch==2.3.1+cu121 torchvision==0.18.1+cu121")
#   TORCH_INDEX_URL (optional, e.g. "https://download.pytorch.org/whl/cu121")
#   TORCH_CUDA_ARCH_LIST (optional, e.g. 8.0 for A100)
#   FORCE_CUDA (default: 1)
#   CUDA_HOME (default: /usr/local/cuda)
#   XPR_FAST_MATH (default: 1)
#   CLEAN (default: 1) - full clean before build
#   EDITABLE (default: 0) - install in editable mode when 1
#   MAX_JOBS (default: nproc)

PYTHON_BIN="${PYTHON:-python3}"
TORCH_SPEC="${TORCH_SPEC:-}"
TORCH_INDEX_URL="${TORCH_INDEX_URL:-}"
export TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-}"
export FORCE_CUDA="${FORCE_CUDA:-1}"
export CUDA_HOME="${CUDA_HOME:-/usr/local/cuda}"
export XPR_FAST_MATH="${XPR_FAST_MATH:-1}"
CLEAN="${CLEAN:-1}"
EDITABLE="${EDITABLE:-0}"
export MAX_JOBS="${MAX_JOBS:-$(command -v nproc >/dev/null 2>&1 && nproc || echo 1)}"

# Ensure CUDA lib64 appears first to avoid compat libs taking precedence
if [[ ":${LD_LIBRARY_PATH:-}:" != *":/usr/local/cuda/lib64:"* ]]; then
  export LD_LIBRARY_PATH="/usr/local/cuda/lib64:${LD_LIBRARY_PATH:-}"
fi
# Remove any cuda/compat entries to avoid loading compat libs at runtime
if [[ -n "${LD_LIBRARY_PATH:-}" ]]; then
  IFS=':' read -r -a __ldarr <<< "$LD_LIBRARY_PATH"
  __filtered=()
  for p in "${__ldarr[@]}"; do
    if [[ "$p" != *"/cuda/compat"* ]]; then
      __filtered+=("$p")
    fi
  done
  export LD_LIBRARY_PATH="$(IFS=':'; echo "${__filtered[*]}")"
fi

echo "[env] PYTHON_BIN=$PYTHON_BIN"
echo "[env] CUDA_HOME=$CUDA_HOME"
echo "[env] FORCE_CUDA=$FORCE_CUDA"
echo "[env] XPR_FAST_MATH=$XPR_FAST_MATH"
echo "[env] TORCH_CUDA_ARCH_LIST=${TORCH_CUDA_ARCH_LIST:-<unset>}"
echo "[env] MAX_JOBS=$MAX_JOBS"
echo "[env] TORCH_SPEC=${TORCH_SPEC:-<unset>}"
echo "[env] TORCH_INDEX_URL=${TORCH_INDEX_URL:-<unset>}"


if [[ -n "$TORCH_SPEC" ]]; then
  echo "[python] installing specified torch: $TORCH_SPEC"
  if [[ -n "$TORCH_INDEX_URL" ]]; then
    "$PYTHON_BIN" -m pip install --no-cache-dir --index-url "$TORCH_INDEX_URL" $TORCH_SPEC
  else
    "$PYTHON_BIN" -m pip install --no-cache-dir $TORCH_SPEC
  fi
fi

echo "[python] torch runtime info:"
"$PYTHON_BIN" - <<'PY'
import torch, sys
print("[torch] version:", getattr(torch, "__version__", None))
print("[torch] cuda:", getattr(getattr(torch, "version", None), "cuda", None))
print("[torch] cuda_is_available:", torch.cuda.is_available() if hasattr(torch, "cuda") else None)
PY

# Locate xpeng_raster project root (this script resides in xpeng_raster/scripts)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$ROOT"

if [[ "$CLEAN" == "1" ]]; then
  echo "[build] cleaning previous builds..."
  "$PYTHON_BIN" setup.py clean --all || true
  rm -rf build/ xpeng_raster/_C.*.so 2>/dev/null || true
fi

echo "[build] building extension in-place..."
"$PYTHON_BIN" setup.py build_ext --inplace

if [[ "$EDITABLE" == "1" ]]; then
  echo "[install] installing (editable)..."
  SETUPTOOLS_ENABLE_FEATURES=legacy-editable "$PYTHON_BIN" setup.py develop
else
  echo "[install] installing..."
  "$PYTHON_BIN" -m pip install --no-cache-dir --no-build-isolation .
fi

echo "[build] done."


