#!/usr/bin/env python3
"""Episode 回填：从项目 ledger 的「持续进展」时间线反向喂 L1 事件流

目的：把 ledger 里本应只挂 L1 的逐日叙事/数字按时间逆推到 Episode 事件流，
让 storyline 主线卡的「②本周发生了什么」「③数字与证据」有细颗粒度来源。

用法：
  python3 team/scripts/backfill_episode_from_ledger.py \
      --ledger team/projects/车型泛化.md --project 车型泛化 [--dry-run]

核心规则：
  - 提取 ledger「三、持续进展」的 markdown 表格行（| 时间 | 作战表 | 会议纪要 | 其他 |）
  - 每行 = 1 条 Episode；时间取该 cell 日期；来源类型 / 原文链接 按单元格内容来源估计
  - 关键数字：抽 cell 里所有数字串（4 位以上数字/带单位/带 %），用分号拼
  - 涉及项目固定为 --project；来源定位 = "ledger://{token}#{date}" 幂等键（防重复入）
  - 该脚本为重跑幂等（先查 Episode 已有来源定位，跳过已存的）
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

BASE = "NkIZb7eU7azZIEsegJ7cl2bfnUd"
TABLE = "Episode事件流"
PROFILE = "xpeng"
# 幂等键前缀
SOURCE_PREFIX = "ledger://"

DATE_RE = re.compile(r"2026-\d{2}-\d{2}")
# 纯数字 4 位起或者 数字+单位（min/case/%/ms/卡/km/万/千）
NUM_RE = re.compile(
    r"(?:\d{4,}"
    r"|\d+(?:\.\d+)?\s*(?:min/case(?:/卡)?|ms|%|km|万|千|卡|元|大卡|千大卡|g)"
    r"|\d+\s*[:比]\s*\d+)"  # 1:34 1.35× 这类
)


def cli(args, timeout=180):
    r = subprocess.run(["lark-cli", "--profile", PROFILE] + args + ["--as", "user"],
                       capture_output=True, text=True, timeout=timeout)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"ok": False, "raw": (r.stdout or r.stderr)[:300]}


def existing_ledger_keys():
    """拉 Episode 表里已存在的以 ledger:// 开头的来源定位集合"""
    keys = set()
    offset = 0
    while True:
        d = cli(["base", "+record-list", "--base-token", BASE, "--table-id", TABLE,
                 "--limit", "500", "--offset", str(offset), "--format", "json"])
        if not d.get("ok"):
            break
        data = d.get("data", {})
        rows = data.get("data", [])
        fields = data.get("fields", [])
        if "来源定位" not in fields:
            break
        idx = fields.index("来源定位")
        for row in rows:
            if idx >= len(row):
                continue
            v = row[idx]
            if isinstance(v, str) and v.startswith(SOURCE_PREFIX):
                keys.add(v)
        if not data.get("has_more"):
            break
        offset += len(rows)
    return keys


def extract_num(s):
    nums = NUM_RE.findall(s)
    return "；".join(dict.fromkeys(nums)).strip("；")


def token_in_cell(cell):
    m = re.search(r"docx/([A-Za-z0-9]{20,})", cell)
    return m.group(1) if m else None


def cell_kind(cell):
    """返回 (来源类型, 摘要 action hint)"""
    cc = cell.replace(" ", "")
    if "作战表" in cc or "Q3作战表" in cc or "PDJ2" in cc:
        return "日报作战表", ""
    if "评审会" in cc or "纪要" in cc or "核心日会" in cc or "日会" in cc:
        return "会议纪要", ""
    return "IM群聊", ""


def parse_table(md_path):
    """输出行列表：[(date_str, 作战表cell, 纪要cell, 其他cell)]"""
    txt = Path(md_path).read_text(encoding="utf-8")
    # 找三、持续进展后面的表
    m = re.search(r"##\s*[三四]、[^\n]*\n(.*?)(?=\n##\s|\Z)", txt, re.S)
    if not m:
        return []
    body = m.group(1)
    out = []
    in_table = False
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("|") and ("时间" in line or "作战表" in line):
            in_table = True
            continue
        if not in_table or not line.startswith("|"):
            continue
        if re.match(r"^\|[-\s|:]+\|", line):  # 分隔线
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        date_cell = cells[0]
        mdate = DATE_RE.search(date_cell)
        if not mdate:
            continue
        out.append((mdate.group(0), cells[1], cells[2], cells[3] if len(cells) > 3 else ""))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True, help="ledger 文件相对 team/ 路径")
    ap.add_argument("--project", required=True, help="涉及项目标签")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    ledger_path = Path(args.ledger)
    if not ledger_path.is_absolute():
        ledger_path = Path(__file__).resolve().parent.parent / args.ledger
    if not ledger_path.exists():
        print(f"找不到 ledger: {ledger_path}")
        sys.exit(1)

    token = "MeLRd4JRTojlQ5xKsuWcqiYAnmd" if "车型泛化" in args.project else "UNKNOWN"
    url = f"https://xiaopeng.feishu.cn/docx/{token}"

    rows = parse_table(ledger_path)
    if not rows:
        print("未从持续进展表中抽出任何行；检查 ledger 结构。")
        sys.exit(1)
    print(f"[backfill] 抽出 {len(rows)} 段进展 (从 {rows[0][0]} 到 {rows[-1][0]})")

    have = existing_ledger_keys()
    print(f"[backfill] 已有 ledger:// 来源 Episode {len(have)} 条")

    new_rows = []
    dup = 0
    for date_str, c1, c2, c3 in rows:
        # 每行按 cell 拆分至多三条 Episode（作战表/纪要/其他 各取最大一条）
        for cell in (c1, c2, c3):
            if not cell or cell in ("—", "-"):
                continue
            kind, _ = cell_kind(cell)
            # 幂等键： ledger://token#date#cell_hash6
            cellhash = format(abs(hash(cell)) % (16 ** 6), '06x')
            key = f"{SOURCE_PREFIX}{token}#{date_str}#{cellhash}"
            if key in have:
                dup += 1
                continue
            nums = extract_num(cell)
            # 摘要按行第一个“：”切一段说明
            summary = cell.split("：", 1)[-1][:70] if "：" in cell else cell[:60]
            # 优先用 cell 内显式 docx token，否则退回项目 ledger
            tok = token_in_cell(cell) or token
            cell_url = f"https://xiaopeng.feishu.cn/docx/{tok}"
            new_rows.append([
                f"[{args.project}] {date_str} {kind}：{summary}",
                f"{date_str} 09:00",
                kind,
                key,
                args.project,
                "",
                nums,
                "",
                cell_url,
            ])
    print(f"[backfill] 新增 {len(new_rows)} 条，跳过重复 {dup} 条")
    if not new_rows:
        print("全部幂等已入，无需写库。")
        return
    if args.dry_run:
        for r in new_rows[:5]:
            print("  ", r[0][:120])
        return

    payload = {"fields": ["事件摘要", "时间", "来源类型", "来源定位", "涉及项目",
                          "涉及人物", "关键数字", "动作", "原文链接"],
               "rows": new_rows}
    resp = cli(["base", "+record-batch-create", "--base-token", BASE,
                "--table-id", TABLE, "--json", json.dumps(payload, ensure_ascii=False)])
    print(f"[backfill] 写库 ok={resp.get('ok')} err={str(resp.get('error',{}).get('message',''))[:300]}")
if __name__ == "__main__":
    main()
