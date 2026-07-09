#!/usr/bin/env python3
"""V9: 删掉【车衣验证】整块——本周无正式进展（斑马/白色来自6/24茶水间非正式、pitch来自6/26 idea会，均为参考非进展）。"""
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
    ok=out.get("ok",False)
    print(f"  ok={ok}" + ("" if ok else f"  err={out.get('error',{}).get('message','')[:120]}"))
    return ok

# 删【车衣验证】的两个 bullet + 标题。逐段删（markdown 纯文本匹配）。
segments = [
    "进展：已验证斑马车衣致车辆不加速、白色车衣可达限速；侧前 pitch 1° 即影响加减速与居中。",
    "计划：泛化多种车衣样式纳入验证集，避免测试车/量产车差异。",
    "【车衣验证】",
]

c=fetch()
for i,seg in enumerate(segments,1):
    if seg in c:
        print(f"[{i}] deleting: {seg[:24]}...")
        rep(seg,"")
        c=fetch()
    else:
        print(f"[{i}] NOT FOUND: {seg[:24]}")

print("\ncheck:")
subprocess.run(["python3","/workspace/team/scripts/check_report.py",DOC,"--audience","boss"])
