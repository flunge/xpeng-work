# -*- coding: utf-8 -*-
"""
程序化生成符合主题（自动驾驶仿真 / 3DGS 点云 / 世界模型 / HUD）的科技风配图。
全部离线用 PIL 绘制，深色 HUD 风格，橙(#FF8C28)/青(#4FB6FF) 主色，
输出到 assets_gen/ 供 PPT 引用。所有图均偏暗，作为有界配图面板，保证叠加文字可读。
"""
import os, math, random
from PIL import Image, ImageDraw, ImageFilter

OUT = os.path.join(os.path.dirname(__file__), "assets_gen")
os.makedirs(OUT, exist_ok=True)

BG1 = (10, 14, 24)
BG2 = (5, 8, 15)
ORANGE = (255, 140, 40)
CYAN = (79, 182, 255)
GREEN = (63, 214, 140)
GRID = (120, 150, 190)
RED = (255, 107, 107)


def base(w, h, vignette=True):
    img = Image.new("RGB", (w, h), BG2)
    px = img.load()
    for y in range(h):
        t = y / h
        r = int(BG1[0] * (1 - t) + BG2[0] * t)
        g = int(BG1[1] * (1 - t) + BG2[1] * t)
        b = int(BG1[2] * (1 - t) + BG2[2] * t)
        for x in range(w):
            px[x, y] = (r, g, b)
    return img


def add_grid(img, step=48, color=GRID, alpha=16):
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    w, h = img.size
    for x in range(0, w, step):
        d.line([(x, 0), (x, h)], fill=color + (alpha,), width=1)
    for y in range(0, h, step):
        d.line([(0, y), (w, y)], fill=color + (alpha,), width=1)
    img.paste(Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB"), (0, 0))


def glow_dots(img, dots, blur=6):
    """dots: [(x,y,r,color,alpha)] 带辉光的点。"""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for x, y, r, c, a in dots:
        d.ellipse([x - r, y - r, x + r, y + r], fill=c + (a,))
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    core = Image.new("RGBA", img.size, (0, 0, 0, 0))
    dc = ImageDraw.Draw(core)
    for x, y, r, c, a in dots:
        rr = max(1, r // 3)
        dc.ellipse([x - rr, y - rr, x + rr, y + rr], fill=c + (min(255, a + 80),))
    out = Image.alpha_composite(img.convert("RGBA"), layer)
    out = Image.alpha_composite(out, core)
    return out.convert("RGB")


def save(img, name):
    p = os.path.join(OUT, name)
    img.save(p, "PNG")
    print("  ->", name, img.size)


# ---------------- 1. 封面：道路透视 + 点云粒子 ----------------
def cover(w=1600, h=1000):
    random.seed(7)
    img = base(w, h)
    add_grid(img, 54, alpha=12)
    d = ImageDraw.Draw(img, "RGBA")
    # 道路透视线（消失点）
    vx, vy = int(w * 0.5), int(h * 0.42)
    for off in range(-7, 8):
        x0 = int(w * 0.5 + off * w * 0.09)
        d.line([(x0, h), (vx, vy)], fill=CYAN + (38,), width=2)
    for i in range(1, 9):           # 横向地平线网格
        yy = vy + (h - vy) * (i / 9) ** 1.7
        d.line([(0, yy), (w, yy)], fill=CYAN + (28,), width=1)
    # 高斯点云粒子
    dots = []
    for _ in range(420):
        x = random.randint(0, w); y = random.randint(vy - 40, h)
        depth = (y - vy) / (h - vy + 1)
        r = max(1, int(2 + depth * 6))
        c = ORANGE if random.random() < 0.32 else CYAN
        a = int(60 + depth * 150)
        dots.append((x, y, r, c, a))
    img = glow_dots(img, dots, blur=5)
    # 顶部光晕
    halo = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse([vx - 380, vy - 320, vx + 380, vy + 120],
                                 fill=ORANGE + (26,))
    img = Image.alpha_composite(img.convert("RGBA"),
                                halo.filter(ImageFilter.GaussianBlur(70))).convert("RGB")
    save(img, "cover.png")


# ---------------- 2. 章节分隔配图（4 个，带不同母题）----------------
def divider(idx, accent, motif, w=1400, h=900):
    random.seed(20 + idx)
    img = base(w, h)
    add_grid(img, 50, alpha=14)
    d = ImageDraw.Draw(img, "RGBA")
    dots = []
    if motif == "crisis":          # 背景：断裂/警示散点
        for _ in range(220):
            x = random.randint(0, w); y = random.randint(0, h)
            dots.append((x, y, random.randint(1, 4),
                         ORANGE if random.random() < 0.5 else accent,
                         random.randint(40, 150)))
        for _ in range(18):        # 断裂线
            x0 = random.randint(0, w); y0 = random.randint(0, h)
            d.line([(x0, y0), (x0 + random.randint(-120, 120),
                                y0 + random.randint(-90, 90))],
                   fill=accent + (50,), width=2)
    elif motif == "evolution":     # 演进：阶梯上升节点
        n = 5
        for i in range(n):
            cx = int(w * (0.12 + i * 0.19)); cy = int(h * (0.8 - i * 0.13))
            if i:
                d.line([(px_, py_), (cx, cy)], fill=accent + (90,), width=3)
            d.ellipse([cx - 16, cy - 16, cx + 16, cy + 16],
                      outline=accent + (220,), width=3)
            px_, py_ = cx, cy
            dots.append((cx, cy, 22, accent, 120))
        for _ in range(160):
            dots.append((random.randint(0, w), random.randint(0, h),
                         random.randint(1, 3), accent, random.randint(30, 90)))
    elif motif == "framework":     # 现状：网格/拓扑节点
        nodes = [(int(w * x), int(h * y)) for x, y in
                 [(0.5, 0.5), (0.25, 0.3), (0.75, 0.3), (0.25, 0.72),
                  (0.75, 0.72), (0.12, 0.5), (0.88, 0.5)]]
        for a in nodes[1:]:
            d.line([nodes[0], a], fill=accent + (70,), width=2)
        for nx, ny in nodes:
            d.ellipse([nx - 12, ny - 12, nx + 12, ny + 12],
                      outline=accent + (210,), width=3)
            dots.append((nx, ny, 18, accent, 110))
        for _ in range(140):
            dots.append((random.randint(0, w), random.randint(0, h),
                         random.randint(1, 3), CYAN, random.randint(30, 80)))
    else:                          # future：辐射/生成
        cx, cy = int(w * 0.5), int(h * 0.5)
        for rr in range(60, 460, 60):
            d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                      outline=accent + (40,), width=2)
        for ang in range(0, 360, 18):
            a = math.radians(ang)
            d.line([(cx, cy), (cx + math.cos(a) * 460, cy + math.sin(a) * 460)],
                   fill=accent + (28,), width=1)
        for _ in range(220):
            ang = random.uniform(0, 2 * math.pi); rad = random.uniform(0, 440)
            dots.append((int(cx + math.cos(ang) * rad), int(cy + math.sin(ang) * rad),
                         random.randint(1, 4), accent if random.random() < 0.6 else ORANGE,
                         random.randint(40, 160)))
    img = glow_dots(img, dots, blur=5)
    save(img, f"div{idx}.png")


# ---------------- 3. 3DGS 点云重建 ----------------
def splat(w=1000, h=760):
    random.seed(3)
    img = base(w, h)
    add_grid(img, 46, alpha=12)
    # 车形轮廓（中心高密度点簇）
    dots = []
    cx, cy = w * 0.5, h * 0.56
    for _ in range(900):
        a = random.uniform(0, 2 * math.pi)
        rad = abs(random.gauss(0, 1)) * 150
        x = cx + math.cos(a) * rad * 1.6
        y = cy + math.sin(a) * rad * 0.8
        if 0 <= x < w and 0 <= y < h:
            col = ORANGE if random.random() < 0.35 else CYAN
            dots.append((int(x), int(y), random.randint(1, 4), col,
                         random.randint(70, 200)))
    for _ in range(260):
        dots.append((random.randint(0, w), random.randint(0, h),
                     random.randint(1, 3), CYAN, random.randint(30, 90)))
    img = glow_dots(img, dots, blur=4)
    save(img, "splat.png")


# ---------------- 4. 世界模型：生成式辐射球 ----------------
def world(w=1000, h=760):
    random.seed(11)
    img = base(w, h)
    add_grid(img, 46, alpha=12)
    d = ImageDraw.Draw(img, "RGBA")
    cx, cy = w // 2, h // 2
    for rr in range(40, 340, 38):
        d.ellipse([cx - rr, cy - int(rr * 0.62), cx + rr, cy + int(rr * 0.62)],
                  outline=CYAN + (60,), width=2)
    for rr in range(40, 340, 38):
        d.ellipse([cx - int(rr * 0.62), cy - rr, cx + int(rr * 0.62), cy + rr],
                  outline=ORANGE + (45,), width=2)
    dots = [(cx, cy, 60, CYAN, 120)]
    for _ in range(260):
        ang = random.uniform(0, 2 * math.pi); rad = random.uniform(0, 320)
        dots.append((int(cx + math.cos(ang) * rad), int(cy + math.sin(ang) * rad * 0.7),
                     random.randint(1, 4), CYAN if random.random() < 0.6 else ORANGE,
                     random.randint(40, 150)))
    img = glow_dots(img, dots, blur=6)
    save(img, "world.png")


def _arrowhead(d, x, y, ang, c, size=14):
    a = ang
    p1 = (x, y)
    p2 = (x - size * math.cos(a - 0.4), y - size * math.sin(a - 0.4))
    p3 = (x - size * math.cos(a + 0.4), y - size * math.sin(a + 0.4))
    d.polygon([p1, p2, p3], fill=c + (230,))


# ---------------- 5. NeRF（隐式模糊） vs 3DGS（显式点云） ----------------
def nerf3dgs(w=1120, h=620):
    random.seed(5)
    img = base(w, h); add_grid(img, 44, alpha=12)
    half = w // 2
    # 左：NeRF 隐式 —— 模糊大色块
    soft = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ds = ImageDraw.Draw(soft)
    cx, cy = half // 2, h // 2
    for _ in range(60):
        x = cx + random.randint(-150, 150); y = cy + random.randint(-130, 130)
        r = random.randint(40, 90)
        ds.ellipse([x - r, y - r, x + r, y + r], fill=CYAN + (22,))
    soft = soft.filter(ImageFilter.GaussianBlur(22))
    img = Image.alpha_composite(img.convert("RGBA"), soft).convert("RGB")
    d = ImageDraw.Draw(img, "RGBA")
    d.line([(half, 30), (half, h - 30)], fill=GRID + (60,), width=2)
    # 右：3DGS 显式 —— 清晰点云
    dots = []
    rcx, rcy = half + half // 2, h // 2
    for _ in range(620):
        a = random.uniform(0, 2 * math.pi); rad = abs(random.gauss(0, 1)) * 120
        x = rcx + math.cos(a) * rad * 1.4; y = rcy + math.sin(a) * rad
        if half < x < w and 0 < y < h:
            dots.append((int(x), int(y), random.randint(1, 4),
                         ORANGE if random.random() < 0.4 else CYAN,
                         random.randint(90, 210)))
    img = glow_dots(img, dots, blur=3)
    save(img, "nerf3dgs.png")


# ---------------- 6. 数据飞轮 ----------------
def flywheel(w=860, h=820):
    random.seed(6)
    img = base(w, h); add_grid(img, 44, alpha=12)
    d = ImageDraw.Draw(img, "RGBA")
    cx, cy, R = w // 2, h // 2, 290
    for k in range(3):
        a0 = math.radians(k * 120 + 8); a1 = math.radians((k + 1) * 120 - 18)
        d.arc([cx - R, cy - R, cx + R, cy + R],
              math.degrees(a0), math.degrees(a1), fill=CYAN + (180,), width=8)
        ex, ey = cx + R * math.cos(a1), cy + R * math.sin(a1)
        _arrowhead(d, ex, ey, a1 + math.pi / 2, ORANGE, 22)
    dots = [(cx, cy, 70, ORANGE, 120)]
    for k in range(3):
        a = math.radians(k * 120 - 90)
        nx, ny = cx + R * math.cos(a), cy + R * math.sin(a)
        d.ellipse([nx - 26, ny - 26, nx + 26, ny + 26], outline=CYAN + (230,), width=4)
        dots.append((int(nx), int(ny), 34, CYAN, 130))
    img = glow_dots(img, dots, blur=6)
    save(img, "flywheel.png")


# ---------------- 7. 协变量偏移：参考轨迹 vs 偏移发散 ----------------
def drift(w=1120, h=540):
    random.seed(9)
    img = base(w, h); add_grid(img, 42, alpha=12)
    d = ImageDraw.Draw(img, "RGBA")
    y0 = int(h * 0.4)
    for x in range(60, w - 60, 22):          # 参考轨迹（青，虚线）
        d.line([(x, y0), (x + 11, y0)], fill=CYAN + (170,), width=4)
    pts = []                                  # 偏移轨迹（橙，发散）
    for i in range(0, w - 120):
        x = 60 + i
        y = y0 + (i / (w - 180)) ** 2 * (h * 0.46)
        pts.append((x, y))
    d.line(pts, fill=ORANGE + (220,), width=5)
    # 发散间隙阴影
    gap = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(gap).polygon([(60, y0)] + pts[::6] + [(pts[-1][0], y0)],
                                fill=ORANGE + (26,))
    img = Image.alpha_composite(img.convert("RGBA"), gap).convert("RGB")
    d = ImageDraw.Draw(img, "RGBA")
    ex, ey = pts[-1]
    for dd in (-16, 16):                      # 崩溃 X
        d.line([(ex - 18, ey + dd - 16), (ex + 18, ey - dd + 16)], fill=RED + (240,), width=6)
    d.ellipse([ex - 30, ey - 30, ex + 30, ey + 30], outline=RED + (220,), width=4)
    save(img, "drift.png")


# ---------------- 8. Agent 网络 ----------------
def agents(w=1120, h=600):
    random.seed(13)
    img = base(w, h); add_grid(img, 44, alpha=12)
    d = ImageDraw.Draw(img, "RGBA")
    cx, cy = w // 2, h // 2
    sat = [(int(cx + 300 * math.cos(math.radians(a))),
            int(cy + 200 * math.sin(math.radians(a)))) for a in (200, 320, 90)]
    for s in sat:
        d.line([(cx, cy), s], fill=CYAN + (110,), width=3)
    dots = [(cx, cy, 56, ORANGE, 130)]
    for s in sat:
        d.ellipse([s[0] - 30, s[1] - 30, s[0] + 30, s[1] + 30], outline=CYAN + (230,), width=4)
        dots.append((s[0], s[1], 36, CYAN, 130))
    for _ in range(120):
        dots.append((random.randint(0, w), random.randint(0, h),
                     random.randint(1, 3), CYAN, random.randint(30, 80)))
    img = glow_dots(img, dots, blur=6)
    save(img, "agents.png")


# ---------------- 9. VLM 扫描：道路场景 + 检测框 ----------------
def scan(w=1120, h=620):
    random.seed(17)
    img = base(w, h); add_grid(img, 44, alpha=12)
    d = ImageDraw.Draw(img, "RGBA")
    vx, vy = w // 2, int(h * 0.4)
    for off in range(-4, 5):                  # 道路透视
        d.line([(vx + off * 130, h), (vx, vy)], fill=CYAN + (40,), width=2)
    boxes = [(int(w*0.28), int(h*0.55), int(w*0.42), int(h*0.78), ORANGE, "CUT-IN"),
             (int(w*0.58), int(h*0.5), int(w*0.7), int(h*0.68), CYAN, "VEHICLE"),
             (int(w*0.46), int(h*0.62), int(w*0.55), int(h*0.84), GREEN, "PEDEST.")]
    for x0, y0, x1, y1, c, _ in boxes:
        d.rectangle([x0, y0, x1, y1], outline=c + (230,), width=3)
        for (bx, by) in [(x0, y0), (x1, y0), (x0, y1), (x1, y1)]:  # 角标
            d.line([(bx - 8, by), (bx + 8, by)], fill=c + (255,), width=3)
            d.line([(bx, by - 8), (bx, by + 8)], fill=c + (255,), width=3)
    d.line([(40, int(h*0.5)), (w - 40, int(h*0.5))], fill=CYAN + (120,), width=2)  # 扫描线
    save(img, "scan.png")


if __name__ == "__main__":
    print("generating assets ...")
    cover()
    divider(1, ORANGE, "crisis")
    divider(2, CYAN, "evolution")
    divider(3, GREEN, "framework")
    divider(4, ORANGE, "future")
    splat()
    world()
    nerf3dgs()
    flywheel()
    drift()
    agents()
    scan()
    print("done.")
