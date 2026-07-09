#!/usr/bin/env python3
"""V8: 清掉黑话——塔包/expand框架/DSOP/RTM topic 说人话。"""
import subprocess, json

DOC = "KtzLdBh3ToRFLYx5R66cpLiHnEk"

def fetch():
    r = subprocess.run(["lark-cli","docs","+fetch","--doc",DOC,"--doc-format","markdown","--format","json"],
                       capture_output=True,text=True)
    return json.loads(r.stdout).get("data",{}).get("document",{}).get("content","")

def rep(old,new):
    r=subprocess.run(["lark-cli","docs","+update","--doc",DOC,"--command","str_replace",
                     "--doc-format","markdown","--pattern",old,"--content",new],
                    capture_output=True,text=True)
    out=json.loads(r.stdout) if r.stdout.strip() else {}
    print(f"  ok={out.get('ok',False)}")
    return out.get("ok",False)

fixes=[
    # 塔包 → 标定压缩包
    ("上传 calibration 塔包功能未通待平台打通。",
     "上传车型标定文件（calibration 压缩包）的功能未打通，待平台支持。"),
    # expand 框架 → 旧评测框架
    ("改为复用旧 expand 框架、按优先级一次批量跑通 10 个 metric。",
     "改为复用旧的评测框架，按优先级一次批量跑通 10 个核心 metric。"),
    # DSOP/RTM topic → 说人话
    ("风险：DSOP 闭环 metric 因 RTM topic 格式变更读不到，10 metric 起跑被阻塞、依赖评估组根因修复。",
     "风险：部分闭环 metric 因上游数据格式变更读取失败，导致 10 个 metric 批量起跑被阻塞，依赖评估组定位根因后修复。"),
]

c=fetch()
for i,(o,n) in enumerate(fixes,1):
    if o in c:
        print(f"[{i}] replacing...")
        rep(o,n); c=fetch()
    else:
        print(f"[{i}] NOT FOUND: {o[:30]}")

print("\ncheck:")
subprocess.run(["python3","/workspace/team/scripts/check_report.py",DOC,"--audience","boss"])
