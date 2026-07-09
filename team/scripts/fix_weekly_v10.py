#!/usr/bin/env python3
"""V10 逐条自查发现的脑补/时态错误：
[8] 极速模式:去"前端界面"脑补 + "计划下周上线"改为源文"正在调研"
[26] 交付:"本周开始试用"→源文"明日(7/1)开始试用"
"""
import subprocess, json

DOC = "KtzLdBh3ToRFLYx5R66cpLiHnEk"

def fetch():
    r=subprocess.run(["lark-cli","docs","+fetch","--doc",DOC,"--doc-format","markdown","--format","json"],
                    capture_output=True,text=True)
    return json.loads(r.stdout).get("data",{}).get("document",{}).get("content","")

def rep(old,new):
    r=subprocess.run(["lark-cli","docs","+update","--doc",DOC,"--command","str_replace",
                     "--doc-format","markdown","--pattern",old,"--content",new],
                    capture_output=True,text=True)
    out=json.loads(r.stdout) if r.stdout.strip() else {}
    ok=out.get("ok",False)
    print(f"  ok={ok}"+("" if ok else f"  err={out.get('error',{}).get('message','')[:120]}"))
    return ok

fixes=[
    # [8] 去"前端界面"脑补 + 下周上线→正在调研
    ("进展：前端界面仿真参数已降至 1 个、准备提 MR；后端改造本周四交付；下一步改自适应设置、计划下周上线。",
     "进展：仿真设置参数已降至 1 个、测试完毕准备提 MR；后端改造本周四交付；自适应仿真设置方案正在调研（涉及平台/扶摇/后端多方），争取尽早落地。"),
    # [26] 本周开始试用 → 明日(7/1)开始
    ("进展：交付组本周开始试用评测准确度；review agent demo（针对化隆）可对两版本特定指标出静态质检报告。",
     "进展：交付组 7/1 起试用评测准确度；review agent demo（针对化隆需求）可对两版本特定指标出静态质检报告。"),
]

c=fetch()
for i,(o,n) in enumerate(fixes,1):
    if o in c:
        print(f"[{i}] replacing...")
        rep(o,n); c=fetch()
    else:
        print(f"[{i}] NOT FOUND: {o[:36]}")

print("\ncheck:")
subprocess.run(["python3","/workspace/team/scripts/check_report.py",DOC,"--audience","boss"])
