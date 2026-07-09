#!/usr/bin/env python3
"""双周报 Topic4 修复：FMprompt 脑补数据(deepseek-v4/20训) + Prompt对齐脑补 83.3%。
真实源：复现率Agent ledger"FM提示词流程集成、40验证集准确率80%"；Prompt对齐源只有85%。"""
import subprocess, json
DOC="A42GdtJGMopqqBxhF2McE7v7n8c"

def fetch():
    r=subprocess.run(["lark-cli","docs","+fetch","--doc",DOC,"--doc-format","markdown","--format","json"],
                    capture_output=True,text=True)
    return json.loads(r.stdout).get("data",{}).get("document",{}).get("content","")
def rep(old,new,label=""):
    r=subprocess.run(["lark-cli","docs","+update","--doc",DOC,"--command","str_replace",
                     "--doc-format","markdown","--pattern",old,"--content",new],
                    capture_output=True,text=True)
    out=json.loads(r.stdout) if r.stdout.strip() else {}
    print(f"  {label} ok={out.get('ok',False)}"+("" if out.get('ok') else f" err={out.get('error',{}).get('message','')[:100]}"))
    return out.get("ok",False)

fixes=[
 # FMprompt: 删脑补的 deepseek-v4/20训, 用真实源"40验证集准确率80%"
 ("；FMprompt 复现率用 deepseek-v4 微调（20 训练 + 40 验证）单训练集达 80%。",
  "；FM 提示词复现流程已集成进 Agent、40 验证集准确率 80%。","FMprompt去脑补"),
 # Prompt对齐: 删脑补 83.3%
 ("Prompt 对齐 Agent 准确率 83.3%→冲 85%（解决 viewpoint 提示词开关 + 飞书机器人 HTML 输出）",
  "Prompt 对齐 Agent 人工一致率 85%（提示词开关 + 飞书机器人 HTML 输出已解决，与刘星昊对齐“卡严/高准确率/允许漏报”标准）","Prompt对齐去脑补83.3"),
]
c=fetch()
for old,new,label in fixes:
    if old in c: rep(old,new,label); c=fetch()
    else: print(f"  {label} NOT FOUND")
print("\ncheck:")
subprocess.run(["python3","/workspace/team/scripts/check_report.py",DOC,"--audience","xianming"])
