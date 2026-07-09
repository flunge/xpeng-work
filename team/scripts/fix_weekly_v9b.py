#!/usr/bin/env python3
"""V9b: 清掉删车衣块后残留的空壳 XML（两个 cite + 空 ul/li）。用 XML 模式精准删。"""
import subprocess, json

DOC = "KtzLdBh3ToRFLYx5R66cpLiHnEk"

def rep_xml(old,new):
    r=subprocess.run(["lark-cli","docs","+update","--doc",DOC,"--command","str_replace",
                     "--pattern",old,"--content",new],  # 默认 XML 模式
                    capture_output=True,text=True)
    out=json.loads(r.stdout) if r.stdout.strip() else {}
    ok=out.get("ok",False)
    print(f"  ok={ok}" + ("" if ok else f"  err={out.get('error',{}).get('message','')[:150]}"))
    return ok

# 残留空壳：两个 cite + 空 ul。整段删除（替换为空）。
orphan = ('<cite type="user" user-id="ou_b41c33085d2e629fbdff0c555cae0a3f" user-name="杨星昊"></cite>'
          '<cite type="user" user-id="ou_16ed70882e5f4247b330612054b07d3f" user-name="王禹丁"></cite>'
          '<ul><li></li><li></li></ul><br/>')

print("[1] deleting orphan shell (XML mode)...")
rep_xml(orphan, "")

print("\ncheck:")
subprocess.run(["python3","/workspace/team/scripts/check_report.py",DOC,"--audience","boss"])
