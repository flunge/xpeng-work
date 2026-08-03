#!/usr/bin/env python3
"""Episode 事件流（L1 原始层）种子入库 + 元数据登记
- 表：Episode事件流 @ Base NkIZb7eU7azZIEsegJ7cl2bfnUd
- 首批数据来源：会议纪要机器人群 7/16-7/31 的 23 篇 docx（token + 主题 + 日期已由 7/23 fetch 得到）
- 后续该表由 ingest 脚本每日增量落行（会议纪要/日报/周报/IM 命中词/仓库 commit）
"""
import json, subprocess, sys

BASE = "NkIZb7eU7azZIEsegJ7cl2bfnUd"
TABLE = "Episode事件流"

# (时间, 主题, token, 涉及项目[逗号], 来源类型)
SEED = [
    ("2026-07-16 09:50", "智能纪要：仿真核心日会", "C2IKdf1z6oaR37xIwl3cYQXTnRc", "多项目", "会议纪要逐字稿"),
    ("2026-07-16 13:58", "智能纪要：WM 落地闭环仿真进展同步", "OVDvdGEOZov5WexKPrfcfLFenoc", "WM-内部探索", "会议纪要逐字稿"),
    ("2026-07-16 17:20", "智能纪要", "HzordPAopomh1MxPJSKcdQycnDh", "", "会议纪要逐字稿"),
    ("2026-07-17 10:19", "智能纪要", "NwLGdZoCqocXH5xGkCBcyv5Yn0f", "", "会议纪要逐字稿"),
    ("2026-07-17 18:38", "智能纪要", "Qt41dUC3wonOlPxpNGBcW5Dtngd", "", "会议纪要逐字稿"),
    ("2026-07-20 09:56", "智能纪要：仿真核心日会", "WjjfdZMEVo3QpTxEzl9cgmrdnXb", "多项目", "会议纪要逐字稿"),
    ("2026-07-20 17:54", "智能纪要：用户反馈讨论", "AjhkdiptFoClMKxIAMDchbQCnie", "极速模式", "会议纪要逐字稿"),
    ("2026-07-21 10:56", "智能纪要：26年晋升及组织盘点信息", "MhordqxJnobt67x7GjOcM8Smnmd", "组织/晋升", "会议纪要"),
    ("2026-07-21 18:58", "智能纪要：周二组会", "RxbgdW1DioeJdNxaT1RckRbXn8e", "慢速模式,车型泛化", "会议纪要逐字稿"),
    ("2026-07-22 09:54", "智能纪要：07-22仿真核心日会", "C8mrdphAPouHMHxCerRcHYB7nrd", "多项目", "会议纪要逐字稿"),
    ("2026-07-23 14:05", "智能纪要", "QPvVdPwxdoTSlyx8gOkcCtHQnwA", "", "会议纪要逐字稿"),
    ("2026-07-24 10:18", "智能纪要：仿真核心日会", "L4iedQPUloO7RwxiAbpc1ahYnch", "RTM,慢速模式", "会议纪要逐字稿"),
    ("2026-07-24 11:50", "智能纪要：晋升结果合议", "Xl72dakJFohzksx3CGhccBtnndd", "组织/晋升", "会议纪要"),
    ("2026-07-28 18:40", "智能纪要：周二组会", "RGHAd7NuJoJ2zjx8cfXctvmynqe", "慢速模式,CCES,车型泛化", "会议纪要逐字稿"),
    ("2026-07-29 09:56", "智能纪要：压测", "BRYAd4Edzo409VxHZJwcAK8gnDg", "", "会议纪要逐字稿"),
    ("2026-07-29 20:42", "智能纪要：聊天茶水间", "ZbGsdhZdhoYAYzxN0iBc6lMAnzg", "", "会议纪要逐字稿"),
    ("2026-07-30 12:13", "智能纪要", "XiPedLBLpoS6ucxV8BbcLzgcnMc", "", "会议纪要逐字稿"),
    ("2026-07-30 14:04", "智能纪要：WM 落地闭环仿真进展同步", "EZ5bdFrYaoXH9Mx3tXdcDKfDn1b", "WM-内部探索", "会议纪要逐字稿"),
    ("2026-07-30 17:22", "智能纪要：技术/算法交流", "C1Qmd5XRmosmyrxc4pvcw3JZnoh", "", "会议纪要逐字稿"),
    ("2026-07-30 18:37", "智能纪要：07-30仿真算法组周会", "Qrbddg6FSojpQqxk1Fac2NhfnFc", "慢速模式,HIL,Oncall", "会议纪要逐字稿"),
    ("2026-07-31 09:59", "智能纪要：仿真核心日会", "VzlVdSBb2oJFBtxvodgcww2Unre", "慢速模式,极速模式,车压测", "会议纪要逐字稿"),
    ("2026-07-31 17:04", "智能纪要：07-31 GIC仿真部双周会", "Cpnnd2ECzo4nzMxve3OcLVuNnof", "多项目", "会议纪要"),
    ("2026-07-31 18:54", "智能纪要：AI实习生③班开题报告", "Dm5ZdwiuToVJFRx6HJDc71mPnSd", "实习生", "会议纪要"),
]

def cli(*a):
    r = subprocess.run(["lark-cli","--profile","xpeng"]+list(a)+["--as","user"],
                       capture_output=True,text=True,timeout=300)
    try: return json.loads(r.stdout)
    except Exception: return {"ok": False, "raw": r.stdout[:300]}

rows = []
for t, title, tok, projs, src in SEED:
    url = f"https://xiaopeng.feishu.cn/docx/{tok}"
    rows.append([f"{title}（{tok[:8]}…)".replace("…",""), t, src, f"docx:{tok}", projs, "", "", "", url])
payload = {"fields":["事件摘要","时间","来源类型","来源定位","涉及项目","涉及人物","关键数字","动作","原文链接"],"rows":rows}
resp = cli("base","+record-batch-create","--base-token",BASE,"--table-id",TABLE,
           "--json",json.dumps(payload,ensure_ascii=False))
print("ok:",resp.get("ok"),str(resp.get("error",{}).get("message",""))[:200])
