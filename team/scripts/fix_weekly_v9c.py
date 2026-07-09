#!/usr/bin/env python3
"""V9c: 清掉车衣残留空壳（真实 XML 结构：<p>两cite</p><ul>两空li</ul>）。"""
import subprocess, json

DOC = "KtzLdBh3ToRFLYx5R66cpLiHnEk"

def fetch_xml():
    r=subprocess.run(["lark-cli","docs","+fetch","--doc",DOC,"--format","json"],
                    capture_output=True,text=True)
    return json.loads(r.stdout).get("data",{}).get("document",{}).get("content","")

def rep_xml(old,new):
    r=subprocess.run(["lark-cli","docs","+update","--doc",DOC,"--command","str_replace",
                     "--pattern",old,"--content",new],
                    capture_output=True,text=True)
    out=json.loads(r.stdout) if r.stdout.strip() else {}
    ok=out.get("ok",False)
    print(f"  ok={ok}" + ("" if ok else f"  err={out.get('error',{}).get('message','')[:150]}"))
    return ok

orphans = [
    # <p> 包着两个空 cite
    ('<p><cite type="user" user-id="ou_b41c33085d2e629fbdff0c555cae0a3f" user-name="杨星昊"></cite>'
     '<cite type="user" user-id="ou_16ed70882e5f4247b330612054b07d3f" user-name="王禹丁"></cite></p>'),
    # 空 ul
    '<ul><li></li><li></li></ul>',
]

c=fetch_xml()
for i,orphan in enumerate(orphans,1):
    if orphan in c:
        print(f"[{i}] deleting orphan...")
        rep_xml(orphan,"")
        c=fetch_xml()
    else:
        print(f"[{i}] NOT FOUND (raw): {orphan[:50]}")

print("\ncheck:")
subprocess.run(["python3","/workspace/team/scripts/check_report.py",DOC,"--audience","boss"])
