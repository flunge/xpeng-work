#!/usr/bin/env python3
"""topic 图 → 飞书画板原生节点。
形状/卡/KPI/标题：SVG→whiteboard-cli --to openapi。
每条 bullet：① 彩色加粗「标签」独立小框（保留格式）② 后面整段内容合成【一个多行可编辑框】。
用法: python3 scripts/push_whiteboard_native.py <topicN> <当前whiteboard_token>
⚠️ token 必须现取（block_replace/新建会换 token），先 docs +fetch 拿 <whiteboard token=...>。"""
import importlib.util, json, subprocess, sys

spec = importlib.util.spec_from_file_location("g", "scripts/gen_svg_infographic.py")
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
WHICH, TOKEN = sys.argv[1], sys.argv[2]

BODIES = []
def _rec(x, y, max_px, items, size=14, lh=22, gap=8):
    BODIES.append((x, y, max_px, list(items), size, lh, gap)); return "", y
g._wbullets = _rec

g._reset_geom()
svg = g.GENERATORS[WHICH]()
open(".nb.svg", "w").write(svg)
subprocess.run(["npx", "-y", "@larksuite/whiteboard-cli@^0.2.12", "-i", ".nb.svg",
                "--to", "openapi", "--format", "json", "-o", ".nb.json"],
               capture_output=True, text=True)
doc = json.load(open(".nb.json")); nodes = doc["nodes"]

def chex(c):
    return {g.WARN: g.WARN, g.ACCENT: g.ACCENT, g.NUM: g.NUM}.get(c, g.TXT)

def tnode(nid, x, y, w, h, text, color, size, bold):
    return {"id": nid, "type": "text_shape", "x": x, "y": y, "width": w, "height": h,
            "text": {"text": text, "font_weight": "bold" if bold else "regular",
                     "font_size": size, "horizontal_align": "left", "vertical_align": "top",
                     "line_through": False, "underline": False, "italic": False, "angle": 0,
                     "text_color": color, "text_color_type": 1,
                     "text_background_color_type": 0, "theme_text_background_color_code": -1}}

bi = 0
for (x, y, max_px, items, size, lh, gap) in BODIES:
    prev = None
    for (mark, color, text) in items:
        indent = (g._tw(mark, size) + 10) if mark else 0
        # 支持源文本里的显式换行 '\n'（表格式/分行）：每段各自按宽折行，再合并
        wl = []
        for _seg in str(text).split("\n"):
            wl += g._wrap(_seg, max_px - indent, size) or [""]
        n = len(wl)
        base = y if prev is None else prev + lh + gap   # 本条首行基线
        top = base - size
        if mark:                                        # ① 彩色加粗标签框
            bi += 1
            nodes.append(tnode(f"lb{WHICH}{bi}", x, top, g._tw(mark, size) + 8,
                               size + 6, mark, chex(color), size, True))
        bi += 1                                         # ② 整段内容一个多行框
        nodes.append(tnode(f"ct{WHICH}{bi}", x + indent, top, max_px - indent + 8,
                           n * lh + 6, "\n".join(wl), g.TXT, size, False))
        prev = base + (n - 1) * lh

json.dump(doc, open(f".nb_{WHICH}.json", "w"), ensure_ascii=False)
r = subprocess.run(["lark-cli", "whiteboard", "+update", "--whiteboard-token", TOKEN,
                    "--source", f"@.nb_{WHICH}.json", "--input_format", "raw",
                    "--idempotent-token", f"nb-{WHICH}-{TOKEN[:6]}-c", "--as", "user", "--overwrite"],
                   capture_output=True, text=True)
print(f"{WHICH}: 节点 {len(nodes)}（含标签+内容框 {bi}）；push:",
      "OK" if '"ok": true' in r.stdout else "FAIL " + r.stdout[:150])
