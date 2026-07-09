#!/usr/bin/env python3
"""从 NotoSansCJK-Bold.ttc 提取 SC 字面为单体 ttf，供 satori 使用。"""
from fontTools.ttLib import TTCollection
import sys

SRC = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
OUT = "/workspace/team/scripts/fonts/NotoSansCJKsc-Bold.ttf"

import os
os.makedirs(os.path.dirname(OUT), exist_ok=True)

coll = TTCollection(SRC)
target = None
for font in coll.fonts:
    name = font["name"]
    # find SC face
    fam = name.getDebugName(1) or ""
    if "SC" in fam and "Mono" not in fam:
        target = font
        print(f"picked: {fam}")
        break
if target is None:
    target = coll.fonts[0]
    print("fallback to first face")
target.save(OUT)
print(f"saved -> {OUT}")
