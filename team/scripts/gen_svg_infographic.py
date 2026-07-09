#!/usr/bin/env python3
"""原生 SVG 信息图生成器（不依赖 satori/HTML，飞书 whiteboard type=svg 直吃）。
深色科技风：标题条 + 分栏卡片 + KPI 数字块 + bullet。手算坐标，无 foreignObject、无全角≤≥、无<br/>。
每个 Topic 一个函数返回自包含 SVG 字符串。"""
import html as _h

W, H = 1024, 576
BG1, BG2 = "#0a1428", "#0d1b30"
CARD = "#1e3a66"
ACCENT = "#4da3ff"
NUM = "#7fd4ff"
TXT = "#e8f0ff"
SUB = "#9fbde0"
WARN = "#ffb86b"
FONT = "Noto Sans CJK SC, PingFang SC, Microsoft YaHei, sans-serif"


def esc(s):
    return _h.escape(str(s), quote=True)


def _txt(x, y, s, size=15, color=TXT, weight="normal", anchor="start"):
    return (f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" '
            f'font-weight="{weight}" text-anchor="{anchor}" '
            f'font-family="{FONT}">{esc(s)}</text>')


def _rect(x, y, w, h, fill, rx=12, stroke="none", sw=0, opacity=1):
    st = f' stroke="{stroke}" stroke-width="{sw}"' if stroke != "none" else ""
    op = f' opacity="{opacity}"' if opacity != 1 else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"{st}{op}/>'


def _header(title, subtitle):
    s = _rect(0, 0, W, H, "url(#bg)", rx=0)
    # 顶部标题区带底部细分隔线
    s += f'<rect x="40" y="30" width="6" height="36" rx="3" fill="url(#accentbar)"/>'
    s += _txt(60, 56, title, size=27, color="#ffffff", weight="bold")
    s += _txt(60, 84, subtitle, size=14.5, color=SUB)
    s += f'<line x1="40" y1="100" x2="{W-40}" y2="100" stroke="#2a4straight" stroke-width="1" opacity="0.25"/>'.replace("#2a4straight", "#3a5f92")
    return s


# 🔴🔴 渲染闸（2026-07-01）：登记每张卡矩形 + 每块 bullet 文字包围盒，
# 生成后几何自检"文字是否越出卡片右/下边界"。纯坐标计算、拦得住溢出，不靠肉眼看缩略图。
_CARDS = []   # [(x,y,w,h,title)]
_BOXES = []   # [(x0,y0,x1,y1,label)] 文字实际包围盒
def _reset_geom():
    _CARDS.clear(); _BOXES.clear()


def _card(x, y, w, h, title):
    # 卡片：深色圆角 + 顶部标题条 + 左侧强调竖条 + 标题下分隔线
    _CARDS.append((x, y, w, h, title))
    s = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="url(#cardgrad)" stroke="#3a6099" stroke-width="1"/>'
    s += f'<rect x="{x}" y="{y}" width="5" height="{h}" rx="2.5" fill="{ACCENT}"/>'
    s += _txt(x + 24, y + 36, title, size=19, color="#bcdcff", weight="bold")
    s += f'<line x1="{x+22}" y1="{y+50}" x2="{x+w-20}" y2="{y+50}" stroke="#3a6099" stroke-width="1" opacity="0.6"/>'
    return s


def _check_overflow(margin=6):
    """几何自检：每块文字包围盒必须落在某张卡内（留 margin）。返回越界清单。"""
    bad = []
    for bx0, by0, bx1, by1, lbl in _BOXES:
        # 找包含该盒左上角的卡
        host = None
        for cx, cy, cw, ch, ct in _CARDS:
            if cx <= bx0 <= cx + cw and cy <= by0 <= cy + ch:
                host = (cx, cy, cw, ch, ct); break
        if not host:
            continue  # 不在任何卡内（如顶部 KPI 带），不管
        cx, cy, cw, ch, ct = host
        if bx1 > cx + cw - margin:
            bad.append(f"横向溢出：「{lbl}」右到 {bx1:.0f} > 卡[{ct}]右界 {cx+cw-margin:.0f}")
        if by1 > cy + ch - margin:
            bad.append(f"纵向溢出：「{lbl}」底到 {by1:.0f} > 卡[{ct}]下界 {cy+ch-margin:.0f}")
    return bad


def _kpi(x, y, w, num, label, h=68):
    # KPI 块：左强调竖条 + 大数字(按宽自适应字号) + 标签(按宽折行)
    s = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" fill="#20486f" stroke="#3f6ea3" stroke-width="0.8"/>'
    s += f'<rect x="{x}" y="{y+12}" width="3.5" height="{h-24}" rx="1.75" fill="{NUM}"/>'
    avail = w - 30
    nsz = 25
    while _tw(num, nsz) > avail and nsz > 15:
        nsz -= 1
    s += _txt(x + 16, y + 33, num, size=nsz, color=NUM, weight="bold")
    # label 折行（最多 2 行）
    for k, ln in enumerate(_wrap(label, avail, 12)[:2]):
        s += _txt(x + 16, y + 52 + k * 15, ln, size=12, color=SUB)
    return s


def _bullets(x, y, items, gap=27):
    s = ""
    for i, (mark, color, text) in enumerate(items):
        yy = y + i * gap
        if mark:
            s += _txt(x, yy, mark, size=14.5, color=color, weight="bold")
        s += _txt(x + (22 if mark else 6), yy, text, size=14, color=(WARN if color == WARN else (NUM if color == NUM else TXT)))
    return s


def _tw(text, size):
    """估算文本像素宽：中文/全角≈size，英数/半角≈size*0.55。"""
    w = 0.0
    for ch in text:
        w += size if ord(ch) > 0x2E7F else size * 0.55
    return w


def _wrap(text, max_px, size):
    """按 max_px 折行，返回行列表。"""
    lines, cur, curw = [], "", 0.0
    for ch in text:
        cw = size if ord(ch) > 0x2E7F else size * 0.55
        if curw + cw > max_px and cur:
            lines.append(cur); cur, curw = ch, cw
        else:
            cur += ch; curw += cw
    if cur:
        lines.append(cur)
    return lines


def _wbullets(x, y, max_px, items, size=14, lh=22, gap=8):
    """自动折行的 bullet：max_px=可用文字宽度。每条按宽折行，行距 lh，条间距 gap。
    items=[(mark,color,text)]，mark 空则纯续行缩进。返回 (svg, 结束 y)。"""
    s, yy = "", y
    for mark, color, text in items:
        col = WARN if color == WARN else (NUM if color == NUM else TXT)
        # 首行文字缩进 = mark 实际宽 + 间隙（避免续行压到 mark）；无 mark 时小缩进
        indent = (_tw(mark, size) + 10) if mark else 12
        lines = _wrap(text, max_px - indent, size)
        for k, ln in enumerate(lines):
            if k == 0 and mark:
                s += _txt(x, yy, mark, size=size, color=color, weight="bold")
            s += _txt(x + indent, yy, ln, size=size, color=col)
            # 登记这一行的文字包围盒（yy 是基线，字顶≈yy-size、字底≈yy+size*0.25）
            _BOXES.append((x, yy - size, x + indent + _tw(ln, size), yy + size * 0.25,
                           (mark + ln)[:14]))
            yy += lh
        yy += gap
    return s, yy


def _defs():
    return (
        '<defs>'
        f'<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{BG1}"/><stop offset="0.55" stop-color="#0f2542"/>'
        f'<stop offset="1" stop-color="{BG2}"/></linearGradient>'
        '<linearGradient id="cardgrad" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#1b3career"/><stop offset="1" stop-color="#152c4d"/>'
        '</linearGradient>'
        f'<linearGradient id="accentbar" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="#7fd4ff"/><stop offset="1" stop-color="{ACCENT}"/></linearGradient>'
        '</defs>'
    ).replace("#1b3career", "#1e3a63")


def wrap(inner):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
            f'viewBox="0 0 {W} {H}">{_defs()}{inner}</svg>')


def topic1():
    # 新优先级 #1：车型泛化（最重点，70% 精力）；fixer=提速手段、clip-iqa=图像质量卡口
    s = _header("Topic 1｜车型泛化",
                "Q3 最高优先：用仿真替代多车型实车采集、支撑 630 多车型发版")
    s += _rect(820, 32, 168, 34, "#c8443a", rx=17)
    s += _txt(904, 55, "7 月核心任务", size=15, color="#ffffff", weight="bold", anchor="middle")
    y = 116
    # ── 顶部 KPI 带：3 个关键指标（h=78 容 2 行 label）──
    s += _kpi(36, y, 300, "≥30 款车型", "Q3 目标：仿真替代逐车型实车采集", h=78)
    s += _kpi(352, y, 300, "参数 ↔ CCES", "建立定量关系、反哺车端算法", h=78)
    s += _kpi(668, y, 320, "首个成果 · G02ES", "定位加速慢=side front left 标定偏差", h=78)
    # ── 左卡：正向分析方法论（三步展开，自动折行）──
    cy = y + 98
    lx, lw = 36, 616
    s += _card(lx, cy, lw, 340, "正向分析方法论：从「验证工具」→「算法诊断工具」")
    _s, _ = _wbullets(lx + 24, cy + 74, lw - 60, [
        ("① 找规律", ACCENT, "同一批场景在多款车型上跑、比 CCES 得分方差；自动分离「多车一起变差=可迁移共性」与「个别偶发」，只对共性投算力"),
        ("② 找根因", ACCENT, "对问题场景逐一扫参（车衣 / 外参 pitch·roll / 车型），看指标随参数怎么变，定位是哪个参数导致算法失效"),
        ("③ 给量化", ACCENT, "参数偏差 ↔ 安全 / 效率 / 加减速 / 居中 四大指标做定量回归，输出「角度偏差→起步时延」关系直接指导算法"),
        ("✓ 已跑通", NUM, "G02ES 加速慢根因=侧前摄像头(side front left)标定，逐个换标定文件比对得出；CloudSim 已支持一套场景生成多车型、可自助改标定验证"),
    ], size=14, lh=21, gap=9)
    s += _s
    # ── 右卡：生产提速 + 图像质检 ──
    rx, rw = 668, 320
    s += _card(rx, cy, rw, 190, "NVFixer 渲染提速")
    _s2, _ = _wbullets(rx + 22, cy + 70, rw - 40, [
        ("痛点", WARN, "渲染是泛化生产的效率瓶颈、回灌耗时长"),
        ("思路", ACCENT, "ref 图编码存 latent 复用、免每帧实时 VAE 计算"),
        ("成果", NUM, "带 ref 新版效率比 1:7.2、远优于 Difix 的 1:17"),
    ], size=13, lh=19, gap=7)
    s += _s2
    s += _card(rx, cy + 206, rw, 134, "图像质检（质量卡口）")
    _s3, _ = _wbullets(rx + 22, cy + 206 + 62, rw - 40, [
        ("·", TXT, "CLIP-IQA 入库前自动质检"),
        ("·", TXT, "过滤渲染差场景、保泛化结论可信"),
        ("·", TXT, "红绿灯难例经 diffusion 修复改善"),
    ], size=13.5, lh=20, gap=9)
    s += _s3
    return wrap(s)


def topic2():
    # 新优先级 #2：闭环仿真 + HIL（长里程生产 + HIL，核心让业务用起来）
    s = _header("Topic 2｜闭环仿真 + HIL",
                "核心让业务用起来：长里程生产 + HIL 台架作发版准出把关；630 模型已交付业务使用")
    y = 116
    s += _card(36, y, 952, 118, "RC 长里程生产")
    s += _kpi(60, y + 46, 220, "561.5km", "新数据累计（截至 6/30）")
    s += _kpi(300, y + 46, 300, "7/1 → 1000km", "新老混合先凑，供各链路仿真")
    s += _kpi(620, y + 46, 344, "7/13", "长里程看板上线；生产卡死问题已修")
    my = y + 140
    s += _card(36, my, 952, 128, "HIL 台架：630 已交付业务、进入使用修复期")
    s += _kpi(60, my + 50, 210, "5 节点", "已接入、630 链路已交付")
    s += _kpi(290, my + 50, 210, "1:2.5", "实时 batch≥30（达月目标 1:3）")
    s += _kpi(520, my + 50, 200, "95.9%", "CCES 可用数据（结论待确认）")
    s += _kpi(742, my + 50, 222, "1300+", "scenario 无中断（3 节点）")
    by = my + 152
    s += _card(36, by, 466, 156, "慢速模式：拿时间换画质")
    _a, _ = _wbullets(60, by + 70, 466 - 48, [
        ("痛点", WARN, "实时链路只够 1:3、喂不饱高质量 Difix 渲染"),
        ("思路", ACCENT, "让系统时钟按比例降速、给算法足够时间算好每帧"),
        ("做法", NUM, "参考图先存成 latent 供链路直读、省掉 H265 实时解析"),
    ], size=13, lh=18, gap=7)
    s += _a
    s += _card(522, by, 466, 156, "风险与计划")
    _b, _ = _wbullets(546, by + 76, 466 - 48, [
        ("△", WARN, "评测结论能否对外、待与交付同学确认"),
        ("△", WARN, "新台架采购延至 7-8 月；RC 卡池抢占、采集折损 20-30%"),
        ("→", ACCENT, "7 月底 5 台机标准化；核心让业务常态化用起来"),
    ], size=13.5, lh=20, gap=9)
    s += _b
    return wrap(s)


def topic3():
    # 新优先级 #3：极速模式（做成海外/质量可快速上手的产品，非技术 demo）
    s = _header("Topic 3｜极速模式",
                "做成海外 / 质量团队可快速上手的产品、而非技术 demo，承接客诉 case 快速验证")
    y = 116
    # ── 顶部 KPI 带 ──
    s += _kpi(36, y, 300, "约 100 分钟", "UCP 全链路跑通（客诉 case 快速复现）", h=78)
    s += _kpi(352, y, 300, "80 / 108", "复现 case、折损后约 50% 作可用基线", h=78)
    s += _kpi(668, y, 320, "近两周", "目标：做成海外 / 质量团队自助工具", h=78)
    cy = y + 98
    # ── 左卡：定位与当前能力 ──
    lx, lw = 36, 466
    s += _card(lx, cy, lw, 340, "为什么快：跳过 3DGS 后训练")
    _a, _ = _wbullets(lx + 24, cy + 74, lw - 46, [
        ("痛点", WARN, "常规要跑完整 3DGS 后训练、单 case 3-4 小时才出场景"),
        ("思路", ACCENT, "只跑预处理 + feedforward 直接前推出场景、跳过后训练、压到 2 小时内"),
        ("用法", NUM, "漏斗式：客诉 case 先用极速快速过一遍、复现不好的再进常规生产"),
        ("已交付", NUM, "6/26 交付文档完成、向质量 + 海外用户开放试用"),
        ("△ 权衡", WARN, "省掉后训练、复现率约常规七成，换来的是几倍提速"),
    ], size=14, lh=21, gap=11)
    s += _a
    # ── 右卡：产品化改造 + 计划 ──
    rx, rw = 522, 466
    s += _card(rx, cy, rw, 340, "从技术链路 → 好用的产品（本周推进）")
    _b, _ = _wbullets(rx + 24, cy + 76, rw - 46, [
        ("△", WARN, "业务反馈：界面难用、参数配置太多、上手门槛高"),
        ("→", NUM, "仿真参数精简至 1 个，配套后端改造本周四交付"),
        ("→", NUM, "下周改自适应模式（无需特殊设置）并上线"),
        ("·", TXT, "优先向质量 / 海外团队开放，让其自助拿到验证结果"),
        ("·", TXT, "Q3 重点优化 feedforward、把入库复现率冲到 50%"),
    ], size=14, lh=21, gap=11)
    s += _b
    return wrap(s)


def topic4():
    # 新优先级 #4：Agent（快速业务上线 + 产品化）
    s = _header("Topic 4｜AI Agent 产品化",
                "7 月全部上线、以业务反馈缩小落地差距；已产出可量化收益")
    s += _rect(858, 34, 130, 34, "#c8443a", rx=17)
    s += _txt(923, 57, "首次汇报", size=16, color="#ffffff", weight="bold", anchor="middle")
    y, h = 116, 424
    x1, w1 = 36, 300
    x2, w2 = 360, 300
    x3, w3 = 684, 304
    # col1 复现率 Agent
    s += _card(x1, y, w1, h, "复现率 Agent")
    s += _kpi(x1 + 20, y + 64, w1 - 40, "9 类 · 61%", "已交付问题类型 / 支持 case 占比", h=76)
    _a, _ = _wbullets(x1 + 22, y + 168, w1 - 44, [
        ("·", TXT, "替代人工逐 case 判断「仿真是否复现实车问题」"),
        ("·", NUM, "生产验收复现准确率 89%、摆动 79%"),
        ("·", TXT, "新增 2 类 metric 排期 7/10"),
        ("·", NUM, "成本极低：单 case 约 1 分钱、每天可处理 430 个"),
    ], size=13.5, lh=20, gap=10)
    s += _a
    # col2 Diff Agent
    s += _card(x2, y, w2, h, "闭环 Diff Agent")
    s += _kpi(x2 + 20, y + 64, w2 - 40, "6 类指标", "找出改版后是哪一版、哪个因子变差", h=76)
    _b, _ = _wbullets(x2 + 22, y + 168, w2 - 44, [
        ("解决", ACCENT, "改了模型不知哪版更差：自动比对 A/B 两版同场景指标差异"),
        ("定位", TXT, "定向找出导致回退的关键因子、再交复现率 Agent 判是否复现"),
        ("△", WARN, "「主辅路跟导航」一类上周未达验收、迭代中；本周再增 3 类"),
        ("✓", NUM, "已产出 AB Review 可视化质检报告"),
    ], size=13.5, lh=20, gap=9)
    s += _b
    # col3 代码审查 + 环境
    s += _card(x3, y, w3, h, "代码审查 + 环境 Agent")
    s += _kpi(x3 + 20, y + 64, w3 - 40, "19 MR · 省 10h/月", "代码审查 Agent 量化收益", h=76)
    _c, _ = _wbullets(x3 + 22, y + 168, w3 - 44, [
        ("✓", NUM, "每次 MR 合入主分支自动触发审查"),
        ("·", TXT, "DeepSeek+开源框架、识别高危风险"),
        ("✓", NUM, "环境构建 Agent：base image → 自动产 Dockerfile"),
        ("·", TXT, "编包 Agent 自动排队、规避资源争抢"),
    ], size=13.5, lh=20, gap=10)
    s += _c
    return wrap(s)


def _person(x, y, w, name, role, tag=None):
    """一个人员卡：name 大字 + role 小字；tag='new'(新入职高亮)/'leave'(产假)/'pending'(待入职)。"""
    h = 52
    if tag == "new":
        fill, border, nc = "#1b5e3a", "#3ddc84", "#eafff2"
    elif tag == "leave":
        fill, border, nc = "#3a3a3a", "#888888", "#cccccc"
    elif tag == "pending":
        fill, border, nc = "#4a3a1a", "#ffb86b", "#ffe0b0"
    else:
        fill, border, nc = "#1e3a66", "#4da3ff", TXT
    s = _rect(x, y, w, h, fill, rx=9, stroke=border, sw=1.2)
    s += _txt(x + w / 2, y + 24, name, size=17, color=nc, weight="bold", anchor="middle")
    s += _txt(x + w / 2, y + 42, role, size=11, color=SUB, anchor="middle")
    if tag == "new":
        s += _txt(x + w - 6, y + 14, "NEW", size=9, color="#3ddc84", weight="bold", anchor="end")
    return s


def _pcard(x, y, w, name, role, tag=None):
    """紧凑人员卡（高 46），用于两条业务线下的成员格。"""
    h = 46
    if tag == "new":
        fill, border, nc = "#1b5e3a", "#3ddc84", "#eafff2"
    elif tag == "leave":
        fill, border, nc = "#3a3a3a", "#888888", "#cccccc"
    elif tag == "pending":
        fill, border, nc = "#4a3a1a", "#ffb86b", "#ffe0b0"
    else:
        fill, border, nc = "#1e3a66", "#4da3ff", TXT
    s = _rect(x, y, w, h, fill, rx=8, stroke=border, sw=1.1)
    s += _txt(x + w / 2, y + 21, name, size=15.5, color=nc, weight="bold", anchor="middle")
    s += _txt(x + w / 2, y + 38, role, size=10, color=SUB, anchor="middle")
    if tag == "new":
        s += _txt(x + w - 5, y + 13, "NEW", size=8.5, color="#3ddc84", weight="bold", anchor="end")
    return s


def team_org():
    s = _rect(0, 0, W, H, "url(#bg)", rx=0)
    s += f'<rect x="36" y="20" width="8" height="26" rx="3" fill="{ACCENT}"/>'
    s += _txt(58, 42, "仿真算法组 组织架构", size=23, color="#ffffff", weight="bold")
    s += _txt(58, 63, "在岗 19 + 产假 1；近一月新入职 8（绿）、待入职 1（橙）", size=12.5, color=SUB)
    # 图例
    lx = 640
    for i, (c, t) in enumerate([("#4da3ff", "在岗"), ("#3ddc84", "新入职"), ("#ffb86b", "待入职"), ("#888888", "产假")]):
        s += _rect(lx + i * 92, 30, 14, 14, c, rx=3)
        s += _txt(lx + i * 92 + 19, 42, t, size=12, color=SUB)

    NW = 150  # 统一框宽
    # 顶层：李坤居中（组负责人、架构中心）；刘开拓平级不汇报、放右侧不与李坤并列争中心
    s += _person(437, 74, NW, "李坤", "P8 · 组负责人")
    s += _person(812, 74, NW, "刘开拓", "生产组 PM")

    # 李坤(中心512) → 郑丽娜/杨星昊 两线 + 直属待入职
    s += f'<line x1="512" y1="126" x2="512" y2="140" stroke="{ACCENT}" stroke-width="1.4"/>'
    s += f'<line x1="140" y1="140" x2="795" y2="140" stroke="{ACCENT}" stroke-width="1.4"/>'
    for bx in (140, 512, 795):  # 分别下垂到 郑丽娜 / 直属 / 杨星昊
        s += f'<line x1="{bx}" y1="140" x2="{bx}" y2="152" stroke="{ACCENT}" stroke-width="1.4"/>'

    # 线负责人（等大框）
    s += _pcard(66, 152, NW, "郑丽娜", "P7 · 业务线")
    s += _pcard(720, 152, NW, "杨星昊", "P6A · 算法线")
    # 直属待入职（王哲成/张友健，先直接挂李坤）
    s += _txt(375, 148, "直属（待入职）", size=11, color=WARN, anchor="middle")
    s += _pcard(300, 152, NW, "王哲成", "待入职·后续产线", tag="pending")
    s += _pcard(474, 152, NW, "张友健", "P7·已入职·feedforward/WM", tag="new")

    # 业务线成员（郑丽娜，左半 2 列）— 含冯美慧(产假)
    by = 216
    biz = [
        ("周蔚旭", "P6A·极速/VM", None), ("吕文杰", "P5·复现Agent/UCP", None),
        ("朱啸峰", "P5·HIL链路", None), ("瞿鑫宇", "P5·慢速/数据精简", None),
        ("严潇竹", "实习·Prompt Agent", "new"), ("李祉浚", "实习·OnCall Agent", "new"),
        ("冯美慧", "P6·产假中", "leave"),
    ]
    for i, (n, r, tag) in enumerate(biz):
        col, row = i % 2, i // 2
        s += _pcard(66 + col * 162, by + row * 52, NW, n, r, tag)

    # 算法线成员（杨星昊，右半 2 列）— 含韩阿东(待入职,技术线)
    alg = [
        ("周冯", "P6·Fixer/Diffusion", None), ("王禹丁", "P5·鱼眼/CLIP-IQA", None),
        ("裴健宏", "P6·场景编辑/泛化", None), ("靳希睿", "校招·静态GGS+WM", "new"),
        ("樊世洲", "实习·障碍车/编包", "new"), ("谷佳萱", "实习·场景编辑·6/23", "new"),
        ("赵浩南", "实习·Diffusion预研·6/30", "new"), ("韩阿东", "P5·7/1入职·车型泛化", "new"),
    ]
    for i, (n, r, tag) in enumerate(alg):
        col, row = i % 2, i // 2
        s += _pcard(608 + col * 162, by + row * 52, NW, n, r, tag)
    return wrap(s)


GENERATORS = {"topic1": topic1, "topic2": topic2, "topic3": topic3, "topic4": topic4, "team_org": team_org}

if __name__ == "__main__":
    import sys, os
    OUT = "/workspace/team/memory/daily-sync/images"
    os.makedirs(OUT, exist_ok=True)
    which = sys.argv[1] if len(sys.argv) > 1 else "topic1"
    _reset_geom()                      # 清空上一张图的几何登记
    svg = GENERATORS[which]()
    # 🔴🔴 渲染闸：几何自检文字是否溢出卡片，越界就拒绝出图（不靠肉眼看缩略图）
    bad = _check_overflow()
    if bad:
        print(f"🚫 {which} 渲染闸拦截：文字溢出卡片 {len(bad)} 处——修坐标/收窄 max_px/精简文案后再生成：")
        for b in bad:
            print("  -", b)
        sys.exit(3)
    p = os.path.join(OUT, f"biweekly_{which}.svg")
    with open(p, "w") as f:
        f.write(svg)
    print(f"OK -> {p} ({len(svg)} bytes)｜渲染闸✅ {len(_BOXES)} 块文字全在卡内")
