#!/usr/bin/env python3
"""原生 SVG 信息图生成器（不依赖 satori/HTML，飞书 whiteboard type=svg 直吃）。
深色科技风：标题条 + 分栏卡片 + KPI 数字块 + bullet。手算坐标，无 foreignObject、无全角≤≥、无<br/>。
每个 Topic 一个函数返回自包含 SVG 字符串。"""
import html as _h

W, H = 1024, 680
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
    # 登记文字包围盒到 _ALLBOXES（供画布溢出闸用；anchor 影响横向范围）
    tw = _tw(str(s), size)
    if anchor == "middle":
        x0, x1 = x - tw / 2, x + tw / 2
    elif anchor == "end":
        x0, x1 = x - tw, x
    else:
        x0, x1 = x, x + tw
    _ALLBOXES.append((x0, y - size, x1, y + size * 0.25, str(s)[:14]))
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
_BOXES = []   # [(x0,y0,x1,y1,label)] 卡内 bullet 文字包围盒
_ALLBOXES = []  # [(x0,y0,x1,y1,label)] 所有文字包围盒（含 KPI/标题/bullet），供画布溢出闸
def _reset_geom():
    _CARDS.clear(); _BOXES.clear(); _ALLBOXES.clear()


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
    # label 折行（最多 2 行）——一个 <text>、续行用相对 dy（勿用绝对 y，否则飞书拆框）
    _lns = _wrap(label, avail, 12)[:2]
    if _lns:
        _sp = ""
        for k, ln in enumerate(_lns):
            _pos = f'y="{y+52}"' if k == 0 else 'dy="15"'
            _sp += f'<tspan x="{x+16}" {_pos}>{esc(ln)}</tspan>'
        s += f'<text font-size="12" fill="{SUB}" font-family="{FONT}">{_sp}</text>'
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
    items=[(mark,color,text)]，mark 空则纯续行缩进。返回 (svg, 结束 y)。
    🔴 整组 bullet = **一个 <text>**，换行用**相对 dy**（首行 absolute y 定位、其余 dy）——
    飞书导入后是**一个可编辑大文本框、内部换行**。绝不给续行 tspan 写绝对 y（会被飞书拆成独立小框）。"""
    yy = y
    prev = None            # 上一行基线（用于算相对 dy）
    parts = []
    for mark, color, text in items:
        col = WARN if color == WARN else (NUM if color == NUM else TXT)
        indent = (_tw(mark, size) + 10) if mark else 12
        lines = _wrap(text, max_px - indent, size) or [""]
        for k, ln in enumerate(lines):
            base = y if prev is None else (prev + (lh + gap if k == 0 else lh))
            dattr = f'y="{base}"' if prev is None else f'dy="{base - prev}"'
            if k == 0 and mark:
                # mark 与首行同基线：mark 带换行位移，首行文字 dy=0 接在同一行
                parts.append(f'<tspan x="{x}" {dattr} fill="{color}" '
                             f'font-weight="bold">{esc(mark)}</tspan>')
                parts.append(f'<tspan x="{x+indent}" dy="0" fill="{col}">{esc(ln)}</tspan>')
            else:
                parts.append(f'<tspan x="{x+indent}" {dattr} fill="{col}">{esc(ln)}</tspan>')
            _box = (x, base - size, x + indent + _tw(ln, size), base + size * 0.25,
                    (mark + ln)[:14])
            _BOXES.append(_box); _ALLBOXES.append(_box)
            prev = base; yy = base
    s = f'<text font-size="{size}" font-family="{FONT}">{"".join(parts)}</text>' if parts else ""
    return s, yy + lh


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
    global H; H=692
    s=_header("Topic 1｜车型泛化","Q3 优先级第一：建立参数对车型的影响规律、支撑跨车型可比；效率提速支撑万级 case 产能")
    s+=_rect(838,32,150,34,"#c8443a",rx=17)
    s+=_txt(913,55,"7 月核心",size=15,color="#ffffff",weight="bold",anchor="middle")
    y=116
    s+=_kpi(36,y,320,"51 → 11.8 min/卡","开环生产效率(目标 <10min)，效率优先",h=78)
    s+=_kpi(372,y,300,"10 款车型","规模化投产 + 非斑马车衣库",h=78)
    s+=_kpi(688,y,300,"✓ 业务采纳","仿真结论与实车一致、常态化用",h=78)
    cy=y+98; lx,lw=36,616
    s+=_card(lx,cy,lw,430,"⭐ 效率优化（核心）：开环提速路径 + 硬件对比")
    _s,_=_wbullets(lx+24,cy+74,lw-56,[
        ("优化路径",ACCENT,"0701 base：51 min/卡 (1:102)\n0707 nvfixer 代 difix + 解 OOM(单卡双任务)：17 (1:34)\n0713 共用 h265 解码 / 3dgs 下载·加载 + 单卡 4 任务：11.8 (1:23)\n0714 encode→h265 优化中：目标 <10"),
        ("硬件对比",NUM,"单 cam 单帧 latency：\ntrt：5080 54.8ms / A100-mig 86.7ms（同量级）\ntorch：A100 整卡 105.9ms / PPU 130.2ms（明显慢）\n→ 统一推 trt + 5080/A100"),
        ("换车衣",TXT,"基于物理模型自动换车衣管线：仅替换纹理、保车身结构、批量生产非斑马车衣库"),
        ("渲染",TXT,"NVFixer 0.4s/img；PPU 暂不支持 dit holmes engine"),
        ("5080 产线",NUM,"车型泛化已适配 5080 并行生产、PPU profile 阶段里程碑；生产走 ceph 直取直传"),
        ("意义",ACCENT,"开环提速直接支撑万级 case 生产 / 8 月 release 高峰产能，并决定复现率上限"),
    ],size=14,lh=21,gap=13)
    s+=_s
    rx,rw=668,320
    s+=_card(rx,cy,rw,205,"诊断依据（NNHA 12 组实验）")
    _s2,_=_wbullets(rx+22,cy+62,rw-40,[
        ("G02 不加速",NUM,"逐摄像头锁定 side front left 外参、换正常 calib 即加速"),
        ("D03 偏右",NUM,"右前相机外参偏 2°；换外参居中提升 ~15cm"),
        ("车衣色",NUM,"194 撞RB场景多色测试：越深对跑不到限速负面越大、黑色最甚；斑马→正常即加速"),
    ],size=12,lh=16.5,gap=7)
    s+=_s2
    by=cy+217
    s+=_card(rx,by,rw,258,"找规律 · 方法论 · 闭环")
    _s3,_=_wbullets(rx+22,by+60,rw-40,[
        ("找规律",ACCENT,"FM lost 热力图 bicluster 诊断短板车型(g01/h93aes)；筛 fm cost>300 比同 case 差值评估性能"),
        ("根因",WARN,"FM 未学车辆通用语义、靠车衣轮廓/画布黑边等旁支信息匹配(数据集捷径)；C/D/E 对照实验隔离车衣色/轮廓/外参"),
        ("闭环上线",NUM,"cloudsim+场景毕业平台已上线(前提已产 3DGS)、联调 calib 上传"),
        ("反馈成效",ACCENT,"结论反馈车端：新模型 F30/H93/F01 安全改善"),
    ],size=12,lh=16.5,gap=6)
    s+=_s3
    return wrap(s)


def topic2():
    global H; H=488
    s=_header("Topic 2｜闭环仿真 + HIL","让业务常态化用起来：HIL 台架作发版准出、RC 长里程持续生产")
    y=116
    s+=_kpi(36,y,300,"metric 有效性验证","HIL 从『跑通』进到 metric 可用性验证",h=78)
    s+=_kpi(352,y,300,"可用率 +2%→冲 95%","修 FM 偶发异常、链路问题收敛",h=78)
    s+=_kpi(668,y,320,"~946km / 61%","RC 本月新数据累计 / 数据留存率",h=78)
    cy=y+98; h=252
    s+=_card(36,cy,300,h,"HIL 链路：本期修复")
    _a,_=_wbullets(58,cy+64,264,[
        ("SF 无输出",NUM,"全量 SF topic 缺失(VRU 缺失)已修复、通过交付验收"),
        ("FM 异常",NUM,"修复 FM 偶发异常、可用率 +2%、适配下游 metric 输入"),
        ("评测有效性",ACCENT,"人工核验 metric 运行有效 → 开启 500km 大批量压测"),
        ("RTM 已修",NUM,"录包 RTM topic 缺失/格式变更问题本期已修复、符合交付标准、进入大批量压测"),
    ],size=12,lh=16.5,gap=9)
    s+=_a
    s+=_card(360,cy,304,h,"HIL 资源 + RC 长里程")
    _b,_=_wbullets(382,cy+64,268,[
        ("台架资源",NUM,"获批 39 台 5080 + 现有 40 余台 + TC 150 套台架，支撑 XP5 TDT/RC"),
        ("HIL 台架",ACCENT,"5 节点调通、可用率 92%→95% 目标、CCES 结论与交付确认可对外"),
        ("长里程",NUM,"本月 946km→月底目标 5000km(4 城)、复刻 TC 3000-4000km 常规路线"),
        ("数据损耗",WARN,"采集+闭环环节合计 ~50% 损耗(TC 侧 30% 无法上传)、已拉群定位"),
    ],size=12,lh=16.5,gap=9)
    s+=_b
    s+=_card(688,cy,300,h,"闭环 metric + 风险计划")
    _c,_=_wbullets(710,cy+64,264,[
        ("闭环 metric",NUM,"Sim-实车 topic 互换适配、补全录制 topic 本期完成；七类验收、出带 PAT 阶段报告"),
        ("链路修复",TXT,"clip-iqa 接入、localpose 切万兆网卡、bsp 大包刷写切 XTest"),
        ("风险",WARN,"场景集2期或收尾：约50%Jira票实车版本太老跑不起复现、需重新出包；拦截结论与实车未成稳定闭环"),
        ("计划",ACCENT,"可用率 95% 绑发版准出；仿真 1 天出结果 vs 实车 3 天"),
    ],size=12,lh=16.5,gap=9)
    s+=_c
    return wrap(s)


def topic3():
    global H; H=488
    s=_header("Topic 3｜极速模式 / 生产链路","极速做成质量/海外自助工具；Feedforward 从根本提复现率上限")
    y=116
    s+=_kpi(36,y,300,"2h vs 4h","极速 50% vs 非极速 70-80%(实测)",h=78)
    s+=_kpi(352,y,300,"SIL 1:112→1:80","SIL 链路耗时优化(1:112.3→1:79.9)",h=78)
    s+=_kpi(668,y,320,"选定 baseline","Feedforward 选型完成：VGGT-Ω + π3",h=78)
    cy=y+98; h=252
    s+=_card(36,cy,300,h,"Feedforward 提上限")
    _a,_=_wbullets(58,cy+64,264,[
        ("为何做",WARN,"极速/闭环复现率上限受 feedforward 重建质量制约、是核心瓶颈"),
        ("benchmark",ACCENT,"三维度横评：几何精度对齐真值 / 多视·多 chunk 一致 / 显存 <40G"),
        ("选型",NUM,"选定 VGGT-Ω + π3：点云直出、多视融合强、开源成熟"),
        ("演进",ACCENT,"评审统一 3D latent voxel 中间表示、打通重建+视频生成"),
    ],size=12,lh=16.5,gap=9)
    s+=_a
    s+=_card(360,cy,304,h,"生产链路提效")
    _b,_=_wbullets(382,cy+64,268,[
        ("RAID 优化",NUM,"H800 单卡 case 比 1:3→1:1.6(最高 1:1.1)、A100 1:6→1:3"),
        ("再提效",ACCENT,"解码/编码/DDS 三环节改造、单环节 +60~80%，整体压向 10min 内；外挂 32CPU +20%"),
        ("产能",NUM,"6/1-7/1 累计 202 个模型仿真、日均 ~6.5 个"),
        ("CloudSim",TXT,"收 60 余份问卷做 UIUX 优化、面板可拖动、后续支持 CLI 提任务"),
    ],size=12,lh=16.5,gap=9)
    s+=_b
    s+=_card(688,cy,300,h,"极速模式产品化")
    _c,_=_wbullets(710,cy+64,264,[
        ("极速实测",NUM,"极速 2h / 复现率 ~50%\nvs 非极速 4h / 70-80%\n漏斗：客诉 case 先极速过一遍"),
        ("改造",ACCENT,"参数精简至 1 个、前端默认打开；全链路已在 A100 跑通、待接 DFIX 优化渲染"),
        ("计划",ACCENT,"Feedforward Phase1 达/超点云→高斯 baseline；极速优先质量/海外、复现率 +30%"),
    ],size=12,lh=16.5,gap=9)
    s+=_c
    return wrap(s)


def topic4():
    global H; H=488
    s=_header("Topic 4｜AI Agent 产品化","7 月全部上线、以业务反馈缩小落地差距；同步搭通用基建")
    y=116
    s+=_kpi(36,y,300,"复现率 11 类","准确率 80~90%、07-24 接场景集自动化",h=78)
    s+=_kpi(352,y,300,"Diff 14 项","metric·准确率 85%·回填 Cloudsim",h=78)
    s+=_kpi(668,y,320,"OnCall 打通","生产链路日志改造、失败根因分析",h=78)
    cy=y+98; h=252
    s+=_card(36,cy,300,h,"复现率 Agent")
    _a,_=_wbullets(58,cy+64,264,[
        ("作用",ACCENT,"替代人工判断『仿真是否复现实车问题』、覆盖 ~61% 人工介入、提效 1 倍+"),
        ("准召",NUM,"主辅路 86.2%→90.7%、路口未跟导航 68.2%→90.7%、优化后达标"),
        ("成本",NUM,"单 case 约 1 分钱、成本极低"),
        ("待优化",WARN,"部分类目生产环境泛化仍待打磨"),
    ],size=12,lh=16.5,gap=9)
    s+=_a
    s+=_card(360,cy,304,h,"闭环 Diff Agent")
    _b,_=_wbullets(382,cy+64,268,[
        ("解决",ACCENT,"改版后自动比对 A/B 两版同场景指标差异、定位回退因子"),
        ("进展",NUM,"已支持 14 项 metric(每工作日+1)、准确率 85%、提速 2/3、结果回填 Cloudsim"),
        ("开环 Diff",NUM,"9 类 top diff 自动分析、单 case 2min 与人工持平、已上线对话助手"),
        ("计划",TXT,"下周验收集成、集成每日 CCS 自动出报告、随业务需求逐步释放"),
    ],size=12,lh=16.5,gap=9)
    s+=_b
    s+=_card(688,cy,300,h,"OnCall + 通用基建")
    _c,_=_wbullets(710,cy+64,264,[
        ("OnCall",NUM,"自动定位生产失败根因：数据<18s / 位移<8m 不满足 3DGS / OSS 日志缺失"),
        ("迭代",WARN,"首答准确率 ~50%、待丰富知识库+优化追问逻辑；接 HIL 监控、推广组外"),
        ("编包 Agent",NUM,"全自动 4 步(登陆宿主机→拉码→打包上传→写结果)产出 Binary Id、避争抢"),
        ("方向",ACCENT,"千问 38B 微调替第三方 API 降本；搭通用基建挖真实需求、避逐类低价值调优"),
    ],size=12,lh=16.5,gap=9)
    s+=_c
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
    OUT = "/workspace/team/tmp"
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
    # 🔴🔴 对外去人名闸（2026-07-13）：给刘先明的图禁止出现组员姓名（溯源闸只扫正文、扫不到 SVG）
    # team_org 是内部团队架构图、姓名是合理的，豁免
    _NAMES = ["夏志勋","邓爽","杨星昊","杨潮","裴健宏","韩阿东","王禹丁","周蔚旭","吕文杰",
              "莫春媚","解文康","云荟","卓明","周冯","周月","张海云","高炳涛","李坤","刘先明"]
    _hit = [n for n in _NAMES if n in svg] if which != "team_org" else []
    if _hit:
        print(f"🚫 {which} 去人名闸拦截：图中出现组员/领导姓名 {_hit}——改为角色/团队/去署名后再生成")
        sys.exit(4)
    # 🔴🔴 画布溢出闸（2026-07-13）：任何文字包围盒都不得越出图像(画布 W×H)边界
    PAD = 4
    oob = [b for b in _ALLBOXES
           if b[0] < PAD or b[1] < PAD or b[2] > W - PAD or b[3] > H - PAD]
    if oob:
        print(f"🚫 {which} 画布溢出闸拦截：{len(oob)} 处文字越出图像范围(画布 {W}x{H})：")
        for b in oob[:8]:
            print(f"  - 「{b[4]}」盒[{b[0]:.0f},{b[1]:.0f},{b[2]:.0f},{b[3]:.0f}]")
        sys.exit(5)
    # 🔴🔴 叠框回归闸（2026-07-13）：禁止把同一 bullet 的多行拆成多个独立 <text>
    # （飞书导入后每个 <text> 是一个文本框、多行会叠成多个框）。多行必须用 <tspan> 分行。
    # 检测信号：两个「无 tspan 的独立 <text>」左对齐(同 x)且纵向间距≈一个行高(10~26)。
    import re as _re
    _solo = []
    for _m in _re.finditer(r'<text\b[^>]*?>([\s\S]*?)</text>', svg):
        if '<tspan' in _m.group(1):
            continue
        _xm = _re.search(r'\bx="([\d.]+)"', _m.group(0))
        _ym = _re.search(r'\by="([\d.]+)"', _m.group(0))
        if _xm and _ym:
            _solo.append((float(_xm.group(1)), float(_ym.group(1))))
    _stack = [(a, b) for i, a in enumerate(_solo) for b in _solo[i+1:]
              if abs(a[0]-b[0]) < 3 and 10 < abs(a[1]-b[1]) < 26]
    if _stack:
        print(f"🚫 {which} 叠框回归闸拦截：{len(_stack)} 处疑似把多行 bullet 拆成独立 <text>"
              f"（应在一个 <text> 内用 <tspan> 分行）：{_stack[:3]}")
        sys.exit(6)
    p = os.path.join(OUT, f"biweekly_{which}.svg")
    with open(p, "w") as f:
        f.write(svg)
    print(f"OK -> {p} ({len(svg)} bytes)｜渲染闸✅ {len(_BOXES)} 块在卡内 / {len(_ALLBOXES)} 块在画布内、无人名、无叠框")
