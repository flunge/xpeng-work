# -*- coding: utf-8 -*-
"""
离线把官方 XPENG SVG 字标栅格化为透明背景 PNG（无需 cairosvg/inkscape）。
自带：路径 d 解析（M/L/H/V/C/S/Q/T/Z 及相对命令）+ 贝塞尔展开 + even-odd 填充（子路径掩码 XOR）。
输出 assets_gen/logo_white.png（白色，透明底）与 logo_dim.png（浅灰 #ECF1F9）。
"""
import os, re
from PIL import Image, ImageDraw, ImageChops

HERE = os.path.dirname(os.path.abspath(__file__))
SVG = os.path.join(HERE, "..", "..", "..", "Xpeng_idRKkKM7yR_0.svg")  # /workspace 根
OUT = os.path.join(HERE, "assets_gen")
os.makedirs(OUT, exist_ok=True)

VBW, VBH = 625.6, 75.0
SCALE = 6  # 渲染倍率


def read_path_d():
    txt = open(SVG, "r", encoding="utf-8").read()
    m = re.search(r'\bd="([^"]+)"', txt, re.S)
    if not m:
        raise RuntimeError("path d not found")
    return m.group(1)


def tokenize(d):
    return re.findall(r"[MmLlHhVvCcSsQqTtZz]|-?\d*\.?\d+(?:[eE]-?\d+)?", d)


def cubic(p0, p1, p2, p3, n=24):
    pts = []
    for i in range(1, n + 1):
        t = i / n; u = 1 - t
        x = u**3*p0[0] + 3*u*u*t*p1[0] + 3*u*t*t*p2[0] + t**3*p3[0]
        y = u**3*p0[1] + 3*u*u*t*p1[1] + 3*u*t*t*p2[1] + t**3*p3[1]
        pts.append((x, y))
    return pts


def quad(p0, p1, p2, n=20):
    pts = []
    for i in range(1, n + 1):
        t = i / n; u = 1 - t
        x = u*u*p0[0] + 2*u*t*p1[0] + t*t*p2[0]
        y = u*u*p0[1] + 2*u*t*p1[1] + t*t*p2[1]
        pts.append((x, y))
    return pts


def parse_subpaths(d):
    toks = tokenize(d)
    i = 0
    cx = cy = sx = sy = 0.0
    subs = []
    cur = []
    cmd = None
    prev_cc = None   # 上一个三次控制点（用于 S）
    prev_qc = None   # 上一个二次控制点（用于 T）

    def num():
        nonlocal i
        v = float(toks[i]); i += 1; return v

    while i < len(toks):
        t = toks[i]
        if re.match(r"[A-Za-z]", t):
            cmd = t; i += 1
        # 处理命令
        if cmd in ("M", "m"):
            x = num(); y = num()
            if cmd == "m": x += cx; y += cy
            if cur: subs.append(cur)
            cur = [(x, y)]
            cx, cy = x, y; sx, sy = x, y
            cmd = "L" if cmd == "M" else "l"
            prev_cc = prev_qc = None
        elif cmd in ("L", "l"):
            x = num(); y = num()
            if cmd == "l": x += cx; y += cy
            cur.append((x, y)); cx, cy = x, y; prev_cc = prev_qc = None
        elif cmd in ("H", "h"):
            x = num()
            if cmd == "h": x += cx
            cur.append((x, cy)); cx = x; prev_cc = prev_qc = None
        elif cmd in ("V", "v"):
            y = num()
            if cmd == "v": y += cy
            cur.append((cx, y)); cy = y; prev_cc = prev_qc = None
        elif cmd in ("C", "c"):
            x1 = num(); y1 = num(); x2 = num(); y2 = num(); x = num(); y = num()
            if cmd == "c":
                x1 += cx; y1 += cy; x2 += cx; y2 += cy; x += cx; y += cy
            cur += cubic((cx, cy), (x1, y1), (x2, y2), (x, y))
            prev_cc = (x2, y2); cx, cy = x, y; prev_qc = None
        elif cmd in ("S", "s"):
            x2 = num(); y2 = num(); x = num(); y = num()
            if cmd == "s":
                x2 += cx; y2 += cy; x += cx; y += cy
            x1, y1 = (2*cx - prev_cc[0], 2*cy - prev_cc[1]) if prev_cc else (cx, cy)
            cur += cubic((cx, cy), (x1, y1), (x2, y2), (x, y))
            prev_cc = (x2, y2); cx, cy = x, y; prev_qc = None
        elif cmd in ("Q", "q"):
            x1 = num(); y1 = num(); x = num(); y = num()
            if cmd == "q":
                x1 += cx; y1 += cy; x += cx; y += cy
            cur += quad((cx, cy), (x1, y1), (x, y))
            prev_qc = (x1, y1); cx, cy = x, y; prev_cc = None
        elif cmd in ("T", "t"):
            x = num(); y = num()
            if cmd == "t": x += cx; y += cy
            x1, y1 = (2*cx - prev_qc[0], 2*cy - prev_qc[1]) if prev_qc else (cx, cy)
            cur += quad((cx, cy), (x1, y1), (x, y))
            prev_qc = (x1, y1); cx, cy = x, y; prev_cc = None
        elif cmd in ("Z", "z"):
            if cur:
                cur.append((sx, sy)); subs.append(cur); cur = []
            cx, cy = sx, sy; prev_cc = prev_qc = None
        else:
            i += 1
    if cur:
        subs.append(cur)
    return subs


def rasterize(color, name):
    subs = parse_subpaths(read_path_d())
    W, H = int(VBW * SCALE), int(VBH * SCALE)
    acc = Image.new("1", (W, H), 0)
    for sp in subs:
        if len(sp) < 3:
            continue
        m = Image.new("1", (W, H), 0)
        ImageDraw.Draw(m).polygon([(x*SCALE, y*SCALE) for x, y in sp], fill=1)
        acc = ImageChops.logical_xor(acc, m)
    # 抗锯齿：高分辨率掩码缩小
    alpha = acc.convert("L").resize((W // 3, H // 3), Image.LANCZOS)
    out = Image.new("RGBA", alpha.size, color + (0,))
    solid = Image.new("RGBA", alpha.size, color + (255,))
    out = Image.composite(solid, out, alpha)
    p = os.path.join(OUT, name)
    out.save(p, "PNG")
    print("  ->", name, out.size, "subpaths:", len(subs))


if __name__ == "__main__":
    rasterize((255, 255, 255), "logo_white.png")
    rasterize((236, 241, 249), "logo_dim.png")
    print("done.")
