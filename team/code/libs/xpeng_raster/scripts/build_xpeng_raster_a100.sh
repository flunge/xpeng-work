#!/usr/bin/env bash
set -euo pipefail

# Workspace root of xpeng_raster
ROOT="/workspace/yangxh7@xiaopeng.com/codes/DockerInstallers/251112_with_hil_pkg/xpeng_raster/"
PYTHON_BIN="${PYTHON:-python}"

# GPU arch for NVIDIA A100 (SM 80). Allow override via env.
export TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-8.0}"
# Ensure CUDA build is forced even if torch thinks otherwise.
export FORCE_CUDA="${FORCE_CUDA:-1}"
# CUDA toolkit location (used by torch cpp_extension)
export CUDA_HOME="${CUDA_HOME:-/usr/local/cuda}"
# Parallel build jobs for ninja
export MAX_JOBS="${MAX_JOBS:-$(command -v nproc >/dev/null 2>&1 && nproc || echo 1)}"
# Fast math default on; override: XPR_FAST_MATH=0
export XPR_FAST_MATH="${XPR_FAST_MATH:-1}"

echo "[build] ROOT=$ROOT"
echo "[build] PYTHON_BIN=$PYTHON_BIN"
echo "[build] CUDA_HOME=$CUDA_HOME"
echo "[build] TORCH_CUDA_ARCH_LIST=$TORCH_CUDA_ARCH_LIST"
echo "[build] MAX_JOBS=$MAX_JOBS"
echo "[build] XPR_FAST_MATH=$XPR_FAST_MATH"

cd "$ROOT"

# Optional full clean: CLEAN=1 scripts/build_xpeng_raster_a100.sh
if [[ "${CLEAN:-0}" == "1" ]]; then
  echo "[build] cleaning previous builds..."
  "$PYTHON_BIN" setup.py clean --all || true
  rm -rf build/ xpeng_raster/_C.*.so 2>/dev/null || true
fi

echo "[build] building extension in-place..."
"$PYTHON_BIN" setup.py build_ext --inplace

# Install mode: EDITABLE=1 for editable, default standard install
if [[ "${EDITABLE:-0}" == "1" ]]; then
  echo "[build] installing (editable)..."
  SETUPTOOLS_ENABLE_FEATURES=legacy-editable "$PYTHON_BIN" setup.py develop
else
  echo "[build] installing..."
  "$PYTHON_BIN" -m pip install .
fi

echo "[build] done."


