#!/usr/bin/env python3
"""Wiki G6I4w06n 嵌套文档 → Episode 事件流（L1）
只入 docx（跳过 bitable 二阶段小批量数据集），以 docx:{token} 为幂等键。
"""
import json, subprocess, sys
from datetime import datetime

BASE = "NkIZb7eU7azZIEsegJ7cl2bfnUd"
EPISODE = "tblV7t82iJwnPb85"
PROJECT = "车型泛化"

DOCS = {
    "Xrrtds7Troa6gaxaT6AcEofxncg": {
        "title": "仿真车型泛化验证报告",
        "time": "2026-05-01",
        "desc": "阶段1-5对线泛化：泛化渲染（4/30)、链路验证（5/9)、小批量验证（5/19)、批量生产验证（5/25)、正向分析+结论，引用原文米数",
    },
    "QgpHd0TByouegnxFqx7ci8REndc": {
        "title": "车型泛化仿真正向分析方案",
        "time": "2026-06-01",
        "desc": "正向分析序列：评论车桥错/不加速/不居中/超慢车/偏右，外参加扰动模拟个体差异，G02/D03 标定个案",
    },
    "KsV2d2LOtoY9wcxY6gxcB4t1nqT": {
        "title": "difix ref图模式优化",
        "time": "2026-06-01",
        "desc": "V1加同车型ref 6:4→V3加车身mask，新车型车身不再修回原车型（最终方案）",
    },
    "NEiKd7i3Bol9VyxLFm4c5G6NnLT": {
        "title": "7月车型泛化/SIL仿真/场景编辑/算法预研周目标",
        "time": "2026-07-01",
        "desc": "7月优先级：车型泛化最高→闭环+HIL第二，业务方 demanding",
    },
}

def cli(*args):
    r = subprocess.run(["lark-cli", "--profile", "xpeng"] + list(args) + ["--as", "user"],
                       capture_output=True, text=True, timeout=180)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"ok": False, "error": {"message": (r.stdout + r.stderr)[:300]}}

# 1. 读已有 Episode 来源定位，做幂等
existing = set()
offset = 0
while True:
    d = cli("base", "+record-list", "--base-token", BASE, "--table-id", EPISODE,
            "--limit", "200", "--offset", str(offset), "--format", "json")
    if not d.get("ok"):
        print("list fail:", d.get("error")); sys.exit(2)
    rows = d["data"].get("data", []); flds = d["data"].get("fields", [])
    idx = {n: i for i, n in enumerate(flds)}
    for row in rows:
        loc = str(row[idx["来源定位"]] or "")
        if loc:
            existing.add(loc)
    if not d["data"].get("has_more"):
        break
    offset += len(rows)
print(f"[check] 已有 {len(existing)} 条来源")

rows = []
now_ms = int(datetime.now().timestamp() * 1000)
for tok, info in DOCS.items():
    src = f"docx:{tok}"
    if src in existing:
        print(f"[skip] {info['title']} 已入")
        continue
    # 拉 revision_id
    d = cli("docs", "+fetch", "--doc", tok, "--doc-format", "markdown", "--scope", "full")
    rev = ((d.get("data") or {}).get("document") or {}).get("revision_id", 0)
    rows.append([
        info["title"],
        f"{info['time']}T00:00:00+08:00",
        info["title"],
        PROJECT,
        "会议纪要",           # 来源类型
        rev,
        "",                   # 关键数字（留给 storyline/filter 后提取）
        info["desc"],
        f"https://xiaopeng.feishu.cn/docx/{tok}",
        src,
        now_ms,
    ])

print(f"[plan] 待入库 {len(rows)} 条:")
for r in rows:
    print(f"  - {r[0]} | {r[1][:10]} | rev={r[5]}")

if not rows:
    sys.exit(0)

cols = ["事件摘要", "时间", "涉及项目", "来源类型", "来源定位", "关键数字", "动作", "原文链接"]
rows_out = []
for r in rows:
    rows_out.append([r[0], r[1], PROJECT, "会议纪要", r[9], "", r[7], r[8]])

payload = {"fields": cols, "rows": rows_out}
d = cli("base", "+record-batch-create", "--base-token", BASE, "--table-id", EPISODE,
        "--json", json.dumps(payload, ensure_ascii=False))
print("write ok:", d.get("ok"), (d.get("error") or {}).get("message", "")[:300])
