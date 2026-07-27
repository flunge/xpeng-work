#!/usr/bin/env python3
"""
每周一 08:00 执行（由 LaunchAgent 调度）：
读取 Q3-7月目标&进展 文档，更新周标题的"（本周）"标记。

逻辑：
1. 读取当前 ISO 周数
2. 在文档中查找所有 h3 标题中的 W{数字}
3. 去掉所有不是本周的 W{数字} 上的"（本周）"
4. 给本周的 W{数字} 加上"（本周）"

注：使用 replace_all 方式逐个替换，因为 W{数字} 在文档中唯一出现。
"""

import subprocess
import json
import re
import datetime
import sys

DOC_URL = "https://xiaopeng.feishu.cn/wiki/SBUYwm8Lri9aJ6kmexFcBAuGnlh"

def log(msg):
    print(f"[week-label] {msg}", flush=True)

def run_lark(args: list) -> dict:
    result = subprocess.run(
        ["lark-cli"] + args,
        capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        raise RuntimeError(f"lark-cli failed (exit {result.returncode}): {result.stderr}")
    return json.loads(result.stdout)

def get_current_week() -> int:
    return datetime.date.today().isocalendar()[1]

def main():
    iso_week = get_current_week()
    log(f"当前 ISO 周数: W{iso_week}")

    # 获取文档内容，提取所有 h3 标题
    doc_data = run_lark([
        "docs", "+fetch", "--api-version", "v2",
        "--doc", DOC_URL
    ])
    content = doc_data["data"]["document"]["content"]

    # 匹配 h3 中的 W{数字}（可能有（本周）后缀）
    # 如 <h3>W28（本周）</h3> 或 <h3>W29</h3> 或 <h3>W27（6/29-7/3）（本周）</h3>
    pattern = re.compile(r'<h3>(W(\d+)(（本周）)?(.*?))</h3>')

    updates = []
    for match in pattern.finditer(content):
        full_text = match.group(1)   # W28（本周） 或 W29 或 W27（6/29-7/3）
        week_num = int(match.group(2))
        has_this_week = match.group(3) == "（本周）"
        rest = match.group(4)        # 如 （6/29-7/3）

        target_tag = f"W{week_num}{rest}"

        if has_this_week and week_num == iso_week:
            log(f"✅ W{week_num} 已正确标记为本周")
        elif has_this_week and week_num != iso_week:
            new_tag = f"W{week_num}{rest}"
            updates.append((target_tag, new_tag))
            log(f"🔄 去除 W{week_num} 的（本周）")
        elif not has_this_week and week_num == iso_week:
            new_tag = f"W{week_num}（本周）{rest}"
            updates.append((target_tag, new_tag))
            log(f"🔄 给 W{week_num} 加上（本周）")

    if not updates:
        log("✅ 无需更新")
        return

    for old, new in updates:
        log(f"替换: '{old}' → '{new}'")
        result = run_lark([
            "docs", "+update", "--api-version", "v2",
            "--doc", DOC_URL,
            "--command", "str_replace",
            "--pattern", old,
            "--content", new,
        ])
        log(f"  结果: {result.get('result', 'ok')}")

    log("✅ 更新完成")

if __name__ == "__main__":
    main()
