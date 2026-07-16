#!/usr/bin/env python3
"""
每日 9:00 项目风险播报
读取 memory/projects/**/ledger.md，提取风险/卡点，推送到飞书 Webhook
"""

import json
import os
import re
import subprocess
from datetime import date
from pathlib import Path

# 推送目标：与机器人(cli_aaad7e4c46f95bb4)的单聊会话（已弃用旧群 webhook）
DM_CHAT = "oc_bc5bb378d432fca62a7786e26cf82578"
# 相对脚本定位：scripts/ 的上一级即项目根（team/）
BASE_DIR = Path(__file__).resolve().parent.parent
PROJECTS_DIR = BASE_DIR / "memory" / "projects"
LOG_FILE = BASE_DIR / "memory" / "daily-sync" / "risk-push.log"


def parse_frontmatter(text: str) -> dict:
    """解析 YAML frontmatter"""
    meta = {}
    if not text.startswith("---"):
        return meta
    end = text.find("\n---", 3)
    if end == -1:
        return meta
    block = text[3:end]
    for line in block.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return meta


def extract_risks(text: str) -> list[str]:
    """提取所有风险/卡点行（包括紧跟的缩进子项）"""
    risks = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        # 匹配含有风险标志的行（🔴/🟡/⚠️/delay/blocked）
        if re.search(r"🔴|🟡|⚠️", line):
            risk_block = [line.rstrip()]
            # 收集缩进续行
            j = i + 1
            while j < len(lines) and lines[j].startswith("  ") and lines[j].strip():
                risk_block.append(lines[j].rstrip())
                j += 1
            risks.append("\n".join(risk_block))
            i = j
        else:
            i += 1
    return risks


def extract_monthly_target(text: str) -> str:
    """提取"当前状态"或"月度目标"中第一行有效内容作为摘要"""
    match = re.search(
        r"## 当前状态[^\n]*\n((?:(?!##).)+)",
        text,
        re.DOTALL,
    )
    if not match:
        return ""
    block = match.group(1).strip()
    # 取前两条非空 bullet（跳过已作为风险单独展示的🔴/🟡/⚠️行）
    bullets = [
        l.strip()
        for l in block.splitlines()
        if l.strip().startswith("-") and not re.search(r"🔴|🟡|⚠️", l)
    ]
    return " | ".join(bullets[:2])


# 日报表格中的 track 顺序（与 W11 表格行顺序一致）
TRACK_ORDER = ["场景&生产", "SIL", "HIL", "Agents"]


def collect_project_risks() -> list[dict]:
    """遍历所有 ledger.md，返回有风险的项目列表（按日报表格顺序）"""
    results = []
    for ledger in sorted(PROJECTS_DIR.rglob("ledger.md")):
        text = ledger.read_text(encoding="utf-8")
        meta = parse_frontmatter(text)
        status = meta.get("status", "active")
        if status == "archived":
            continue

        risks = extract_risks(text)
        if not risks:
            continue

        # 从路径推断 track/project 名
        parts = ledger.parts
        idx = parts.index("projects")
        track = parts[idx + 1] if idx + 1 < len(parts) else "?"
        project = parts[idx + 2] if idx + 2 < len(parts) else ledger.parent.name

        results.append(
            {
                "track": track,
                "project": project,
                "owner": meta.get("owner", "—"),
                "risks": risks,
                "summary": extract_monthly_target(text),
            }
        )

    # 按日报表格 track 顺序排序，track 内按项目名字母序
    def sort_key(p):
        try:
            ti = TRACK_ORDER.index(p["track"])
        except ValueError:
            ti = len(TRACK_ORDER)
        return (ti, p["project"])

    results.sort(key=sort_key)
    return results


def build_feishu_message(projects: list[dict]) -> dict:
    """构建飞书 post 格式消息"""
    today = date.today().strftime("%Y-%m-%d")
    red_count = sum(
        1
        for p in projects
        for r in p["risks"]
        if "🔴" in r
    )
    yellow_count = sum(
        1
        for p in projects
        for r in p["risks"]
        if "🟡" in r and "🔴" not in r
    )

    # 标题行
    title = f"📋 项目风险播报 {today}  🔴×{red_count} 🟡×{yellow_count}"

    content_blocks = []

    for p in projects:
        # 项目标题行（不加 style 字段，飞书 post webhook 不支持）
        content_blocks.append(
            [{"tag": "text", "text": f"【{p['track']} / {p['project']}】  负责人：{p['owner']}"}]
        )
        # 当前状态摘要
        if p["summary"]:
            content_blocks.append(
                [{"tag": "text", "text": f"  ↳ {p['summary']}"}]
            )
        # 风险条目
        for risk in p["risks"]:
            first_line = risk.splitlines()[0]
            content_blocks.append([{"tag": "text", "text": f"  {first_line}"}])
            for sub in risk.splitlines()[1:]:
                if sub.strip():
                    content_blocks.append(
                        [{"tag": "text", "text": f"    {sub.strip()}"}]
                    )
        # 分隔空行
        content_blocks.append([{"tag": "text", "text": ""}])

    if not content_blocks:
        content_blocks.append([{"tag": "text", "text": "✅ 当前无🔴/🟡级风险"}])

    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": content_blocks,
                }
            }
        },
    }


def push(payload: dict):
    """通过 app 机器人(cli_aaad...)把风险播报发到单聊 DM_CHAT（post 富文本）。"""
    post_content = payload["content"]["post"]  # {"zh_cn": {...}}
    content_json = json.dumps(post_content, ensure_ascii=False)
    r = subprocess.run(
        ["lark-cli", "im", "+messages-send", "--as", "bot",
         "--chat-id", DM_CHAT, "--msg-type", "post", "--content", content_json],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        raise RuntimeError(f"lark-cli send failed: {(r.stderr or r.stdout).strip()[:200]}")
    return (r.stdout or "").strip()[:120]


def log(msg: str):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    timestamp = date.today().isoformat()
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {msg}\n")


def main():
    try:
        projects = collect_project_risks()
        payload = build_feishu_message(projects)
        resp = push(payload)
        log(f"OK — {len(projects)} projects with risks — resp: {resp[:120]}")
        print(f"推送成功，共 {len(projects)} 个项目有风险")
    except Exception as e:
        log(f"ERROR — {e}")
        raise


if __name__ == "__main__":
    main()
