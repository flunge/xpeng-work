#!/usr/bin/env python3
# 用法: python3 make_slide.py spec.json  -> 渲染 output/<name>.png（自适应高度，自动裁掉底部留白）
import sys, json, subprocess, os
from PIL import Image
SPEC = json.load(open(sys.argv[1], encoding="utf-8"))
OUT = os.path.dirname(os.path.abspath(sys.argv[1]))
W = 2048

CSS = """
*{margin:0;padding:0;box-sizing:border-box;font-family:"Noto Sans CJK SC",sans-serif;}
body{width:2048px;background:#0A1628;color:#E8EEF5;}
.slide{padding:44px 56px 40px;display:flex;flex-direction:column;}
.title{font-size:54px;font-weight:700;color:#fff;letter-spacing:1px;}
.sub{font-size:23px;color:#8AA0B8;margin-top:10px;line-height:1.4;}
.hl{display:flex;gap:18px;margin:6px 0 16px;}
.hlc{flex:1;background:linear-gradient(135deg,#13324f,#0E1E33);border:1.5px solid #1FB6C9;border-radius:12px;padding:14px 20px;}
.hlk{font-size:20px;color:#9fc4d8;}
.hlv{font-size:40px;font-weight:800;color:#33D17A;line-height:1.1;margin-top:2px;}
.hr{height:3px;background:linear-gradient(90deg,#1FB6C9,transparent);margin:18px 0 22px;}
.grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px;align-items:start;}
.grid.g2{grid-template-columns:1fr 1fr;}
.card{background:#0E1E33;border:1.5px solid #1c3a5e;border-radius:14px;padding:22px 24px;}
.ct{font-size:26px;font-weight:700;color:#fff;margin-bottom:14px;}
.li{font-size:21px;line-height:1.5;color:#C7D6E6;margin-bottom:8px;padding-left:16px;position:relative;}
.li::before{content:"";position:absolute;left:0;top:11px;width:7px;height:7px;border-radius:50%;background:#1FB6C9;}
.tl{font-size:21px;line-height:1.65;color:#C7D6E6;}
.tl b{color:#5CC8D8;font-weight:600;}
.num{color:#5CC8D8;font-weight:700;}
.risk{color:#F5A623;font-weight:700;}
.ok{color:#33D17A;font-weight:700;}
.tag{display:inline-block;font-size:18px;font-weight:700;padding:3px 12px;border-radius:6px;margin-right:10px;color:#06121f;white-space:nowrap;}
.row{display:flex;align-items:flex-start;margin-bottom:11px;font-size:20px;color:#C7D6E6;line-height:1.4;}
.g{background:#33D17A;}.lg{background:#7BE0A8;}.y{background:#F0C420;}.gr{background:#7E94A8;}.b{background:#5CC8D8;}
.steps{display:flex;align-items:center;gap:8px;margin-top:12px;flex-wrap:wrap;}
.step{background:#13283f;border:1px solid #1FB6C9;border-radius:8px;padding:8px 12px;font-size:19px;color:#CFE3F0;line-height:1.35;}
.arr{color:#1FB6C9;font-size:22px;}
.concl{margin-top:20px;background:#102844;border-left:5px solid #1FB6C9;border-radius:10px;padding:18px 26px;font-size:23px;color:#fff;line-height:1.5;}
.concl b{color:#5CC8D8;}
.stats{display:flex;gap:20px;margin-top:18px;}
.pill{flex:1;background:#0E1E33;border:1.5px solid #1FB6C9;border-radius:12px;padding:14px 0;text-align:center;}
.pk{font-size:20px;color:#8AA0B8;}.pv{font-size:32px;font-weight:700;color:#33D17A;margin-left:8px;}
"""


import re as _re
_NUM=_re.compile(r"(\d+(?:\.\d+)?\s*(?:%\+?|km/?天?|FPS|h(?![a-z])|min|ms|×|倍|个|条|类|帧|天|周|卡|dB|GB|G(?![a-z])|秒|分钟|车型|城)|\d+(?:\.\d+)?:\d+(?:\.\d+)?|\d+/\d+|\d{2,}\+?)")
_RISK=_re.compile(r"(风险|卡点|缺卡|缺\s?A100|离职|受限|阻塞|待解|未启动|未集成|不可用|延迟|缺位|大量\s?FP|误判|失败|降级|损失|抖动|幻觉|OOD|不对称|高危|偏低|颠倒|断裂|空洞|不通用|遗留)"
)
_OK=_re.compile(r"(已上线|上线|打通|达标|跑通|通过|已交付|交付|已发布|发布|已应用|完成|对齐|满足|默认打开)")
def hl(text):
    parts=_re.split(r"(<[^>]+>)",text); out=[]
    for p in parts:
        if p.startswith("<"): out.append(p); continue
        p=_OK.sub(r'<span class="ok">\1</span>',p)
        p=_RISK.sub(r'<span class="risk">\1</span>',p)
        p=_NUM.sub(r'<span class="num">\1</span>',p)
        out.append(p)
    return "".join(out)

def card_html(c):
    t=c.get("type","bullets"); body=""
    if t=="bullets":
        body="".join(f'<div class="li">{hl(x)}</div>' for x in c.get("items",[]))
    elif t=="lines":
        body=f'<div class="tl">{hl(c.get("html",""))}</div>'
    elif t=="rows":
        body="".join(f'<div class="row"><span class="tag {col}">{tag}</span>{hl(txt)}</div>' for tag,col,txt in c.get("rows",[]))
    elif t=="steps":
        intro=f'<div class="tl">{c.get("intro","")}</div>' if c.get("intro") else ""
        steps=('<span class="arr">→</span>').join(f'<span class="step">{s}</span>' for s in c.get("steps",[]))
        body=intro+f'<div class="steps">{steps}</div>'
    return f'<div class="card"><div class="ct">{c["t"]}</div>{body}</div>'

cards="".join(card_html(c) for c in SPEC["cards"])
_n=len(SPEC["cards"])
cols=SPEC.get("cols", 2 if _n in (2,4) else 1 if _n==1 else 3)
gcls="grid"+(" g2" if cols==2 else "")
if cols==1: gcls="grid";  # single column fallback handled by template width
stats="".join(f'<div class="pill"><span class="pk">{k}</span><span class="pv">{v}</span></div>' for k,v in SPEC.get("stats",[]))
concl=f'<div class="concl"><b>结论：</b>{SPEC["conclusion"]}</div>' if SPEC.get("conclusion") else ""
statsdiv=f'<div class="stats">{stats}</div>' if stats else ""
hl=""
if SPEC.get("highlight"):
    hl='<div class="hl">'+"".join(f'<div class="hlc"><div class="hlk">{k}</div><div class="hlv">{v}</div></div>' for k,v in SPEC["highlight"])+'</div>'
gridstyle='' if cols!=1 else ' style="grid-template-columns:1fr;"'
HTML=f'''<!DOCTYPE html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body><div class="slide">
<div class="title">{SPEC["title"]}</div><div class="sub">{SPEC["subtitle"]}</div><div class="hr"></div>{hl}
<div class="{gcls}"{gridstyle}>{cards}</div>{concl}{statsdiv}</div></body></html>'''

name=SPEC["name"]
hp=os.path.join(OUT,f"{name}.html"); open(hp,"w",encoding="utf-8").write(HTML)
png=os.path.join(OUT,f"{name}.png")
# 渲染到足够高的画布
subprocess.run(["chromium","--headless","--no-sandbox","--disable-gpu","--force-device-scale-factor=1",
    "--hide-scrollbars","--window-size=2048,2600",f"--screenshot={png}",hp],capture_output=True,timeout=120)
# PIL 自动裁掉底部背景留白
BG=(10,22,40)  # #0A1628
def near(px): return abs(px[0]-BG[0])<=6 and abs(px[1]-BG[1])<=6 and abs(px[2]-BG[2])<=6
im=Image.open(png).convert("RGB"); w,h=im.size; px=im.load()
last=0
for y in range(h-1,-1,-1):
    rowbg=all(near(px[x,y]) for x in range(0,w,17))
    if not rowbg: last=y; break
crop_h=min(h, last+40)
im.crop((0,0,w,crop_h)).save(png)
print("OK", png, f"{w}x{crop_h}")
