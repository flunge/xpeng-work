#!/usr/bin/env python3
"""
PreToolUse hook：拦截写飞书文档的 lark-cli 命令，扫描内容里的 ASR 易错词。
命中则 exit 2 阻断，把命中清单反馈给模型，强制先清洗再写。

不依赖"我记得扫描"——harness 每次写飞书文档都强制跑本脚本。

也可命令行直接用：python3 asr_guard.py "<要检查的文本>"
"""

import sys
import json
import re

# ASR 易错词 → 标准词。键是正则（大小写不敏感），值是正确写法 + 说明。
# 与 weekly-report/SKILL.md 的对照表保持同步。
ASR_PATTERNS = [
    (r'黑友|黑耀|黑油', 'HIL（"HIL"读嗨欧被音译）'),
    (r'\bHEEL\b|\bHELL\b|\bHERA\b|\bHill\b|\bHail\b', 'HIL'),
    (r'\bSeal\b|\bSEAL\b', 'SIL（"SIL"读塞欧被听成 Seal）'),
    (r'\bAP8\b', 'FP8'),
    (r'\bAA Docker\b', 'AI Docker / agent Docker'),
]

# 命中后只警告、不阻断的"成对叫法"检测：同一文本里 HIL 与其错写变体同时出现
DUAL_NAMING = [
    (r'HIL', r'黑友|黑耀|黑油'),
    (r'SIL', r'\bSeal\b'),
]


def scan(text):
    """返回 (命中列表, 成对叫法列表)。"""
    hits = []
    for pat, correct in ASR_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            hits.append((m.group(0), correct))
    duals = []
    for std, wrong in DUAL_NAMING:
        if re.search(std, text) and re.search(wrong, text, re.IGNORECASE):
            duals.append((std, wrong))
    return hits, duals


def is_feishu_write(command):
    """是否是写飞书文档的命令（docs +create / +update）。"""
    if 'lark-cli' not in command:
        return False
    if 'docs' not in command:
        return False
    return '+create' in command or '+update' in command


def main():
    # Hook 模式：从 stdin 读 PreToolUse JSON
    raw = sys.stdin.read() if not sys.stdin.isatty() else ''
    command = ''
    if raw.strip():
        try:
            payload = json.loads(raw)
            command = payload.get('tool_input', {}).get('command', '')
        except (json.JSONDecodeError, AttributeError):
            command = raw
    elif len(sys.argv) > 1:
        command = ' '.join(sys.argv[1:])

    if not command:
        sys.exit(0)

    # 只在写飞书文档时检查
    if not is_feishu_write(command):
        sys.exit(0)

    hits, duals = scan(command)
    if not hits and not duals:
        sys.exit(0)

    msg = ['🚫 ASR 术语扫描命中——写飞书文档前必须先清洗（沉淀自 2026-06-29，已犯多次）：']
    seen = set()
    for word, correct in hits:
        key = word.lower()
        if key in seen:
            continue
        seen.add(key)
        msg.append(f'  • "{word}" → 应为 {correct}')
    for std, wrong in duals:
        msg.append(f'  • 同时出现「{std}」和它的错写变体，报告里不准两种叫法并存')
    msg.append('修正 content 后重试。若确认是别的项目代号而非 ASR 错词，请向用户确认。')

    print('\n'.join(msg), file=sys.stderr)
    sys.exit(2)  # exit 2 = 阻断并把 stderr 反馈给模型


if __name__ == '__main__':
    main()
