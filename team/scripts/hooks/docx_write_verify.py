#!/usr/bin/env python3
"""
PostToolUse hook：检测 lark-cli docs +update 的 block 级写操作后，强制提醒"写后必复查"。

背景：用失效 block id 做 block_replace/insert_after/delete 时，lark-cli 返回 ok:true 假象、
不报错，但文档实际没变（2026-06-30 同一坑踩两次）。规则光写不够，这里在每次 block 写操作后
主动把"不能信返回值、必须重新 fetch 复查内容真的变了"推到模型面前。

退出码语义（PostToolUse）：exit 2 = 把 stderr 作为 additionalContext 反馈给模型（非阻断，提示性）。
只对 block_replace / block_insert_after / block_delete 触发（这几个才有 id 失效风险）；
append / str_replace / create 不触发，避免噪音。
"""
import sys
import json
import re

RISKY = ("block_replace", "block_insert_after", "block_delete", "block_insert_before")


def main():
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    if not raw.strip():
        sys.exit(0)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    cmd = payload.get("tool_input", {}).get("command", "") or ""
    if "lark-cli" not in cmd or "docs" not in cmd or "+update" not in cmd:
        sys.exit(0)

    # 只对有 id 失效风险的 block 级命令触发
    hit = next((c for c in RISKY if c in cmd), None)
    if not hit:
        sys.exit(0)

    # 提取被操作的 block-id（仅用于提示文案，便于定位）
    m = re.search(r'--block-id\s+(\S+)', cmd)
    bid = m.group(1) if m else "<该 block>"
    m2 = re.search(r'--doc\s+(\S+)', cmd)
    doc = m2.group(1).strip('"') if m2 else "<doc>"

    msg = [
        f"⚠️ 刚执行了 docx {hit}（block {bid}）。lark-cli 对失效 id 会返回 ok:true 假象、不报错。",
        f"必须立刻 fetch 复查内容真的变了，不要信返回值：",
        f"  lark-cli docs +fetch --api-version v2 --doc {doc} --scope section --detail with-ids --format json",
        f"提醒：block_replace 后该块自身 id 也会变；若还要在它附近 insert/replace，先重新 fetch 拿新 id，绝不复用旧 id。",
    ]
    print("\n".join(msg), file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
