#!/usr/bin/env python3
"""4主线项目时间轴(W28-W31)。面向刘先明(GIC不懂细节):milestone写"价值/结果大白话",
控制字数不截断。深色科技风。"""
LINES={
"车型泛化":("#4da3ff","用仿真替代多车型实车采集，支撑 630 多车型发版",[
 ["跑通基础链路，产 4k-8k 场景","业务方可自助生产、不用等我们"],
 ["找出车型在哪些场景会崩、出规律","建起核心车型的车衣库"],
 ["摸清相机参数偏差如何影响评分","产出参数影响结论报告"],
 ["覆盖 ≥30 款车型","沉淀车型敏感规律，稳定供业务用"],
]),
"闭环仿真+HIL":("#37d67a","RC 生产 + HIL 台架作发版把关，让业务常态化用起来",[
 ["630 链路交给业务试用","HIL 5 节点打通、可用率冲 95%"],
 ["慢速模式过评审、正式可用","拿到 SIL 与 HIL 一致性结论"],
 ["HIL 自动化、绑定发版准出","长里程数据留存率升到 75%"],
 ["性能与一致性达标","业务正式验收、可对外出报告"],
]),
"极速模式":("#ffb020","做成海外/质量团队能自助上手的产品，而非技术 demo",[
 ["功能上线、操作简化到一键","开放外部团队试用、收反馈"],
 ["用新算法把复现率再提上去"],
 ["解决卡顿、端到端提速"],
 ["复现率达 50%、可正式交付"],
]),
"AI Agent":("#b56cff","7 月全部上线，用 AI 替人工、缩短落地差距、产出可量化收益",[
 ["复现率判定 Agent 覆盖 11 类问题","代码/结果对比 Agent 扩到 7 类"],
 ["每周新增 2 类、接入 HIL 监控"],
 ["集成到平台、开放给组外用"],
 ["全部上线、给出省人力的收益数字"],
]),
}
WEEKS=["W28 (7/7-11)","W29 (7/14-18)","W30 (7/21-25)","W31 (7/28-31)"]

def gen(name):
    col,subtitle,weeks=LINES[name]
    W=1280; H=440; pad=42; node_y=140; seg=(W-2*pad)/4
    s=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="PingFang SC,Microsoft YaHei,sans-serif">']
    s.append(f'<rect width="{W}" height="{H}" fill="#0d1424"/>')
    s.append(f'<text x="{pad}" y="42" fill="{col}" font-size="22" font-weight="bold">【{name}】7月路线图</text>')
    s.append(f'<text x="{pad}" y="70" fill="#9fb4d8" font-size="13.5">目标：{subtitle}</text>')
    s.append(f'<line x1="{pad}" y1="{node_y}" x2="{W-pad}" y2="{node_y}" stroke="{col}" stroke-width="3"/>')
    for i,wk in enumerate(WEEKS):
        cx=pad+seg*i+seg/2
        s.append(f'<circle cx="{cx}" cy="{node_y}" r="9" fill="{col}"/>')
        s.append(f'<circle cx="{cx}" cy="{node_y}" r="15" fill="none" stroke="{col}" stroke-width="1.5" opacity="0.5"/>')
        s.append(f'<text x="{cx}" y="{node_y-26}" fill="#e8f0ff" font-size="15" font-weight="bold" text-anchor="middle">{wk}</text>')
        ms=weeks[i] if i<len(weeks) else []
        cy=node_y+34; cardw=seg-14; cardh=30+len(ms)*34
        s.append(f'<rect x="{cx-cardw/2}" y="{cy}" width="{cardw}" height="{cardh}" rx="8" fill="#16203a" stroke="{col}" stroke-width="1" opacity="0.9"/>')
        for j,m in enumerate(ms):
            # 不截断:字号12,卡片宽约300px,15字内可容纳
            s.append(f'<circle cx="{cx-cardw/2+15}" cy="{cy+28+j*34}" r="3" fill="{col}"/>')
            s.append(f'<text x="{cx-cardw/2+25}" y="{cy+32+j*34}" fill="#dbe6fa" font-size="12">{m}</text>')
    s.append('</svg>')
    return "\n".join(s)

FN={"车型泛化":"veh","闭环仿真+HIL":"hil","极速模式":"fast","AI Agent":"agent"}
for nm in LINES:
    fn="/workspace/team/.tl_"+FN[nm]+".svg"
    open(fn,"w",encoding="utf-8").write(gen(nm)); print("生成",fn)
