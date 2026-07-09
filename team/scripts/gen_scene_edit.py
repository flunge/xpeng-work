#!/usr/bin/env python3
"""场景编辑首次汇报图。左:7类编辑需求(优先级+放大倍数);右:W28-W31里程碑。深色科技风。"""
COL="#4da3ff"
# 7类编辑需求(名称,优先级P,放大倍数)
NEEDS=[
 ("周边目标速度","P1","×4"),
 ("交通参与者行为","P1","重点"),
 ("天气/时间段","P2","组合"),
 ("车道编辑","P3","×2"),
 ("车流密度","P4","×3"),
 ("遮挡编辑","P5","重点"),
 ("道路设施/临时交通","P6","补充"),
]
# W28-31里程碑(周,要点)
MS=[
 ("W28 7/7-11","输出场景编辑Agent第一版yaml、跑通仿真闭环"),
 ("W29 7/14-18","链路代码整理+回归测试、不影响其他链路后合入主线"),
 ("W30 7/21-25","修坐标系偏移/roll角;切入泛化100场景生产仿真、交需求方验证"),
 ("W31 7/28-31","建切出/跟车/对向各100场景泛化库、对接需求方迭代"),
]
W=1280; H=560
s=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="PingFang SC,Microsoft YaHei,sans-serif">']
s.append(f'<rect width="{W}" height="{H}" fill="#0d1424"/>')
s.append(f'<rect x="36" y="22" width="8" height="26" rx="3" fill="{COL}"/>')
s.append(f'<text x="58" y="44" fill="#ffffff" font-size="23" font-weight="bold">场景编辑（CornerCase 生产）</text>')
s.append(f'<text x="58" y="70" fill="#9fb4d8" font-size="13.5">目标：把 RT 长里程 48 万 km 真实数据，编辑成差异化、拟人化的仿真场景，用于闭环验证自动驾驶能力</text>')
# 左半:7类编辑需求
lx=50; ly=100; lw=560
s.append(f'<text x="{lx}" y="{ly}" fill="{COL}" font-size="16" font-weight="bold">七类编辑能力（按优先级）</text>')
s.append(f'<text x="{lx}" y="{ly+20}" fill="#8296b5" font-size="11.5">在保持道路结构/导航意图/交规合理的前提下扩展交互变量</text>')
for i,(nm,p,mul) in enumerate(NEEDS):
    y=ly+38+i*54
    s.append(f'<rect x="{lx}" y="{y}" width="{lw}" height="46" rx="7" fill="#16203a" stroke="{COL}" stroke-width="1" opacity="0.9"/>')
    pc="#ff6b6b" if p in("P1",) else ("#ffb020" if p in("P2","P3") else "#5a7099")
    s.append(f'<rect x="{lx+12}" y="{y+13}" width="34" height="20" rx="4" fill="{pc}"/>')
    s.append(f'<text x="{lx+29}" y="{y+27}" fill="#0d1424" font-size="12" font-weight="bold" text-anchor="middle">{p}</text>')
    s.append(f'<text x="{lx+56}" y="{y+29}" fill="#e8f0ff" font-size="14.5">{nm}</text>')
    s.append(f'<text x="{lx+lw-14}" y="{y+29}" fill="{COL}" font-size="13" text-anchor="end">放大 {mul}</text>')
# 右半:W28-31里程碑
rx=660; ry=100; rw=W-rx-40
s.append(f'<text x="{rx}" y="{ry}" fill="#37d67a" font-size="16" font-weight="bold">7月路线图（W28→W31）</text>')
s.append(f'<line x1="{rx+8}" y1="{ry+26}" x2="{rx+8}" y2="{ry+26+4*98}" stroke="#37d67a" stroke-width="2.5"/>')
for i,(wk,txt) in enumerate(MS):
    y=ry+40+i*98
    s.append(f'<circle cx="{rx+8}" cy="{y}" r="7" fill="#37d67a"/>')
    s.append(f'<text x="{rx+26}" y="{y-4}" fill="#e8f0ff" font-size="14" font-weight="bold">{wk}</text>')
    # 要点换行(每行约22字)
    words=txt; lines=[]
    while words:
        lines.append(words[:22]); words=words[22:]
    for li,ln in enumerate(lines):
        s.append(f'<text x="{rx+26}" y="{y+16+li*19}" fill="#c8d6f0" font-size="12.5">{ln}</text>')
# 底部关键数据条
by=H-38
s.append(f'<rect x="50" y="{by-4}" width="{W-100}" height="30" rx="6" fill="#16203a"/>')
s.append(f'<text x="66" y="{by+16}" fill="#9fb4d8" font-size="12.5">当前进展：webviz+metric 全链路已打通编辑车数据 ｜ JSON 场景模板 5 种 ｜ 交付里程按"有效性筛选"统计，目标 ≥48 万 km</text>')
s.append('</svg>')
open("/workspace/team/.scene.svg","w",encoding="utf-8").write("\n".join(s))
print("场景编辑图生成,行数需求7、里程碑4")
