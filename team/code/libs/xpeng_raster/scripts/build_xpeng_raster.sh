#!/usr/bin/env bash
set -euo pipefail

ROOT="/workspace/yangxh7@xiaopeng.com/codes/DockerInstallers/251112_with_hil_pkg/xpeng_raster/"
PYTHON_BIN="${PYTHON:-python}"

# Fast math default on; override: XPR_FAST_MATH=0 scripts/build_xpeng_raster.sh
export XPR_FAST_MATH="${XPR_FAST_MATH:-1}"

cd "$ROOT"
"$PYTHON_BIN" setup.py build_ext --inplace

"$PYTHON_BIN" -m pip install .
